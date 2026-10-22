import Foundation

// A user may choose the game's normal streaming for one launch after an
// preload cannot finish. Required files and integrity checks remain
// enforced, and the next ordinary launch attempts the full preload again.
struct ContentRecovery {
    private(set) var canOfferStreaming = false
    private(set) var streamingOnce = false
    mutating func failed(_ error: Error) {
        canOfferStreaming = (error as? PatchFileFailure)?.allowsStreaming == true
        streamingOnce = false
    }
    mutating func chooseStreaming() {
        guard canOfferStreaming else { return }
        canOfferStreaming = false; streamingOnce = true
    }
    mutating func clear() { canOfferStreaming = false; streamingOnce = false }
    mutating func preparationForPlay() -> ContentPreparation {
        let selected: ContentPreparation = streamingOnce ? .startup : .visuals
        clear(); return selected
    }
}

// A dated observation of official archive checks, never a substitute for the
// current manifest and file fingerprints checked again before sign-in.
struct ContentReadiness: Codable {
    enum Status: String, Codable { case checking, incomplete, ready }
    let schema: Int
    let revision: String
    let preparation: ContentPreparation
    let status: Status
    let selectedArchives: Int
    let verifiedArchives: Int
    let expectedBytes: UInt64
    let checkedUTC: String

    init(manifest: PatchManifest, preparation: ContentPreparation, inventory: PatchInventory? = nil) {
        let selected = manifest.records.filter { preparation.requiresFullArchive($0) }
        let missing = Set(inventory?.needed.map { $0.localPath } ?? selected.map { $0.localPath })
        schema = 1; revision = manifest.revision; self.preparation = preparation
        selectedArchives = selected.count
        verifiedArchives = inventory == nil ? 0 : selected.filter { !missing.contains($0.localPath) }.count
        expectedBytes = selected.reduce(0) { $0 + $1.size }
        status = inventory == nil ? .checking : verifiedArchives == selectedArchives ? .ready : .incomplete
        checkedUTC = ISO8601DateFormatter().string(from: Date())
    }
    var summary: String {
        if status == .ready && preparation == .visuals { return "Game visuals verified. Updates are checked before sign-in." }
        if preparation == .visuals && status == .incomplete {
            return "Visual preload incomplete: \(verifiedArchives) of \(selectedArchives) archives verified. Play retries the preload."
        }
        return "All game visuals are downloaded and verified before sign-in. Music and dialogue can stream during play."
    }
    func save(state: URL) throws {
        let url = state.appendingPathComponent("ContentReadiness.json")
        try JSONEncoder().encode(self).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
    static func load(state: URL) -> Self? {
        let url = state.appendingPathComponent("ContentReadiness.json")
        guard let bytes = try? Data(contentsOf: url), bytes.count <= 65536,
              let value = try? JSONDecoder().decode(Self.self, from: bytes), value.schema == 1,
              value.revision.range(of: "^r[0-9]+\\.[A-Za-z0-9_]+$", options: .regularExpression) != nil,
              (0...100000).contains(value.selectedArchives), (0...value.selectedArchives).contains(value.verifiedArchives),
              value.status != .ready || value.verifiedArchives == value.selectedArchives,
              value.checkedUTC.count <= 32, ISO8601DateFormatter().date(from: value.checkedUTC) != nil else { return nil }
        return value
    }
}
