// Wizard: find the engine folder and check its Python environment.
import AmadeusKit
import SwiftUI

struct EngineStep: View {
    @Environment(AppModel.self) private var model
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "shippingbox.fill", title: "The Engine",
                       text: "The analysis, the director and the DMX output run in the Amadeus DMX engine (Python). The app starts it for you.")
            GroupBox {
                VStack(alignment: .leading, spacing: 10) {
                    if model.workspace?.isBuiltIn == true {
                        Check(ok: true, text: "Engine", detail: "Built into the app")
                    } else {
                        Check(ok: model.workspace?.hasPackage == true, text: "Engine folder",
                              detail: model.workspace?.root.path ?? "Not found")
                        Check(ok: model.workspace?.isValid == true, text: "Python environment (.venv)",
                              detail: model.workspace.map { $0.python.path } ?? "–")
                    }
                    HStack {
                        Button("Choose Engine Folder…") { choose() }
                        if let error { Text(error).foregroundStyle(.red).font(.callout) }
                    }
                }
                .padding(6)
            }
            GroupBox("OpenAI API Key (optional: the rule-based director works without)") {
                OpenAIKeyView().padding(6)
            }
        }
    }

    private func choose() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.message = "Choose the Amadeus DMX folder (with amadeus/ and .venv/)"
        if p.runModal() == .OK, let url = p.url {
            error = model.useWorkspace(url) ? nil : "No engine in that folder."
        }
    }
}

struct Check: View {
    var ok: Bool
    var optional = false
    var text: String
    var detail: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: ok ? "checkmark.circle.fill" : optional ? "circle.dashed" : "xmark.circle.fill")
                .foregroundStyle(ok ? .green : optional ? .secondary : .red)
            VStack(alignment: .leading, spacing: 1) {
                Text(text)
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
        }
    }
}
