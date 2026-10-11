// Rigs: the venues. A list of your rigs; the one picked is edited in 3D (trusses, towers, stage, zones). Sets are
// placed on a rig here, and only here: a set on a rig is a combination the show can run, and its fixtures are
// arranged on the rig in the same editor. With no set picked you edit the rig alone.
import DecisiveKit
import SwiftUI

struct RigView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HSplitView {
            RigList()
                .frame(minWidth: 180, idealWidth: 220, maxWidth: 300, maxHeight: .infinity)
            VStack(spacing: 0) {
                if !model.editingRig.isEmpty {
                    PlacementBar()
                    Divider()
                }
                if let ws = model.workspace, !model.editingRig.isEmpty,
                   let editor = RigEditorModel(workspace: ws, rig: model.editingRig, set: model.editingRigSet) {
                    RigEditorView(editor: editor)
                        .id("\(model.editingRig)/\(model.editingRigSet)")
                } else {
                    ContentUnavailableView {
                        Label("No Rig Yet", systemImage: "square.split.bottomrightquarter")
                    } description: {
                        Text("A rig is the venue: the stage and the trusses your fixtures hang on.")
                    } actions: {
                        Button("New Rig…") { model.showNewRig = true }.buttonStyle(.borderedProminent)
                    }
                }
            }
            .frame(minWidth: 600, maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Your rigs.
private struct RigList: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List(selection: Binding(get: { model.editingRig }, set: { if let v = $0 { model.editingRig = v; model.editingRigSet = "" } })) {
            SwiftUI.Section("Rigs") {
                ForEach(model.rigs) { r in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.name).font(.headline)
                        let on = model.setsOn(r.name)
                        Text(r.summary + (on.isEmpty ? "" : " · " + on.joined(separator: ", ")))
                            .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                    .tag(Optional(r.name))
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            Button("New Rig…", systemImage: "plus") { model.showNewRig = true }
                .buttonStyle(.borderless).padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

/// The sets on this rig: which one's placement you edit, putting another set on it, taking one off.
private struct PlacementBar: View {
    @Environment(AppModel.self) private var model
    @State private var placing: String?
    @State private var removing: String?
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        let rig = model.editingRig
        let on = model.setsOn(rig)
        let off = model.sets.map(\.name).filter { !on.contains($0) }
        HStack(spacing: 10) {
            Text("On this rig").foregroundStyle(.secondary)
            Picker("Edit", selection: Binding(get: { model.editingRigSet }, set: { model.editingRigSet = $0 })) {
                Text("The rig alone").tag("")
                ForEach(on, id: \.self) { s in Text(s).tag(s) }
            }
            .labelsHidden()
            .fixedSize()
            .help("Edit the rig alone, or where a set's fixtures hang on it")
            Menu {
                ForEach(off, id: \.self) { s in Button(s) { placing = s } }
            } label: {
                Label("Place a Set", systemImage: "plus")
            }
            .fixedSize()
            .disabled(off.isEmpty || model.engineRunning || busy)
            .help("Put one of your sets on this rig: a combination the show can run")
            if !model.editingRigSet.isEmpty {
                Button("Take Off…", systemImage: "minus.circle") { removing = model.editingRigSet }
                    .disabled(model.engineRunning || busy)
                    .help("Take this set off the rig: where its fixtures hang here is forgotten")
            }
            if busy { ProgressView().controlSize(.small) }
            Spacer()
            if !on.isEmpty {
                Text("\(on.count) combination\(on.count == 1 ? "" : "s") for the show").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 8)
        .confirmationDialog("Place “\(placing ?? "")” on \(rig)", isPresented: Binding(get: { placing != nil }, set: { if !$0 { placing = nil } }),
                            titleVisibility: .visible) {
            Button("Auto-Mount the Fixtures") { place(auto: true) }
            Button("Place Them by Hand") { place(auto: false) }
            Button("Cancel", role: .cancel) { placing = nil }
        } message: {
            Text("Auto-mount hangs them the way a lighting tech would start; by hand they wait in front of the stage until you drag them onto the trusses.")
        }
        .confirmationDialog("Take “\(removing ?? "")” off \(rig)?", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible) {
            Button("Take Off", role: .destructive) {
                let s = removing ?? ""
                removing = nil
                run { try await model.unplaceSet(s, from: rig) }
            }
        } message: {
            Text("Where its fixtures hang on this rig is forgotten, and the show can no longer run this combination. The set and the rig stay.")
        }
        .alert("Couldn’t Change the Rig", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
    }

    private func place(auto: Bool) {
        guard let s = placing else { return }
        placing = nil
        let rig = model.editingRig
        run { try await model.placeSet(s, on: rig, auto: auto) }
    }

    private func run(_ op: @escaping () async throws -> Void) {
        busy = true
        Task {
            do { try await op() } catch { self.error = error.localizedDescription }
            busy = false
        }
    }
}
