import Foundation

struct OptimizationSettings: Equatable {
    var buffer = false
    var stream = false
    var waitQueues = false
    var nativeDecode = false
    var prepareAssets = false
    var drawLayouts = false
    var directLayouts = false
    var gameRepair = false
    var sceneNodes = false
    var metalArchive = false
    var sceneTextures = false
    var preparePipelines = false
    var prepareAppearance = false

    var environment: [String: String] {
        ["W101_DECOMPRESS": buffer && stream ? "both" : buffer ? "buffer" : stream ? "stream" : "off",
         "W101_WAIT_QUEUES": waitQueues ? "sharded" : "off",
         "W101_NATIVE_DECODE": nativeDecode ? "auto" : "off",
         "W101_PREPARE_ASSETS": prepareAssets ? "1" : "0",
         "W101_DRAW_LAYOUT_CACHE": drawLayouts ? "1" : "0",
         "W101_DRAW_LAYOUT_DIRECT": directLayouts ? "1" : "0",
         "W101_GAME_REPAIR": gameRepair ? "1" : "0",
         "W101_SCENE_NODES": sceneNodes ? "1" : "0",
         "W101_METAL_ARCHIVE": metalArchive ? "1" : "0",
         "W101_SCENE_TEXTURES": sceneTextures ? "1" : "0",
         "W101_PREPARE_PIPELINES": preparePipelines ? "1" : "0",
         "W101_PREPARE_APPEARANCE": prepareAppearance ? "1" : "0"]
    }
    static func load(from defaults: UserDefaults = .standard) -> Self {
        Self(buffer: defaults.bool(forKey: "optimization.buffer"),
             stream: defaults.bool(forKey: "optimization.stream"),
             waitQueues: defaults.bool(forKey: "optimization.waitQueues"),
             nativeDecode: defaults.bool(forKey: "optimization.nativeDecode"),
             prepareAssets: defaults.bool(forKey: "optimization.prepareAssets"),
             drawLayouts: defaults.bool(forKey: "optimization.drawLayouts"),
             directLayouts: defaults.bool(forKey: "optimization.directLayouts"),
             gameRepair: defaults.bool(forKey: "optimization.gameRepair"),
             sceneNodes: defaults.bool(forKey: "optimization.sceneNodes"),
             metalArchive: defaults.bool(forKey: "optimization.metalArchive"),
             sceneTextures: defaults.bool(forKey: "optimization.sceneTextures"),
             preparePipelines: defaults.bool(forKey: "optimization.preparePipelines"),
             prepareAppearance: defaults.bool(forKey: "optimization.prepareAppearance"))
    }
    func save(to defaults: UserDefaults = .standard) {
        defaults.set(buffer, forKey: "optimization.buffer")
        defaults.set(stream, forKey: "optimization.stream")
        defaults.set(waitQueues, forKey: "optimization.waitQueues")
        defaults.set(nativeDecode, forKey: "optimization.nativeDecode")
        defaults.set(prepareAssets, forKey: "optimization.prepareAssets")
        defaults.set(drawLayouts, forKey: "optimization.drawLayouts")
        defaults.set(directLayouts, forKey: "optimization.directLayouts")
        defaults.set(gameRepair, forKey: "optimization.gameRepair")
        defaults.set(sceneNodes, forKey: "optimization.sceneNodes")
        defaults.set(metalArchive, forKey: "optimization.metalArchive")
        defaults.set(sceneTextures, forKey: "optimization.sceneTextures")
        defaults.set(preparePipelines, forKey: "optimization.preparePipelines")
        defaults.set(prepareAppearance, forKey: "optimization.prepareAppearance")
    }
}
