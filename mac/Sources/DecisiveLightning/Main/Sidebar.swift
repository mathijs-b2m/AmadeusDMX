// The sidebar: the pages, the sets, and the engine's state at the bottom.
import DecisiveKit
import SwiftUI

struct Sidebar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: $model.sidebarSelection) {
            // id: \.self - a selectable list tags ForEach rows with their id; it must be the selection's type
            ForEach(Section.allCases, id: \.self) { s in
                NavigationLink(value: s) {
                    Label(s.title, systemImage: s.symbol)
                }
                .badge(badge(s))
            }
            if !model.sets.isEmpty {
                SwiftUI.Section("Sets") {
                    ForEach(model.sets) { set in
                        Button {
                            if !model.engineRunning { model.selectedSet = set.name }
                        } label: {
                            HStack {
                                Label(set.name, systemImage: set.name == model.selectedSet ? "checkmark.circle.fill" : "circle")
                                    .symbolRenderingMode(.hierarchical)
                                    .foregroundStyle(set.name == model.selectedSet ? .primary : .secondary)
                                Spacer()
                                Text("\(set.fixtureCount)")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        .buttonStyle(.plain)
                        .disabled(model.engineRunning && set.name != model.selectedSet)
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) { EngineFooter().padding(10) }
    }

    private func badge(_ s: Section) -> Text? {
        if s == .engine, case .failed = model.showState { return Text("!") }
        return nil
    }
}

/// The engine at a glance, at the bottom of the sidebar.
struct EngineFooter: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let state = model.showState
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: state.symbol)   // no symbolEffect: a running animation redraws every frame
                    .foregroundStyle(color(state))
                Text(state.title).font(.callout.weight(.semibold))
                Spacer()
                if model.feed.state == .connected, state.isActive, !model.feed.lite {
                    Text("\(Int(model.feed.fps.rounded())) fps")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            if case .failed(let why) = state {
                Text(why).font(.caption).foregroundStyle(.secondary).lineLimit(3)
            } else if let link = model.feed.link, model.engineRunning {
                Label(link.up ? "\(link.name) · \(String(format: "%.0f", link.jitterMs)) ms jitter" : "\(link.name): link down",
                      systemImage: link.up ? "laptopcomputer" : "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(link.up ? Color.secondary : Color.orange)
            } else if state == .waitingForDJ {
                Text(model.remoteDJ.map { "Waiting for \($0)…" } ?? "Load a track in VirtualDJ with DecisiveLink as master effect.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if state == .attached {
                Text("An engine started outside the app is running; the app shows its lights.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if let set = model.currentSet {
                Text(set.isVirtual || !model.sendArtNet ? "Visualiser only" : set.outputText)
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassEffect(.regular, in: .rect(cornerRadius: 14))
    }

    private func color(_ s: ShowState) -> Color {
        switch s {
        case .live, .playing: .green
        case .waitingForDJ, .starting: .orange
        case .attached: .blue
        case .failed: .red
        case .stopped: .secondary
        }
    }
}
