// Settings (⌘,): the engine folder, the AI key, the DJ software integrations, the look of the stage.
import DecisiveKit
import SwiftUI

/// The same settings in the Settings window (⌘,) and on the main window's Settings page.
struct SettingsView: View {
    var page = false

    var body: some View {
        if page {
            tabs.frame(maxWidth: 680).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top).padding()
        } else {
            tabs.frame(width: 560).scenePadding()
        }
    }

    private var tabs: some View {
        TabView {
            Tab("General", systemImage: "gearshape") { GeneralSettings() }
            Tab("Director", systemImage: "wand.and.stars") { DirectorSettings() }
            Tab("Integrations", systemImage: "dot.radiowaves.left.and.right") { IntegrationSettings() }
        }
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
    var body: some View {
        Form {
            DirectorChoiceSection()
            SwiftUI.Section {
                OpenAIKeyView()
            } header: {
                Text("AI Director: OpenAI API key")
            } footer: {
                Text("With a key, the AI director (OpenAI) decides the show; without one, the rule-based director does. Your key is kept in your Keychain and handed to the engine when it starts, never written to a file, and only sent to OpenAI.")
            }
        }
        .formStyle(.grouped)
    }
}

/// What each DJ software integration needs or may do: one section per DJ software.
struct IntegrationSettings: View {
    var body: some View {
        Form {
            VirtualDJSection()
            DjaySection()
        }
        .formStyle(.grouped)
    }
}

struct DjaySection: View {
    @Environment(AppModel.self) private var model
    @State private var streamed = false
    @State private var confirming = false

    var body: some View {
        SwiftUI.Section {
            Toggle(isOn: Binding(get: { streamed }, set: { on in
                if on { confirming = true } else { save(false) }
            })) {
                Text("Light streamed tracks")
                Text("Spotify tracks have no file to analyse. When one is loaded on a deck, a copy of the same recording is downloaded from YouTube (yt-dlp, once per track) and analysed. The audience still hears djay's own stream. Needs an internet connection during the show.")
            }
            .disabled(model.workspace == nil)
            if streamed, model.workspace?.hasPythonPackage("yt_dlp") == false {
                Label("yt-dlp isn't installed in the engine's environment: pip install -e '.[streamed]'", systemImage: "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.orange)
            }
        } header: {
            Text("djay Pro")
        } footer: {
            Text("Off by default. Downloading from YouTube goes against YouTube's terms of service and may not be allowed by copyright law where you are. Only switch this on for music you may copy; you are responsible for that choice. Needs an internet connection: a track is fetched when it is loaded on a deck (a few seconds); offline, streamed tracks stay dark, while tracks fetched before still light. Copies stay on this Mac (the engine's .cache/streamed) and are used only to analyse the track. Takes effect at the next live show.")
        }
        .onAppear { streamed = model.workspace?.integrationSetting("djay", "streamed") ?? false }
        .confirmationDialog("Download copies of streamed tracks?", isPresented: $confirming) {
            Button("Switch On") { save(true) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Each Spotify track you load in djay is downloaded from YouTube to analyse it. That goes against YouTube's terms of service and may not be allowed where you are. Only use it for music you may copy.")
        }
    }

    private func save(_ on: Bool) {
        model.workspace?.setIntegrationSetting("djay", "streamed", on)
        streamed = on
    }
}

struct VirtualDJSection: View {
    @Environment(AppModel.self) private var model
    @State private var status = ""

    private var dest: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Application Support/VirtualDJ/PluginsMacArm/SoundEffect/DecisiveLink.bundle")
    }

    var body: some View {
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
