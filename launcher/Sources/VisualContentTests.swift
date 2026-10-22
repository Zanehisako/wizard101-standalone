import Foundation

private final class VisualFixtureHTTP: URLProtocol {
    static let content = Data((0..<60000).map { UInt8(truncatingIfNeeded: $0) })
    private static let lock = NSLock()
    private static var requests: [(String, String?)] = []
    private static var corrupt = false
    private static var deniedPath: String?
    private static var deniedStatus = 403
    private static var connectionLost = false
    static func reset(corrupt: Bool = false, deniedPath: String? = nil, deniedStatus: Int = 403, connectionLost: Bool = false) {
        lock.lock(); defer { lock.unlock() }; requests = []; self.corrupt = corrupt
        self.deniedPath = deniedPath; self.deniedStatus = deniedStatus
        self.connectionLost = connectionLost
    }
    static func observed() -> [(String, String?)] { lock.lock(); defer { lock.unlock() }; return requests }
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "versionak.us.wizard101.com" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url else { return }
        let range = request.value(forHTTPHeaderField: "Range")
        Self.lock.lock(); Self.requests.append((url.path, range)); let corrupt = Self.corrupt && url.lastPathComponent.hasPrefix("Mob2-")
        let denied = Self.deniedPath == url.path, deniedStatus = Self.deniedStatus, connectionLost = Self.connectionLost; Self.lock.unlock()
        if denied {
            if connectionLost { client?.urlProtocol(self, didFailWithError: URLError(.networkConnectionLost)); return }
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: url, statusCode: deniedStatus, httpVersion: "HTTP/1.1", headerFields: [:])!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocolDidFinishLoading(self); return
        }
        let requested = range?.dropFirst(6).split(separator: "-", omittingEmptySubsequences: false) ?? []
        let offset = requested.first.flatMap { Int($0) } ?? 0
        let end = requested.last.flatMap { Int($0) } ?? Self.content.count - 1
        var headers = ["Content-Length": String(end - offset + 1)]
        if range != nil { headers["Content-Range"] = "bytes \(offset)-\(end)/\(Self.content.count)" }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: url, statusCode: range != nil ? 206 : 200, httpVersion: "HTTP/1.1", headerFields: headers)!, cacheStoragePolicy: .notAllowed)
        var body = Self.content
        if corrupt { body[5000] ^= 1 }
        var position = offset
        while position <= end {
            let next = min(position + 4000, end + 1)
            client?.urlProtocol(self, didLoad: body.subdata(in: position..<next)); position = next
        }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

func runVisualContentTests(check: (Bool, String) throws -> Void,
                           rejects: (String, () throws -> Void) throws -> Void) throws {
    let fm = FileManager.default, token = CancellationToken()
    let root = fm.temporaryDirectory.appendingPathComponent("w101-visuals-\(UUID().uuidString)")
    defer { try? fm.removeItem(at: root) }
    let paths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": root.path])
    try fm.createDirectory(at: paths.game.appendingPathComponent("Data/GameData"), withIntermediateDirectories: true)
    try fm.createDirectory(at: paths.game.appendingPathComponent("Bin"), withIntermediateDirectories: true)
    try fm.createDirectory(at: paths.state, withIntermediateDirectories: true)
    func record(_ name: String, type: UInt32 = 3) -> PatchRecord {
        PatchRecord(source: "Data/GameData/\(name).wad", target: "", type: type,
                    size: UInt64(VisualFixtureHTTP.content.count), crc: VisualFixtureHTTP.content.kiCRC,
                    table: name, headerSize: 32, headerCRC: Data(VisualFixtureHTTP.content.prefix(32)).kiCRC)
    }
    let names = ["ClassicMode-WorldData", "WizardCity-WorldData", "Arcanum-WorldData", "Wallaru-WorldData", "Equipment2-WorldData", "Mob-WorldData", "Mob2-WorldData", "Root", "_Shared-WorldData", "Pets-WorldData"]
    let visuals = names.map { record($0) }
    let audio = ["Music", "Sound-WorldData", "Sound_Dialogue_WL"].map { record($0) }
    let records = visuals + audio
    let manifest = PatchManifest(revision: "r123.Fixture", prefix: URL(string: "http://versionak.us.wizard101.com/visual-fixture/")!, records: records)
    try check(visuals.allSatisfy(\.visualArchive) && audio.allSatisfy { !$0.visualArchive }, "Visual scope covers all worlds, classic, numbered families, pets and shared assets while excluding audio")
    try check(record("ClassicMode-WC_Hub", type: 4).visualArchive && record("Mob2-WorldData", type: 1).visualArchive
              && !record("Sound_Dialogue_WL", type: 4).visualArchive, "Full visual scope also handles non-streamed and compressed manifest archive types")
    try check(record("Mob2-WorldData").appearanceArchive && record("Equipment12-HighDetail").appearanceArchive
              && !record("Mobster-WorldData").appearanceArchive && !record("Mob٢-WorldData").appearanceArchive,
              "Appearance compatibility includes numbered Mob and Equipment families with exact ASCII boundaries")
    let nested = PatchRecord(source: "Data/GameData/Sub/Mob2-WorldData.wad", target: "", type: 3, size: 60000, crc: 0)
    let alias = PatchRecord(source: "PatchClient/alias.wad", target: "Data/GameData/Mob2-WorldData.wad", type: 3, size: 60000, crc: 0)
    try check(!nested.visualArchive && !alias.visualArchive, "Visual preparation excludes nested paths and official-launcher aliases")
    let mob = visuals[6], mobFile = paths.game.appendingPathComponent(mob.localPath)
    let handle = try FileHandle(forWritingTo: {
        fm.createFile(atPath: mobFile.path, contents: Data(VisualFixtureHTTP.content.prefix(32))); return mobFile
    }())
    try handle.truncate(atOffset: mob.size); try handle.close()
    let sparse = try Data(contentsOf: mobFile)
    let tracking = mobFile.appendingPathExtension("utd"), sentinel = Data("existing streaming state".utf8)
    try sentinel.write(to: tracking)
    let preference = paths.game.appendingPathComponent("Bin/preferences.xml")
    let secret = "SECRET_PASSWORD_TICKET_SESSION_IDENTITY"
    try Data("<preferences><ClassicMode>1</ClassicMode><Password>\(secret)</Password></preferences>".utf8).write(to: preference)
    let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [VisualFixtureHTTP.self]
    func patcher(_ token: CancellationToken = CancellationToken(), free: UInt64 = UInt64.max,
                 progress: @escaping @Sendable (PatchProgress) -> Void = { _ in }) -> NativePatcher {
        NativePatcher(base: paths.game, state: paths.state, token: token, report: progress,
                      manifestLoader: { _, _ in manifest }, gameplayClosed: {}, availableBytes: { _ in free }, transferConfiguration: config)
    }
    VisualFixtureHTTP.reset()
    let pending = try patcher().run(apply: false, preparation: .visuals)
    try check(pending.inventory.needed == visuals && pending.inventory.headerBootstraps.isEmpty && pending.inventory.optionalMissing == audio.count,
              "Visual inventory requires complete sparse and missing archives without forcing audio bodies")
    try check(VisualFixtureHTTP.observed().isEmpty && (try Data(contentsOf: mobFile)) == sparse
              && ContentReadiness.load(state: paths.state)?.status == .incomplete, "Visual check records incomplete readiness without replacing game content")
    try rejects("Insufficient storage stops visual preparation before any download") { _ = try patcher(free: 0).run(apply: true, preparation: .visuals) }
    try check(VisualFixtureHTTP.observed().isEmpty && (try Data(contentsOf: mobFile)) == sparse, "Storage failure preserves original streamed content")
    let cancel = CancellationToken()
    try rejects("Cancel during visual downloads stops installation") {
        _ = try patcher(cancel, progress: { update in
            if update.detail.contains("downloaded") && (update.fraction ?? 0) > 0 { cancel.cancel() }
        }).run(apply: true, preparation: .visuals)
    }
    try check((try Data(contentsOf: mobFile)) == sparse && ContentReadiness.load(state: paths.state)?.status == .incomplete,
              "Cancelled preload retains the installed archive and incomplete readiness")
    let mobStage = paths.state.appendingPathComponent(NativePatcher.stagingName(mob))
    if fm.fileExists(atPath: mobStage.path) { try fm.removeItem(at: mobStage) }
    VisualFixtureHTTP.reset(corrupt: true)
    try rejects("Body corruption despite a valid archive header prevents visual installation") { _ = try patcher().run(apply: true, preparation: .visuals) }
    try check((try Data(contentsOf: mobFile)) == sparse && !fm.fileExists(atPath: paths.game.appendingPathComponent(visuals[0].localPath).path),
              "Failed visual CRC leaves every installed archive untouched")
    let resume = paths.state.appendingPathComponent(NativePatcher.stagingName(visuals[0]))
    try Data(VisualFixtureHTTP.content.prefix(257)).write(to: resume)
    for status in [403, 404] {
        VisualFixtureHTTP.reset(deniedPath: manifest.prefix.appendingPathComponent(visuals[0].source).path, deniedStatus: status)
        var blocked: Error?
        do { _ = try patcher().run(apply: true, preparation: .visuals) } catch { blocked = error }
        try check((blocked as? PatchFileFailure)?.allowsStreaming == true
                  && (try Data(contentsOf: resume)) == VisualFixtureHTTP.content.prefix(257),
                  "Unavailable optional HTTP \(status) remains a typed failure and preserves resumed bytes")
        try check(!fm.fileExists(atPath: paths.game.appendingPathComponent(visuals[0].localPath).path)
                  && ContentReadiness.load(state: paths.state)?.status == .incomplete,
                  "Unavailable optional archive cannot silently complete or commit the full preload")
        var recovery = ContentRecovery()
        recovery.chooseStreaming()
        try check(recovery.preparationForPlay() == .visuals, "Streaming cannot be selected without a qualified optional-file failure")
        recovery.failed(blocked!)
        try check(recovery.canOfferStreaming && !recovery.streamingOnce, "A server failure offers streaming without selecting it automatically")
        recovery.chooseStreaming()
        try check(recovery.streamingOnce && recovery.preparationForPlay() == .startup
                  && recovery.preparationForPlay() == .visuals, "Explicit streaming choice applies to one play attempt and then restores full preload")
        recovery.failed(blocked!); recovery.clear()
        try check(!recovery.canOfferStreaming && !recovery.streamingOnce, "Retry full preload clears the streaming choice")
    }
    for status in [401, 429, 500] {
        let failure = PatchFileFailure(record: visuals[0], preparation: .visuals, underlying: HTTPTransfer.ServerFailure(status: status))
        try check(!failure.allowsStreaming, "Other HTTP failures do not offer streaming: \(status)")
    }
    for required in [record("Root"), record("_Shared-WorldData"), record("Mob-WorldData", type: 5), record("ClassicMode-WC_Hub", type: 4), record("Mob-WorldData", type: 1)] {
        try check(!PatchFileFailure(record: required, preparation: .visuals, underlying: HTTPTransfer.ServerFailure(status: 403)).allowsStreaming,
                  "Required or nonoptional archives cannot offer streaming: \(required.table), type \(required.type)")
    }
    try check(!PatchFileFailure(record: visuals[0], preparation: .startup, underlying: HTTPTransfer.ServerFailure(status: 403)).allowsStreaming
              && !PatchFileFailure(record: visuals[0], preparation: .visuals, underlying: LauncherError.message("checksum failure")).allowsStreaming,
              "Startup and integrity failures cannot offer streaming")
    _ = try patcher().run(apply: true, preparation: .startup)
    try check(!fm.fileExists(atPath: paths.game.appendingPathComponent(visuals[0].localPath).path)
              && Integrity.matches(paths.game.appendingPathComponent("Data/GameData/Root.wad"), size: visuals[7].size, crc: visuals[7].crc, token: token)
              && ContentReadiness.load(state: paths.state)?.status == .incomplete,
              "Chosen streaming still verifies required startup content and leaves full visual readiness incomplete")
    VisualFixtureHTTP.reset()
    _ = try patcher().run(apply: true, preparation: .visuals)
    try check(VisualFixtureHTTP.observed().contains { $0.0.hasSuffix("ClassicMode-WorldData.wad") && $0.1 == "bytes=257-59999" }, "Retry resumes an accepted partial visual archive")
    for record in visuals {
        try check(Integrity.matches(paths.game.appendingPathComponent(record.localPath), size: record.size, crc: record.crc, token: token), "Full visual CRC verified after installation: \(record.table)")
    }
    try check(try Data(contentsOf: tracking) == sentinel, "Visual preparation preserves streaming tracking files")
    let ready = ContentReadiness.load(state: paths.state)
    try check(ready?.status == .ready && ready?.verifiedArchives == visuals.count && ready?.expectedBytes == UInt64(visuals.count * 60000),
              "Readiness records the exact verified revision, archive count and byte total")
    VisualFixtureHTTP.reset()
    _ = try patcher().run(apply: true, preparation: .visuals)
    try check(VisualFixtureHTTP.observed().isEmpty, "Repeated preload reuses verified archives with no redundant download")
    let legacy = try patcher().run(apply: false, preparation: .appearance)
    try check(legacy.inventory.needed.isEmpty, "Existing appearance mode remains compatible with completed numbered archives")

    let plan = LaunchPlan(paths: paths, mode: .uncapped, profile: false, environment: [:])
    let (run, _) = try plan.prepareLogs()
    try LaunchDiagnosticSnapshot.record(plan: plan, run: run)
    try Data("\(secret) Failed to upload texture".utf8).write(to: run.appendingPathComponent("logs/WizardGraphicalClient_d3d9.log"))
    try Data(String(repeating: "Failed to upload texture", count: 9).utf8).write(to: paths.game.appendingPathComponent("Bin/WizardGraphicalClient_d3d9.log"))
    let (decoy, _) = try plan.prepareLogs()
    try fm.setAttributes([.modificationDate: Date().addingTimeInterval(10)], ofItemAtPath: decoy.path)
    try Data(String(repeating: "Failed to upload texture", count: 3).utf8).write(to: decoy.appendingPathComponent("logs/WizardGraphicalClient_d3d9.log"))
    let report = DiagnosticReport(paths: paths, mode: .capped, diagnostics: ReliabilityDiagnostics(state: paths.state))
    func output() throws -> [String: Any] { try JSONSerialization.jsonObject(with: report.data()) as! [String: Any] }
    let captured = try output()
    let counts = captured["log_token_counts"] as? [String: [String: Int]]
    let snapshot = LaunchDiagnosticSnapshot.load(state: paths.state)
    try check(counts?["WizardGraphicalClient_d3d9.log"]?["texture_upload_failure"] == 1
              && captured["renderer_log_selection"] as? String == "recorded_launch", "Diagnostics read the recorded run instead of a stale Bin log or newer unrelated directory")
    try check(snapshot?.frameMode == .uncapped && snapshot?.settings["preferences.xml"] == ["ClassicMode": "1"], "Launch snapshot preserves actual frame mode and allowlisted settings across reopening")
    try check(!String(decoding: try report.data(), as: UTF8.self).contains(secret), "Renderer diagnostics and saved launch settings omit raw secrets")
    try fm.removeItem(at: run.appendingPathComponent("logs/WizardGraphicalClient_d3d9.log"))
    let absent = try output()
    let source = (absent["log_sources"] as? [String: [String: Any]])?["WizardGraphicalClient_d3d9.log"]
    try check(source?["available"] as? Bool == false && (absent["log_token_counts"] as? [String: Any])?["WizardGraphicalClient_d3d9.log"] == nil,
              "A missing recorded log is unavailable instead of zero errors or a stale fallback")
    try fm.createSymbolicLink(at: run.appendingPathComponent("logs/WizardGraphicalClient_d3d9.log"), withDestinationURL: preference)
    try check(((try output())["log_sources"] as? [String: [String: Any]])?["WizardGraphicalClient_d3d9.log"]?["available"] as? Bool == false,
              "Diagnostic collection refuses linked renderer logs")
    try fm.removeItem(at: paths.state.appendingPathComponent("LastLaunch.json"))
    let fallback = try output()
    try check(fallback["renderer_log_selection"] as? String == "newest_legacy_run"
              && (fallback["log_token_counts"] as? [String: [String: Int]])?["WizardGraphicalClient_d3d9.log"]?["texture_upload_failure"] == 3
              && (fallback["renderer_settings"] as? [String: Bool])?["available"] == false, "Legacy log fallback never infers historical flags from current preferences")
    try Data("{}".utf8).write(to: paths.state.appendingPathComponent("ContentReadiness.json"))
    try check(ContentReadiness.load(state: paths.state) == nil, "Malformed readiness cannot be reported as verified")
    try runPreparedVisualRecoveryTests(check: check, rejects: rejects)
}

private func runPreparedVisualRecoveryTests(check: (Bool, String) throws -> Void,
                                           rejects: (String, () throws -> Void) throws -> Void) throws {
    let fm = FileManager.default, root = fm.temporaryDirectory.appendingPathComponent("w101-prepared-\(UUID().uuidString)")
    defer { try? fm.removeItem(at: root) }
    let paths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": root.path])
    try fm.createDirectory(at: paths.game.appendingPathComponent("Data/GameData"), withIntermediateDirectories: true)
    try fm.createDirectory(at: paths.state, withIntermediateDirectories: true)
    let bytes = VisualFixtureHTTP.content
    func record(_ name: String, _ type: UInt32 = 3) -> PatchRecord {
        PatchRecord(source: "Data/GameData/\(name).wad", target: "", type: type, size: UInt64(bytes.count), crc: bytes.kiCRC,
                    table: name, headerSize: 32, headerCRC: Data(bytes.prefix(32)).kiCRC)
    }
    let mob = record("Mob2-WorldData", 5), shared = record("Root", 1)
    let prepared = record("WizardCity-WorldData"), corrupt = record("Arcanum-WorldData"), partial = record("Wallaru-WorldData")
    let manifest = PatchManifest(revision: "r123.Recovery", prefix: URL(string: "http://versionak.us.wizard101.com/recovery/")!,
                                 records: [mob, shared, prepared, corrupt, partial])
    let mobFile = paths.game.appendingPathComponent(mob.localPath)
    try Data(bytes.prefix(32)).write(to: mobFile)
    let handle = try FileHandle(forWritingTo: mobFile); try handle.truncate(atOffset: mob.size); try handle.close()
    let original = try Data(contentsOf: mobFile)
    let tracking = mobFile.appendingPathExtension("utd"), sentinel = Data("retained tracking".utf8)
    try sentinel.write(to: tracking)
    let mobStage = paths.state.appendingPathComponent(NativePatcher.stagingName(mob))
    try Data(bytes.prefix(257)).write(to: mobStage)
    let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [VisualFixtureHTTP.self]
    func patcher() -> NativePatcher {
        NativePatcher(base: paths.game, state: paths.state, token: CancellationToken(), report: { _ in },
                      manifestLoader: { _, _ in manifest }, gameplayClosed: {}, availableBytes: { _ in UInt64.max }, transferConfiguration: config)
    }
    VisualFixtureHTTP.reset(deniedPath: manifest.prefix.appendingPathComponent(mob.source).path, connectionLost: true)
    var blocked: PatchFileFailure?
    do { _ = try patcher().run(apply: true, preparation: .visuals) } catch { blocked = error as? PatchFileFailure }
    try check(blocked?.existingStreamingArchiveVerified == true && blocked?.allowsStreaming == true
              && (try Data(contentsOf: mobStage)) == bytes.prefix(257),
              "Real connection-loss failure offers recovery only with a verified installed dynamic header and retains partial bytes")
    var recovery = ContentRecovery(); recovery.failed(blocked!)
    try check(recovery.canOfferStreaming && !recovery.streamingOnce && recovery.preparationForPlay() == .visuals,
              "Interrupted preload never selects streaming automatically")
    recovery.failed(blocked!); recovery.chooseStreaming()
    try check(recovery.preparationForPlay() == .startup && recovery.preparationForPlay() == .visuals,
              "Network recovery consumes exactly one explicit streaming choice")
    for candidate in [shared, record("Root", 5), record("_Shared-WorldData", 5)] {
        try check(!PatchFileFailure(record: candidate, preparation: .visuals, underlying: HTTPTransfer.NetworkFailure(code: -1005),
                                    existingStreamingArchiveVerified: true).allowsStreaming,
                  "Core shared startup archives never qualify for network streaming recovery")
    }
    try check(!PatchFileFailure(record: mob, preparation: .visuals, underlying: HTTPTransfer.NetworkFailure(code: -1005)).allowsStreaming
              && !PatchFileFailure(record: mob, preparation: .visuals, underlying: LauncherError.message("checksum"), existingStreamingArchiveVerified: true).allowsStreaming,
              "Missing validated installation and integrity failures cannot qualify for network recovery")
    try Data(bytes).write(to: paths.state.appendingPathComponent(NativePatcher.stagingName(prepared)))
    var bad = bytes; bad[5000] ^= 1
    let corruptStage = paths.state.appendingPathComponent(NativePatcher.stagingName(corrupt))
    let partialStage = paths.state.appendingPathComponent(NativePatcher.stagingName(partial))
    try bad.write(to: corruptStage); try Data(bytes.prefix(257)).write(to: partialStage)
    VisualFixtureHTTP.reset()
    _ = try patcher().run(apply: true, preparation: .startup)
    try check(!fm.fileExists(atPath: paths.game.appendingPathComponent(prepared.localPath).path),
              "Ordinary startup does not silently install staged optional visuals")
    VisualFixtureHTTP.reset()
    _ = try patcher().run(apply: true, preparation: .startup, installPreparedVisuals: true)
    try check(VisualFixtureHTTP.observed().isEmpty
              && Integrity.matches(paths.game.appendingPathComponent(prepared.localPath), size: prepared.size, crc: prepared.crc, token: CancellationToken()),
              "Explicit recovery transaction installs prepared visuals with full CRC and no redundant downloads")
    try check((try Data(contentsOf: mobFile)) == original && (try Data(contentsOf: mobStage)) == bytes.prefix(257)
              && (try Data(contentsOf: tracking)) == sentinel, "Recovery preserves the streamed archive, incomplete download and tracking")
    try check((try Data(contentsOf: corruptStage)) == bad && (try Data(contentsOf: partialStage)) == bytes.prefix(257)
              && !fm.fileExists(atPath: paths.game.appendingPathComponent(corrupt.localPath).path)
              && !fm.fileExists(atPath: paths.game.appendingPathComponent(partial.localPath).path),
              "Prepared installation refuses corrupt and partial files without modifying them")
    let readiness = ContentReadiness.load(state: paths.state)
    try check(readiness?.status == .incomplete && readiness?.verifiedArchives == 2 && readiness?.selectedArchives == 5,
              "Recovery reports remaining visual gaps rather than claiming the full preload finished")
    try rejects("Prepared promotion is never a read-only check") { _ = try patcher().run(apply: false, installPreparedVisuals: true) }
    try rejects("Prepared promotion cannot bypass full preload") { _ = try patcher().run(apply: true, preparation: .visuals, installPreparedVisuals: true) }
}
