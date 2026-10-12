// Wizard: saved; what to do next.
import AmadeusKit
import SwiftUI

struct DoneStep: View {
    @Environment(AppModel.self) private var model
    var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            StepHeader(symbol: "checkmark.seal.fill", title: "“\(w.name)” on “\(w.useExistingRig ? w.existingRig : w.rigName)” Is Ready",
                       text: w.autoMount ? "Both are selected in the main window. Check where everything hangs on the Rig page, then start the show with ⌘R or try a track (⌘O)."
                       : "Both are selected in the main window. Your fixtures wait in front of the stage: drag them onto the trusses on the Rig page.")
            Feature(symbol: "dot.radiowaves.left.and.right", title: "Connect your DJ software",
                    text: "VirtualDJ: install the AmadeusLink plugin (Settings › VirtualDJ) and add it as master effect. Mixxx or djay Pro: choose it in the Start menu.")
            Feature(symbol: "light.overhead.right", title: "Check the patch",
                    text: "The Set page lists every fixture with its DMX address; Identify lights one on the real rig.")
            Feature(symbol: "square.split.bottomrightquarter", title: "Another venue?",
                    text: "Make a rig for it (Rig › New Rig…) and mount the same set on it.")
        }
    }
}
