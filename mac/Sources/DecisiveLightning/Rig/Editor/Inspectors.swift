// The editor's inspector: the selected truss or fixture.
import DecisiveKit
import SwiftUI

struct EditorInspector: View {
    @Bindable var editor: RigEditorModel
    @Binding var showAdd: Bool

    var body: some View {
        Form {
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
        .formStyle(.grouped)
    }

    @ViewBuilder
    private var overview: some View {
        SwiftUI.Section {
            LabeledContent("Set", value: editor.setName)
            LabeledContent("Trusses", value: "\(editor.doc.trusses.count)")
            LabeledContent("Fixtures", value: "\(editor.doc.fixtures.count)")
            if editor.isDirty { Label("Unsaved changes", systemImage: "circle.fill").foregroundStyle(.orange).font(.callout) }
        }
        SwiftUI.Section("Trusses") {
            if editor.doc.trusses.isEmpty {
                Text("No trusses yet. Add one with the Truss button; fixtures snap onto it.").foregroundStyle(.secondary)
            }
            ForEach(editor.doc.trusses) { t in
                Button { editor.selection = .truss(t.id) } label: {
                    HStack {
                        Image(systemName: t.vertical ? "building.columns" : "square.split.bottomrightquarter")
                        Text(t.id)
                        Spacer()
                        Text("\(t.lengthM.formatted()) m · \(editor.doc.fixtures.filter { $0.truss == t.id }.count) fixtures")
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
        SwiftUI.Section("Fixtures") {
            ForEach(editor.doc.fixtures) { f in
                Button { editor.selection = .fixture(f.id) } label: {
                    HStack {
                        Text(f.id)
                        Spacer()
                        Text(f.truss.map { "on \($0)" } ?? f.mount).foregroundStyle(.secondary).font(.caption)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }
}

private func metres(_ v: Double) -> String { String(format: "%.2f m", v) }

struct TrussInspector: View {
    let editor: RigEditorModel
    let truss: Truss

    var body: some View {
        let id = truss.id
        SwiftUI.Section {
            HStack {
                Image(systemName: truss.vertical ? "building.columns" : "square.split.bottomrightquarter")
                    .font(.title2).foregroundStyle(.tint)
                VStack(alignment: .leading) {
                    Text(truss.id).font(.headline)
                    Text(truss.vertical ? "Tower, box truss 30 cm" : "Box truss (quatro), 30 cm").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        SwiftUI.Section("Size and Place") {
            Stepper(value: binding(\.lengthM), in: 0.5...20, step: 0.5) {
                LabeledContent("Length", value: metres(truss.lengthM))
            }
            ValueSlider(title: "Across (x)", value: binding(\.xM), range: -6...(editor.doc.width + 6), step: 0.25)
            ValueSlider(title: "Depth (y)", value: binding(\.yM), range: -14...4, step: 0.25)
            if !truss.vertical {
                ValueSlider(title: "Height", value: binding(\.zM), range: 0.5...max(2, editor.doc.stage.ceilingM), step: 0.1)
                ValueSlider(title: "Rotation", value: binding(\.rotDeg), range: -180...180, step: 15, unit: "°")
            }
        }
        SwiftUI.Section {
            LabeledContent("Fixtures on it", value: "\(editor.doc.fixtures.filter { $0.truss == id }.count)")
            Button("Duplicate", systemImage: "plus.square.on.square") { editor.duplicateSelection() }
            Button("Delete Truss", systemImage: "trash", role: .destructive) { editor.deleteSelection() }
        }
    }

    private func binding(_ kp: WritableKeyPath<Truss, Double>) -> Binding<Double> {
        Binding(get: { truss[keyPath: kp] }, set: { v in editor.updateTruss(truss.id) { $0[keyPath: kp] = v } })
    }
}

struct FixtureInspector: View {
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
            LabeledContent("Patch", value: "\(fixture.universe).\(String(format: "%03d", fixture.address)) · \(fixture.mode)")
        }
        SwiftUI.Section("Mounting") {
            Picker("Truss", selection: Binding(get: { fixture.truss ?? "" }, set: { editor.attach(fixture.id, to: $0.isEmpty ? nil : $0) })) {
                Text("None (floor / stand)").tag("")
                ForEach(editor.doc.trusses) { t in Text(t.id).tag(t.id) }
            }
            if let t = truss, !t.vertical {
                Picker("Position", selection: Binding(get: { fixture.side ?? (fixture.mount == "stand" ? "top" : "under") },
                                                      set: { editor.setSide(fixture.id, $0) })) {
                    Text("Under 0°").tag("under"); Text("Front 90°").tag("front"); Text("Top 180°").tag("top"); Text("Back 270°").tag("back")
                }
                .pickerStyle(.segmented)
            } else {
            Picker("Mount", selection: Binding(get: { fixture.mount }, set: { m in
                editor.updateFixture(fixture.id, "Change Mount") { f in
                    f.mount = m
                    if m == "floor" && f.truss == nil { f.zM = 0.25 }
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
            Button("Delete Fixture", systemImage: "trash", role: .destructive) { editor.deleteSelection() }
        }
    }

    private func defaultAim(_ k: FixtureKind?) -> SIMD2<Double> {
        switch k {
        case .laser: [0, 13]
        case .blinder: [0, 7]
        case .strobe: [0, 8]
        default: [0, 80]
        }
    }

    private func binding(_ kp: WritableKeyPath<PlacedFixture, Double>) -> Binding<Double> {
        Binding(get: { fixture[keyPath: kp] }, set: { v in editor.updateFixture(fixture.id, "Move Fixture") { $0[keyPath: kp] = v } })
    }

    private func binding(_ kp: WritableKeyPath<PlacedFixture, Double?>, default d: Double) -> Binding<Double> {
        Binding(get: { fixture[keyPath: kp] ?? d }, set: { v in editor.updateFixture(fixture.id, "Move Fixture") { $0[keyPath: kp] = v } })
    }

    private func icon(_ kind: String?) -> String {
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
