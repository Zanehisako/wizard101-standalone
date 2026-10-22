import Foundation
import Network
import CryptoKit

final class CancellationToken: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    var isCancelled: Bool { lock.lock(); defer { lock.unlock() }; return cancelled }
    func cancel() { lock.lock(); cancelled = true; lock.unlock() }
    func check() throws { if isCancelled { throw CancellationError() } }
}

struct BinaryReader {
    let data: Data
    var offset = 0
    var remaining: Int { data.count - offset }
    mutating func bytes(_ n: Int) throws -> Data {
        guard n >= 0, n <= remaining else { throw LauncherError.message("Unsupported or truncated server message.") }
        defer { offset += n }
        return data.subdata(in: offset..<offset+n)
    }
    mutating func integer<T: FixedWidthInteger>(_ type: T.Type) throws -> T {
        let b = try bytes(MemoryLayout<T>.size)
        return b.enumerated().reduce(T.zero) { $0 | (T(truncatingIfNeeded: $1.element) << ($1.offset * 8)) }
    }
    mutating func blob() throws -> Data { try bytes(Int(integer(UInt16.self))) }
    mutating func string() throws -> String {
        let b = try blob()
        guard let s = String(data: b, encoding: .utf8), !s.contains("\0") else {
            throw LauncherError.message("Unsupported server text encoding.")
        }
        return s
    }
    mutating func end() throws {
        guard remaining == 0 else { throw LauncherError.message("Unsupported server message version.") }
    }
}
extension Data {
    mutating func put<T: FixedWidthInteger>(_ n: T) {
        var value = n.littleEndian
        Swift.withUnsafeBytes(of: &value) { append(contentsOf: $0) }
    }
    mutating func putBlob(_ b: Data) throws {
        guard b.count <= Int(UInt16.max) else { throw LauncherError.message("Login field is too long.") }
        put(UInt16(b.count)); append(b)
    }
    mutating func putString(_ s: String) throws { try putBlob(Data(s.utf8)) }
    var kiCRC: UInt32 { withUnsafeBytes { w101_crc(0, $0.bindMemory(to: UInt8.self).baseAddress, count) } }
    var sha256Hex: String { SHA256.hash(data: self).map { String(format: "%02x", $0) }.joined() }
}

struct KIFrame {
    let control: Bool
    let opcode: UInt8
    let payload: Data
    func encoded() throws -> Data {
        guard payload.count + 5 < 65536 else { throw LauncherError.message("Server packet exceeds the supported size.") }
        var d = Data(); d.put(UInt16(0xf00d)); d.put(UInt16(payload.count + 5))
        d.append(control ? 1 : 0); d.append(opcode); d.put(UInt16(0)); d.append(payload); d.append(0)
        return d
    }
    static func decode(_ data: Data) throws -> KIFrame {
        var r = BinaryReader(data: data)
        guard try r.integer(UInt16.self) == 0xf00d else { throw LauncherError.message("Invalid server packet marker.") }
        let n = Int(try r.integer(UInt16.self))
        guard n == r.remaining, n >= 5 else { throw LauncherError.message("Invalid server packet length.") }
        let c = try r.integer(UInt8.self), op = try r.integer(UInt8.self)
        guard c <= 1, try r.integer(UInt16.self) == 0 else { throw LauncherError.message("Unsupported server packet header.") }
        let p = try r.bytes(r.remaining - 1)
        guard try r.integer(UInt8.self) == 0 else { throw LauncherError.message("Invalid server packet terminator.") }
        return KIFrame(control: c == 1, opcode: op, payload: p)
    }
    static func message(service: UInt8, type: UInt8, fields: Data) -> KIFrame {
        var d = Data([service, type]); d.put(UInt16(fields.count + 4)); d.append(fields)
        return KIFrame(control: false, opcode: 0, payload: d)
    }
}

enum AuthenticationTransportFailure: String, LocalizedError {
    case deadline, trafficLimit, integrity, invalidFrame, disconnected
    var errorDescription: String? {
        switch self {
        case .deadline: return "Sign-in timed out after 30 seconds. Try again when ready."
        case .trafficLimit: return "The account server exceeded the sign-in traffic limit. Try again when ready."
        case .integrity: return "The account-server stream failed its integrity check. Sign in again."
        case .invalidFrame: return "The account server returned an unsupported encrypted reply. Try again."
        case .disconnected: return "The server connection was interrupted. Try again."
        }
    }
}

protocol EncryptedTransport: AnyObject {
    var now: TimeInterval { get }
    var deadline: TimeInterval { get }
    func sendBytes(_ data: Data) throws
    // A poll timeout keeps exactly one pending read; it must not discard bytes.
    func receiveAvailable(maximum: Int, until: TimeInterval) throws -> Data?
}

// Used only from a worker queue. Network's callbacks have their own serial queue.
final class KIConnection: EncryptedTransport {
    private let connection: NWConnection
    private let token: CancellationToken
    let deadline: TimeInterval
    var now: TimeInterval { ProcessInfo.processInfo.systemUptime }
    private final class Read {
        let done = DispatchSemaphore(value: 0)
        var data: Data?
        var failed = false
    }
    private var pendingRead: Read?
    init(host: String, port: UInt16, token: CancellationToken) throws {
        self.token = token
        deadline = ProcessInfo.processInfo.systemUptime + 30
        connection = NWConnection(host: NWEndpoint.Host(host), port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        let done = DispatchSemaphore(value: 0)
        var ready = false
        connection.stateUpdateHandler = { state in
            if case .ready = state { ready = true; done.signal() }
            if case .failed = state { done.signal() }
        }
        connection.start(queue: DispatchQueue(label: "w101.network"))
        do { try wait(done); guard ready else { throw LauncherError.message("The account or patch server is unavailable. Try again.") } }
        catch { connection.cancel(); throw error }
        connection.stateUpdateHandler = nil
    }
    deinit { connection.cancel() }
    func close() { connection.cancel() }
    private func wait(_ semaphore: DispatchSemaphore) throws {
        while semaphore.wait(timeout: .now() + min(0.05, max(0, deadline - now))) == .timedOut {
            try token.check()
            guard now < deadline else { throw AuthenticationTransportFailure.deadline }
        }
        try token.check()
        guard now < deadline else { throw AuthenticationTransportFailure.deadline }
    }
    func send(_ frame: KIFrame) throws {
        try sendBytes(frame.encoded())
    }
    func sendBytes(_ data: Data) throws {
        try token.check()
        guard now < deadline else { throw AuthenticationTransportFailure.deadline }
        guard !data.isEmpty else { return }
        let semaphore = DispatchSemaphore(value: 0)
        var failed = false
        connection.send(content: data, completion: .contentProcessed { error in failed = error != nil; semaphore.signal() })
        try wait(semaphore)
        if failed { throw AuthenticationTransportFailure.disconnected }
    }
    func receiveAvailable(maximum: Int, until: TimeInterval) throws -> Data? {
        try token.check()
        guard now < deadline else { throw AuthenticationTransportFailure.deadline }
        let read: Read
        if let pendingRead { read = pendingRead }
        else {
            read = Read(); pendingRead = read
            connection.receive(minimumIncompleteLength: 1, maximumLength: min(maximum, 16384)) { data, _, complete, error in
                read.data = data; read.failed = error != nil || (complete && (data?.isEmpty ?? true)); read.done.signal()
            }
        }
        while read.done.wait(timeout: .now() + min(0.05, max(0, min(until, deadline) - now))) == .timedOut {
            try token.check()
            guard now < deadline else { throw AuthenticationTransportFailure.deadline }
            if now >= until { return nil }
        }
        pendingRead = nil
        try token.check()
        guard now < deadline else { throw AuthenticationTransportFailure.deadline }
        guard !read.failed, let data = read.data, !data.isEmpty else { throw AuthenticationTransportFailure.disconnected }
        return data
    }
    func receiveBytes(_ count: Int) throws -> Data {
        var result = Data()
        while result.count < count {
            try token.check()
            let requested = min(count - result.count, 16384)
            guard let part = try receiveAvailable(maximum: requested, until: deadline) else { throw AuthenticationTransportFailure.deadline }
            result.append(part)
        }
        return result
    }
    func receive() throws -> KIFrame {
        let header = try receiveBytes(4)
        var r = BinaryReader(data: header)
        guard try r.integer(UInt16.self) == 0xf00d else { throw LauncherError.message("Invalid server packet marker.") }
        let n = Int(try r.integer(UInt16.self))
        guard n >= 5 else { throw LauncherError.message("Invalid server packet length.") }
        return try KIFrame.decode(header + receiveBytes(n))
    }
}

struct SessionOffer {
    let id: UInt16
    let seconds: UInt32
    let milliseconds: UInt32
    let encryption: Data
    init(frame: KIFrame) throws {
        guard frame.control, frame.opcode == 0 else { throw LauncherError.message("Unsupported login handshake.") }
        var r = BinaryReader(data: frame.payload)
        id = try r.integer(UInt16.self)
        guard try r.integer(UInt32.self) == 0 else { throw LauncherError.message("Unsupported login handshake version.") }
        seconds = try r.integer(UInt32.self); milliseconds = try r.integer(UInt32.self)
        let n = try r.integer(UInt32.self)
        guard n <= 4096 else { throw LauncherError.message("Unsupported login encryption offer.") }
        encryption = try r.bytes(Int(n)); try r.end()
    }
    func accept() -> KIFrame {
        var d = Data(); d.put(UInt16(0)); d.put(UInt32(0)); d.put(seconds); d.put(milliseconds); d.put(id)
        d.put(UInt32(1)); d.append(0)
        return KIFrame(control: true, opcode: 5, payload: d)
    }
    func requireSupportedEncryption() throws {
        // Never transmit credentials through the legacy transport fallback.
        if encryption == Data([0]) {
            throw LauncherError.message("The account server offered unsigned legacy transport. Native sign-in requires a verified encrypted handshake. No credentials were sent.")
        }
        _ = try SignedEncryptionOffer(encryption)
        throw LauncherError.message("The account-server signature was verified, but this build cannot yet complete its encrypted reply. No credentials were sent. Native sign-in compatibility still needs to be completed.")
    }
    func credentialPayload(username: String, password: String) throws -> Data {
        let first = Data(SHA512.hash(data: Data(password.utf8))).base64EncodedString()
        let salt = "\(id)\(seconds)\(milliseconds)"
        let clientKey = Data(SHA512.hash(data: Data((first + salt).utf8))).base64EncodedString()
        return try crypt(Data("\(id) \(username) \(clientKey)".utf8))
    }
    func validationKey(_ passKey: String) -> String {
        Data(SHA512.hash(data: Data("\(passKey)\(id)\(seconds)\(milliseconds)".utf8))).base64EncodedString()
    }
    func crypt(_ data: Data) throws -> Data {
        var key = (0..<32).map { UInt8(0x17 + $0) }
        var iv = (0..<16).map { UInt8(0xb6 - $0) }
        key[4] = UInt8(truncatingIfNeeded: id); key[5] = 0; key[6] = UInt8(truncatingIfNeeded: id >> 8)
        key[8] = UInt8(truncatingIfNeeded: seconds); key[9] = UInt8(truncatingIfNeeded: seconds >> 16)
        key[12] = UInt8(truncatingIfNeeded: seconds >> 8); key[13] = UInt8(truncatingIfNeeded: seconds >> 24)
        key[14] = UInt8(truncatingIfNeeded: milliseconds); key[15] = UInt8(truncatingIfNeeded: milliseconds >> 8)
        var output = Data(count: data.count)
        key.withUnsafeBufferPointer { k in iv.withUnsafeBufferPointer { v in
            data.withUnsafeBytes { source in output.withUnsafeMutableBytes { dest in
                _ = w101_twofish_ofb(k.baseAddress, v.baseAddress, source.bindMemory(to: UInt8.self).baseAddress,
                                    data.count, dest.bindMemory(to: UInt8.self).baseAddress)
            }}
        }}
        _ = key.withUnsafeMutableBytes { $0.initializeMemory(as: UInt8.self, repeating: 0) }
        _ = iv.withUnsafeMutableBytes { $0.initializeMemory(as: UInt8.self, repeating: 0) }
        return output
    }
}
