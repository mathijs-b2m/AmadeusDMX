// The rig editor: the stage in 3D (or from above), trusses and fixtures to place, an inspector for the selection.
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
                    HStack {
                        hint
                        Spacer()
                        cameraButtons
                    }
                    .padding(12)
                }
            }
            .frame(minWidth: 520)

            EditorInspector(editor: editor, showAdd: $showAdd)
                .frame(minWidth: 280, idealWidth: 320, maxWidth: 420)
        }
        .onChange(of: undoManager) { editor.undoManager = undoManager }
        .background {  // ⌘S saves the layout
            Button("") { save() }.keyboardShortcut("s", modifiers: .command).hidden()
        }
        .alert("Couldn’t Save", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
    }

    private func save() {
        do { try editor.save(); model.reloadSets() } catch { self.error = error.localizedDescription }
    }

    private var toolbar: some View {
        GlassEffectContainer(spacing: 8) {
            HStack(spacing: 8) {
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
                .help("Add a truss")
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
                Button { showAdd = true } label: { Label("Fixtures", systemImage: "plus.circle") }
                    .buttonStyle(.glass)
                    .help("Add fixtures: on the selected truss, or on the floor")
                    .popover(isPresented: $showAdd, arrowEdge: .bottom) {
                        AddFixturesView(editor: editor, isPresented: $showAdd)
                    }
                Toggle(isOn: $editor.showZones) { Label("Zones", systemImage: editor.showZones ? "eye" : "eye.slash") }
                    .toggleStyle(.button)
                    .buttonStyle(.glass)
                    .help("Show or hide the zones (a selected zone always shows)")
                Toggle(isOn: $editor.snap) { Label("Snap", systemImage: "squareshape.split.3x3") }
                    .toggleStyle(.button)
                    .buttonStyle(.glass)
                    .help("Snap to the 25 cm grid and onto trusses (hold ⌥ while dragging to place freely)")
                Spacer()
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
                    .help("Write the layout into the set (⌘S)")
            }
        }
    }

    private var hint: some View {
        Text(editor.selection == nil
             ? "Click a truss or fixture to select it · drag empty space to turn the view"
             : "Drag to move · R rotates 15° (⇧R 90°) · arrows nudge · ⌫ deletes · ⌥-drag places freely")
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
