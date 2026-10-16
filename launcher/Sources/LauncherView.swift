import AppKit
import SwiftUI

private let ink = Color(red: 0.20, green: 0.13, blue: 0.28)
private let gold = Color(red: 0.94, green: 0.71, blue: 0.32)
private let parchment = Color(red: 0.98, green: 0.92, blue: 0.77)

struct LauncherView: View {
    @ObservedObject var model: LauncherModel
    @StateObject private var artwork: OfficialArtwork
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var active = true
    @State private var minimized = false
    @FocusState private var focused: Field?
    private enum Field { case username, password }
    init(model: LauncherModel) {
        self.model = model
        _artwork = StateObject(wrappedValue: OfficialArtwork(cache: model.state.appendingPathComponent("Artwork")))
    }
    private var animated: Bool { model.effects && !reduceMotion && active && !minimized }
    var body: some View {
        ZStack {
            Color(red: 0.10, green: 0.055, blue: 0.19)
            HStack(spacing: 0) {
                adventure.frame(maxWidth: .infinity)
                spellbook.frame(width: 372).padding(.trailing, 32)
            }.padding(.top, 26).padding(.bottom, 26)
            RoundedRectangle(cornerRadius: 9).stroke(gold.opacity(0.45), lineWidth: 1).padding(8)
                .allowsHitTesting(false).accessibilityHidden(true)
        }.preferredColorScheme(.dark)
        .task { await artwork.load() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in active = false }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in active = true }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didMiniaturizeNotification)) { _ in minimized = true }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didDeminiaturizeNotification)) { _ in minimized = false }
        .sheet(isPresented: $model.showSettings) { SettingsView(model: model) }
        .sheet(isPresented: $model.showImports) { imports }
        .alert("A little help is needed", isPresented: Binding(get: { model.issue != nil }, set: { if !$0 { model.issue = nil } })) {
            Button("OK", role: .cancel) { model.issue = nil }
            Button("Details", action: model.openLogs)
        } message: { Text(model.issue ?? "") }
    }
    private var adventure: some View {
        ZStack {
            Group {
                if let image = artwork.city { ArtworkScene(image: image, animated: animated) }
                else { MagicScene(animated: animated) }
            }.accessibilityHidden(true).allowsHitTesting(false)
            VStack(spacing: 0) {
                Group {
                    if let logo = artwork.logo {
                        Image(nsImage: logo).resizable().scaledToFit().frame(width: 265, height: 140)
                            .shadow(color: .black.opacity(0.6), radius: 8, y: 3)
                    } else {
                        Text("Wizard101").font(.system(size: 49, weight: .bold, design: .serif))
                            .foregroundColor(gold).frame(height: 140)
                    }
                }.accessibilityElement(children: .ignore).accessibilityLabel("Wizard101")
                Text("THE SPIRAL AWAITS").font(.system(size: 10, weight: .semibold, design: .serif)).tracking(4)
                    .foregroundColor(parchment.opacity(0.85)).padding(.top, 9)
                Spacer()
                HStack(spacing: 18) {
                    ForEach(Array(schools.enumerated()), id: \.offset) { _, school in
                        Image(systemName: school.1).font(.system(size: 15, weight: .semibold))
                            .foregroundColor(school.2).frame(width: 29, height: 29)
                            .background(Circle().fill(Color.black.opacity(0.22)))
                            .overlay(Circle().stroke(school.2.opacity(0.45)))
                            .help(school.0).accessibilityLabel(school.0)
                    }
                }.padding(.bottom, 28)
                Toggle(isOn: $model.effects) { Label("Magical effects", systemImage: "sparkles") }
                    .toggleStyle(.checkbox).font(.system(size: 11)).foregroundColor(parchment.opacity(0.8))
                    .help(reduceMotion ? "Animations are paused by your Mac's Reduce Motion setting." : "Turn the launcher's animated fireflies and sparkles on or off.")
            }.padding(.top, 42).padding(.bottom, 16)
        }
    }
    private var spellbook: some View {
        VStack(spacing: 0) {
            HStack {
                Image(systemName: "sparkle").foregroundColor(Color(red: 0.60, green: 0.36, blue: 0.14))
                Spacer()
                Button { model.showSettings = true } label: { Image(systemName: "gearshape.fill").font(.system(size: 17)) }
                    .buttonStyle(.plain).help("Settings").accessibilityLabel("Settings")
            }
            Text(model.ready ? "Welcome back" : "Welcome, wizard")
                .font(.system(size: 29, weight: .bold, design: .serif)).padding(.top, 16)
            Text(model.ready ? "Your adventure is one spell away." : "Let's open a door to the Spiral.")
                .font(.system(size: 12)).foregroundColor(ink.opacity(0.7)).padding(.top, 7)
            if !model.ready { setupSteps.padding(.top, 16) }
            ornament.padding(.top, 16).padding(.bottom, 16)
            if model.ready { login } else { setup }
            Spacer(minLength: 16)
            if model.busy || model.lastFailure != nil || !model.ready {
                VStack(spacing: 8) {
                    if model.busy {
                        if let progress = model.progress { ProgressView(value: progress).tint(ink) }
                        else { ProgressView().controlSize(.small).tint(ink) }
                    }
                    Text(model.status).font(.system(size: 12, weight: .semibold)).lineLimit(2).multilineTextAlignment(.center)
                    if model.busy { Text(model.detail).font(.system(size: 11)).foregroundColor(ink.opacity(0.65)).lineLimit(2) }
                    if !model.busy, let failure = model.lastFailure {
                        Text(failure).font(.system(size: 11)).foregroundColor(ink.opacity(0.8)).multilineTextAlignment(.center).lineLimit(4)
                    }
                    if !model.ready && !model.busy && model.lastFailure == nil {
                        Text(model.detail).font(.system(size: 11)).foregroundColor(ink.opacity(0.65)).multilineTextAlignment(.center).lineLimit(4)
                    }
                    if model.canCancel { Button("Cancel", action: model.cancel).buttonStyle(.plain).underline().font(.system(size: 11)) }
                }.frame(maxWidth: .infinity).accessibilityElement(children: .contain)
            } else if model.ready {
                Label("Ready for adventure", systemImage: "checkmark.seal.fill").font(.system(size: 11))
                    .foregroundColor(Color(red: 0.23, green: 0.39, blue: 0.26))
            }
            ornament.padding(.top, 20).padding(.bottom, 14)
            HStack(spacing: 5) {
                Text(model.provider == .steam ? "US Steam accounts" : "US accounts").font(.system(size: 10))
                Text("·")
                Link("Create an account", destination: model.provider.registrationURL).font(.system(size: 10)).underline()
            }.foregroundColor(ink.opacity(0.7))
            Text("Community beta · Manual app updates").font(.system(size: 9)).foregroundColor(ink.opacity(0.55)).padding(.top, 8)
        }.padding(.horizontal, 30).padding(.vertical, 26).frame(maxHeight: .infinity)
        .foregroundColor(ink).environment(\.colorScheme, .light)
        .background(RoundedRectangle(cornerRadius: 22)
            .fill(LinearGradient(colors: [parchment, Color(red: 0.92, green: 0.83, blue: 0.63), parchment], startPoint: .topLeading, endPoint: .bottomTrailing))
            .shadow(color: .black.opacity(0.5), radius: 20, x: -5, y: 8))
        .overlay(RoundedRectangle(cornerRadius: 17).stroke(Color(red: 0.64, green: 0.43, blue: 0.20).opacity(0.55), lineWidth: 1).padding(7).allowsHitTesting(false))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(gold.opacity(0.9), lineWidth: 2).allowsHitTesting(false))
    }
    private var login: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Account type", selection: Binding(get: { model.provider }, set: { model.selectProvider($0) })) {
                ForEach(AccountProvider.allCases) { provider in Text(provider.title).tag(provider) }
            }.pickerStyle(.segmented).accessibilityLabel("Account type")
            Text(model.provider.hint).font(.system(size: 11)).foregroundColor(ink.opacity(0.75))
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 7) {
                Text("Username").font(.system(size: 12, weight: .semibold))
                TextField("Enter your username", text: $model.username).textFieldStyle(.plain).font(.system(size: 14)).padding(12)
                    .background(Color.white.opacity(0.55)).clipShape(RoundedRectangle(cornerRadius: 7))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(ink.opacity(0.18)))
                    .focused($focused, equals: .username).onSubmit { focused = .password }.accessibilityLabel("Wizard101 username")
            }
            VStack(alignment: .leading, spacing: 7) {
                Text("Password").font(.system(size: 12, weight: .semibold))
                SecureField("Enter your password", text: $model.password).textFieldStyle(.plain).font(.system(size: 14)).padding(12)
                    .background(Color.white.opacity(0.55)).clipShape(RoundedRectangle(cornerRadius: 7))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(ink.opacity(0.18)))
                    .focused($focused, equals: .password).onSubmit { if canPlay { model.launch() } }.accessibilityLabel("Wizard101 password")
            }
            Toggle("Remember me", isOn: $model.savePassword).toggleStyle(.checkbox).font(.system(size: 12)).help("Save your password securely in Mac Keychain.")
            Button(action: model.launch) {
                Label(model.busy ? "Preparing…" : "Play", systemImage: model.busy ? "hourglass" : "play.fill")
                    .font(.system(size: 22, weight: .bold, design: .serif)).frame(maxWidth: .infinity).frame(height: 52)
            }.buttonStyle(SpellButtonStyle()).disabled(!canPlay).keyboardShortcut(.defaultAction)
            HStack {
                Spacer()
                Link("Forgot password?", destination: URL(string: "https://www.wizard101.com/user/account/needhelp")!).font(.system(size: 11)).foregroundColor(ink.opacity(0.7)).underline()
                Spacer()
            }
        }.disabled(model.busy)
    }
    private var canPlay: Bool {
        NativeAuthentication.encryptedHandshakeVerified && model.ready && !model.busy &&
            !model.username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !model.password.isEmpty
    }
    private var setup: some View {
        VStack(spacing: 14) {
            Image(systemName: model.needsRosetta ? "wand.and.stars" : "book.closed.fill").font(.system(size: 54))
                .foregroundColor(Color(red: 0.40, green: 0.24, blue: 0.52)).padding(.vertical, 8).accessibilityHidden(true)
            Text(model.needsRosetta ? "A touch of Apple magic" : "A whole world of magic").font(.system(size: 19, weight: .semibold, design: .serif))
            Text(model.needsRosetta ? "Install Rosetta with Apple's guided prompt to continue." : "Reuse a downloaded game or install a fresh copy. Your original files stay safe.")
                .font(.system(size: 12)).foregroundColor(ink.opacity(0.7)).multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Button(action: model.needsRosetta ? model.installRosetta : model.freshInstall) {
                Text(model.busy ? "Preparing…" : (model.needsRosetta ? "Install Rosetta" : (model.setupStarted ? "Continue setup" : "Install Wizard101")))
                    .font(.system(size: 18, weight: .bold, design: .serif)).frame(maxWidth: .infinity).frame(height: 52)
            }.buttonStyle(SpellButtonStyle()).disabled(model.busy || (!model.needsRosetta && !model.setupAvailable)).keyboardShortcut(.defaultAction)
            if model.needsRosetta || !model.setupAvailable {
                Button("Check again", action: model.refresh).buttonStyle(.plain).underline().font(.system(size: 11)).disabled(model.busy)
            } else {
                Button(model.installedGames.isEmpty ? "Already installed? Choose game folder…" : "Reuse a detected installation…", action: model.chooseImport)
                    .buttonStyle(.plain).underline().font(.system(size: 12)).disabled(model.busy)
            }
        }
    }
    private var setupSteps: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(SetupStep.allCases, id: \.rawValue) { step in
                Label(step.title, systemImage: step.rawValue < model.setupStep.rawValue ? "checkmark.circle.fill" : "\(step.rawValue + 1).circle")
                    .font(.system(size: 11, weight: step == model.setupStep ? .bold : .regular))
                    .foregroundColor(ink.opacity(step == model.setupStep ? 1 : 0.55))
                    .accessibilityLabel(step.title + (step == model.setupStep ? ", current step" : ""))
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private var imports: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Reuse your downloaded game").font(.system(size: 24, weight: .bold, design: .serif))
            Text("Choose a source. We'll copy its game files and settings into your separate standalone installation.")
                .font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
            ScrollView {
                VStack(spacing: 8) {
                    ForEach(model.installedGames) { source in
                        Button { model.importGame(source) } label: {
                            HStack {
                                Label(source.name, systemImage: "folder.fill").font(.system(size: 14, weight: .medium))
                                Spacer(); Image(systemName: "chevron.right")
                            }.padding(14).contentShape(Rectangle())
                        }.buttonStyle(.plain).background(Color.white.opacity(0.5)).cornerRadius(8)
                    }
                }
            }.frame(maxHeight: 240)
            HStack {
                Button("Choose another folder…", action: model.chooseImportFolder)
                Spacer()
                Button("Cancel") { model.showImports = false }.keyboardShortcut(.cancelAction)
            }
        }.padding(28).frame(width: 520).foregroundColor(ink).background(parchment).environment(\.colorScheme, .light)
    }
    private var ornament: some View {
        HStack(spacing: 10) {
            Rectangle().fill(ink.opacity(0.18)).frame(height: 1)
            Image(systemName: "sparkle").font(.system(size: 10)).foregroundColor(Color(red: 0.59, green: 0.38, blue: 0.16))
            Rectangle().fill(ink.opacity(0.18)).frame(height: 1)
        }.accessibilityHidden(true)
    }
    private var schools: [(String, String, Color)] {
        [("Fire", "flame.fill", .orange), ("Ice", "snowflake", .cyan), ("Storm", "bolt.fill", .purple),
         ("Myth", "eye.fill", .yellow), ("Life", "leaf.fill", .green), ("Death", "moon.fill", .white), ("Balance", "sun.max.fill", gold)]
    }
}

private struct SpellButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.foregroundColor(Color(red: 1, green: 0.94, blue: 0.76))
            .background(LinearGradient(colors: [Color(red: 0.46, green: 0.25, blue: 0.65), Color(red: 0.25, green: 0.12, blue: 0.39)], startPoint: .top, endPoint: .bottom))
            .clipShape(RoundedRectangle(cornerRadius: 10)).overlay(RoundedRectangle(cornerRadius: 10).stroke(gold, lineWidth: 2))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(gold.opacity(0.25)).padding(5))
            .shadow(color: ink.opacity(0.2), radius: 4, y: 3).scaleEffect(configuration.isPressed ? 0.98 : 1).opacity(enabled ? 1 : 0.55)
    }
}

private struct SettingsView: View {
    @ObservedObject var model: LauncherModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var advanced = false
    private let purple = Color(red: 0.39, green: 0.22, blue: 0.54)
    var body: some View {
        VStack(spacing: 20) {
            HStack(spacing: 12) {
                Image(systemName: "gearshape.fill").font(.system(size: 24)).foregroundColor(purple)
                Text("Settings").font(.system(size: 29, weight: .bold, design: .serif))
                Spacer()
            }
            Group {
                if advanced { ScrollView { settingsContent }.scrollIndicators(.hidden) }
                else { settingsContent }
            }
            Spacer(minLength: 0)
            HStack {
                Link(destination: URL(string: "https://www.wizard101.com/game/help-faq")!) {
                    Label("Help", systemImage: "questionmark.circle").font(.system(size: 12))
                }.foregroundColor(purple)
                Spacer()
                Button { model.showSettings = false } label: {
                    Text("Done").font(.system(size: 15, weight: .semibold)).frame(width: 100, height: 36)
                }.buttonStyle(SpellButtonStyle()).keyboardShortcut(.defaultAction)
            }
        }.padding(26).frame(width: 470, height: 560)
            .foregroundColor(ink).tint(purple).preferredColorScheme(.light)
            .background(LinearGradient(colors: [parchment, Color(red: 0.94, green: 0.86, blue: 0.68)], startPoint: .topLeading, endPoint: .bottomTrailing))
            .overlay(RoundedRectangle(cornerRadius: 9).stroke(gold.opacity(0.7)).padding(7).allowsHitTesting(false))
            .sheet(isPresented: $model.showOptimizations) { OptimizationView(model: model) }
    }
    private var settingsContent: some View {
                VStack(spacing: 14) {
                    card {
                        HStack(spacing: 14) {
                            icon("sparkles")
                            VStack(alignment: .leading, spacing: 5) {
                                Text("Magical effects").font(.system(size: 14, weight: .semibold))
                                Text(reduceMotion ? "Paused by Reduce Motion on your Mac." : "A little extra sparkle in the launcher.")
                                    .font(.system(size: 11)).foregroundColor(ink.opacity(0.65))
                            }
                            Spacer(minLength: 8)
                            Toggle("Magical effects", isOn: $model.effects).labelsHidden().toggleStyle(.switch)
                                .tint(purple).accentColor(purple).accessibilityLabel("Magical launcher effects")
                        }
                    }
                    card {
                        VStack(alignment: .leading, spacing: 12) {
                            Label("Game frame rate", systemImage: "speedometer").font(.system(size: 14, weight: .semibold))
                            HStack(spacing: 6) {
                                ForEach(FrameMode.allCases, id: \.self) { mode in
                                    Button { model.mode = mode } label: {
                                        Text(mode.title).font(.system(size: 13, weight: .semibold))
                                            .frame(maxWidth: .infinity).padding(.vertical, 9)
                                            .foregroundColor(model.mode == mode ? parchment : ink)
                                            .background(RoundedRectangle(cornerRadius: 7).fill(model.mode == mode ? purple : Color.white.opacity(0.4)))
                                    }.buttonStyle(.plain).accessibilityAddTraits(model.mode == mode ? .isSelected : [])
                                }
                            }.disabled(model.busy)
                        }
                    }
                    card {
                        VStack(spacing: 0) {
                            action("Check game updates", symbol: "arrow.triangle.2.circlepath", disabled: !model.ready || model.busy,
                                   help: model.ready ? "Check for game updates." : "Available after installing the game.", run: model.checkUpdates)
                            if let summary = model.updateSummary {
                                Text(summary).font(.system(size: 11)).foregroundColor(ink.opacity(0.7))
                                    .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8).padding(.leading, 34)
                            }
                            Divider().overlay(ink.opacity(0.1)).padding(.vertical, 10)
                            action("Forget saved password", symbol: "key.fill", disabled: model.busy || model.username.isEmpty,
                                   help: "Remove the remembered password from Mac Keychain.", run: model.forgetPassword)
                        }
                    }
                    card {
                        DisclosureGroup(isExpanded: $advanced) {
                            VStack(alignment: .leading, spacing: 14) {
                                if model.combinedOptimizations {
                                    Button("Performance options…") { model.showOptimizations = true }.disabled(model.busy)
                                } else if model.plan.workloadPerformance {
                                    Toggle("Use performance fixes", isOn: $model.workloadFixes).disabled(model.busy)
                                }
                                if !model.plan.workloadDiagnostics { Toggle("Prepare learned shaders", isOn: $model.warmup).disabled(model.busy) }
                                Toggle("Capture diagnostic timings", isOn: $model.profile).disabled(model.busy)
                                Button("Open launch details", action: model.openLogs)
                                Button("Reload saved password", action: model.loadPassword).disabled(model.busy || model.username.isEmpty)
                            }.font(.system(size: 12)).toggleStyle(.checkbox).padding(.top, 14)
                        } label: { Label("Advanced", systemImage: "wand.and.stars").font(.system(size: 14, weight: .semibold)) }
                        .tint(purple)
                    }
                }.padding(1)
    }
    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        content().frame(maxWidth: .infinity, alignment: .leading).padding(16)
            .background(RoundedRectangle(cornerRadius: 11).fill(Color.white.opacity(0.35)))
            .overlay(RoundedRectangle(cornerRadius: 11).stroke(ink.opacity(0.1)))
    }
    private func icon(_ symbol: String) -> some View {
        Image(systemName: symbol).font(.system(size: 21)).foregroundColor(purple)
            .frame(width: 30).accessibilityHidden(true)
    }
    private func action(_ title: String, symbol: String, disabled: Bool, help: String, run: @escaping () -> Void) -> some View {
        Button(action: run) {
            HStack(spacing: 12) {
                Image(systemName: symbol).frame(width: 22).foregroundColor(purple)
                Text(title).font(.system(size: 13, weight: .medium))
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 10))
            }.padding(.vertical, 3).contentShape(Rectangle())
        }.buttonStyle(.plain).disabled(disabled).help(help)
    }
}
