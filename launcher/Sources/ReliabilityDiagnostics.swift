import Foundation
import CryptoKit
import Metal
import Darwin

// Persist only typed observations. No free-form errors, argv, environment,
// network bytes, account identities, tickets or game/session logs are serialized.
final class ReliabilityDiagnostics: @unchecked Sendable {
    enum Counter: String, Codable, CaseIterable {
        case authenticationFailures, patchFailures, recoveryAttempts, recoveryFailures
        case verifiedChunks, receivedBytes, sentBytes, controlFrames, heartbeatBatches
    }
    enum Outcome: String, Codable { case success, cancelled, serverRejected, deadline, trafficLimit, integrity, invalidFrame, disconnected, unavailable }
    struct Attempt: Codable {
        let provider: AccountProvider
        let stage: AuthenticationFailure.Stage
        let milliseconds: Int
        let outcome: Outcome
        let rejection: AuthenticationFailure?
    }
    struct Snapshot: Codable {
        var attempts: [Attempt] = []
        var counters: [String: Int] = [:]
    }
    let url: URL
    private let lock = NSLock()
    private var value: Snapshot
    init(state: URL) {
        url = state.appendingPathComponent("ReliabilityDiagnostics.json")
        value = (try? JSONDecoder().decode(Snapshot.self, from: Data(contentsOf: url))) ?? Snapshot()
        value.attempts = Array(value.attempts.suffix(20))
        value.counters = value.counters.filter { key, count in Counter.allCases.contains { $0.rawValue == key } && count >= 0 }
    }
    func snapshot() -> Snapshot { lock.lock(); defer { lock.unlock() }; return value }
    private func save() {
        guard let bytes = try? JSONEncoder().encode(value) else { return }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try? bytes.write(to: url, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
    func increment(_ counter: Counter, by count: Int = 1) {
        lock.lock(); defer { lock.unlock() }
        value.counters[counter.rawValue] = min(1_000_000_000, value.counters[counter.rawValue, default: 0] + max(0, count))
        save()
    }
    func exchange(_ stats: AuthenticationExchangeStats) {
        lock.lock(); defer { lock.unlock() }
        for (counter, count) in [(Counter.verifiedChunks, stats.verifiedChunks), (.receivedBytes, stats.receivedBytes), (.sentBytes, stats.sentBytes), (.controlFrames, stats.controlFrames), (.heartbeatBatches, stats.heartbeatBatches)] {
            value.counters[counter.rawValue] = min(1_000_000_000, value.counters[counter.rawValue, default: 0] + count)
        }
        save()
    }
    func measure<T>(provider: AccountProvider, stage: AuthenticationFailure.Stage, _ body: () throws -> T) throws -> T {
        let start = ProcessInfo.processInfo.systemUptime
        func record(_ error: Error?) {
            let outcome: Outcome
            if error == nil { outcome = .success }
            else if error is CancellationError { outcome = .cancelled }
            else if error is AuthenticationFailure { outcome = .serverRejected }
            else if let transport = error as? AuthenticationTransportFailure { outcome = Outcome(rawValue: transport.rawValue) ?? .unavailable }
            else { outcome = .unavailable }
            let attempt = Attempt(provider: provider, stage: stage, milliseconds: min(3_600_000, max(0, Int((ProcessInfo.processInfo.systemUptime - start) * 1000))), outcome: outcome, rejection: error as? AuthenticationFailure)
            lock.lock(); defer { lock.unlock() }
            value.attempts = Array((value.attempts + [attempt]).suffix(20))
            if error != nil && !(error is CancellationError) { value.counters[Counter.authenticationFailures.rawValue] = min(1_000_000_000, value.counters[Counter.authenticationFailures.rawValue, default: 0] + 1) }
            save()
        }
        do { let result = try body(); record(nil); return result }
        catch { record(error); throw error }
    }
}

struct DiagnosticReport {
    let paths: PortablePaths
    let mode: FrameMode
    let diagnostics: ReliabilityDiagnostics
    static func hash(_ url: URL) -> String? {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }
        var hash = SHA256()
        do {
            while let bytes = try handle.read(upToCount: 1024 * 1024), !bytes.isEmpty { hash.update(data: bytes) }
            return hash.finalize().map { String(format: "%02x", $0) }.joined()
        } catch { return nil }
    }
    static let settingNames = Set(["BloomActive", "ClassicMode", "HardwareCursor", "IsFullscreen", "Resolution", "Smoothing", "ShadowDetail", "EquipTextureDetail", "TextureDetail", "ParticleScale", "JewelParticles", "EnableSound", "MusicVolume", "SFXVolume", "DialogVolume", "SpeakerSetup", "Fullscreen", "Width", "Height", "WindowWidth", "WindowHeight", "TextureQuality", "GraphicsQuality"])
    static let namedSettings = Set(["Smoothing", "EquipTextureDetail", "TextureDetail", "TextureQuality", "GraphicsQuality"])
    static let settingValues = Set(["Off", "On", "None", "Low", "Medium", "High", "Ultra", "2x", "4x", "8x", "16x"])
    static func validSettings(_ values: [String: String]) -> Bool {
        values.count <= settingNames.count && values.allSatisfy { name, text in
            settingNames.contains(name) && (text.range(of: "^[0-9xX,. +\\-]{1,32}$|^(true|false)$", options: .regularExpression) != nil
                || (namedSettings.contains(name) && settingValues.contains(text)))
        }
    }
    static func gameSettings(paths: PortablePaths) -> [String: [String: String]] {
        var result: [String: [String: String]] = [:]
        for name in ["config.xml", "preferences.xml"] {
            if let file = try? SafeInstallation(base: paths.game).file("Bin/\(name)"),
               let data = try? Data(contentsOf: file) { result[name] = settings(data) }
        }
        return result
    }
    static func settings(_ bytes: Data) -> [String: String] {
        guard bytes.count <= 2 * 1024 * 1024,
              !String(decoding: bytes, as: UTF8.self).uppercased().contains("<!DOCTYPE"),
              let document = try? XMLDocument(data: bytes, options: .nodeLoadExternalEntitiesNever) else { return [:] }
        var result: [String: String] = [:]
        for name in settingNames {
            for node in (try? document.nodes(forXPath: "//\(name)")) ?? [] {
                if let text = node.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines),
                   text.range(of: "^[0-9xX,. +\\-]{1,32}$|^(true|false)$", options: .regularExpression) != nil
                    || (namedSettings.contains(name) && settingValues.contains(text)) { result[name] = text }
            }
        }
        return result
    }
    static let logTokens = ["device_lost": "VK_ERROR_DEVICE_LOST", "swapchain_out_of_date": "VK_ERROR_OUT_OF_DATE_KHR", "swapchain_suboptimal": "VK_SUBOPTIMAL_KHR", "d3d_device_lost": "D3DERR_DEVICELOST", "shader_compile_failure": "Failed to compile shader", "pipeline_failure": "Failed to create pipeline", "texture_upload_failure": "Failed to upload texture", "texture_load_failure": "Failed to load texture", "stream_download_failure": "Failed to download", "focus_gained": "WM_SETFOCUS", "focus_lost": "WM_KILLFOCUS"]
    static func logCounts(_ bytes: Data) -> [String: Int] {
        let text = String(decoding: bytes.suffix(2 * 1024 * 1024), as: UTF8.self)
        return logTokens.mapValues { text.components(separatedBy: $0).count - 1 }
    }
    static func systemValue(_ key: String) -> String {
        var size = 0
        guard sysctlbyname(key, nil, &size, nil, 0) == 0, size > 0, size <= 1024 else { return "unavailable" }
        var bytes = [CChar](repeating: 0, count: size)
        guard sysctlbyname(key, &bytes, &size, nil, 0) == 0 else { return "unavailable" }
        return String(cString: bytes)
    }
    static func rendererRun(paths: PortablePaths, launch: LaunchDiagnosticSnapshot?) -> URL? {
        let installation = SafeInstallation(base: paths.prefix)
        if let launch { return try? installation.file("drive_c/NativeLogs/\(launch.runID)") }
        // Older launchers have no LastLaunch record. Read the newest recognized
        // run, but never invent launch settings from today's preferences.
        guard let root = try? installation.file("drive_c/NativeLogs"),
              let folders = try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.contentModificationDateKey]) else { return nil }
        return folders.filter { folder in
            guard LaunchDiagnosticSnapshot.validRunID(folder.lastPathComponent),
                  let marker = try? installation.file("drive_c/NativeLogs/\(folder.lastPathComponent)/session.json") else { return false }
            return FileManager.default.fileExists(atPath: marker.path)
        }.max { lhs, rhs in
            let a = (try? lhs.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let b = (try? rhs.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return a == b ? lhs.lastPathComponent < rhs.lastPathComponent : a < b
        }
    }
    static func logObservation(_ file: URL?) -> ([String: Int]?, [String: Any]) {
        guard let file, let info = try? file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]),
              info.isRegularFile == true, info.isSymbolicLink != true,
              let handle = try? FileHandle(forReadingFrom: file) else { return (nil, ["available": false]) }
        defer { try? handle.close() }
        do {
            let size = try handle.seekToEnd(), limit: UInt64 = 2 * 1024 * 1024
            try handle.seek(toOffset: size > limit ? size - limit : 0)
            let bytes = try handle.read(upToCount: Int(limit)) ?? Data()
            var observation: [String: Any] = ["available": true, "bytes_read": bytes.count, "truncated": size > limit]
            if let date = try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate {
                observation["modified_utc"] = ISO8601DateFormatter().string(from: date)
            }
            return (logCounts(bytes), observation)
        } catch { return (nil, ["available": false]) }
    }
    func data() throws -> Data {
        let resources = paths.resources
        let files: [String: URL] = [
            "launcher": resources.deletingLastPathComponent().appendingPathComponent("MacOS/Wizard101Native"),
            "wine": paths.wine, "wineserver": paths.runtime.appendingPathComponent("bin/wineserver"),
            "ntdll": paths.runtime.appendingPathComponent("lib/wine/x86_64-unix/ntdll.so"),
            "moltenvk": paths.runtime.appendingPathComponent("lib/libMoltenVK.dylib"),
            "bundled_renderer": resources.appendingPathComponent("Renderer/d3d9.dll"),
            "installed_renderer": paths.game.appendingPathComponent("Bin/d3d9.dll"),
            "game": paths.game.appendingPathComponent("Bin/WizardGraphicalClient.exe"),
            "decoder": paths.game.appendingPathComponent("Bin/d3dx9_43.dll")]
        let hashes = files.mapValues { Self.hash($0) ?? "unavailable" }
        let settings = Self.gameSettings(paths: paths)
        let launch = LaunchDiagnosticSnapshot.load(state: paths.state)
        let patch = PatchDiagnostics(state: paths.state).snapshot()
        let run = Self.rendererRun(paths: paths, launch: launch)
        var logs: [String: Any] = [:]
        var sources: [String: Any] = [:]
        for name in ["WizardClient.log", "WizardGraphicalClient_d3d9.log"] {
            let file = name == "WizardClient.log" ? try? SafeInstallation(base: paths.game).file("Bin/\(name)")
                : run.flatMap { try? SafeInstallation(base: $0).file("logs/\(name)") }
            let (counts, observation) = Self.logObservation(file)
            if let counts { logs[name] = counts }
            sources[name] = observation
        }
        let observations = try JSONSerialization.jsonObject(with: JSONEncoder().encode(diagnostics.snapshot()))
        var plan = LaunchPlan(paths: paths, mode: mode, profile: false, environment: ProcessInfo.processInfo.environment)
        if Bundle.main.object(forInfoDictionaryKey: "W101CombinedOptimizations") as? Bool == true { plan.experimentSelections = OptimizationSettings.load().environment }
        func object<T: Encodable>(_ value: T) throws -> Any { try JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) }
        let report: [String: Any] = ["schema": 3, "candidate": Bundle.main.object(forInfoDictionaryKey: "W101ReliabilityCandidate") as? Bool ?? false,
            "app_version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unavailable",
            "app_build": Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unavailable",
            "created_utc": ISO8601DateFormatter().string(from: Date()),
            "mac": ["model": Self.systemValue("hw.model"), "cpu": Self.systemValue("machdep.cpu.brand_string"), "gpu": MTLCreateSystemDefaultDevice()?.name ?? "unavailable", "macos": ProcessInfo.processInfo.operatingSystemVersionString, "memory_bytes": ProcessInfo.processInfo.physicalMemory],
            "component_sha256": hashes, "settings": settings, "frame_mode": launch?.frameMode.rawValue ?? "unavailable",
            "next_launch_frame_mode": mode.rawValue, "pacing": "legacy",
            "authentication": observations, "log_token_counts": logs, "log_sources": sources,
            "renderer_log_selection": launch != nil ? "recorded_launch" : run != nil ? "newest_legacy_run" : "unavailable",
            "last_launch": try launch.map { try object($0) } ?? ["available": false],
            "launch_content_mode": launch?.contentPreparation.map { $0 == .visuals ? "full_visual_preload" : $0 == .startup ? "streaming_once" : "appearance_preload" } ?? "unavailable",
            "patch": try object(patch), "archive_verification": ArchiveAudit.inspect(paths: paths, manifest: patch.manifest),
            "renderer_settings": try launch.map { try object($0.renderer) } ?? ["available": false],
            "next_launch_renderer_settings": try object(RendererConfiguration(plan: plan)),
            "content_readiness": try ContentReadiness.load(state: paths.state).map { try object($0) } ?? ["available": false],
            "log_scope": "Last 2 MiB per available log. Game log is the latest game-folder file; renderer log belongs to the selected run. Missing logs are unavailable. Readiness is dated; live graphics are unverified.",
            "graphics_live_verified": false, "app_switch_live_verified": false]
        return try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
    }
    func save(to destination: URL) throws {
        try data().write(to: destination, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
    }
}
