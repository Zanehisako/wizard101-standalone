import Foundation

// Presentation preferences never enable game experiments or timing capture.
struct LauncherPreferences {
    let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    var effects: Bool {
        get { defaults.object(forKey: "launcher.effects") as? Bool ?? true }
        nonmutating set { defaults.set(newValue, forKey: "launcher.effects") }
    }
    var frameMode: FrameMode {
        get { FrameMode(rawValue: defaults.string(forKey: "launcher.frameMode") ?? "") ?? .capped }
        nonmutating set { defaults.set(newValue.rawValue, forKey: "launcher.frameMode") }
    }
}
