// The editor's inspector: with nothing selected, the set on this rig (what hangs where, and what still waits,
// in groups to drag onto the stage) and the venue; else the selected truss, fixture(s) or zone.
import AmadeusKit
import SwiftUI

struct EditorInspector: View {
    @Environment(AppModel.self) private var model
    @Bindable var editor: RigEditorModel
    @Binding var showAdd: Bool

    var body: some View {
        Form {
            if editor.selectedFixtures.count > 1 {
                MultiFixtureInspector(editor: editor, ids: editor.selectedFixtures)
            } else {
                switch editor.selection {
                case .truss(let id):
                    if let t = editor.doc.trusses.first(where: { $0.id == id }) { TrussInspector(editor: editor, truss: t) }
                case .fixture(let id):
                    if let f = editor.doc.fixtures.first(where: { $0.id == id }) { FixtureInspector(editor: editor, fixture: f) }
                case .zone(let id):
                    if let z = editor.doc.zones.first(where: { $0.id == id }) { ZoneInspector(editor: editor, zone: z) }
                case nil:
                    overview
                }
            }
        }
        .formStyle(.grouped)
    }

    @ViewBuilder
    private var overview: some View {
        let fixtures = editor.doc.fixtures
        let waiting = editor.doc.waitingCount
        if editor.setName.isEmpty {  // the rig alone
            SwiftUI.Section {
                Label("The rig alone: its structure. Choose a set under “Showing” to arrange its fixtures here.",
                      systemImage: "building.2")
                    .font(.callout).foregroundStyle(.secondary)
                if editor.isDirty { Label("Unsaved changes", systemImage: "circle.fill").foregroundStyle(.orange).font(.callout) }
            }
        } else {
        SwiftUI.Section {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: "light.overhead.right").foregroundStyle(.tint)
                    Text("Set “\(editor.setName)”").font(.headline)
                    Spacer()
                    Button("Fixtures…") { model.editingSet = editor.setName; model.section = .set }.buttonStyle(.link).font(.caption)
                }
                if !fixtures.isEmpty {
                    ProgressView(value: Double(fixtures.count - waiting), total: Double(fixtures.count))
                        .tint(waiting == 0 ? .green : .orange)
                    Text(waiting == 0 ? "All \(fixtures.count) fixtures hang on this rig."
                         : "\(fixtures.count - waiting) of \(fixtures.count) mounted. \(waiting) wait in front of the stage.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                if waiting > 0 {
                    Button {
                        Task { await editor.autoMount(model) }
                    } label: {
                        Label("Auto-Mount the \(waiting) Waiting", systemImage: "wand.and.stars").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(editor.busy)
                }
                if editor.isDirty { Label("Unsaved changes", systemImage: "circle.fill").foregroundStyle(.orange).font(.callout) }
            }
        } footer: {
            if !fixtures.isEmpty {
                Text("Drag a group or a fixture onto a truss in the stage: a group hangs in a row. Click a group to select it all.")
            }
        }
        SwiftUI.Section("Fixtures by Model") {
            if fixtures.isEmpty {
                Text("The set has no fixtures yet.").foregroundStyle(.secondary)
                Button("Add Fixtures to the Set…") { model.editingSet = editor.setName; model.section = .set }
            }
            ForEach(modelGroups(fixtures), id: \.key) { g in
                ModelGroupRow(editor: editor, key: g.key, fixtures: g.fixtures)
            }
        }
        }
        SwiftUI.Section("Venue") {
            ValueSlider(title: "Stage width", value: stageBinding(\.widthM), range: 2...30, step: 0.5)
            Toggle("Outdoor", isOn: Binding(get: { editor.doc.stage.outdoor }, set: { v in editor.updateStage { $0.outdoor = v } }))
                .help("An open-air stage: no ceiling, so the director uses the sky far more (beams up into the night). Indoors the ceiling is kept clear.")
            if !editor.doc.stage.outdoor {
                ValueSlider(title: "Ceiling", value: stageBinding(\.ceilingM), range: 2.5...20, step: 0.5)
            }
            ValueSlider(title: "Room depth", value: stageBinding(\.roomDepthM), range: 3...60, step: 1)
            ValueSlider(title: "Stage height", value: Binding(get: { editor.doc.stage.deckM }, set: { editor.setStageHeight($0) }),
                        range: 0...3, step: 0.1)
                .help("How high the stage stands above the hall floor: heights count from the hall floor, so the stage's grid is its height plus the height above the stage")
            Toggle("LED wall behind the DJ", isOn: Binding(get: { editor.doc.hasScreen }, set: { editor.setScreen($0) }))
            if !editor.doc.stage.outdoor {
                Toggle("Beams stay off the ceiling", isOn: Binding(get: { editor.doc.stage.ceilingGuard },
                                                                   set: { v in editor.updateStage { $0.ceilingGuard = v } }))
                    .help("Moving heads only go up so far that their beam reaches the ceiling at least the room's depth away")
            }
            Toggle("Beams never shine back at the DJ", isOn: Binding(get: { editor.doc.stage.backGuard },
                                                                     set: { v in editor.updateStage { $0.backGuard = v } }))
                .help("Moving heads never swing back past the rig towards the stage (pointing steeply down is fine)")
        }
        SwiftUI.Section("Trusses") {
            if editor.doc.trusses.isEmpty {
                Text("No trusses: fixtures stand on the floor. Add one with Truss; fixtures snap onto it.").foregroundStyle(.secondary)
            }
            ForEach(editor.doc.trusses) { t in
                Button { editor.selection = .truss(t.id) } label: {
                    HStack {
                        Image(systemName: t.vertical ? "building.columns" : t.isRing ? "circle" : "square.split.bottomrightquarter")
                        Text(t.id)
                        Spacer()
                        Text("\(t.isRing ? ringName(t) : "\(t.lengthM.formatted()) m") · \(fixtures.filter { $0.truss == t.id }.count) fixtures")
                            .foregroundStyle(.secondary).font(.caption)
                    }
                }
                .buttonStyle(.plain)
            }
        }
        SwiftUI.Section("Zones") {
            if editor.doc.zones.isEmpty {
                Text("No zones. Use Zone to keep beams off walls and the set, or lasers out of the audience.")
                    .foregroundStyle(.secondary)
            }
            ForEach(editor.doc.zones) { z in
                Button { editor.selection = .zone(z.id) } label: {
                    HStack {
                        Image(systemName: ZoneInspector.symbol(z)).foregroundStyle(ZoneInspector.color(z))
                        Text(z.name)
                        Spacer()
                        Text(ZoneInspector.kindName(z.kind)).foregroundStyle(.secondary).font(.caption)
                    }
                    .opacity(z.enabled ? 1 : 0.5)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func modelGroups(_ fixtures: [PlacedFixture]) -> [(key: String, fixtures: [PlacedFixture])] {
        var order: [String] = [], by: [String: [PlacedFixture]] = [:]
        for f in fixtures {
            if by[f.key] == nil { order.append(f.key) }
            by[f.key, default: []].append(f)
        }
        return order.map { ($0, by[$0]!) }
    }

    private func stageBinding(_ kp: WritableKeyPath<Stage, Double>) -> Binding<Double> {
        Binding(get: { editor.doc.stage[keyPath: kp] }, set: { v in editor.updateStage { $0[keyPath: kp] = v } })
    }
}

/// One model of the set: how many, mounted or waiting; drag it (the waiting ones, else all) onto the stage.
private struct ModelGroupRow: View {
    let editor: RigEditorModel
    let key: String
    let fixtures: [PlacedFixture]
    @State private var open = false

    var body: some View {
        let def = editor.definition(key)
        let waiting = fixtures.filter(\.waiting)
        let dragIDs = (waiting.isEmpty ? fixtures : waiting).map(\.id)
        DisclosureGroup(isExpanded: $open) {
            ForEach(fixtures) { f in
                HStack {
                    Image(systemName: "line.3.horizontal").foregroundStyle(.tertiary).font(.caption)
                    Text(f.id).font(.callout.monospaced())
                    Spacer()
                    Text(f.waiting ? "waiting" : f.truss.map { "\($0) · \(f.side ?? "")" } ?? f.mount)
                        .font(.caption).foregroundStyle(f.waiting ? Color.orange : Color.secondary)
                }
                .contentShape(.rect)
                .onTapGesture { editor.select(fixtures: [f.id]) }
                .draggable(RigEditorModel.payload([f.id]))
            }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: FixtureIcon.symbol(def?.kind)).foregroundStyle(.tint).frame(width: 20)
                VStack(alignment: .leading, spacing: 1) {
                    Text("\(fixtures.count)× \(def?.name ?? key)").lineLimit(1)
                    Text(waiting.isEmpty ? "all mounted" : "\(waiting.count) waiting")
                        .font(.caption).foregroundStyle(waiting.isEmpty ? Color.secondary : Color.orange)
                }
                Spacer()
                Image(systemName: "hand.draw").foregroundStyle(.tertiary)
                    .help("Drag onto a truss: they hang in a row")
            }
            .contentShape(.rect)
            .onTapGesture { editor.select(fixtures: fixtures.map(\.id)) }
            .draggable(RigEditorModel.payload(dragIDs)) {
                Label("\(dragIDs.count)× \(def?.model ?? key)", systemImage: FixtureIcon.symbol(def?.kind))
                    .padding(8).background(.regularMaterial, in: .capsule)
            }
        }
    }
}

/// Several fixtures selected: what they have in common, and what can be done to all of them.
private struct MultiFixtureInspector: View {
    @Environment(AppModel.self) private var model
    let editor: RigEditorModel
    let ids: Set<String>

    var body: some View {
        let fixtures = editor.doc.fixtures.filter { ids.contains($0.id) }
        let models = Set(fixtures.map(\.key))
        let onBoxTruss = fixtures.allSatisfy { f in f.truss.flatMap { t in editor.doc.trusses.first { $0.id == t } }.map { !$0.vertical } ?? false }
        let onTower = fixtures.allSatisfy { f in f.truss.flatMap { t in editor.doc.trusses.first { $0.id == t } }.map(\.vertical) ?? false }
        SwiftUI.Section {
            HStack {
                Image(systemName: "square.stack.3d.up").font(.title2).foregroundStyle(.tint)
                VStack(alignment: .leading) {
                    Text("\(fixtures.count) Fixtures").font(.headline)
                    Text(models.count == 1 ? (editor.definition(models.first!)?.name ?? models.first!) : "\(models.count) models")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Text(fixtures.map(\.id).sorted().joined(separator: ", ")).font(.caption.monospaced()).foregroundStyle(.secondary)
        } footer: {
            Text("Drag one of them in the stage and the others come along: onto a truss they hang in a row.")
        }
        if onBoxTruss {
            let onRing = fixtures.allSatisfy { f in f.truss.flatMap { t in editor.doc.trusses.first { $0.id == t } }?.isRing ?? false }
            SwiftUI.Section("Position on the Truss") {
                Picker("Side", selection: Binding(get: { Set(fixtures.compactMap(\.side)).count == 1 ? fixtures.first?.side ?? "under" : "" },
                                                  set: { editor.setSide(ids, $0) })) {
                    Text("Under").tag("under"); Text(onRing ? "Outside" : "Front").tag("front"); Text("Top").tag("top")
                    Text(onRing ? "Inside" : "Back").tag("back")
                }
                .pickerStyle(.segmented)
            }
        } else if onTower {
            SwiftUI.Section("Position on the Tower") {
                Picker("Face", selection: Binding(get: { Set(fixtures.compactMap(\.side)).count == 1 ? fixtures.first?.side ?? "front" : "" },
                                                  set: { editor.setSide(ids, $0) })) {
                    Text("Front").tag("front"); Text("Left").tag("left"); Text("Right").tag("right"); Text("Back").tag("back")
                    Text("Top").tag("top")
                }
                .pickerStyle(.segmented)
            }
        }
        SwiftUI.Section {
            Button("Auto-Mount These", systemImage: "wand.and.stars") { Task { await editor.autoMount(model, ids: Array(ids)) } }
            Button("Rotate 90°", systemImage: "rotate.right") { editor.rotateSelection(by: 90) }
            Button("Unmount (Back to Waiting)", systemImage: "arrow.down.to.line") { editor.unmount(ids) }
        }
    }
}

private func metres(_ v: Double) -> String { String(format: "%.2f m", v) }

/// "Ø 4 m circle" / "Ø 6 m half circle".
func ringName(_ t: Truss) -> String {
    let d = (t.diameterM ?? 4).formatted()
    return t.isFullRing ? "Ø \(d) m circle" : t.arc == 180 ? "Ø \(d) m half circle" : "Ø \(d) m, \(Int(t.arc))° arc"
}

struct TrussInspector: View {
    let editor: RigEditorModel
    let truss: Truss

    var body: some View {
        let id = truss.id
        SwiftUI.Section {
            HStack {
                Image(systemName: truss.vertical ? "building.columns" : truss.isRing ? "circle" : "square.split.bottomrightquarter")
                    .font(.title2).foregroundStyle(.tint)
                VStack(alignment: .leading) {
                    Text(truss.id).font(.headline)
                    Text(truss.vertical ? "Tower, box truss 30 cm" : truss.isRing ? "Round truss, \(ringName(truss))"
                         : "Box truss (quatro), 30 cm").font(.caption).foregroundStyle(.secondary)
                }
            }
            if truss.isRing {
                Text("Heads on a ring play it as a circle: crowns of beams out of it, cones, twisters, waves running round.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        SwiftUI.Section("Size and Place") {
            if truss.isRing {
                Picker("Diameter", selection: Binding(get: { truss.diameterM ?? 4 }, set: { v in
                    editor.updateTruss(truss.id, "Change Diameter") { $0.diameterM = v }
                })) {
                    ForEach(Array(Set(Truss.ringDiameters + [truss.diameterM ?? 4])).sorted(), id: \.self) { d in
                        Text("Ø \(d.formatted()) m").tag(d)
                    }
                }
                Stepper(value: Binding(get: { truss.diameterM ?? 4 }, set: { v in
                    editor.updateTruss(truss.id, "Change Diameter") { $0.diameterM = v }
                }), in: 1...20, step: 0.5) {
                    LabeledContent("Round the arc", value: metres(truss.lengthM))
                }
                Picker("Shape", selection: Binding(get: { truss.arc }, set: { v in
                    editor.updateTruss(truss.id, v >= 359.5 ? "Make Full Circle" : "Make Half Circle") { $0.arcDeg = v }
                })) {
                    Text("Full circle").tag(360.0); Text("Half circle").tag(180.0)
                    if !Truss.ringArcs.contains(truss.arc) { Text("\(Int(truss.arc))°").tag(truss.arc) }
                }
                .pickerStyle(.segmented)
            } else {
            Stepper(value: binding(\.lengthM), in: 0.5...20, step: 0.5) {
                LabeledContent("Length", value: metres(truss.lengthM))
            }
            }
            ValueSlider(title: "Across (x)", value: binding(\.xM), range: -6...(editor.doc.width + 6), step: 0.25)
            ValueSlider(title: "Depth (y)", value: binding(\.yM), range: -14...4, step: 0.25)
            if !truss.vertical {
                ValueSlider(title: "Height", value: binding(\.zM), range: 0.5...max(2, editor.doc.stage.ceilingM), step: 0.1)
                ValueSlider(title: "Rotation", value: binding(\.rotDeg), range: -180...180, step: 15, unit: "°")
            }
        }
        if !truss.vertical {
            SwiftUI.Section("Lights") {
                Picker("Aim", selection: Binding(get: { truss.aim ?? "" }, set: { v in
                    editor.updateTruss(truss.id, "Change Aim") { $0.aim = v.isEmpty ? nil : v }
                })) {
                    Text(truss.yM >= Truss.overCrowdM ? "Automatic (down)" : "Automatic").tag("")
                    Text("Towards the audience").tag("audience")
                    Text("Down").tag("down")
                }
                .help("Where the heads on this truss play. Automatic: down when it hangs over the crowd, else wherever the show aims")
                Text(aimNote).font(.caption).foregroundStyle(.secondary)
            }
        }
        SwiftUI.Section {
            LabeledContent("Fixtures on it", value: "\(editor.doc.fixtures.filter { $0.truss == id }.count)")
            Button("Duplicate", systemImage: "plus.square.on.square") { editor.duplicateSelection() }
            Button("Delete Truss", systemImage: "trash", role: .destructive) { editor.deleteSelection() }
        }
    }

    private var aimNote: String {
        switch truss.lightAim {
        case "down": "The heads play down onto the crowd under it (they still go up for a build)."
        case "audience": "The heads play out towards the audience, never back at the stage."
        default: "The heads play wherever the show aims: the crowd, the stage or the sky."
        }
    }

    private func binding(_ kp: WritableKeyPath<Truss, Double>) -> Binding<Double> {
        Binding(get: { truss[keyPath: kp] }, set: { v in editor.updateTruss(truss.id) { $0[keyPath: kp] = v } })
    }
}

struct FixtureInspector: View {
    @Environment(AppModel.self) private var model
    let editor: RigEditorModel
    let fixture: PlacedFixture

    var body: some View {
        let def = editor.definition(fixture.key)
        let truss = editor.doc.trusses.first { $0.id == fixture.truss }
        SwiftUI.Section {
            HStack {
                Image(systemName: icon(def?.kind)).font(.title2).foregroundStyle(.tint)
                VStack(alignment: .leading) {
                    Text(fixture.id).font(.headline)
                    Text(def?.name ?? fixture.key).font(.caption).foregroundStyle(.secondary)
                }
            }
            LabeledContent("Patch", value: "\(fixture.patchText) · \(fixture.mode)")
            let refusal = editor.testRefusal(model, fixture), on = editor.lit.contains(fixture.id)
            Button(on ? "On: Click to Switch Off" : "Test on the Lights", systemImage: on ? "lightbulb.fill" : "lightbulb") {
                Task { await editor.toggleTest(model, fixture.id) }
            }
            .buttonStyle(.bordered)
            .tint(on ? .yellow : nil)
            .disabled(refusal != nil && !on)
            .help(refusal ?? (on ? "Switch it off again"
                              : "Light it on the real rig until you switch it off (a minute at most), a head aimed as here: is it patched, connected and hung the way it is placed?"))
            if let refusal {
                Text(refusal).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            if on && def?.isMoving == true {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Its beam should point at the audience, as on the stage here. Where does the real one point?")
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Left", systemImage: "arrow.left") { fix("left") }
                        Button("Right", systemImage: "arrow.right") { fix("right") }
                        Button("Back", systemImage: "arrow.uturn.down") { fix("back") }
                    }
                    .controlSize(.small)
                    .help("Left and right as seen from the audience, facing the stage. The head's calibration is put right in the set and it is aimed again: pressed the wrong one, it ends up the other way; press that one")
                }
            }
        }
        SwiftUI.Section("Mounting") {
            Picker("Truss", selection: Binding(get: { fixture.truss ?? "" }, set: { editor.attach(fixture.id, to: $0.isEmpty ? nil : $0) })) {
                Text("None (floor / stand)").tag("")
                ForEach(editor.doc.trusses) { t in Text(t.id).tag(t.id) }
            }
            if let t = truss, !t.vertical {
                Picker("Position", selection: Binding(get: { fixture.side ?? (fixture.mount == "stand" ? "top" : "under") },
                                                      set: { editor.setSide(fixture.id, $0) })) {
                    Text("Under 0°").tag("under"); Text(t.isRing ? "Outside 90°" : "Front 90°").tag("front"); Text("Top 180°").tag("top")
                    Text(t.isRing ? "Inside 270°" : "Back 270°").tag("back")
                }
                .pickerStyle(.segmented)
            } else if let t = truss, t.vertical {
                Picker("Face", selection: Binding(get: { fixture.side ?? "front" }, set: { editor.setSide(fixture.id, $0) })) {
                    Text("Front").tag("front"); Text("Left").tag("left"); Text("Right").tag("right"); Text("Back").tag("back")
                    Text("Top").tag("top")
                }
                .pickerStyle(.segmented)
                Text(fixture.side == "top" ? "Standing on top of the tower." : "Hanging off the tower's face, the head pointing out.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
            Picker("Mount", selection: Binding(get: { fixture.mount }, set: { m in
                let stage = editor.doc.stage
                editor.updateFixture(fixture.id, "Change Mount") { f in
                    f.mount = m
                    if m == "floor" && f.truss == nil { f.zM = 0.25 + stage.ground(x: f.x, yM: f.yM) }
                }
            })) {
                Text(truss == nil ? "Hanging" : "Under").tag("hang")
                Text(truss == nil ? "Stand" : "On top").tag("stand")
                if truss == nil { Text("Floor").tag("floor") }
            }
            .pickerStyle(.segmented)
            }
            if let t = truss {
                ValueSlider(title: t.vertical ? "Height on tower" : "Along the truss",
                            value: binding(\.trussPos, default: 0),
                            range: t.vertical ? 0.2...t.lengthM : -t.lengthM / 2...t.lengthM / 2, step: 0.05)
            } else {
                ValueSlider(title: "Across (x)", value: Binding(get: { fixture.x * editor.doc.width }, set: { v in
                    editor.updateFixture(fixture.id, "Move Fixture") { $0.x = v / editor.doc.width }
                }), range: -6...(editor.doc.width + 6), step: 0.05)
                ValueSlider(title: "Depth (y)", value: binding(\.yM), range: -14...4, step: 0.05)
                ValueSlider(title: "Height", value: binding(\.zM), range: 0...max(2, editor.doc.stage.ceilingM), step: 0.05)
            }
        }
        SwiftUI.Section("Orientation") {
            ValueSlider(title: "Rotation", value: binding(\.rotDeg), range: -180...180, step: 5, unit: "°")
            if !(def?.isMoving ?? true) {
                let aim = fixture.aim ?? defaultAim(def?.elementKind)
                ValueSlider(title: "Aim up/down", value: Binding(get: { aim.y }, set: { v in
                    editor.updateFixture(fixture.id, "Aim") { $0.aim = SIMD2(aim.x, v) }
                }), range: -90...90, step: 5, unit: "°")
                ValueSlider(title: "Aim left/right", value: Binding(get: { aim.x }, set: { v in
                    editor.updateFixture(fixture.id, "Aim") { $0.aim = SIMD2(v, aim.y) }
                }), range: -180...180, step: 5, unit: "°")
                if def?.elementKind == .laser {
                    Text("Where the laser points when its pattern is centred: measure it on the real laser. The laser "
                         + "guard uses it to keep beams out of the laser safety zones.")
                        .font(.caption).foregroundStyle(.orange)
                }
            } else {
                Text("Moving fixtures aim themselves; the rotation tells the engine where their front is.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        SwiftUI.Section {
            if fixture.waiting {
                Label("Waiting in front of the stage: drag it onto a truss, or Auto-Mount.", systemImage: "hourglass")
                    .font(.callout).foregroundStyle(.orange)
            } else {
                Button("Unmount (Back to Waiting)", systemImage: "arrow.down.to.line") { editor.unmount([fixture.id]) }
            }
        } footer: {
            Text("The fixture stays in the set; to remove it from your gear, use the Set page.")
        }
    }

    private func defaultAim(_ k: FixtureKind?) -> SIMD2<Double> {
        switch k {
        case .laser: [0, 13]
        case .blinder: [0, 7]
        case .strobe: [0, 8]
        case .smoke: [0, 10]
        default: [0, 80]
        }
    }

    private func binding(_ kp: WritableKeyPath<PlacedFixture, Double>) -> Binding<Double> {
        Binding(get: { fixture[keyPath: kp] }, set: { v in editor.updateFixture(fixture.id, "Move Fixture") { $0[keyPath: kp] = v } })
    }

    private func binding(_ kp: WritableKeyPath<PlacedFixture, Double?>, default d: Double) -> Binding<Double> {
        Binding(get: { fixture[keyPath: kp] ?? d }, set: { v in editor.updateFixture(fixture.id, "Move Fixture") { $0[keyPath: kp] = v } })
    }

    private func fix(_ seen: String) { Task { await editor.fixFront(model, fixture.id, seen: seen) } }

    private func icon(_ kind: String?) -> String { FixtureIcon.symbol(kind) }
}

/// A labelled slider with its value; snaps to `step`.
struct ValueSlider: View {
    let title: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var step: Double = 0.1
    var unit = " m"

    var body: some View {
        LabeledContent(title) {
            HStack {
                Slider(value: Binding(get: { min(max(value, range.lowerBound), range.upperBound) },
                                      set: { value = ($0 / step).rounded() * step }), in: range)
                Text(unit == "°" ? "\(Int(value.rounded()))°" : String(format: "%.2f%@", value, unit))
                    .monospacedDigit().foregroundStyle(.secondary).frame(width: 58, alignment: .trailing)
            }
        }
    }
}
