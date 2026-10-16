import Foundation

func runAccountTests(check: (Bool, String) throws -> Void, rejects: (String, () throws -> Void) throws -> Void) throws {
    let suite = "org.wizard101native.accounts.test." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let preferences = AccountPreferences(defaults: defaults)
    try check(preferences.provider == .us, "Existing and fresh users default to US")
    defaults.set("legacy-user", forKey: "username")
    defaults.set(true, forKey: "savePassword")
    try check(preferences.username(for: .us) == "legacy-user" && preferences.remembersPassword(for: .us), "Legacy credentials and remember preference stay assigned to US")
    try check(preferences.username(for: .steam).isEmpty && !preferences.remembersPassword(for: .steam), "Steam never inherits legacy credentials")
    try check(AccountProvider.us.keychainService == PasswordStore().service && AccountProvider.steam.keychainService != AccountProvider.us.keychainService, "US Keychain namespace remains compatible and Steam is separate")
    preferences.provider = .steam
    preferences.save(username: "same-name", remember: true, for: .steam)
    preferences.save(username: "same-name", remember: false, for: .us)
    let reloaded = AccountPreferences(defaults: UserDefaults(suiteName: suite)!)
    try check(reloaded.provider == .steam && reloaded.username(for: .steam) == "same-name" && reloaded.remembersPassword(for: .steam), "Provider and Steam credentials survive restart")
    try check(reloaded.username(for: .us) == "same-name" && !reloaded.remembersPassword(for: .us), "Identical usernames have independent password preferences")
    preferences.save(username: "another-steam-user", remember: false, for: .steam)
    try check(preferences.username(for: .us) == "same-name" && !preferences.remembersPassword(for: .us), "Editing Steam preferences leaves US preferences intact")
    defaults.set("invalid-provider", forKey: "account.provider")
    try check(preferences.provider == .us, "Invalid saved provider falls back to US")
    let steamHome = FileManager.default.temporaryDirectory.appendingPathComponent("w101-steam-layout-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: steamHome) }
    let bootstrap = steamHome.appendingPathComponent("Applications/Steam.app")
    let client = steamHome.appendingPathComponent("Library/Application Support/Steam/Steam.AppBundle/Steam")
    let library = client.appendingPathComponent("Contents/MacOS/Frameworks/Steam Helper.app/Contents/MacOS/libsteam_api.dylib")
    try FileManager.default.createDirectory(at: bootstrap.appendingPathComponent("Contents"), withIntermediateDirectories: true)
    try FileManager.default.createDirectory(at: library.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data().write(to: bootstrap.appendingPathComponent("Contents/Info.plist"))
    try Data().write(to: library)
    try check(MacSteamClient.library(in: bootstrap) == nil && MacSteamClient.library(in: [bootstrap, client]) == library,
              "Steam bootstrapper resolves the running client's separate Application Support library")
    let locations = MacSteamClient.applications(registered: bootstrap, home: steamHome)
    try check(locations.first?.path == bootstrap.path && locations.contains(where: { $0.path == client.path }), "Registered Steam bootstrapper does not hide the client installation")
    let modern = steamHome.appendingPathComponent("ModernSteam.app/Contents/Frameworks/Steam Helper.app/Contents/MacOS/libsteam_api.dylib")
    try FileManager.default.createDirectory(at: modern.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data().write(to: modern)
    try check(MacSteamClient.library(in: steamHome.appendingPathComponent("ModernSteam.app")) == modern,
              "Steam library discovery supports the current Frameworks layout")
    let rawTicket = Data([0, 255, 128, 65, 0, 66])
    let steam = try SteamAuthorization(userID: 76561198000000001, ticket: rawTicket)
    for provider in AccountProvider.allCases {
        let wire = try LoginRequest.authentication(credential: Data("ENCRYPTED-FIXTURE".utf8), clientID: "fixture-client",
                                                    provider: provider, steam: provider == .steam ? steam : nil)
        var reader = BinaryReader(data: wire)
        try check(try reader.blob() == Data("ENCRYPTED-FIXTURE".utf8), "\(provider.title) request keeps encrypted credential record")
        for _ in 0..<4 { try check(try reader.string().isEmpty, "\(provider.title) official version defaults") }
        try check(try reader.integer(UInt64.self) == 0 && reader.string() == "en-US" && reader.string() == "fixture-client", "\(provider.title) machine, locale and installation identity")
        try check(try reader.integer(UInt32.self) == (provider == .steam ? 1 : 0) && reader.integer(UInt8.self) == 0 && reader.string().isEmpty, "\(provider.title) provider flag and desktop platform encoding")
        try check(try reader.string() == (provider == .steam ? "76561198000000001" : "0"), "\(provider.title) request sends matching Steam identity")
        try check(try reader.blob() == (provider == .steam ? rawTicket : Data()), "\(provider.title) raw Steam ticket preserves binary bytes and embedded NULs")
        try reader.end()
    }
    try rejects("Steam request cannot omit the ticket") { _ = try LoginRequest.authentication(credential: Data(), clientID: "fixture", provider: .steam, steam: nil) }
    try rejects("US request cannot carry Steam identity or ticket") { _ = try LoginRequest.authentication(credential: Data(), clientID: "fixture", provider: .us, steam: steam) }
    try rejects("Empty Steam ticket is rejected") { _ = try SteamAuthorization(userID: steam.userID, ticket: Data()) }
    try rejects("Oversized Steam ticket is rejected") { _ = try SteamAuthorization(userID: steam.userID, ticket: Data(count: 2561)) }
    var session = GameSession(userID: 123, passKey: "SYNTHETIC-SESSION", expires: Date().addingTimeInterval(120), provider: .steam)
    try rejects("Session validation cannot cross providers") { _ = try LoginRequest.validation(session: session, provider: .us, key: "fixture-key", clientID: "fixture") }
    var validation = BinaryReader(data: try LoginRequest.validation(session: session, provider: .steam, key: "fixture-key", clientID: "fixture"))
    try check(try validation.integer(UInt64.self) == 123 && validation.string() == "fixture-key" && validation.integer(UInt64.self) == 0 && validation.string() == "en-US" && validation.string() == "fixture" && validation.string().isEmpty,
              "Steam revalidation uses the KingsIsle session without re-sending credentials or ticket")
    try validation.end()
    let testPaths = PortablePaths(resources: URL(fileURLWithPath: "/synthetic/resources"), environment: ["W101_DATA_ROOT": "/synthetic/data"])
    var launch = LaunchPlan(paths: testPaths, mode: .capped, profile: false, environment: ["SteamAppId": "799960", "SteamGameId": "799960"])
    launch.session = session
    try rejects("Game launch rejects a session from the other provider") { try launch.validateSession() }
    launch.provider = .steam; try launch.validateSession()
    let steamArguments = launch.arguments, steamEnvironment = launch.childEnvironment
    launch.provider = .us; session.provider = .us; launch.session = session
    try check(launch.arguments == steamArguments && !steamArguments.contains("-ST"), "Both providers hand off validated sessions through the same direct game command")
    try check(launch.childEnvironment == steamEnvironment && steamEnvironment["SteamAppId"] == nil && steamEnvironment["SteamGameId"] == nil,
              "Switching providers preserves game folder, rendering, settings and pacing environment")
    var calls = 0
    let rejectedSource = SteamTicketSource { _ in calls += 1; throw MacSteamClient.failure(-3) }
    let usAuth = NativeAuthentication(base: testPaths.game, provider: .us, steamTickets: rejectedSource)
    try check(try usAuth.authorization(token: CancellationToken()) == nil && calls == 0, "US sign-in never starts or queries Steam")
    let steamAuth = NativeAuthentication(base: testPaths.game, provider: .steam, steamTickets: rejectedSource)
    try rejects("Steam ticket failure stops sign-in without another provider retry") { _ = try steamAuth.authorization(token: CancellationToken()) }
    try check(calls == 1, "Steam ticket request has no automatic account fallback")
    let cancelled = CancellationToken(); cancelled.cancel()
    do { _ = try steamAuth.authorization(token: cancelled); throw LauncherError.message("Cancelled Steam sign-in proceeded") }
    catch is CancellationError { try check(calls == 1, "Cancellation stops before Steam or credentials are touched") }
    let duringTicket = CancellationToken()
    var released = false
    let cancellingSource = SteamTicketSource { token in
        token.cancel()
        return try SteamAuthorization(userID: steam.userID, ticket: rawTicket, release: { released = true })
    }
    let cancellingAuth = NativeAuthentication(base: testPaths.game, provider: .steam, steamTickets: cancellingSource)
    do { _ = try cancellingAuth.authorization(token: duringTicket); throw LauncherError.message("Cancelled ticket was accepted") }
    catch is CancellationError { try check(released, "Cancellation during ticket acquisition releases the ticket before sending credentials") }
    try rejects("Cancelled US sign-in stops before opening a network connection") { _ = try usAuth.signIn(username: "fixture", password: "fixture", token: cancelled) }
    for provider in AccountProvider.allCases {
        var fields = Data(); fields.put(Int32(2)); fields.put(UInt64(123)); try fields.putBlob(Data("fixture-key".utf8))
        try fields.putString("SECRET-ECHO"); try fields.putString(""); fields.put(Int32(0)); fields.put(Int32(0)); try fields.putString(""); try fields.putString("")
        do { _ = try AuthenticationResponse.parse(.message(service: 7, type: 14, fields: fields), provider: provider); throw LauncherError.message("Rejected credentials accepted") }
        catch { try check(error.localizedDescription.hasPrefix(provider.title + " sign-in was rejected") && !error.localizedDescription.contains("SECRET-ECHO"), "\(provider.title) rejected credentials stay in the selected provider without echoing server secrets") }
    }
    if CommandLine.arguments.contains("--keychain-test") {
        // Real Keychain round trip, using disposable services and synthetic values.
        let scope = "local.wizard101.native-launcher.test." + UUID().uuidString
        let us = PasswordStore(service: scope + ".US"), steam = PasswordStore(service: scope + ".Steam")
        defer { try? us.remove(account: "same-name"); try? steam.remove(account: "same-name") }
        try us.save(account: "same-name", password: "SYNTHETIC-US")
        try check(try steam.load(account: "same-name") == nil, "Steam cannot read a US Keychain password")
        try steam.save(account: "same-name", password: "SYNTHETIC-STEAM")
        try check(try us.load(account: "same-name") == "SYNTHETIC-US" && steam.load(account: "same-name") == "SYNTHETIC-STEAM", "Same username stores different passwords in each provider")
        try steam.save(account: "same-name", password: "UPDATED-STEAM")
        try steam.remove(account: "same-name"); try steam.remove(account: "same-name")
        try check(try us.load(account: "same-name") == "SYNTHETIC-US" && steam.load(account: "same-name") == nil, "Forgetting Steam password preserves US and is idempotent")
    }
}
