// The rig of the selected set: every fixture with its patch, and a 3D preview that lights the selection.
import DecisiveKit
import SwiftUI

struct RigView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        Group {
            if model.rigMode == "layout", let ws = model.workspace,
               let editor = RigEditorModel(workspace: ws, set: model.selectedSet) {
                RigEditorView(editor: editor)
                    .id(model.selectedSet)
            } else {
                RigPatchView()
            }
        }
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Picker("View", selection: $model.rigMode) {
                    Label("Patch", systemImage: "tablecells").labelStyle(.titleAndIcon).tag("patch")
                    Label("Layout", systemImage: "square.split.bottomrightquarter").labelStyle(.titleAndIcon).tag("layout")
                }
                .pickerStyle(.segmented)
                .fixedSize()
                .help("Patch: every fixture and its address · Layout: place trusses and fixtures")
            }
        }
    }
}

struct RigPatchView: View {
    @Environment(AppModel.self) private var model
    @StateObject private var stage = StageController()
    @State private var selection = Set<RigFile.Fixture.ID>()
    @State private var rig: RigFile?
    @State private var sortOrder = [KeyPathComparator(\RigFile.Fixture.id)]
    @State private var message: String?
    @State private var names: [String: String] = [:]

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                if let rig {
                    summary(rig)
                    Table(sorted(rig.fixtures), selection: $selection, sortOrder: $sortOrder) {
                        TableColumn("Fixture", value: \.id) { f in
                            Label(f.id, systemImage: symbol(f)).labelStyle(.titleAndIcon)
                        }
                        .width(min: 90, ideal: 110)
                        TableColumn("Model", value: \.model) { f in
                            Text(names[f.fixture] ?? f.model).foregroundStyle(.secondary)
                        }
                        TableColumn("Mode") { f in Text(f.mode ?? "–").monospacedDigit() }
                            .width(60)
                        TableColumn("Patch") { f in
                            Text("\(f.universe ?? 1).\(String(format: "%03d", f.address ?? 0))").monospacedDigit()
                        }
                        .width(70)
                        TableColumn("Mount") { f in Text(f.mount ?? "stand") }
                            .width(60)
                        TableColumn("Position") { f in
                            Text(position(f, rig)).monospacedDigit().foregroundStyle(.secondary)
                        }
                    }
                    .contextMenu(forSelectionType: RigFile.Fixture.ID.self) { ids in
                        Button("Identify on the Rig", systemImage: "lightbulb.max") { identify(ids) }
                            .disabled(model.currentSet?.isVirtual ?? true)
                    }
                } else {
                    ContentUnavailableView("No Set Selected", systemImage: "light.overhead.right")
                }
            }
            .frame(minWidth: 460)

            ZStack(alignment: .bottomLeading) {
                StageView(controller: stage)
                if let message {
                    Text(message).font(.callout).padding(10).glassEffect(.regular, in: .capsule).padding(12)
                }
            }
            .frame(minWidth: 360)
        }
        .toolbar {
            ToolbarItem {
                Button("Identify", systemImage: "lightbulb.max") { identify(selection) }
                    .disabled(selection.isEmpty || (model.currentSet?.isVirtual ?? true) || model.engineRunning)
                    .help("Light the selected fixtures on the real rig for 2 seconds")
            }
        }
        .onAppear(perform: load)
        .onChange(of: model.selectedSet) { load() }
        .onChange(of: selection) { stage.highlight = selection }
    }

    private func load() {
        rig = model.workspace?.loadSet(model.selectedSet)
        for key in Set(rig?.fixtures.map(\.fixture) ?? []) where names[key] == nil {
            if let d = model.workspace?.definition(key) { names[key] = "\(d.manufacturer) \(d.model)" }
        }
        stage.workLight = 1
        selection = []
        let name = model.selectedSet
        stage.input = { [weak model] in (model?.preview(name), nil) }
        stage.preset = .drone
    }

    private func sorted(_ f: [RigFile.Fixture]) -> [RigFile.Fixture] { f.sorted(using: sortOrder) }

    private func summary(_ rig: RigFile) -> some View {
        let set = model.currentSet
        return HStack(spacing: 18) {
            Metric(value: "\(rig.fixtures.count)", label: "fixtures")
            Metric(value: "\(Set(rig.fixtures.map(\.universe)).count)", label: "universes")
            Metric(value: set?.isVirtual ?? true ? "Visualiser" : (set?.outputText ?? "–"), label: "DMX output")
            Metric(value: rig.stage.map { "\(Int($0.widthM)) m" } ?? "6 m", label: "stage width")
            if rig.hasScreen { Metric(value: "LED", label: "wall") }
            Spacer()
            Button {
                model.editLayout()
            } label: {
                Label("Edit Layout", systemImage: "square.split.bottomrightquarter")
            }
            .buttonStyle(.borderedProminent)
            .help("Place trusses, fixtures and zones in 3D (⌘E)")
        }
        .padding(16)
    }

    private func symbol(_ f: RigFile.Fixture) -> String {
        let m = f.fixture.lowercased()
        if m.contains("laser") || m.contains("cs-1000") { return "rays" }
        if m.contains("blinder") { return "light.panel" }
        if m.contains("compar") || m.contains("par") { return "light.recessed" }
        return "light.overhead.right"
    }

    private func position(_ f: RigFile.Fixture, _ rig: RigFile) -> String {
        let w = rig.stage?.widthM ?? 6
        let x = (f.x ?? 0.5) * w
        let y = f.yM.map { String(format: "%.1f", $0) } ?? "–"
        let z = f.zM.map { String(format: "%.1f", $0) } ?? "–"
        return String(format: "x %.1f · y %@ · z %@", x, y, z)
    }

    private func identify(_ ids: Set<String>) {
        let rigIDs = Set(ids)
        Task {
            guard await model.ensureSetupService() else { message = "The setup service did not start."; return }
            if model.workspace?.activeSet != model.selectedSet { try? await model.api.makeDefault(model.selectedSet) }
            for id in rigIDs { try? await model.api.identify(fixture: id) }
            message = "Lit \(rigIDs.count == 1 ? rigIDs.first! : "\(rigIDs.count) fixtures") for 2 s"
            try? await Task.sleep(for: .seconds(3))
            message = nil
        }
    }
}
