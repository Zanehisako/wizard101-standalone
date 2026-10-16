import Foundation
import CryptoKit

enum FrameMode: String, CaseIterable, Codable, Sendable {
    case capped, uncapped
    var title: String { self == .capped ? "60 FPS" : "Uncapped" }
}

struct LaunchPlan: Sendable {
    let paths: PortablePaths
    let mode: FrameMode
    let profile: Bool
    let environment: [String: String]
    var warmup: Bool = false
    var session: GameSession? = nil
    var provider: AccountProvider = .us
    var renderingCandidate: Bool = Bundle.main.object(forInfoDictionaryKey: "W101RenderingPerformanceCandidate") as? Bool ?? false
    var workloadDiagnostics: Bool = Bundle.main.object(forInfoDictionaryKey: "W101WorkloadDiagnostics") as? Bool ?? false
    var workloadPerformance: Bool = Bundle.main.object(forInfoDictionaryKey: "W101WorkloadPerformanceCandidate") as? Bool ?? false
    var workloadPerformanceEnabled: Bool = true
    var experimentDefaults: [String: String] = Bundle.main.object(forInfoDictionaryKey: "W101ExperimentDefaults") as? [String: String] ?? [:]
    var experimentSelections: [String: String]? = nil
    var experimentFeatures: [String: String] {
        let allowed = ["W101_DECOMPRESS": ["off", "buffer", "stream", "both"], "W101_WAIT_QUEUES": ["off", "sharded"], "W101_NATIVE_DECODE": ["off", "auto"], "W101_PREPARE_ASSETS": ["0", "1"], "W101_DRAW_LAYOUT_CACHE": ["0", "1"], "W101_DRAW_LAYOUT_DIRECT": ["0", "1"], "W101_GAME_REPAIR": ["0", "1"], "W101_SCENE_NODES": ["0", "1"], "W101_METAL_ARCHIVE": ["0", "1"], "W101_SCENE_TEXTURES": ["0", "1"], "W101_PREPARE_PIPELINES": ["0", "1"], "W101_PREPARE_APPEARANCE": ["0", "1"]]
        var result: [String: String] = [:]
        for (key, values) in allowed {
            let disabled = values[0]
            let value: String
            if let selections = experimentSelections {
                value = experimentDefaults[key] != nil ? (selections[key] ?? disabled) : disabled
            } else {
                value = experimentDefaults[key] != nil && workloadPerformanceEnabled ? (environment[key] ?? experimentDefaults[key]!) : disabled
            }
            result[key] = key == "W101_DRAW_LAYOUT_CACHE" && experimentDefaults["W101_DRAW_LAYOUT_DIRECT"] != nil
                ? "0" : (values.contains(value) ? value : disabled)
        }
        return result
    }
    var workloadFeatureDefaults: [String: String] = Bundle.main.object(forInfoDictionaryKey: "W101WorkloadPerformanceDefaults") as? [String: String] ?? [:]
    var workloadFeatures: [String: String] {
        let allowed = ["W101_ASSET_CACHE": ["0", "1"], "W101_ASSET_WORKERS": ["0", "2"], "W101_LOCK_FIX": ["0"], "W101_GPU_TEXTURE_CONVERSION": ["off", "auto"]]
        var result: [String: String] = [:]
        for (key, values) in allowed {
            let value = workloadPerformance && (workloadPerformanceEnabled || !experimentDefaults.isEmpty) ? (environment[key] ?? workloadFeatureDefaults[key] ?? values[0]) : values[0]
            result[key] = values.contains(value) ? value : values[0]
        }
        return result
    }
    var stutterFix: Bool {
        if workloadDiagnostics { return false }
        if let value = environment["DXVK_W101_STUTTER_FIX"] { return value == "1" }
        return renderingCandidate
    }
    var gameDirectory: URL { paths.game }
    var pipelineOptimization: String {
        if workloadDiagnostics { return "off" }
        if renderingCandidate || stutterFix { return "off" }
        let value = environment["DXVK_W101_PIPELINE_OPT"] ?? "off"
        return ["off", "replay", "lookup", "both"].contains(value) ? value : "off"
    }
    var cpuOptimization: String {
        if workloadDiagnostics { return "off" }
        if renderingCandidate || stutterFix { return "off" }
        let value = environment["DXVK_W101_CPU_OPT"] ?? "off"
        return ["off", "constants", "locking", "both"].contains(value) ? value : "off"
    }
    var synchronousQueueSubmits: String {
        if workloadDiagnostics { return "1" }
        if renderingCandidate || stutterFix { return "1" }
        return environment["MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS"] == "0" ? "0" : "1"
    }
    var executable: URL { paths.wine }
    var arguments: [String] {
        var args = ["C:\\ProgramData\\KingsIsle Entertainment\\Wizard101\\Bin\\WizardGraphicalClient.exe",
                    "-L", "login.us.wizard101.com", "12000", "-PT", "0"]
        if let session { args += ["-U", "..\(session.userID)", session.passKey] }
        return args
    }
    var childEnvironment: [String: String] {
        var result = paths.environment(environment)
        // The native client exchanges the Mac Steam ticket for a KingsIsle
        // session. The Windows child uses that session, without a second Steam
        // client or the Windows-only -ST initialization path.
        result.removeValue(forKey: "SteamAppId"); result.removeValue(forKey: "SteamGameId")
        result["DXVK_FRAME_RATE"] = mode == .capped ? "60" : "0"
        result["DXVK_W101_LIMITER"] = "legacy"
        result["DXVK_DIAGNOSTICS"] = "0"
        result["DXVK_W101_CACHE"] = "1"
        result["DXVK_W101_CATALOG"] = workloadDiagnostics ? "0" : "1"
        result["DXVK_W101_WARMUP"] = warmup && !workloadDiagnostics ? "1" : "0"
        result["DXVK_ASYNC"] = "0"
        result["DXVK_W101_PIPELINE_OPT"] = pipelineOptimization
        result["DXVK_W101_CPU_OPT"] = cpuOptimization
        result["DXVK_W101_STUTTER_FIX"] = stutterFix ? "1" : "0"
        result["MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS"] = synchronousQueueSubmits
        for (key, value) in workloadFeatures { result[key] = value }
        for (key, value) in experimentFeatures { result[key] = value }
        result.removeValue(forKey: "W101_METAL_ARCHIVE_PATH")
        result.removeValue(forKey: "W101_METAL_ARCHIVE_KEY")
        if experimentFeatures["W101_METAL_ARCHIVE"] == "1" {
            let renderer = gameDirectory.appendingPathComponent("Bin/d3d9.dll")
            let backend = paths.runtime.appendingPathComponent("lib/libMoltenVK.dylib")
            if let bytes = try? Data(contentsOf: renderer), let metal = try? Data(contentsOf: backend) {
                result["W101_METAL_ARCHIVE_PATH"] = paths.state.appendingPathComponent("MetalArchive").path
                result["W101_METAL_ARCHIVE_KEY"] = Data((bytes.sha256Hex + metal.sha256Hex).utf8).sha256Hex
            } else {
                result["W101_METAL_ARCHIVE"] = "0"
            }
        }
        result.removeValue(forKey: "W101_ASSET_CACHE_FILE")
        if experimentDefaults["W101_PREPARE_ASSETS"] != nil {
            result["W101_ASSET_CACHE_FILE"] = "C:\\graphics-patch-cache\\Wizard101\\known-assets.w101assets"
        }
        for key in ["W101_ARRIVAL_PATH", "W101_ARRIVAL_KEY", "W101_ARRIVAL_TEST"] { result.removeValue(forKey: key) }
        if experimentDefaults["W101_PREPARE_PIPELINES"] != nil {
            let files = [gameDirectory.appendingPathComponent("Bin/d3d9.dll"),
                         paths.runtime.appendingPathComponent("lib/libMoltenVK.dylib"),
                         gameDirectory.appendingPathComponent("Bin/WizardGraphicalClient.exe"),
                         gameDirectory.appendingPathComponent("Bin/d3dx9_43.dll")]
            let hashes = files.compactMap { try? Data(contentsOf: $0).sha256Hex }
            if hashes.count == files.count {
                result["W101_ARRIVAL_PATH"] = "C:\\graphics-patch-cache\\Wizard101\\Arrival"
                result["W101_ARRIVAL_KEY"] = Data((hashes.joined() + ProcessInfo.processInfo.operatingSystemVersionString).utf8).sha256Hex
            } else { result["W101_PREPARE_PIPELINES"] = "0" }
        }
        result.removeValue(forKey: "W101_ASSET_PREPARE_TEST")
        result.removeValue(forKey: "W101_DRAW_LAYOUT_TEST")
        result.removeValue(forKey: "W101_DRAW_LAYOUT_DIRECT_TEST")
        result.removeValue(forKey: "W101_DECODE_HELPER")
        if experimentFeatures["W101_NATIVE_DECODE"] == "auto" {
            result["W101_DECODE_HELPER"] = paths.runtime.appendingPathComponent("bin/w101decode-helper").path
        }
        result.removeValue(forKey: "W101_PERFORMANCE_TEST")
        result.removeValue(forKey: "W101_PERFORMANCE_TEST_FORCE_16BIT")
        result.removeValue(forKey: "W101_NATIVE_TEST")
        for key in ["W101_LAUNCHER_WAIT_MS", "W101_LAUNCHER_DIAGNOSTICS", "DXVK_W101_PROFILE", "DXVK_SHADER_DUMP_PATH"] { result.removeValue(forKey: key) }
        return result
    }
    func validateInstallation() throws {
        try paths.validateRuntime()
        guard FileManager.default.fileExists(atPath: gameDirectory.appendingPathComponent("Bin/WizardGraphicalClient.exe").path),
              FileManager.default.fileExists(atPath: gameDirectory.appendingPathComponent("Bin/d3d9.dll").path),
              FileManager.default.fileExists(atPath: paths.state.appendingPathComponent("setup-complete.json").path) else {
            throw LauncherError.message("Install Wizard101 or import an existing installation to begin.")
        }
    }
    func validate() throws {
        try validateInstallation()
        try validateSession()
    }
    func validateSession() throws {
        guard let session else { throw LauncherError.message("Sign in before starting the game.") }
        guard session.provider == provider else { throw LauncherError.message("Sign in again with the selected \(provider.title) account type.") }
        try session.validate()
    }
    func prepareLogs() throws -> (URL, [String: String]) {
        let id = "native-" + UUID().uuidString
        let run = paths.prefix.appendingPathComponent("drive_c/NativeLogs/\(id)")
        try FileManager.default.createDirectory(at: run.appendingPathComponent("logs"), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.createDirectory(at: run.appendingPathComponent("shaders"), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        var env = childEnvironment
        if env["W101_ASSET_CACHE_FILE"] != nil {
            try? FileManager.default.createDirectory(at: paths.prefix.appendingPathComponent("drive_c/graphics-patch-cache/Wizard101"), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        }
        if env["W101_ARRIVAL_PATH"] != nil {
            try? FileManager.default.createDirectory(at: paths.prefix.appendingPathComponent("drive_c/graphics-patch-cache/Wizard101/Arrival"), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        }
        env["DXVK_LOG_PATH"] = "C:\\NativeLogs\\\(id)\\logs"
        env["DXVK_FAILURE_DUMP_PATH"] = "C:\\NativeLogs\\\(id)\\shaders"
        if profile {
            env["DXVK_W101_PROFILE"] = "C:\\NativeLogs\\\(id)\\timing.csv"
            env["DXVK_W101_PROFILE_SECONDS"] = "900"
            if workloadDiagnostics {
                env["DXVK_W101_PROFILE_MAX_BYTES"] = String(112 * 1024 * 1024)
                env["W101_WORKLOAD_NATIVE"] = run.appendingPathComponent("native.jsonl").path
                env["W101_WORKLOAD_THREADS"] = run.appendingPathComponent("threads.jsonl").path
                env["W101_WORKLOAD_SECONDS"] = "900"
                env["W101_WORKLOAD_DEADLINE_UNIX_US"] = String(Int64(Date().timeIntervalSince1970 * 1_000_000) + 900_000_000)
                if workloadPerformance { env["W101_WORKLOAD_LOCKS"] = run.appendingPathComponent("locks.jsonl").path }
            }
        }
        let dll = gameDirectory.appendingPathComponent("Bin/d3d9.dll")
        let rendererHash = (try? Data(contentsOf: dll).sha256Hex) ?? "unavailable"
        func digest(_ files: [URL]) -> String {
            var data = Data()
            for file in files.sorted(by: { $0.path < $1.path }) {
                guard let bytes = try? Data(contentsOf: file) else { continue }
                data.append(Data(file.lastPathComponent.utf8)); data.append(0); data.append(Data(bytes.sha256Hex.utf8))
            }
            return data.sha256Hex
        }
        let cacheDirectory = paths.prefix.appendingPathComponent("drive_c/graphics-patch-cache/Wizard101")
        let cacheFiles = ((try? FileManager.default.contentsOfDirectory(at: cacheDirectory, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension == "vkcache" || $0.pathExtension == "w101shaders" }
            + [gameDirectory.appendingPathComponent("Bin/WizardGraphicalClient.dxvk-cache")]
        var metadata: [String: Any] = ["started_at": ISO8601DateFormatter().string(from: Date()), "entrypoint": "WizardGraphicalClient.exe", "frame_rate": mode.rawValue, "limiter": "legacy", "profiling_requested": profile, "profile_max_seconds": 900, "warmup_requested": warmup, "startup_wait_max_seconds": 10, "renderer_sha256": rendererHash]
        metadata["pipeline_optimization"] = pipelineOptimization
        metadata["cpu_optimization"] = cpuOptimization
        metadata["stutter_fix"] = stutterFix
        metadata["process_cpu_sampling_interval_seconds"] = profile && !workloadDiagnostics ? 1 : 0
        metadata["synchronous_queue_submits"] = synchronousQueueSubmits
        metadata["async"] = false
        metadata["experiments"] = experimentFeatures
        metadata["prepare_known_assets"] = experimentFeatures["W101_PREPARE_ASSETS"] == "1"
        metadata["reuse_character_draw_layouts"] = experimentFeatures["W101_DRAW_LAYOUT_CACHE"] == "1"
        metadata["faster_draw_layouts"] = experimentFeatures["W101_DRAW_LAYOUT_DIRECT"] == "1"
        metadata["game_repair_requested"] = experimentFeatures["W101_GAME_REPAIR"] == "1"
        metadata["game_repair_expected_hooks"] = experimentFeatures["W101_GAME_REPAIR"] == "1"
            ? [["rva": 0x2239020, "sha256": "5d67b2171d7d6f6f65bd27ea33557c072985a9392d3f3ce40cf8ce8fa30e8d1e", "getter_rva": 0x224ed40, "getter_signature": "488d4110c3"]] : []
        metadata["draw_layout_cache_available"] = experimentDefaults["W101_DRAW_LAYOUT_CACHE"] != nil && experimentDefaults["W101_DRAW_LAYOUT_DIRECT"] == nil
        metadata["draw_layout_cache_max_entries"] = 256
        metadata["draw_layout_cache_max_bytes"] = 1024 * 1024
        metadata["asset_preparation_cutoff_seconds"] = NSNull()
        metadata["persistent_asset_cache_max_bytes"] = 32 * 1024 * 1024
        metadata["asset_memory_max_bytes"] = 128 * 1024 * 1024
        if workloadPerformance {
            metadata["workload_performance"] = true
            metadata["workload_features"] = workloadFeatures
            metadata["game_executable_sha256"] = (try? Data(contentsOf: gameDirectory.appendingPathComponent("Bin/WizardGraphicalClient.exe")).sha256Hex) ?? "unavailable"
            metadata["native_d3dx_file_sha256"] = (try? Data(contentsOf: gameDirectory.appendingPathComponent("Bin/d3dx9_43.dll")).sha256Hex) ?? "unavailable"
            metadata["lock_fix_status"] = "Unresolved game lock; no bypass or semantics change"
            metadata["draw_timing_stride"] = 256
            metadata["lock_max_bytes"] = 4 * 1024 * 1024
        }
        if workloadDiagnostics {
            metadata["workload_diagnostics"] = true
            metadata["warmup_requested"] = false
            metadata["profile_max_bytes"] = 256 * 1024 * 1024
            metadata["renderer_max_bytes"] = 112 * 1024 * 1024
            metadata["native_max_bytes"] = 128 * 1024 * 1024
            metadata["thread_map_max_bytes"] = 1024 * 1024
            metadata["sample_interval_ms"] = 250
            metadata["native_thread_cpu_sampling_interval_seconds"] = profile ? 0.25 : 0
            metadata["read_hook_scope"] = "Main executable imports. Async admissions, dynamic calls, DLL reads and mapped faults are separate or uncovered."
            metadata["stack_identity_policy"] = "Unresolved stacks remain unidentified. Thread names are not identity evidence."
        }
        if profile {
            metadata["starting_cache_sha256"] = digest(cacheFiles)
            metadata["settings_sha256"] = digest(["config.xml", "preferences.xml"].map { gameDirectory.appendingPathComponent("Bin/\($0)") })
            metadata["clock_unix_us"] = Int64(Date().timeIntervalSince1970 * 1_000_000)
            metadata["clock_system_uptime_seconds"] = ProcessInfo.processInfo.systemUptime
        }
        if let label = environment["W101_COMPARISON_LABEL"], label.range(of: "^(pair[1-3]-(baseline|candidate)(-restart)?|screen-(baseline|candidate)|learning|diagnostic|trace-cpu|trace-gpu|persistence)$", options: .regularExpression) != nil {
            metadata["comparison_label"] = label
        }
        if let value = environment["W101_COMPARISON_METADATA"], let bytes = value.data(using: .utf8),
           let comparison = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any] {
            for key in ["seed_sha256", "starting_inputs_sha256", "seed_restored", "heavyweight_trace", "route", "persistence_restart"] {
                if let value = comparison[key] { metadata[key] = value }
            }
            if comparison["seed_restored"] as? Bool == true {
                // Installed-content checks can run between restore and handoff.
                // A scored game must still see the frozen bytes at this point.
                let seed = paths.data.deletingLastPathComponent().appendingPathComponent("Seed/manifest.json")
                let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: seed)) as? [String: Any]
                guard manifest?["seed_sha256"] as? String == comparison["seed_sha256"] as? String,
                      let files = manifest?["files"] as? [String: [String: Any]],
                      let roots = manifest?["roots"] as? [String] else {
                    throw LauncherError.message("The comparison seed is missing or changed. Restore the seed and retry.")
                }
                var actual = Set<String>()
                let dataRoot = paths.data.resolvingSymlinksInPath().path
                for root in roots {
                    let url = paths.data.appendingPathComponent(root)
                    var directory: ObjCBool = false
                    guard FileManager.default.fileExists(atPath: url.path, isDirectory: &directory) else { continue }
                    let urls = directory.boolValue
                        ? (FileManager.default.enumerator(at: url, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey])?.allObjects as? [URL] ?? [])
                        : [url]
                    for file in urls {
                        let info = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
                        guard info.isSymbolicLink != true else { throw LauncherError.message("Comparison inputs contain a symbolic link.") }
                        if info.isRegularFile == true {
                            let resolved = file.resolvingSymlinksInPath().path
                            guard resolved.hasPrefix(dataRoot + "/") else { throw LauncherError.message("Comparison inputs leave the isolated folder.") }
                            actual.insert(String(resolved.dropFirst(dataRoot.count + 1)))
                        }
                    }
                }
                guard actual == Set(files.keys) else { throw LauncherError.message("Archives or tracking files changed before game handoff. Restore the seed and retry.") }
                for (relative, expected) in files {
                    let file = paths.data.appendingPathComponent(relative)
                    guard file.resolvingSymlinksInPath().path.hasPrefix(dataRoot + "/") else {
                        throw LauncherError.message("Comparison inputs leave the isolated folder.")
                    }
                    let handle = try FileHandle(forReadingFrom: file)
                    defer { try? handle.close() }
                    var hash = SHA256()
                    while let block = try handle.read(upToCount: 1024 * 1024), !block.isEmpty { hash.update(data: block) }
                    let digest = hash.finalize().map { String(format: "%02x", $0) }.joined()
                    guard digest == expected["sha256"] as? String else {
                        throw LauncherError.message("Frozen comparison input changed before game handoff. Restore the seed and retry.")
                    }
                }
                metadata["handoff_inputs_verified"] = true
            }
        }
        try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys]).write(to: run.appendingPathComponent("session.json"), options: .atomic)
        return (run, env)
    }
}

enum LauncherError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let message): return message }
    }
}

enum GameActivity: String {
    case idle, launcher, game
    static func parse(_ processNames: String) -> GameActivity {
        // Only executable names are inspected, never login arguments.
        let names = processNames.split(separator: "\n").map {
            $0.trimmingCharacters(in: .whitespaces).lowercased()
                .replacingOccurrences(of: "\\", with: "/")
                .split(separator: "/").last.map(String.init) ?? ""
        }
        if names.contains("wizardgraphicalclient.exe") { return .game }
        if names.contains("wizardlauncher.exe") || names.contains("wizard101.exe") { return .launcher }
        return .idle
    }
    static func scan() throws -> GameActivity {
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-axo", "comm="]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw LauncherError.message("Unable to check running games. Close other Wizard101 sessions and try again.")
        }
        return parse(String(decoding: data, as: UTF8.self))
    }
}
