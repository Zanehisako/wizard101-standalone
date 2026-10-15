import Foundation

struct InstalledGame: Identifiable, Equatable {
    let name: String
    let game: URL
    var id: String { game.path }

    static func discover(home: URL = FileManager.default.homeDirectoryForCurrentUser, excluding destination: URL) -> [InstalledGame] {
        let fm = FileManager.default
        let support = home.appendingPathComponent("Library/Application Support")
        let gamePath = "drive_c/ProgramData/KingsIsle Entertainment/Wizard101"
        var result: [InstalledGame] = [], seen = Set<String>()
        func add(_ name: String, _ game: URL) {
            let game = game.standardizedFileURL
            guard game != destination.standardizedFileURL,
                  game == game.resolvingSymlinksInPath().standardizedFileURL,
                  fm.fileExists(atPath: game.appendingPathComponent("Bin/WizardGraphicalClient.exe").path),
                  (try? game.appendingPathComponent("Data").resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true,
                  seen.insert(game.path).inserted else { return }
            result.append(InstalledGame(name: name, game: game))
        }
        // Scan known roots only; do not walk downloaded worlds or other apps.
        for folder in (try? fm.contentsOfDirectory(at: support, includingPropertiesForKeys: nil)) ?? []
            where folder.lastPathComponent.hasPrefix("Wizard101") {
            for prefix in ["Prefix/", "Data/Prefix/", ""] {
                add(folder.lastPathComponent, folder.appendingPathComponent(prefix + gamePath))
            }
        }
        for (label, root) in [("CrossOver", support.appendingPathComponent("CrossOver/Bottles")),
                              ("Official Wizard101", support.appendingPathComponent("Wizard101/Bottles"))] {
            for bottle in (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? [] {
                add(label + " — " + bottle.lastPathComponent, bottle.appendingPathComponent(gamePath))
            }
        }
        return result.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }
}

enum SetupStep: Int, CaseIterable {
    case prepareMac, installGame, signIn
    var title: String {
        switch self {
        case .prepareMac: return "Prepare Mac"
        case .installGame: return "Install or reuse game"
        case .signIn: return "Sign in and Play"
        }
    }
    static func current(needsRosetta: Bool, runtimeReady: Bool, gameReady: Bool) -> SetupStep {
        if needsRosetta || !runtimeReady { return .prepareMac }
        return gameReady ? .signIn : .installGame
    }
}
