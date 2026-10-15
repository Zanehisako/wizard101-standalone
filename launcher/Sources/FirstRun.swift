import Foundation
import Darwin

struct FirstRun {
    let paths: PortablePaths
    let token: CancellationToken
    let report: @Sendable (PatchProgress) -> Void
    // Fixture imports use an injected guard; ordinary setup always checks live
    // gameplay through NativePatcher before writing to an installation.
    let gameplayClosed: () throws -> Void
    let availableBytes: () throws -> UInt64
    init(paths: PortablePaths, token: CancellationToken, report: @escaping @Sendable (PatchProgress) -> Void,
         gameplayClosed: @escaping () throws -> Void = NativePatcher.requireClosed,
         availableBytes: (() throws -> UInt64)? = nil) {
        self.paths = paths; self.token = token; self.report = report; self.gameplayClosed = gameplayClosed
        self.availableBytes = availableBytes ?? { try SetupStorage.available(at: paths.data) }
    }
    private func run(_ arguments: [String]) throws {
        try token.check()
        let process = Process(); process.executableURL = paths.wine; process.arguments = arguments
        var environment = paths.environment(ProcessInfo.processInfo.environment)
        // This C++ game does not need Wine's optional Mono/Gecko installers.
        // Suppress their first-prefix dialogs during native setup.
        environment["WINEDLLOVERRIDES"] = (environment["WINEDLLOVERRIDES"] ?? "") + ";mscoree=d;mshtml=d"
        process.environment = environment
        process.standardInput = FileHandle.nullDevice; process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        try process.run()
        while process.isRunning {
            if token.isCancelled { process.terminate(); process.waitUntilExit(); throw CancellationError() }
            Thread.sleep(forTimeInterval: 0.1)
        }
        guard process.terminationStatus == 0 else { throw LauncherError.message("Wine setup failed (code \(process.terminationStatus)). Retry setup.") }
    }
    func initialize() throws {
        try paths.validateRuntime(); try gameplayClosed(); try token.check()
        try SetupStorage.require(free: availableBytes(), copying: 0)
        let fm = FileManager.default
        for directory in [paths.data, paths.prefix, paths.state] {
            guard directory.standardizedFileURL == directory.resolvingSymlinksInPath().standardizedFileURL else { throw LauncherError.message("Setup cannot use a symbolic link for writable data.") }
            try fm.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        }
        report(PatchProgress(phase: "Preparing Windows environment…", detail: "Creating your separate Wizard101 installation.", fraction: nil))
        try run(["wineboot", "-u"])
        // The game is x64; Windows 10 and the native renderer apply only here.
        try run(["reg", "add", "HKCU\\Software\\Wine", "/v", "Version", "/d", "win10", "/f"])
        try run(["reg", "add", "HKCU\\Software\\Wine\\AppDefaults\\WizardGraphicalClient.exe\\DllOverrides", "/v", "d3d9", "/d", "native", "/f"])
        try fm.createDirectory(at: paths.game, withIntermediateDirectories: true)
    }
    func installRenderer() throws {
        try token.check(); try gameplayClosed()
        let source = paths.resources.appendingPathComponent("Renderer/d3d9.dll")
        let expected = try String(contentsOf: paths.resources.appendingPathComponent("Renderer/d3d9.sha256"), encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        guard try Data(contentsOf: source).sha256Hex == expected else { throw LauncherError.message("The bundled renderer failed its integrity check.") }
        let target = try SafeInstallation(base: paths.game).file("Bin/d3d9.dll")
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(contentsOf: source).write(to: target, options: .atomic)
        let adapter = paths.resources.appendingPathComponent("Renderer/w101decompress.dll")
        if FileManager.default.fileExists(atPath: adapter.path) {
            let digest = try String(contentsOf: paths.resources.appendingPathComponent("Renderer/w101decompress.sha256"), encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            let bytes = try Data(contentsOf: adapter)
            guard bytes.sha256Hex == digest else { throw LauncherError.message("The decompression adapter failed its integrity check.") }
            try bytes.write(to: SafeInstallation(base: paths.game).file("Bin/w101decompress.dll"), options: .atomic)
        }
    }
    func importGame(_ source: URL) throws {
        try token.check(); try gameplayClosed()
        let source = source.standardizedFileURL
        guard source != paths.game.standardizedFileURL,
              !source.path.hasPrefix(paths.data.path + "/"), !paths.data.path.hasPrefix(source.path + "/"),
              FileManager.default.fileExists(atPath: source.appendingPathComponent("Bin/WizardGraphicalClient.exe").path) else {
            throw LauncherError.message("Choose the Wizard101 folder containing Bin and Data.")
        }
        guard !FileManager.default.fileExists(atPath: paths.state.appendingPathComponent("setup-complete.json").path) else { throw LauncherError.message("An installation is already configured. Import is only available during first-time setup.") }
        try SetupStorage.require(free: availableBytes(), copying: 0)
        let stage = try SafeInstallation(base: paths.state).file("Import")
        try FileManager.default.createDirectory(at: stage, withIntermediateDirectories: true)
        let sourceRecord = try SafeInstallation(base: paths.state).file("import-source.json")
        if let data = try? Data(contentsOf: sourceRecord), let previous = try? JSONDecoder().decode(String.self, from: data), previous != source.path {
            throw LauncherError.message("Resume the import from the same installation folder.")
        }
        try JSONEncoder().encode(source.path).write(to: sourceRecord, options: .atomic)
        var files: [(URL, URL)] = []
        for name in ["Bin", "Data", "PatchInfo", "LocalPackagesList.txt"] {
            let item = source.appendingPathComponent(name)
            if FileManager.default.fileExists(atPath: item.path) { try collect(item, to: stage.appendingPathComponent(name), files: &files) }
        }
        // Import never executes or copies an official launcher, nor any prefix
        // registry, drive links, credentials, shader captures or launch logs.
        let login = source.appendingPathComponent("PatchClient/BankB/LoginMessages.xml")
        if FileManager.default.fileExists(atPath: login.path) { try collect(login, to: stage.appendingPathComponent("PatchClient/BankB/LoginMessages.xml"), files: &files) }
        for (index, file) in files.enumerated() {
            try copy(file.0, to: file.1)
            report(PatchProgress(phase: "Importing your game…", detail: "\(index + 1) of \(files.count) files · originals preserved",
                                 fraction: Double(index + 1) / Double(max(files.count, 1))))
        }
        let fm = FileManager.default
        try token.check()
        // Commit the whole imported tree in one rename. A cancelled copy stays
        // staged for retry, with the source and game destination untouched.
        guard (try fm.contentsOfDirectory(atPath: paths.game.path)).isEmpty else {
            throw LauncherError.message("The destination contains game files. Resume installation instead of importing again.")
        }
        // POSIX rename atomically replaces the empty directory on this volume.
        guard rename(stage.path, paths.game.path) == 0 else { throw LauncherError.message("Unable to activate the staged import. Keep the source available and retry.") }
        try? fm.removeItem(at: sourceRecord)

    }
    private func collect(_ source: URL, to destination: URL, files: inout [(URL, URL)]) throws {
        try token.check()
        let fm = FileManager.default
        let values = try source.resourceValues(forKeys: [.isSymbolicLinkKey, .isDirectoryKey, .isRegularFileKey])
        guard values.isSymbolicLink != true else { throw LauncherError.message("Import contains a symbolic link. Choose a regular game installation.") }
        let name = source.lastPathComponent.lowercased()
        if ["wizard101.exe", "wizardlauncher.exe", "wizardlauncherui.dll"].contains(name) { return }
        if name.contains("graphics-patch") || name.hasSuffix(".log") || name.hasSuffix(".csv") || name.hasSuffix(".dxso") || name.hasSuffix(".spv") { return }
        if values.isDirectory == true {
            _ = try SafeInstallation(base: paths.state).file(destination.path.replacingOccurrences(of: paths.state.path + "/", with: "", options: .anchored))
            try fm.createDirectory(at: destination, withIntermediateDirectories: true)
            for item in try fm.contentsOfDirectory(at: source, includingPropertiesForKeys: nil).sorted(by: { $0.path < $1.path }) {
                try collect(item, to: destination.appendingPathComponent(item.lastPathComponent), files: &files)
            }
        } else if values.isRegularFile == true {
            files.append((source, destination))
        }
    }
    private func copy(_ source: URL, to destination: URL) throws {
            try token.check()
            let fm = FileManager.default
            let relative = destination.path.replacingOccurrences(of: paths.state.path + "/", with: "", options: .anchored)
            _ = try SafeInstallation(base: paths.state).file(relative)
            try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            if fm.fileExists(atPath: destination.path) {
                let saved = try destination.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey, .fileSizeKey, .contentModificationDateKey])
                let original = try source.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                guard saved.isSymbolicLink != true, saved.isRegularFile == true else { throw LauncherError.message("A staged import path is unsafe.") }
                if saved.fileSize == original.fileSize && saved.contentModificationDate == original.contentModificationDate { return }
                try fm.removeItem(at: destination)
            }
            // APFS clone is independent on write, unlike a hard link.
            if copyfile(source.path, destination.path, nil, copyfile_flags_t(COPYFILE_ALL | COPYFILE_CLONE_FORCE)) != 0 {
                let bytes = try source.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                try SetupStorage.require(free: availableBytes(), copying: UInt64(bytes))
                if copyfile(source.path, destination.path, nil, copyfile_flags_t(COPYFILE_ALL)) != 0 {
                    throw LauncherError.message("Unable to import a game file. Check free disk space and retry.")
                }
            }
    }
    func finish() throws {
        if FileManager.default.fileExists(atPath: paths.state.appendingPathComponent("Import").path) {
            let saved = try JSONDecoder().decode(String.self, from: Data(contentsOf: paths.state.appendingPathComponent("import-source.json")))
            try importGame(URL(fileURLWithPath: saved))
        }
        try installRenderer()
        _ = try NativePatcher(base: paths.game, state: paths.state, token: token, report: report).run(apply: true)
        try bootstrapConfiguration()
        try LoginSchema.verify(paths.game.appendingPathComponent("PatchClient/BankB/LoginMessages.xml"))
        _ = try CodeIntegrityNonce(game: paths.game.appendingPathComponent("Bin/WizardGraphicalClient.exe"), token: token)
        try Data("{\"version\":1}\n".utf8).write(to: paths.state.appendingPathComponent("setup-complete.json"), options: .atomic)
    }
    private func bootstrapConfiguration() throws {
        // The official file list ships defaults under Data, while the Windows
        // launcher normally creates per-user Bin configuration from them.
        let defaults = try XMLDocument(data: Data(contentsOf: paths.game.appendingPathComponent("Data/GameData/defaultconfig.xml")), options: .nodeLoadExternalEntitiesNever)
        guard let root = defaults.rootElement(), root.name == "defaultconfig" else { throw LauncherError.message("Downloaded game configuration is invalid.") }
        for (name, tables) in [("config", Set(root.children?.compactMap { $0.name } ?? [])), ("preferences", Set(["GUISettings", "GameSettings", "SoundSettings", "VersionInfo", "VideoSettings"]))] {
            let target = try SafeInstallation(base: paths.game).file("Bin/\(name).xml")
            if FileManager.default.fileExists(atPath: target.path) { continue }
            let result = XMLElement(name: name), list = XMLElement(name: "_TableList")
            for child in root.children ?? [] where child.kind == .element && child.name != "_TableList" && tables.contains(child.name ?? "") {
                let record = XMLElement(name: "RECORD"), value = XMLElement(name: "Name", stringValue: child.name!)
                value.addAttribute(XMLNode.attribute(withName: "TYPE", stringValue: "STR") as! XMLNode)
                record.addChild(value); list.addChild(record); result.addChild(child.copy() as! XMLNode)
            }
            result.insertChild(list, at: 0)
            let document = XMLDocument(rootElement: result); document.version = "1.0"
            try document.xmlData(options: .nodePrettyPrint).write(to: target, options: .atomic)
        }
    }
}

enum SetupStorage {
    static let reserve: UInt64 = 512 * 1024 * 1024
    static func available(at location: URL) throws -> UInt64 {
        var ancestor = location
        while !FileManager.default.fileExists(atPath: ancestor.path), ancestor.path != "/" {
            ancestor.deleteLastPathComponent()
        }
        let attributes = try FileManager.default.attributesOfFileSystem(forPath: ancestor.path)
        guard let bytes = attributes[.systemFreeSize] as? NSNumber else {
            throw LauncherError.message("Unable to check free disk space. Try setup again.")
        }
        return bytes.uint64Value
    }
    static func require(free: UInt64, copying bytes: UInt64) throws {
        guard free >= reserve, bytes <= free - reserve else {
            throw LauncherError.message("Not enough free disk space. Free some space, then choose Continue setup. Your staged files and original game are safe.")
        }
    }
}
