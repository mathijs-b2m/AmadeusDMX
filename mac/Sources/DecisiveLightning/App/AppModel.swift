// The app's state: where the engine is, the show engine and the setup service, the live feed, the sets.
import AppKit
import DecisiveKit
import Foundation
import Observation
import Security

@MainActor
@Observable
final class AppModel {
    var workspace: Workspace?
    let engine = EngineProcess(name: "show")
    let setup = EngineProcess(name: "setup")
    let feed = LiveFeed()
    let api = SetupAPI(port: 8181)

    var section: Section = .show
    /// The sidebar's selection (a List wants an optional; nothing selected keeps the page).
    var sidebarSelection: Section? {
        get { section }
        set { if let v = newValue { section = v } }
    }
    var sets: [SetSummary] = []
    var selectedSet: String = ""
    /// Visualise / Perform / both (-showMode perform). Perform ↔ both switches live; DMX on/off restarts the show.
    var mode: ShowMode = .both {
        didSet {
            UserDefaults.standard.set(mode.rawValue, forKey: "showMode")
            feed.lite = !mode.renders3D
        }
    }
    var sendArtNet: Bool { mode.sendsDMX }
    /// A mode change that needs the running show restarted, waiting for the operator's OK.
    var pendingMode: ShowMode?
    @ObservationIgnored private var runningWithDMX = false
    @ObservationIgnored private var remoteCode: String?
    var showInspector = true
    /// The Rig page: "patch" (the table) or "layout" (the rig editor).
    var rigMode: String = UserDefaults.standard.string(forKey: "rigMode") ?? "patch" {
        didSet { UserDefaults.standard.set(rigMode, forKey: "rigMode") }
    }

    /// Open the rig editor for a set.
    func editLayout(_ set: String? = nil) {
        if let set, !engineRunning { selectedSet = set }
        rigMode = "layout"
        section = .rig
    }
    var showZones = UserDefaults.standard.bool(forKey: "showZones")   // -showZones YES
    var playingFile: URL?
    var setupReady = false

    @ObservationIgnored private var setupStartedAt: Date?
    @ObservationIgnored private var previewCache: (key: String, input: StageInput)?

    init() {
        EngineProcess.stopLeftover(name: "show")
        EngineProcess.stopLeftover(name: "setup")
        workspace = Workspace.locate(saved: UserDefaults.standard.string(forKey: "engineRoot"))
        mode = UserDefaults.standard.string(forKey: "showMode").flatMap(ShowMode.init(rawValue:))
            ?? (UserDefaults.standard.object(forKey: "sendArtNet") as? Bool == false ? .visualise : .both)
        reloadSets()
        if let s = UserDefaults.standard.string(forKey: "section").flatMap(Section.init(rawValue:)) { section = s }  // -section rig
        DispatchQueue.main.async { EditorSelfTest.runIfRequested(self) }  // -editorSelfTest SET (development)
        if UserDefaults.standard.bool(forKey: "startLive") {  // -startLive YES: start the live show at launch
            DispatchQueue.main.async { self.startLive() }
        } else if let dj = UserDefaults.standard.string(forKey: "startDJ"),  // -startDJ NAME -djCode 1234
                  let code = UserDefaults.standard.string(forKey: "djCode") {
            DispatchQueue.main.async { self.startLive(dj: dj, code: code) }
        }
        if let file = UserDefaults.standard.string(forKey: "play") {  // -play FILE [-playFrom SECONDS]: start with a track
            let from = UserDefaults.standard.double(forKey: "playFrom")
            DispatchQueue.main.async { self.play(URL(filePath: file), from: from) }
        }
        feed.start()
    }

    var needsSetup: Bool { workspace == nil }

    func useWorkspace(_ url: URL) -> Bool {
        let ws = Workspace(root: url)
        guard ws.isValid else { return false }
        workspace = ws
        UserDefaults.standard.set(url.path, forKey: "engineRoot")
        reloadSets()
        return true
    }

    func reloadSets() {
        guard let ws = workspace else { sets = []; return }
        sets = ws.sets()
        if selectedSet.isEmpty || !sets.contains(where: { $0.name == selectedSet }) {
            selectedSet = UserDefaults.standard.string(forKey: "lastSet").flatMap { n in sets.contains { $0.name == n } ? n : nil }
                ?? ws.activeSet ?? sets.first?.name ?? ""
        }
        previewCache = nil
    }

    var currentSet: SetSummary? { sets.first { $0.name == selectedSet } }

    // MARK: show state

    var showState: ShowState {
        switch engine.state {
        case .failed(let why): return .failed(why)
        case .starting: return .starting
        case .running:
            if playingFile != nil { return feed.state == .connected && feed.hello != nil ? .playing : .starting }
            return feed.decks.contains { $0.play } && feed.hello != nil ? .live : .waitingForDJ
        case .stopped:
            return feed.state == .connected && feed.hello != nil ? .attached : .stopped
        }
    }

    var engineRunning: Bool { engine.isRunning }

    let djs = LinkBrowser()
    /// The DJ laptop the show follows (Decisive Link), when it isn't this Mac.
    private(set) var remoteDJ: String?

    /// Start live mode: the lights follow VirtualDJ (DecisiveLink plugin), on this Mac or on a DJ laptop.
    func startLive(dj: String? = nil, code: String? = nil) {
        guard let ws = workspace, !selectedSet.isEmpty else { return }
        UserDefaults.standard.set(selectedSet, forKey: "lastSet")
        playingFile = nil
        remoteDJ = dj
        remoteCode = code
        runningWithDMX = sendArtNet
        var args = ["live", "--set", selectedSet, "--health", "30"]
        if let dj, let code { args += ["--remote", "dj:" + dj, "--code", code] }
        if sendArtNet { args.insert("--artnet", at: 1) }
        engine.start(ws, args, environment: engineEnvironment, readyWhen: "Live mode", keepAwake: true)
    }

    /// Play a track with the engine itself (no VirtualDJ): to try a set or a look.
    func play(_ file: URL, from start: Double = 0) {
        guard let ws = workspace, !selectedSet.isEmpty else { return }
        UserDefaults.standard.set(selectedSet, forKey: "lastSet")
        playingFile = file
        runningWithDMX = sendArtNet
        var args = ["play", file.path, "--set", selectedSet]
        if sendArtNet { args.append("--artnet") }
        if start > 0 { args += ["--start", String(Int(start))] }
        if UserDefaults.standard.bool(forKey: "muted") { args.append("--mute") }   // -muted YES (testing)
        engine.start(ws, args, environment: engineEnvironment, readyWhen: "Visualiser", keepAwake: true)
    }

    func stopShow() { engine.stop() }

    /// Switch the mode. Turning the lights on or off needs a new engine: a running show asks first.
    func setMode(_ m: ShowMode) {
        if engineRunning && m.sendsDMX != runningWithDMX {
            pendingMode = m
        } else {
            mode = m
        }
    }

    /// The operator said yes: switch and restart the show where it was.
    func confirmPendingMode() {
        guard let m = pendingMode else { return }
        pendingMode = nil
        mode = m
        let file = playingFile, at = feed.time, dj = remoteDJ, code = remoteCode
        engine.stop()
        Task {
            for _ in 0..<80 where engine.isRunning { try? await Task.sleep(for: .milliseconds(100)) }
            if let file { play(file, from: at) } else { startLive(dj: dj, code: code) }
        }
    }

    var engineEnvironment: [String: String] {
        var env: [String: String] = [:]
        if let key = Keychain.openAIKey, !key.isEmpty { env["OPENAI_API_KEY"] = key }
        return env
    }

    // MARK: setup service (the engine's setup API, for the wizard and the rig tools)

    func ensureSetupService() async -> Bool {
        if await api.isUp() { setupReady = true; return true }
        guard let ws = workspace else { return false }
        if !setup.isRunning {
            setup.start(ws, ["setup", "--port", "8181"], environment: engineEnvironment, readyWhen: "Fixture setup")
        }
        for _ in 0..<60 {
            if await api.isUp() { setupReady = true; return true }
            try? await Task.sleep(for: .milliseconds(250))
        }
        return false
    }

    func shutdown() {
        engine.stopAndWait()
        setup.stopAndWait(timeout: 2)
    }

    // MARK: what the stage shows

    /// The running show's rig, or a preview of the selected set.
    func stageInput() -> StageInput? {
        if let h = feed.hello, feed.state == .connected {
            return StageInput(key: "show:\(h.fixtures.count):\(h.stage.widthM):\(h.screen):\(h.trusses.count)", fixtures: h.fixtures,
                              stage: h.stage, screen: h.screen, hello: h, trusses: h.trusses,
                              zones: showZones ? h.zones : [])
        }
        return preview(selectedSet)
    }

    func preview(_ name: String) -> StageInput? {
        if let c = previewCache, c.key == name { return c.input }
        guard let ws = workspace, let p = ws.preview(name) else { return nil }
        let inp = StageInput(key: "preview:\(name):\(p.fixtures.count)", fixtures: p.fixtures, stage: p.stage,
                             screen: p.screen, hello: nil, trusses: p.trusses)
        previewCache = (name, inp)
        return inp
    }
}
