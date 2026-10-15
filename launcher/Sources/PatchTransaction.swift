import Foundation
import Darwin

final class LauncherLock {
    private var fd: Int32 = -1
    init(directory: URL) throws {
        guard directory.standardizedFileURL == directory.resolvingSymlinksInPath().standardizedFileURL else { throw LauncherError.message("The launcher state directory contains a symbolic link.") }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        fd = open(directory.appendingPathComponent("operation.lock").path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard fd >= 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            if fd >= 0 { close(fd); fd = -1 }
            throw LauncherError.message("Another native launcher is already signing in, updating, or running the game.")
        }
    }
    deinit { if fd >= 0 { flock(fd, LOCK_UN); close(fd) } }
}

struct SafeInstallation {
    let base: URL
    func file(_ path: String) throws -> URL {
        guard base.standardizedFileURL == base.resolvingSymlinksInPath().standardizedFileURL else { throw LauncherError.message("The game installation directory contains a symbolic link.") }
        try PatchManifest.validatePath(path)
        var current = base
        // lstat, rather than resolving symlinks, also protects missing destinations.
        for component in path.split(separator: "/") {
            current.appendPathComponent(String(component))
            var info = stat()
            if lstat(current.path, &info) == 0 {
                guard info.st_mode & S_IFMT != S_IFLNK else { throw LauncherError.message("The installation contains a symbolic link at an update path.") }
            } else if errno != ENOENT { throw LauncherError.message("Unable to inspect an update path.") }
        }
        return current
    }
}

final class ChecksumCache {
    enum Mode: String, Codable { case fullFile, archiveHeader }
    struct Validation: Codable, Equatable {
        let mode: Mode
        let bytes: UInt64
        let crc: UInt32
        let table: String, source: String
    }
    struct Entry: Codable {
        let device: UInt64, inode: UInt64, size: UInt64, mtime: Int64, mtimeNS: Int64, ctime: Int64, ctimeNS: Int64
        let validation: Validation
        static func fingerprint(_ url: URL, validation: Validation) throws -> Entry {
            var s = stat()
            guard lstat(url.path, &s) == 0, s.st_mode & S_IFMT == S_IFREG else { throw LauncherError.message("Unable to inspect a game file.") }
            return Entry(device: UInt64(s.st_dev), inode: UInt64(s.st_ino), size: UInt64(s.st_size),
                         mtime: Int64(s.st_mtimespec.tv_sec), mtimeNS: Int64(s.st_mtimespec.tv_nsec),
                         ctime: Int64(s.st_ctimespec.tv_sec), ctimeNS: Int64(s.st_ctimespec.tv_nsec), validation: validation)
        }
        func sameFile(_ other: Entry) -> Bool {
            device == other.device && inode == other.inode && size == other.size && mtime == other.mtime && mtimeNS == other.mtimeNS && ctime == other.ctime && ctimeNS == other.ctimeNS
        }
    }
    struct Storage: Codable { let version: Int; let entries: [String: Entry] }
    private let url: URL
    private var entries: [String: Entry]
    init(url: URL) {
        self.url = url
        let saved = try? JSONDecoder().decode(Storage.self, from: Data(contentsOf: url))
        // Older caches have no validation scope and must be rebuilt.
        if let saved, saved.version == 2 { entries = saved.entries } else { entries = [:] }
    }
    func valid(_ file: URL, record: PatchRecord, token: CancellationToken, mode requestedMode: Mode? = nil) throws -> Bool {
        try token.check()
        let mode = requestedMode ?? (record.streamedArchive ? .archiveHeader : .fullFile)
        let validation = Validation(mode: mode, bytes: mode == .archiveHeader ? record.headerSize : record.size,
                                    crc: mode == .archiveHeader ? record.headerCRC : record.crc, table: record.table, source: record.source)
        let fingerprint = try Entry.fingerprint(file, validation: validation)
        guard fingerprint.size == record.size, mode != .archiveHeader || (validation.bytes > 0 && validation.bytes <= record.size) else {
            entries.removeValue(forKey: record.localPath); return false
        }
        if let cached = entries[record.localPath], cached.validation == validation, cached.sameFile(fingerprint) { return true }
        let crc = try Integrity.crc(file, token: token, byteCount: mode == .archiveHeader ? validation.bytes : nil)
        // Do not cache a checksum if the file changed while it was being read.
        let after = try Entry.fingerprint(file, validation: validation)
        guard after.sameFile(fingerprint), crc == validation.crc else { entries.removeValue(forKey: record.localPath); return false }
        entries[record.localPath] = after
        return true
    }
    func save() throws { try JSONEncoder().encode(Storage(version: 2, entries: entries)).write(to: url, options: .atomic) }
}

struct PatchInventory {
    let needed: [PatchRecord]
    let checkedFiles: Int, streamedArchives: Int, optionalMissing: Int, launcherExcluded: Int
    let headerBootstraps: Set<String>
    var downloadBytes: UInt64 { needed.reduce(0) { $0 + (headerBootstraps.contains($1.localPath) ? $1.compressedHeaderSize : $1.downloadSize) } }
    static func inspect(records: [PatchRecord], base: URL, cache: ChecksumCache, token: CancellationToken,
                        requireClosed: () throws -> Void = {}, prepareAppearance: Bool = false, progress: (Int, Int) -> Void = { _, _ in }) throws -> PatchInventory {
        let installation = SafeInstallation(base: base), fm = FileManager.default
        var selected: [PatchRecord] = [], needed: [PatchRecord] = []
        var optionalMissing = 0, launcherExcluded = 0, streamedArchives = 0, headerBootstraps = Set<String>()
        for record in records {
            try token.check()
            let file = try installation.file(record.localPath)
            if record.officialLauncher && !record.loginDefinition { launcherExcluded += 1; continue }
            if record.protected && !(record.bootstrapOnly && !fm.fileExists(atPath: file.path)) { continue }
            if !fm.fileExists(atPath: file.path) && !record.requiredAtStartup && !(prepareAppearance && record.appearanceArchive) { optionalMissing += 1; continue }
            selected.append(record)
        }
        for (index, record) in selected.enumerated() {
            try token.check()
            if index % 32 == 0 { try requireClosed() }
            let file = try installation.file(record.localPath)
            if try !fm.fileExists(atPath: file.path) || !cache.valid(file, record: record, token: token, mode: prepareAppearance && record.appearanceArchive ? .fullFile : nil) {
                needed.append(record)
                if record.type == 5 && record.streamedArchive && record.compressedHeaderSize > 0 && !(prepareAppearance && record.appearanceArchive) && !fm.fileExists(atPath: file.path) { headerBootstraps.insert(record.localPath) }
            }
            else if record.streamedArchive { streamedArchives += 1 }
            progress(index + 1, selected.count)
        }
        return PatchInventory(needed: needed, checkedFiles: selected.count, streamedArchives: streamedArchives,
                              optionalMissing: optionalMissing, launcherExcluded: launcherExcluded, headerBootstraps: headerBootstraps)
    }
}

struct PatchResult { let manifest: PatchManifest; let inventory: PatchInventory }

struct PatchProgress: Sendable {
    let phase: String
    let detail: String
    let fraction: Double?
}

final class PatchTransaction {
    struct Item: Codable {
        let path: String, staged: String, backup: String, hadOriginal: Bool
        let size: UInt64, crc: UInt32
        var headerSize: UInt64? = nil
        var headerCRC: UInt32? = nil
    }
    struct Journal: Codable { var committed: Bool; let items: [Item] }
    let installation: SafeInstallation
    let state: URL
    let gameplayClosed: () throws -> Void
    private var journalURL: URL { state.appendingPathComponent("transaction.json") }
    init(base: URL, state: URL, gameplayClosed: @escaping () throws -> Void) {
        installation = SafeInstallation(base: base); self.state = state; self.gameplayClosed = gameplayClosed
    }
    private func write(_ journal: Journal) throws {
        try JSONEncoder().encode(journal).write(to: journalURL, options: .atomic)
        let handle = try FileHandle(forWritingTo: journalURL); try handle.synchronize(); try handle.close()
        let directory = open(state.path, O_RDONLY); if directory >= 0 { _ = fsync(directory); close(directory) }
    }
    func recover() throws {
        guard FileManager.default.fileExists(atPath: journalURL.path) else { return }
        try gameplayClosed()
        let journal = try JSONDecoder().decode(Journal.self, from: Data(contentsOf: journalURL))
        for item in journal.items {
            _ = try installation.file(item.path)
            guard item.staged == URL(fileURLWithPath: item.staged).lastPathComponent,
                  item.backup == URL(fileURLWithPath: item.backup).lastPathComponent,
                  item.backup.hasPrefix("backup-"), item.staged.hasSuffix(".part"),
                  item.backup != ".", item.backup != "..", item.staged != ".", item.staged != "..",
                  (!PatchRecord(source: item.path, target: "", type: 1, size: item.size, crc: item.crc).protected ||
                   (!item.hadOriginal && PatchRecord(source: item.path, target: "", type: 1, size: item.size, crc: item.crc).bootstrapOnly)) else { throw LauncherError.message("The recovery journal contains an unsafe path.") }
            guard (item.headerSize == nil && item.headerCRC == nil) ||
                (!item.hadOriginal && item.path.lowercased().hasPrefix("data/") && item.path.lowercased().hasSuffix(".wad") &&
                 (item.headerSize ?? 0) > 0 && (item.headerSize ?? UInt64.max) <= item.size && item.headerCRC != nil) else {
                throw LauncherError.message("The recovery journal contains unsafe archive validation.")
            }
        }
        if !journal.committed {
            // Backups are hard links created before the journal or any replacement.
            // Copy to a temporary file before rename so recovery itself is repeatable.
            for item in journal.items.reversed() {
                try gameplayClosed()
                let destination = try installation.file(item.path)
                let backup = state.appendingPathComponent(item.backup)
                if item.hadOriginal {
                    guard FileManager.default.fileExists(atPath: backup.path) else { throw LauncherError.message("A required recovery backup is missing. The installed app was not replaced.") }
                    let temp = state.appendingPathComponent("restore-\(UUID().uuidString)")
                    try FileManager.default.copyItem(at: backup, to: temp)
                    let restored = try FileHandle(forWritingTo: temp); try restored.synchronize(); try restored.close()
                    guard rename(temp.path, destination.path) == 0 else { try? FileManager.default.removeItem(at: temp); throw LauncherError.message("Unable to restore an interrupted update.") }
                    let fd = open(destination.deletingLastPathComponent().path, O_RDONLY); if fd >= 0 { _ = fsync(fd); close(fd) }
                } else if FileManager.default.fileExists(atPath: destination.path) {
                    // Only remove a new destination if it is the staged, validated file.
                    let valid = item.headerSize.map { Integrity.matchesHeader(destination, size: item.size, headerSize: $0, headerCRC: item.headerCRC!, token: CancellationToken()) }
                        ?? Integrity.matches(destination, size: item.size, crc: item.crc, token: CancellationToken())
                    guard valid else { throw LauncherError.message("An interrupted update destination changed. Recovery needs attention.") }
                    try FileManager.default.removeItem(at: destination)
                }
            }
        }
        if !journal.committed { try write(Journal(committed: true, items: journal.items)) }
        for item in journal.items { try? FileManager.default.removeItem(at: state.appendingPathComponent(item.backup)) }
        try FileManager.default.removeItem(at: journalURL)
    }
    func commit(_ files: [(PatchRecord, URL)], token: CancellationToken, headerBootstraps: Set<String> = []) throws {
        try token.check(); try gameplayClosed()
        let fm = FileManager.default
        var items: [Item] = []
        do {
            for (record, staged) in files {
                try token.check(); try gameplayClosed()
                let destination = try installation.file(record.localPath)
                let initialHeader = headerBootstraps.contains(record.localPath)
                let existing = fm.fileExists(atPath: destination.path)
                let headerAllowed = !initialHeader || (!existing && record.type == 5 && record.streamedArchive && record.localPath.lowercased().hasPrefix("data/"))
                let valid = initialHeader ? Integrity.matchesHeader(staged, size: record.size, headerSize: record.headerSize, headerCRC: record.headerCRC, token: token)
                    : Integrity.matches(staged, size: record.size, crc: record.crc, token: token)
                guard record.mayInstall(at: destination), staged.deletingLastPathComponent().standardizedFileURL == state.standardizedFileURL,
                      headerAllowed, valid else {
                    throw LauncherError.message("An update file failed its final integrity check.")
                }
                try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
                let name = "backup-\(UUID().uuidString)"
                if existing { try fm.linkItem(at: destination, to: state.appendingPathComponent(name)) }
                items.append(Item(path: record.localPath, staged: staged.lastPathComponent, backup: name, hadOriginal: existing, size: record.size, crc: record.crc,
                                  headerSize: initialHeader ? record.headerSize : nil, headerCRC: initialHeader ? record.headerCRC : nil))
            }
            try write(Journal(committed: false, items: items))
        } catch {
            if !fm.fileExists(atPath: journalURL.path) { for item in items { try? fm.removeItem(at: state.appendingPathComponent(item.backup)) } }
            throw error
        }
        do {
            for item in items {
                try token.check(); try gameplayClosed()
                let destination = try installation.file(item.path)
                guard rename(state.appendingPathComponent(item.staged).path, destination.path) == 0 else { throw LauncherError.message("Unable to replace an updated game file.") }
                for directory in [state, destination.deletingLastPathComponent()] {
                    let fd = open(directory.path, O_RDONLY); if fd >= 0 { _ = fsync(fd); close(fd) }
                }
            }
            try write(Journal(committed: true, items: items))
            try recover()
        } catch {
            // If a game was opened externally, defer recovery until it is closed.
            try? recover()
            throw error
        }
    }
}


struct RevisionMetadata {
    static func stage(revision: String, base: URL, state: URL, token: CancellationToken) throws -> [(PatchRecord, URL)] {
        guard revision.range(of: "^r[0-9]+\\.[A-Za-z0-9_]+$", options: .regularExpression) != nil else {
            throw LauncherError.message("Unsupported patch revision identifier.")
        }
        let content = Data((revision + "\n").utf8), installation = SafeInstallation(base: base)
        var updates: [(PatchRecord, URL)] = []
        for path in ["Bin/revision.dat", "Bin/data.dat"] {
            try token.check()
            let destination = try installation.file(path)
            if (try? Data(contentsOf: destination)) == content { continue }
            let record = PatchRecord(source: path, target: "", type: 1, size: UInt64(content.count), crc: content.kiCRC)
            let staged = state.appendingPathComponent(Data((revision + path).utf8).sha256Hex + ".part")
            try content.write(to: staged, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: staged.path)
            let handle = try FileHandle(forWritingTo: staged); try handle.synchronize(); try handle.close()
            updates.append((record, staged))
        }
        return updates
    }
}

final class NativePatcher: Sendable {
    let base: URL, state: URL
    let token: CancellationToken
    let report: @Sendable (PatchProgress) -> Void
    init(base: URL, state: URL, token: CancellationToken, report: @escaping @Sendable (PatchProgress) -> Void) {
        self.base = base; self.state = state; self.token = token; self.report = report
    }
    static func requireClosed() throws {
        guard try GameActivity.scan() == .idle else { throw LauncherError.message("Close Wizard101 and its official launcher before updating. Your game was left running.") }
    }
    static func stagingName(_ record: PatchRecord) -> String {
        Data("\(record.source):\(record.size):\(record.crc)".utf8).sha256Hex + ".part"
    }
    static func additionalStagingBytes(_ records: [PatchRecord], state: URL, headerBootstraps: Set<String> = [], token: CancellationToken = CancellationToken()) -> UInt64 {
        func remaining(_ url: URL, _ expected: UInt64, validComplete: (() -> Bool)? = nil) -> UInt64 {
            let info = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            let saved = info?.isRegularFile == true && info?.isSymbolicLink != true ? UInt64(max(0, info?.fileSize ?? 0)) : 0
            // A header-valid sparse .part can have the full logical length.
            // The downloader restarts complete invalid files; reserve its full
            // body rather than counting holes as downloaded bytes.
            if saved >= expected, let validComplete, !validComplete() { return expected }
            return expected - min(expected, saved)
        }
        return records.reduce(0) { count, record in
            let target = state.appendingPathComponent(stagingName(record))
            if headerBootstraps.contains(record.localPath) {
                return count + remaining(target.appendingPathExtension("hdr.gz"), record.compressedHeaderSize)
                    + remaining(target.appendingPathExtension("header"), record.headerSize) + remaining(target, record.headerSize)
            }
            if record.type == 4 {
                return count + remaining(target.appendingPathExtension("gz"), record.downloadSize) + remaining(target, record.size, validComplete: { Integrity.matches(target, size: record.size, crc: record.crc, token: token) })
            }
            let body = remaining(target, record.size, validComplete: { Integrity.matches(target, size: record.size, crc: record.crc, token: token) })
            if body > 0 && ArchivePrefix.required(record: record, destination: target) {
                let header = target.appendingPathExtension("header")
                let expanded = remaining(header, record.headerSize, validComplete: { Integrity.matches(header, size: record.headerSize, crc: record.headerCRC, token: token) })
                let wire = expanded == 0 ? 0 : remaining(target.appendingPathExtension("hdr.gz"), record.compressedHeaderSize)
                return count + body + expanded + wire
            }
            return count + body
        }
    }
    static func hasStagingSpace(_ records: [PatchRecord], state: URL, free: UInt64, headerBootstraps: Set<String> = [], token: CancellationToken = CancellationToken()) -> Bool {
        // An up-to-date installation needs no update staging reserve.
        if records.isEmpty { return true }
        let reserve: UInt64 = 512 * 1024 * 1024
        return free > reserve && additionalStagingBytes(records, state: state, headerBootstraps: headerBootstraps, token: token) < free - reserve
    }
    private func archiveHeader(_ record: PatchRecord, prefix: URL, target: URL, progress: @escaping (UInt64) -> Void) throws -> URL {
        let installation = SafeInstallation(base: state)
        let header = try installation.file(target.lastPathComponent + ".header")
        let wire = try installation.file(target.lastPathComponent + ".hdr.gz")
        if !Integrity.matches(header, size: record.headerSize, crc: record.headerCRC, token: token) {
            let wireSize = (try? FileManager.default.attributesOfItem(atPath: wire.path))?[.size] as? NSNumber
            if wireSize?.uint64Value != record.compressedHeaderSize {
                try HTTPTransfer.download(url: prefix.appendingPathComponent(record.source + ".hdr.gz"), to: wire,
                                          size: record.compressedHeaderSize, token: token, progress: progress)
            }
            let result = w101_gunzip_file(wire.path, header.path, record.headerSize, { context in
                guard let context else { return 1 }
                return Unmanaged<CancellationToken>.fromOpaque(context).takeUnretainedValue().isCancelled ? 1 : 0
            }, Unmanaged.passUnretained(token).toOpaque())
            try token.check()
            guard result == 0, Integrity.matches(header, size: record.headerSize, crc: record.headerCRC, token: token) else {
                try? FileManager.default.removeItem(at: wire); try? FileManager.default.removeItem(at: header)
                throw LauncherError.message("A streamed archive header failed validation. Retry to download it again.")
            }
        }
        return header
    }
    func run(apply: Bool, prepareAppearance: Bool = false) throws -> PatchResult {
        try Self.requireClosed(); try token.check()
        try FileManager.default.createDirectory(at: state, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let transaction = PatchTransaction(base: base, state: state, gameplayClosed: Self.requireClosed)
        if apply { try transaction.recover() }
        else if FileManager.default.fileExists(atPath: state.appendingPathComponent("transaction.json").path) {
            throw LauncherError.message("An interrupted update needs recovery before checking files.")
        }
        report(PatchProgress(phase: "Checking updates…", detail: "Querying the US Windows patch server.", fraction: nil))
        let manifest = try PatchManifest.fetch(token: token, staging: state)
        let cache = ChecksumCache(url: state.appendingPathComponent("checksums.json"))
        let installation = SafeInstallation(base: base)
        let inventory = try PatchInventory.inspect(records: manifest.records, base: base, cache: cache, token: token, requireClosed: Self.requireClosed, prepareAppearance: prepareAppearance) { index, count in
            report(PatchProgress(phase: "Checking installed files…", detail: "\(index) of \(count)", fraction: Double(index) / Double(count)))
        }
        let needed = inventory.needed
        try cache.save()
        if !apply {
            report(PatchProgress(phase: "Update check complete", detail: "\(needed.count) files need updates or startup downloads. Revision \(manifest.revision).", fraction: 1))
            return PatchResult(manifest: manifest, inventory: inventory)
        }
        try token.check(); try Self.requireClosed()
        let total = inventory.downloadBytes
        var counts = [String: UInt64](), failure: Error?, staged: [(PatchRecord, URL)] = []
        let lock = NSLock(), queue = OperationQueue(); queue.maxConcurrentOperationCount = 3
        let free = (try FileManager.default.attributesOfFileSystem(forPath: state.path)[.systemFreeSize] as? NSNumber)?.uint64Value ?? 0
        guard Self.hasStagingSpace(needed, state: state, free: free, headerBootstraps: inventory.headerBootstraps, token: token) else { throw LauncherError.message("There is not enough free space to stage this update.") }
        for record in needed {
            queue.addOperation {
                do {
                    try self.token.check()
                    let name = Self.stagingName(record)
                    let target = self.state.appendingPathComponent(name)
                    let downloadProgress: (UInt64) -> Void = { value in
                        lock.lock(); counts[record.localPath] = value
                        let count = counts.values.reduce(UInt64(0), +); lock.unlock()
                        self.report(PatchProgress(phase: "Downloading updates…", detail: "\(ByteCountFormatter.string(fromByteCount: Int64(count), countStyle: .file)) of \(ByteCountFormatter.string(fromByteCount: Int64(total), countStyle: .file))", fraction: total == 0 ? 1 : Double(count) / Double(total)))
                    }
                    if inventory.headerBootstraps.contains(record.localPath) {
                        if !Integrity.matchesHeader(target, size: record.size, headerSize: record.headerSize, headerCRC: record.headerCRC, token: self.token) {
                            let header = try self.archiveHeader(record, prefix: manifest.prefix, target: target, progress: downloadProgress)
                            try InitialArchive.stage(header: header, destination: target, record: record, token: self.token)
                        }
                    } else if !Integrity.matches(target, size: record.size, crc: record.crc, token: self.token) {
                        let source = manifest.prefix.appendingPathComponent(record.downloadSource)
                        let wireTarget = record.type == 4 ? self.state.appendingPathComponent(name + ".gz") : target
                        guard record.downloadSize > 0 else { throw LauncherError.message("Missing compressed download size.") }
                        let wireComplete = record.type == 4 && (try? wireTarget.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])).map { $0.isRegularFile == true && UInt64($0.fileSize ?? 0) == record.downloadSize } == true
                        if !wireComplete {
                            if ArchivePrefix.required(record: record, destination: target) {
                                let header = try self.archiveHeader(record, prefix: manifest.prefix, target: target, progress: downloadProgress)
                                try ArchivePrefix.stage(header: header, destination: target, record: record, token: self.token)
                            }
                            try HTTPTransfer.download(url: source, to: wireTarget, size: record.downloadSize, token: self.token, progress: downloadProgress)
                        }
                        if record.type == 4 {
                            let result = w101_gunzip_file(wireTarget.path, target.path, record.size, { context in
                                guard let context else { return 1 }
                                return Unmanaged<CancellationToken>.fromOpaque(context).takeUnretainedValue().isCancelled ? 1 : 0
                            }, Unmanaged.passUnretained(self.token).toOpaque())
                            try self.token.check()
                            if result != 0 {
                                try? FileManager.default.removeItem(at: wireTarget)
                                throw LauncherError.message("A compressed download failed validation. Retry to download it again.")
                            }
                        }
                        guard Integrity.matches(target, size: record.size, crc: record.crc, token: self.token) else {
                            try? FileManager.default.removeItem(at: target)
                            if record.type == 4 { try? FileManager.default.removeItem(at: wireTarget) }
                            throw LauncherError.message("A download failed its checksum. Retry to download it again.")
                        }
                    }
                    lock.lock(); counts[record.localPath] = inventory.headerBootstraps.contains(record.localPath) ? record.compressedHeaderSize : record.downloadSize; staged.append((record, target)); lock.unlock()
                } catch {
                    lock.lock()
                    if failure == nil { failure = error is CancellationError ? error : LauncherError.message("Update failed for \(record.localPath): \(error.localizedDescription)") }
                    lock.unlock(); self.token.cancel()
                }
            }
        }
        queue.waitUntilAllOperationsAreFinished()
        if let failure { throw failure }
        try token.check()
        report(PatchProgress(phase: "Installing verified updates…", detail: "Keeping your graphics patch and settings.", fraction: nil))
        staged += try RevisionMetadata.stage(revision: manifest.revision, base: base, state: state, token: token)
        try transaction.commit(staged, token: token, headerBootstraps: inventory.headerBootstraps)
        for (record, _) in staged { _ = try cache.valid(installation.file(record.localPath), record: record, token: token,
                                                     mode: inventory.headerBootstraps.contains(record.localPath) ? .archiveHeader : .fullFile) }
        try cache.save()
        report(PatchProgress(phase: "Content is ready", detail: manifest.revision, fraction: 1))
        return PatchResult(manifest: manifest, inventory: inventory)
    }
}

enum ArchivePrefix {
    static func required(record: PatchRecord, destination: URL) -> Bool {
        guard record.type == 5, record.streamedArchive, record.compressedHeaderSize > 0,
              record.headerSize > 0, record.headerSize < record.size else { return false }
        let attributes = try? FileManager.default.attributesOfItem(atPath: destination.path)
        guard attributes == nil || attributes?[.type] as? FileAttributeType == .typeRegular else { return false }
        let saved = (attributes?[.size] as? NSNumber)?.uint64Value ?? 0
        return saved < record.headerSize || saved >= record.size
    }
    static func stage(header: URL, destination: URL, record: PatchRecord, token: CancellationToken) throws {
        try token.check()
        guard required(record: record, destination: destination),
              header.standardizedFileURL != destination.standardizedFileURL,
              header.deletingLastPathComponent().standardizedFileURL == destination.deletingLastPathComponent().standardizedFileURL,
              Integrity.matches(header, size: record.headerSize, crc: record.headerCRC, token: token) else {
            throw LauncherError.message("Invalid full-archive download prefix.")
        }
        let source = try FileHandle(forWritingTo: header); try source.synchronize(); try source.close()
        try token.check()
        // A CRC-verified prefix is useful progress, never a completed archive.
        // Atomically replace only staging; the installed file is untouched.
        guard rename(header.path, destination.path) == 0 else { throw LauncherError.message("Unable to stage an archive download prefix.") }
        let fd = open(destination.deletingLastPathComponent().path, O_RDONLY); if fd >= 0 { _ = fsync(fd); close(fd) }
    }
}

enum InitialArchive {
    static func stage(header: URL, destination: URL, record: PatchRecord, token: CancellationToken) throws {
        try token.check()
        guard record.type == 5, record.streamedArchive, Integrity.matches(header, size: record.headerSize, crc: record.headerCRC, token: token) else {
            throw LauncherError.message("Invalid initial streamed archive header.")
        }
        let descriptor = open(destination.path, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else { throw LauncherError.message("Unable to stage an initial archive.") }
        let target = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? target.close() }
        let source = try FileHandle(forReadingFrom: header); defer { try? source.close() }
        while let bytes = try source.read(upToCount: 65536), !bytes.isEmpty { try token.check(); try target.write(contentsOf: bytes) }
        // This is the official first-install layout: verified header plus an
        // empty sparse body. The game populates its streamed resources later.
        try target.truncate(atOffset: record.size); try target.synchronize()
        guard Integrity.matchesHeader(destination, size: record.size, headerSize: record.headerSize, headerCRC: record.headerCRC, token: token) else {
            throw LauncherError.message("The initial streamed archive failed validation.")
        }
    }
}
