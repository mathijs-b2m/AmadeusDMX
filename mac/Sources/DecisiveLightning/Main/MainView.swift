// The main window: a sidebar (Show, Rig, Set, Engine), the rig and set and the engine controls in the toolbar.
import DecisiveKit
import SwiftUI

struct MainView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @StateObject private var stage = StageController()

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            Sidebar()
                .navigationSplitViewColumnWidth(min: 200, ideal: 230, max: 300)
        } detail: {
            Group {
                if model.needsSetup {
                    EngineMissingView()
                } else {
                    switch model.section {
                    case .show: ShowView(stage: stage)
                    case .rig: RigView()
                    case .set: SetView()
                    case .engine: EngineView()
                    }
                }
            }
            .toolbar { toolbar }
        }
        .alert(model.pendingMode.map { "Switch to \($0.title)?" } ?? "", isPresented: Binding(
            get: { model.pendingMode != nil }, set: { if !$0 { model.pendingMode = nil } }
        ), presenting: model.pendingMode) { _ in
            Button("Restart Show") { model.confirmPendingMode() }
            Button("Cancel", role: .cancel) { model.pendingMode = nil }
        } message: { m in
            Text(m.sendsDMX ? "Sending to the lights needs the show to restart. It picks up where it was in a few seconds."
                 : "The show restarts without sending to the lights: the lights black out.")
        }
        .sheet(isPresented: $model.showNewRig) { NewRigSheet().environment(model) }
        .sheet(isPresented: Binding(get: { model.mountPrompt != nil }, set: { if !$0 { model.mountPrompt = nil } })) {
            if let p = model.mountPrompt { MountPromptSheet(rig: p.rig, set: p.set).environment(model) }
        }
        .navigationTitle(model.section == .show ? (model.showState.isActive ? model.feed.hello?.title ?? "Show" : "Show")
                         : model.section.title)
        .navigationSubtitle(subtitle)
        .onAppear {
            if model.needsSetup || model.sets.isEmpty || UserDefaults.standard.bool(forKey: "wizard") { openWindow(id: "wizard") }
        }
    }

    private var subtitle: String {
        switch model.showState {
        case .live, .playing, .attached:
            if let h = model.feed.hello { return "\(Int(h.bpm.rounded())) BPM · \(model.showState.title)" }
            return model.showState.title
        default:
            let m = model.mounted
            guard m.total > 0 else { return model.currentRig?.summary ?? "" }
            return m.placed < m.total ? "\(m.total - m.placed) of \(m.total) fixtures not mounted" : "\(m.total) fixtures · \(model.currentRig?.summary ?? "")"
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .navigation) {
            SetMenu()
        }
        ToolbarItem(placement: .principal) {
            StatusPill()
        }
        ToolbarItemGroup(placement: .primaryAction) {
            ModeMenu()
            EngineButton()
            if model.section == .show {
                Button {
                    model.showInspector.toggle()
                } label: {
                    Label("Director", systemImage: "sidebar.trailing")
                }
                .help("Show what the director decided for this phrase")
            }
        }
    }
}

struct EngineMissingView: View {
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        ContentUnavailableView {
            Label("Engine Not Found", systemImage: "shippingbox")
        } description: {
            Text("Decisive Lightning needs its engine folder (with the Python environment).")
        } actions: {
            Button("Set Up…") { openWindow(id: "wizard") }
                .buttonStyle(.glassProminent)
        }
    }
}
