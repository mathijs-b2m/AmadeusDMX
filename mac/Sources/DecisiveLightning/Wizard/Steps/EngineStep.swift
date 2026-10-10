// Wizard: find the engine folder and check its Python environment.
import DecisiveKit
import SwiftUI

struct EngineStep: View {
    @Environment(AppModel.self) private var model
    @State private var error: String?
    @State private var key = Keychain.openAIKey ?? ""

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "shippingbox.fill", title: "The Engine",
                       text: "The analysis, the director and the DMX output run in the Decisive Lightning engine (Python). The app starts it for you.")
            GroupBox {
                VStack(alignment: .leading, spacing: 10) {
                    Check(ok: model.workspace?.hasPackage == true, text: "Engine folder",
                          detail: model.workspace?.root.path ?? "Not found")
                    Check(ok: model.workspace?.isValid == true, text: "Python environment (.venv)",
                          detail: model.workspace.map { $0.python.path } ?? "–")
                    Check(ok: !key.isEmpty || model.workspace?.hasEnvKey == true, optional: true, text: "OpenAI key for the AI director",
                          detail: model.workspace?.hasEnvKey == true ? "found in .env" : key.isEmpty ? "optional: the rules director works without" : "in your Keychain")
                    HStack {
                        Button("Choose Engine Folder…") { choose() }
                        if let error { Text(error).foregroundStyle(.red).font(.callout) }
                    }
                }
                .padding(6)
            }
            GroupBox("OpenAI API Key (optional)") {
                HStack {
                    SecureField("sk-…", text: $key)
                    Button("Save") { Keychain.openAIKey = key.trimmingCharacters(in: .whitespaces) }
                }
                .padding(6)
            }
        }
    }

    private func choose() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.message = "Choose the Decisive Lightning folder (with decisive/ and .venv/)"
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
