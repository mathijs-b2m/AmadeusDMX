// Settings (⌘,): the engine folder, the AI key, VirtualDJ, the look of the stage.
import DecisiveKit
import SwiftUI

struct SettingsView: View {
    var body: some View {
        TabView {
            Tab("General", systemImage: "gearshape") { GeneralSettings() }
            Tab("Director", systemImage: "wand.and.stars") { DirectorSettings() }
            Tab("VirtualDJ", systemImage: "dot.radiowaves.left.and.right") { VirtualDJSettings() }
        }
        .frame(width: 560)
        .scenePadding()
    }
}

struct GeneralSettings: View {
    @Environment(AppModel.self) private var model
    @State private var error: String?

    var body: some View {
        @Bindable var model = model
        Form {
            SwiftUI.Section {
                LabeledContent("Engine folder") {
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(model.workspace?.root.path ?? "Not set").font(.callout).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                        Button("Choose…") { choose() }
                    }
                }
                if let error { Text(error).foregroundStyle(.red).font(.callout) }
            } footer: {
                Text("The Decisive Lightning folder with its Python environment (.venv). The web UI uses the same folder, sets and fixtures.")
            }
            SwiftUI.Section {
                Picker("Mode", selection: Binding(get: { model.mode }, set: { model.setMode($0) })) {
                    ForEach(ShowMode.allCases) { m in Text(m.title).tag(m) }
                }
            } footer: {
                Text(model.mode.detail + " Perform Only keeps the computer free for the lights at a gig.")
            }
        }
        .formStyle(.grouped)
    }

    private func choose() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.message = "Choose the Decisive Lightning engine folder"
        if p.runModal() == .OK, let url = p.url {
            error = model.useWorkspace(url) ? nil : "That folder has no engine (decisive/ and .venv/bin/python)."
        }
    }
}

struct DirectorSettings: View {
    @Environment(AppModel.self) private var model
    @State private var key = Keychain.openAIKey ?? ""
    @State private var saved = false

    var body: some View {
        Form {
            SwiftUI.Section {
                SecureField("OpenAI API key", text: $key, prompt: Text("sk-…"))
                HStack {
                    if model.workspace?.hasEnvKey == true {
                        Label("The engine folder also has a key in .env", systemImage: "checkmark.circle")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if saved { Text("Saved").foregroundStyle(.secondary) }
                    Button("Save") {
                        Keychain.openAIKey = key.trimmingCharacters(in: .whitespacesAndNewlines)
                        saved = true
                    }
                }
            } header: {
                Text("AI Director")
            } footer: {
                Text("Stored in your Keychain and handed to the engine when it starts; never written to a file.")
            }
        }
        .formStyle(.grouped)
    }
}

struct VirtualDJSettings: View {
    @Environment(AppModel.self) private var model
    @State private var status = ""

    private var dest: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Application Support/VirtualDJ/PluginsMacArm/SoundEffect/DecisiveLink.bundle")
    }

    var body: some View {
        Form {
            SwiftUI.Section {
                LabeledContent("DecisiveLink plugin") {
                    Text(FileManager.default.fileExists(atPath: dest.path) ? "Installed" : "Not installed")
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Spacer()
                    if !status.isEmpty { Text(status).foregroundStyle(.secondary) }
                    Button("Install Plugin") { install() }
                        .disabled(!(FileManager.default.fileExists(atPath: model.workspace?.pluginBundle.path ?? "")))
                }
            } header: {
                Text("VirtualDJ")
            } footer: {
                Text("In VirtualDJ, add DecisiveLink as master effect. It sends every deck's position, tempo and volume to the engine (UDP 9123). Restart VirtualDJ after installing.")
            }
        }
        .formStyle(.grouped)
    }

    private func install() {
        guard let src = model.workspace?.pluginBundle else { return }
        do {
            try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: dest)
            try FileManager.default.copyItem(at: src, to: dest)
            status = "Installed. Restart VirtualDJ."
        } catch {
            status = error.localizedDescription
        }
    }
}
