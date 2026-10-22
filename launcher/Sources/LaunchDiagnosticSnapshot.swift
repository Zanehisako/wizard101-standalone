import Foundation

struct RendererConfiguration: Codable {
    let experiments: [String: String]
    let workload: [String: String]
    let cpuOptimization: String
    let pipelineOptimization: String
    let synchronousQueueSubmits: String
    let stutterFix: Bool
    init(plan: LaunchPlan) {
        experiments = plan.experimentFeatures; workload = plan.workloadFeatures
        cpuOptimization = plan.cpuOptimization; pipelineOptimization = plan.pipelineOptimization
        synchronousQueueSubmits = plan.synchronousQueueSubmits; stutterFix = plan.stutterFix
    }
    var valid: Bool {
        let modes = Set(["off", "buffer", "stream", "both", "sharded", "auto", "0", "1"])
        return experiments.count <= 13 && experiments.allSatisfy { OptimizationSettings().environment[$0.key] != nil && modes.contains($0.value) }
            && workload.count <= 4 && workload.allSatisfy { ["W101_ASSET_CACHE", "W101_ASSET_WORKERS", "W101_LOCK_FIX", "W101_GPU_TEXTURE_CONVERSION"].contains($0.key) && ["0", "1", "2", "off", "auto"].contains($0.value) }
            && ["off", "constants", "locking", "both"].contains(cpuOptimization)
            && ["off", "replay", "lookup", "both"].contains(pipelineOptimization)
            && ["0", "1"].contains(synchronousQueueSubmits)
    }
}

// Only typed, allowlisted launch facts survive launcher handoff/reopening.
// No session, account identity, arguments or inherited environment is stored.
struct LaunchDiagnosticSnapshot: Codable {
    let schema: Int
    let runID: String
    let startedUTC: String
    let version: String
    let build: String
    let frameMode: FrameMode
    let renderer: RendererConfiguration
    let settings: [String: [String: String]]
    static func validRunID(_ id: String) -> Bool {
        id.hasPrefix("native-") && id.count == 43 && UUID(uuidString: String(id.dropFirst(7))) != nil
    }
    static func record(plan: LaunchPlan, run: URL) throws {
        guard validRunID(run.lastPathComponent),
              run.deletingLastPathComponent().standardizedFileURL == plan.paths.prefix.appendingPathComponent("drive_c/NativeLogs").standardizedFileURL else {
            throw LauncherError.message("Invalid launch diagnostic location.")
        }
        let value = Self(schema: 1, runID: run.lastPathComponent,
                         startedUTC: ISO8601DateFormatter().string(from: Date()),
                         version: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unavailable",
                         build: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unavailable",
                         frameMode: plan.mode, renderer: RendererConfiguration(plan: plan), settings: DiagnosticReport.gameSettings(paths: plan.paths))
        try FileManager.default.createDirectory(at: plan.paths.state, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let url = plan.paths.state.appendingPathComponent("LastLaunch.json")
        try JSONEncoder().encode(value).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
    static func load(state: URL) -> Self? {
        guard let bytes = try? Data(contentsOf: state.appendingPathComponent("LastLaunch.json")), bytes.count <= 65536,
              let value = try? JSONDecoder().decode(Self.self, from: bytes), value.schema == 1, validRunID(value.runID),
              value.startedUTC.count <= 32, ISO8601DateFormatter().date(from: value.startedUTC) != nil,
              [value.version, value.build].allSatisfy({ $0 == "unavailable" || $0.range(of: "^[0-9.]{1,16}$", options: .regularExpression) != nil }),
              value.renderer.valid, value.settings.count <= 2,
              value.settings.allSatisfy({ ["config.xml", "preferences.xml"].contains($0.key) && DiagnosticReport.validSettings($0.value) }) else { return nil }
        return value
    }
}
