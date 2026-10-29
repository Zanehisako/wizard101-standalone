import Foundation

// A saved report checks the archive bytes again, against the dated manifest
// observed by this launcher. It never fetches/installs content during reporting.
enum ArchiveAudit {
    static func file(_ url: URL, archive: PatchDiagnostics.Archive, staging: Bool, token: CancellationToken) -> [String: Any] {
        guard FileManager.default.fileExists(atPath: url.path) else { return ["status": "missing"] }
        do {
            let validation = ChecksumCache.Validation(mode: .fullFile, bytes: archive.size, crc: archive.crc, table: "", source: archive.source)
            let before = try ChecksumCache.Entry.fingerprint(url, validation: validation)
            let allocated = try url.resourceValues(forKeys: [.fileAllocatedSizeKey]).fileAllocatedSize
            var result: [String: Any] = ["logical_bytes": before.size]
            if let allocated { result["allocated_bytes"] = allocated }
            if before.size != archive.size {
                result["status"] = staging && before.size < archive.size ? "partial" : "verification_failed"
                return result
            }
            let full = try Integrity.crc(url, token: token)
            result["observed_full_crc"] = full
            result["full_crc_matches"] = full == archive.crc
            if full == archive.crc { result["status"] = "complete" }
            else if archive.streamed {
                let header = try Integrity.crc(url, token: token, byteCount: archive.headerSize)
                result["header_crc_matches"] = header == archive.headerCRC
                result["status"] = header == archive.headerCRC ? "valid_streamed_header" : "verification_failed"
            } else { result["status"] = "verification_failed" }
            let after = try ChecksumCache.Entry.fingerprint(url, validation: validation)
            guard before.sameFile(after) else { return ["status": "changed_during_check"] }
            return result
        } catch { return ["status": "unavailable"] }
    }
    static func inspect(paths: PortablePaths, manifest: PatchDiagnostics.Manifest?) -> [String: Any] {
        guard let manifest, manifest.valid else { return ["available": false] }
        let token = CancellationToken()
        let game = SafeInstallation(base: paths.game), state = SafeInstallation(base: paths.state)
        let stagedNames = (try? FileManager.default.contentsOfDirectory(atPath: paths.state.path)) ?? []
        let archives: [[String: Any]] = manifest.archives.map { archive in
            let installed = (try? game.file(archive.path)).map { file($0, archive: archive, staging: false, token: token) } ?? ["status": "unavailable"]
            let staged = (try? state.file(archive.stagingName)).map { file($0, archive: archive, staging: true, token: token) } ?? ["status": "unavailable"]
            return ["archive": archive.path, "expected_bytes": archive.size, "expected_crc": archive.crc,
                    "installed": installed, "staged": staged,
                    "retained_rejected_files": stagedNames.filter { $0.hasPrefix(archive.stagingName + ".") && $0.contains(".rejected-") }.count]
        }
        return ["available": true, "read_only": true, "checked_utc": ISO8601DateFormatter().string(from: Date()),
                "revision": manifest.revision, "manifest_checked_utc": manifest.checkedUTC,
                "scope": "Novus, housing Novus, shared, Mob and Equipment archives plus the latest failed archive. Expected checksums are from the dated patch check; no network refresh during report collection. A valid streamed header does not verify the body or establish a graphics fix.",
                "archives": archives]
    }
}
