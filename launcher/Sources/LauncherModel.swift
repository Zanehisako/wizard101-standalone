import AppKit
import SwiftUI
import Metal

@MainActor
final class LauncherModel: ObservableObject {
    let paths: PortablePaths
    @Published var mode: FrameMode = LauncherPreferences().frameMode {
        didSet { LauncherPreferences().frameMode = mode }
    }
    @Published var effects = LauncherPreferences().effects {
        didSet { LauncherPreferences().effects = effects }
    }
    @Published var showSettings = false
    @Published var needsRosetta = false
    @Published var setupAvailable = false
    @Published var installedGames: [InstalledGame] = []
    @Published var showImports = false
    @Published var setupStarted = false
    var setupStep: SetupStep { .current(needsRosetta: needsRosetta, runtimeReady: setupAvailable, gameReady: ready) }
    @Published var profile = ProcessInfo.processInfo.environment["W101_CAPTURE_TIMING"].map { $0 == "1" }
        ?? (Bundle.main.object(forInfoDictionaryKey: "W101CaptureTiming") as? Bool ?? false)
    @Published var warmup = ProcessInfo.processInfo.environment["W101_WARMUP_SELECTION"] == "1"
    @Published var workloadFixes = true
    let combinedOptimizations = Bundle.main.object(forInfoDictionaryKey: "W101CombinedOptimizations") as? Bool ?? false
    @Published var showOptimizations = false
    @Published var optimizations = OptimizationSettings() {
        didSet { if combinedOptimizations { optimizations.save() } }
    }
    @Published private(set) var provider = AccountPreferences().provider
    @Published var username = "" {
        didSet { rememberAccount() }
    }
    @Published var password = ""
    @Published var savePassword = false {
        didSet { rememberAccount() }
    }
    @Published var busy = false
    @Published private(set) var gameActivity = GameActivity.idle
    @Published private(set) var recovering = false
    @Published private(set) var savingReport = false
    @Published var reportSummary: String?
    @Published var canCancel = false
    @Published var status = "Checking your installation…"
    @Published var detail = ""
    @Published var issue: String?
    @Published private(set) var lastFailure: String?
    @Published private(set) var contentRecovery = ContentRecovery()
    @Published var ready = false
    @Published var progress: Double?
    @Published var updateSummary: String?
    @Published private(set) var contentSummary = "All game visuals are downloaded and verified before sign-in. Music and dialogue can stream during play."
    let renderer: SpiralRenderer?
    let gpu: String
    private var process: Process?
    private var launchedSession: GameSession?
    private var timer: Timer?
    private var token: CancellationToken?
    private var operationLock: LauncherLock?
    private var logURL: URL?
    private var scanning = false
    private var changingProvider = false
    private var handoffStarted = false
    lazy var reliability = ReliabilityDiagnostics(state: state)
    var canForceQuit: Bool { gameActivity != .idle && token == nil && !recovering && operationLock == nil }
    private var keychain: PasswordStore { PasswordStore(service: provider.keychainService) }
    var state: URL { paths.state }
    var plan: LaunchPlan {
        var result = LaunchPlan(paths: paths, mode: mode, profile: profile, environment: ProcessInfo.processInfo.environment, warmup: warmup)
        result.provider = provider
        result.workloadPerformanceEnabled = workloadFixes
        if combinedOptimizations { result.experimentSelections = optimizations.environment }
        return result
    }

    init(paths: PortablePaths) {
        self.paths = paths
        if let readiness = ContentReadiness.load(state: paths.state) { contentSummary = readiness.summary }
        if combinedOptimizations { optimizations = .load() }
        if Bundle.main.object(forInfoDictionaryKey: "W101WorkloadDiagnostics") as? Bool == true { profile = false; warmup = false }
        if let device = MTLCreateSystemDefaultDevice(), let shader = Bundle.main.url(forResource: "Spiral", withExtension: "metal"),
           let renderer = try? SpiralRenderer(device: device, shaderURL: shader) {
            self.renderer = renderer; self.gpu = device.name
        } else { self.renderer = nil; self.gpu = "Unavailable" }
        let accounts = AccountPreferences()
        changingProvider = true
        username = accounts.username(for: accounts.provider)
        savePassword = accounts.remembersPassword(for: accounts.provider)
        changingProvider = false
        refresh(); scan()
        if ready, savePassword, !username.isEmpty { loadPassword() }
    }
    func refresh() {
        guard token == nil, !recovering, !handoffStarted else { return }
        if gameActivity != .idle { scan(); return }
        guard !busy else { return }
        defer { scan() }
        setupAvailable = false
        setupStarted = FileManager.default.fileExists(atPath: paths.prefix.appendingPathComponent("system.reg").path)
        installedGames = InstalledGame.discover(excluding: paths.game)
        do {
            needsRosetta = !(try PortablePaths.rosettaAvailable())
            if needsRosetta {
                ready = false; status = "One quick step"; detail = "Apple's Rosetta lets your Mac run the game."
                return
            }
            try paths.validateRuntime()
            setupAvailable = true
            try plan.validateInstallation(); ready = true
            if lastFailure == nil { status = "Ready for adventure"; detail = ""; issue = nil }
        } catch {
            ready = false
            status = setupAvailable ? "Welcome, wizard!" : "Setup needs attention"
            detail = setupAvailable ? "Install once, then sign in and play." : error.localizedDescription
        }
    }
    func installRosetta() {
        guard needsRosetta, !busy, let helper = Bundle.main.url(forResource: "Rosetta Setup", withExtension: "app") else { return }
        busy = true; status = "Follow Apple's installation prompt"; detail = "Return here when Rosetta is installed."
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.openApplication(at: helper, configuration: configuration) { _, error in
            DispatchQueue.main.async {
                self.busy = false
                if let error { self.fail(error.localizedDescription) }
                else { self.refresh() }
            }
        }
    }
    func freshInstall() { guard setupAvailable else { return }; setup(importing: nil) }
    func chooseImport() {
        guard !busy, setupAvailable else { return }
        if installedGames.isEmpty { chooseImportFolder() }
        else { showImports = true }
    }
    func importGame(_ source: InstalledGame) {
        guard !busy, setupAvailable else { return }
        showImports = false
        setup(importing: source.game)
    }
    func chooseImportFolder() {
        guard !busy, setupAvailable else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false; panel.message = "Choose the Wizard101 folder containing Bin and Data."
        if panel.runModal() == .OK, let url = panel.url { showImports = false; setup(importing: url) }
    }
    private func setup(importing source: URL?) {
        guard !busy else { return }
        let token = CancellationToken(); self.token = token; busy = true; canCancel = true
        let paths = paths, diagnostics = reliability
        let reporter = ProgressReporter { update in DispatchQueue.main.async { self.status = update.phase; self.detail = update.detail; self.progress = update.fraction } }
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let lock = try LauncherLock(directory: paths.state)
                let setup = FirstRun(paths: paths, token: token, report: { reporter.report($0) })
                try setup.initialize()
                if let source { try setup.importGame(source) }
                try setup.finish()
                withExtendedLifetime(lock) {}
                DispatchQueue.main.async { self.busy = false; self.canCancel = false; self.token = nil; self.refresh() }
            } catch {
                if !(error is CancellationError) { diagnostics.increment(.patchFailures) }
                DispatchQueue.main.async {
                    self.token = nil
                    self.setupStarted = true
                    if error is CancellationError { self.busy = false; self.canCancel = false; self.progress = nil; self.status = "Setup cancelled"; self.detail = "Choose Continue setup to resume your staged files." }
                    else { self.fail(error.localizedDescription) }
                }
            }
        }
    }
    private func rememberAccount() {
        guard !changingProvider else { return }
        AccountPreferences().save(username: username, remember: savePassword, for: provider)
    }
    func selectProvider(_ selected: AccountProvider) {
        guard !busy, selected != provider else { return }
        rememberAccount()
        changingProvider = true
        password = ""; issue = nil; lastFailure = nil; detail = ""
        contentRecovery.clear()
        provider = selected
        let accounts = AccountPreferences()
        accounts.provider = selected
        username = accounts.username(for: selected)
        savePassword = accounts.remembersPassword(for: selected)
        changingProvider = false
        if ready { status = "Ready for adventure" }
        if ready, savePassword, !username.isEmpty { loadPassword() }
    }
    func loadPassword() {
        let account = username, keychain = keychain, selectedProvider = provider
        guard !account.isEmpty, !busy else { return }
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try keychain.load(account: account) }
            DispatchQueue.main.async {
                self.busy = self.gameActivity != .idle
                switch result {
                case .success(let value): if self.username == account && self.provider == selectedProvider { self.password = value ?? ""; self.detail = value == nil ? "No password is saved for this account." : "Password loaded from Mac Keychain." }
                case .failure(let error): self.fail(error.localizedDescription)
                }
            }
        }
    }
    func forgetPassword() {
        let account = username, keychain = keychain
        guard !account.isEmpty, !busy else { return }
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try keychain.remove(account: account) }
            DispatchQueue.main.async {
                self.busy = self.gameActivity != .idle
                switch result {
                case .success: self.password = ""; self.savePassword = false; self.detail = "Saved password removed from Keychain."
                case .failure(let error): self.fail(error.localizedDescription)
                }
            }
        }
    }
    func launch() { begin(checkOnly: false) }
    func chooseStreamingOnce() {
        guard !busy, contentRecovery.canOfferStreaming else { return }
        contentRecovery.chooseStreaming()
        issue = nil; lastFailure = nil
        status = "Streaming selected for next play"
        detail = "Some visuals may still be missing. Full preload will be retried on your next launch."
    }
    func retryVisualPreload() { contentRecovery.clear(); issue = nil }
    func checkUpdates() { begin(checkOnly: true) }
    func cancel() { token?.cancel(); canCancel = false; status = "Cancelling…"; detail = "Partial downloads will be kept for retry." }
    func shutdown() { token?.cancel() }
    private func begin(checkOnly: Bool) {
        guard ready, !busy, !scanning, gameActivity == .idle else { return }
        let preparation: ContentPreparation = checkOnly ? .visuals : contentRecovery.preparationForPlay()
        let account = username.trimmingCharacters(in: .whitespacesAndNewlines), secret = password, save = savePassword, selectedProvider = provider
        var selected = plan
        let directory = state, keychain = keychain, reliability = reliability
        let diagnostics = Bundle.main.object(forInfoDictionaryKey: "W101AuthenticationDiagnostics") as? Bool == true
            ? AuthenticationDiagnostics(url: directory.appendingPathComponent("AuthenticationFailure.json")) : nil
        try? diagnostics?.clear()
        let token = CancellationToken(); self.token = token
        let patcher = patcher(token: token)
        busy = true; canCancel = true; progress = nil; lastFailure = nil; issue = nil
        if checkOnly { updateSummary = "Checking updates…" }
        status = checkOnly ? "Checking updates…" : "Signing in…"
        detail = checkOnly ? "Looking for new game content." : "Getting your adventure ready."
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let lock = try LauncherLock(directory: directory)
                try NativePatcher.requireClosed()
                if !checkOnly {
                    // Bind the installed renderer/decoder to this candidate before
                    // updating or sending credentials, including existing data.
                    if selected.experimentDefaults["W101_SCENE_TEXTURES"] != nil {
                        try FirstRun(paths: selected.paths, token: token, report: { _ in }).installRenderer()
                    }
                    // Update bootstrap files before any credentials are sent.
                    _ = try patcher.run(apply: true, preparation: preparation, installPreparedVisuals: preparation == .startup)
                    DispatchQueue.main.async {
                        self.contentSummary = ContentReadiness.load(state: directory)?.summary ?? self.contentSummary
                        if preparation == .startup { self.contentSummary = "Using on-demand visuals for this launch. Full visual preload remains incomplete." }
                    }
                    let auth = NativeAuthentication(base: selected.gameDirectory, provider: selectedProvider, diagnostics: reliability)
                    var session = try auth.signIn(username: account, password: secret, token: token)
                    if save { try keychain.save(account: account, password: secret) }
                    else { try keychain.remove(account: account) }
                    AccountPreferences().save(username: account, remember: save, for: selectedProvider)
                    DispatchQueue.main.async { self.status = "Verifying session…"; self.detail = "Checking your session with the account server before launch."; self.progress = nil }
                    session = try auth.revalidate(session, token: token)
                    selected.session = session
                    try selected.validate(); try token.check(); try NativePatcher.requireClosed()
                    DispatchQueue.main.async { self.operationLock = lock; self.password = ""; self.canCancel = false; self.start(selected) }
                } else {
                    let result = try patcher.run(apply: false, preparation: .visuals)
                    withExtendedLifetime(lock) {}
                    DispatchQueue.main.async {
                        self.busy = false; self.canCancel = false; self.token = nil
                        self.contentSummary = ContentReadiness.load(state: directory)?.summary ?? self.contentSummary
                        self.updateSummary = result.inventory.needed.isEmpty ? "Game is up to date." : "Updates will install when you press Play."
                    }
                }
            } catch {
                try? diagnostics?.record(error)
                DispatchQueue.main.async {
                    self.password = ""; self.token = nil
                    self.contentSummary = ContentReadiness.load(state: directory)?.summary ?? self.contentSummary
                    if !checkOnly { self.contentRecovery.failed(error) }
                    if checkOnly { self.updateSummary = error is CancellationError ? "Update check cancelled." : "Couldn’t check updates." }
                    if error is CancellationError { self.busy = false; self.canCancel = false; self.progress = nil; self.status = "Cancelled"; self.detail = "Retry when ready. Partial downloads remain staged." }
                    else { self.fail(error.localizedDescription) }
                }
            }
        }
    }
    private func patcher(token: CancellationToken) -> NativePatcher {
        let reporter = ProgressReporter { update in
            DispatchQueue.main.async { self.status = update.phase; self.detail = update.detail; self.progress = update.fraction }
        }
        return NativePatcher(base: plan.gameDirectory, state: state, token: token, report: { reporter.report($0) })
    }
    private func start(_ launchPlan: LaunchPlan) {
        do {
            try launchPlan.validate(); try NativePatcher.requireClosed()
            status = "Launching Wizard101…"; detail = "Starting the graphical client directly."; progress = nil
            let (logs, environment) = try launchPlan.prepareLogs()
            let child = Process(); child.executableURL = launchPlan.executable; child.arguments = launchPlan.arguments
            child.environment = environment; child.currentDirectoryURL = launchPlan.gameDirectory.appendingPathComponent("Bin")
            child.standardInput = FileHandle.nullDevice
            // Wine can echo command arguments on errors. Never retain its output.
            child.standardOutput = FileHandle.nullDevice; child.standardError = FileHandle.nullDevice
            child.terminationHandler = { process in DispatchQueue.main.async { self.finished(process.terminationStatus) } }
            logURL = logs; process = child; launchedSession = launchPlan.session
            try child.run()
            // Reporting must never interrupt a successful game launch.
            try? LaunchDiagnosticSnapshot.record(plan: launchPlan, run: logs)
            handoffStarted = true; beginMonitoring()
        } catch { fail(error.localizedDescription) }
    }
    private func beginMonitoring() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in DispatchQueue.main.async { self?.scan() } }
        timer?.tolerance = 1; scan()
    }
    private func scan() {
        guard !scanning else { return }; scanning = true
        DispatchQueue.global(qos: .utility).async {
            let result = Result { try GameActivity.scan(prefix: self.paths.prefix) }
            DispatchQueue.main.async {
                self.scanning = false
                switch result {
                case .success(let activity):
                    self.gameActivity = activity
                    if GameActivity.shouldExitAfterHandoff(activity: activity, startedHere: self.handoffStarted) {
                        // The game is an independent process. Quitting here
                        // closes only the native launcher after handoff.
                        NSApp.terminate(nil)
                        return
                    }
                    guard self.token == nil, !self.recovering else { return }
                    if activity != .idle {
                        self.busy = true; self.canCancel = false
                        self.status = activity == .game ? "Wizard101 is running" : "Official launcher is open"
                        self.detail = "Close it normally, or use Force Quit Game if it is stuck."
                        self.beginMonitoring()
                    } else if self.process?.isRunning != true && self.token == nil {
                        self.busy = false; self.operationLock = nil; self.timer?.invalidate(); self.timer = nil
                        if self.ready && self.lastFailure == nil { self.status = "Ready for adventure"; self.detail = "" }
                    }
                case .failure(let error): self.fail(error.localizedDescription)
                }
            }
        }
    }
    private func finished(_ code: Int32) {
        process = nil; token = nil; launchedSession = nil; handoffStarted = false
        if code != 0 { fail("The game exited with code \(code). Sign in again to retry.") }
        else { status = "Game closed"; detail = "Sign in to play again."; scan() }
    }
    private func fail(_ message: String) {
        launchedSession = nil
        busy = false; canCancel = false; progress = nil; operationLock = nil
        timer?.invalidate(); timer = nil
        status = "Needs attention"; detail = message; lastFailure = message; issue = message
    }
    func openLogs() {
        let directory = logURL ?? paths.prefix.appendingPathComponent("drive_c/NativeLogs")
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        NSWorkspace.shared.open(directory)
    }
    func forceQuitGame() {
        guard canForceQuit else { return }
        recovering = true; busy = true; canCancel = false
        status = "Closing Wizard101…"; detail = "Closing this installation's game processes."
        let recovery = PrefixRecovery(paths: paths), diagnostics = reliability
        diagnostics.increment(.recoveryAttempts)
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try recovery.forceQuit() }
            DispatchQueue.main.async {
                self.recovering = false
                switch result {
                case .success:
                    self.gameActivity = .idle; self.busy = false; self.lastFailure = nil; self.issue = nil
                    self.status = "Game closed"; self.detail = "Sign in when ready."; self.password = ""; self.scan()
                case .failure(let error): diagnostics.increment(.recoveryFailures); self.fail(error.localizedDescription); self.scan()
                }
            }
        }
    }
    func saveDiagnosticReport() {
        guard !savingReport else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "Wizard101-Diagnostic-Report.json"
        panel.message = "Save Mac details, component hashes, graphics settings and safe failure counters."
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        savingReport = true; reportSummary = "Saving report…"
        let report = DiagnosticReport(paths: paths, mode: mode, diagnostics: reliability)
        DispatchQueue.global(qos: .utility).async {
            let result = Result { try report.save(to: destination) }
            DispatchQueue.main.async {
                self.savingReport = false
                switch result {
                case .success: self.reportSummary = "Diagnostic report saved."
                case .failure: self.reportSummary = "Couldn’t save the report. Choose another location and retry."
                }
            }
        }
    }
}

private final class ProgressReporter: @unchecked Sendable {
    private let lock = NSLock()
    private var previous: Date = .distantPast
    private var phase = ""
    private let callback: (PatchProgress) -> Void
    init(callback: @escaping (PatchProgress) -> Void) { self.callback = callback }
    func report(_ value: PatchProgress) {
        lock.lock(); defer { lock.unlock() }
        let now = Date()
        guard value.phase != phase || value.fraction == 1 || now.timeIntervalSince(previous) >= 0.15 else { return }
        phase = value.phase; previous = now; callback(value)
    }
}
