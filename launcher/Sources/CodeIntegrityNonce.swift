import Foundation
import CryptoKit

// Research-stage codec. Its traversal is checked against the installed machine
// code offline; server acceptance is still unverified. Never enables sign-in.
// Only revision-specific locators are bundled; challenged bytes are read from
// the user's installed executable, without executing or modifying it.
struct CodeIntegrityNonce {
    static let supportedRevision = "544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e"
    private let image: PEImage
    init(game: URL, token: CancellationToken) throws {
        try token.check()
        let attrs = try FileManager.default.attributesOfItem(atPath: game.path)
        guard attrs[.type] as? FileAttributeType == .typeRegular,
              (attrs[.size] as? NSNumber)?.uint64Value == 56_433_288 else {
            throw LauncherError.message("The installed game revision is unsupported for encrypted sign-in. No credentials were sent.")
        }
        let bytes = try Data(contentsOf: game)
        try token.check()
        guard bytes.sha256Hex == Self.supportedRevision else {
            throw LauncherError.message("The installed game revision changed. Encrypted sign-in needs a compatibility update. No credentials were sent.")
        }
        image = try PEImage(bytes)
    }

    func decode(_ nonce: Data) throws -> Data {
        var r = BinaryReader(data: nonce)
        guard nonce.count == 17 else { throw unsupported() }
        let start = Int(try r.integer(UInt16.self)), count = Int(try r.integer(UInt16.self))
        guard start + count <= 0x6aa, try r.integer(UInt8.self) == 0xf1 else { throw unsupported() }
        let flags = try r.integer(UInt32.self), argument = try r.integer(UInt32.self), selector = try r.integer(UInt32.self)
        try r.end()
        var output = Data()
        output.put(Self.fnv(try image.bytes(rva: 0x32f3950 + start, count: count)))
        output.put(try proof(flags: flags, argument: argument, selector: selector))
        return output
    }

    func proof(flags: UInt32, argument: UInt32, selector: UInt32) throws -> UInt32 {
        // This is the explicit no-code-check variant in the installed routine.
        // It is not used to replace or avoid a challenge requiring code checks.
        if flags & 0x20 != 0 { return 0 }
        var groups = [[UInt8]](repeating: [], count: 3)
        var period = 0
        for (source, destination) in [(18, 4), (14, 3), (7, 2), (5, 1), (3, 0)] {
            period |= Int((selector >> source) & 1) << destination
        }
        func append(_ bytes: Data, to group: Int) {
            for byte in bytes {
                let count = groups[group].count
                if period != 0 && count != 0 && count % period == 0 { groups[group].append(groups[group][count - 1]) }
                let shift = (groups[group].count & 3) * 8
                groups[group].append(byte ^ UInt8(truncatingIfNeeded: selector >> shift))
            }
        }
        var module = Data(); module.put(Self.fnv(Data("wizardgraphicalclient.exe".utf8)))
        func address(_ rva: Int) {
            append(module, to: 0)
            var offset = Data(); offset.put(UInt64(rva)); append(offset, to: 1)
        }
        for (rva, count) in Self.ranges {
            address(rva); append(try image.bytes(rva: rva, count: count), to: 2)
        }
        for (rva, count) in Self.tables {
            address(rva)
            var pointers = BinaryReader(data: try image.bytes(rva: rva, count: count * 8))
            for _ in 0..<count {
                let target = try pointers.integer(UInt64.self)
                guard target >= image.base, target - image.base < UInt64(image.imageSize) else { throw unsupported() }
                address(Int(target - image.base))
            }
        }
        var guardMarker = Data(); guardMarker.put(UInt32(0xcccccccc)); append(guardMarker, to: 2)
        var bytes: [UInt8] = []
        if flags & 0x200 != 0 { bytes += groups[1] }
        if flags & 0x1000 != 0 { bytes += groups[0] }
        bytes += groups[2]
        if flags & 0x20000 != 0 {
            for index in bytes.indices { bytes[index] ^= UInt8(truncatingIfNeeded: flags >> ((index & 3) * 8)) }
        }
        let stride = Int((argument >> 2) & 15) + 1, rounds = Int((argument >> 6) & 3) + 1
        var state = argument >> 8
        for _ in 0..<rounds {
            for lane in 0..<stride {
                var index = lane
                while index < bytes.count {
                    let byte = UInt32(bytes[index])
                    switch argument & 3 {
                    case 0: state = (state ^ byte) &* 0x1000193
                    case 1: state = (state &* 0x1000193) ^ byte
                    case 2: state = (state &+ byte) &* 0x401; state ^= state >> 6
                    default:
                        state = (state << 4) &+ byte
                        let high = state & 0xf0000000
                        if high != 0 { state ^= high >> 24 }
                        state &= ~high
                    }
                    index += stride
                }
            }
        }
        return state
    }

    private static func fnv(_ data: Data) -> UInt32 {
        data.reduce(UInt32(0x811c9dc5)) { ($0 ^ UInt32($1)) &* 0x1000193 }
    }
    private func unsupported() -> LauncherError {
        .message("Unsupported encrypted sign-in challenge. No credentials were sent.")
    }

    private static let ranges: [(Int, Int)] = [
        (0x14277a0, 256),
        (0xc2f668, 64),
        (0x1427ae0, 256),
        (0x1428a50, 256),
        (0xc2f678, 64),
        (0x14282e0, 256),
        (0x1426c30, 256),
        (0x1426ab0, 256),
        (0x14287a0, 256),
        (0x1425fd0, 256),
        (0x14260d0, 256),
        (0x1426160, 256),
        (0x1427cb0, 256),
        (0x1427d50, 256),
        (0x142d030, 256),
        (0x142d610, 256),
        (0x142e790, 256),
        (0x142e890, 256),
        (0x141c990, 256),
        (0x141e1b0, 256),
        (0x141e1d0, 256),
        (0x141e1f0, 256),
        (0x141e350, 256),
        (0x141e460, 256),
        (0x141d170, 256),
        (0x141d280, 256),
        (0xc2f678, 64),
        (0x2552a60, 256),
        (0xc2f678, 64),
        (0x25527a0, 256),
        (0xc2f688, 64),
        (0x25571f0, 256),
        (0xc2f690, 64),
        (0x2522b80, 256),
        (0x142bda0, 256),
        (0x142a4dc, 64),
        (0x2557540, 256),
        (0xc2f678, 64),
        (0x142b4c0, 256),
        (0xc2f680, 64),
        (0x142c220, 256),
        (0xc2f668, 64),
        (0x2557820, 256),
        (0xc2f678, 64),
        (0x25574e0, 256),
        (0x2523220, 256),
        (0xc2f6a0, 64),
        (0x2557420, 256),
        (0xc2f6a8, 64),
        (0x25225d0, 256),
        (0xc2f688, 64),
        (0x25571f0, 256),
        (0xc2f690, 64),
        (0x2522b80, 256),
        (0x142bda0, 256),
        (0x142a4dc, 64),
        (0x2557540, 256),
        (0xc2f678, 64),
        (0x142b4c0, 256),
        (0xc2f680, 64),
        (0x142c220, 256),
        (0xc2f668, 64),
        (0x2557820, 256),
        (0xc2f678, 64),
        (0x25574e0, 256),
        (0x2523220, 256),
        (0xc2f6a0, 64),
        (0x2557420, 256),
        (0xc2f6a8, 64),
        (0x25225d0, 256),
        (0xc2f688, 64),
        (0x14245e0, 256),
        (0xe0eb5c, 256),
        (0xe0eb68, 256),
        (0xc2f688, 64),
        (0x142b930, 256),
        (0xc2f6a0, 64),
        (0x1416c90, 256),
        (0xc2f678, 64),
        (0x142bf80, 256),
        (0xc2f688, 64),
        (0x142b8a0, 256),
        (0xc2f6a0, 64),
        (0x1416c90, 256),
        (0xc2f678, 64),
        (0x142bdd0, 256),
        (0x17c1a10, 256),
        (0x17c1630, 256),
        (0x17c17d0, 256),
        (0x17c1800, 256),
        (0x17c1a70, 256),
        (0x17c1c30, 256),
        (0x17c1da0, 256),
        (0x17c22b0, 256),
        (0x17c1f00, 256),
        (0x17c1ee0, 256),
        (0x17c24a0, 256),
        (0x17c2600, 256),
        (0x17c23f0, 256),
        (0x17c2470, 256),
        (0x17c1ff0, 256),
        (0x17c2010, 256),
        (0x17c1fb0, 256),
        (0x17c2050, 256),
        (0x17c2080, 256),
        (0x17c2570, 256),
        (0x17c1ff0, 256),
        (0x17c23b0, 256),
        (0x17c2430, 256),
        (0x17c2520, 256),
        (0x17c2020, 256),
        (0x16dd770, 256)
    ]
    private static let tables: [(Int, Int)] = [
        (0x2c29530, 5),
        (0x2c29530, 7),
        (0x2e40de8, 7),
        (0x2e40d20, 7),
        (0x2c29d88, 9),
        (0x2c29d88, 10),
        (0x2c29cf0, 16),
        (0x2c29cf0, 7),
        (0x2c29cf0, 8),
        (0x2c29cf0, 5),
        (0x2c29be8, 7),
        (0x2c29be8, 12),
        (0x2c29be8, 13),
        (0x2c29e08, 9),
        (0x2c29e08, 10),
        (0x2c29cf0, 16),
        (0x2c29cf0, 7),
        (0x2c29cf0, 8),
        (0x2c29cf0, 5),
        (0x2c29be8, 7),
        (0x2c29be8, 12),
        (0x2c29be8, 13),
        (0x2e41ab8, 9),
        (0x2e41760, 9),
        (0x2e41760, 12),
        (0x2e41760, 7),
        (0x2e415d0, 9),
        (0x2e415d0, 12),
        (0x2e415d0, 7)
    ]
}

private struct PEImage {
    let data: Data
    let base: UInt64
    let imageSize: Int
    private let sections: [(rva: Int, offset: Int, size: Int)]
    init(_ data: Data) throws {
        func read<T: FixedWidthInteger>(_ offset: Int, _ type: T.Type) throws -> T {
            guard offset >= 0, offset <= data.count - MemoryLayout<T>.size else { throw LauncherError.message("Invalid installed executable.") }
            var r = BinaryReader(data: data.subdata(in: offset..<offset + MemoryLayout<T>.size))
            return try r.integer(type)
        }
        guard try read(0, UInt16.self) == 0x5a4d else { throw LauncherError.message("Invalid installed executable.") }
        let pe = Int(try read(0x3c, UInt32.self)), optional = pe + 24
        guard try read(pe, UInt32.self) == 0x4550, try read(pe + 4, UInt16.self) == 0x8664,
              try read(optional, UInt16.self) == 0x20b else { throw LauncherError.message("Unsupported installed executable.") }
        let count = Int(try read(pe + 6, UInt16.self)), table = optional + Int(try read(pe + 20, UInt16.self))
        guard count > 0, count <= 32 else { throw LauncherError.message("Unsupported installed executable sections.") }
        base = try read(optional + 24, UInt64.self); imageSize = Int(try read(optional + 56, UInt32.self))
        var list: [(Int, Int, Int)] = []
        for k in 0..<count {
            let at = table + k * 40
            let rva = Int(try read(at + 12, UInt32.self)), size = Int(try read(at + 16, UInt32.self)), offset = Int(try read(at + 20, UInt32.self))
            guard offset <= data.count, size <= data.count - offset, rva <= imageSize, size <= imageSize - rva else {
                throw LauncherError.message("Invalid installed executable section bounds.")
            }
            list.append((rva, offset, size))
        }
        sections = list; self.data = data
    }
    func bytes(rva: Int, count: Int) throws -> Data {
        guard rva >= 0, count >= 0, let section = sections.first(where: { rva >= $0.rva && rva - $0.rva <= $0.size && count <= $0.size - (rva - $0.rva) }) else {
            throw LauncherError.message("Unsupported installed executable address.")
        }
        let offset = section.offset + rva - section.rva
        return data.subdata(in: offset..<offset + count)
    }
}
