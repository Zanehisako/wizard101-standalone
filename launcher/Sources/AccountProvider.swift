import Foundation

enum AccountProvider: String, CaseIterable, Codable, Sendable, Identifiable {
    case us, steam
    var id: String { rawValue }
    var title: String { self == .us ? "US" : "Steam" }
    // Preserve every existing US Keychain item and preference in place.
    var keychainService: String { "local.wizard101.native-launcher." + (self == .us ? "US" : "Steam") }
    var usernameKey: String { self == .us ? "username" : "account.steam.username" }
    var rememberKey: String { self == .us ? "savePassword" : "account.steam.savePassword" }
    var hint: String {
        self == .us ? "Use your US Wizard101 account."
            : "Experimental on Mac. Use the Wizard101 username and password you created through Steam."
    }
    var registrationURL: URL {
        URL(string: self == .us ? "https://www.wizard101.com/game" : "https://www.wizard101.com/patchClient/New?abs=1")!
    }
}

struct AccountPreferences {
    let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    var provider: AccountProvider {
        get { AccountProvider(rawValue: defaults.string(forKey: "account.provider") ?? "") ?? .us }
        nonmutating set { defaults.set(newValue.rawValue, forKey: "account.provider") }
    }
    func username(for provider: AccountProvider) -> String { defaults.string(forKey: provider.usernameKey) ?? "" }
    func remembersPassword(for provider: AccountProvider) -> Bool { defaults.bool(forKey: provider.rememberKey) }
    func save(username: String, remember: Bool, for provider: AccountProvider) {
        defaults.set(username, forKey: provider.usernameKey)
        defaults.set(remember, forKey: provider.rememberKey)
    }
}
