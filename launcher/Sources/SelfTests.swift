import Foundation
import Darwin

// Entirely synthetic tests: no account, installed game, shader capture, or repo.
func runSelfTests() throws {
    let fm = FileManager.default, token = CancellationToken()
    let root = fm.temporaryDirectory.appendingPathComponent("w101-synthetic-\(UUID().uuidString)")
    try fm.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? fm.removeItem(at: root) }
    var checks: [String] = []
    func check(_ condition: Bool, _ name: String) throws {
        guard condition else { throw LauncherError.message(name) }; checks.append(name)
    }
    func rejects(_ name: String, _ body: () throws -> Void) throws {
        var rejected = false; do { try body() } catch { rejected = true }; try check(rejected, name)
    }
    try runSetupTests(check: check, rejects: rejects)
    try runAccountTests(check: check, rejects: rejects)
    try runAuthenticationTests(check: check, rejects: rejects)
    try runReliabilityTests(check: check, rejects: rejects)
    try runVisualContentTests(check: check, rejects: rejects)
    let presentationSuite = "org.wizard101native.presentation.test." + UUID().uuidString
    let presentationDefaults = UserDefaults(suiteName: presentationSuite)!
    defer { presentationDefaults.removePersistentDomain(forName: presentationSuite) }
    let presentation = LauncherPreferences(defaults: presentationDefaults)
    try check(presentation.effects && presentation.frameMode == .capped, "Fresh launcher enables effects and preserves 60 FPS")
    presentation.effects = false; presentation.frameMode = .uncapped
    let reloadedPresentation = LauncherPreferences(defaults: presentationDefaults)
    try check(!reloadedPresentation.effects && reloadedPresentation.frameMode == .uncapped, "Effects and frame rate survive launcher restart")
    presentationDefaults.set("invalid", forKey: "launcher.frameMode")
    try check(presentation.frameMode == .capped, "Invalid saved frame rate falls back to 60 FPS")
    try check(presentationDefaults.object(forKey: "optimization.preparePipelines") == nil && presentationDefaults.object(forKey: "W101_CAPTURE_TIMING") == nil, "Presentation preferences do not enable game experiments or capture")
    let paths = PortablePaths(resources: root.appendingPathComponent("App Resources"), environment: ["W101_DATA_ROOT": root.appendingPathComponent("Data with 'spaces;literal'").path])
    let comparisonPaths = PortablePaths(resources: root, environment: [:], bundledDataRoot: root.appendingPathComponent("Comparison").path)
    let overriddenPaths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": paths.data.path], bundledDataRoot: comparisonPaths.data.path)
    try check(comparisonPaths.data.path == root.appendingPathComponent("Comparison").path && overriddenPaths.data == paths.data, "Comparison app data root and explicit override")
    let env = ["CROSSOVER_WINE": "/do/not/use", "CX_BOTTLE_PATH": "/do/not/use", "WINEPREFIX": "/do/not/use", "DYLD_LIBRARY_PATH": "/do/not/use", "DXVK_W101_LIMITER": "sleep", "DXVK_W101_PROFILE": "inherited.csv"]
    var capped = LaunchPlan(paths: paths, mode: .capped, profile: false, environment: env, renderingCandidate: false, workloadDiagnostics: false, workloadPerformance: false, experimentDefaults: [:])
    let uncapped = LaunchPlan(paths: paths, mode: .uncapped, profile: true, environment: env, renderingCandidate: false, workloadDiagnostics: false, workloadPerformance: false, experimentDefaults: [:])
    capped.session = GameSession(userID: 123, passKey: "SYNTHETIC+SESSION=", expires: Date().addingTimeInterval(120))
    try check(capped.arguments.first?.hasSuffix("WizardGraphicalClient.exe") == true && !capped.arguments.contains("--bottle"), "Plain Wine direct launch")
    try check(capped.arguments.suffix(3) == ["-U", "..123", "SYNTHETIC+SESSION="], "Literal session arguments")
    try check(capped.childEnvironment["WINEPREFIX"] == paths.prefix.path && capped.executable == paths.wine, "Explicit runtime and isolated prefix")
    for key in ["CROSSOVER_WINE", "CX_BOTTLE_PATH", "DYLD_LIBRARY_PATH"] { try check(capped.childEnvironment[key] == nil, "Discard inherited \(key)") }
    try check(capped.childEnvironment["DXVK_FRAME_RATE"] == "60" && uncapped.childEnvironment["DXVK_FRAME_RATE"] == "0", "60 FPS and Uncapped")
    try check(capped.childEnvironment["DXVK_W101_LIMITER"] == "legacy", "Preserve default pacing")
    try check(capped.childEnvironment["DXVK_W101_WARMUP"] == "0", "Warm-up stays opt-in until gameplay acceptance")
    try check(capped.childEnvironment["DXVK_W101_PIPELINE_OPT"] == "off" && capped.childEnvironment["MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS"] == "1", "Performance defaults preserve baseline")
    for value in ["off", "replay", "lookup", "both", "invalid"] {
        let plan = LaunchPlan(paths: paths, mode: .capped, profile: true, environment: ["DXVK_W101_PIPELINE_OPT": value, "MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS": "0"], renderingCandidate: false, workloadDiagnostics: false, workloadPerformance: false, experimentDefaults: [:])
        let (run, child) = try plan.prepareLogs()
        let recorded = try JSONSerialization.jsonObject(with: Data(contentsOf: run.appendingPathComponent("session.json"))) as? [String: Any]
        let expected = value == "invalid" ? "off" : value
        try check(child["DXVK_W101_PIPELINE_OPT"] == expected && recorded?["pipeline_optimization"] as? String == expected && recorded?["synchronous_queue_submits"] as? String == "0" && child["DXVK_ASYNC"] == "0", "Performance mode and queue submission metadata: \(value)")
    }
    try check(capped.childEnvironment["DXVK_W101_STUTTER_FIX"] == "0", "Renderer switch defaults off")
    for candidate in [false, true] {
        for value in [nil, "0", "1", "invalid"] as [String?] {
            var env = ["DXVK_W101_CPU_OPT": "both", "DXVK_W101_PIPELINE_OPT": "both", "MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS": "0"]
            if let value { env["DXVK_W101_STUTTER_FIX"] = value }
            let plan = LaunchPlan(paths: paths, mode: .capped, profile: false, environment: env, renderingCandidate: candidate, workloadDiagnostics: false, workloadPerformance: false, experimentDefaults: [:])
            let expected = value.map { $0 == "1" } ?? candidate
            let (run, child) = try plan.prepareLogs()
            let recorded = try JSONSerialization.jsonObject(with: Data(contentsOf: run.appendingPathComponent("session.json"))) as? [String: Any]
            try check(child["DXVK_W101_STUTTER_FIX"] == (expected ? "1" : "0") && recorded?["stutter_fix"] as? Bool == expected && child["DXVK_W101_PROFILE"] == nil, "Rendering switch and opt-in capture: \(candidate)/\(value ?? "default")")
            if candidate || expected {
                try check(child["DXVK_W101_CPU_OPT"] == "off" && child["DXVK_W101_PIPELINE_OPT"] == "off" && child["MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS"] == "1" && child["DXVK_ASYNC"] == "0", "Rendering candidate isolates experiment: \(value ?? "default")")
            }
        }
    }
    var warmed = capped; warmed.warmup = true
    try check(capped.childEnvironment["DXVK_W101_CPU_OPT"] == "off", "CPU optimization defaults off")
    for value in ["off", "constants", "locking", "both", "invalid"] {
        let plan = LaunchPlan(paths: paths, mode: .capped, profile: true, environment: ["DXVK_W101_CPU_OPT": value], renderingCandidate: false, workloadDiagnostics: false, workloadPerformance: false, experimentDefaults: [:])
        let (run, child) = try plan.prepareLogs()
        let recorded = try JSONSerialization.jsonObject(with: Data(contentsOf: run.appendingPathComponent("session.json"))) as? [String: Any]
        let expected = value == "invalid" ? "off" : value
        try check(child["DXVK_W101_CPU_OPT"] == expected && recorded?["cpu_optimization"] as? String == expected && recorded?["process_cpu_sampling_interval_seconds"] as? Int == 1, "CPU mode and bounded sample metadata: \(value)")
    }
    try check(warmed.childEnvironment["DXVK_W101_WARMUP"] == "1" && warmed.childEnvironment["DXVK_W101_CATALOG"] == "1", "Explicit learned-shader warm-up toggle")
    let (logs, child) = try capped.prepareLogs()
    try check(!String(decoding: try Data(contentsOf: logs.appendingPathComponent("session.json")), as: UTF8.self).contains("SYNTHETIC"), "No credentials in launch metadata")
    try check(child["DXVK_W101_PROFILE"] == nil, "Capture remains opt-in")
    let (_, capture) = try uncapped.prepareLogs()
    try check(capture["DXVK_W101_PROFILE_SECONDS"] == "900", "Bounded route capture includes loading and revisits")
    let hostile = ["DXVK_W101_STUTTER_FIX":"1", "DXVK_W101_PIPELINE_OPT":"both", "DXVK_W101_CPU_OPT":"both", "MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS":"0", "W101_WORKLOAD_NATIVE":"inherited.jsonl"]
    let workloadOff = LaunchPlan(paths: paths, mode: .capped, profile: false, environment: hostile, warmup: true, renderingCandidate: true, workloadDiagnostics: true, workloadPerformance: false, experimentDefaults: [:])
    let (_, offEnvironment) = try workloadOff.prepareLogs()
    try check(!workloadOff.stutterFix && workloadOff.cpuOptimization == "off" && workloadOff.pipelineOptimization == "off" && workloadOff.synchronousQueueSubmits == "1", "Workload diagnostics disable earlier candidates and force baseline submits")
    try check(offEnvironment["W101_WORKLOAD_NATIVE"] == nil && offEnvironment["DXVK_W101_PROFILE"] == nil && offEnvironment["DXVK_W101_WARMUP"] == "0" && offEnvironment["DXVK_W101_CATALOG"] == "0", "Disabled workload capture has no recording paths or warm-up")
    let workloadOn = LaunchPlan(paths: paths, mode: .capped, profile: true, environment: hostile, workloadDiagnostics: true, workloadPerformance: false, experimentDefaults: [:])
    let (workloadLogs, workloadEnvironment) = try workloadOn.prepareLogs()
    var workloadCandidate = LaunchPlan(paths: paths, mode: .capped, profile: false, environment: ["W101_LOCK_FIX":"1", "W101_PERFORMANCE_TEST":"1"], workloadDiagnostics: true, workloadPerformance: true, experimentDefaults: [:], workloadFeatureDefaults: ["W101_ASSET_CACHE":"1", "W101_ASSET_WORKERS":"2", "W101_GPU_TEXTURE_CONVERSION":"auto"])
    try check(workloadCandidate.childEnvironment["W101_ASSET_CACHE"] == "1" && workloadCandidate.childEnvironment["W101_ASSET_WORKERS"] == "2" && workloadCandidate.childEnvironment["W101_GPU_TEXTURE_CONVERSION"] == "auto", "Performance candidate uses verified independent defaults")
    try check(workloadCandidate.childEnvironment["W101_LOCK_FIX"] == "0" && workloadCandidate.childEnvironment["W101_PERFORMANCE_TEST"] == nil, "Unresolved game lock and verification bypass cannot be enabled by launcher")
    workloadCandidate.workloadPerformanceEnabled = false
    try check(workloadCandidate.childEnvironment["W101_ASSET_CACHE"] == "0" && workloadCandidate.childEnvironment["W101_ASSET_WORKERS"] == "0" && workloadCandidate.childEnvironment["W101_GPU_TEXTURE_CONVERSION"] == "off", "Comparison checkbox restores original preparation paths")
    workloadCandidate.workloadPerformanceEnabled = true
    var decompression = workloadCandidate
    decompression.experimentDefaults = ["W101_DECOMPRESS": "both"]
    decompression.workloadFeatureDefaults = ["W101_ASSET_CACHE": "1", "W101_ASSET_WORKERS": "2"]
    decompression.workloadPerformanceEnabled = false
    try check(decompression.childEnvironment["W101_DECOMPRESS"] == "off" && decompression.childEnvironment["W101_ASSET_CACHE"] == "1" && decompression.childEnvironment["W101_ASSET_WORKERS"] == "2", "Experiment comparison keeps existing cache and workers")
    decompression.workloadPerformanceEnabled = true
    try check(decompression.childEnvironment["W101_DECOMPRESS"] == "both" && decompression.childEnvironment["W101_WAIT_QUEUES"] == "off" && decompression.childEnvironment["W101_NATIVE_DECODE"] == "off", "Each app enables only its own experiment")
    let preferencesName = "org.wizard101native.optimizations.test." + UUID().uuidString
    let preferences = UserDefaults(suiteName: preferencesName)!
    defer { preferences.removePersistentDomain(forName: preferencesName) }
    try check(OptimizationSettings.load(from: preferences) == OptimizationSettings(), "Combined launcher starts with all experiments off")
    preferences.set(true, forKey: "optimization.drawLayouts")
    let upgraded = OptimizationSettings.load(from: preferences)
    try check(upgraded.drawLayouts && !upgraded.directLayouts && !upgraded.gameRepair && !upgraded.sceneNodes && !upgraded.metalArchive && !upgraded.sceneTextures && !upgraded.preparePipelines && !upgraded.prepareAppearance, "Upgrade retains saved selections and starts new switches off")
    let syntheticRenderer = paths.game.appendingPathComponent("Bin/d3d9.dll")
    try fm.createDirectory(at: syntheticRenderer.deletingLastPathComponent(), withIntermediateDirectories: true)
    let rendererBytes = Data("synthetic renderer identity".utf8)
    try rendererBytes.write(to: syntheticRenderer)
    let syntheticMetal = paths.runtime.appendingPathComponent("lib/libMoltenVK.dylib")
    try fm.createDirectory(at: syntheticMetal.deletingLastPathComponent(), withIntermediateDirectories: true)
    let metalBytes = Data("synthetic Metal identity".utf8)
    try metalBytes.write(to: syntheticMetal)
    let archiveKey = Data((rendererBytes.sha256Hex + metalBytes.sha256Hex).utf8).sha256Hex
    try Data("synthetic game".utf8).write(to: paths.game.appendingPathComponent("Bin/WizardGraphicalClient.exe"))
    try Data("synthetic decoder".utf8).write(to: paths.game.appendingPathComponent("Bin/d3dx9_43.dll"))
    for mask in 0..<8192 {
        let settings = OptimizationSettings(buffer: mask & 1 != 0, stream: mask & 2 != 0, waitQueues: mask & 4 != 0, nativeDecode: mask & 8 != 0, prepareAssets: mask & 16 != 0, drawLayouts: mask & 32 != 0, directLayouts: mask & 64 != 0, gameRepair: mask & 128 != 0, sceneNodes: mask & 256 != 0, metalArchive: mask & 512 != 0, sceneTextures: mask & 1024 != 0, preparePipelines: mask & 2048 != 0, prepareAppearance: mask & 4096 != 0)
        settings.save(to: preferences)
        try check(OptimizationSettings.load(from: preferences) == settings, "Optimization switches persist independently: \(mask)")
        var combined = decompression
        combined.experimentDefaults = ["W101_DECOMPRESS":"off", "W101_WAIT_QUEUES":"off", "W101_NATIVE_DECODE":"off", "W101_PREPARE_ASSETS":"0", "W101_DRAW_LAYOUT_CACHE":"0", "W101_DRAW_LAYOUT_DIRECT":"0", "W101_GAME_REPAIR":"0", "W101_SCENE_NODES":"0", "W101_METAL_ARCHIVE":"0", "W101_SCENE_TEXTURES":"0", "W101_PREPARE_PIPELINES":"0", "W101_PREPARE_APPEARANCE":"0"]
        combined.experimentSelections = settings.environment
        let selected = combined.childEnvironment
        try check(settings.environment.allSatisfy { selected[$0.key] == ($0.key == "W101_DRAW_LAYOUT_CACHE" ? "0" : $0.value) }
            && selected["W101_ASSET_CACHE"] == "1" && selected["W101_ASSET_WORKERS"] == "2"
            && selected["DXVK_FRAME_RATE"] == "60" && selected["MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS"] == "1"
            && (selected["W101_DECODE_HELPER"] != nil) == settings.nativeDecode,
            "All combined configurations preserve baseline and scope helper: \(mask)")
        for frameMode in FrameMode.allCases {
            for profiling in [false, true] {
                var variant = LaunchPlan(paths: paths, mode: frameMode, profile: profiling, environment: ["W101_ASSET_CACHE_FILE":"hostile", "W101_ASSET_PREPARE_TEST":"allocation", "W101_DRAW_LAYOUT_TEST":"allocation", "W101_DRAW_LAYOUT_DIRECT_TEST":"stats", "W101_DRAW_LAYOUT_DIRECT":"1", "W101_DRAW_LAYOUT_CACHE":"1"], workloadDiagnostics: true, workloadPerformance: true, experimentDefaults: combined.experimentDefaults, experimentSelections: settings.environment, workloadFeatureDefaults: combined.workloadFeatureDefaults)
                variant.session = combined.session
                let (run, child) = try variant.prepareLogs()
                let recorded = try JSONSerialization.jsonObject(with: Data(contentsOf: run.appendingPathComponent("session.json"))) as? [String:Any]
                try check(child["W101_PREPARE_ASSETS"] == (settings.prepareAssets ? "1" : "0")
                    && child["W101_ASSET_CACHE_FILE"] == "C:\\graphics-patch-cache\\Wizard101\\known-assets.w101assets"
                    && child["W101_ASSET_PREPARE_TEST"] == nil
                    && child["W101_DRAW_LAYOUT_TEST"] == nil
                    && child["W101_DRAW_LAYOUT_DIRECT_TEST"] == nil
                    && child["W101_DRAW_LAYOUT_CACHE"] == "0"
                    && child["W101_DRAW_LAYOUT_DIRECT"] == (settings.directLayouts ? "1" : "0")
                    && recorded?["reuse_character_draw_layouts"] as? Bool == false
                    && recorded?["draw_layout_cache_available"] as? Bool == false
                    && recorded?["faster_draw_layouts"] as? Bool == settings.directLayouts
                    && child["W101_GAME_REPAIR"] == (settings.gameRepair ? "1" : "0")
                    && recorded?["game_repair_requested"] as? Bool == settings.gameRepair
                    && child["W101_SCENE_NODES"] == (settings.sceneNodes ? "1" : "0")
                    && child["W101_METAL_ARCHIVE"] == (settings.metalArchive ? "1" : "0")
                    && (child["W101_METAL_ARCHIVE_PATH"] != nil) == settings.metalArchive
                    && child["W101_METAL_ARCHIVE_KEY"] == (settings.metalArchive ? archiveKey : nil)
                    && (child["DXVK_W101_PROFILE"] != nil) == profiling
                    && child["DXVK_FRAME_RATE"] == (frameMode == .capped ? "60" : "0")
                    && recorded?["prepare_known_assets"] as? Bool == settings.prepareAssets
                    && recorded?["asset_preparation_cutoff_seconds"] is NSNull,
                    "Preparation, FPS, profiling and metadata combination: \(mask)/\(frameMode)/\(profiling)")
                try fm.removeItem(at: run)
            }
        }
    }
    var metalCandidate = LaunchPlan(paths: paths, mode: .capped, profile: false, environment: ["W101_METAL_ARCHIVE_PATH":"/hostile/path", "W101_METAL_ARCHIVE_KEY":String(repeating: "b", count: 64)], workloadDiagnostics: true, experimentDefaults: ["W101_METAL_ARCHIVE":"0", "W101_SCENE_TEXTURES":"0", "W101_PREPARE_PIPELINES":"0", "W101_PREPARE_APPEARANCE":"0"])
    try check(metalCandidate.childEnvironment["W101_METAL_ARCHIVE"] == "0" && metalCandidate.childEnvironment["W101_METAL_ARCHIVE_PATH"] == nil && metalCandidate.childEnvironment["W101_METAL_ARCHIVE_KEY"] == nil, "Disabled Metal archive discards inherited paths and keys")
    metalCandidate.experimentSelections = ["W101_METAL_ARCHIVE":"1"]
    try check(metalCandidate.childEnvironment["W101_METAL_ARCHIVE_PATH"] == paths.state.appendingPathComponent("MetalArchive").path && metalCandidate.childEnvironment["W101_METAL_ARCHIVE_KEY"] == archiveKey, "Metal archive uses isolated path and installed renderer/backend identities")
    try Data("changed backend".utf8).write(to: syntheticMetal)
    try check(metalCandidate.childEnvironment["W101_METAL_ARCHIVE_KEY"] != archiveKey, "Metal backend change invalidates prior archive identity")
    try fm.removeItem(at: syntheticMetal)
    try check(metalCandidate.childEnvironment["W101_METAL_ARCHIVE"] == "0", "Missing Metal backend disables archive")
    try fm.removeItem(at: syntheticRenderer)
    try check(metalCandidate.childEnvironment["W101_METAL_ARCHIVE"] == "0" && metalCandidate.childEnvironment["W101_METAL_ARCHIVE_PATH"] == nil, "Missing renderer disables Metal archive")
    var scoped = decompression
    var repairCandidate = scoped
    repairCandidate.experimentDefaults["W101_GAME_REPAIR"] = "0"
    repairCandidate.experimentDefaults.removeValue(forKey: "W101_DRAW_LAYOUT_DIRECT")
    repairCandidate.experimentDefaults.removeValue(forKey: "W101_DRAW_LAYOUT_CACHE")
    repairCandidate.experimentSelections = ["W101_GAME_REPAIR":"1", "W101_DRAW_LAYOUT_DIRECT":"1", "W101_DRAW_LAYOUT_CACHE":"1"]
    try check(repairCandidate.childEnvironment["W101_GAME_REPAIR"] == "1" && repairCandidate.childEnvironment["W101_DRAW_LAYOUT_DIRECT"] == "0" && repairCandidate.childEnvironment["W101_DRAW_LAYOUT_CACHE"] == "0", "Repair candidate retains stored layout choices while using original draw paths")
    scoped.experimentSelections = ["W101_DECOMPRESS":"invalid", "W101_WAIT_QUEUES":"sharded", "W101_NATIVE_DECODE":"auto"]
    try check(scoped.experimentFeatures.allSatisfy { $0.value == (["W101_PREPARE_ASSETS", "W101_DRAW_LAYOUT_CACHE", "W101_DRAW_LAYOUT_DIRECT", "W101_GAME_REPAIR", "W101_SCENE_NODES", "W101_METAL_ARCHIVE", "W101_SCENE_TEXTURES", "W101_PREPARE_PIPELINES", "W101_PREPARE_APPEARANCE"].contains($0.key) ? "0" : "off") }, "Selected modes reject invalid and unsupported features")
    var hostileAssets = scoped
    hostileAssets.experimentDefaults["W101_PREPARE_ASSETS"] = "0"
    hostileAssets.experimentSelections = ["W101_PREPARE_ASSETS":"invalid"]
    try check(hostileAssets.childEnvironment["W101_PREPARE_ASSETS"] == "0" && hostileAssets.childEnvironment["W101_ASSET_PREPARE_TEST"] == nil, "Asset preparation rejects invalid modes and strips fault injection")
    try check(workloadOff.childEnvironment["W101_ASSET_CACHE"] == "0" && workloadOff.childEnvironment["W101_GPU_TEXTURE_CONVERSION"] == "off", "Normal diagnostics cannot inherit new optimization flags")
    let workloadSession = try JSONSerialization.jsonObject(with: Data(contentsOf: workloadLogs.appendingPathComponent("session.json"))) as? [String:Any]
    try check(workloadEnvironment["W101_WORKLOAD_NATIVE"] == workloadLogs.appendingPathComponent("native.jsonl").path && workloadEnvironment["W101_WORKLOAD_THREADS"] == workloadLogs.appendingPathComponent("threads.jsonl").path, "Native workload paths scoped to this session")
    try check(workloadEnvironment["DXVK_W101_PROFILE_MAX_BYTES"] == String(112 * 1024 * 1024) && workloadSession?["profile_max_bytes"] as? Int == 256 * 1024 * 1024, "Workload capture fits the 256 MiB combined budget")
    try check(workloadEnvironment["W101_WORKLOAD_SECONDS"] == "900" && workloadEnvironment["W101_WORKLOAD_DEADLINE_UNIX_US"].flatMap(Int64.init) != nil, "Workload capture has an absolute 15 minute deadline")
    let frozenRelative = "Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Data/synthetic.wad"
    let frozen = paths.data.appendingPathComponent(frozenRelative)
    try fm.createDirectory(at: frozen.deletingLastPathComponent(), withIntermediateDirectories: true)
    let frozenBytes = Data("frozen archive".utf8)
    try frozenBytes.write(to: frozen)
    let seed = paths.data.deletingLastPathComponent().appendingPathComponent("Seed")
    try fm.createDirectory(at: seed, withIntermediateDirectories: true)
    let seedHash = String(repeating: "a", count: 64)
    let frozenManifest: [String: Any] = ["seed_sha256": seedHash,
        "roots": ["Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Data"],
        "files": [frozenRelative: ["sha256": frozenBytes.sha256Hex]]]
    try JSONSerialization.data(withJSONObject: frozenManifest).write(to: seed.appendingPathComponent("manifest.json"))
    let comparisonMeta: [String: Any] = ["seed_sha256": seedHash, "starting_inputs_sha256": seedHash,
        "seed_restored": true, "heavyweight_trace": false]
    var scoredEnv = env
    scoredEnv["W101_COMPARISON_METADATA"] = String(decoding: try JSONSerialization.data(withJSONObject: comparisonMeta), as: UTF8.self)
    scoredEnv["W101_COMPARISON_LABEL"] = "pair1-baseline"
    let scored = LaunchPlan(paths: paths, mode: .capped, profile: true, environment: scoredEnv, workloadDiagnostics: false, workloadPerformance: false, experimentDefaults: [:])
    let (scoredLogs, _) = try scored.prepareLogs()
    let scoredSession = try JSONSerialization.jsonObject(with: Data(contentsOf: scoredLogs.appendingPathComponent("session.json"))) as? [String: Any]
    try check(scoredSession?["handoff_inputs_verified"] as? Bool == true, "Frozen content verified at game handoff")
    try Data("changed archive".utf8).write(to: frozen)
    try rejects("Changed archive blocks scored handoff") { _ = try scored.prepareLogs() }
    try frozenBytes.write(to: frozen)
    let extraTracking = frozen.deletingLastPathComponent().appendingPathComponent("new.wad.utd")
    try Data("tracking".utf8).write(to: extraTracking)
    try rejects("Added tracking file blocks scored handoff") { _ = try scored.prepareLogs() }
    try fm.removeItem(at: extraTracking)
    try check(paths.windowsPath(logs).hasPrefix("C:\\NativeLogs\\"), "Logs map into the isolated prefix")
    try check(GameActivity.parse("wine64\nWizardGraphicalClient.exe") == .game, "Detect gameplay handoff")
    try check(GameActivity.parse("WizardLauncher.exe") == .launcher && GameActivity.parse("wine64") == .idle, "Recognize official launcher and idle")
    try rejects("Expired session") { try capped.session!.validate(at: capped.session!.expires) }
    try rejects("Changed game revision fails closed") { _ = try CodeIntegrityNonce(game: logs.appendingPathComponent("session.json"), token: token) }
    try check(Data("123456789".utf8).kiCRC == 771566984, "KingsIsle CRC variant")
    for path in ["../escape", "/etc/passwd", "Bin//file", "C:/file", "Bin/../file", "Bin\\file"] { try rejects("Unsafe manifest path \(path)") { try PatchManifest.validatePath(path) } }
    let base = root.appendingPathComponent("SyntheticGame"), state = root.appendingPathComponent("State")
    try fm.createDirectory(at: base, withIntermediateDirectories: true)
    try fm.createDirectory(at: state, withIntermediateDirectories: true)
    let lock = try LauncherLock(directory: state)
    try rejects("Concurrent update lock") { _ = try LauncherLock(directory: state) }
    withExtendedLifetime(lock) {}
    let content = Data("synthetic config".utf8)
    let config = PatchRecord(source: "Windows/Bin/config.xml", target: "", type: 1, size: UInt64(content.count), crc: content.kiCRC)
    try check(NativePatcher.hasStagingSpace([], state: state, free: 0), "No update staging reserve when installed content is current")
    try check(!NativePatcher.hasStagingSpace([config], state: state, free: 512 * 1024 * 1024), "Real updates still require staging reserve")
    try check(NativePatcher.hasStagingSpace([config], state: state, free: UInt64(content.count) + 512 * 1024 * 1024 + 1), "Real update space includes only needed content plus reserve")
    let login = PatchRecord(source: "PatchClient/LoginMessages.xml", target: "LoginMessages.xml", type: 1, size: UInt64(content.count), crc: content.kiCRC, table: "PatchClient")
    try check(login.localPath == "PatchClient/BankB/LoginMessages.xml", "Map official login definition alias into native auth location")
    let cursor = PatchRecord(source: "Windows/Bin/Cursors/arrow.cur", target: "", type: 1, size: UInt64(content.count), crc: content.kiCRC)
    let official = PatchRecord(source: "PatchClient/BankB/WizardLauncher.exe", target: "", type: 1, size: 1, crc: 0, table: "PatchClient")
    let renderer = PatchRecord(source: "Windows/Bin/d3d9.dll", target: "", type: 1, size: 1, crc: 0)
    let cache = ChecksumCache(url: state.appendingPathComponent("checksums.json"))
    let inventory = try PatchInventory.inspect(records: [config, login, cursor, official, renderer], base: base, cache: cache, token: token)
    try check(Set(inventory.needed.map { $0.localPath }) == Set([config.localPath, login.localPath, cursor.localPath]), "Fresh config, cursor and login definitions downloaded; launcher and renderer excluded")
    let transaction = PatchTransaction(base: base, state: state, gameplayClosed: {})
    var staged: [(PatchRecord, URL)] = []
    for (i, record) in inventory.needed.enumerated() {
        let file = state.appendingPathComponent("synthetic-\(i).part"); try content.write(to: file); staged.append((record, file))
    }
    try transaction.commit(staged, token: token)
    try check(try Data(contentsOf: base.appendingPathComponent(config.localPath)) == content, "Transactional bootstrap commit")
    let repeated = try PatchInventory.inspect(records: [config, login, cursor], base: base, cache: cache, token: token)
    try check(repeated.needed.isEmpty, "Existing settings and cursors protected")
    let replacement = state.appendingPathComponent("replacement.part"); try content.write(to: replacement)
    try rejects("Existing configuration cannot be overwritten") { try transaction.commit([(config, replacement)], token: token) }
    let wad = base.appendingPathComponent("Data/GameData/Root.wad")
    try fm.createDirectory(at: wad.deletingLastPathComponent(), withIntermediateDirectories: true)
    let header = Data("synthetic header".utf8), payload = Data("streamed payload differs".utf8)
    try (header + payload).write(to: wad)
    let archive = PatchRecord(source: "Windows/Data/GameData/Root.wad", target: "", type: 5, size: UInt64(header.count + payload.count), crc: 0, table: "GameData", headerSize: UInt64(header.count), headerCRC: header.kiCRC)
    try check(try cache.valid(wad, record: archive, token: token), "Imported streamed WAD validates its header")
    try check(try !cache.valid(wad, record: archive, token: token, mode: .fullFile), "Staged WAD requires full-file CRC")
    let cancelled = CancellationToken(); cancelled.cancel()
    try rejects("Cancellation before update commit") { try transaction.commit([], token: cancelled) }
    let key = Data(0..<16), iv = Data(16..<32), plaintext = Data(repeating: 42, count: 4096)
    let tx = try GCMChunkCodec(key: key, iv: iv, chunkSize: 4096), rx = try GCMChunkCodec(key: key, iv: iv, chunkSize: 4096)
    let wire = try tx.encode(plaintext)
    try check(try rx.decode(wire) == plaintext, "Authenticated encryption round trip")
    var corrupt = wire; corrupt[0] ^= 1
    let rx2 = try GCMChunkCodec(key: key, iv: iv, chunkSize: 4096)
    try rejects("Reject unauthenticated ciphertext") { _ = try rx2.decode(corrupt) }
    let gzip = Data([31,139,8,0,0,0,0,0,2,255,43,174,204,43,201,72,45,201,76,86,72,175,202,44,80,72,73,44,73,4,0,168,143,145,152,19,0,0,0])
    let compressed = state.appendingPathComponent("synthetic.gz"), inflated = state.appendingPathComponent("inflated.part")
    try gzip.write(to: compressed)
    try check(w101_gunzip_file(compressed.path, inflated.path, 19, nil, nil) == 0 && (try Data(contentsOf: inflated)) == Data("synthetic gzip data".utf8), "Gzip download expands exact expected content")
    try check(w101_gunzip_file(compressed.path, inflated.path, 18, nil, nil) != 0, "Bound decompressed output")
    var brokenGzip = gzip; brokenGzip[31] ^= 1; try brokenGzip.write(to: compressed)
    try check(w101_gunzip_file(compressed.path, inflated.path, 19, nil, nil) != 0, "Reject corrupt gzip trailer")
    try Data(gzip.dropLast(4)).write(to: compressed)
    try check(w101_gunzip_file(compressed.path, inflated.path, 19, nil, nil) != 0, "Reject truncated gzip trailer")
    try Data("synthetic gzip data".utf8).write(to: compressed)
    try check(w101_gunzip_file(compressed.path, inflated.path, 19, nil, nil) != 0, "Reject transparent raw gzip input")
    let packed = PatchRecord(source: "Bin/Game.exe", target: "", type: 4, size: 19, crc: 1, headerSize: 39)
    try check(packed.downloadSource == "Bin/Game.exe.gz" && packed.downloadSize == 39, "Type-4 compressed URL and wire size")
    let resumeRecord = PatchRecord(source: "Data/test.wad", target: "", type: 3, size: 1000, crc: 0)
    let resumeFile = state.appendingPathComponent(NativePatcher.stagingName(resumeRecord))
    try Data(repeating: 0, count: 700).write(to: resumeFile)
    try check(NativePatcher.additionalStagingBytes([resumeRecord, packed], state: state) == 358, "Resume space includes remaining wire and decompression bytes")
    let prior = Data("old synthetic file".utf8), updated = Data("updated synthetic file".utf8)
    let recoverPath = "Data/recover.dat", recoverDestination = base.appendingPathComponent(recoverPath)
    try prior.write(to: recoverDestination)
    let backup = state.appendingPathComponent("backup-synthetic"), recoveryStage = state.appendingPathComponent("recovery.part")
    try fm.linkItem(at: recoverDestination, to: backup); try updated.write(to: recoveryStage)
    let recoveryItem = PatchTransaction.Item(path: recoverPath, staged: recoveryStage.lastPathComponent, backup: backup.lastPathComponent,
                                            hadOriginal: true, size: UInt64(updated.count), crc: updated.kiCRC)
    let journalURL = state.appendingPathComponent("transaction.json")
    try JSONEncoder().encode(PatchTransaction.Journal(committed: false, items: [recoveryItem])).write(to: journalURL)
    try check(rename(recoveryStage.path, recoverDestination.path) == 0, "Simulate interruption after file replacement")
    try transaction.recover(); try transaction.recover()
    try check(try Data(contentsOf: recoverDestination) == prior && !fm.fileExists(atPath: journalURL.path), "Interrupted update rolls back and recovery is repeatable")
    let newPath = "Data/new.dat", newDestination = base.appendingPathComponent(newPath)
    try updated.write(to: newDestination)
    let newItem = PatchTransaction.Item(path: newPath, staged: "new.part", backup: "backup-new", hadOriginal: false,
                                       size: UInt64(updated.count), crc: updated.kiCRC)
    try JSONEncoder().encode(PatchTransaction.Journal(committed: false, items: [newItem])).write(to: journalURL)
    try transaction.recover()
    try check(!fm.fileExists(atPath: newDestination.path), "Interrupted new-file update removes only validated destination")
    let firstArchive = PatchRecord(source: "Data/GameData/Initial.wad", target: "", type: 5, size: 4096, crc: 0,
                                   table: "GameData", headerSize: UInt64(content.count), compressedHeaderSize: 39, headerCRC: content.kiCRC)
    let firstInventory = try PatchInventory.inspect(records: [firstArchive], base: base, cache: cache, token: token)
    try check(firstInventory.headerBootstraps == [firstArchive.localPath] && firstInventory.downloadBytes == 39, "Fresh type-5 archive downloads only its compressed header")
    let firstHeader = state.appendingPathComponent("initial.header"), firstStage = state.appendingPathComponent("initial.part")
    try content.write(to: firstHeader)
    try InitialArchive.stage(header: firstHeader, destination: firstStage, record: firstArchive, token: token)
    try check(Integrity.matchesHeader(firstStage, size: firstArchive.size, headerSize: firstArchive.headerSize, headerCRC: firstArchive.headerCRC, token: token)
              && !Integrity.matches(firstStage, size: firstArchive.size, crc: firstArchive.crc, token: token), "Initial sparse archive validates header and size without claiming a full CRC")
    try transaction.commit([(firstArchive, firstStage)], token: token, headerBootstraps: [firstArchive.localPath])
    let firstRepeated = try PatchInventory.inspect(records: [firstArchive], base: base, cache: cache, token: token)
    try check(firstRepeated.needed.isEmpty && firstRepeated.streamedArchives == 1, "Fresh streamed archive is ready without a full redownload")
    try InitialArchive.stage(header: firstHeader, destination: firstStage, record: firstArchive, token: token)
    try rejects("Header-only staging cannot replace an existing archive") { try transaction.commit([(firstArchive, firstStage)], token: token, headerBootstraps: [firstArchive.localPath]) }
    try rejects("Ordinary archive replacements still require full CRC") { try transaction.commit([(firstArchive, firstStage)], token: token) }
    let appearanceHeader = FixtureHTTP.content.prefix(32)
    let equipment = PatchRecord(source: "Data/GameData/Equipment-WorldData.wad", target: "", type: 5,
                                size: UInt64(FixtureHTTP.content.count), crc: FixtureHTTP.content.kiCRC,
                                table: "GameData", headerSize: 32, compressedHeaderSize: 48, headerCRC: appearanceHeader.kiCRC)
    let mob = PatchRecord(source: "Data/GameData/Mob-WorldData.wad", target: "", type: 3,
                          size: UInt64(FixtureHTTP.content.count), crc: FixtureHTTP.content.kiCRC,
                          table: "GameData", headerSize: 32, headerCRC: appearanceHeader.kiCRC)
    let world = PatchRecord(source: "Data/GameData/WizardCity-WorldData.wad", target: "", type: 3, size: 60000, crc: 0)
    let nestedAppearance = PatchRecord(source: "Data/GameData/Sub/Equipment-WorldData.wad", target: "", type: 3, size: 60000, crc: 0)
    try check(equipment.appearanceArchive && mob.appearanceArchive && !world.appearanceArchive && !nestedAppearance.appearanceArchive,
              "Appearance scope selects only top-level Equipment and Mob WAD archives")
    let appearanceHeaderFile = state.appendingPathComponent("appearance.header")
    let equipmentStage = state.appendingPathComponent(NativePatcher.stagingName(equipment))
    let mobStage = state.appendingPathComponent(NativePatcher.stagingName(mob))
    try Data(appearanceHeader).write(to: appearanceHeaderFile)
    try InitialArchive.stage(header: appearanceHeaderFile, destination: equipmentStage, record: equipment, token: token)
    try transaction.commit([(equipment, equipmentStage)], token: token, headerBootstraps: [equipment.localPath])
    let equipmentFile = base.appendingPathComponent(equipment.localPath)
    let sparseBefore = try Data(contentsOf: equipmentFile)
    let appearanceRecords = [equipment, mob, world, nestedAppearance]
    let defaultAppearance = try PatchInventory.inspect(records: appearanceRecords, base: base, cache: cache, token: token)
    try check(defaultAppearance.needed.isEmpty && defaultAppearance.optionalMissing == 3,
              "Appearance downloads default off and retain normal streamed-header validation")
    let fullAppearance = try PatchInventory.inspect(records: appearanceRecords, base: base, cache: cache, token: token, preparation: .appearance)
    try check(fullAppearance.needed == [equipment, mob] && fullAppearance.headerBootstraps.isEmpty
              && fullAppearance.downloadBytes == 120000 && fullAppearance.optionalMissing == 2,
              "Appearance preparation rejects header-valid incomplete body and fully downloads missing Mob")
    try check(!NativePatcher.hasStagingSpace(fullAppearance.needed, state: state, free: 512 * 1024 * 1024 + 120000),
              "Appearance staging requires complete body bytes plus existing reserve")
    try InitialArchive.stage(header: appearanceHeaderFile, destination: equipmentStage, record: equipment, token: token)
    try check(NativePatcher.additionalStagingBytes(fullAppearance.needed, state: state) == 120080,
              "Sparse full-length staging reserves the full body and verified-prefix staging")
    try Data(FixtureHTTP.content.prefix(257)).write(to: equipmentStage)
    try check(NativePatcher.additionalStagingBytes(fullAppearance.needed, state: state) == 119743,
              "Appearance staging accounts for resumable full-file downloads")
    try FixtureHTTP.content.write(to: equipmentStage)
    try FixtureHTTP.content.write(to: mobStage)
    try check(NativePatcher.additionalStagingBytes(fullAppearance.needed, state: state) == 0,
              "Already CRC-verified complete staging needs no body or prefix download space")
    try check(NativePatcher.hasStagingSpace(fullAppearance.needed, state: state, free: 512 * 1024 * 1024 + 1),
              "Verified complete staging requires only the existing transaction reserve")
    let cancelledAppearance = CancellationToken(); cancelledAppearance.cancel()
    try rejects("Cancelled appearance install leaves originals untouched") {
        try transaction.commit([(equipment, equipmentStage), (mob, mobStage)], token: cancelledAppearance)
    }
    try check(try Data(contentsOf: equipmentFile) == sparseBefore, "Cancellation preserves incomplete installed archive")
    var rollbackTriggered = false
    let appearanceTransaction = PatchTransaction(base: base, state: state, gameplayClosed: {
        if !rollbackTriggered && (try? Data(contentsOf: equipmentFile)) == FixtureHTTP.content {
            rollbackTriggered = true; throw LauncherError.message("Synthetic interruption between appearance replacements")
        }
    })
    try rejects("Interrupted appearance transaction rolls back replaced Equipment") {
        try appearanceTransaction.commit([(equipment, equipmentStage), (mob, mobStage)], token: token)
    }
    try check(rollbackTriggered && (try Data(contentsOf: equipmentFile)) == sparseBefore
              && !fm.fileExists(atPath: base.appendingPathComponent(mob.localPath).path), "Appearance rollback restores all prior content")
    try FixtureHTTP.content.write(to: equipmentStage)
    try FixtureHTTP.content.write(to: mobStage)
    var corruptAppearance = FixtureHTTP.content; corruptAppearance[4000] ^= 1
    try corruptAppearance.write(to: mobStage)
    try rejects("Appearance corrupt body prevents any transaction replacement") {
        try transaction.commit([(equipment, equipmentStage), (mob, mobStage)], token: token)
    }
    try check(try Data(contentsOf: equipmentFile) == sparseBefore, "Corrupt staged appearance preserves installed bytes")
    try FixtureHTTP.content.write(to: mobStage)
    try transaction.commit([(equipment, equipmentStage), (mob, mobStage)], token: token)
    let readyAppearance = try PatchInventory.inspect(records: appearanceRecords, base: base, cache: cache, token: token, preparation: .appearance)
    try check(readyAppearance.needed.isEmpty, "Full CRC-verified appearance archives are reused")
    try corruptAppearance.write(to: equipmentFile)
    let corruptInstalled = try PatchInventory.inspect(records: appearanceRecords, base: base, cache: cache, token: token, preparation: .appearance)
    try check(corruptInstalled.needed == [equipment], "Appearance detects body corruption despite valid header and cached full CRC")
    var zeros = [UInt8](repeating: 0, count: 32), zeroIV = [UInt8](repeating: 0, count: 16), block = [UInt8](repeating: 0, count: 16)
    zeros.withUnsafeBufferPointer { key in zeroIV.withUnsafeBufferPointer { iv in
        let input = block
        input.withUnsafeBufferPointer { p in block.withUnsafeMutableBufferPointer { out in _ = w101_twofish_ofb(key.baseAddress, iv.baseAddress, p.baseAddress, 16, out.baseAddress) } }
    }}
    try check(block.map { String(format: "%02x", $0) }.joined() == "57ff739d4dc92c1bd7fc01700cc8216f", "Twofish-256 known vector")
    let frame = KIFrame.message(service: 8, type: 1, fields: Data(repeating: 0, count: 28))
    try check(try KIFrame.decode(frame.encoded()).payload == frame.payload, "Protocol frame round trip")
    try rejects("Reject truncated protocol frame") { _ = try KIFrame.decode(Data(try frame.encoded().dropLast())) }
    try rejects("Reject unsigned server encryption") { _ = try SignedEncryptionOffer(Data(repeating: 0, count: 281)) }
    var bogus = Data(repeating: 0, count: 281); bogus[0] = 2; bogus[1] = 2; bogus[3] = 17
    try rejects("Reject forged server signature") { _ = try SignedEncryptionOffer(bogus) }
    let importSource = root.appendingPathComponent("Original")
    try fm.createDirectory(at: importSource.appendingPathComponent("Bin"), withIntermediateDirectories: true)
    for name in ["WizardGraphicalClient.exe", "preferences.xml", "shader.dxso", "WizardClient.log"] { try content.write(to: importSource.appendingPathComponent("Bin/" + name)) }
    let importPaths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": root.appendingPathComponent("Imported").path])
    try fm.createDirectory(at: importPaths.game, withIntermediateDirectories: true)
    let blockedSetup = FirstRun(paths: importPaths, token: token, report: { _ in }, gameplayClosed: {
        throw LauncherError.message("Fixture game is running")
    })
    try rejects("Running-game guard blocks fixture import") { try blockedSetup.importGame(importSource) }
    let setup = FirstRun(paths: importPaths, token: token, report: { _ in }, gameplayClosed: {}, availableBytes: { UInt64.max })
    try setup.importGame(importSource)
    try check(try Data(contentsOf: importPaths.game.appendingPathComponent("Bin/preferences.xml")) == content, "Import preserves settings")
    try Data("changed clone".utf8).write(to: importPaths.game.appendingPathComponent("Bin/preferences.xml"))
    try check(try Data(contentsOf: importSource.appendingPathComponent("Bin/preferences.xml")) == content, "Imported clone writes cannot alter source")
    try check(!fm.fileExists(atPath: importPaths.game.appendingPathComponent("Bin/shader.dxso").path) && !fm.fileExists(atPath: importPaths.game.appendingPathComponent("Bin/WizardClient.log").path), "Import excludes capture and credential-bearing logs")
    let networkStage = state.appendingPathComponent("network.part")
    let httpConfig = URLSessionConfiguration.ephemeral; httpConfig.protocolClasses = [FixtureHTTP.self]
    func download(_ path: String, token: CancellationToken = CancellationToken(), progress: @escaping (UInt64) -> Void = { _ in }) throws {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/\(path)")!, to: networkStage,
                                  size: UInt64(FixtureHTTP.content.count), token: token, progress: progress, testConfiguration: httpConfig)
    }
    let prefixHeader = state.appendingPathComponent("network.header")
    let shortPrefix = Data(FixtureHTTP.content.prefix(2))
    try shortPrefix.write(to: networkStage)
    try check(ArchivePrefix.required(record: equipment, destination: networkStage), "A partial streamed header needs a verified download prefix")
    try rejects("Repeated server drops inside the header retain staged progress") { try download("blocked-header") }
    try check(try Data(contentsOf: networkStage) == shortPrefix, "Failed header-range downloads preserve the partial file")
    try Data(repeating: 42, count: 32).write(to: prefixHeader)
    try rejects("Corrupt compressed-header output cannot seed a full download") {
        try ArchivePrefix.stage(header: prefixHeader, destination: networkStage, record: equipment, token: token)
    }
    try check(try Data(contentsOf: networkStage) == shortPrefix, "Invalid prefix leaves prior staged bytes untouched")
    try Data(appearanceHeader).write(to: prefixHeader)
    let cancelledPrefix = CancellationToken(); cancelledPrefix.cancel()
    try rejects("Cancelled prefix staging does not replace resumable progress") {
        try ArchivePrefix.stage(header: prefixHeader, destination: networkStage, record: equipment, token: cancelledPrefix)
    }
    try check(try Data(contentsOf: networkStage) == shortPrefix && fm.fileExists(atPath: prefixHeader.path), "Prefix cancellation preserves both staging files")
    try ArchivePrefix.stage(header: prefixHeader, destination: networkStage, record: equipment, token: token)
    try check(try Data(contentsOf: networkStage) == Data(appearanceHeader)
              && !Integrity.matches(networkStage, size: equipment.size, crc: equipment.crc, token: token), "Verified prefix stays partial and cannot satisfy full-file CRC")
    try download("blocked-header")
    try check(try Data(contentsOf: networkStage) == FixtureHTTP.content && FixtureHTTP.lastRange == "bytes=32-59999",
              "Full archive resumes after the verified header and passes body CRC")
    try FixtureHTTP.content.prefix(4000).write(to: networkStage)
    try check(!ArchivePrefix.required(record: equipment, destination: networkStage), "Body download progress is retained without reseeding the prefix")
    try corruptAppearance.write(to: networkStage)
    try check(ArchivePrefix.required(record: equipment, destination: networkStage), "Invalid full-length staging can restart from a verified prefix")
    try Data(appearanceHeader).write(to: prefixHeader)
    try ArchivePrefix.stage(header: prefixHeader, destination: networkStage, record: equipment, token: token)
    try check(try Data(contentsOf: networkStage).count == 32, "Corrupt full-length staging becomes a real prefix rather than a sparse complete file")
    try check(!ArchivePrefix.required(record: mob, destination: networkStage), "Archives without official compressed headers retain ordinary downloads")
    try fm.removeItem(at: networkStage)
    try fm.createSymbolicLink(at: networkStage, withDestinationURL: equipmentFile)
    try Data(appearanceHeader).write(to: prefixHeader)
    let beforeUnsafePrefix = try Data(contentsOf: equipmentFile)
    try rejects("Prefix staging rejects a symbolic-link destination") {
        try ArchivePrefix.stage(header: prefixHeader, destination: networkStage, record: equipment, token: token)
    }
    try check(try Data(contentsOf: equipmentFile) == beforeUnsafePrefix, "Rejected prefix staging leaves the installed archive untouched")
    try fm.removeItem(at: networkStage)
    try FixtureHTTP.content.prefix(257).write(to: networkStage)
    try download("resume")
    try check(try Data(contentsOf: networkStage) == FixtureHTTP.content && FixtureHTTP.lastRange == "bytes=257-59999", "Range download resumes partial file")
    try FixtureHTTP.content.prefix(257).write(to: networkStage); try download("ignore-range")
    try check(try Data(contentsOf: networkStage) == FixtureHTTP.content, "Server ignoring Range restarts safely")
    try FixtureHTTP.content.prefix(257).write(to: networkStage)
    try rejects("Invalid Content-Range rejected") { try download("bad-range") }
    try fm.removeItem(at: networkStage)
    try rejects("Oversized download rejected") { try download("oversize") }
    try fm.removeItem(at: networkStage)
    try download("corrupt")
    try check(!Integrity.matches(networkStage, size: UInt64(FixtureHTTP.content.count), crc: FixtureHTTP.content.kiCRC, token: token), "Wrong downloaded CRC cannot be accepted")
    try fm.removeItem(at: networkStage)
    let interrupted = CancellationToken()
    try rejects("In-flight download cancellation returns") { try download("good", token: interrupted) { if $0 > 0 { interrupted.cancel() } } }
    try check(fm.fileExists(atPath: networkStage.path), "Cancelled download retains partial file")
    try download("resume")
    try check(try Data(contentsOf: networkStage) == FixtureHTTP.content, "Cancelled download resumes successfully")
    try fm.removeItem(at: networkStage); try download("drop-once") { if $0 >= 4000 { FixtureHTTP.dropReady.signal() } }
    try check(try Data(contentsOf: networkStage) == FixtureHTTP.content && FixtureHTTP.lastRange == "bytes=4000-59999", "Transient connection loss retries by resuming validated range")
    try fm.removeItem(at: networkStage)
    FixtureHTTP.boundedDrops = [2000, 10000, 18000, 26000, 34000, 42000, 50000, 58000]
    let boundaries = Set(FixtureHTTP.boundedDrops.map { UInt64($0) })
    try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/bounded")!, to: networkStage,
        size: UInt64(FixtureHTTP.content.count), token: CancellationToken(), progress: { if boundaries.contains($0) { FixtureHTTP.boundedDropReady.signal() } },
        testConfiguration: httpConfig, testChunkSize: 4096)
    try check(FixtureHTTP.boundedDrops.isEmpty && (try Data(contentsOf: networkStage)) == FixtureHTTP.content,
              "Bounded ranges complete a download across eight separate connection losses without restarting accepted progress")
    try check(FixtureHTTP.boundedRanges.first == "bytes=0-4095" && FixtureHTTP.boundedRanges.allSatisfy { value in
        let parts = value.dropFirst(6).split(separator: "-").compactMap { Int($0) }
        return parts.count == 2 && parts[1] - parts[0] + 1 <= 4096
    }, "Every bounded request includes an explicit start and end within its size limit")
    try FixtureHTTP.content.prefix(257).write(to: networkStage)
    try rejects("A server returning the wrong end of a bounded range is rejected") {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/bad-end")!, to: networkStage,
            size: UInt64(FixtureHTTP.content.count), token: CancellationToken(), progress: { _ in },
            testConfiguration: httpConfig, testChunkSize: 4096)
    }
    try check((try Data(contentsOf: networkStage)) == FixtureHTTP.content.prefix(257), "Rejected range endpoints leave staged bytes untouched")
    let chunkCancel = CancellationToken()
    try rejects("Cancelling between bounded ranges stops before the next request") {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/resume")!, to: networkStage,
            size: UInt64(FixtureHTTP.content.count), token: chunkCancel, progress: { if $0 >= 4353 { chunkCancel.cancel() } },
            testConfiguration: httpConfig, testChunkSize: 4096)
    }
    let acceptedChunk = try Data(contentsOf: networkStage)
    try check(acceptedChunk == FixtureHTTP.content.prefix(acceptedChunk.count) && acceptedChunk.count < FixtureHTTP.content.count,
              "Cancelled bounded download retains only accepted content for a later resume")
    let dns: [String: Any] = ["Status": 0, "TC": false,
        "Question": [["name": CDNRoute.host + ".", "type": 1]],
        "Answer": [["name": CDNRoute.host, "type": 5, "TTL": 20, "data": "edge.example."],
                   ["name": "edge.example", "type": 1, "TTL": 20, "data": "23.210.92.230"],
                   ["name": "edge.example", "type": 1, "TTL": 20, "data": "23.210.73.204"],
                   ["name": "unrelated.example", "type": 1, "TTL": 20, "data": "8.8.8.8"]]]
    func dnsData(_ value: [String: Any]) throws -> Data { try JSONSerialization.data(withJSONObject: value) }
    try check(try CDNRoute.parse(dnsData(dns)) == ["23.210.92.230", "23.210.73.204"], "Alternate route accepts only live A answers reachable from the exact official DNS question")
    for field in ["Status", "TC", "Question", "Answer"] {
        var invalid = dns; invalid[field] = field == "TC" ? true : NSNull()
        try rejects("Malformed alternate DNS field rejected: \(field)") { _ = try CDNRoute.parse(dnsData(invalid)) }
    }
    var wrongQuestion = dns; wrongQuestion["Question"] = [["name": "unrelated.example", "type": 1]]
    try rejects("Unrelated DNS question rejected") { _ = try CDNRoute.parse(dnsData(wrongQuestion)) }
    for address in ["127.0.0.1", "10.1.2.3", "169.254.1.2", "172.16.1.1", "192.168.1.1", "100.64.1.1", "0.1.2.3", "224.1.2.3", "23.210.092.230", "23.210.92.230:80", "::1"] {
        try check(!CDNRoute.publicIPv4(address), "Alternate route rejects private, reserved or noncanonical address: \(address)")
    }
    for records in [
        [["name": CDNRoute.host, "type": 1, "TTL": 0, "data": "23.210.92.230"]],
        [["name": CDNRoute.host, "type": 1, "TTL": 20, "data": "127.0.0.1"]],
        [["name": CDNRoute.host, "type": 5, "TTL": 20, "data": CDNRoute.host]],
        [["name": "unrelated.example", "type": 1, "TTL": 20, "data": "23.210.92.230"]]
    ] {
        var invalid = dns; invalid["Answer"] = records
        try rejects("Expired, private, cyclic or unrelated DNS answer rejected") { _ = try CDNRoute.parse(dnsData(invalid)) }
    }
    try rejects("Oversized DNS JSON rejected") { _ = try CDNRoute.parse(Data(repeating: 32, count: 65537)) }
    let officialURL = URL(string: "http://versionak.us.wizard101.com/resume")!
    try check(CDNRoute.permitted(officialURL, settings: [:], environment: [:]), "Alternate route remains scoped to official HTTP downloads")
    try check(!CDNRoute.permitted(officialURL, settings: nil, environment: [:]), "Unknown proxy configuration disables alternate routing")
    for settings: [String: Any] in [["HTTPEnable": 1], ["HTTPSEnable": 1], ["SOCKSEnable": 1], ["ProxyAutoConfigEnable": 1], ["ProxyAutoDiscoveryEnable": 1], ["__SCOPED__": ["en0": ["HTTPEnable": 1]]]] {
        try check(!CDNRoute.permitted(officialURL, settings: settings, environment: [:]), "System and scoped proxy routing is preserved")
    }
    try check(!CDNRoute.permitted(officialURL, settings: [:], environment: ["HTTPS_PROXY": "configured"]), "Explicit proxy environment prevents alternate routing")
    for url in ["https://versionak.us.wizard101.com/resume", "http://example.com/resume", "http://versionak.us.wizard101.com:80/resume"] {
        try check(!CDNRoute.permitted(URL(string: url)!, settings: [:], environment: [:]), "Unsupported URL cannot use alternate routing: \(url)")
    }
    let dnsConfig = URLSessionConfiguration.ephemeral; dnsConfig.protocolClasses = [FixtureDNS.self]
    FixtureDNS.body = try dnsData(dns)
    try check(try CDNRoute.addresses(token: CancellationToken(), testConfiguration: dnsConfig).count == 2, "Bounded native HTTPS DNS lookup returns qualified routes")
    FixtureDNS.body = Data(repeating: 32, count: 65537)
    try rejects("DNS response is bounded while receiving data") { _ = try CDNRoute.addresses(token: CancellationToken(), testConfiguration: dnsConfig) }
    FixtureDNS.body = try dnsData(dns); FixtureDNS.status = 302
    try rejects("DNS lookup rejects redirect status") { _ = try CDNRoute.addresses(token: CancellationToken(), testConfiguration: dnsConfig) }
    FixtureDNS.status = 200
    let dnsCancelled = CancellationToken(); dnsCancelled.cancel()
    try rejects("Cancelled DNS lookup exits before network access") { _ = try CDNRoute.addresses(token: dnsCancelled, testConfiguration: dnsConfig) }
    try FixtureHTTP.content.prefix(257).write(to: networkStage)
    var routeLookups = 0
    FixtureHTTP.routeReady = false
    try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/route-rotate")!, to: networkStage,
        size: UInt64(FixtureHTTP.content.count), token: CancellationToken(), progress: { if $0 >= 4257 { FixtureHTTP.routeDropReady.signal() } }, testConfiguration: httpConfig,
        testRoutes: { _ in routeLookups += 1; FixtureHTTP.routeReady = true; return ["23.210.92.230", "23.210.73.204"] })
    try check(routeLookups == 2 && FixtureHTTP.lastRange == "bytes=4257-59999" && (try Data(contentsOf: networkStage)) == FixtureHTTP.content,
              "Repeated network failures rotate bounded routes and retain accepted partial bytes for exact resume")
    try check(Integrity.matches(networkStage, size: UInt64(FixtureHTTP.content.count), crc: FixtureHTTP.content.kiCRC, token: token), "Route-recovered content still requires the exact full-file CRC")
    try FixtureHTTP.content.prefix(257).write(to: networkStage); routeLookups = 0
    try rejects("Range validation failure cannot trigger route lookup") {
        try HTTPTransfer.download(url: URL(string: "http://versionak.us.wizard101.com/bad-range")!, to: networkStage,
            size: UInt64(FixtureHTTP.content.count), token: CancellationToken(), progress: { _ in }, testConfiguration: httpConfig,
            testRoutes: { _ in routeLookups += 1; return ["23.210.92.230"] })
    }
    try check(routeLookups == 0 && (try Data(contentsOf: networkStage)) == FixtureHTTP.content.prefix(257), "Invalid ranges leave existing staged data untouched and preserve normal error fallback")
    let report: [String: Any] = ["passed": checks.count, "checks": checks, "synthetic_only": true, "real_login_verified": false, "gameplay_verified": false]
    print(String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), as: UTF8.self))
}

private final class FixtureHTTP: URLProtocol {
    static let content = Data((0..<60000).map { UInt8(truncatingIfNeeded: $0) })
    static var lastRange: String?
    static var droppedOnce = false
    static var routeReady = false, routeDropped = false
    static var boundedDrops = [Int](), boundedRanges = [String]()
    static let boundedDropReady = DispatchSemaphore(value: 0)
    static let routeDropReady = DispatchSemaphore(value: 0)
    static let dropReady = DispatchSemaphore(value: 0)
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "versionak.us.wizard101.com" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url else { return }
        let range = request.value(forHTTPHeaderField: "Range"); Self.lastRange = range
        let requested = range?.dropFirst(6).split(separator: "-", omittingEmptySubsequences: false) ?? []
        var offset = requested.first.flatMap { Int($0) } ?? 0
        var end = requested.last.flatMap { Int($0) } ?? Self.content.count - 1
        if url.path == "/blocked-header" && offset < 32 {
            client?.urlProtocol(self, didFailWithError: NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost)); return
        }
        if url.path == "/route-rotate" && !Self.routeReady {
            client?.urlProtocol(self, didFailWithError: NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost)); return
        }
        let ignore = url.path == "/ignore-range"
        if ignore { offset = 0; end = Self.content.count - 1 }
        let status = range != nil && !ignore ? 206 : 200
        var headers: [String: String] = [:]
        if status == 206 { headers["Content-Range"] = "bytes \(url.path == "/bad-range" ? offset + 1 : offset)-\(url.path == "/bad-end" ? end + 1 : end)/\(Self.content.count)" }
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        if url.path == "/bounded" {
            Self.boundedRanges.append(range ?? "")
            if let boundary = Self.boundedDrops.first, offset < boundary, boundary <= end {
                Self.boundedDrops.removeFirst()
                client?.urlProtocol(self, didLoad: Self.content.subdata(in: offset..<boundary))
                DispatchQueue.global().async {
                    _ = Self.boundedDropReady.wait(timeout: .now() + 3)
                    self.client?.urlProtocol(self, didFailWithError: NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost))
                }
                return
            }
        }
        if url.path == "/route-rotate" && !Self.routeDropped {
            Self.routeDropped = true
            client?.urlProtocol(self, didLoad: Self.content.subdata(in: offset..<offset+4000))
            DispatchQueue.global().async {
                _ = Self.routeDropReady.wait(timeout: .now() + 3)
                self.client?.urlProtocol(self, didFailWithError: NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost))
            }
            return
        }
        if url.path == "/drop-once" && !Self.droppedOnce {
            Self.droppedOnce = true
            client?.urlProtocol(self, didLoad: Self.content.prefix(4000))
            DispatchQueue.global().async {
                _ = Self.dropReady.wait(timeout: .now() + 3)
                self.client?.urlProtocol(self, didFailWithError: NSError(domain: NSURLErrorDomain, code: NSURLErrorNetworkConnectionLost))
            }
            return
        }
        var data = url.path == "/corrupt" ? Data(repeating: 42, count: Self.content.count) : Self.content
        if url.path == "/oversize" { data.append(1) }
        let limit = url.path == "/oversize" ? data.count : min(end + 1, data.count)
        while offset < limit {
            let next = min(offset + 4000, limit)
            client?.urlProtocol(self, didLoad: data.subdata(in: offset..<next)); offset = next
        }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

private final class FixtureDNS: URLProtocol {
    static var body = Data(), status = 200
    override class func canInit(with request: URLRequest) -> Bool { request.url == CDNRoute.endpoint }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let response = HTTPURLResponse(url: CDNRoute.endpoint, statusCode: Self.status, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/dns-json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        for offset in stride(from: 0, to: Self.body.count, by: 4000) {
            client?.urlProtocol(self, didLoad: Self.body.subdata(in: offset..<min(offset+4000, Self.body.count)))
        }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
