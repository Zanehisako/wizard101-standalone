import Foundation

func runAuthenticationTests(check: (Bool, String) throws -> Void, rejects: (String, () throws -> Void) throws -> Void) throws {
    let secret = "SECRET-PASSWORD-TICKET-SESSION-IDENTITY"
    func response(code: Int32 = 996708736, reason: Data, validation: Bool = false, userID: UInt64 = 123) throws -> KIFrame {
        var fields = Data(); fields.put(code)
        if validation {
            try fields.putBlob(reason); fields.put(userID)
        } else {
            fields.put(userID); try fields.putString(secret); try fields.putBlob(reason)
        }
        try fields.putString(secret); fields.put(Int32(0)); fields.put(Int32(0)); try fields.putString(secret)
        if !validation { try fields.putString(secret) }
        return .message(service: 7, type: validation ? 16 : 14, fields: fields)
    }
    func parse(_ frame: KIFrame, provider: AccountProvider, validation: Bool) throws {
        if validation { try SessionValidationResponse.validate(frame, userID: 123, provider: provider) }
        else { _ = try AuthenticationResponse.parse(frame, provider: provider) }
    }
    let known: [(String, AuthenticationFailure.Reason, String)] = [
        ("AuthDown", .serverUnavailable, "unavailable"),
        ("AuthBanned", .banned, "ban"),
        ("AuthQuarantined", .quarantined, "quarantined"),
        ("AccountClientMismatch", .accountClientMismatch, "account/client mismatch")
    ]
    let unknown = [Data(), Data(secret.utf8), Data("AuthDown \(secret)".utf8), Data("AuthBanned\0\(secret)".utf8),
                   Data("\(secret)AccountClientMismatch".utf8), Data("authdown".utf8), Data([0xff, 0x80, 0])]
    for provider in AccountProvider.allCases {
        for validation in [false, true] {
            for (wire, category, recovery) in known + unknown.map({ (String(decoding: $0, as: UTF8.self), .unknown, "recognized reason") }) {
                let frame = try response(reason: Data(wire.utf8), validation: validation)
                do {
                    try parse(frame, provider: provider, validation: validation)
                    throw LauncherError.message("Account rejection was accepted")
                } catch let failure as AuthenticationFailure {
                    try check(failure.provider == provider && failure.code == 996708736 && failure.reason == category
                              && failure.stage == (validation ? .validation : .authentication), "Typed \(provider.title) \(validation ? "validation" : "authentication") rejection: \(category.rawValue)")
                    let message = failure.localizedDescription
                    try check(message.contains(provider.title) && message.contains(recovery) && !message.contains("password"), "Account rejection gives a neutral, category-specific recovery")
                    let diagnostic = try failure.diagnosticData()
                    let report = try JSONSerialization.jsonObject(with: diagnostic) as! [String: Any]
                    try check(Set(report.keys) == Set(["provider", "code", "reason", "stage"])
                              && report["reason"] as? String == category.rawValue, "Diagnostic contains only provider, code, safe category and stage")
                    let surfaces = [message, String(describing: failure), String(reflecting: failure),
                                    (failure as NSError).localizedDescription, String(decoding: diagnostic, as: UTF8.self)]
                    try check(surfaces.allSatisfy { !$0.contains(secret) }, "Server fields cannot echo secrets through error or diagnostic formatting")
                }
            }
            // Invalid UTF-8 is opaque server text, not a reason to print bytes.
            do { try parse(response(reason: Data([0xff, 0x80, 0])), provider: provider, validation: false) }
            catch let failure as AuthenticationFailure { try check(failure.reason == .unknown, "Invalid reason encoding stays an unknown rejection") }
            let complete = try response(reason: Data("AuthDown".utf8), validation: validation)
            for count in 0..<complete.payload.count {
                let truncated = KIFrame(control: false, opcode: 0, payload: Data(complete.payload.prefix(count)))
                var rejected = false
                do { try parse(truncated, provider: provider, validation: validation) }
                catch {
                    rejected = true
                    try check(!(error is AuthenticationFailure) && !error.localizedDescription.contains(secret), "Truncated responses fail safely before classifying rejection")
                }
                try check(rejected, "Truncated account response cannot be accepted")
            }
            var badService = complete.payload; badService[0] = 8
            var badType = complete.payload; badType[1] = 27
            var trailing = complete.payload; trailing.append(0)
            let wrongLength = UInt16(trailing.count).littleEndian
            trailing[2] = UInt8(truncatingIfNeeded: wrongLength); trailing[3] = UInt8(truncatingIfNeeded: wrongLength >> 8)
            for payload in [badService, badType, trailing] {
                try rejects("Wrong response service, type or trailing fields are rejected") {
                    try parse(KIFrame(control: false, opcode: 0, payload: payload), provider: provider, validation: validation)
                }
            }
            try rejects("Control frames cannot become account rejections") {
                try parse(KIFrame(control: true, opcode: 0, payload: complete.payload), provider: provider, validation: validation)
            }
            try parse(response(code: 0, reason: Data("AuthBanned".utf8), validation: validation), provider: provider, validation: validation)
        }
    }
    do { _ = try AuthenticationResponse.parse(response(code: -123, reason: Data(secret.utf8)), provider: .steam) }
    catch let failure as AuthenticationFailure { try check(failure.code == -123 && failure.reason == .unknown, "Unknown numeric failure code is preserved without guessing its meaning") }
    try rejects("Authentication success still needs a nonzero identity") { _ = try AuthenticationResponse.parse(response(code: 0, reason: Data(), userID: 0)) }
    try rejects("Session validation still needs the matching identity") { try SessionValidationResponse.validate(response(code: 0, reason: Data(), validation: true), userID: 456) }

    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("w101-auth-diagnostics-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: folder) }
    let diagnostics = AuthenticationDiagnostics(url: folder.appendingPathComponent("AuthenticationFailure.json"))
    try diagnostics.record(CancellationError()); try diagnostics.record(LauncherError.message(secret))
    try check(!FileManager.default.fileExists(atPath: diagnostics.url.path), "Cancellation and arbitrary errors never enter authentication diagnostics")
    let failure = AuthenticationFailure(provider: .steam, code: 996708736, reason: .unknown, stage: .authentication)
    try diagnostics.record(failure)
    try check(try Data(contentsOf: diagnostics.url) == failure.diagnosticData(), "Local diagnostic file serializes only the typed error")
    try diagnostics.clear(); try diagnostics.clear()
    try check(!FileManager.default.fileExists(atPath: diagnostics.url.path), "Each retry clears stale diagnostic results")

    var released = 0
    let source = SteamTicketSource { _ in try SteamAuthorization(userID: 123, ticket: Data([0, 255, 65]), release: { released += 1 }) }
    let auth = NativeAuthentication(base: folder, provider: .steam, steamTickets: source)
    do {
        try auth.withAuthorization(token: CancellationToken()) { _ in
            _ = try AuthenticationResponse.parse(response(reason: Data("AuthDown".utf8)), provider: .steam)
        }
    } catch is AuthenticationFailure { }
    try check(released == 1, "Rejected account exchange releases its Steam ticket")
    let cancelled = CancellationToken()
    do { try auth.withAuthorization(token: cancelled) { _ in cancelled.cancel() } }
    catch is CancellationError { }
    try check(released == 2, "Cancellation after ticket acquisition stops handoff and releases the ticket")
    var retained: GameSession? = try auth.withAuthorization(token: CancellationToken()) { steam in
        GameSession(userID: 123, passKey: "FIXTURE", expires: Date().addingTimeInterval(120), provider: .steam, steamAuthorization: steam)
    }
    try check(released == 2 && retained?.steamAuthorization != nil, "Successful session retains its Steam ticket for game handoff")
    retained = nil
    try check(released == 3, "Discarding the session cleans up its Steam ticket exactly once")
    try rejects("Synthetic Steam probes cannot send fake account credentials or request a ticket") { _ = try auth.syntheticAuthenticationProbe(token: CancellationToken()) }
    try check(released == 3, "Synthetic Steam probe does not acquire a ticket")
}
