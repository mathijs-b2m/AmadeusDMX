// The rig editor: the stage in 3D (or from above), the rig's trusses and zones, the set's fixtures to mount on
// it (one by one, as a group, or automatically), and an inspector for the selection.
import DecisiveKit
import SwiftUI

struct RigEditorView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.undoManager) private var undoManager
    @State var editor: RigEditorModel
    @StateObject private var stage = StageController()
    @State private var showAdd = false
    @State private var error: String?

    var body: some View {
        HSplitView {
            ZStack(alignment: .top) {
                StageView(controller: stage)
                    .onAppear {
                        stage.workLight = 1
                        stage.editor = editor
                        stage.input = { [editor] in (editor.stageInput(), nil) }
                        stage.preset = .drone
                        editor.undoManager = undoManager
                    }
                toolbar.padding(12)
                VStack {
                    Spacer()
                    HStack(alignment: .bottom) {
                        hint
                        Spacer()
                        cameraButtons
                    }
                    .padding(12)
                }
            }
            .frame(minWidth: 520)

            EditorInspector(editor: editor, showAdd: $showAdd)
                .frame(minWidth: 300, idealWidth: 340, maxWidth: 440)
        }
        .onChange(of: undoManager) { editor.undoManager = undoManager }
        .onChange(of: model.configVersion) { editor.reloadIfClean() }
        .background {  // ⌘S saves the rig
            Button("") { save() }.keyboardShortcut("s", modifiers: .command).hidden()
        }
        .alert("Couldn’t Save", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
    }

    private func save() {
        Task {
            do { try await editor.save(model) } catch { self.error = error.localizedDescription }
        }
    }

    private var toolbar: some View {
        GlassEffectContainer(spacing: 8) {
            HStack(spacing: 8) {
                RigMenu(editor: editor)
                Picker("Tool", selection: $editor.tool) {
                    Label("Select", systemImage: "cursorarrow").tag(RigEditorModel.Tool.select)
                    Label("Draw Truss", systemImage: "line.diagonal").tag(RigEditorModel.Tool.truss)
                    Label("Place Tower", systemImage: "arrow.up.to.line").tag(RigEditorModel.Tool.tower)
                }
                .pickerStyle(.segmented)
                .labelStyle(.iconOnly)
                .fixedSize()
                .help("Select and move · Draw a truss on the floor (T) · Click to set a tower · Esc: back to select")
                if editor.tool == .truss {
                    Stepper(String(format: "at %.1f m", editor.buildHeight), value: $editor.buildHeight, in: 1...15, step: 0.25)
                        .fixedSize()
                        .help("The height a new truss goes up to")
                } else if editor.tool == .tower {
                    Stepper(String(format: "%.1f m tall", editor.towerHeight), value: $editor.towerHeight, in: 1...12, step: 0.5)
                        .fixedSize()
                        .help("How tall a new tower is")
                }
                Menu {
                    SwiftUI.Section("Box truss (quatro, 30 cm)") {
                        ForEach([1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0], id: \.self) { l in
                            Button("\(Int(l)) m") { editor.addTruss(length: l) }
                        }
                    }
                    SwiftUI.Section("Tower") {
                        ForEach([2.0, 3.0, 4.0], id: \.self) { l in
                            Button("\(Int(l)) m tower") { editor.addTruss(length: l, vertical: true) }
                        }
                    }
                } label: {
                    Label("Truss", systemImage: "square.split.bottomrightquarter")
                }
                .buttonStyle(.glass)
                .help("Add a truss or a tower")
                Menu {
                    SwiftUI.Section("Artistic (moving heads)") {
                        ForEach([RigEditorModel.ZonePreset.wall, .floorArea, .keepIn]) { p in
                            Button(p.title, systemImage: p.symbol) { editor.addZone(p) }
                        }
                    }
                    SwiftUI.Section("Safety (lasers)") {
                        ForEach([RigEditorModel.ZonePreset.laserAudience, .laserPlane]) { p in
                            Button(p.title, systemImage: p.symbol) { editor.addZone(p) }
                        }
                    }
                } label: {
                    Label("Zone", systemImage: "square.dashed")
                }
                .buttonStyle(.glass)
                .help("Draw a zone: where beams may not go (or may only go)")
                Menu {
                    Button("Mount the \(editor.doc.waitingCount) Waiting", systemImage: "wand.and.stars") {
                        Task { await editor.autoMount(model) }
                    }
                    .disabled(editor.doc.waitingCount == 0)
                    if editor.selectedFixtures.count > 0 {
                        Button("Re-Mount the Selected \(editor.selectedFixtures.count)", systemImage: "arrow.triangle.2.circlepath") {
                            Task { await editor.autoMount(model, ids: Array(editor.selectedFixtures)) }
                        }
                    }
                    Divider()
                    Button("Re-Mount Everything", systemImage: "arrow.counterclockwise") { Task { await editor.autoMount(model, all: true) } }
                } label: {
                    Label("Auto-Mount", systemImage: "wand.and.stars")
                } primaryAction: {
                    Task { await editor.autoMount(model, all: editor.doc.waitingCount == 0) }
                }
                .buttonStyle(.glass)
                .disabled(editor.busy || editor.doc.fixtures.isEmpty)
                .help("Hang the fixtures that wait in front of the stage: heads on the trusses, lasers high at the back, bars on the floor…")
                Toggle(isOn: $editor.showZones) { Label("Zones", systemImage: editor.showZones ? "eye" : "eye.slash") }
                    .toggleStyle(.button)
                    .buttonStyle(.glass)
                    .labelStyle(.iconOnly)
                    .help("Show or hide the zones (a selected zone always shows)")
                Toggle(isOn: $editor.snap) { Label("Snap", systemImage: "squareshape.split.3x3") }
                    .toggleStyle(.button)
                    .buttonStyle(.glass)
                    .labelStyle(.iconOnly)
                    .help("Snap to the 25 cm grid and onto trusses (hold ⌥ while dragging to place freely)")
                Spacer()
                if editor.busy { ProgressView().controlSize(.small) }
                if let m = editor.message {
                    Text(m).font(.callout).foregroundStyle(.secondary)
                        .task(id: m) { try? await Task.sleep(for: .seconds(2.5)); editor.message = nil }
                }
                Button("Revert") { editor.revert() }
                    .buttonStyle(.glass)
                    .disabled(!editor.isDirty)
                Button("Save") { save() }
                    .buttonStyle(.glassProminent)
                    .disabled(!editor.isDirty)
                    .help("Save the rig, and where the set hangs on it (⌘S)")
            }
        }
    }

    private var hint: some View {
        let n = editor.selectedFixtures.count
        let text = if editor.doc.waitingCount > 0 && editor.selection == nil {
            "\(editor.doc.waitingCount) fixtures wait in front of the stage: drag them onto a truss, drag a group from the list, or Auto-Mount"
        } else if editor.selection == nil {
            "Click to select · ⇧-click for more · ⌘A all fixtures · drag empty space to turn the view"
        } else if n > 1 {
            "\(n) selected: drag one and the rest come along · ⌫ unmounts them · R rotates"
        } else {
            "Drag to move · R rotates 15° (⇧R 90°) · arrows nudge · ⌫ unmounts or deletes · ⌥-drag places freely"
        }
        return Text(text)
            .font(.caption)
            .padding(.horizontal, 10).padding(.vertical, 6)
            .glassEffect(.regular, in: .capsule)
    }

    private var cameraButtons: some View {
        GlassEffectContainer(spacing: 6) {
            HStack(spacing: 6) {
                ForEach([CameraPreset.plan, .drone, .frontOfHouse, .side], id: \.self) { p in
                    Button { stage.preset = p } label: { Image(systemName: p.symbol).frame(width: 18, height: 18) }
                        .buttonStyle(p == stage.preset ? AnyPrimitiveButtonStyle(.glassProminent) : AnyPrimitiveButtonStyle(.glass))
                        .help(p.rawValue)
                }
            }
        }
    }
}

/// The rig's name: make a new one, duplicate, rename, delete (switching rigs is the list on the Rigs page).
private struct RigMenu: View {
    @Environment(AppModel.self) private var model
    let editor: RigEditorModel
    @State private var renaming: String?
    @State private var confirmDelete = false
    @State private var error: String?

    var body: some View {
        Menu {
            Button("New Rig…", systemImage: "plus") { model.showNewRig = true }
            Button("Duplicate", systemImage: "plus.square.on.square") {
                let r = model.editingRig
                run { try await model.api.createRig(name: unique(r + "-copy"), copyOf: r) }
            }
            Button("Rename…", systemImage: "pencil") { renaming = model.editingRig }
            Button("Show in Finder", systemImage: "folder") {
                if let url = model.workspace?.rigURL(model.editingRig) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
            }
            Divider()
            Button("Delete…", systemImage: "trash", role: .destructive) { confirmDelete = true }
                .disabled(model.rigs.count <= 1)
        } label: {
            Label(editor.isDirty ? "\(model.editingRig) •" : model.editingRig, systemImage: "building.2")
        }
        .buttonStyle(.glass)
        .disabled(model.engineRunning)
        .help("The rig: a new one, duplicate, rename, delete")
        .alert("Rename the Rig", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: Binding(get: { renaming ?? "" }, set: { renaming = $0 }))
            Button("Rename") {
                let old = model.editingRig, new = renaming ?? old
                run { try await model.api.renameRig(old, to: new); await MainActor.run { model.editingRig = new.lowercased() } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .confirmationDialog("Delete the rig “\(model.editingRig)”?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { let r = model.editingRig; run { try await model.api.deleteRig(r) } }
        } message: {
            Text("Its trusses, zones and where every set hung on it are removed. Your sets (the fixtures) stay.")
        }
        .alert("Couldn’t Change the Rigs", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
    }

    private func unique(_ base: String) -> String {
        var n = base, i = 2
        while model.rigs.contains(where: { $0.name == n }) { n = "\(base)\(i)"; i += 1 }
        return n
    }

    private func run(_ op: @escaping () async throws -> Void) {
        Task {
            guard await model.ensureSetupService() else { error = "The engine's setup service did not start."; return }
            do { try await op() } catch { self.error = error.localizedDescription }
            model.reloadSets()
        }
    }
}
