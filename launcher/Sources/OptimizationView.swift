import SwiftUI

struct OptimizationView: View {
    @ObservedObject var model: LauncherModel
    private var directAvailable: Bool {
        let defaults = Bundle.main.object(forInfoDictionaryKey: "W101ExperimentDefaults") as? [String: String] ?? [:]
        return defaults["W101_DRAW_LAYOUT_DIRECT"] != nil
    }
    private var layoutCacheAvailable: Bool {
        model.plan.experimentDefaults["W101_DRAW_LAYOUT_CACHE"] != nil && !directAvailable
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Optimizations").font(.title2).fontWeight(.semibold)
            Text("Choose what to enable for your next launch. Compare one change at a time.")
                .foregroundColor(.secondary)
            ScrollView {
              VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Game visuals").fontWeight(.semibold)
                    Text(model.contentSummary).font(.caption).foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                option("Faster buffer decompression", detail: "Speeds up decoding complete blocks of game data.", value: $model.optimizations.buffer)
                option("Faster streaming decompression", detail: "Speeds up decoding game data as it arrives.", value: $model.optimizations.stream)
                option("Sharded wait queues", detail: "Reduces contention between waiting game threads.", value: $model.optimizations.waitQueues)
                option("Native Apple Silicon decoding", detail: "Uses your Mac's native CPU for large compressed blocks.", value: $model.optimizations.nativeDecode)
                option("Reuse character draw layouts", detail: layoutCacheAvailable ? "Reuses vertex layouts across draws. Experimental; improvement is unverified." : "Unavailable in this candidate; saved selection retained.", value: $model.optimizations.drawLayouts)
                    .disabled(!layoutCacheAvailable)
                option("Faster draw layouts", detail: directAvailable ? "Speeds up constructing draw layouts. Experimental; gameplay improvement is unverified." : "Unavailable in this candidate; saved selection retained.", value: $model.optimizations.directLayouts)
                    .disabled(!directAvailable)
                option("Prepare known assets", detail: "Prepares textures learned from earlier play before gameplay. Startup may take longer.", value: $model.optimizations.prepareAssets)
                if model.plan.experimentDefaults["W101_GAME_REPAIR"] != nil {
                    option("Faster scene property lookups", detail: "Speeds up scene metadata searches. Experimental; zone-entry improvement is unverified.", value: $model.optimizations.gameRepair)
                }
                if model.plan.experimentDefaults["W101_SCENE_NODES"] != nil {
                    option("Reuse temporary scene nodes", detail: "Reuses temporary scene memory. Experimental; gameplay improvement is unverified.", value: $model.optimizations.sceneNodes)
                }
                if model.plan.experimentDefaults["W101_METAL_ARCHIVE"] != nil {
                    option("Reuse compiled Metal pipelines", detail: "Reuses GPU shader pipelines after restart. Learning may take longer on the first visit.", value: $model.optimizations.metalArchive)
                }
                if model.plan.experimentDefaults["W101_SCENE_TEXTURES"] != nil {
                    option("Reuse scene texture uploads", detail: "Prepares reusable scene textures before play. Takes effect next launch.", value: $model.optimizations.sceneTextures)
                    option("Prepare known pipelines", detail: "Prepares saved rendering states before play. Startup may take longer.", value: $model.optimizations.preparePipelines)
                }
              }
            }.frame(maxHeight: 480)
            Text("Experimental · 60 FPS, graphics, cursor, asset cache and workers keep their current settings.")
                .font(.caption).foregroundColor(.secondary)
            HStack {
                Button("Reset to baseline") { model.optimizations = OptimizationSettings() }
                Spacer()
                Button("Done") { model.showOptimizations = false }.keyboardShortcut(.defaultAction)
            }
        }.padding(28).frame(width: 460).preferredColorScheme(.light)
            .foregroundColor(Color(red: 0.20, green: 0.13, blue: 0.28))
            .tint(Color(red: 0.39, green: 0.22, blue: 0.54))
            .background(Color(red: 0.98, green: 0.92, blue: 0.77))
    }
    private func option(_ title: String, detail: String, value: Binding<Bool>) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Toggle(title, isOn: value).toggleStyle(.checkbox)
            Text(detail).font(.caption).foregroundColor(.secondary).padding(.leading, 20)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}
