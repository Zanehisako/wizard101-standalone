import Foundation
import Security

// Public RSA trust anchors recovered from the installed graphical client, not
// from the network. Client SHA-256: 544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e.
// Its public bank is initialized at RVA 0x25917b2 from RVA 0x32f3950.
// Keep the complete signed offer intact: the signature authenticates the flag,
// key index, encoding mask, nonce and seed. No private keys are bundled.
struct SignedEncryptionOffer {
    let keyIndex: UInt8
    let nonce: Data
    let seed: UInt32
    let publicKey: SecKey
    private static let keys = [
        "MIIBCAKCAQEA6DWoO/Ij7njXklGAVGIed7LizUt7s1YrGqHbz92899jfjmHU5EFuT4bNU5C81f2jMZKsS4VIP0dSAACDOOaHnh6QZPzC1/gm8XsLqDR+wCSdVttOgleUILDcMP+EAbRdCqr2OZ3Hb7Zi9VVKa1L4+UQxXyp/O2j77a9L1f9mt25Hd8oyfm5vM+YTYpnfWFh+wA0mTSvv7C6SvYx1d4O/m5KNtax7z3emNoNRy/GoyLsnA9ip8Y2q4nb+mB/f7HRWjyFxsRHlfVue9CHZIVm6Pqc2yBJa9UChzPn58X+Fux2q7N2/gIxDALA7kOaMhxDQz/a0IGr4RlM4ZHVW4h7UWQIBEQ==",
        "MIIBCAKCAQEAn8DwDyHdF640nPZh1KtoIY209es0Xn8S2GfkUmmEXgitz5ljRybkP9pO9wNDgUzCp4S4wJRBTkcwwy8YrgEu6VfkrkJuTiYD95mePYGMdmpmsZtkXC0XyvQ+fxZr7BKbbDskDF73LA8I6+c3jR9E7tGh14WPXlY2JGs5mIdJEFbKBMo5PCDNE8Fp0JdrnvV9tyqKRXioFMueW1bVW+WbHQIFv12LBNO8omuh0l91v4xDdyWZW2IVsrlJO05YIBeQ7QLV5ZQ5eYjbZIkhISd5e9U7K9ytuxkqUmBVlbzVopOf8/ahib0XAMN3P2xS4T/u8LMp5ZVt7W4FNB73d+AUIQIBEQ==",
        "MIIBCAKCAQEAxP7NAH1NQarARFA87fV8lyE7Vw+S2xgs5E6J+uP0XiUQHMynF4pWYBr8UCn7Pbuc9FzAPtSe6CpmjmpPg5IJgrnyQm0UkewRHeqrPthbS5eP67mZLCp560vzc6xAO3RNKj++bjTz1YzjjTiAc1OTbMWbQzyaz9WmQDfSmwOY9HKCyefmS5vqHvBRXbmP9gFAoKmzVq/p0j3fMikl6ROzWL/GuOsnBWOwaiZG08rLUA7q4V82IVNBp9SdRYPhNNEAhy17qCbQ56VWSmvp1ECyyUE8E7VFtQL9A2naQ7ctPGfznzR8mr6+evVR+d54CBCkeCGaJjCo7m3hFX/ZQqU+3QIBEQ==",
        "MIIBCAKCAQEAkmk1NKJ9Qw2qc7jS9mKPrAfia/l4ST/2A5wVRejnzNy5DFR/mMFLlWQfejy0xzL5h1GSbRebI7Y+gtRRCrwngeUabDOcPmAlCR9fhXCRMK1r4r0uW8ywytZ3V8gu3k5TpP/7Vv/DnwINALWeHDRjJ17JbMgXtL02aisqRw70vRoD+RCyeKzEawqCCEeiZmUnkaxVQVmKglUfYLJlOfB2T2N6VFAZX/aCFASDkdKi1c3/PjjXHFidwH4/UXmqNDXWr2+Jpcrr9Fcq2nPyVAQMZruJpSbsTkut4NRW1CNWXi3UlaltU3ZvhqiesAFncyCxgd/M+EJfTmOBCJMp7hwGWQIBEQ==",
        "MIIBCAKCAQEA0ORU7Yak2rpPmrAws/PD23hnggwWAoMqsuMQ0/a6xalLrX9v8jVO3px6dVeboDxsao3/Mq2vcMrgg2mPoe3L3zXFbw3Fa49qFitKQS3tT7LKO6hx92vj2YO87xMTX44YvM0CtFivFLu6+Nd6UCHRc8noLNc3vknb6BzC6X6beO3IUwgAVklPoYalqwsVbxH1rW3KA3U1DMZ0BX1q8Gew8Vfh0riuf0SefZAPS4M38V5vQfgZBYdlWHFj08hhn6U6s8uQoRYzyYukeZMuox81ppoB5JiE8X/UI5/kpmcKjK5FvjvvjhQwLFXF+4N8VYTFMggcWdPDTDp0LX2o8UcGvQIBEQ=="
    ]

    init(_ data: Data) throws {
        var reader = BinaryReader(data: data)
        let flag = try reader.integer(UInt8.self)
        guard flag == 1 || flag == 2 else {
            throw LauncherError.message("Unsigned or unsupported account-server encryption. No credentials were sent.")
        }
        keyIndex = try reader.integer(UInt8.self)
        _ = try reader.integer(UInt8.self) // Encoding mask is covered by the signature.
        let count = Int(try reader.integer(UInt8.self))
        guard Int(keyIndex) < Self.keys.count, count == 17, reader.remaining == count + 4 + 256,
              let der = Data(base64Encoded: Self.keys[Int(keyIndex)]) else {
            throw LauncherError.message("The account server uses an unsupported encryption key or handshake version. No credentials were sent.")
        }
        nonce = try reader.bytes(count)
        seed = try reader.integer(UInt32.self)
        let signature = try reader.bytes(256)
        try reader.end()
        let attributes: [CFString: Any] = [kSecAttrKeyType: kSecAttrKeyTypeRSA,
                                          kSecAttrKeyClass: kSecAttrKeyClassPublic,
                                          kSecAttrKeySizeInBits: 2048]
        guard let key = SecKeyCreateWithData(der as CFData, attributes as CFDictionary, nil),
              SecKeyIsAlgorithmSupported(key, .verify, .rsaSignatureMessagePKCS1v15SHA1),
              SecKeyVerifySignature(key, .rsaSignatureMessagePKCS1v15SHA1,
                                    Data(data.dropLast(256)) as CFData, signature as CFData, nil) else {
            throw LauncherError.message("The account-server signature could not be verified. No credentials were sent. Try again.")
        }
        publicKey = key
    }
}
