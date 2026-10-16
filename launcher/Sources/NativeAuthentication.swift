import Foundation
import Security

final class PasswordStore: Sendable {
    let service: String
    init(service: String = "local.wizard101.native-launcher.US") { self.service = service }
    private func query(_ account: String) -> [CFString: Any] {
        [kSecClass: kSecClassGenericPassword, kSecAttrService: service,
         kSecAttrAccount: account, kSecAttrSynchronizable: false]
    }
    func load(account: String) throws -> String? {
        var q = query(account); q[kSecReturnData] = true; q[kSecMatchLimit] = kSecMatchLimitOne
        var value: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &value)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = value as? Data, let password = String(data: data, encoding: .utf8) else {
            throw LauncherError.message("Keychain could not read this saved password. Enter it locally or try again.")
        }
        return password
    }
    func save(account: String, password: String) throws {
        let attributes: [CFString: Any] = [kSecValueData: Data(password.utf8), kSecAttrAccessible: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let q = query(account)
        var status = SecItemUpdate(q as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound { status = SecItemAdd(q.merging(attributes) { _, new in new } as CFDictionary, nil) }
        guard status == errSecSuccess else { throw LauncherError.message("Keychain could not save the password. Sign-in can be retried without saving.") }
    }
    func remove(account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw LauncherError.message("Keychain could not remove the saved password. Try again.") }
    }
}

struct LoginSchema {
    struct Field: Equatable { let name: String; let type: String }
    static let authFields: [Field] = [Field(name: "Rec1", type: "STR"), Field(name: "Version", type: "STR"), Field(name: "Revision", type: "STR"), Field(name: "DataRevision", type: "STR"), Field(name: "CRC", type: "STR"), Field(name: "MachineID", type: "GID"), Field(name: "Locale", type: "STR"), Field(name: "PatchClientID", type: "STR"), Field(name: "IsSteamPatcher", type: "UINT"), Field(name: "ConsoleType", type: "UBYT"), Field(name: "PlatformChatID", type: "STR"), Field(name: "SteamID", type: "STR"), Field(name: "SteamAuthTicket", type: "STR")]
    static let responseFields: [Field] = [Field(name: "Error", type: "INT"), Field(name: "UserID", type: "GID"), Field(name: "Rec1", type: "STR"), Field(name: "Reason", type: "STR"), Field(name: "TimeStamp", type: "STR"), Field(name: "PayingUser", type: "INT"), Field(name: "Flags", type: "INT"), Field(name: "SupportID", type: "STR"), Field(name: "PublicPlayerName", type: "STR")]
    static let validationFields: [Field] = [Field(name: "UserID", type: "GID"), Field(name: "PassKey3", type: "STR"), Field(name: "MachineID", type: "GID"), Field(name: "Locale", type: "STR"), Field(name: "PatchClientID", type: "STR"), Field(name: "PlatformChatID", type: "STR")]
    static let validationResponseFields: [Field] = [Field(name: "Error", type: "INT"), Field(name: "Reason", type: "STR"), Field(name: "UserID", type: "GID"), Field(name: "TimeStamp", type: "STR"), Field(name: "PayingUser", type: "INT"), Field(name: "Flags", type: "INT"), Field(name: "SupportID", type: "STR")]
    static func verify(_ url: URL) throws {
        let delegate = DefinitionReader()
        let parser = XMLParser(data: try Data(contentsOf: url)); parser.delegate = delegate; parser.shouldResolveExternalEntities = false
        guard parser.parse(), delegate.service == 7, delegate.version == 1,
              delegate.orders["MSG_USER_AUTHEN_V3"] == 27, delegate.orders["MSG_USER_AUTHEN_RSP"] == 14,
              delegate.fields["MSG_USER_AUTHEN_V3"] == authFields, delegate.fields["MSG_USER_AUTHEN_RSP"] == responseFields,
              delegate.orders["MSG_USER_VALIDATE"] == 15, delegate.orders["MSG_USER_VALIDATE_RSP"] == 16,
              delegate.fields["MSG_USER_VALIDATE"] == validationFields,
              delegate.fields["MSG_USER_VALIDATE_RSP"] == validationResponseFields else {
            throw LauncherError.message("The installed login definitions use an unsupported protocol version.")
        }
    }
    private final class DefinitionReader: NSObject, XMLParserDelegate {
        var service: Int?, version: Int?, orders: [String: Int] = [:], fields: [String: [Field]] = [:]
        private var stack: [String] = [], text = ""
        func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName: String?, attributes: [String: String]) {
            stack.append(name); text = ""
            if stack.count == 4, stack[1].hasPrefix("MSG_"), attributes["NOXFER"] != "TRUE", let type = attributes["TYPE"] {
                fields[stack[1], default: []].append(Field(name: name, type: type))
            }
        }
        func parser(_ parser: XMLParser, foundCharacters string: String) { text += string }
        func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName: String?) {
            if name == "ServiceID" { service = Int(text) }
            if name == "ProtocolVersion" { version = Int(text) }
            if name == "_MsgOrder", stack.count == 4 { orders[stack[1]] = Int(text) }
            stack.removeLast(); text = ""
        }
    }
}

struct AuthenticationResponse {
    let userID: UInt64
    let encryptedKey: Data
    static func parse(_ frame: KIFrame, provider: AccountProvider = .us) throws -> AuthenticationResponse {
        guard !frame.control else { throw LauncherError.message("The account server interrupted sign-in. Try again.") }
        var reader = BinaryReader(data: frame.payload)
        guard try reader.integer(UInt8.self) == 7, try reader.integer(UInt8.self) == 14,
              Int(try reader.integer(UInt16.self)) == frame.payload.count else { throw LauncherError.message("Unsupported authentication response.") }
        let error = try reader.integer(Int32.self), id = try reader.integer(UInt64.self), key = try reader.blob()
        let reason = AuthenticationFailure.Reason(serverReason: try reader.blob())
        _ = try reader.blob(); _ = try reader.integer(Int32.self); _ = try reader.integer(Int32.self)
        _ = try reader.blob(); _ = try reader.blob(); try reader.end()
        guard error == 0 else { throw AuthenticationFailure(provider: provider, code: error, reason: reason, stage: .authentication) }
        guard id != 0, !key.isEmpty, key.count <= 512 else { throw LauncherError.message("The account server returned an invalid session.") }
        return AuthenticationResponse(userID: id, encryptedKey: key)
    }
}

struct SessionValidationResponse {
    static func validate(_ frame: KIFrame, userID: UInt64, provider: AccountProvider = .us) throws {
        guard !frame.control else { throw LauncherError.message("The account server interrupted session verification. Sign in again.") }
        var reader = BinaryReader(data: frame.payload)
        guard try reader.integer(UInt8.self) == 7, try reader.integer(UInt8.self) == 16,
              Int(try reader.integer(UInt16.self)) == frame.payload.count else {
            throw LauncherError.message("Unsupported session verification response.")
        }
        let error = try reader.integer(Int32.self)
        let reason = AuthenticationFailure.Reason(serverReason: try reader.blob())
        let id = try reader.integer(UInt64.self)
        _ = try reader.blob(); _ = try reader.integer(Int32.self); _ = try reader.integer(Int32.self)
        _ = try reader.blob(); try reader.end()
        guard error == 0 else { throw AuthenticationFailure(provider: provider, code: error, reason: reason, stage: .validation) }
        guard userID != 0, id == userID else { throw LauncherError.message("The account server returned an invalid session identity. Sign in again.") }
    }
}

struct GameSession: Sendable {
    let userID: UInt64
    let passKey: String
    let expires: Date
    var provider: AccountProvider = .us
    var steamAuthorization: SteamAuthorization? = nil
    func validateFormat() throws {
        guard userID > 0, !passKey.isEmpty, passKey.utf8.count <= 255,
              passKey.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=_-.").contains($0) }) else {
            throw LauncherError.message("The sign-in session expired or is invalid. Sign in again.")
        }
    }
    func validate(at date: Date = Date()) throws {
        try validateFormat()
        guard date < expires else { throw LauncherError.message("The sign-in session expired. Sign in again.") }
    }
}

struct NativeAuthentication {
    let base: URL
    var provider: AccountProvider = .us
    var steamTickets: SteamTicketSource = .macOS
    // Verified against the live signed server offer, complete GCM tags, and an
    // authenticated rejection for a random nonexistent diagnostic identity.
    static let encryptedHandshakeVerified = true
    func signIn(username: String, password: String, token: CancellationToken) throws -> GameSession {
        // No preference, environment variable or diagnostic can authorize a real account.
        guard Self.encryptedHandshakeVerified else { throw LauncherError.message("Encrypted native sign-in is not yet verified. No credentials were sent.") }
        return try authenticate(username: username, password: password, token: token)
    }
    private func authenticate(username: String, password: String, token: CancellationToken) throws -> GameSession {
        try token.check()
        guard !username.isEmpty, !password.isEmpty, username.utf8.count <= 100,
              !username.contains(where: { $0.isWhitespace }), password.utf8.count <= 255 else {
            throw LauncherError.message("Enter your username and password locally.")
        }
        try LoginSchema.verify(base.appendingPathComponent("PatchClient/BankB/LoginMessages.xml"))
        return try withAuthorization(token: token) { steam in
            let connection = try KIConnection(host: "login.us.wizard101.com", port: 12000, token: token)
            defer { connection.close() }
            let encrypted = try NativeEncryptedSession(connection: connection, game: base.appendingPathComponent("Bin/WizardGraphicalClient.exe"), token: token)
            try encrypted.verifyTransport()
            let offer = encrypted.offer
            var fields = try LoginRequest.authentication(credential: offer.credentialPayload(username: username, password: password),
                                                         clientID: clientID(), provider: provider, steam: steam)
            defer { fields.wipe() }
            try encrypted.send(.message(service: 7, type: 27, fields: fields))
            let response = try AuthenticationResponse.parse(encrypted.receiveMessage(), provider: provider)
            try token.check()
            var plain = try offer.crypt(response.encryptedKey)
            defer { plain.wipe() }
            guard let passKey = String(data: plain, encoding: .utf8)?.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) else {
                throw LauncherError.message("The account server returned an unsupported session key.")
            }
            let session = GameSession(userID: response.userID, passKey: passKey, expires: Date().addingTimeInterval(120), provider: provider, steamAuthorization: steam)
            try session.validate(); return session
        }
    }
    func withAuthorization<T>(token: CancellationToken, _ body: (SteamAuthorization?) throws -> T) throws -> T {
        let steam = try authorization(token: token)
        // Keep the Steam context alive through the complete exchange. On any
        // throw it closes here; a successful GameSession retains it for handoff.
        defer { withExtendedLifetime(steam) {} }
        let result = try body(steam)
        try token.check()
        return result
    }
    func authorization(token: CancellationToken) throws -> SteamAuthorization? {
        try token.check()
        let result = provider == .steam ? try steamTickets.acquire(token) : nil
        try token.check()
        return result
    }
    func revalidate(_ session: GameSession, token: CancellationToken) throws -> GameSession {
        try token.check()
        guard session.provider == provider else { throw LauncherError.message("The session belongs to another account type. Sign in again with \(provider.title).") }
        // Ask the server even if the conservative local expiry elapsed while
        // downloading. No password is sent again, and launch still requires a
        // fresh successful server validation.
        try session.validateFormat()
        try LoginSchema.verify(base.appendingPathComponent("PatchClient/BankB/LoginMessages.xml"))
        let connection = try KIConnection(host: "login.us.wizard101.com", port: 12000, token: token)
        defer { connection.close() }
        let encrypted = try NativeEncryptedSession(connection: connection, game: base.appendingPathComponent("Bin/WizardGraphicalClient.exe"), token: token)
        try encrypted.verifyTransport()
        var fields = try LoginRequest.validation(session: session, provider: provider,
                                                  key: encrypted.offer.validationKey(session.passKey), clientID: clientID())
        defer { fields.wipe() }
        try encrypted.send(.message(service: 7, type: 15, fields: fields))
        try SessionValidationResponse.validate(encrypted.receiveMessage(), userID: session.userID, provider: provider)
        try token.check()
        let refreshed = GameSession(userID: session.userID, passKey: session.passKey, expires: Date().addingTimeInterval(120), provider: provider, steamAuthorization: session.steamAuthorization)
        try refreshed.validate(); return refreshed
    }
    private func clientID() -> String {
        let defaults = UserDefaults.standard
        let value = defaults.string(forKey: "patchClientID") ?? UUID().uuidString
        defaults.set(value, forKey: "patchClientID")
        return value
    }
    func syntheticAuthenticationProbe(token: CancellationToken) throws -> String {
        // Random, nonexistent identity. Never reads GUI fields or saved passwords.
        guard provider == .us else { throw LauncherError.message("The synthetic authentication probe is US-only; use the local form to diagnose Steam.") }
        let account = "nativeprobe" + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        do {
            _ = try authenticate(username: account, password: UUID().uuidString, token: token)
            throw LauncherError.message("The nonexistent diagnostic account unexpectedly authenticated.")
        } catch let failure as AuthenticationFailure where failure.stage == .authentication {
            try token.check()
            var report = try JSONSerialization.jsonObject(with: failure.diagnosticData()) as! [String: Any]
            report["authenticated_response_received"] = true
            report["real_credentials_sent"] = false
            report["synthetic_account_rejected"] = true
            return String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self)
        }
    }
    func probe(token: CancellationToken) throws -> String {
        try LoginSchema.verify(base.appendingPathComponent("PatchClient/BankB/LoginMessages.xml"))
        let connection = try KIConnection(host: "login.us.wizard101.com", port: 12000, token: token)
        defer { connection.close() }
        let session = try NativeEncryptedSession(connection: connection, game: base.appendingPathComponent("Bin/WizardGraphicalClient.exe"), token: token)
        try session.verifyTransport()
        let report: [String: Any] = ["server_signature_verified": true, "encrypted_reply_accepted": true,
                                     "incoming_gcm_tags_verified": session.verifiedChunks,
                                     "encrypted_handshake_verified": true,
                                     "native_authentication_verified": false, "credentials_sent": false]
        return String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self)
    }
}
