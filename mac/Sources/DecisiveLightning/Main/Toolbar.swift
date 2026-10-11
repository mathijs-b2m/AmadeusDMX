// The toolbar: the set, the show's status, the mode and the start/stop button.
import DecisiveKit
import SwiftUI

/// The rig and the set the show runs with: "showcase on club". Most people have one set, and a rig per venue.
struct SetMenu: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Menu {
            SwiftUI.Section("Rig: the venue") {
                Picker("Rig", selection: Binding(get: { model.selectedRig }, set: { model.choose(rig: $0) })) {
                    ForEach(model.rigs) { r in
                        Text("\(r.name) — \(r.summary)").tag(r.name)
                    }
                }
                .pickerStyle(.inline)
                Button("New Rig…", systemImage: "plus") { model.showNewRig = true }
                Button("Edit the Rig", systemImage: "square.split.bottomrightquarter") { model.section = .rig }
            }
            SwiftUI.Section("Set: your fixtures") {
                if model.sets.count > 1 {
                    Picker("Set", selection: Binding(get: { model.selectedSet }, set: { model.choose(set: $0) })) {
                        ForEach(model.sets) { s in Text("\(s.name) — \(s.fixtureCount) fixtures").tag(s.name) }
                    }
                    .pickerStyle(.inline)
                }
                Button("Fixtures and Patch", systemImage: "light.overhead.right") { model.section = .set }
                Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
            }
        } label: {
            Label(model.showLabel, systemImage: "square.split.bottomrightquarter")
                .labelStyle(.titleAndIcon)
        }
        .disabled(model.engineRunning)
        .help(model.engineRunning ? "A show runs on this rig with this set; stop it to switch"
              : "The venue (rig) and your fixtures (set) the show runs with")
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
