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
        catch { throw LauncherError.message("The account-server stream failed its integrity check. Sign in again.") }
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
    private var authenticatedBytes = Data()
    private var heartbeat: UInt16 = 0
    private var chunkCount = 0
    private(set) var verifiedChunks = 0
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
        var fields = Data(); fields.put(UInt16(0)); fields.put(UInt32(0)); fields.put(offer.seconds); fields.put(offer.milliseconds); fields.put(offer.id)
        fields.put(UInt32(reply.count)); fields.append(reply)
        try connection.send(KIFrame(control: true, opcode: 5, payload: fields))
    }
    deinit { authenticatedBytes.wipe() }
    func send(_ frame: KIFrame) throws {
        try token.check()
        var plain = try frame.encoded(); defer { plain.wipe() }
        try connection.sendBytes(tx.encode(plain))
    }
    private func receiveChunk() throws {
        try token.check()
        // A short authentication reply otherwise waits indefinitely for the
        // peer's fixed 64 KiB tag. Bounded control replies complete that chunk.
        // This runs only during sign-in, never in the idle UI or gameplay.
        guard chunkCount < 4 else { throw LauncherError.message("Sign-in exceeded the supported authenticated exchange. Try again.") }
        chunkCount += 1
        var controls = Data()
        // At least 17 complete outgoing chunks are needed: 16 chunks end one
        // byte short of the peer's first complete heartbeat response chunk.
        for _ in 0..<4864 {
            try token.check()
            var payload = Data(); payload.put(offer.id); payload.put(UInt16(0)); payload.put(heartbeat); heartbeat &+= 1
            controls.append(try KIFrame(control: true, opcode: 3, payload: payload).encoded())
        }
        defer { controls.wipe() }
        try connection.sendBytes(tx.encode(controls))
        let clear = try rx.decode(connection.receiveBytes(65568))
        authenticatedBytes.append(clear); verifiedChunks += 1
    }
    func receive() throws -> KIFrame {
        while true {
            try token.check()
            if authenticatedBytes.count >= 4 {
                var reader = BinaryReader(data: Data(authenticatedBytes.prefix(4)))
                guard try reader.integer(UInt16.self) == 0xf00d else { throw LauncherError.message("Invalid authenticated server frame.") }
                let size = Int(try reader.integer(UInt16.self)) + 4
                guard size >= 9 else { throw LauncherError.message("Invalid authenticated server packet size.") }
                if authenticatedBytes.count >= size {
                    let frame = try KIFrame.decode(Data(authenticatedBytes.prefix(size)))
                    authenticatedBytes.removeFirst(size)
                    return frame
                }
            }
            try receiveChunk()
        }
    }
    func verifyTransport() throws {
        let frame = try receive()
        guard verifiedChunks > 0, frame.control, frame.opcode == 4, frame.payload.count == 6 else {
            throw LauncherError.message("The encrypted handshake was not accepted. No credentials were sent.")
        }
    }
    func receiveMessage() throws -> KIFrame {
        for _ in 0..<20000 {
            let frame = try receive()
            if !frame.control { return frame }
            guard frame.opcode == 4 else { throw LauncherError.message("The account server interrupted sign-in. Try again.") }
        }
        throw LauncherError.message("The account server did not return an authentication response. Try again.")
    }
}
