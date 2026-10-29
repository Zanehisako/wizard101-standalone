import Foundation

// A CDN can make useful progress on every request yet drop each response before
// its requested end. This used to exhaust three retries inside one 8 MiB range.
private final class ProgressFixtureHTTP: URLProtocol {
    static let content = Data((0..<16000).map { UInt8(truncatingIfNeeded: $0) })
    static let received = DispatchSemaphore(value: 0)
    static var offsets: [Int] = []
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "versionak.us.wizard101.com" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        if request.url!.path == "/stall" {
            client?.urlProtocol(self, didFailWithError: URLError(.networkConnectionLost)); return
        }
        if request.url!.path == "/denied" {
            client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: [:])!, cacheStoragePolicy: .notAllowed)
            client?.urlProtocolDidFinishLoading(self); return
        }
        let parts = request.value(forHTTPHeaderField: "Range")!.dropFirst(6).split(separator: "-")
        let start = Int(parts[0])!, end = Int(parts[1])!
        Self.offsets.append(start)
        let response = HTTPURLResponse(url: request.url!, statusCode: 206, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Range": "bytes \(request.url!.path == "/bad-range" ? start + 1 : start)-\(end)/\(Self.content.count)"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if request.url!.path == "/bad-range" { client?.urlProtocolDidFinishLoading(self); return }
        let completeThenDisconnect = request.url!.path == "/complete-disconnect"
        let next = completeThenDisconnect ? end + 1 : min(start + 2000, end + 1)
        client?.urlProtocol(self, didLoad: Self.content.subdata(in: start..<next))
        DispatchQueue.global().async {
            _ = Self.received.wait(timeout: .now() + 3)
            if next <= end || completeThenDisconnect { self.client?.urlProtocol(self, didFailWithError: URLError(.networkConnectionLost)) }
            else { self.client?.urlProtocolDidFinishLoading(self) }
        }
    }
    override func stopLoading() {}
}

func runPatchDiagnosticTests(check: (Bool, String) throws -> Void,
                             rejects: (String, () throws -> Void) throws -> Void) throws {
    let fm = FileManager.default, root = fm.temporaryDirectory.appendingPathComponent("w101-patch-diagnostic-" + UUID().uuidString)
    try fm.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? fm.removeItem(at: root) }
    let file = root.appendingPathComponent("progress.part")
    let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [ProgressFixtureHTTP.self]
    ProgressFixtureHTTP.offsets = []
    var transfers: [HTTPTransfer.Observation] = []
    var acceptedBytes: UInt64 = 0
    try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/progress")!, to: file,
        size: UInt64(ProgressFixtureHTTP.content.count), token: CancellationToken(), progress: {
            if $0 > acceptedBytes { acceptedBytes = $0; ProgressFixtureHTTP.received.signal() }
        },
        testConfiguration: config, observer: {
            transfers.append($0)
            if ProcessInfo.processInfo.environment["W101_SELF_TEST_PROGRESS"] == "1",
               let data = try? JSONEncoder().encode($0) { fputs("Progress fixture: \(String(decoding: data, as: UTF8.self))\n", stderr) }
        })
    try check(try Data(contentsOf: file) == ProgressFixtureHTTP.content && ProgressFixtureHTTP.offsets == Array(stride(from: 0, to: 16000, by: 2000)),
              "Eight consecutive partial responses resume useful progress without exhausting a no-progress retry budget")
    try check(transfers.count == 8 && transfers[0].requestedRange?.start == 0 && transfers[0].requestedRange?.end == 15999
              && transfers[0].receivedBytes == 2000 && transfers[0].stagedBytes == 2000
              && transfers[0].httpStatus == 206 && transfers[0].networkCode == -1005 && transfers[0].outcome == .network
              && transfers.last?.outcome == .completed && transfers.last?.receivedBytes == 2000,
              "Transfer observations distinguish received bytes from resumed file size and preserve exact range and network status")
    try fm.removeItem(at: file); transfers = []
    try rejects("A stalled connection still exhausts three no-progress retries") {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/stall")!, to: file,
            size: 16000, token: CancellationToken(), progress: { _ in }, testConfiguration: config, observer: { transfers.append($0) })
    }
    try check(transfers.count == 3 && transfers.allSatisfy { $0.receivedBytes == 0 && $0.networkCode == -1005 && $0.httpStatus == nil },
              "No-progress failures remain bounded and absent HTTP responses stay unavailable")
    try Data(ProgressFixtureHTTP.content.prefix(257)).write(to: file); transfers = []
    try rejects("Invalid HTTP range does not trigger progress retries") {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/bad-range")!, to: file,
            size: 16000, token: CancellationToken(), progress: { _ in }, testConfiguration: config, observer: { transfers.append($0) })
    }
    try check(transfers.count == 1 && transfers[0].outcome == .invalidRange && transfers[0].receivedBytes == 0
              && transfers[0].requestedRange?.start == 257 && (try Data(contentsOf: file)).count == 257,
              "Rejected response diagnostics preserve the requested range and existing partial download")
    transfers = []
    try rejects("HTTP denial stays a server failure with one observation") {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/denied")!, to: file,
            size: 16000, token: CancellationToken(), progress: { _ in }, testConfiguration: config, observer: { transfers.append($0) })
    }
    try check(transfers.count == 1 && transfers[0].httpStatus == 404 && transfers[0].networkCode == nil && transfers[0].outcome == .http,
              "HTTP failure is not mislabeled as URLSession cancellation")
    try fm.removeItem(at: file); transfers = []
    ProgressFixtureHTTP.offsets = []
    try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/complete-disconnect")!, to: file,
        size: 16000, token: CancellationToken(), progress: { if $0 > 0 { ProgressFixtureHTTP.received.signal() } }, testConfiguration: config,
        observer: { transfers.append($0) })
    try check(ProgressFixtureHTTP.offsets == [0] && Integrity.matches(file, size: 16000, crc: ProgressFixtureHTTP.content.kiCRC, token: CancellationToken())
              && transfers[0].outcome == .network && transfers[0].receivedBytes == 16000,
              "A connection error after the final bytes preserves complete staging for the mandatory CRC rather than truncating and downloading again")

    let paths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": root.path])
    let metrics = PatchDiagnostics(state: paths.state)
    let record = PatchRecord(source: "Data/GameData/Novus-WorldData.wad", target: "", type: 5, size: 16000,
        crc: ProgressFixtureHTTP.content.kiCRC, headerSize: 32, headerCRC: Data(ProgressFixtureHTTP.content.prefix(32)).kiCRC)
    let manifest = PatchManifest(revision: "r123.Diagnostics", prefix: URL(string: "http://versionak.us.wizard101.com/fixture/")!, records: [record])
    metrics.manifest(manifest)
    let context = PatchDiagnostics.Context.make(record: record, revision: manifest.revision, preparation: .visuals)!
    metrics.record(context, phase: .archiveBody, transfer: transfers[0])
    metrics.failed(context, phase: .archiveBody, error: PatchValidationFailure.checksum, primary: true)
    for _ in 0..<25 { metrics.record(context, phase: .archiveBody, transfer: transfers[0]) }
    let loaded = PatchDiagnostics(state: paths.state).snapshot()
    try check(loaded.observations.count == 20 && loaded.transfers?.count == 20 && loaded.latestFailure?.archive.path == record.localPath
              && loaded.latestFailure?.verification == .checksumFailed && loaded.latestFailure?.transfer?.receivedBytes == 16000,
              "The latest 20 transfer/verification observations survive reopening while the primary failure remains available")
    let secret = "SECRET_PASSWORD_TICKET_SESSION_IDENTITY"
    metrics.failed(context, phase: .archiveBody, error: LauncherError.message(secret), primary: true)
    let reportFile = paths.state.appendingPathComponent("PatchDiagnostics.json")
    try check(!String(decoding: try Data(contentsOf: reportFile), as: UTF8.self).contains(secret)
              && (try fm.attributesOfItem(atPath: reportFile.path)[.posixPermissions] as? NSNumber)?.intValue == 0o600,
              "Patch diagnostics exclude raw errors and use private file permissions")
    let invalid = PatchRecord(source: "Data/GameData/../../Password.wad", target: "", type: 5, size: 16000, crc: 0)
    try check(PatchDiagnostics.Context.make(record: invalid, revision: manifest.revision, preparation: .visuals) == nil,
              "Diagnostic archive identities reject unsafe and nonmanifest paths")
    let installed = paths.game.appendingPathComponent(record.localPath)
    try fm.createDirectory(at: installed.deletingLastPathComponent(), withIntermediateDirectories: true)
    try ProgressFixtureHTTP.content.write(to: installed)
    let staged = paths.state.appendingPathComponent(NativePatcher.stagingName(record))
    try Data(ProgressFixtureHTTP.content.prefix(257)).write(to: staged)
    let audit = ArchiveAudit.inspect(paths: paths, manifest: loaded.manifest)
    let archives = audit["archives"] as! [[String: Any]]
    try check((archives[0]["installed"] as? [String: Any])?["status"] as? String == "complete"
              && (archives[0]["staged"] as? [String: Any])?["status"] as? String == "partial",
              "Archive reports separately classify a complete installed file and its partial staging")
    try Data(ProgressFixtureHTTP.content.prefix(32)).write(to: installed)
    let handle = try FileHandle(forWritingTo: installed); try handle.truncate(atOffset: 16000); try handle.close()
    try check(ArchiveAudit.file(installed, archive: .init(record), staging: false, token: CancellationToken())["status"] as? String == "valid_streamed_header",
              "A current header-valid sparse archive is reported as valid streaming without claiming full preload or corrupt body")
    try Data(repeating: 42, count: 16000).write(to: installed)
    try check(ArchiveAudit.file(installed, archive: .init(record), staging: false, token: CancellationToken())["status"] as? String == "verification_failed",
              "A failed current full and header CRC is distinguished from a valid streamed archive")
    try fm.removeItem(at: installed)
    try fm.createSymbolicLink(at: installed, withDestinationURL: file)
    let unsafeAudit = ArchiveAudit.inspect(paths: paths, manifest: loaded.manifest)["archives"] as! [[String: Any]]
    try check((unsafeAudit[0]["installed"] as? [String: Any])?["status"] as? String == "unavailable"
              && (try Data(contentsOf: staged)).count == 257, "Read-only audit refuses linked archives and preserves partial staging")
    let retained = try RejectedStaging.preserve(staged)!
    try check(!fm.fileExists(atPath: staged.path) && (try Data(contentsOf: retained)).count == 257,
              "Rejected staging is retained under a unique name for retry and rollback")
    var plan = LaunchPlan(paths: paths, mode: .uncapped, profile: false, environment: [:])
    plan.contentPreparation = .visuals
    let (run, _) = try plan.prepareLogs()
    try LaunchDiagnosticSnapshot.record(plan: plan, run: run)
    let report = DiagnosticReport(paths: paths, mode: .capped, diagnostics: ReliabilityDiagnostics(state: paths.state))
    func reportData() throws -> [String: Any] { try JSONSerialization.jsonObject(with: report.data()) as! [String: Any] }
    try check(try reportData()["launch_content_mode"] as? String == "full_visual_preload", "Diagnostic launch mode records completed preload independently of current preferences")
    plan.contentPreparation = .startup; try LaunchDiagnosticSnapshot.record(plan: plan, run: run)
    try check(try reportData()["launch_content_mode"] as? String == "streaming_once", "The explicit streaming launch mode survives launcher reopening")
    let lastLaunch = paths.state.appendingPathComponent("LastLaunch.json")
    var legacy = try JSONSerialization.jsonObject(with: Data(contentsOf: lastLaunch)) as! [String: Any]
    legacy["schema"] = 1; legacy.removeValue(forKey: "contentPreparation")
    try JSONSerialization.data(withJSONObject: legacy).write(to: lastLaunch)
    try check(LaunchDiagnosticSnapshot.load(state: paths.state)?.frameMode == .uncapped
              && (try reportData())["launch_content_mode"] as? String == "unavailable",
              "Build 15 launch snapshots remain readable and missing content mode means unavailable")
    try check(!String(decoding: try report.data(), as: UTF8.self).contains(secret), "The complete report excludes raw failure messages and credentials")
    let exports = DiagnosticExports(paths: paths)
    let firstZIP = try exports.save(report), firstBytes = try Data(contentsOf: firstZIP)
    let secondZIP = try exports.save(report)
    try check(firstZIP != secondZIP && DiagnosticExports.validName(firstZIP.lastPathComponent)
              && (try Data(contentsOf: firstZIP)) == firstBytes && exports.latest() != nil,
              "One-click exports have unique timestamped ZIP names and remain discoverable after reopening without overwriting prior reports")
    try check((try fm.attributesOfItem(atPath: firstZIP.path)[.posixPermissions] as? NSNumber)?.intValue == 0o600
              && (try fm.attributesOfItem(atPath: exports.directory.path)[.posixPermissions] as? NSNumber)?.intValue == 0o700,
              "Saved diagnostic ZIPs and their reports folder have private permissions")
    let unpacked = root.appendingPathComponent("unpacked-report")
    let unzip = Process(); unzip.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
    unzip.arguments = ["-x", "-k", firstZIP.path, unpacked.path]
    unzip.standardOutput = FileHandle.nullDevice; unzip.standardError = FileHandle.nullDevice
    try unzip.run(); unzip.waitUntilExit()
    let archiveFolder = unpacked.appendingPathComponent("Wizard101 Diagnostics")
    let json = try Data(contentsOf: archiveFolder.appendingPathComponent("Diagnostic-Report.json"))
    try check(unzip.terminationStatus == 0
              && Set(try fm.contentsOfDirectory(atPath: archiveFolder.path)) == Set(["Diagnostic-Report.json", "README.txt"])
              && !String(decoding: json, as: UTF8.self).contains(secret)
              && (try JSONSerialization.jsonObject(with: json) as? [String: Any])?["schema"] as? Int == 3,
              "The shareable ZIP contains only the safe schema-3 JSON and short sharing instructions")
    let linked = exports.directory.appendingPathComponent("Wizard101-Diagnostics-build16-20990101T000000Z-AAAAAAAA.zip")
    try fm.createSymbolicLink(at: linked, withDestinationURL: firstZIP)
    try check(exports.latest() != linked, "Sharing discovery refuses linked diagnostic archives")
    let unsafePaths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": root.appendingPathComponent("linked-data").path])
    try fm.createDirectory(at: unsafePaths.data, withIntermediateDirectories: true)
    try fm.createSymbolicLink(at: unsafePaths.data.appendingPathComponent("Diagnostics"), withDestinationURL: exports.directory)
    try rejects("Diagnostic exports refuse a linked reports folder") { _ = try DiagnosticExports(paths: unsafePaths).save(report) }
}
