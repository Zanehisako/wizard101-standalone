import Foundation
import Darwin

struct PrefixRecovery {
    let paths: PortablePaths
    var arguments: [String] { ["-k"] }
    var environment: [String: String] { paths.environment(ProcessInfo.processInfo.environment) }
    var server: URL { paths.runtime.appendingPathComponent("bin/wineserver") }
    // Each helper has a hard bound; signals address only the helper we started.
    static func run(_ executable: URL, arguments: [String], environment: [String: String], timeout: TimeInterval = 6) throws {
        let child = Process(); child.executableURL = executable; child.arguments = arguments; child.environment = environment
        child.standardInput = FileHandle.nullDevice; child.standardOutput = FileHandle.nullDevice; child.standardError = FileHandle.nullDevice
        try child.run()
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        while child.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.05) }
        if child.isRunning {
            child.terminate()
            let grace = ProcessInfo.processInfo.systemUptime + 0.5
            while child.isRunning && ProcessInfo.processInfo.systemUptime < grace { Thread.sleep(forTimeInterval: 0.02) }
            if child.isRunning { kill(child.processIdentifier, SIGKILL) }
            throw LauncherError.message("The game did not close in time. Reopen the launcher to check its status.")
        }
        guard child.terminationStatus == 0 else { throw LauncherError.message("The game could not be closed. Reopen the launcher to check its status.") }
    }
    func forceQuit() throws {
        // Share the exact same lock as setup and updates, including other app copies.
        let lock = try LauncherLock(directory: paths.state)
        defer { withExtendedLifetime(lock) {} }
        guard FileManager.default.fileExists(atPath: paths.prefix.appendingPathComponent("system.reg").path),
              FileManager.default.isExecutableFile(atPath: server.path) else {
            throw LauncherError.message("This installation's Wine prefix or runtime is unavailable.")
        }
        guard try GameActivity.scan(prefix: paths.prefix) != .idle else { return }
        try Self.run(server, arguments: arguments, environment: environment)
        try Self.run(server, arguments: ["-w"], environment: environment)
        guard try GameActivity.scan(prefix: paths.prefix) == .idle else {
            throw LauncherError.message("Wizard101 is still running. Reopen the launcher to try recovery again.")
        }
    }
}

extension GameActivity {
    static func scan(prefix: URL) throws -> GameActivity {
        guard FileManager.default.fileExists(atPath: prefix.path) else { return .idle }
        let child = Process(), output = Pipe()
        child.executableURL = URL(fileURLWithPath: "/bin/ps"); child.arguments = ["-axo", "pid=,comm="]
        child.standardOutput = output; child.standardError = FileHandle.nullDevice
        try child.run()
        let bytes = output.fileHandleForReading.readDataToEndOfFile(); child.waitUntilExit()
        guard child.terminationStatus == 0 else { throw LauncherError.message("Unable to check this installation's game processes.") }
        var result = GameActivity.idle
        for line in String(decoding: bytes, as: UTF8.self).split(separator: "\n") {
            let fields = line.trimmingCharacters(in: .whitespaces).split(maxSplits: 1, whereSeparator: { $0.isWhitespace })
            guard fields.count == 2, let pid = Int32(fields[0]) else { continue }
            let activity = parse(String(fields[1]))
            guard activity != .idle else { continue }
            let scoped = w101_pid_in_prefix(pid, prefix.path)
            guard scoped >= 0 else { throw LauncherError.message("Unable to check this installation's game processes. Try reopening the launcher.") }
            if scoped == 1 && (activity == .game || result == .idle) { result = activity }
        }
        return result
    }
    static func shouldExitAfterHandoff(activity: GameActivity, startedHere: Bool) -> Bool {
        activity == .game && startedHere
    }
}
