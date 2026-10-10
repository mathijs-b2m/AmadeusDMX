// The set: your gear. Every fixture you own, grouped by model, with its DMX patch and where it hangs on the
// rig the show uses; adding and removing fixtures; and (rarely needed) more sets, in a menu.
import DecisiveKit
import SwiftUI

struct SetView: View {
    @Environment(AppModel.self) private var model
    @StateObject private var stage = StageController()
    @State private var selection = Set<String>()
    @State private var doc: RigDocument?
    @State private var names: [String: FixtureDefinition] = [:]
    @State private var showAdd = false
    @State private var message: String?
    @State private var error: String?

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                SetHeader(doc: doc, showAdd: $showAdd)
                Divider()
                if let doc, !doc.fixtures.isEmpty {
                    List(selection: $selection) {
                        ForEach(groups(doc), id: \.key) { g in
                            SwiftUI.Section {
                                ForEach(g.fixtures) { f in FixtureRow(fixture: f, doc: doc) }
                            } header: {
                                GroupHeader(group: g, rig: model.selectedRig)
                            }
                        }
                    }
                    .contextMenu(forSelectionType: String.self) { ids in
                        Button("Identify on the Lights", systemImage: "lightbulb.max") { identify(ids) }
                            .disabled(model.currentSet?.isVirtual ?? true || model.engineRunning)
                        Button("Mount on \(model.selectedRig)", systemImage: "wand.and.stars") { mount(ids) }
                            .disabled(model.engineRunning)
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
            .frame(minWidth: 480)

            ZStack(alignment: .bottomLeading) {
                StageView(controller: stage)
                if let message {
                    Text(message).font(.callout).padding(10).glassEffect(.regular, in: .capsule).padding(12)
                }
            }
            .frame(minWidth: 340)
        }
        .sheet(isPresented: $showAdd) { AddToSetSheet { load() }.environment(model) }
        .toolbar {
            ToolbarItem {
                Button("Identify", systemImage: "lightbulb.max") { identify(selection) }
                    .disabled(selection.isEmpty || (model.currentSet?.isVirtual ?? true) || model.engineRunning)
                    .help("Light the selected fixtures on the real rig for 2 seconds")
            }
        }
        .alert("Couldn’t Change the Set", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
        .onAppear(perform: load)
        .onChange(of: model.selectedSet) { load() }
        .onChange(of: model.selectedRig) { load() }
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

    private func load() {
        guard let ws = model.workspace else { return }
        doc = ws.document(rig: model.selectedRig, set: model.selectedSet)
        for key in Set(doc?.fixtures.map(\.key) ?? []) where names[key] == nil { names[key] = ws.definition(key) }
        selection = selection.filter { id in doc?.fixtures.contains { $0.id == id } ?? false }
        stage.workLight = 1
        let rig = model.selectedRig, set = model.selectedSet
        stage.input = { [weak model] in (model?.preview(rig: rig, set: set), nil) }
        if stage.preset != .drone { stage.preset = .drone }
    }

    private func flash(_ text: String) {
        message = text
        Task { try? await Task.sleep(for: .seconds(3)); if message == text { message = nil } }
    }

    private func identify(_ ids: Set<String>) {
        let rig = model.selectedRig, set = model.selectedSet
        Task {
            guard await model.ensureSetupService() else { error = "The engine's setup service did not start."; return }
            for id in ids { try? await model.api.identify(fixture: id, rig: rig, set: set) }
            flash("Lit \(ids.count == 1 ? ids.first! : "\(ids.count) fixtures") for 2 s")
        }
    }

    private func mount(_ ids: Set<String>) {
        let rig = model.selectedRig, set = model.selectedSet
        Task {
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                try await model.api.automount(rig: rig, set: set, ids: Array(ids))
                model.reloadSets()
                load()
                flash("Mounted \(ids.count) on \(rig)")
            } catch { self.error = error.localizedDescription }
        }
    }

    private func remove(_ ids: Set<String>) {
        let rig = model.selectedRig, set = model.selectedSet
        Task {
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                var layout = try await model.api.rig(rig: rig, set: set)
                layout["fixtures"] = (layout["fixtures"] as? [[String: Any]] ?? []).filter { !ids.contains($0["id"] as? String ?? "") }
                try await model.api.saveRig(layout, rigName: rig, setName: set)
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
        let set = model.currentSet
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Menu {
                    if model.sets.count > 1 {
                        Picker("Set", selection: Binding(get: { model.selectedSet }, set: { model.choose(set: $0) })) {
                            ForEach(model.sets) { s in Text("\(s.name) — \(s.fixtureCount) fixtures").tag(s.name) }
                        }
                        .pickerStyle(.inline)
                        Divider()
                    }
                    Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
                    Button("Duplicate", systemImage: "plus.square.on.square") { run { try await model.api.createSet(name: unique(model.selectedSet + "-copy"), copyOf: model.selectedSet) } }
                    Button("Rename…", systemImage: "pencil") { renaming = model.selectedSet }
                    Divider()
                    Button("Show in Finder", systemImage: "folder") {
                        if let url = model.workspace?.setURL(model.selectedSet) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                    }
                    Button("Delete…", systemImage: "trash", role: .destructive) { confirmDelete = true }
                        .disabled(model.sets.count <= 1)
                } label: {
                    Text(model.selectedSet).font(.title2.weight(.semibold))
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
                Metric(value: set?.isVirtual ?? true ? "Visualiser" : (set?.outputText ?? "–"), label: "DMX output")
                Spacer()
                let m = model.mounted
                if m.total > 0 {
                    Button {
                        model.section = .rig
                    } label: {
                        Label(m.placed == m.total ? "All mounted on \(model.selectedRig)" : "\(m.total - m.placed) not mounted on \(model.selectedRig)",
                              systemImage: m.placed == m.total ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                    }
                    .buttonStyle(.link)
                    .foregroundStyle(m.placed == m.total ? Color.green : Color.orange)
                    .help("Open the rig to see where they hang")
                }
            }
        }
        .padding(16)
        .alert("Rename the Set", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: Binding(get: { renaming ?? "" }, set: { renaming = $0 }))
            Button("Rename") {
                let old = model.selectedSet, new = renaming ?? old
                run { try await model.api.renameSet(old, to: new); await MainActor.run { model.selectedSet = new.lowercased() } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .confirmationDialog("Delete the set “\(model.selectedSet)”?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { let s = model.selectedSet; run { try await model.api.deleteSet(s) } }
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
    let rig: String

    var body: some View {
        let d = group.definition
        let placed = group.fixtures.filter { !$0.waiting }.count
        HStack {
            Image(systemName: FixtureIcon.symbol(d?.kind)).foregroundStyle(.tint)
            Text("\(group.fixtures.count)× \(d?.name ?? group.key)").font(.headline)
            if let f = group.fixtures.first {
                Text("\(f.mode) · \(d?.channels(f.mode) ?? 0) ch").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(placed == group.fixtures.count ? "on \(rig)" : "\(group.fixtures.count - placed) waiting")
                .font(.caption).foregroundStyle(placed == group.fixtures.count ? Color.secondary : Color.orange)
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
            Spacer()
            Text(location).font(.callout).foregroundStyle(fixture.waiting ? Color.orange : Color.secondary)
        }
        .tag(fixture.id)
    }

    private var location: String {
        if fixture.waiting { return "not mounted" }
        guard let t = fixture.truss else {
            return fixture.mount == "floor" ? "on the floor" : fixture.mount == "hang" ? "hanging" : "on a stand"
        }
        let truss = doc.trusses.first { $0.id == t }
        if truss?.vertical == true { return "\(t), \(String(format: "%.1f", fixture.zM)) m up" }
        return "\(t), \(fixture.side ?? "under")"
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
