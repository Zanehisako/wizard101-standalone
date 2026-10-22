import Foundation
import CryptoKit

enum ContentPreparation: String, Codable {
    case startup, appearance, visuals
    func requiresFullArchive(_ record: PatchRecord) -> Bool {
        switch self {
        case .startup: return false
        case .appearance: return record.appearanceArchive
        case .visuals: return record.visualArchive
        }
    }
}

struct PatchRecord: Codable, Equatable {
    let source: String
    let target: String
    let type: UInt32
    let size: UInt64
    let crc: UInt32
    let table: String
    let headerSize: UInt64
    let compressedHeaderSize: UInt64
    let headerCRC: UInt32
    init(source: String, target: String, type: UInt32, size: UInt64, crc: UInt32,
         table: String = "", headerSize: UInt64 = 0, compressedHeaderSize: UInt64 = 0, headerCRC: UInt32 = 0) {
        self.source = source; self.target = target; self.type = type; self.size = size; self.crc = crc
        self.table = table; self.headerSize = headerSize; self.compressedHeaderSize = compressedHeaderSize; self.headerCRC = headerCRC
    }
    var localPath: String {
        if loginDefinition { return "PatchClient/BankB/LoginMessages.xml" }
        var name = target.isEmpty ? source : target
        if name.hasPrefix("Windows/") { name = String(name.dropFirst(8)) }
        return name
    }
    var protected: Bool {
        let p = localPath.lowercased(), n = URL(fileURLWithPath: p).lastPathComponent
        return officialLauncher || ["wizard101.exe", "appstart.dat", "d3d9.dll", "dxvk.conf", "preferences.xml", "config.xml", "patchconfig.xml", "state.dat"].contains(n)
            || n.hasSuffix(".cur") || n.hasSuffix(".ani") || n.hasSuffix(".dxvk-cache")
            || p.contains("shader") || p.contains("pipeline-cache")
    }
    // Only these launcher definitions are needed by native authentication.
    // Missing settings/cursors may be bootstrapped, but existing user files
    // remain protected. Renderer DLLs always come from this app's own build.
    var loginDefinition: Bool {
        let p = source.lowercased().replacingOccurrences(of: "windows/", with: "")
        return p == "patchclient/loginmessages.xml" || p == "patchclient/bankb/loginmessages.xml"
    }
    var bootstrapOnly: Bool {
        let p = localPath.lowercased(), n = URL(fileURLWithPath: p).lastPathComponent
        return loginDefinition || (["config.xml", "preferences.xml", "patchconfig.xml"].contains(n) && p.hasPrefix("bin/"))
            || ((n.hasSuffix(".cur") || n.hasSuffix(".ani")) && !officialLauncher)
    }
    func mayInstall(at destination: URL) -> Bool {
        return !protected || (bootstrapOnly && !FileManager.default.fileExists(atPath: destination.path))
    }
    var officialLauncher: Bool {
        func launcherPath(_ path: String) -> Bool {
            let p = path.lowercased()
            return p.hasPrefix("patchclient/") || p.hasPrefix("windows/patchclient/")
        }
        return table.lowercased() == "patchclient" || launcherPath(source) || launcherPath(localPath)
    }
    var streamedArchive: Bool {
        [3, 5].contains(type) && localPath.lowercased().hasSuffix(".wad")
    }
    var appearanceArchive: Bool {
        guard gameDataArchive else { return false }
        let family = archiveFamily
        return ["equipment", "mob"].contains { prefix in
            family.hasPrefix(prefix) && family.dropFirst(prefix.count).allSatisfy { $0.isASCII && $0.isNumber }
        }
    }
    private var gameDataArchive: Bool {
        let p = localPath.lowercased()
        return [1, 3, 4, 5].contains(type) && p.hasSuffix(".wad") && !protected && !officialLauncher && p.hasPrefix("data/gamedata/")
            && p.split(separator: "/").count == 3
    }
    private var archiveFamily: String {
        String(URL(fileURLWithPath: localPath.lowercased()).deletingPathExtension().lastPathComponent.split(separator: "-").first ?? "")
    }
    var visualArchive: Bool {
        guard gameDataArchive else { return false }
        let family = archiveFamily
        return family != "music" && family != "sound" && !family.hasPrefix("sound_")
    }
    var downloadSize: UInt64 { type == 4 ? headerSize : size }
    var downloadSource: String { source + (type == 4 ? ".gz" : "") }
    var requiredAtStartup: Bool {
        // Installer-era crash-report shortcuts are listed but no longer served
        // by LatestBuild. The graphical client does not load these at startup.
        if ["bin/bugreporter.bat", "bin/bugreporter.ico", "bin/bugreporter.ini"].contains(localPath.lowercased()) { return false }
        // Missing worlds and dialogue stay on demand. Keep the existing shared
        // startup dependencies, including Root and _Shared-WorldData.
        if ["data/gamedata/root.wad", "data/gamedata/_shared-worlddata.wad"].contains(localPath.lowercased()) { return true }
        let name = URL(fileURLWithPath: source).lastPathComponent.lowercased()
        if streamedArchive && name.hasPrefix("sound_dialogue") { return false }
        return type != 3
    }
}

struct PatchManifest {
    let revision: String
    let prefix: URL
    let records: [PatchRecord]
    static func parseBinary(_ data: Data) throws -> [PatchRecord] {
        var stream = BinaryReader(data: data), output: [PatchRecord] = [], tables = Set<String>()
        while stream.remaining > 0 {
            let count = try stream.integer(UInt32.self)
            guard count <= 100000 else { throw LauncherError.message("Unsupported patch table size.") }
            var schema = try packet(&stream, kind: 1)
            var fields: [(String, UInt8)] = [], table = ""
            while schema.remaining > 0 {
                let name = try schema.string(), type = try schema.integer(UInt8.self)
                guard try schema.integer(UInt8.self) == 0x28 else { throw LauncherError.message("Unsupported patch schema flags.") }
                if name == "_TargetTable" {
                    guard type == 9 else { throw LauncherError.message("Invalid patch table name.") }
                    table = try schema.string(); try schema.end(); break
                }
                guard fields.count < 64 else { throw LauncherError.message("Unsupported patch schema size.") }
                fields.append((name, type))
            }
            guard !table.isEmpty, tables.insert(table).inserted else { throw LauncherError.message("Duplicate or missing patch table.") }
            for _ in 0..<count {
                var record = try packet(&stream, kind: 2), strings: [String: String] = [:], numbers: [String: UInt32] = [:]
                for (name, type) in fields {
                    switch type {
                    case 9: strings[name] = try record.string()
                    case 3: numbers[name] = try record.integer(UInt32.self)
                    default: throw LauncherError.message("Unsupported patch field type.")
                    }
                }
                try record.end()
                if table != "_TableList" && table != "About" {
                    guard let src = strings["SrcFileName"], let tar = strings["TarFileName"], let type = numbers["FileType"],
                          let size = numbers["Size"], let crc = numbers["CRC"], [1,3,4,5].contains(type) else {
                        throw LauncherError.message("Unsupported Windows file manifest.")
                    }
                    guard let headerSize = numbers["HeaderSize"], let compressedHeaderSize = numbers["CompressedHeaderSize"],
                          let headerCRC = numbers["HeaderCRC"] else { throw LauncherError.message("Missing patch header metadata.") }
                    let entry = PatchRecord(source: src, target: tar, type: type, size: UInt64(size), crc: crc,
                                            table: table, headerSize: UInt64(headerSize), compressedHeaderSize: UInt64(compressedHeaderSize), headerCRC: headerCRC)
                    guard !entry.streamedArchive || (entry.headerSize > 0 && entry.headerSize <= entry.size) else {
                        throw LauncherError.message("Invalid streamed archive header size.")
                    }
                    try validatePath(entry.source); try validatePath(entry.localPath)
                    output.append(entry)
                }
            }
        }
        guard !output.isEmpty, Set(output.map { $0.localPath.lowercased() }).count == output.count else {
            throw LauncherError.message("Empty or ambiguous Windows manifest.")
        }
        return output
    }
    private static func packet(_ stream: inout BinaryReader, kind: UInt8) throws -> BinaryReader {
        guard try stream.integer(UInt8.self) == 2, try stream.integer(UInt8.self) == kind else {
            throw LauncherError.message("Unsupported binary patch format.")
        }
        let length = Int(try stream.integer(UInt16.self))
        guard length >= 4 else { throw LauncherError.message("Invalid patch record length.") }
        return BinaryReader(data: try stream.bytes(length - 4))
    }
    static func validatePath(_ path: String) throws {
        let components = path.split(separator: "/", omittingEmptySubsequences: false)
        guard !path.isEmpty, !path.contains("\\"), !path.contains(":"), !path.contains("\0"),
              !components.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else {
            throw LauncherError.message("The manifest contains an unsafe file path.")
        }
    }
    static func safeURL(_ text: String) throws -> URL {
        guard let url = URL(string: text), ["http", "https"].contains(url.scheme),
              url.host == "versionak.us.wizard101.com", url.user == nil, url.password == nil,
              url.port == nil, url.query == nil, url.fragment == nil else {
            throw LauncherError.message("The patch server returned an unsupported download address.")
        }
        return url
    }
    static func fetch(token: CancellationToken, staging: URL) throws -> PatchManifest {
        let socket = try KIConnection(host: "patch.us.wizard101.com", port: 12500, token: token)
        defer { socket.close() }
        _ = try SessionOffer(frame: socket.receive())
        try socket.send(.message(service: 8, type: 1, fields: Data(repeating: 0, count: 28)))
        let response = try socket.receive()
        guard !response.control else { throw LauncherError.message("The patch server is unavailable.") }
        var r = BinaryReader(data: response.payload)
        guard try r.integer(UInt8.self) == 8, try r.integer(UInt8.self) == 1,
              Int(try r.integer(UInt16.self)) == response.payload.count else { throw LauncherError.message("Unsupported patch response.") }
        _ = try r.integer(UInt32.self); _ = try r.string(); _ = try r.integer(UInt32.self); _ = try r.integer(UInt32.self)
        let size = try r.integer(UInt32.self), crc = try r.integer(UInt32.self)
        let url = try safeURL(r.string()), prefix = try safeURL(r.string())
        _ = try r.string(); try r.end()
        guard size < 32 * 1024 * 1024, url.path.contains("/Windows/"), url.path.hasSuffix(".bin"),
              let version = url.pathComponents.first(where: { $0.hasPrefix("V_r") }),
              prefix.pathComponents.contains(version) else { throw LauncherError.message("The patch manifest is not for this Windows installation.") }
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let file = staging.appendingPathComponent("manifest-\(crc).bin")
        if !Integrity.matches(file, size: UInt64(size), crc: crc, token: token) {
            try HTTPTransfer.download(url: url, to: file, size: UInt64(size), token: token, progress: { _ in })
            guard Integrity.matches(file, size: UInt64(size), crc: crc, token: token) else {
                try? FileManager.default.removeItem(at: file)
                throw LauncherError.message("The downloaded manifest failed its integrity check. Try again.")
            }
        }
        return PatchManifest(revision: String(version.dropFirst(2)), prefix: prefix,
                             records: try parseBinary(Data(contentsOf: file)))
    }
}

struct Integrity {
    static func matchesHeader(_ url: URL, size: UInt64, headerSize: UInt64, headerCRC: UInt32, token: CancellationToken) -> Bool {
        guard headerSize > 0, headerSize <= size,
              let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              attributes[.type] as? FileAttributeType == .typeRegular,
              (attributes[.size] as? NSNumber)?.uint64Value == size else { return false }
        return (try? Self.crc(url, token: token, byteCount: headerSize)) == headerCRC
    }
    static func crc(_ url: URL, token: CancellationToken, byteCount: UInt64? = nil) throws -> UInt32 {
        let file = try FileHandle(forReadingFrom: url); defer { try? file.close() }
        var value: UInt32 = 0, read: UInt64 = 0
        while true {
            try token.check()
            if let byteCount, read == byteCount { return value }
            let count = Int(min(1024 * 1024, byteCount.map { $0 - read } ?? UInt64(1024 * 1024)))
            // FileHandle autoreleases its buffers. Drain each chunk here rather
            // than retaining entire archives until a launcher operation ends.
            let processed = try autoreleasepool { () throws -> Int in
                let data = try file.read(upToCount: count) ?? Data()
                if !data.isEmpty {
                    value = data.withUnsafeBytes { w101_crc(value, $0.bindMemory(to: UInt8.self).baseAddress, data.count) }
                }
                return data.count
            }
            if processed == 0 {
                guard byteCount == nil else { throw LauncherError.message("A streamed archive header is truncated.") }
                return value
            }
            read += UInt64(processed)
        }
    }
    static func matches(_ url: URL, size: UInt64, crc: UInt32, token: CancellationToken) -> Bool {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              attributes[.type] as? FileAttributeType == .typeRegular,
              (attributes[.size] as? NSNumber)?.uint64Value == size else { return false }
        return (try? Self.crc(url, token: token)) == crc
    }
}

// Streams response chunks to disk; a cancelled transfer retains its partial file.
final class HTTPTransfer: NSObject, URLSessionDataDelegate, URLSessionTaskDelegate {
    struct ServerFailure: LocalizedError {
        let status: Int
        var errorDescription: String? {
            if status == 403 || status == 404 {
                return "The official download server rejected this file request (HTTP \(status)). Your downloaded files are preserved."
            }
            return "The official download server returned HTTP \(status). Retry to resume."
        }
    }
    struct NetworkFailure: LocalizedError {
        let code: Int
        var resumable: Bool { [-1001, -1004, -1005, -1009].contains(code) }
        var errorDescription: String? { "A download was interrupted (network code \(code)). Retry to resume." }
    }
    private let url: URL, destination: URL, expected: UInt64, token: CancellationToken, progress: (UInt64) -> Void
    private let chunkSize: UInt64, deadline: TimeInterval
    private var written: UInt64 = 0, offset: UInt64 = 0
    private var rangeEnd: UInt64 = 0, responseEnd: UInt64 = 0
    private var file: FileHandle?
    private var error: Error?
    private let completed = DispatchSemaphore(value: 0)
    private var accepted = false
    var testConfiguration: URLSessionConfiguration?
    private var routeAddress: String?
    init(url: URL, destination: URL, size: UInt64, token: CancellationToken, chunkSize: UInt64,
         deadline: TimeInterval, progress: @escaping (UInt64) -> Void) {
        self.url = url; self.destination = destination; self.expected = size; self.token = token; self.progress = progress
        self.chunkSize = chunkSize; self.deadline = deadline
    }
    static func download(url: URL, to: URL, size: UInt64, token: CancellationToken, progress: @escaping (UInt64) -> Void,
                         testConfiguration: URLSessionConfiguration? = nil,
                         testRoutes: ((CancellationToken) throws -> [String])? = nil,
                         testChunkSize: UInt64? = nil) throws {
        let chunkSize = testChunkSize ?? 8 * 1024 * 1024
        guard size > 0, chunkSize > 0, chunkSize <= 8 * 1024 * 1024 else {
            throw LauncherError.message("Invalid download size.")
        }
        let deadline = ProcessInfo.processInfo.systemUptime + 3600
        // Explicit, bounded ranges avoid long CDN responses dropping partway
        // through a WAD. Each completed range preserves progress; every range
        // has bounded retries and all ranges share a one-hour deadline.
        while true {
            try token.check()
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw NetworkFailure(code: -1001) }
            if try downloadRange(url: url, to: to, size: size, token: token, progress: progress,
                                 testConfiguration: testConfiguration, testRoutes: testRoutes,
                                 chunkSize: chunkSize, deadline: deadline) { return }
        }
    }
    private static func downloadRange(url: URL, to: URL, size: UInt64, token: CancellationToken,
                                      progress: @escaping (UInt64) -> Void, testConfiguration: URLSessionConfiguration?,
                                      testRoutes: ((CancellationToken) throws -> [String])?,
                                      chunkSize: UInt64, deadline: TimeInterval) throws -> Bool {
        var lastFailure: NetworkFailure?
        for attempt in 0..<3 {
            try token.check()
            let transfer = HTTPTransfer(url: url, destination: to, size: size, token: token,
                                        chunkSize: chunkSize, deadline: deadline, progress: progress)
            transfer.testConfiguration = testConfiguration
            do { try transfer.run(); return transfer.written == size }
            catch let failure as NetworkFailure where [-1001, -1004, -1005, -1009].contains(failure.code) {
                lastFailure = failure
                // Resume only transient network failures. Invalid paths, ranges,
                // sizes and integrity errors remain visible without retry.
                if attempt < 2 {
                    for _ in 0..<(10 * (attempt + 1)) { try token.check(); Thread.sleep(forTimeInterval: 0.1) }
                }
            }
        }
        guard var lastFailure else { throw LauncherError.message("The download could not be completed.") }
        // Preserve proxy/security routing. A failing CDN edge can be replaced
        // only for this public official HTTP request, never system-wide.
        guard testRoutes != nil || (testConfiguration == nil && CDNRoute.available(url)) else { throw lastFailure }
        var attempted = Set<String>()
        for _ in 0..<2 {
            try token.check()
            if testRoutes == nil && !CDNRoute.available(url) { throw lastFailure }
            // Resolve immediately before each request. An earlier response's
            // short TTL may expire during a long accepted body transfer.
            let addresses: [String]
            if let testRoutes { addresses = try testRoutes(token) }
            else { addresses = try CDNRoute.addresses(token: token) }
            guard let address = addresses.prefix(2).first(where: { !attempted.contains($0) }) else { throw lastFailure }
            guard CDNRoute.publicIPv4(address) else { throw LauncherError.message("Invalid alternate download route.") }
            attempted.insert(address)
            if testRoutes == nil && !CDNRoute.available(url) { throw lastFailure }
            let transfer = HTTPTransfer(url: url, destination: to, size: size, token: token,
                                        chunkSize: chunkSize, deadline: deadline, progress: progress)
            transfer.testConfiguration = testConfiguration; transfer.routeAddress = address
            do { try transfer.run(); return transfer.written == size }
            catch let failure as NetworkFailure where [-1001, -1004, -1005, -1009].contains(failure.code) { lastFailure = failure }
        }
        throw lastFailure
    }
    private func run() throws {
        guard ProcessInfo.processInfo.systemUptime < deadline else { throw NetworkFailure(code: -1001) }
        let fm = FileManager.default
        if let attributes = try? fm.attributesOfItem(atPath: destination.path) {
            guard attributes[.type] as? FileAttributeType == .typeRegular else { throw LauncherError.message("Unsafe staged download path.") }
            offset = (attributes[.size] as? NSNumber)?.uint64Value ?? 0
        } else {
            guard fm.createFile(atPath: destination.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
                throw LauncherError.message("Could not create a staged download.")
            }
        }
        file = try FileHandle(forWritingTo: destination)
        defer { try? file?.close() }
        if offset >= expected { try file?.truncate(atOffset: 0); offset = 0 }
        rangeEnd = offset + min(chunkSize, expected - offset) - 1
        responseEnd = rangeEnd
        written = offset; try file?.seek(toOffset: offset)
        let config = testConfiguration?.copy() as? URLSessionConfiguration ?? URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = max(0.1, deadline - ProcessInfo.processInfo.systemUptime)
        config.httpMaximumConnectionsPerHost = 3; config.urlCache = nil; config.httpCookieStorage = nil
        if let routeAddress {
            config.urlCredentialStorage = nil
            config.connectionProxyDictionary = ["HTTPEnable": 1, "HTTPProxy": routeAddress, "HTTPPort": 80]
        }
        let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1
        let session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: url)
        request.setValue("Wizard101-Native/2", forHTTPHeaderField: "User-Agent")
        request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        request.setValue("bytes=\(offset)-\(rangeEnd)", forHTTPHeaderField: "Range")
        let task = session.dataTask(with: request); task.resume()
        while completed.wait(timeout: .now() + 0.1) == .timedOut {
            if token.isCancelled { task.cancel() }
            if ProcessInfo.processInfo.systemUptime >= deadline { task.cancel() }
        }
        try token.check()
        guard ProcessInfo.processInfo.systemUptime < deadline else { throw NetworkFailure(code: -1001) }
        if let error { throw error }
        guard accepted else { throw LauncherError.message("The download server returned no accepted response.") }
        guard written == responseEnd + 1 else { throw NetworkFailure(code: -1005) }
        try file?.synchronize()
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        do {
            guard let http = response as? HTTPURLResponse,
                  let responseURL = response.url, try PatchManifest.safeURL(responseURL.absoluteString) == responseURL else {
                throw LauncherError.message("The download server returned an unsupported response.")
            }
            guard [200,206].contains(http.statusCode) else { throw ServerFailure(status: http.statusCode) }
            if http.statusCode == 206 {
                let value = http.value(forHTTPHeaderField: "Content-Range") ?? ""
                let parts = value.replacingOccurrences(of: "bytes ", with: "").split(whereSeparator: { $0 == "-" || $0 == "/" })
                guard expected > 0, parts.count == 3, UInt64(parts[0]) == offset, UInt64(parts[2]) == expected,
                      UInt64(parts[1]) == rangeEnd else { throw LauncherError.message("Invalid resumed download response.") }
            } else {
                // A server may ignore Range and return the complete file.
                responseEnd = expected - 1
                if offset > 0 { try file?.truncate(atOffset: 0); try file?.seek(toOffset: 0); written = 0 }
            }
            accepted = true; progress(written); completionHandler(.allow)
        } catch { self.error = error; completionHandler(.cancel) }
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        do {
            try token.check()
            let limit = responseEnd + 1
            guard accepted, written <= limit, UInt64(data.count) <= limit - written else { throw LauncherError.message("A download exceeds its declared size.") }
            try file?.write(contentsOf: data); written += UInt64(data.count); progress(written)
        } catch { self.error = error; dataTask.cancel() }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if self.error == nil, let error {
            let native = error as NSError
            self.error = native.domain == NSURLErrorDomain ? NetworkFailure(code: native.code) : error
        }
        completed.signal()
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        if routeAddress != nil {
            error = LauncherError.message("The alternate download route redirected the resource."); completionHandler(nil); return
        }
        guard let url = request.url, (try? PatchManifest.safeURL(url.absoluteString)) != nil else {
            error = LauncherError.message("The patch server redirected to an unsupported host."); completionHandler(nil); return
        }
        completionHandler(request)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        if routeAddress != nil && challenge.protectionSpace.isProxy() {
            error = LauncherError.message("The alternate download route requested proxy authentication.")
            completionHandler(.cancelAuthenticationChallenge, nil)
        } else { completionHandler(.performDefaultHandling, nil) }
    }
}
