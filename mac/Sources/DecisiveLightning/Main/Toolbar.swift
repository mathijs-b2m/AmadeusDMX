// The toolbar: the set, the show's status, the mode and the start/stop button.
import DecisiveKit
import SwiftUI

struct SetMenu: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Menu {
            Picker("Set", selection: Binding(get: { model.selectedSet }, set: { model.selectedSet = $0 })) {
                ForEach(model.sets) { s in
                    Text("\(s.name) — \(s.fixtureCount) fixtures").tag(s.name)
                }
            }
            .pickerStyle(.inline)
            Divider()
            Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
            Button("Manage Sets", systemImage: "square.stack.3d.up") { model.section = .sets }
        } label: {
            Label(model.selectedSet.isEmpty ? "No Set" : model.selectedSet, systemImage: "square.stack.3d.up.fill")
                .labelStyle(.titleAndIcon)
        }
        .disabled(model.engineRunning)
        .help(model.engineRunning ? "A show runs with this set; stop it to switch sets" : "The rig the show runs with")
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
                Button("Start Live Show (VirtualDJ)", systemImage: "dot.radiowaves.left.and.right") { model.startLive() }
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
