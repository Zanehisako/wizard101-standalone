import Foundation

struct PortablePaths: Sendable {
    let runtime: URL
    let data: URL
    let resources: URL
    var prefix: URL { data.appendingPathComponent("Prefix") }
    var state: URL { data.appendingPathComponent("State") }
    var game: URL { prefix.appendingPathComponent("drive_c/ProgramData/KingsIsle Entertainment/Wizard101") }
    var wine: URL { runtime.appendingPathComponent("bin/wine") }
    init(resources: URL = Bundle.main.resourceURL!, environment: [String: String] = ProcessInfo.processInfo.environment, bundledDataRoot: String? = Bundle.main.object(forInfoDictionaryKey: "W101DataRoot") as? String) {
        self.resources = resources
        runtime = environment["W101_RUNTIME_ROOT"].map { URL(fileURLWithPath: $0) } ?? resources.appendingPathComponent("Runtime")
        let directory = Bundle.main.object(forInfoDictionaryKey: "W101DefaultDataDirectory") as? String ?? "Wizard101 Native"
        data = (environment["W101_DATA_ROOT"] ?? bundledDataRoot).map { URL(fileURLWithPath: $0) } ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/\(directory)")
    }
    func windowsPath(_ url: URL) -> String {
        let c = prefix.appendingPathComponent("drive_c").path + "/"
        if url.path.hasPrefix(c) { return "C:\\" + url.path.dropFirst(c.count).replacingOccurrences(of: "/", with: "\\") }
        return "Z:" + url.path.replacingOccurrences(of: "/", with: "\\")
    }
    func validateRuntime() throws {
        guard FileManager.default.isExecutableFile(atPath: wine.path),
              FileManager.default.fileExists(atPath: runtime.appendingPathComponent("runtime.json").path) else {
            throw LauncherError.message("The bundled Wine runtime is missing. Download the complete app archive.")
        }
        guard try Self.rosettaAvailable() else { throw LauncherError.message("One quick step: install Apple's Rosetta, then continue.") }
    }
    static func rosettaAvailable() throws -> Bool {
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/arch"); p.arguments = ["-x86_64", "/usr/bin/true"]
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        try p.run(); p.waitUntilExit()
        return p.terminationStatus == 0
    }
    func environment(_ inherited: [String: String]) -> [String: String] {
        var env = inherited
        for key in Array(env.keys) where key.hasPrefix("W101_WORKLOAD_") || key.hasPrefix("CX_") || key.hasPrefix("CROSSOVER") || key.hasPrefix("DYLD_") || key.hasPrefix("WINE") || key.hasPrefix("VK_") || key.hasPrefix("DXVK_") || key.hasPrefix("D9VK_") { env.removeValue(forKey: key) }
        env["PATH"] = runtime.appendingPathComponent("bin").path + ":/usr/bin:/bin:/usr/sbin:/sbin"
        env["WINEPREFIX"] = prefix.path; env["WINEARCH"] = "win64"
        env["WINEDLLOVERRIDES"] = "d3d9=n;winemenubuilder.exe=d"
        env["WINEDEBUG"] = "-all"; env["WINEMSYNC"] = "1"
        env["WINEDLLPATH"] = runtime.appendingPathComponent("lib/wine").path
        env["DYLD_FALLBACK_LIBRARY_PATH"] = runtime.appendingPathComponent("lib").path + ":/usr/lib"
        env["VK_ICD_FILENAMES"] = runtime.appendingPathComponent("share/vulkan/icd.d/MoltenVK_icd.json").path
        env["MVK_CONFIG_RESUME_LOST_DEVICE"] = "1"
        return env
    }
}
