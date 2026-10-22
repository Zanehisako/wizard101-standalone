import Foundation
import Network

private final class ReplayEncryptedTransport: EncryptedTransport {
    var now: TimeInterval = 0
    let deadline: TimeInterval = 30
    var wire: Data
    var fragments: [Int]
    var fragmentIndex = 0
    var availableAt: TimeInterval = 0
    var pollStep: TimeInterval = 0.02
    var sent = 0
    var onRead: (() -> Void)?
    init(wire: Data, fragments: [Int] = [16384]) { self.wire = wire; self.fragments = fragments }
    func sendBytes(_ data: Data) throws { sent += data.count }
    func receiveAvailable(maximum: Int, until: TimeInterval) throws -> Data? {
        onRead?()
        if now < availableAt || wire.isEmpty { now += max(pollStep, until - now); return nil }
        let count = min(maximum, fragments[fragmentIndex % fragments.count], wire.count)
        fragmentIndex += 1; now += 0.00001
        let part = Data(wire.prefix(count)); wire.removeFirst(count); return part
    }
}

func runReliabilityTests(check: (Bool, String) throws -> Void, rejects: (String, () throws -> Void) throws -> Void) throws {
    let key = Data(repeating: 7, count: 16), iv = Data(repeating: 9, count: 16)
    let control = try KIFrame(control: true, opcode: 4, payload: Data(repeating: 0, count: 6)).encoded()
    let message = KIFrame.message(service: 7, type: 14, fields: Data("FIXTURE".utf8))
    func sealed(controls: Int, reply: KIFrame? = message) throws -> Data {
        var plain = Data()
        for _ in 0..<controls { plain.append(control) }
        if let reply { plain.append(try reply.encoded()) }
        let remainder = plain.count % 65536
        if remainder > 0 { plain.append(Data(repeating: 0, count: 65536 - remainder)) }
        let codec = try GCMChunkCodec(key: key, iv: iv, chunkSize: 65536)
        var wire = Data(), offset = 0
        while offset < plain.count {
            let end = min(plain.count, offset + 65536)
            wire.append(try codec.encode(plain.subdata(in: offset..<end))); offset = end
        }
        return wire
    }
    func reader(_ peer: ReplayEncryptedTransport, token: CancellationToken = CancellationToken()) throws -> EncryptedReplyStream {
        EncryptedReplyStream(connection: peer, token: token,
            tx: try GCMChunkCodec(key: key, iv: iv, chunkSize: 4096),
            rx: try GCMChunkCodec(key: key, iv: iv, chunkSize: 65536), sessionID: 1)
    }
    for provider in AccountProvider.allCases {
        for attempt in 0..<10 {
            let peer = ReplayEncryptedTransport(wire: try sealed(controls: 23000), fragments: [1, 3, 7, 16384, 2, 16383])
            peer.availableAt = 0.4
            let stream = try reader(peer)
            try stream.send(.message(service: 7, type: 27, fields: Data("SYNTHETIC".utf8)))
            let received = try stream.receiveMessage()
            try check(received.payload == message.payload && stream.stats.verifiedChunks > 4,
                      "Delayed encrypted reply beyond four blocks, fragmented tags and manual fresh exchange \(provider.rawValue)/\(attempt)")
            try check(stream.stats.heartbeatBatches > 1 && peer.sent <= EncryptedReplyStream.maximumSentBytes,
                      "Heartbeat batches interleave with reads under a bounded budget")
        }
    }
    // A maximum-size message crosses a chunk boundary; no partial frame escapes.
    let large = KIFrame.message(service: 7, type: 14, fields: Data(repeating: 1, count: 65400))
    let crossing = try reader(ReplayEncryptedTransport(wire: sealed(controls: 100, reply: large), fragments: [13, 16384]))
    try check(try crossing.receiveMessage().payload == large.payload && crossing.stats.verifiedChunks == 2, "Fragmented message crosses authenticated chunks")
    for corrupt in [0, 65536, 65551] {
        var wire = try sealed(controls: 2); wire[corrupt] ^= 1
        let stream = try reader(ReplayEncryptedTransport(wire: wire))
        do { _ = try stream.receiveMessage(); throw LauncherError.message("Corrupt tag was accepted") }
        catch let failure as AuthenticationTransportFailure { try check(failure == .integrity && stream.stats.verifiedChunks == 0, "Corrupt ciphertext or complete tag never releases plaintext") }
    }
    let silent = ReplayEncryptedTransport(wire: Data()); silent.pollStep = 1
    let timeout = try reader(silent)
    do { _ = try timeout.receiveMessage(); throw LauncherError.message("Silent peer was accepted") }
    catch let failure as AuthenticationTransportFailure { try check(failure == .deadline && silent.now >= 30, "One shared deadline stops a silent peer") }
    let flooding = ReplayEncryptedTransport(wire: Data())
    let outgoingBound = try reader(flooding)
    do { _ = try outgoingBound.receiveMessage(); throw LauncherError.message("Outgoing heartbeat flood was accepted") }
    catch let failure as AuthenticationTransportFailure {
        try check(failure == .trafficLimit && flooding.sent <= EncryptedReplyStream.maximumSentBytes && flooding.now < 30,
                  "A stalled peer cannot cause unbounded outgoing heartbeat traffic")
    }
    // Control traffic can continue without any credential response. It is bounded
    // by authenticated bytes, rather than an arbitrary count of valid frames.
    var controls = Data()
    for _ in 0..<570_200 { controls.append(control) }
    let hostile = ReplayEncryptedTransport(wire: Data())
    // Feed additional complete chunks without exceeding the codec's small input bound.
    let codec = try GCMChunkCodec(key: key, iv: iv, chunkSize: 65536)
    var boundedWire = Data(), offset = 0
    while offset < controls.count {
        let end = min(controls.count, offset + 65536)
        boundedWire.append(try codec.encode(controls.subdata(in: offset..<end))); offset = end
    }
    hostile.wire = boundedWire
    let limited = try reader(hostile)
    do { _ = try limited.receiveMessage(); throw LauncherError.message("Control-only flood was accepted") }
    catch let failure as AuthenticationTransportFailure { try check(failure == .trafficLimit && limited.stats.receivedBytes <= EncryptedReplyStream.maximumReceivedBytes, "Control-only peer hits the traffic bound") }
    let token = CancellationToken(), cancelling = ReplayEncryptedTransport(wire: try sealed(controls: 3), fragments: [5])
    cancelling.onRead = { token.cancel() }
    try rejects("Cancellation interrupts fragmented reception") { _ = try reader(cancelling, token: token).receiveMessage() }
    let retry = try reader(ReplayEncryptedTransport(wire: sealed(controls: 0)))
    try check(try retry.receiveMessage().payload == message.payload, "Immediate explicit retry has independent buffers, keys and deadline")
    let partial = ReplayEncryptedTransport(wire: Data(try sealed(controls: 0).dropLast(1))); partial.pollStep = 1
    let partialReader = try reader(partial)
    try rejects("A missing tag byte cannot release plaintext") { _ = try partialReader.receiveMessage() }
    try check(partialReader.stats.verifiedChunks == 0, "Incomplete tags remain unverified through timeout")
    try check(!GameActivity.shouldExitAfterHandoff(activity: .game, startedHere: false) && GameActivity.shouldExitAfterHandoff(activity: .game, startedHere: true), "Reopen stays visible and successful handoff still exits")
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("w101-reliability-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: folder) }
    let paths = PortablePaths(resources: folder, environment: ["W101_DATA_ROOT": folder.path], bundledDataRoot: nil)
    let recovery = PrefixRecovery(paths: paths)
    try check(recovery.arguments == ["-k"] && recovery.environment["WINEPREFIX"] == paths.prefix.path && recovery.server == paths.runtime.appendingPathComponent("bin/wineserver"), "Recovery addresses only the selected prefix's wineserver")
    let lock = try LauncherLock(directory: paths.state)
    try rejects("Updater lock prevents forced shutdown") { try recovery.forceQuit() }
    withExtendedLifetime(lock) {}
    let metrics = ReliabilityDiagnostics(state: paths.state)
    let secret = "SECRET_PASSWORD_TICKET_SESSION_IDENTITY"
    do { let _: Int = try metrics.measure(provider: .us, stage: .authentication) { throw LauncherError.message(secret) } } catch {}
    do { let _: Int = try metrics.measure(provider: .steam, stage: .validation) { throw CancellationError() } } catch {}
    let report = DiagnosticReport(paths: paths, mode: .capped, diagnostics: metrics)
    let output = try report.data()
    try check(!String(decoding: output, as: UTF8.self).contains(secret) && !String(decoding: try Data(contentsOf: metrics.url), as: UTF8.self).contains(secret), "Raw errors and secrets are excluded from saved diagnostics")
    let xml = Data("<preferences><VideoSettings><RECORD><IsFullscreen>1</IsFullscreen><Resolution>2560,1600</Resolution><EquipTextureDetail>High</EquipTextureDetail><Smoothing>Off</Smoothing><Password>\(secret)</Password><LastPlayer>\(secret)</LastPlayer><ShadowDetail>\(secret)</ShadowDetail></RECORD></VideoSettings></preferences>".utf8)
    try check(DiagnosticReport.settings(xml) == ["IsFullscreen": "1", "Resolution": "2560,1600", "EquipTextureDetail": "High", "Smoothing": "Off"], "Settings use numeric and enumerated graphics allowlists without account fields")
    try check(DiagnosticReport.settings(Data("<!DOCTYPE a [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><a>&x;</a>".utf8)).isEmpty, "Diagnostic settings reject external entities")
    let counts = DiagnosticReport.logCounts(Data("\(secret) VK_ERROR_DEVICE_LOST \(secret) Failed to upload texture".utf8))
    try check(counts["device_lost"] == 1 && counts["texture_upload_failure"] == 1 && !String(describing: counts).contains(secret), "Only allowlisted failure counts survive raw game logs")
    let saved = folder.appendingPathComponent("report.json"); try report.save(to: saved)
    try check((try FileManager.default.attributesOfItem(atPath: saved.path)[.posixPermissions] as? NSNumber)?.intValue == 0o600, "Saved report is private to this Mac user")
    try runReplyPollingTest(check: check, rejects: rejects)
    let snapshot = metrics.snapshot()
    try check(snapshot.attempts.count == 2 && snapshot.attempts[1].outcome == .cancelled && snapshot.counters["authenticationFailures"] == 1, "Authentication timings distinguish manual failure and cancellation")
}

// Exercise Network.framework's actual callback/pending-read behavior locally.
// Replays above also cover complete encryption and multi-block message parsing.
private func runReplyPollingTest(check: (Bool, String) throws -> Void, rejects: (String, () throws -> Void) throws -> Void) throws {
    let queue = DispatchQueue(label: "w101.loopback-test"), ready = DispatchSemaphore(value: 0)
    let listener = try NWListener(using: .tcp, on: .any)
    var peers: [NWConnection] = []
    listener.stateUpdateHandler = { state in
        if case .ready = state { ready.signal() }
        if case .failed = state { ready.signal() }
    }
    listener.newConnectionHandler = { peer in
        peers.append(peer)
        peer.stateUpdateHandler = { state in
            if case .ready = state {
                peer.send(content: Data([1, 2, 3]), completion: .idempotent)
                queue.asyncAfter(deadline: .now() + 0.15) { peer.send(content: Data([4, 5, 6]), completion: .idempotent) }
            }
        }
        peer.start(queue: queue)
    }
    listener.start(queue: queue)
    defer { listener.cancel(); queue.sync { peers.forEach { $0.cancel() } } }
    guard ready.wait(timeout: .now() + 5) == .success, let port = listener.port else { throw LauncherError.message("Loopback listener did not start") }
    for attempt in 0..<2 {
        let token = CancellationToken(), client = try KIConnection(host: "127.0.0.1", port: port.rawValue, token: token)
        defer { client.close() }
        var received = Data(), polls = 0
        while received.count < 6 {
            if let part = try client.receiveAvailable(maximum: 2, until: min(client.deadline, client.now + 0.02)) { received.append(part) }
            else { polls += 1 }
        }
        try check(received == Data([1, 2, 3, 4, 5, 6]) && polls > 0, "Timed polls preserve a single pending native read and its later bytes, retry \(attempt)")
        token.cancel()
        try rejects("Native network polling responds to cancellation") { _ = try client.receiveAvailable(maximum: 1, until: client.deadline) }
    }
}
