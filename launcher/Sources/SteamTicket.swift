import AppKit

// A ticket is kept only in memory, through validated game handoff. It is never
// a preference, Keychain item, command-line argument, or diagnostic field.
final class SteamAuthorization: @unchecked Sendable {
    let userID: UInt64
    private(set) var ticket: Data
    private let release: () -> Void
    init(userID: UInt64, ticket: Data, release: @escaping () -> Void = {}) throws {
        guard userID > 0, !ticket.isEmpty, ticket.count <= 2560 else {
            throw LauncherError.message("Steam returned an invalid ticket. Sign in to Steam and retry Play.")
        }
        self.userID = userID; self.ticket = ticket; self.release = release
    }
    deinit { ticket.wipe(); release() }
}

struct SteamTicketSource {
    let acquire: (CancellationToken) throws -> SteamAuthorization
    static let macOS = SteamTicketSource { try MacSteamClient().authorize(token: $0) }
}

struct MacSteamClient {
    static func failure(_ code: Int32) -> LauncherError {
        switch code {
        case -1: return .message("Update or reinstall the macOS Steam client, then retry Steam Play.")
        case -3: return .message("Sign in to Steam and go online, then retry Steam Play.")
        case -4: return .message("Add Wizard101 to this Steam account’s library, then retry Steam Play.")
        case -5: return .message("Steam could not issue a Wizard101 ticket. Check Steam’s connection and retry Play.")
        case -6: return .message("Another Steam sign-in is in progress. Wait for it to finish, then retry Play.")
        default: return .message("Sign in to the macOS Steam client and make sure Wizard101 is in your library, then retry Steam Play.")
        }
    }
    static func library(in app: URL) -> URL? {
        ["Contents/Frameworks/Steam Helper.app/Contents/MacOS/libsteam_api.dylib",
         "Contents/MacOS/Frameworks/Steam Helper.app/Contents/MacOS/libsteam_api.dylib",
         "Contents/MacOS/libsteam_api.dylib"].map { app.appendingPathComponent($0) }
            .first { FileManager.default.fileExists(atPath: $0.path) }
    }
    static func applications(registered: URL?, home: URL) -> [URL] {
        [registered, URL(fileURLWithPath: "/Applications/Steam.app"),
         home.appendingPathComponent("Applications/Steam.app"),
         home.appendingPathComponent("Library/Application Support/Steam/Steam.AppBundle/Steam")].compactMap { $0 }
    }
    static func library(in applications: [URL]) -> URL? {
        // /Applications/Steam.app is commonly only a bootstrapper. Its running
        // client and API live in Application Support, under the same bundle ID.
        applications.lazy.compactMap { library(in: $0) }.first
    }
    private var applications: [URL] {
        Self.applications(registered: NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.valvesoftware.steam"),
                          home: FileManager.default.homeDirectoryForCurrentUser)
    }
    func authorize(token: CancellationToken) throws -> SteamAuthorization {
        try token.check()
        guard let app = applications.first(where: { FileManager.default.fileExists(atPath: $0.appendingPathComponent("Contents/Info.plist").path) }) else {
            throw LauncherError.message("Install the macOS Steam client from store.steampowered.com, sign in, and add Wizard101 to your library. Then retry Steam Play.")
        }
        // Start Steam through LaunchServices; never start a second Wine Steam
        // installation or request the user's Steam password in this form.
        let completed = DispatchSemaphore(value: 0)
        let result = SteamOpenResult()
        DispatchQueue.main.async {
            let configuration = NSWorkspace.OpenConfiguration(); configuration.activates = true
            NSWorkspace.shared.openApplication(at: app, configuration: configuration) { _, error in
                result.failed = error != nil; completed.signal()
            }
        }
        let deadline = Date().addingTimeInterval(25)
        while completed.wait(timeout: .now() + 0.1) == .timedOut {
            try token.check()
            guard Date() < deadline else { throw Self.failure(-2) }
        }
        try token.check()
        guard !result.failed else { throw Self.failure(-2) }
        guard let library = Self.library(in: [app] + applications) else { throw Self.failure(-1) }
        var context: OpaquePointer?
        let opened = w101_steam_open(library.path, &context)
        guard opened == 0, let context else { throw Self.failure(opened) }
        var retained = false
        defer { if !retained { w101_steam_close(context) } }
        var bytes = Data(count: 2560); defer { bytes.wipe() }
        while true {
            try token.check()
            var user: UInt64 = 0, length = 0
            let status = bytes.withUnsafeMutableBytes {
                w101_steam_poll(context, &user, $0.bindMemory(to: UInt8.self).baseAddress, $0.count, &length)
            }
            if status < 0 { throw Self.failure(status) }
            if status == 1 {
                let authorization = try SteamAuthorization(userID: user, ticket: Data(bytes.prefix(length)), release: { w101_steam_close(context) })
                retained = true; try token.check(); return authorization
            }
            guard Date() < deadline else {
                throw LauncherError.message("Steam did not return a ticket in time. Go online in Steam and retry Play.")
            }
            Thread.sleep(forTimeInterval: 0.1)
        }
    }
}

private final class SteamOpenResult: @unchecked Sendable {
    // Published by the semaphore before the worker reads it.
    var failed = false
}
