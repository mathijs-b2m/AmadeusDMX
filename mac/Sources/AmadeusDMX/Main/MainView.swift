// The main window: a sidebar (Show, Rig, Set, Engine), the rig and set and the engine controls in the toolbar.
import AmadeusKit
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
            VStack(spacing: 0) {
                LimiterBanner()  // a row of its own above the page: it pushes the page down, never covers it
                Group {
                    if model.needsSetup {
                        EngineMissingView()
                    } else {
                        switch model.section {
                        case .show: ShowView(stage: stage)
                        case .dmx: DMXPage()
                        case .rig: RigView()
                        case .set: SetView()
                        case .engine: EngineView()
                        case .settings: SettingsView(page: true)
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
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
        .navigationTitle(model.section == .show ? (model.showState.isActive ? model.feed.hello?.title ?? "Show" : "Show")
                         : model.section.title)
        .navigationSubtitle(subtitle)
        .onAppear {
            if model.needsSetup || model.sets.isEmpty || UserDefaults.standard.bool(forKey: "wizard") { openWindow(id: "wizard") }
            if let id = UserDefaults.standard.string(forKey: "openWindow") {  // -openWindow wizard (screenshots)
                if id == "dmx" { model.section = .dmx } else { openWindow(id: id) }
            }
        }
    }

    private var subtitle: String {
        switch model.section {  // each page about its own thing
        case .set:
            return model.sets.first { $0.name == model.editingSet }.map { "\($0.fixtureCount) fixtures" } ?? ""
        case .rig:
            let r = model.rigs.first { $0.name == model.editingRig }
            return r.map { $0.summary + (model.editingRigSet.isEmpty ? "" : " · \(model.editingRigSet) on it") } ?? ""
        case .dmx:
            return "set “\(model.selectedSet)”"
        case .engine, .settings:
            return ""
        case .show:
            break
        }
        switch model.showState {
        case .live, .playing, .attached:
            if let h = model.feed.hello { return "\(Int(h.bpm.rounded())) BPM · \(model.showTitle)" }
            return model.showTitle
        default:
            let m = model.mounted
            guard m.total > 0 else { return model.currentRig?.summary ?? "" }
            return m.placed < m.total ? "\(m.total - m.placed) of \(m.total) fixtures not mounted" : "\(m.total) fixtures · \(model.currentRig?.summary ?? "")"
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        if model.section == .show {  // the combination the show runs: only on the Show page
            ToolbarItem(placement: .navigation) {
                SetMenu()
            }
            ToolbarItem(placement: .navigation) {
                DirectorMenu()
            }
        }
        ToolbarItem(placement: .principal) {
            StatusPill()
        }
        ToolbarItemGroup(placement: .primaryAction) {
            LimiterButton()
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
            Text("Amadeus DMX needs its engine folder (with the Python environment).")
        } actions: {
            Button("Set Up…") { openWindow(id: "wizard") }
                .buttonStyle(.glassProminent)
        }
    }
}
