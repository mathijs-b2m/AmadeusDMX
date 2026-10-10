// Wizard: saved; what to do next.
import DecisiveKit
import SwiftUI

struct DoneStep: View {
    @Environment(AppModel.self) private var model
    var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            StepHeader(symbol: "checkmark.seal.fill", title: "“\(w.name)” Is Ready",
                       text: "It’s selected in the main window. Start the show with ⌘R, or try it with a track first (⌘O).")
            Feature(symbol: "dot.radiowaves.left.and.right", title: "Connect VirtualDJ",
                    text: "Install the DecisiveLink plugin (Settings › VirtualDJ) and add it as master effect.")
            Feature(symbol: "light.overhead.right", title: "Check the patch",
                    text: "The Rig page lists every fixture with its address; Identify lights one on the real rig.")
        }
    }
}
