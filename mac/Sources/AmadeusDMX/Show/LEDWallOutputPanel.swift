// LED Wall Output (Show menu, ⇧⌘L): where the LED wall's picture goes on this computer. A display (the HDMI or
// DisplayPort into the LED processor), the wall's rectangle on it in pixels (what the processor reads), a brightness
// ceiling, how far the picture runs ahead of the lights, and a test card to line it all up.
import AmadeusKit
import SwiftUI

struct LEDWallOutputPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let out = model.wallOutput
        @Bindable var o = out
        Form {
            SwiftUI.Section {
                Toggle(isOn: $o.settings.on) {
                    Label("Play the LED Wall", systemImage: "tv")
                    Text(status(out)).foregroundStyle(out.problem == nil ? .secondary : Color.orange)
                }
                .toggleStyle(.switch)
                Picker("Output", selection: $o.settings.target) {
                    Text("Full Screen on a Display").tag(WallOutputSettings.Target.display)
                    Text("In a Window").tag(WallOutputSettings.Target.window)
                }
                if out.settings.target == .display {
                    Picker("Display", selection: displayBinding(out)) {
                        if out.settings.display == nil { Text("Choose…").tag(String?.none) }
                        if let id = out.settings.display, out.chosenScreen == nil {
                            Text("\(out.settings.displayName ?? "A display") (not connected)").tag(String?.some(id))
                        }
                        ForEach(out.screens) { s in
                            Text(s.holdsApp ? "\(s.label) (Amadeus DMX is here)" : s.label).tag(String?.some(s.id))
                        }
                    }
                    if out.screens.count < 2 {
                        Text("Connect the LED processor (HDMI or DisplayPort) like a second display. Set it to Extend, not Mirror, in System Settings › Displays.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                }
            } footer: {
                if let hint = showHint { Text(hint).foregroundStyle(.secondary) }
            }

            if out.settings.target == .display {
                SwiftUI.Section {
                    Toggle("Whole Display", isOn: Binding(get: { out.settings.rect == nil }, set: { whole in
                        out.settings.rect = whole ? nil : defaultRect(out)
                    }))
                    if let r = out.settings.rect {
                        LabeledContent("Start") {
                            HStack {
                                PixelField(label: "X", value: Binding(get: { r.x }, set: { out.settings.rect?.x = max(0, $0) }))
                                PixelField(label: "Y", value: Binding(get: { r.y }, set: { out.settings.rect?.y = max(0, $0) }))
                            }
                        }
                        LabeledContent("Size") {
                            HStack {
                                PixelField(label: "W", value: Binding(get: { r.w }, set: { out.settings.rect?.w = max(1, $0) }))
                                PixelField(label: "H", value: Binding(get: { r.h }, set: { out.settings.rect?.h = max(1, $0) }))
                            }
                        }
                        PanelsRow(out: out)
                    }
                    if let px = rigPixels, out.settings.rect.map({ $0.w != px.w || $0.h != px.h }) ?? true {
                        Button("Use the Rig's Wall: \(px.w) × \(px.h)") {
                            let r = out.settings.rect
                            out.settings.rect = PixelRect(x: r?.x ?? 0, y: r?.y ?? 0, w: px.w, h: px.h)
                        }
                        .help("The LED wall's pixels from the show's rig (Rigs › the rig › LED wall pixels)")
                    }
                    if let warn = shapeWarning(out) { Text(warn).font(.callout).foregroundStyle(.orange) }
                } header: {
                    Text("The Wall on the Display")
                } footer: {
                    Text("In pixels from the display's top left, as the LED processor maps it (its input's start position and the wall's size). Black around it.")
                        .foregroundStyle(.secondary)
                }
            }

            SwiftUI.Section {
                LabeledContent("Brightness") {
                    HStack {
                        Slider(value: $o.settings.brightness, in: 0.05...1)
                        Text("\(Int((out.settings.brightness * 100).rounded())) %").monospacedDigit().frame(width: 48, alignment: .trailing)
                    }
                }
                LabeledContent("Ahead of the Lights") {
                    HStack {
                        Slider(value: Binding(get: { out.settings.leadMs },
                                              set: { out.settings.leadMs = ($0 / 5).rounded() * 5 }),
                               in: WallOutputSettings.leadRange)
                        Text("\(Int(out.settings.leadMs)) ms").monospacedDigit().frame(width: 60, alignment: .trailing)
                    }
                }
                Toggle("Test Card", isOn: $o.settings.testPattern)
                if out.settings.testPattern {
                    LabeledContent("Panel Size") {
                        PixelField(label: "px", value: Binding(get: { out.settings.panelPx }, set: {
                            out.settings.panelPx = min(WallOutputSettings.panelRange.upperBound, max(WallOutputSettings.panelRange.lowerBound, $0))
                        }))
                    }
                }
            } footer: {
                Text("A wall is bright: a dark club wants far less than daylight. An LED processor holds the picture a frame or two (16–50 ms): run it that far ahead so the wall and the lights land on the same beat. The test card shows the wall's edges, the panels, colour bars and a moving bar that stutters when frames are dropped.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 520)
        .fixedSize(horizontal: false, vertical: true)
        .onAppear { out.refreshScreens() }
    }

    private func status(_ out: WallOutputController) -> String {
        if let p = out.problem, out.settings.on { return p }
        if let on = out.playingOn {
            let px = out.outputPixels.map { " · \($0.w) × \($0.h)" } ?? ""
            return "Playing on \(on)\(out.settings.target == .display ? "" : px)"
        }
        return out.settings.on ? "Starting…" : "Off"
    }

    /// What the show gives the wall, when it gives it nothing.
    private var showHint: String? {
        guard model.wallOutput.settings.on else { return nil }
        guard let h = model.feed.hello, model.feed.state == .connected else {
            return "The wall stays black until a show plays."
        }
        return h.screen ? nil : "This show's rig has no LED wall: turn it on in the rig (Rigs) and the director plays it. Until then the wall stays black."
    }

    /// The show's LED wall pixels: the running show's rig, else the selected one.
    private var rigPixels: (w: Int, h: Int)? {
        if let px = model.feed.hello?.screenPx, model.feed.state == .connected { return (px[0], px[1]) }
        return model.workspace?.document(rig: model.selectedRig, set: model.selectedSet)?.screenPixels
    }

    /// The rectangle is another shape than the rig's wall: the picture gets black bars.
    private func shapeWarning(_ out: WallOutputController) -> String? {
        guard let r = out.settings.rect, let px = rigPixels else { return nil }
        let a = Double(r.w) / Double(max(1, r.h)), b = Double(px.w) / Double(px.h)
        guard abs(a / b - 1) > 0.02 else { return nil }
        return String(format: "The rectangle is %.2f:1, the rig's wall %.2f:1: the picture keeps the rig's shape, with black bars.", a, b)
    }

    private func displayBinding(_ out: WallOutputController) -> Binding<String?> {
        Binding(get: { out.settings.display }, set: { id in
            out.settings.display = id
            out.settings.displayName = out.screens.first { $0.id == id }?.name ?? out.settings.displayName
        })
    }

    /// A wall where the processor usually starts reading (the top left), the display's size to begin with.
    private func defaultRect(_ out: WallOutputController) -> PixelRect {
        let px = out.chosenScreen?.pixels ?? (w: 1920, h: 1080)
        return PixelRect(x: 0, y: 0, w: px.w, h: px.h)
    }
}

/// A whole number of pixels.
private struct PixelField: View {
    let label: String
    @Binding var value: Int

    var body: some View {
        HStack(spacing: 4) {
            Text(label).foregroundStyle(.secondary)
            TextField(label, value: $value, format: .number.grouping(.never))
                .labelsHidden()
                .multilineTextAlignment(.trailing)
                .frame(width: 64)
            Stepper(label, value: $value).labelsHidden()
        }
    }
}

/// The wall's size from its panels: columns × rows of the panel size.
private struct PanelsRow: View {
    let out: WallOutputController
    @State private var cols = 6
    @State private var rows = 3

    var body: some View {
        LabeledContent("From Panels") {
            HStack(spacing: 6) {
                Stepper("\(cols) across", value: $cols, in: 1...64)
                Stepper("\(rows) high", value: $rows, in: 1...64)
                Text("of \(out.settings.panelPx) px").foregroundStyle(.secondary)
                Button("Set") {
                    let p = WallOutputLayout.panels(cols: cols, rows: rows, panelPx: out.settings.panelPx)
                    out.settings.rect?.w = p.w
                    out.settings.rect?.h = p.h
                }
            }
        }
        .help("The wall's size from its panels (the panel size is under Test Card)")
    }
}
