// Sets: your gear, nothing else. A list of your sets; the one picked shows every fixture, grouped by model, with
// its DMX patch, and lets you add and remove fixtures. Rigs (and where a set hangs on one) are on the Rigs page.
import AmadeusKit
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
    @State private var lit = Set<String>()   // fixtures the light test keeps on
    @State private var testOff: [String: Task<Void, Never>] = [:]   // their switch-off when the engine's time runs out
    @State private var mapTarget: MapTarget?   // the DMX mapper, for a model and mode of the set
    @State private var error: String?

    var body: some View {
        @Bindable var model = model
        HSplitView {
            List(selection: Binding(get: { model.editingSet }, set: { if let v = $0 { model.editingSet = v } })) {
                SwiftUI.Section {
                    ForEach(model.sets.filter { !$0.isExample }) { SetRow(set: $0) }
                    if !model.sets.contains(where: { !$0.isExample }) {
                        Text("None yet. Your fixtures go in a set of your own: make one with New Set…")
                            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                            .selectionDisabled()
                    }
                } header: {
                    HStack {  // as on the Rigs page: a + by the title, the big button under the list
                        Text("Your Sets")
                        Spacer()
                        Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
                            .labelStyle(.iconOnly).buttonStyle(.borderless)
                            .disabled(model.engineRunning)
                            .help("Make a new set with the set-up assistant")
                    }
                }
                if model.sets.contains(where: \.isExample) {
                    SwiftUI.Section {
                        ForEach(model.sets.filter(\.isExample)) { SetRow(set: $0) }
                    } header: {
                        Text("Examples")
                    } footer: {
                        Text("To look around in and try the show.").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                Button { openWindow(id: "wizard") } label: {
                    Label("New Set…", systemImage: "plus").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent).controlSize(.large)
                .disabled(model.engineRunning)
                .padding(10)
            }
            .frame(minWidth: 180, idealWidth: 220, maxWidth: 300, maxHeight: .infinity)

            VStack(spacing: 0) {
                SetHeader(doc: doc, showAdd: $showAdd)
                if editingSummary?.isExample ?? false { ExampleNotice() }
                Divider()
                if let doc, !doc.fixtures.isEmpty {
                    List(selection: $selection) {
                        ForEach(groups(doc), id: \.key) { g in
                            SwiftUI.Section {
                                ForEach(g.fixtures) { f in
                                    FixtureRow(fixture: f, doc: doc, lit: lit.contains(f.id),
                                               test: f.address == nil ? "No start address yet: give it one first"
                                                   : testRefusal(g.definition)) { toggleTest(f.id) }
                                }
                            } header: {
                                GroupHeader(group: g) { mapChannels(g.fixtures.first { $0.address != nil } ?? g.fixtures.first) }
                            }
                        }
                    }
                    .contextMenu(forSelectionType: String.self) { ids in
                        Button("Identify on the Lights", systemImage: "lightbulb.max") { identify(ids) }
                            .disabled(editingSummary?.isVirtual ?? true || model.engineRunning)
                        Button("Map DMX Channels…", systemImage: "slider.vertical.3") {
                            mapChannels(doc.fixtures.first { ids.contains($0.id) })
                        }
                        .disabled(ids.isEmpty || model.engineRunning)
                        Divider()
                        Button("Remove from the Set", systemImage: "trash", role: .destructive) { remove(ids) }
                            .disabled(model.engineRunning)
                    }
                } else {
                    ContentUnavailableView {
                        Label("No Fixtures Yet", systemImage: "light.overhead.right")
                    } description: {
                        Text("Add the fixtures you own: search by brand or model across our library, QLC+, the Open Fixture Library and DMXControl.")
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
        .sheet(item: $mapTarget) { t in
            MapperSheet(target: t, tryRefusal: t.address == nil ? "Give \(t.fixture) a start address to try values on it" : tryRefusal) {
                names[t.key] = model.workspace?.definition(t.key)
                load()
                flash("Mapped \(names[t.key]?.name ?? t.key) (\(t.mode)): every one in your sets plays by it")
            }
            .environment(model)
        }
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
        .onDisappear { switchOffTests() }
        .onChange(of: model.editingSet) { old, _ in switchOffTests(set: old); selection = []; load() }
        .onChange(of: model.engineRunning) { if model.engineRunning { switchOffTests() } }
        .onChange(of: model.configVersion) { load() }  // also a change made elsewhere (amadeus mcp, the web page)
        .onChange(of: selection) { stage.highlight = Set(selection.flatMap { id in elementIDs(id) }) }
    }

    struct Group {
        var key: String
        var definition: FixtureDefinition?
        var fixtures: [PlacedFixture]
    }

    private func groups(_ doc: RigDocument) -> [Group] {
        var order: [String] = [], by: [String: [PlacedFixture]] = [:]
        for f in doc.fixtures.sorted(by: { ($0.universe, $0.address ?? 513) < ($1.universe, $1.address ?? 513) }) {
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

    private func flash(_ text: String, seconds: Double = 3) {
        message = text
        Task { try? await Task.sleep(for: .seconds(seconds)); if message == text { message = nil } }
    }

    private func identify(_ ids: Set<String>) {
        let rig = model.selectedRig, set = model.editingSet  // (identify only needs the set's patch and output)
        Task {
            guard await model.ensureSetupService() else { error = "The engine's setup service did not start."; return }
            for id in ids { try? await model.api.identify(fixture: id, rig: rig, set: set) }
            flash("Lit \(ids.count == 1 ? ids.first! : "\(ids.count) fixtures") for 2 s")
        }
    }

    /// The DMX mapper for this fixture's model and mode (tried on this fixture).
    private func mapChannels(_ f: PlacedFixture?) {
        guard let f else { return }
        switchOffTests()
        mapTarget = MapTarget(key: f.key, mode: f.mode, fixture: f.id, address: f.address, universe: f.universe)
    }

    /// Why nothing can be lit on the real rig now (nil: it can).
    private var tryRefusal: String? {
        if editingSummary?.isVirtual ?? true { return "This set only feeds the visualiser: give it a DMX output to test the real lights" }
        if model.engineRunning { return "Stop the show to test the lights" }
        return nil
    }

    /// Why the light test can't light this model here (nil: it can).
    private func testRefusal(_ d: FixtureDefinition?) -> String? {
        if let r = tryRefusal { return r }
        if let d, !d.inert.isEmpty { return "Not tested: \(d.inert)" }
        if d?.kind == "smoke" { return "Smoke machines fire only in the show or the hardware test" }
        return nil
    }

    /// The light test: the fixture on (the rest of the set dark) until switched off again, to see that it is
    /// patched and connected. The engine switches it off by itself after a minute.
    private func toggleTest(_ id: String) {
        let on = !lit.contains(id), rig = model.selectedRig, set = model.editingSet
        if on { lit.insert(id) } else { lit.remove(id) }
        testOff[id]?.cancel()
        Task {
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                let r = try await model.api.testLight(fixture: id, on: on, rig: rig, set: set)
                if on {
                    flash("\(id) on: \(r.summary)", seconds: 8)
                    testOff[id] = Task {
                        try? await Task.sleep(for: .seconds(r.seconds))
                        if !Task.isCancelled { lit.remove(id) }
                    }
                }
            } catch {
                lit.remove(id)
                self.error = error.localizedDescription
            }
        }
    }

    private func switchOffTests(set: String? = nil) {
        guard !lit.isEmpty else { return }
        let ids = lit, rig = model.selectedRig, set = set ?? model.editingSet
        lit = []
        testOff.values.forEach { $0.cancel() }
        testOff = [:]
        Task { for id in ids { _ = try? await model.api.testLight(fixture: id, on: false, rig: rig, set: set) } }
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
    @State private var confirmExample = false
    @State private var error: String?

    var body: some View {
        let set = model.sets.first { $0.name == model.editingSet }
        let example = set?.isExample ?? false
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
                Text(example ? "example" : "your fixtures").foregroundStyle(.secondary)
                Spacer()
                if example {
                    Button("Add Fixtures…", systemImage: "plus") { confirmExample = true }
                        .disabled(model.engineRunning)
                } else {
                    Button("Add Fixtures…", systemImage: "plus") { showAdd = true }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.engineRunning)
                }
            }
            HStack(spacing: 18) {
                Metric(value: "\(doc?.fixtures.count ?? 0)", label: "fixtures")
                Metric(value: "\(Set(doc?.fixtures.map(\.key) ?? []).count)", label: "models")
                Metric(value: "\(Set(doc?.fixtures.map(\.universe) ?? []).count)", label: "universes")
                if let n = doc?.fixtures.filter({ $0.address == nil }).count, n > 0 {
                    Metric(value: "\(n)", label: "without address")
                        .foregroundStyle(.orange)
                        .help("Fixtures without a start address play in the visualiser only: select one and give it the address set on the fixture")
                }
                Button { model.section = .dmx } label: {
                    Metric(value: set?.isVirtual ?? true ? "Visualiser" : (set?.outputText ?? "–"), label: "DMX output ›")
                }
                .buttonStyle(.plain)
                .help("Where the set's universes go: the DMX Output page (⇧⌘D)")
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
        .confirmationDialog("Add fixtures to the example “\(model.editingSet)”?", isPresented: $confirmExample, titleVisibility: .visible) {
            Button("New Set…") { openWindow(id: "wizard") }
            Button("Add to the Example") { showAdd = true }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The examples are there to look around in. Your own fixtures belong in a set of your own.")
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

private struct SetRow: View {
    let set: SetSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(set.name).font(.headline)
            Text("\(set.fixtureCount) fixtures · \(set.isVirtual ? "visualiser only" : set.outputText)")
                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
        .tag(Optional(set.name))
    }
}

/// Over an example set: it is not yours, and where yours go.
private struct ExampleNotice: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "info.circle.fill").font(.title2).foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 2) {
                Text("This is an example set").font(.headline)
                Text("Look around and try the show with it. For the fixtures you own, make a set of your own.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            Button("New Set…", systemImage: "plus") { openWindow(id: "wizard") }
                .buttonStyle(.borderedProminent)
                .disabled(model.engineRunning)
        }
        .padding(12)
        .background(.tint.opacity(0.12), in: .rect(cornerRadius: 10))
        .padding(.horizontal, 16).padding(.bottom, 12)
    }
}

private struct GroupHeader: View {
    @Environment(AppModel.self) private var model
    let group: SetView.Group
    let map: () -> Void

    var body: some View {
        let d = group.definition
        HStack {
            Image(systemName: FixtureIcon.symbol(d?.kind)).foregroundStyle(.tint)
            Text("\(group.fixtures.count)× \(d?.name ?? group.key)").font(.headline)
            if let f = group.fixtures.first {
                Text("\(f.mode) · \(d?.channels(f.mode) ?? 0) ch").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if let d, let f = group.fixtures.first, d.inert.isEmpty, d.kind != "smoke" {
                let dark = !d.plays(f.mode)
                if dark {
                    Label("Plays nothing", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption).foregroundStyle(.orange)
                        .help("The show finds no dimmer or colour channel in this mode: map its channels by hand")
                } else if d.needsCheck {
                    Label("Not checked yet", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption).foregroundStyle(.orange)
                        .help("Made from a common layout: check its channels one by one on the fixture")
                }
                Button(dark ? "Map Channels…" : d.needsCheck ? "Check Channels…" : "Channels…", systemImage: "slider.vertical.3", action: map)
                    .controlSize(.small)
                    .buttonStyle(.bordered)
                    .tint(dark || d.needsCheck ? .orange : nil)
                    .disabled(model.engineRunning)
                    .help("The DMX mapper: what each channel does, by hand, with the values tried on the real fixture")
            }
        }
        .padding(.vertical, 2)
    }
}

private struct FixtureRow: View {
    let fixture: PlacedFixture
    let doc: RigDocument
    let lit: Bool
    let test: String?   // why it can't be tested now (nil: it can)
    let toggle: () -> Void

    var body: some View {
        HStack {
            Text(fixture.id).font(.body.monospaced())
                .frame(width: 110, alignment: .leading)
            Group {
                if fixture.address != nil {
                    Text(fixture.patchText).monospacedDigit().foregroundStyle(.secondary)
                } else {
                    Text("no address").foregroundStyle(.orange)
                }
            }
            .frame(width: 80, alignment: .leading)
            .help(fixture.address == nil ? "No start address yet: select it and give it one (the visualiser only until then)"
                  : "Universe.address: set this start address on the fixture's display")
            Text(fixture.mode).font(.callout).foregroundStyle(.secondary)
            Spacer()
            Button(lit ? "On" : "Test", systemImage: lit ? "lightbulb.fill" : "lightbulb") { toggle() }
                .labelStyle(.titleAndIcon)
                .buttonStyle(.bordered)
                .controlSize(.small)
                .tint(lit ? .yellow : nil)
                .disabled(test != nil && !lit)
                .help(test ?? (lit ? "Switch it off again"
                               : "Light it on the real rig until you switch it off (a minute at most): is it patched and connected?"))
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
        case "smoke": "cloud.fog"
        default: "light.recessed"
        }
    }
}
