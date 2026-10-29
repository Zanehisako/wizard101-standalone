import AppKit
import SwiftUI

private final class ConsoleProgress: @unchecked Sendable {
    private let lock = NSLock()
    private var phase = ""
    private var bucket = -1
    func report(_ update: PatchProgress) {
        lock.lock(); defer { lock.unlock() }
        let next = Int((update.fraction ?? 0) * 20)
        if update.phase != phase || next != bucket {
            phase = update.phase; bucket = next
            print(update.phase + " " + update.detail); fflush(stdout)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow?
    var model: LauncherModel?
    func applicationDidFinishLaunching(_ notification: Notification) {
        let model = LauncherModel(paths: PortablePaths())
        self.model = model
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 660),
                              styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
                              backing: .buffered, defer: false)
        window.title = Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "Wizard101 Native"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .darkAqua)
        window.contentView = NSHostingView(rootView: LauncherView(model: model))
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        let menu = NSMenu()
        let item = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Wizard101 Native", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Wizard101 Native", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Wizard101 Native", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu
        menu.addItem(item)
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        for (title, action, key) in [("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                                     ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationWillTerminate(_ notification: Notification) { model?.shutdown() }
    func applicationDidBecomeActive(_ notification: Notification) { model?.refresh() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window?.makeKeyAndOrderFront(nil)
        model?.refresh()
        return true
    }
}

let arguments = CommandLine.arguments
let contentPreparation: ContentPreparation = arguments.contains("--prepare-visuals") ? .visuals
    : arguments.contains("--prepare-appearance") ? .appearance : .startup
if arguments.contains("--prepare-visuals") && (arguments.contains("--prepare-appearance")
    || (!arguments.contains("--prepare-content") && !arguments.contains("--check-updates"))) {
    fputs("Use --prepare-visuals with --prepare-content or --check-updates, without --prepare-appearance.\n", stderr); exit(2)
}
let paths = PortablePaths()
if arguments.contains("--install-prepared-visuals") && (!arguments.contains("--prepare-content") || contentPreparation != .startup) {
    fputs("Use --install-prepared-visuals with --prepare-content, without a full-preload scope.\n", stderr); exit(2)
}
if arguments.contains("--self-test") {
    do { try runSelfTests(); exit(0) }
    catch { fputs("Self-test failed: \(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--game-status") || arguments.contains("--force-quit-game") {
    do {
        if arguments.contains("--force-quit-game") { try PrefixRecovery(paths: paths).forceQuit() }
        print(try GameActivity.scan(prefix: paths.prefix).rawValue); exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(2) }
}
if let index = arguments.firstIndex(of: "--save-diagnostic-report") {
    do {
        guard index + 1 < arguments.count else { throw LauncherError.message("Pass the report destination after --save-diagnostic-report.") }
        try DiagnosticReport(paths: paths, mode: LauncherPreferences().frameMode, diagnostics: ReliabilityDiagnostics(state: paths.state)).save(to: URL(fileURLWithPath: arguments[index + 1]))
        print("Diagnostic report saved."); exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(2) }
}
if arguments.contains("--diagnose") {
    do {
        try paths.validateRuntime()
        var plan = LaunchPlan(paths: paths, mode: .capped, profile: false, environment: ProcessInfo.processInfo.environment)
        if Bundle.main.object(forInfoDictionaryKey: "W101CombinedOptimizations") as? Bool == true {
            plan.experimentSelections = OptimizationSettings.load().environment
        }
        let summary: [String: Any] = ["runtime_present": true, "rosetta_available": true, "crossover_required": false,
            "prefix": paths.prefix.path, "game": plan.gameDirectory.path, "stutter_fix": plan.stutterFix,
            "cpu_optimization": plan.cpuOptimization, "pipeline_optimization": plan.pipelineOptimization,
            "frame_rate": "60", "limiter": "legacy", "synchronous_queue_submits": plan.synchronousQueueSubmits,
            "workload_diagnostics": plan.workloadDiagnostics,
            "experiments": plan.experimentFeatures,
            "profiling_enabled_by_bundle": Bundle.main.object(forInfoDictionaryKey: "W101CaptureTiming") as? Bool ?? false]
        print(String(decoding: try JSONSerialization.data(withJSONObject: summary, options: [.prettyPrinted, .sortedKeys]), as: UTF8.self)); exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--setup-fresh") || arguments.contains("--import-game") {
    do {
        let lock = try LauncherLock(directory: paths.state)
        let setup = FirstRun(paths: paths, token: CancellationToken(), report: { print($0.phase + " " + $0.detail) })
        try setup.initialize()
        if let index = arguments.firstIndex(of: "--import-game") {
            guard index + 1 < arguments.count else { throw LauncherError.message("Pass the Wizard101 installation folder after --import-game.") }
            try setup.importGame(URL(fileURLWithPath: arguments[index + 1]))
        }
        try setup.finish(); withExtendedLifetime(lock) {}; print("Setup complete"); exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--prepare-content") {
    // Download and verify installed content without starting Wine or signing in.
    // Useful for separating network/update verification from runtime setup.
    do {
        let lock = try LauncherLock(directory: paths.state)
        let token = CancellationToken()
        signal(SIGINT, SIG_IGN)
        let cancel = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
        cancel.setEventHandler { token.cancel() }; cancel.resume()
        defer { cancel.cancel() }
        try FileManager.default.createDirectory(at: paths.game, withIntermediateDirectories: true)
        let reporter = ConsoleProgress()
        let result = try NativePatcher(base: paths.game, state: paths.state, token: token, report: { update in
            reporter.report(update)
        }).run(apply: true, preparation: contentPreparation, installPreparedVisuals: arguments.contains("--install-prepared-visuals"))
        if contentPreparation != .startup {
            var archives = [[String: Any]]()
            let cache = ChecksumCache(url: paths.state.appendingPathComponent("checksums.json"))
            for record in result.manifest.records where contentPreparation.requiresFullArchive(record) {
                let file = try SafeInstallation(base: paths.game).file(record.localPath)
                guard try cache.valid(file, record: record, token: token, mode: .fullFile) else {
                    throw LauncherError.message("Content verification failed after installation.")
                }
                archives.append(["path": record.localPath, "bytes": record.size, "crc": record.crc, "full_crc_verified": true])
            }
            let report: [String: Any] = ["revision": result.manifest.revision,
                contentPreparation == .visuals ? "visual_archives" : "appearance_archives": archives,
                "authentication_performed": false, "game_started": false]
            print(String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), as: UTF8.self))
        }
        withExtendedLifetime(lock) {}; print("Content prepared; runtime setup still required"); exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--patch-probe") || arguments.contains("--list-startup") {
    do {
        let lock = try LauncherLock(directory: paths.state)
        let token = CancellationToken(), manifest = try PatchManifest.fetch(token: token, staging: paths.state)
        let result = try PatchInventory.inspect(records: manifest.records, base: paths.game, cache: ChecksumCache(url: paths.state.appendingPathComponent("checksums.json")), token: token)
        let report: [String: Any] = ["revision": manifest.revision, "records": manifest.records.count, "download_bytes": result.downloadBytes, "files_needed": result.needed.count,
            "bootstrap_paths": manifest.records.filter { $0.bootstrapOnly }.map { $0.localPath }, "installed_files_modified": false]
        print(String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), as: UTF8.self)); withExtendedLifetime(lock) {}; exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--audit-content") {
    do {
        let lock = try LauncherLock(directory: paths.state)
        try NativePatcher.requireClosed()
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("w101-content-audit-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let token = CancellationToken(), manifest = try PatchManifest.fetch(token: token, staging: temporary)
        var names = Set<String>()
        for index in arguments.indices where arguments[index] == "--archive" {
            guard index + 1 < arguments.count, URL(fileURLWithPath: arguments[index + 1]).lastPathComponent == arguments[index + 1],
                  arguments[index + 1].lowercased().hasSuffix(".wad") else { throw LauncherError.message("Pass an archive filename after --archive.") }
            names.insert(arguments[index + 1].lowercased())
        }
        let archives = manifest.records.map(PatchDiagnostics.Archive.init).filter { archive in
            archive.valid && (names.isEmpty ? archive.relevantToNovus : names.contains(URL(fileURLWithPath: archive.path).lastPathComponent.lowercased()))
        }
        guard archives.count <= 256, !archives.isEmpty, names.isEmpty || archives.count == names.count else {
            throw LauncherError.message("The requested archives are missing or ambiguous in the current manifest.")
        }
        let observation = PatchDiagnostics.Manifest(revision: manifest.revision, checkedUTC: ISO8601DateFormatter().string(from: Date()), archives: archives)
        var report = ArchiveAudit.inspect(paths: paths, manifest: observation)
        report["schema"] = 1; report["manifest_refreshed_for_audit"] = true
        print(String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), as: UTF8.self))
        withExtendedLifetime(lock) {}; exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--check-updates") {
    do {
        let lock = try LauncherLock(directory: paths.state)
        let result = try NativePatcher(base: paths.game, state: paths.state, token: CancellationToken(), report: { _ in }).run(apply: false, preparation: contentPreparation)
        let report: [String: Any] = ["revision": result.manifest.revision, "records": result.manifest.records.count, "game_downloads": result.inventory.needed.count, "download_bytes": result.inventory.downloadBytes,
            "checked_files": result.inventory.checkedFiles, "validated_archive_headers": result.inventory.streamedArchives, "queued_paths": result.inventory.needed.map { $0.localPath }, "installed_files_modified": false]
        print(String(decoding: try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]), as: UTF8.self)); withExtendedLifetime(lock) {}; exit(0)
    } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
}
if arguments.contains("--protocol-probe") {
    do { print(try NativeAuthentication(base: paths.game).probe(token: CancellationToken())); exit(0) }
    catch { fputs("\(error.localizedDescription)\n", stderr); exit(2) }
}
if arguments.contains("--synthetic-auth-probe") {
    let token = CancellationToken()
    signal(SIGINT, SIG_IGN)
    let cancel = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
    cancel.setEventHandler { token.cancel() }; cancel.resume()
    do { print(try NativeAuthentication(base: paths.game).syntheticAuthenticationProbe(token: token)); cancel.cancel(); exit(0) }
    catch { cancel.cancel(); fputs("\(error.localizedDescription)\n", stderr); exit(2) }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
