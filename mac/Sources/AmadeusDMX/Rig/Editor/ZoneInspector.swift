// The selected zone: kind, shape, size, angles and margin.
import AmadeusKit
import SwiftUI

struct ZoneInspector: View {
    let editor: RigEditorModel
    let zone: Zone

    static func kindName(_ k: String) -> String {
        switch k {
        case "keep_in": "Keep beams in"
        case "laser_out": "Laser safety"
        default: "Keep beams out"
        }
    }
    static func color(_ z: Zone) -> Color { z.kind == "laser_out" ? .red : z.kind == "keep_in" ? .green : .blue }
    static func symbol(_ z: Zone) -> String {
        z.kind == "laser_out" ? "exclamationmark.triangle.fill" : z.shape == "box" ? "cube.transparent" : "rectangle.dashed"
    }

    var body: some View {
        SwiftUI.Section {
            HStack {
                Image(systemName: Self.symbol(zone)).font(.title2).foregroundStyle(Self.color(zone))
                TextField("Name", text: Binding(get: { zone.name }, set: { v in editor.updateZone(zone.id, "Rename Zone") { $0.name = v } }))
                    .textFieldStyle(.plain).font(.headline)
            }
            Toggle("Active", isOn: Binding(get: { zone.enabled }, set: { v in editor.updateZone(zone.id) { $0.enabled = v } }))
        }
        SwiftUI.Section("What It Does") {
            Picker("Kind", selection: Binding(get: { zone.kind }, set: { v in editor.updateZone(zone.id, "Change Zone Kind") { z in
                z.kind = v
                z.marginDeg = v == "laser_out" ? max(z.marginDeg, 5) : z.marginDeg
            } })) {
                Text("Keep beams out").tag("avoid")
                Text("Keep beams in").tag("keep_in")
                Text("Laser safety").tag("laser_out")
            }
            Text(explanation).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            ValueSlider(title: "Margin", value: Binding(get: { zone.marginDeg }, set: { v in editor.updateZone(zone.id) { $0.marginDeg = v } }),
                        range: zone.kind == "laser_out" ? 3...20 : 0...15, step: 1, unit: "°")
            if zone.kind != "laser_out" {
                Picker("Applies to", selection: Binding(get: { zone.applies }, set: { v in editor.updateZone(zone.id) { $0.applies = v } })) {
                    Text("Moving heads").tag("auto")
                    Text("All motorised fixtures").tag("all")
                }
            }
        }
        SwiftUI.Section("Shape and Place") {
            Picker("Shape", selection: Binding(get: { zone.shape }, set: { v in editor.updateZone(zone.id, "Change Zone Shape") { z in
                z.shape = v
                if v == "box" && z.size.count < 3 { z.size = [z.size[0], 2, z.size.count > 1 ? z.size[1] : 2] }
            } })) {
                Text("Rectangle").tag("rect")
                Text("Box").tag("box")
            }
            .pickerStyle(.segmented)
            ValueSlider(title: "Width", value: size(0), range: 0.25...40, step: 0.25)
            ValueSlider(title: zone.shape == "box" ? "Depth" : "Height", value: size(1), range: 0.25...40, step: 0.25)
            if zone.shape == "box" { ValueSlider(title: "Height", value: size(2), range: 0.25...15, step: 0.25) }
            ValueSlider(title: "Across (x)", value: center(0), range: -10...(editor.doc.width + 10), step: 0.25)
            ValueSlider(title: "Depth (y)", value: center(1), range: -16...max(4, editor.doc.stage.roomDepthM + 2), step: 0.25)
            ValueSlider(title: "Height (z)", value: center(2), range: 0...max(3, editor.doc.stage.ceilingM), step: 0.1)
            ValueSlider(title: "Rotation", value: Binding(get: { zone.rotDeg }, set: { v in editor.updateZone(zone.id) { $0.rotDeg = v } }),
                        range: -180...180, step: 5, unit: "°")
            if zone.shape == "rect" {
                ValueSlider(title: "Tilt", value: Binding(get: { zone.tiltDeg }, set: { v in editor.updateZone(zone.id) { $0.tiltDeg = v } }),
                            range: 0...90, step: 5, unit: "°")
            }
        }
        if zone.kind == "laser_out" {
            SwiftUI.Section {
                Label("A software guard, not a safety system. Set the laser’s masking plate, mounting height and scan "
                      + "safety first; keep an E-stop at hand.", systemImage: "exclamationmark.shield")
                    .font(.caption).foregroundStyle(.orange)
            }
        }
        SwiftUI.Section {
            Button("Duplicate", systemImage: "plus.square.on.square") { editor.duplicateSelection() }
            Button("Delete Zone", systemImage: "trash", role: .destructive) { editor.deleteSelection() }
        }
    }

    private var explanation: String {
        switch zone.kind {
        case "keep_in": "Moving-head beams land only inside this area; outside it they slide back to its edge."
        case "laser_out": "No laser beam may come into this zone (with the margin). The show lifts or shrinks the "
            + "pattern; if that isn’t enough, the laser goes dark."
        default: "Moving-head beams stay off this surface: they slide to its edge, and go dark while crossing it."
        }
    }

    private func size(_ k: Int) -> Binding<Double> {
        Binding(get: { k < zone.size.count ? zone.size[k] : 1 }, set: { v in editor.updateZone(zone.id, "Resize Zone") { z in
            while z.size.count <= k { z.size.append(1) }
            z.size[k] = v
        } })
    }

    private func center(_ k: Int) -> Binding<Double> {
        Binding(get: { zone.center[k] }, set: { v in editor.updateZone(zone.id, "Move Zone") { $0.center[k] = v } })
    }
}
