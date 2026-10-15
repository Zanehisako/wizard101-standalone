import Foundation

// Fixtures exercise failure recovery without Wine, network or user game data.
func runSetupTests(check: (Bool, String) throws -> Void,
                   rejects: (String, () throws -> Void) throws -> Void) throws {
    let fm = FileManager.default
    let root = fm.temporaryDirectory.appendingPathComponent("w101-setup-\(UUID().uuidString)")
    try fm.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? fm.removeItem(at: root) }
    try check(SetupStep.current(needsRosetta: true, runtimeReady: true, gameReady: false) == .prepareMac,
              "Missing Rosetta stays at Prepare Mac")
    try check(SetupStep.current(needsRosetta: false, runtimeReady: false, gameReady: false) == .prepareMac,
              "Missing runtime cannot advance setup")
    try check(SetupStep.current(needsRosetta: false, runtimeReady: true, gameReady: false) == .installGame,
              "Ready Mac offers installation or reuse")
    try check(SetupStep.current(needsRosetta: false, runtimeReady: true, gameReady: true) == .signIn,
              "Existing standalone data advances directly to sign-in")
    try rejects("Setup blocks insufficient storage") { try SetupStorage.require(free: SetupStorage.reserve - 1, copying: 0) }
    try rejects("Fallback copy retains storage reserve") { try SetupStorage.require(free: SetupStorage.reserve + 8, copying: 9) }
    try rejects("Oversized copy cannot overflow storage arithmetic") { try SetupStorage.require(free: UInt64.max, copying: UInt64.max) }
    try SetupStorage.require(free: SetupStorage.reserve + 9, copying: 9)
    let support = root.appendingPathComponent("Library/Application Support")
    let suffix = "drive_c/ProgramData/KingsIsle Entertainment/Wizard101"
    let source = support.appendingPathComponent("CrossOver/Bottles/My Wizards/" + suffix)
    let other = support.appendingPathComponent("Wizard101 Arrival Candidate/Data/Prefix/" + suffix)
    let paths = PortablePaths(resources: root, environment: ["W101_DATA_ROOT": support.appendingPathComponent("Wizard101 Native").path])
    let original = Data("source game and settings".utf8)
    for game in [source, other, paths.game] {
        try fm.createDirectory(at: game.appendingPathComponent("Bin"), withIntermediateDirectories: true)
        try fm.createDirectory(at: game.appendingPathComponent("Data"), withIntermediateDirectories: true)
        for name in ["WizardGraphicalClient.exe", "preferences.xml"] {
            try original.write(to: game.appendingPathComponent("Bin/" + name))
        }
    }
    let found = InstalledGame.discover(home: root, excluding: paths.game)
    try check(found.count == 2 && Set(found.map(\.name)) == Set(["CrossOver — My Wizards", "Wizard101 Arrival Candidate"]),
              "Multiple imports have friendly names and exclude active standalone data")
    // Discovery never follows a linked bottle or unknown directories.
    try fm.createSymbolicLink(at: support.appendingPathComponent("CrossOver/Bottles/Linked"), withDestinationURL: source)
    try check(InstalledGame.discover(home: root, excluding: paths.game) == found, "Import discovery ignores linked sources")
    try fm.removeItem(at: paths.game)
    try fm.createDirectory(at: paths.game, withIntermediateDirectories: true)
    let noSpace = FirstRun(paths: paths, token: CancellationToken(), report: { _ in }, gameplayClosed: {}, availableBytes: { 0 })
    try rejects("Low storage prevents import before staging") { try noSpace.importGame(source) }
    try check(!fm.fileExists(atPath: paths.state.appendingPathComponent("Import").path), "Low storage leaves destination and source intact")
    let token = CancellationToken()
    let interrupted = FirstRun(paths: paths, token: token, report: { update in if update.fraction != nil { token.cancel() } }, gameplayClosed: {})
    try rejects("Import cancellation interrupts an in-flight copy") { try interrupted.importGame(source) }
    try check((try fm.contentsOfDirectory(atPath: paths.game.path)).isEmpty && fm.fileExists(atPath: paths.state.appendingPathComponent("Import/Bin/WizardGraphicalClient.exe").path),
              "Cancelled import retains staged files without activating partial data")
    let resumed = FirstRun(paths: paths, token: CancellationToken(), report: { _ in }, gameplayClosed: {})
    try rejects("A staged import cannot switch sources") { try resumed.importGame(other) }
    try resumed.importGame(source)
    try check(try Data(contentsOf: paths.game.appendingPathComponent("Bin/preferences.xml")) == original,
              "Retry resumes and atomically activates imported settings")
    try check(!fm.fileExists(atPath: paths.state.appendingPathComponent("Import").path), "Successful resume consumes staging")
    try Data("independent clone write".utf8).write(to: paths.game.appendingPathComponent("Bin/preferences.xml"))
    try check(try Data(contentsOf: source.appendingPathComponent("Bin/preferences.xml")) == original,
              "Resumed imported files cannot alter the original")
}
