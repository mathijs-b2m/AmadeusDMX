// Sets: your gear, nothing else. A list of your sets; the one picked shows every fixture, grouped by model, with
// its DMX patch, and lets you add and remove fixtures. Rigs (and where a set hangs on one) are on the Rigs page.
import DecisiveKit
import SwiftUI

struct SetView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @StateObject private var stage = StageController()
    @State private var selection = Set<String>()
    @State private var doc: RigDocument?
    @State private var layout: [String: Any] = [:]   // the set as in its file (what the inspector edits)
    @State private var names: [String: FixtureDefinition] = [:]
    @State private var showAdd = false
    @State private var message: String?
    @State private var error: String?

    var body: some View {
        @Bindable var model = model
        HSplitView {
            List(selection: Binding(get: { model.editingSet }, set: { if let v = $0 { model.editingSet = v } })) {
                SwiftUI.Section("Sets") {
                    ForEach(model.sets) { s in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.name).font(.headline)
                            Text("\(s.fixtureCount) fixtures · \(s.isVirtual ? "visualiser only" : s.outputText)")
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        .tag(Optional(s.name))
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
                    .buttonStyle(.borderless).padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(minWidth: 180, idealWidth: 220, maxWidth: 300, maxHeight: .infinity)

            VStack(spacing: 0) {
                SetHeader(doc: doc, showAdd: $showAdd)
                Divider()
                if let doc, !doc.fixtures.isEmpty {
                    List(selection: $selection) {
                        ForEach(groups(doc), id: \.key) { g in
                            SwiftUI.Section {
                                ForEach(g.fixtures) { f in FixtureRow(fixture: f, doc: doc) }
                            } header: {
                                GroupHeader(group: g)
                            }
                        }
                    }
                    .contextMenu(forSelectionType: String.self) { ids in
                        Button("Identify on the Lights", systemImage: "lightbulb.max") { identify(ids) }
                            .disabled(editingSummary?.isVirtual ?? true || model.engineRunning)
                        Divider()
                        Button("Remove from the Set", systemImage: "trash", role: .destructive) { remove(ids) }
                            .disabled(model.engineRunning)
                    }
                } else {
                    ContentUnavailableView {
                        Label("No Fixtures Yet", systemImage: "light.overhead.right")
                    } description: {
                        Text("Add the fixtures you own: search by brand or model across our library, QLC+ and the Open Fixture Library.")
                    } actions: {
                        Button("Add Fixtures…") { showAdd = true }.buttonStyle(.borderedProminent)
                    }
                }
            }
            .frame(minWidth: 480, maxWidth: .infinity, maxHeight: .infinity, alignment: .top)

            VStack(spacing: 0) {
                if selection.isEmpty {
                    ContentUnavailableView("Select a Fixture", systemImage: "slider.horizontal.3",
                                           description: Text("Its DMX mode, universe and address, and its name, are edited here. Select several to patch them in a row."))
                } else {
                    PatchInspector(ids: selection, fixtures: layout["fixtures"] as? [[String: Any]] ?? [],
                                     definition: { key in names[key] ?? model.workspace?.definition(key) },
                                     apply: change, rename: renameFixture)
                }
                if let message {
                    Text(message).font(.callout).padding(10).glassEffect(.regular, in: .capsule).padding(12)
                }
            }
            .frame(minWidth: 320, idealWidth: 380, maxHeight: .infinity, alignment: .top)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .sheet(isPresented: $showAdd) { AddToSetSheet { load() }.environment(model) }
        .toolbar {
            ToolbarItem {
                Button("Identify", systemImage: "lightbulb.max") { identify(selection) }
                    .disabled(selection.isEmpty || (editingSummary?.isVirtual ?? true) || model.engineRunning)
                    .help("Light the selected fixtures on the real rig for 2 seconds")
            }
        }
        .alert("Couldn’t Change the Set", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
        .onAppear(perform: load)
        .onChange(of: model.editingSet) { selection = []; load() }
        .onChange(of: model.sets) { load() }
        .onChange(of: selection) { stage.highlight = Set(selection.flatMap { id in elementIDs(id) }) }
    }

    struct Group {
        var key: String
        var definition: FixtureDefinition?
        var fixtures: [PlacedFixture]
    }

    private func groups(_ doc: RigDocument) -> [Group] {
        var order: [String] = [], by: [String: [PlacedFixture]] = [:]
        for f in doc.fixtures.sorted(by: { ($0.universe, $0.address) < ($1.universe, $1.address) }) {
            if by[f.key] == nil { order.append(f.key) }
            by[f.key, default: []].append(f)
        }
        return order.map { Group(key: $0, definition: names[$0], fixtures: by[$0]!) }
    }

    /// The visualiser's ids for a fixture (a bar's cells are "id.1", "id.2", …).
    private func elementIDs(_ id: String) -> [String] {
        guard let f = doc?.fixtures.first(where: { $0.id == id }) else { return [id] }
        let n = names[f.key]?.cells(f.mode) ?? 1
        return n > 1 ? (1...n).map { "\(id).\($0)" } : [id]
    }

    private var editingSummary: SetSummary? { model.sets.first { $0.name == model.editingSet } }

    private func load() {
        guard let ws = model.workspace else { return }
        doc = ws.document(rig: "", set: model.editingSet)  // the set alone: no rig
        layout = ws.composed(rig: "", set: model.editingSet)
            .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        for key in Set(doc?.fixtures.map(\.key) ?? []) where names[key] == nil { names[key] = ws.definition(key) }
        selection = selection.filter { id in doc?.fixtures.contains { $0.id == id } ?? false }
        stage.workLight = 1
        let set = model.editingSet
        stage.input = { [weak model] in (model?.preview(rig: "", set: set), nil) }
        if stage.preset != .drone { stage.preset = .drone }
    }

    /// A change to the set's fixtures, saved at once (the set alone).
    private func change(_ name: String, _ body: (inout [[String: Any]]) -> Void) {
        var l = layout
        var fixtures = l["fixtures"] as? [[String: Any]] ?? []
        body(&fixtures)
        l["fixtures"] = fixtures
        layout = l
        let set = model.editingSet
        Task {
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                try await model.api.saveSet(l, set: set)
                model.reloadSets()
                load()
            } catch { self.error = error.localizedDescription; load() }
        }
    }

    private func renameFixture(_ old: String, _ new: String) {
        let set = model.editingSet
        Task {
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                try await model.api.renameFixture(old, to: new, in: set)
                model.reloadSets()
                selection = [new]
                load()
                flash("Renamed \(old) → \(new)")
            } catch { self.error = error.localizedDescription }
        }
    }

    private func flash(_ text: String) {
        message = text
        Task { try? await Task.sleep(for: .seconds(3)); if message == text { message = nil } }
    }

    private func identify(_ ids: Set<String>) {
        let rig = model.selectedRig, set = model.editingSet  // (identify only needs the set's patch and output)
        Task {
            guard await model.ensureSetupService() else { error = "The engine's setup service did not start."; return }
            for id in ids { try? await model.api.identify(fixture: id, rig: rig, set: set) }
            flash("Lit \(ids.count == 1 ? ids.first! : "\(ids.count) fixtures") for 2 s")
        }
    }

    private func remove(_ ids: Set<String>) {
        let set = model.editingSet
        Task {
            do {
                guard await model.ensureSetupService(), let ws = model.workspace, let data = ws.composed(rig: "", set: set),
                      var layout = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw SetupAPIError.notRunning }
                layout["fixtures"] = (layout["fixtures"] as? [[String: Any]] ?? []).filter { !ids.contains($0["id"] as? String ?? "") }
                try await model.api.saveSet(layout, set: set)
                model.reloadSets()
                selection = []
                load()
                flash("Removed \(ids.count == 1 ? ids.first! : "\(ids.count) fixtures")")
            } catch { self.error = error.localizedDescription }
        }
    }
}

/// The set's name (a menu for the rare second set), what it holds, and where the DMX goes.
private struct SetHeader: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    let doc: RigDocument?
    @Binding var showAdd: Bool
    @State private var renaming: String?
    @State private var confirmDelete = false
    @State private var error: String?

    var body: some View {
        let set = model.sets.first { $0.name == model.editingSet }
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Menu {
                    Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
                    Button("Duplicate", systemImage: "plus.square.on.square") { run { try await model.api.createSet(name: unique(model.editingSet + "-copy"), copyOf: model.editingSet) } }
                    Button("Rename…", systemImage: "pencil") { renaming = model.editingSet }
                    Divider()
                    Button("Show in Finder", systemImage: "folder") {
                        if let url = model.workspace?.setURL(model.editingSet) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                    }
                    Button("Delete…", systemImage: "trash", role: .destructive) { confirmDelete = true }
                        .disabled(model.sets.count <= 1)
                } label: {
                    Text(model.editingSet).font(.title2.weight(.semibold))
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .disabled(model.engineRunning)
                Text("your fixtures").foregroundStyle(.secondary)
                Spacer()
                Button("Add Fixtures…", systemImage: "plus") { showAdd = true }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.engineRunning)
            }
            HStack(spacing: 18) {
                Metric(value: "\(doc?.fixtures.count ?? 0)", label: "fixtures")
                Metric(value: "\(Set(doc?.fixtures.map(\.key) ?? []).count)", label: "models")
                Metric(value: "\(Set(doc?.fixtures.map(\.universe) ?? []).count)", label: "universes")
                Button { openWindow(id: "dmx") } label: {
                    Metric(value: set?.isVirtual ?? true ? "Visualiser" : (set?.outputText ?? "–"), label: "DMX output ›")
                }
                .buttonStyle(.plain)
                .help("Where the set's universes go: DMX Devices & Output… (⇧⌘D)")
                Spacer()
            }
        }
        .padding(16)
        .alert("Rename the Set", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: Binding(get: { renaming ?? "" }, set: { renaming = $0 }))
            Button("Rename") {
                let old = model.editingSet, new = renaming ?? old
                run { try await model.api.renameSet(old, to: new); await MainActor.run { model.editingSet = new.lowercased() } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .confirmationDialog("Delete the set “\(model.editingSet)”?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { let s = model.editingSet; run { try await model.api.deleteSet(s) } }
        } message: {
            Text("Its fixture list and patch are removed, and where it hung on every rig. The rigs themselves stay.")
        }
        .alert("Couldn’t Change the Sets", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
    }

    private func unique(_ base: String) -> String {
        var n = base, i = 2
        while model.sets.contains(where: { $0.name == n }) { n = "\(base)\(i)"; i += 1 }
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

private struct GroupHeader: View {
    let group: SetView.Group

    var body: some View {
        let d = group.definition
        HStack {
            Image(systemName: FixtureIcon.symbol(d?.kind)).foregroundStyle(.tint)
            Text("\(group.fixtures.count)× \(d?.name ?? group.key)").font(.headline)
            if let f = group.fixtures.first {
                Text("\(f.mode) · \(d?.channels(f.mode) ?? 0) ch").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.vertical, 2)
    }
}

private struct FixtureRow: View {
    let fixture: PlacedFixture
    let doc: RigDocument

    var body: some View {
        HStack {
            Text(fixture.id).font(.body.monospaced())
                .frame(width: 110, alignment: .leading)
            Text("\(fixture.universe).\(String(format: "%03d", fixture.address))").monospacedDigit().foregroundStyle(.secondary)
                .frame(width: 70, alignment: .leading)
                .help("Universe.address: set this start address on the fixture's display")
            Text(fixture.mode).font(.callout).foregroundStyle(.secondary)
            Spacer()
        }
        .tag(fixture.id)
    }


}

/// SF Symbols for fixture kinds (library `kind`).
enum FixtureIcon {
    static func symbol(_ kind: String?) -> String {
        switch kind {
        case "moving_head": "light.overhead.right"
        case "moving_bar", "par_bar": "light.strip.2"
        case "laser": "rays"
        case "strobe": "bolt"
        case "blinder": "light.panel"
        default: "light.recessed"
        }
    }
}
