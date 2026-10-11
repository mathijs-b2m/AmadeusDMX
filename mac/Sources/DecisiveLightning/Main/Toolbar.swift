// The toolbar: the set, the show's status, the mode and the start/stop button.
import DecisiveKit
import SwiftUI

/// The rig and the set the show runs with: "showcase on club". Most people have one set, and a rig per venue.
struct SetMenu: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Menu {
            let combos = model.combinations
            if combos.isEmpty {
                Text("No set is placed on a rig yet")
            } else {
                Picker("Show", selection: Binding(get: { AppModel.Combination(rig: model.selectedRig, set: model.selectedSet) },
                                                  set: { model.chooseShow($0) })) {
                    ForEach(combos) { c in Text(c.label).tag(c) }
                }
                .pickerStyle(.inline)
            }
            Divider()
            Button("Place Sets on Rigs…", systemImage: "square.split.bottomrightquarter") {
                model.editingRig = model.selectedRig
                model.editingRigSet = model.selectedSet
                model.section = .rig
            }
        } label: {
            Label(model.combinations.isEmpty ? "No Combination" : model.showLabel, systemImage: "square.split.bottomrightquarter")
                .labelStyle(.titleAndIcon)
        }
        .disabled(model.engineRunning)
        .help(model.engineRunning ? "A show runs with this set on this rig; stop it to switch"
              : "The set on the rig the show runs with: the combinations made on the Rigs page")
    }
}

struct StatusPill: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let state = model.showState
        HStack(spacing: 8) {
            Circle()
                .fill(dot(state))
                .frame(width: 8, height: 8)
                .shadow(color: dot(state), radius: state.isActive ? 4 : 0)
            if let h = model.feed.hello, state.isActive {
                let d = h.plan.indices.contains(model.feed.phrase) ? h.plan[model.feed.phrase] : nil
                Text(h.title).lineLimit(1).frame(maxWidth: 260)
                if let d {
                    Text(d.section.capitalized)
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Color(simd: Sections.color(d.section)).opacity(0.85), in: .capsule)
                        .foregroundStyle(.white)
                }
                Text(timeString(model.feed.time)).monospacedDigit().foregroundStyle(.secondary)
            } else {
                Text(state.title).foregroundStyle(.secondary)
            }
        }
        .font(.callout)
        .padding(.horizontal, 12)
    }

    private func dot(_ s: ShowState) -> Color {
        switch s {
        case .live, .playing: .green
        case .waitingForDJ, .starting: .orange
        case .attached: .blue
        case .failed: .red
        case .stopped: .gray
        }
    }
}

/// Who decides the show: the rules (instant, offline) or an AI model. It belongs to the set; a running live
/// show follows a change (the rules' plan plays until the AI's plan is ready).
struct DirectorMenu: View {
    @Environment(AppModel.self) private var model
    @State private var options: [DirectorOption] = []
    @State private var current = ""
    @State private var problem: String?

    var body: some View {
        Menu {
            Picker("Decision Model", selection: Binding(get: { current }, set: { choose($0) })) {
                ForEach(options) { d in
                    Text(d.available ? d.label : "\(d.label) (\(d.note ?? "not available"))").tag(d.value)
                        .selectionDisabled(!d.available)
                }
            }
            .pickerStyle(.inline)
            if let problem { Text(problem) }
        } label: {
            Label(short, systemImage: current == "rules" || current.isEmpty ? "list.bullet.rectangle" : "sparkles")
                .labelStyle(.titleAndIcon)
        }
        .disabled(model.selectedSet.isEmpty)
        .help("Decision model of this set: \(options.first { $0.value == current }?.label ?? current)")
        .task(id: "\(model.selectedRig)|\(model.selectedSet)") { await load() }
    }

    private var short: String {
        switch current {
        case "", "rules": "Rules"
        case let d where d.hasPrefix("ollama:"): "AI · " + d.dropFirst(7)
        default: "AI"
        }
    }

    private func load() async {
        guard !model.selectedSet.isEmpty, await model.ensureSetupService() else { return }
        options = (try? await model.api.directors()) ?? []
        let raw = try? await model.api.rig(rig: model.selectedRig, set: model.selectedSet)
        current = raw?["director"] as? String ?? "rules"
    }

    private func choose(_ value: String) {
        let before = current
        current = value
        Task {
            do {
                try await model.api.setDirector(value, rig: model.selectedRig, set: model.selectedSet)
                problem = nil
            } catch {
                current = before
                problem = "Couldn't switch: \(error.localizedDescription)"
            }
        }
    }
}

struct ModeMenu: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Menu {
            Picker("Mode", selection: Binding(get: { model.mode }, set: { model.setMode($0) })) {
                ForEach(ShowMode.allCases) { m in
                    Button { } label: { Label(m.title, systemImage: m.symbol); Text(m.detail) }.tag(m)
                }
            }
            .pickerStyle(.inline)
        } label: {
            Label(model.mode.title, systemImage: model.mode.symbol)
        }
        .help("\(model.mode.title): \(model.mode.detail)")
    }
}

struct EngineButton: View {
    @Environment(AppModel.self) private var model
    @State private var showDJ = false

    var body: some View {
        if model.engineRunning {
            Button {
                model.stopShow()
            } label: {
                Label("Stop", systemImage: "stop.fill")
            }
            .help("Stop the show (the lights black out) ⌘R")
        } else {
            Menu {
                ForEach(model.workspace?.djSources() ?? [], id: \.name) { dj in
                    Button("Start Live Show (\(dj.app)\(dj.verified.hasPrefix("not yet") ? ", untested" : ""))",
                           systemImage: "dot.radiowaves.left.and.right") { model.startLive(source: dj.name) }
                }
                Button("Start with a DJ Laptop…", systemImage: "laptopcomputer.and.arrow.down") { showDJ = true }
                Button("Play a Track…", systemImage: "music.note") { PlayPanel.choose(model) }
            } label: {
                Label("Start", systemImage: "play.fill")
            } primaryAction: {
                model.startLive()
            }
            .disabled(model.workspace == nil || model.selectedSet.isEmpty || model.showState == .attached)
            .sheet(isPresented: $showDJ) { DJLinkSheet().environment(model) }
            .help(model.showState == .attached ? "An engine is already running outside the app"
                  : "Start the live show: the lights follow VirtualDJ ⌘R")
        }
    }
}
