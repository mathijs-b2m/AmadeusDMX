// Settings (⌘,): the engine folder, the AI key, the DJ software integrations, the look of the stage.
import AmadeusKit
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

    @State private var tab = UserDefaults.standard.string(forKey: "settingsTab") ?? "general"  // -settingsTab director (screenshots)

    private var tabs: some View {
        TabView(selection: $tab) {
            Tab("General", systemImage: "gearshape", value: "general") { GeneralSettings() }
            Tab("Director", systemImage: "wand.and.stars", value: "director") { DirectorSettings() }
            Tab("Integrations", systemImage: "dot.radiowaves.left.and.right", value: "integrations") { IntegrationSettings() }
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
                LabeledContent("Engine") {
                    VStack(alignment: .trailing, spacing: 4) {
                        Text(model.workspace.map { $0.isBuiltIn ? "Built into the app" : $0.root.path } ?? "Not set")
                            .font(.callout).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                        HStack {
                            if Workspace.builtIn != nil, model.workspace?.isBuiltIn != true {
                                Button("Use Built-in") { model.useBuiltInWorkspace(); error = nil }
                            }
                            Button("Choose Folder…") { choose() }
                        }
                    }
                }
                if let ws = model.workspace, ws.isBuiltIn {
                    LabeledContent("Your data") {
                        Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([ws.data]) }
                    }
                }
                if let error { Text(error).foregroundStyle(.red).font(.callout) }
            } footer: {
                if model.workspace?.isBuiltIn == true {
                    Text("Your sets, rigs and fixtures are kept apart from the app, so an update never touches them. A development checkout (with its .venv) can be chosen instead.")
                } else {
                    Text("The Amadeus DMX folder with its Python environment (.venv). The web UI uses the same folder, sets and fixtures.")
                }
            }
            UpdatesSection()
            PacksSection()
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
        p.message = "Choose the Amadeus DMX engine folder"
        if p.runModal() == .OK, let url = p.url {
            error = model.useWorkspace(url) ? nil : "That folder has no engine (amadeus/ and .venv/bin/python)."
        }
    }
}

/// Updates (Sparkle, App/Updates.swift): whether to check and install by itself, and checking now.
struct UpdatesSection: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let updates = model.updates
        SwiftUI.Section {
            if updates.isAvailable {
                UpdateToggles(updates: updates)
                UpdateStatusView(updates: updates, appName: "Amadeus DMX", whenIdle: "when the show stops")
            } else {
                LabeledContent("Amadeus DMX \(updates.version)") {
                    Text("A development build: it updates with the code, not by itself.").foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Updates")
        } footer: {
            if updates.isAvailable { Text(UpdateToggles.rules) }
        }
    }
}

/// Whether to check and install by itself (Settings › General and the sidebar's version line).
struct UpdateToggles: View {
    let updates: Updates
    @State private var checks = false
    @State private var installs = false

    static let rules = "Never during a show: no check while the lights run, and an update you install then waits until the show stops. One downloaded by itself is installed when you quit. Your sets, rigs and packs stay as they are."

    var body: some View {
        Toggle("Check for updates automatically", isOn: Binding(get: { checks }, set: {
            updates.checksAutomatically = $0; checks = $0
        }))
        Toggle("Download and install updates by themselves", isOn: Binding(get: { installs }, set: {
            updates.installsAutomatically = $0; installs = $0
        }))
        .disabled(!checks)
        .onAppear {
            checks = updates.checksAutomatically
            installs = updates.installsAutomatically
        }
    }
}

/// The optional packs (amadeus/cli/packs.py): what each adds, and installing it.
struct PacksSection: View {
    @Environment(AppModel.self) private var model
    @State private var packs: [PackInfo] = []
    @State private var installing: String?
    @State private var confirm: PackInfo?
    @State private var failed: String?

    var body: some View {
        SwiftUI.Section {
            ForEach(packs) { pack in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(pack.title)
                        Spacer()
                        if pack.installed {
                            Label("Installed", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                        } else if installing == pack.name {
                            ProgressView().controlSize(.small)
                        } else {
                            Button("Install (\(pack.size))") { confirm = pack }.disabled(installing != nil)
                        }
                    }
                    Text(pack.about).font(.callout).foregroundStyle(.secondary)
                    if installing == pack.name {
                        Text(model.packInstall.lastLine).font(.caption.monospaced()).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                    }
                    if failed == pack.name {
                        Text("Not installed: \(model.packInstall.log.last(where: \.isError)?.text ?? model.packInstall.lastLine)")
                            .font(.callout).foregroundStyle(.red)
                    }
                }
                .padding(.vertical, 2)
            }
        } header: {
            Text("Optional packs")
        } footer: {
            Text("Downloaded from the internet when you install them, then they work offline. They take effect at the next show.")
        }
        .task(id: model.workspace) { packs = await model.workspace?.packs() ?? [] }
        .confirmationDialog("Install \(confirm?.title ?? "")?", isPresented: Binding(get: { confirm != nil }, set: { if !$0 { confirm = nil } }),
                            presenting: confirm) { pack in
            Button("Install (\(pack.size))") { install(pack.name) }
            Button("Cancel", role: .cancel) {}
        } message: { pack in
            Text(pack.note.isEmpty ? pack.about : pack.note)
        }
    }

    private func install(_ name: String) {
        installing = name
        failed = nil
        Task {
            let ok = await model.installPack(name)
            packs = await model.workspace?.packs() ?? []
            installing = nil
            if !ok { failed = name }
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
            StreamedSection()
            AssistantSection()
        }
        .formStyle(.grouped)
    }
}

/// Streamed tracks (Spotify in djay Pro and VirtualDJ, here or on a DJ laptop through Amadeus Link): a copy of the
/// same recording, downloaded to analyse it (amadeus/show/sources/streamed.py). One switch for all, off by default.
struct StreamedSection: View {
    @Environment(AppModel.self) private var model
    @State private var on = false
    @State private var confirming = false

    var body: some View {
        SwiftUI.Section {
            Toggle(isOn: Binding(get: { on }, set: { new in
                if new { confirming = true } else { save(false) }
            })) {
                Text("Light streamed tracks")
                Text("Spotify tracks in djay Pro and VirtualDJ have no file to analyse. When one is loaded on a deck (on this Mac, or on a DJ laptop through Amadeus Link), a copy of the same recording is downloaded from YouTube (yt-dlp, once per track) and analysed. The audience still hears the DJ software's own stream. Needs an internet connection during the show.")
            }
            .disabled(model.workspace == nil)
            if on, model.workspace?.hasPythonPackage("yt_dlp") == false {
                Label("yt-dlp isn't installed: install Streamed tracks under General › Optional packs", systemImage: "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.orange)
            }
        } header: {
            Text("Streamed tracks")
        } footer: {
            Text("Off by default. Downloading from YouTube goes against YouTube's terms of service and may not be allowed by copyright law where you are. Only switch this on for music you may copy; you are responsible for that choice. Needs an internet connection: a track is fetched when it is loaded on a deck (a few seconds); offline, streamed tracks stay dark, while tracks fetched before still light. Copies stay on this Mac (the engine's .cache/streamed) and are used only to analyse the track. Takes effect at the next live show.")
        }
        .onAppear {
            on = (model.workspace?.integrationSetting("streamed", "on") ?? false)
                || (model.workspace?.integrationSetting("djay", "streamed") ?? false)  // the switch as djay's own, from before
        }
        .confirmationDialog("Download copies of streamed tracks?", isPresented: $confirming) {
            Button("Switch On") { save(true) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Each Spotify track you load in djay Pro or VirtualDJ is downloaded from YouTube to analyse it. That goes against YouTube's terms of service and may not be allowed where you are. Only use it for music you may copy.")
        }
    }

    private func save(_ value: Bool) {
        model.workspace?.setIntegrationSetting("streamed", "on", value)
        if !value { model.workspace?.setIntegrationSetting("djay", "streamed", false) }  // off means off, also the old one
        on = value
    }
}

/// Your own AI assistant (amadeus mcp, docs/ai-assistants.md): Claude Desktop starts the engine's assistant server and
/// can then make and change your sets and rigs. Off until switched on; the engine writes Claude's config.
struct AssistantSection: View {
    @Environment(AppModel.self) private var model
    @State private var busy = false

    var body: some View {
        let status = model.claudeDesktop
        SwiftUI.Section {
            Toggle(isOn: Binding(get: { status?.on ?? false }, set: { on in
                busy = true
                Task { await model.setClaudeDesktop(on); busy = false }
            })) {
                Text("Claude Desktop can work on your sets and rigs")
                Text("Ask Claude to make a rig for a venue from its PDFs, add fixtures, mount them or check what is unfinished. It uses your own Claude subscription.")
            }
            .disabled(busy || status == nil || status?.installed == false && status?.on == false)
            if let status {
                if !status.problem.isEmpty {
                    Label(status.problem, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange)
                } else if !status.installed {
                    Label("Claude Desktop isn't installed (or hasn't been opened yet).", systemImage: "info.circle")
                        .font(.callout).foregroundStyle(.secondary)
                } else if status.on {
                    Label("Restart Claude Desktop to pick this up. In a new chat, amadeus-dmx is under the tools button.",
                          systemImage: "checkmark.circle").font(.callout).foregroundStyle(.secondary)
                }
            }
            HStack {
                Spacer()
                Link("Other assistants (Claude Code, Codex)…", destination: HelpLinks.assistants).font(.callout)
            }
        } header: {
            Text("Your AI assistant")
        } footer: {
            Text("Everything it saves is checked as in the app, and before each change your sets and rigs are copied aside: ask it to undo. It can't delete sets or rigs, switch lights on or change a show that is running. An open rig editor shows its changes, or asks first when you have unsaved changes there.")
        }
        .task(id: model.workspace) { await model.refreshClaudeDesktop() }
    }
}

struct VirtualDJSection: View {
    @Environment(AppModel.self) private var model
    @State private var message = ""
    @State private var installed = VirtualDJPlugin.Status.notInstalled

    var body: some View {
        let bundled = model.workspace?.pluginBundle
        SwiftUI.Section {
            LabeledContent("AmadeusLink plugin") {
                Text(installedText).foregroundStyle(installed == .outdated ? .orange : .secondary)
            }
            HStack {
                Spacer()
                if !message.isEmpty { Text(message).foregroundStyle(.secondary) }
                Button(installed == .outdated ? "Update Plugin" : "Install Plugin") { install(bundled) }
                    .disabled(!(FileManager.default.fileExists(atPath: bundled?.path ?? "")) || installed == .upToDate)
            }
        } header: {
            Text("VirtualDJ")
        } footer: {
            Text("In VirtualDJ, add AmadeusLink as master effect. It sends every deck's position, tempo and volume to the engine (UDP 9123). Restart VirtualDJ after installing. On a separate DJ laptop, Amadeus Link installs it.")
        }
        .onAppear { installed = VirtualDJPlugin.status(comparedTo: bundled) }
    }

    private var installedText: String {
        switch installed {
        case .notInstalled: "Not installed"
        case .upToDate: "Installed"
        case .outdated: "An update is ready"
        }
    }

    private func install(_ bundled: URL?) {
        guard let bundled else { return }
        do {
            try VirtualDJPlugin.install(from: bundled)
            message = "Installed. Restart VirtualDJ."
        } catch {
            message = error.localizedDescription
        }
        installed = VirtualDJPlugin.status(comparedTo: bundled)
    }
}
