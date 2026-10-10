// Wizard: the set before it is saved.
import DecisiveKit
import SwiftUI

struct ReviewStep: View {
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "checklist", title: "Ready to Create",
                       text: "A set is one rig. A show starts with one set; make as many as you like.")
            Form {
                TextField("Set name", text: $w.name)
                LabeledContent("Venue", value: "\(w.venue.title), \(Int(w.width)) × \(Int(w.depth)) m, trusses at \(w.height.formatted()) m")
                LabeledContent("Fixtures") {
                    VStack(alignment: .trailing) {
                        if w.quickRig, let e = w.quickEntry {
                            Text("\(w.quickCount)× \(e.model) in a concert layout")
                            if w.quickLasers > 0 { Text("\(w.quickLasers)× laser") }
                        } else {
                            ForEach(w.planned) { p in Text("\(p.count)× \(p.entry.model)") }
                        }
                    }
                }
                LabeledContent("LED wall", value: w.ledWall ? "Yes" : "No")
                LabeledContent("Lights", value: w.outputText)
                LabeledContent("Director", value: w.directors.first { $0.value == w.director }?.label ?? w.director)
            }
            .formStyle(.grouped)
        }
    }
}
