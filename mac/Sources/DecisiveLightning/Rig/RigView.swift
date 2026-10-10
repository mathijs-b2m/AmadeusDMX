// The rig: the venue's structure (trusses, towers, stage, zones) and where the set's fixtures hang on it.
import DecisiveKit
import SwiftUI

struct RigView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if let ws = model.workspace, !model.selectedRig.isEmpty, !model.selectedSet.isEmpty,
           let editor = RigEditorModel(workspace: ws, rig: model.selectedRig, set: model.selectedSet) {
            RigEditorView(editor: editor)
                .id("\(model.selectedRig)/\(model.selectedSet)")
        } else {
            ContentUnavailableView {
                Label("No Rig Yet", systemImage: "square.split.bottomrightquarter")
            } description: {
                Text("A rig is the venue: the stage and the trusses your fixtures hang on.")
            } actions: {
                Button("New Rig…") { model.showNewRig = true }.buttonStyle(.borderedProminent)
            }
        }
    }
}
