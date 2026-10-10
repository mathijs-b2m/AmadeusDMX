// Wizard step 2 and 3: the rig your fixtures go on (a new one from a template, or one you have), and how they
// go on it (auto-mounted, or by hand afterwards).
import DecisiveKit
import SwiftUI

struct RigStep: View {
    @Environment(AppModel.self) private var model
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(symbol: "square.split.bottomrightquarter", title: "Where Do They Hang?",
                       text: "A rig is the venue: the stage and what your fixtures hang on. You can have one per venue and mount the same set on each.")
            if !model.rigs.isEmpty {
                Picker("", selection: $w.useExistingRig) {
                    Text("A new rig").tag(false)
                    Text("A rig I have").tag(true)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }
            if w.useExistingRig {
                Picker("Rig", selection: $w.existingRig) {
                    ForEach(model.rigs) { r in Text("\(r.name) — \(r.summary)").tag(r.name) }
                }
                .onAppear { if w.existingRig.isEmpty { w.existingRig = model.selectedRig } }
            } else {
                HStack(spacing: 8) {
                    ForEach(RigTemplate.allCases) { t in
                        Button { w.template = t } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                RigSketch(template: t).frame(height: 44)
                                Text(t.title).font(.caption.weight(.semibold)).lineLimit(2)
                            }
                            .padding(8)
                            .frame(maxWidth: .infinity, minHeight: 90, alignment: .topLeading)
                            .background(.background.secondary, in: .rect(cornerRadius: 10))
                            .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(w.template == t ? Color.accentColor : .clear, lineWidth: 2) }
                            .contentShape(.rect(cornerRadius: 10))
                        }
                        .buttonStyle(.plain)
                        .help(t.detail)
                    }
                }
                Form {
                    TextField("Rig name", text: $w.rigName)
                    SizeRow(title: "Stage width", value: $w.width, range: 2...30, step: 0.5)
                    if w.template != .floor { SizeRow(title: "Truss height", value: $w.height, range: 2...12, step: 0.5) }
                    Toggle("LED wall behind the DJ", isOn: $w.ledWall)
                }
                .formStyle(.grouped)
                .scrollDisabled(true)
                .frame(height: w.template == .floor ? 150 : 190)
            }
            Picker("Your fixtures on it", selection: $w.autoMount) {
                Label("Auto-mount them", systemImage: "wand.and.stars").tag(true)
                Label("I’ll place them myself", systemImage: "hand.draw").tag(false)
            }
            .pickerStyle(.radioGroup)
            Text(w.autoMount ? "Heads under the trusses, lasers high at the back, bars on the floor: a sensible start you can change in the rig editor."
                 : "They wait on the floor in front of the stage; drag them onto the trusses in the rig editor.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }
}

/// A labelled slider with its value in metres.
struct SizeRow: View {
    var title: String
    @Binding var value: Double
    var range: ClosedRange<Double>
    var step: Double

    var body: some View {
        LabeledContent(title) {
            HStack {
                Slider(value: $value, in: range, step: step)
                Text(step < 1 ? String(format: "%.1f m", value) : "\(Int(value)) m")
                    .monospacedDigit().frame(width: 56, alignment: .trailing)
            }
        }
    }
}
