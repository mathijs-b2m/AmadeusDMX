// The app's state: where the engine is, the show engine and the setup service, the live feed, the sets.
import AppKit
import AmadeusKit
import Foundation
import Observation
import Security

@MainActor
@Observable
final class AppModel {
    var workspace: Workspace?
    let engine = EngineProcess(name: "show")
    /// What the show costs the computer: the light engine against the 3D stage.
    let power = PowerMeter()
    let setup = EngineProcess(name: "setup")
    /// Installs an optional pack (Settings › General).
    let packInstall = EngineProcess(name: "packs")
    let feed = LiveFeed()
    let api = SetupAPI(port: 8181)

    var section: Section = .show
    /// The sidebar's selection (a List wants an optional; nothing selected keeps the page).
    var sidebarSelection: Section? {
        get { section }
        set { if let v = newValue { section = v } }
    }
    /// Your gear (fixtures and patch) and the venues (trusses, stage) it can hang on. A show runs with one of each.
    var sets: [SetSummary] = []
    var rigs: [RigSummary] = []
    var selectedSet: String = "" { didSet { if selectedSet != oldValue { selectionChanged() } } }
    var selectedRig: String = "" { didSet { if selectedRig != oldValue { selectionChanged() } } }
    /// The set on the rig, in words: "showcase on club".
    var showLabel: String { selectedSet.isEmpty ? "No Set" : "\(selectedSet) on \(selectedRig)" }
    /// Sheets: a new rig (from a template), and "mount the set on this rig?" when it isn't yet.
    var showNewRig = false
    /// Goes up whenever sets or rigs were (re)read: views showing a file reload it.
    var configVersion = 0
    var mountPrompt: (rig: String, set: String)?
    /// The Sets page edits this set (it has nothing to do with the show's choice).
    var editingSet = ""
    /// The Rigs page edits this rig, and the set placed on it whose placement is shown ("": the rig alone).
    var editingRig = ""
    var editingRigSet = ""

    /// A set placed on a rig: what a show runs. Made on the Rigs page; the show picks one of these.
    struct Combination: Hashable, Identifiable {
        var rig: String
        var set: String
        var id: String { "\(set)@\(rig)" }
        var label: String { "\(set) on \(rig)" }
    }

    /// Every set placed on a rig (with or without fixtures mounted yet).
    var combinations: [Combination] {
        let names = Set(sets.map(\.name))
        return rigs.flatMap { r in r.mounted.keys.sorted().filter { names.contains($0) }.map { Combination(rig: r.name, set: $0) } }
    }

    /// The sets placed on a rig.
    func setsOn(_ rig: String) -> [String] { combinations.filter { $0.rig == rig }.map(\.set) }

    /// The show runs this combination.
    func chooseShow(_ c: Combination) {
        guard !engineRunning else { return }
        selectedRig = c.rig
        selectedSet = c.set
    }

    /// Puts a set on a rig (a new combination), auto-mounting its fixtures or leaving them to place by hand.
    func placeSet(_ set: String, on rig: String, auto: Bool) async throws {
        guard await ensureSetupService() else { throw SetupAPIError.notRunning }
        try await api.placeSet(set, on: rig, auto: auto)
        reloadSets()
        editingRigSet = set
    }

    /// Takes a set off a rig (its placements there are forgotten).
    func unplaceSet(_ set: String, from rig: String) async throws {
        guard await ensureSetupService() else { throw SetupAPIError.notRunning }
        try await api.unplaceSet(set, from: rig)
        if editingRigSet == set { editingRigSet = "" }
        reloadSets()
    }
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

    /// Open the rig editor.
    func editLayout() {
        section = .rig
    }
    var showZones = UserDefaults.standard.bool(forKey: "showZones")   // -showZones YES
    var playingFile: URL?
    var setupReady = false

    @ObservationIgnored private var setupStartedAt: Date?
    @ObservationIgnored private var previewCache: (key: String, input: StageInput)?

    /// Settings saved before the rename to Amadeus DMX (another bundle id): copied once, where not set here.
    private static func adoptOldSettings() {
        let d = UserDefaults.standard
        guard !d.bool(forKey: "adoptedOldSettings") else { return }
        for (k, v) in d.persistentDomain(forName: "io.github.decisivelightning.app") ?? [:] where d.object(forKey: k) == nil {
            d.set(v, forKey: k)
        }
        d.set(true, forKey: "adoptedOldSettings")
    }

    init() {
        Self.adoptOldSettings()
        EngineProcess.stopLeftover(name: "show")
        EngineProcess.stopLeftover(name: "setup")
        workspace = Workspace.locate(saved: UserDefaults.standard.string(forKey: "engineRoot"))
        mode = UserDefaults.standard.string(forKey: "showMode").flatMap(ShowMode.init(rawValue:))
            ?? (UserDefaults.standard.object(forKey: "sendArtNet") as? Bool == false ? .visualise : .both)
        reloadSets()
        if let s = UserDefaults.standard.string(forKey: "section").flatMap(Section.init(rawValue:)) { section = s }  // -section rig
        if UserDefaults.standard.string(forKey: "section") == "sets" { section = .set }
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

    /// Installs an optional pack; afterwards the engine runs with it (a release: the packs' environment).
    func installPack(_ name: String) async -> Bool {
        guard let ws = workspace, !packInstall.isRunning else { return false }
        packInstall.clearLog()
        packInstall.start(ws, ["packs", "install", name], environment: engineEnvironment)
        while packInstall.isRunning { try? await Task.sleep(for: .milliseconds(250)) }
        if ws.isBuiltIn, let fresh = Workspace.builtIn { workspace = fresh }
        if setup.isRunning { setup.stop(); setupReady = false }  // started again when needed, with the new packages
        return packInstall.state == .stopped
    }

    /// Back to the engine inside the app (after a development folder was chosen).
    func useBuiltInWorkspace() {
        guard let ws = Workspace.builtIn else { return }
        workspace = ws
        UserDefaults.standard.removeObject(forKey: "engineRoot")
        reloadSets()
    }

    /// Reads the sets and rigs again (after any change to them), and keeps a valid selection.
    func reloadSets() {
        guard let ws = workspace else { sets = []; rigs = []; return }
        ws.prepare()
        sets = ws.sets()
        rigs = ws.rigs()
        if selectedSet.isEmpty || !sets.contains(where: { $0.name == selectedSet }) {
            selectedSet = UserDefaults.standard.string(forKey: "lastSet").flatMap { n in sets.contains { $0.name == n } ? n : nil }
                ?? ws.activeSet ?? sets.first?.name ?? ""
        }
        if selectedRig.isEmpty || !rigs.contains(where: { $0.name == selectedRig }) {
            selectedRig = UserDefaults.standard.string(forKey: "lastRig").flatMap { n in rigs.contains { $0.name == n } ? n : nil }
                ?? ws.activeRig ?? rigs.first?.name ?? ""
        }
        // the show runs a combination made on the Rigs page (never a set and a rig that were never put together)
        if !combinations.contains(Combination(rig: selectedRig, set: selectedSet)), let c = combinations.first {
            selectedRig = c.rig
            selectedSet = c.set
        }
        if editingSet.isEmpty || !sets.contains(where: { $0.name == editingSet }) { editingSet = selectedSet }
        if editingRig.isEmpty || !rigs.contains(where: { $0.name == editingRig }) { editingRig = selectedRig }
        if !editingRigSet.isEmpty && !setsOn(editingRig).contains(editingRigSet) { editingRigSet = "" }
        previewCache = nil
        configVersion += 1
    }

    private func selectionChanged() {
        previewCache = nil
        if !selectedSet.isEmpty { UserDefaults.standard.set(selectedSet, forKey: "lastSet") }
        if !selectedRig.isEmpty { UserDefaults.standard.set(selectedRig, forKey: "lastRig") }
    }

    var currentSet: SetSummary? { sets.first { $0.name == selectedSet } }
    var currentRig: RigSummary? { rigs.first { $0.name == selectedRig } }

    /// How much of the set hangs on the rig: (mounted, all).
    var mounted: (placed: Int, total: Int) {
        workspace?.mounted(rig: selectedRig, set: selectedSet) ?? (0, 0)
    }

    /// Picks the rig (and the set) for the show; offers to mount the set if it doesn't hang there yet.
    func choose(rig: String? = nil, set: String? = nil) {
        guard !engineRunning else { return }
        if let rig { selectedRig = rig }
        if let set { selectedSet = set }
    }

    /// Auto-mount the set's fixtures that aren't mounted on the rig yet (or all of them).
    func autoMount(rig: String, set: String, all: Bool = false) async throws {
        guard await ensureSetupService() else { throw SetupAPIError.notRunning }
        try await api.automount(rig: rig, set: set, all: all)
        reloadSets()
    }

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
    /// The DJ laptop the show follows (Amadeus Link), when it isn't this Mac.
    private(set) var remoteDJ: String?
    /// The DJ software a live show on this Mac follows (from the engine's list; VirtualDJ unless chosen).
    private(set) var liveSource: DJSource?

    /// Who the show waits for or follows, for people: the DJ laptop, else the DJ software.
    var djName: String { remoteDJ ?? liveSource?.app ?? "VirtualDJ" }

    /// What to do while the show waits for the DJ software.
    var djWaiting: String {
        if let remoteDJ { return "Waiting for \(remoteDJ)…" }
        return liveSource?.waiting ?? "Load a track in VirtualDJ with AmadeusLink as master effect."
    }

    /// The show's state for people: "Waiting for djay Pro" rather than a fixed name.
    var showTitle: String { showState == .waitingForDJ ? "Waiting for \(djName)" : showState.title }

    /// The DJ software Start (⌘R) follows: the last one chosen in the Start menu.
    var nextSourceName: String {
        workspace?.djSource(UserDefaults.standard.string(forKey: "djSource") ?? "vdj")?.app ?? "VirtualDJ"
    }

    /// Start live mode: the lights follow the DJ software on this Mac (VirtualDJ, Mixxx, …) or on a DJ laptop.
    func startLive(dj: String? = nil, code: String? = nil, source: String? = nil) {
        guard let ws = workspace, !selectedSet.isEmpty else { return }
        playingFile = nil
        remoteDJ = dj
        remoteCode = code
        if let source { UserDefaults.standard.set(source, forKey: "djSource") }
        liveSource = dj == nil ? ws.djSource(source ?? UserDefaults.standard.string(forKey: "djSource") ?? "vdj") : nil
        runningWithDMX = sendArtNet
        var args = ["live", "--set", selectedSet, "--rig", selectedRig, "--health", "30"]
        if let dj, let code { args += ["--remote", "dj:" + dj, "--code", code] }
        else if let source = source ?? UserDefaults.standard.string(forKey: "djSource"), source != "vdj" {
            args += ["--source", source]   // another DJ software on this Mac (the last one chosen in the Start menu)
        }
        if sendArtNet { args.insert("--artnet", at: 1) }
        engine.start(ws, args, environment: engineEnvironment, readyWhen: "Live mode", keepAwake: true)
    }

    /// Play a track with the engine itself (no VirtualDJ): to try a set or a look.
    func play(_ file: URL, from start: Double = 0) {
        guard let ws = workspace, !selectedSet.isEmpty else { return }
        playingFile = file
        runningWithDMX = sendArtNet
        var args = ["play", file.path, "--set", selectedSet, "--rig", selectedRig]
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
        if let ws = workspace { env.merge(ws.environment) { _, new in new } }  // where the engine and your data are
        if let key = Keychain.openAIKey, !key.isEmpty { env["OPENAI_API_KEY"] = key }
        if let host = UserDefaults.standard.string(forKey: "ollamaHost"), !host.isEmpty { env["OLLAMA_HOST"] = host }
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

    /// Start the setup service again (e.g. with a new OpenAI key or Ollama address), when it runs.
    func restartSetupService() async {
        guard setup.isRunning else { return }
        setup.stopAndWait(timeout: 2)
        setupReady = false
        _ = await ensureSetupService()
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
        return preview(rig: selectedRig, set: selectedSet)
    }

    /// The set on the rig, before a show runs. Cached until the selection changes or a save (`reloadSets`).
    func preview(rig: String, set: String) -> StageInput? {
        let key = "\(rig)/\(set)"
        if let c = previewCache, c.key == key { return c.input }
        guard let ws = workspace, let p = ws.preview(rig: rig, set: set) else { return nil }
        let inp = StageInput(key: "preview:\(key):\(p.fixtures.count):\(p.trusses.count)", fixtures: p.fixtures, stage: p.stage,
                             screen: p.screen, hello: nil, trusses: p.trusses)
        previewCache = (key, inp)
        return inp
    }
}
