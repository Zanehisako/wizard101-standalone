import Foundation

// These records contain manifest archive names and typed outcomes only. URLs,
// headers, error messages, network bodies and account/session data stay out.
final class PatchDiagnostics: @unchecked Sendable {
    enum Phase: String, Codable { case archiveBody, compressedBody, archiveHeader }
    enum Event: String, Codable { case transfer, verification, failure }
    enum Verification: String, Codable { case notPerformed, fullCRCVerified, headerCRCVerified, checksumFailed, decompressionFailed, cancelled, unavailable }
    struct Archive: Codable {
        let path: String
        let source: String
        let type: UInt32
        let size: UInt64
        let crc: UInt32
        let headerSize: UInt64
        let headerCRC: UInt32
        init(_ record: PatchRecord) {
            path = record.localPath; source = record.source; type = record.type; size = record.size; crc = record.crc
            headerSize = record.headerSize; headerCRC = record.headerCRC
        }
        var valid: Bool {
            path.range(of: #"(?i)^Data/GameData/[a-z0-9_(). +'\-]{1,180}\.wad$"#, options: .regularExpression) != nil
                && source.range(of: #"(?i)^(Windows/)?Data/GameData/[a-z0-9_(). +'\-]{1,180}\.wad$"#, options: .regularExpression) != nil
                && [1, 3, 4, 5].contains(type) && size > 0 && size <= UInt64(UInt32.max) && headerSize <= size
        }
        var streamed: Bool { [3, 5].contains(type) && headerSize > 0 }
        var stagingName: String { Data("\(source):\(size):\(crc)".utf8).sha256Hex + ".part" }
        var relevantToNovus: Bool {
            let name = URL(fileURLWithPath: path).lastPathComponent.lowercased()
            return name.hasPrefix("novus-") || name.hasPrefix("housing_novus-") || name == "root.wad"
                || name == "_shared-worlddata.wad" || name.hasPrefix("mob") || name.hasPrefix("equipment")
        }
    }
    struct Context {
        let operationID = UUID().uuidString
        let archive: Archive
        let revision: String
        let preparation: ContentPreparation
        static func make(record: PatchRecord, revision: String, preparation: ContentPreparation) -> Self? {
            let archive = Archive(record)
            guard archive.valid, validRevision(revision) else { return nil }
            return Self(archive: archive, revision: revision, preparation: preparation)
        }
    }
    struct Observation: Codable {
        let operationID: String
        let observedUTC: String
        let archive: Archive
        let revision: String
        let preparation: ContentPreparation
        let phase: Phase
        let event: Event
        let transfer: HTTPTransfer.Observation?
        let verification: Verification
        var valid: Bool {
            UUID(uuidString: operationID) != nil && validDate(observedUTC) && archive.valid
                && validRevision(revision) && (transfer?.valid ?? true)
        }
    }
    struct Manifest: Codable {
        let revision: String
        let checkedUTC: String
        var archives: [Archive]
        var valid: Bool { validRevision(revision) && validDate(checkedUTC) && archives.count <= 256 && archives.allSatisfy(\.valid) }
    }
    struct Snapshot: Codable {
        var schema = 1
        var observations: [Observation] = []
        var transfers: [Observation]? = nil
        var latestFailure: Observation? = nil
        var manifest: Manifest? = nil
    }
    static func validRevision(_ value: String) -> Bool { value.range(of: "^r[0-9]+\\.[A-Za-z0-9_]+$", options: .regularExpression) != nil && value.count <= 80 }
    static func validDate(_ value: String) -> Bool { value.count <= 32 && ISO8601DateFormatter().date(from: value) != nil }
    private let state: URL
    private let lock = NSLock()
    private var value: Snapshot
    private var pendingTransfers: [String: HTTPTransfer.Observation] = [:]
    init(state: URL) {
        self.state = state
        if let file = try? SafeInstallation(base: state).file("PatchDiagnostics.json"),
           let bytes = try? Data(contentsOf: file), bytes.count <= 512 * 1024,
           var loaded = try? JSONDecoder().decode(Snapshot.self, from: bytes), loaded.schema == 1 {
            loaded.observations = Array(loaded.observations.filter(\.valid).suffix(20))
            loaded.transfers = loaded.transfers.map { Array($0.filter { $0.valid && $0.event == .transfer }.suffix(20)) }
            if loaded.latestFailure?.valid == false { loaded.latestFailure = nil }
            if loaded.manifest?.valid == false { loaded.manifest = nil }
            value = loaded
        } else { value = Snapshot() }
    }
    func snapshot() -> Snapshot { lock.lock(); defer { lock.unlock() }; return value }
    func finish(_ context: Context?) {
        guard let context else { return }
        lock.lock(); defer { lock.unlock() }
        pendingTransfers = pendingTransfers.filter { !$0.key.hasPrefix(context.operationID + "/") }
    }
    private func save() {
        guard let file = try? SafeInstallation(base: state).file("PatchDiagnostics.json"),
              let bytes = try? JSONEncoder().encode(value) else { return }
        try? FileManager.default.createDirectory(at: state, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try? bytes.write(to: file, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }
    func manifest(_ manifest: PatchManifest) {
        guard Self.validRevision(manifest.revision) else { return }
        var archives = manifest.records.map(Archive.init).filter { $0.valid && $0.relevantToNovus }
        lock.lock(); defer { lock.unlock() }
        if let failedPath = value.latestFailure?.archive.path,
           !archives.contains(where: { $0.path == failedPath }),
           let record = manifest.records.first(where: { $0.localPath == failedPath }), Archive(record).valid {
            archives.insert(Archive(record), at: 0)
        }
        value.manifest = Manifest(revision: manifest.revision, checkedUTC: ISO8601DateFormatter().string(from: Date()), archives: Array(archives.prefix(255)))
        save()
    }
    func record(_ context: Context?, phase: Phase, transfer: HTTPTransfer.Observation) {
        append(context, phase: phase, event: .transfer, transfer: transfer, verification: .notPerformed)
    }
    func verified(_ context: Context?, phase: Phase, _ verification: Verification) {
        append(context, phase: phase, event: .verification, verification: verification)
    }
    func failed(_ context: Context?, phase: Phase, error: Error, primary: Bool) {
        let verification: Verification
        if error is CancellationError { verification = .cancelled }
        else if let failure = error as? PatchValidationFailure { verification = failure == .decompression ? .decompressionFailed : .checksumFailed }
        else { verification = .unavailable }
        append(context, phase: phase, event: .failure, verification: verification, primary: primary)
    }
    private func append(_ context: Context?, phase: Phase, event: Event, transfer: HTTPTransfer.Observation? = nil,
                        verification: Verification, primary: Bool = false) {
        guard let context else { return }
        lock.lock(); defer { lock.unlock() }
        let previous = value.observations.last { $0.operationID == context.operationID && $0.phase == phase }
        let key = context.operationID + "/" + phase.rawValue
        if let transfer { pendingTransfers[key] = transfer }
        let observation = Observation(operationID: context.operationID, observedUTC: ISO8601DateFormatter().string(from: Date()),
            archive: context.archive, revision: context.revision, preparation: context.preparation, phase: phase,
            event: event, transfer: transfer ?? pendingTransfers[key] ?? previous?.transfer, verification: verification)
        guard observation.valid else { return }
        value.observations = Array((value.observations + [observation]).suffix(20))
        if event == .transfer { value.transfers = Array(((value.transfers ?? []) + [observation]).suffix(20)) }
        if primary && event == .failure && verification != .cancelled {
            value.latestFailure = observation
            if value.manifest?.revision == context.revision,
               value.manifest?.archives.contains(where: { $0.path == context.archive.path }) == false,
               (value.manifest?.archives.count ?? 256) < 256 { value.manifest?.archives.append(context.archive) }
        }
        save()
    }
}

enum PatchValidationFailure: String, LocalizedError {
    case headerChecksum, checksum, decompression
    var errorDescription: String? {
        switch self {
        case .headerChecksum: return "A streamed archive header failed validation. Retry to download it again."
        case .checksum: return "A download failed its checksum. Retry to download it again."
        case .decompression: return "A compressed download failed validation. Retry to download it again."
        }
    }
}

// Retain rejected staging for diagnosis/rollback. A normal retry uses the
// original staging name. This helper is never applied to installed game files.
enum RejectedStaging {
    @discardableResult static func preserve(_ file: URL) throws -> URL? {
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        let safe = try SafeInstallation(base: file.deletingLastPathComponent()).file(file.lastPathComponent)
        guard (try safe.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true else {
            throw LauncherError.message("Unsafe rejected download path.")
        }
        let retained = file.appendingPathExtension("rejected-" + UUID().uuidString)
        try FileManager.default.moveItem(at: safe, to: retained)
        return retained
    }
}
