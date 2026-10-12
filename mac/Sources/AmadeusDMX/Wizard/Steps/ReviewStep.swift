// Wizard: the set, the rig and how the set goes on it, before anything is made.
import AmadeusKit
import SwiftUI

struct ReviewStep: View {
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "checklist", title: "Ready to Create",
                       text: "Your set (the fixtures) goes on the rig (the venue). Later you can mount the same set on other rigs.")
            Form {
                SwiftUI.Section("1 · The set") {
                    TextField("Set name", text: $w.name)
                    LabeledContent("Fixtures") {
                        VStack(alignment: .trailing) { ForEach(w.planned) { p in Text("\(p.count)× \(p.entry.model)") } }
                    }
                    LabeledContent("Lights", value: w.outputText)
                    LabeledContent("Director", value: w.directors.first { $0.value == w.director }?.label ?? w.director)
                }
                SwiftUI.Section("2 · The rig") {
                    if w.useExistingRig {
                        LabeledContent("Rig", value: w.existingRig)
                    } else {
                        LabeledContent("Rig", value: "\(w.rigName): \(w.template.title.lowercased())")
                        LabeledContent("Size", value: "\(w.width.formatted()) m wide\(w.template == .floor ? "" : ", trusses at \(w.height.formatted()) m")")
                        LabeledContent("LED wall", value: w.ledWall ? "Yes" : "No")
                    }
                }
                SwiftUI.Section("3 · On the rig") {
                    LabeledContent("Fixtures", value: w.autoMount ? "Auto-mounted" : "Placed by hand in the rig editor")
                }
            }
            .formStyle(.grouped)
        }
    }
}
