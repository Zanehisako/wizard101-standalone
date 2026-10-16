import Foundation

// Never retain the server's Reason (or any other response field) in an error.
// These exact tokens are compared by the official Windows launcher's
// MSG_USER_AUTHEN_RSP handler. Prefixes, suffixes and free text stay unknown.
struct AuthenticationFailure: Error, LocalizedError, Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    enum Reason: String, Codable, Sendable {
        case serverUnavailable = "server_unavailable"
        case banned, quarantined
        case accountClientMismatch = "account_client_mismatch"
        case unknown

        init(serverReason: Data) {
            switch serverReason {
            case Data("AuthDown".utf8): self = .serverUnavailable
            case Data("AuthBanned".utf8): self = .banned
            case Data("AuthQuarantined".utf8): self = .quarantined
            case Data("AccountClientMismatch".utf8): self = .accountClientMismatch
            default: self = .unknown
            }
        }
    }
    enum Stage: String, Codable, Sendable { case authentication, validation }

    let provider: AccountProvider
    let code: Int32
    let reason: Reason
    let stage: Stage

    var errorDescription: String? {
        let subject = stage == .authentication ? "\(provider.title) sign-in" : "The \(provider.title) session"
        let detail: String
        switch reason {
        case .serverUnavailable: detail = "The authentication service is unavailable. Try again later."
        case .banned: detail = "The server reports an account ban. Contact Wizard101 support."
        case .quarantined: detail = "The server reports that this account is quarantined. Contact Wizard101 support."
        case .accountClientMismatch: detail = "The server reports an account/client mismatch. Check the selected account type."
        case .unknown: detail = "The server did not provide a recognized reason. Retry later or contact Wizard101 support."
        }
        return "\(subject) was rejected (account server code \(code)). \(detail)"
    }
    var description: String { errorDescription! }
    var debugDescription: String { description }

    // Closed set of diagnostic fields; no arbitrary text, identity or secrets.
    func diagnosticData() throws -> Data {
        struct Report: Encodable {
            let provider: AccountProvider
            let code: Int32
            let reason: Reason
            let stage: Stage
        }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(Report(provider: provider, code: code, reason: reason, stage: stage))
    }
}

// Only the separate local diagnostic candidate enables this file. Normal apps
// continue to display the safe message without recording an account failure.
struct AuthenticationDiagnostics {
    let url: URL
    func clear() throws {
        if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }
    }
    func record(_ error: Error) throws {
        guard let failure = error as? AuthenticationFailure else { return }
        try failure.diagnosticData().write(to: url, options: .atomic)
    }
}
