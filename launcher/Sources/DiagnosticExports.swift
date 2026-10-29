import Foundation

struct DiagnosticExports {
    let paths: PortablePaths
    var directory: URL { paths.data.appendingPathComponent("Diagnostics") }
    func prepareDirectory() throws -> URL {
        let folder = try SafeInstallation(base: paths.data).file("Diagnostics")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        return folder
    }
    static func validName(_ name: String) -> Bool {
        name.range(of: #"^Wizard101-Diagnostics-build([0-9.]{1,16}|unknown)-[0-9]{8}T[0-9]{6}Z-[A-Fa-f0-9]{8}\.zip$"#, options: .regularExpression) != nil
    }
    func latest() -> URL? {
        guard let folder = try? SafeInstallation(base: paths.data).file("Diagnostics"),
              let files = try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .contentModificationDateKey]) else { return nil }
        return files.filter { file in
            guard Self.validName(file.lastPathComponent),
                  let info = try? file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]) else { return false }
            return info.isRegularFile == true && info.isSymbolicLink != true
        }.max { lhs, rhs in
            let a = (try? lhs.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let b = (try? rhs.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return a == b ? lhs.lastPathComponent < rhs.lastPathComponent : a < b
        }
    }
    func save(_ report: DiagnosticReport) throws -> URL {
        let folder = try prepareDirectory(), fm = FileManager.default
        let staging = folder.appendingPathComponent(".export-" + UUID().uuidString)
        try fm.createDirectory(at: staging, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? fm.removeItem(at: staging) }
        let contents = staging.appendingPathComponent("Wizard101 Diagnostics")
        try fm.createDirectory(at: contents, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        try report.save(to: contents.appendingPathComponent("Diagnostic-Report.json"))
        try Data("""
        Attach this ZIP to your Wizard101 support message.

        Add a screenshot, the exact preload error or Novus location, the time
        with time zone, and whether waiting or re-entering changed the scene.
        Save a new ZIP immediately after each failure so the observations match.

        The JSON contains safe diagnostic observations and selected settings.
        Passwords, account names, tickets, session keys and raw logs are excluded.
        Nothing was uploaded automatically.

        """.utf8).write(to: contents.appendingPathComponent("README.txt"))
        let archive = staging.appendingPathComponent("Report.zip")
        let zip = Process(); zip.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        zip.arguments = ["-c", "-k", "--norsrc", "--noextattr", "--keepParent", contents.path, archive.path]
        zip.standardOutput = FileHandle.nullDevice; zip.standardError = FileHandle.nullDevice
        try zip.run(); zip.waitUntilExit()
        guard zip.terminationStatus == 0 else { throw LauncherError.message("Couldn’t package the diagnostic report.") }
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: archive.path)
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown"
        let safeBuild = build.range(of: "^[0-9.]{1,16}$", options: .regularExpression) != nil ? build : "unknown"
        let name = "Wizard101-Diagnostics-build\(safeBuild)-\(formatter.string(from: Date()))-\(UUID().uuidString.prefix(8)).zip"
        let destination = try SafeInstallation(base: folder).file(name)
        try fm.moveItem(at: archive, to: destination)
        return destination
    }
}
