// Amadeus DMX for macOS: a native front end for the Python light engine.
import AppKit
import AmadeusKit
import SwiftUI

@main
struct AmadeusDMXApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup("Amadeus DMX", id: "main") {
            MainView()
                .environment(model)
                .onAppear { delegate.model = model }
                .frame(minWidth: 980, minHeight: 620)
        }
        .defaultSize(width: 1440, height: 900)
        .commands { AppCommands(model: model) }

        Window("DMX Devices & Output", id: "dmx") {
            DMXWindow()
                .environment(model)
        }
        .defaultSize(width: 900, height: 620)

        Window("Set Up a Rig", id: "wizard") {
            WizardView()
                .environment(model)
        }
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
        .defaultPosition(.center)

        Settings {
            SettingsView()
                .environment(model)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: AppModel?

    private var signalSources: [DispatchSourceSignal] = []

    func applicationDidFinishLaunching(_ n: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate()
        // killed (SIGTERM/SIGINT, e.g. at logout or from a terminal): stop the engine first, like a normal quit
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { [weak self] in
                MainActor.assumeIsolated { self?.model?.shutdown() }
                exit(0)
            }
            src.resume()
            signalSources.append(src)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ n: Notification) {
        // stop the engine cleanly: it blacks out the lights before it exits
        MainActor.assumeIsolated { model?.shutdown() }
    }
}

struct AppCommands: Commands {
    let model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button("New Set…") { openWindow(id: "wizard") }
                .keyboardShortcut("n", modifiers: [.command, .shift])
        }
        CommandMenu("Show") {
            Button(model.engineRunning ? "Stop Show" : "Start Live Show") {
                model.engineRunning ? model.stopShow() : model.startLive()
            }
            .keyboardShortcut("r", modifiers: .command)
            .disabled(model.workspace == nil)
            Button("Play a Track…") { PlayPanel.choose(model) }
                .keyboardShortcut("o", modifiers: .command)
                .disabled(model.workspace == nil || model.engineRunning)
            Divider()
            Button("DMX Devices & Output…") { openWindow(id: "dmx") }
                .keyboardShortcut("d", modifiers: [.command, .shift])
                .disabled(model.workspace == nil)
            Divider()
            Picker("Mode", selection: Binding(get: { model.mode }, set: { model.setMode($0) })) {
                ForEach(ShowMode.allCases) { m in Label(m.title, systemImage: m.symbol).tag(m) }
            }
            .pickerStyle(.inline)
        }
        CommandGroup(after: .sidebar) {
            ForEach(Array(Section.allCases.enumerated()), id: \.element) { i, s in
                Button(s.title) { model.section = s }
                    .keyboardShortcut(KeyEquivalent(Character(String(i + 1))), modifiers: .command)
            }
            Button("Edit Rig Layout") { model.editLayout() }
                .keyboardShortcut("e", modifiers: .command)
            Divider()
            Button(model.showInspector ? "Hide Director" : "Show Director") { model.showInspector.toggle() }
                .keyboardShortcut("i", modifiers: [.command, .option])
        }
    }
}

/// Open panel for "Play a Track…".
@MainActor
enum PlayPanel {
    static func choose(_ model: AppModel) {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.audio]
        p.message = "Choose a track to play with the lights"
        p.prompt = "Play"
        if p.runModal() == .OK, let url = p.url { model.play(url) }
    }
}
