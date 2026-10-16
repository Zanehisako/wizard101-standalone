import Foundation

enum LoginRequest {
    static func authentication(credential: Data, clientID: String, provider: AccountProvider, steam: SteamAuthorization?) throws -> Data {
        guard (provider == .steam) == (steam != nil) else {
            throw LauncherError.message("\(provider.title) sign-in needs the matching account provider. Retry Play.")
        }
        var fields = Data()
        try fields.putBlob(credential)
        // Version, Revision, DataRevision and CRC use the official defaults.
        for _ in 0..<4 { try fields.putString("") }
        fields.put(UInt64(0)); try fields.putString("en-US"); try fields.putString(clientID)
        fields.put(UInt32(provider == .steam ? 1 : 0)); fields.append(0)
        try fields.putString("") // PlatformChatID is not a Steam identity.
        try fields.putString(steam.map { String($0.userID) } ?? "0")
        // The official client copies the Web API ticket bytes into the DML STR.
        // Do not UTF-8 decode, hex/base64 encode, or truncate at embedded NULs.
        try fields.putBlob(steam?.ticket ?? Data())
        return fields
    }

    static func validation(session: GameSession, provider: AccountProvider, key: String, clientID: String) throws -> Data {
        guard session.provider == provider else {
            throw LauncherError.message("The session belongs to another account type. Sign in again with \(provider.title).")
        }
        var fields = Data()
        fields.put(session.userID); try fields.putString(key); fields.put(UInt64(0))
        try fields.putString("en-US"); try fields.putString(clientID); try fields.putString("")
        return fields
    }
}
