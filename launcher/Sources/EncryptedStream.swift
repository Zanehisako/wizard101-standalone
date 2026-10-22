import Foundation
import Security
import CryptoKit

// The installed peer uses asymmetric fixed GCM chunks. Keep received plaintext
// private until its complete tag verifies, including frames crossing a boundary.
// This avoids the installed client's optimistic use of unverified plaintext.
final class GCMChunkCodec {
    private var key: Data
    private var iv: Data
    private var pending = Data()
    let chunkSize: Int
    init(key: Data, iv: Data, chunkSize: Int) throws {
        guard key.count == 16, iv.count == 16, [4096, 65536].contains(chunkSize) else {
            throw LauncherError.message("Unsupported encrypted stream parameters.")
        }
        self.key = key; self.iv = iv; self.chunkSize = chunkSize
    }
    deinit { key.wipe(); iv.wipe(); pending.wipe() }
    func encode(_ plaintext: Data) throws -> Data {
        guard pending.count + plaintext.count <= 196608 else { throw LauncherError.message("Encrypted stream buffer exceeded its bound.") }
        pending.append(plaintext)
        var output = Data()
        while pending.count >= chunkSize {
            var chunk = Data(pending.prefix(chunkSize))
            defer { chunk.wipe() }
            let sealed = try AES.GCM.seal(chunk, using: SymmetricKey(data: key), nonce: AES.GCM.Nonce(data: iv))
            output.append(sealed.ciphertext); output.append(sealed.tag)
            iv.wipe(); iv = try Data.secureRandom(count: 16); output.append(iv)
            pending.removeFirst(chunkSize)
        }
        return output
    }
    func decode(_ wire: Data) throws -> Data {
        guard wire.count == chunkSize + 32 else { throw LauncherError.message("Truncated encrypted stream chunk.") }
        let sealed = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: iv), ciphertext: Data(wire.prefix(chunkSize)), tag: wire.subdata(in: chunkSize..<chunkSize + 16))
        let clear: Data
        do { clear = try AES.GCM.open(sealed, using: SymmetricKey(data: key)) }
        catch { throw AuthenticationTransportFailure.integrity }
        iv.wipe(); iv = Data(wire.suffix(16))
        return clear
    }
}

extension Data {
    mutating func wipe() { withUnsafeMutableBytes { raw in if let p = raw.baseAddress { w101_wipe(p, raw.count) } }; removeAll(keepingCapacity: false) }
    static func secureRandom(count: Int) throws -> Data {
        var bytes = Data(count: count)
        let status = bytes.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, count, $0.baseAddress!) }
        guard status == errSecSuccess else { bytes.wipe(); throw LauncherError.message("Secure randomness is unavailable. Try again.") }
        return bytes
    }
}

struct RSAHandshakeReply {
    // Ciphertext is public on the wire. Key material stays in process memory.
    static func encrypt(nonce: Data, seed: UInt32, time: UInt32, key: Data, iv: Data, publicKey: SecKey) throws -> Data {
        guard nonce.count == 8, key.count == 16, iv.count == 16,
              SecKeyIsAlgorithmSupported(publicKey, .encrypt, .rsaEncryptionOAEPSHA1) else {
            throw LauncherError.message("Unsupported signed handshake reply.")
        }
        var plain = Data([UInt8(nonce.count)]); plain.append(nonce); plain.put(seed); plain.put(time); plain.append(key); plain.append(iv)
        defer { plain.wipe() }
        guard let encrypted = SecKeyCreateEncryptedData(publicKey, .rsaEncryptionOAEPSHA1, plain as CFData, nil),
              (encrypted as Data).count == 256 else { throw LauncherError.message("The encrypted handshake reply could not be created. Try again.") }
        return Data([1]) + (encrypted as Data)
    }
}

final class NativeEncryptedSession {
    private let connection: KIConnection
    private let token: CancellationToken
    private let tx: GCMChunkCodec
    private let rx: GCMChunkCodec
    let offer: SessionOffer
    private let replies: EncryptedReplyStream
    var verifiedChunks: Int { replies.stats.verifiedChunks }
    var stats: AuthenticationExchangeStats { replies.stats }
    init(connection: KIConnection, game: URL, token: CancellationToken) throws {
        self.connection = connection; self.token = token
        offer = try SessionOffer(frame: connection.receive())
        let signed = try SignedEncryptionOffer(offer.encryption)
        let decoded = try CodeIntegrityNonce(game: game, token: token).decode(signed.nonce)
        var key = try Data.secureRandom(count: 16), iv = try Data.secureRandom(count: 16)
        defer { key.wipe(); iv.wipe() }
        let reply = try RSAHandshakeReply.encrypt(nonce: decoded, seed: signed.seed, time: UInt32(Date().timeIntervalSince1970), key: key, iv: iv, publicKey: signed.publicKey)
        tx = try GCMChunkCodec(key: key, iv: iv, chunkSize: 4096)
        rx = try GCMChunkCodec(key: key, iv: iv, chunkSize: 65536)
        replies = EncryptedReplyStream(connection: connection, token: token, tx: tx, rx: rx, sessionID: offer.id)
        var fields = Data(); fields.put(UInt16(0)); fields.put(UInt32(0)); fields.put(offer.seconds); fields.put(offer.milliseconds); fields.put(offer.id)
        fields.put(UInt32(reply.count)); fields.append(reply)
        try connection.send(KIFrame(control: true, opcode: 5, payload: fields))
    }
    func send(_ frame: KIFrame) throws { try replies.send(frame) }
    func verifyTransport() throws {
        let frame = try replies.receive()
        guard verifiedChunks > 0, frame.control, frame.opcode == 4, frame.payload.count == 6 else {
            throw AuthenticationTransportFailure.invalidFrame
        }
    }
    func receiveMessage() throws -> KIFrame { try replies.receiveMessage() }
}

struct AuthenticationExchangeStats: Codable {
    var sentBytes = 0
    var receivedBytes = 0
    var verifiedChunks = 0
    var controlFrames = 0
    var heartbeatBatches = 0
}

// Injectable transport replays the real encrypted reader, including split tags,
// frame boundaries and control-only peers, without credentials or a live server.
final class EncryptedReplyStream {
    static let maximumSentBytes = 4 * 1024 * 1024
    static let maximumReceivedBytes = 8 * 1024 * 1024
    private let connection: EncryptedTransport
    private let token: CancellationToken
    private let tx: GCMChunkCodec, rx: GCMChunkCodec
    private let sessionID: UInt16
    private var authenticatedBytes = Data()
    private var wire = Data()
    private var heartbeat: UInt16 = 0
    private var nextHeartbeat: TimeInterval = 0
    private(set) var stats = AuthenticationExchangeStats()
    init(connection: EncryptedTransport, token: CancellationToken, tx: GCMChunkCodec, rx: GCMChunkCodec, sessionID: UInt16) {
        self.connection = connection; self.token = token; self.tx = tx; self.rx = rx; self.sessionID = sessionID
    }
    deinit { authenticatedBytes.wipe(); wire.wipe() }
    private func check() throws {
        try token.check()
        guard connection.now < connection.deadline else { throw AuthenticationTransportFailure.deadline }
    }
    private func sendPlain(_ plain: Data) throws {
        try check()
        var encoded = try tx.encode(plain); defer { encoded.wipe() }
        guard stats.sentBytes + encoded.count <= Self.maximumSentBytes else { throw AuthenticationTransportFailure.trafficLimit }
        try connection.sendBytes(encoded); stats.sentBytes += encoded.count
    }
    func send(_ frame: KIFrame) throws {
        var plain = try frame.encoded(); defer { plain.wipe() }
        try sendPlain(plain)
    }
    private func sendHeartbeats() throws {
        var controls = Data(); defer { controls.wipe() }
        // 256 small controls per batch, with reads between batches. The first
        // complete 64 KiB server tag needs about 19 batches, not one large burst.
        for _ in 0..<256 {
            try check()
            var payload = Data(); payload.put(sessionID); payload.put(UInt16(0)); payload.put(heartbeat); heartbeat &+= 1
            controls.append(try KIFrame(control: true, opcode: 3, payload: payload).encoded())
        }
        try sendPlain(controls); stats.heartbeatBatches += 1
        nextHeartbeat = connection.now + 0.02
    }
    private func receiveChunk() throws {
        let size = rx.chunkSize + 32
        while wire.count < size {
            try check()
            if connection.now >= nextHeartbeat { try sendHeartbeats() }
            if let part = try connection.receiveAvailable(maximum: min(16384, size - wire.count), until: min(nextHeartbeat, connection.deadline)) {
                guard part.count <= size - wire.count, stats.receivedBytes + part.count <= Self.maximumReceivedBytes else {
                    throw AuthenticationTransportFailure.trafficLimit
                }
                wire.append(part); stats.receivedBytes += part.count
            }
        }
        var clear = try rx.decode(wire); defer { clear.wipe() }
        authenticatedBytes.append(clear); wire.wipe(); stats.verifiedChunks += 1
    }
    func receive() throws -> KIFrame {
        while true {
            try check()
            if authenticatedBytes.count >= 4 {
                var reader = BinaryReader(data: Data(authenticatedBytes.prefix(4)))
                guard try reader.integer(UInt16.self) == 0xf00d else { throw AuthenticationTransportFailure.invalidFrame }
                let size = Int(try reader.integer(UInt16.self)) + 4
                guard size >= 9 else { throw AuthenticationTransportFailure.invalidFrame }
                if authenticatedBytes.count >= size {
                    let frame: KIFrame
                    do { frame = try KIFrame.decode(Data(authenticatedBytes.prefix(size))) }
                    catch { throw AuthenticationTransportFailure.invalidFrame }
                    authenticatedBytes.removeFirst(size)
                    return frame
                }
            }
            try receiveChunk()
        }
    }
    func receiveMessage() throws -> KIFrame {
        while true {
            let frame = try receive()
            if !frame.control { return frame }
            guard frame.opcode == 4, frame.payload.count == 6 else { throw AuthenticationTransportFailure.invalidFrame }
            stats.controlFrames += 1
        }
    }
}
