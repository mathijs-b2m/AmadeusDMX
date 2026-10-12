// The setup wizard's state: 1. a set (your fixtures and where the DMX goes), 2. a rig (the venue: a new one from a
// template, or one you have), 3. the set placed on the rig (auto-mounted, or by hand in the rig editor).
// Everything is made through the engine's setup API.
import AmadeusKit
import Foundation
import Observation

struct PlannedFixture: Identifiable, Hashable {
    var id = UUID()
    var entry: CatalogEntry
    var mode: String
    var modes: [String]
    var count: Int
}

enum WizardStep: Int, CaseIterable {
    case welcome, engine, fixtures, network, rig, director, review, done

    var title: String {
        switch self {
        case .welcome: "Welcome"
        case .engine: "Engine"
        case .fixtures: "Your Fixtures"
        case .network: "Lights"
        case .rig: "Rig"
        case .director: "Director"
        case .review: "Review"
        case .done: "Done"
        }
    }
}

@MainActor
@Observable
final class WizardModel {
    var step: WizardStep = .welcome

    // the set: fixtures
    var planned: [PlannedFixture] = []
    var query = ""
    var results: [CatalogEntry] = []
    var searching = false

    // network
    enum Output: String { case visualiser, node, manual, usb }
    var output: Output = .visualiser
    /// Network nodes: Art-Net or sACN (a Showtec NET-2/3 or NET-2/5 speaks both)
    var sacn = false
    var multicast = true
    var usb: [USBInterface] = []
    var usbPort = "auto"
    var searchingUSB = false
    var nodes: [ArtNetNode] = []
    var node: ArtNetNode?
    var manualIP = "2.0.0.10"
    var discovering = false
    var discoverError: String?

    // the rig: a new one from a template, or one there is already; and how the set goes on it
    var useExistingRig = false
    var existingRig = ""
    var template: RigTemplate = .club { didSet { applyTemplate() } }
    var rigName = "club"
    var width = 10.0
    var height = 4.5
    var depth = 15.0
    var ledWall = true
    var autoMount = true

    // director
    var directors: [DirectorOption] = []
    var director = "rules"

    // create
    var name = "my-set"
    var creating = false
    var progress = ""
    var error: String?

    init() {
        applyTemplate()
        if let raw = UserDefaults.standard.string(forKey: "wizardStep"),  // -wizardStep network (testing)
           let st = WizardStep.allCases.first(where: { $0.title.lowercased() == raw || "\($0)" == raw }) {
            step = st
            if st == .network { output = .usb }
        }
    }

    private func applyTemplate() {
        (width, height, depth) = template.size
        ledWall = template == .club || template == .stage
        if RigTemplate.allCases.contains(where: { rigName.hasPrefix($0.rawValue) }) || rigName.isEmpty { rigName = template.rawValue }
    }

    var fixtureCount: Int { planned.reduce(0) { $0 + $1.count } }

    var canContinue: Bool {
        switch step {
        case .fixtures: !planned.isEmpty
        case .rig: useExistingRig ? !existingRig.isEmpty : !rigName.trimmingCharacters(in: .whitespaces).isEmpty
        case .network: (output != .node || node != nil) && (output != .usb || !usb.isEmpty || usbPort == "auto")
        case .review: !name.trimmingCharacters(in: .whitespaces).isEmpty
        default: true
        }
    }

    // MARK: catalogue

    func search(_ api: SetupAPI) async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { results = []; return }
        searching = true
        defer { searching = false }
        results = (try? await api.catalog(q, limit: 30)) ?? []
    }

    func add(_ e: CatalogEntry, _ api: SetupAPI) async {
        var modes = e.modes.map { $0.sorted { $0.value > $1.value }.map(\.key) } ?? []
        if modes.isEmpty, let d = try? await api.details(e.key) { modes = d.modeList.map(\.name) }
        planned.append(PlannedFixture(entry: e, mode: modes.first ?? "", modes: modes,
                                      count: e.type == "moving head" ? 4 : 2))
    }

    // MARK: network

    func discover(_ api: SetupAPI) async {
        discovering = true
        discoverError = nil
        defer { discovering = false }
        do {
            nodes = try await api.discover()
            if node == nil { node = nodes.first }
            if nodes.isEmpty { discoverError = "No Art-Net nodes answered. Check the cable and that the node is powered." }
        } catch {
            discoverError = error.localizedDescription
        }
    }

    func findUSB(_ api: SetupAPI) async {
        searchingUSB = true
        defer { searchingUSB = false }
        usb = (try? await api.usbInterfaces()) ?? []
        if let pro = usb.first(where: \.isPro) { usbPort = pro.port }
    }

    /// The set's "output" block (nil: Art-Net to `artnetIP`, as sets always did).
    var outputSpec: [String: Any]? {
        switch output {
        case .visualiser: return nil
        case .usb: return ["type": "enttec_pro", "port": usbPort, "universe": 1]
        case .node, .manual:
            guard sacn else { return nil }
            var s: [String: Any] = ["type": "sacn", "priority": 100]
            if !multicast { s["ip"] = artnetIP }
            return s
        }
    }

    var outputText: String {
        switch output {
        case .visualiser: "Visualiser only"
        case .usb: "USB ENTTEC Pro → \(usbPort == "auto" ? "first one found" : (usbPort as NSString).lastPathComponent)"
        case .node, .manual: sacn ? "sACN → \(multicast ? "multicast" : artnetIP)" : "Art-Net → \(artnetIP)"
        }
    }

    var artnetIP: String {
        switch output {
        case .visualiser: "127.0.0.1"
        case .node: node?.ip ?? "127.0.0.1"
        case .manual: manualIP
        case .usb: "127.0.0.1"
        }
    }

    // MARK: create: the set, the rig, the set on the rig

    static func safe(_ name: String) -> String {
        name.lowercased().replacingOccurrences(of: #"[^a-z0-9_-]+"#, with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    }

    func create(_ model: AppModel) async {
        creating = true
        error = nil
        defer { creating = false }
        let api = model.api
        let setName = Self.safe(name)
        let rig = useExistingRig ? existingRig : Self.safe(rigName)
        do {
            progress = "Starting the engine’s setup service…"
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            if model.sets.contains(where: { $0.name == setName }) {
                throw SetupAPIError.server("A set called “\(setName)” already exists. Choose another name.")
            }
            if !useExistingRig && model.rigs.contains(where: { $0.name == rig }) {
                throw SetupAPIError.server("A rig called “\(rig)” already exists. Choose another name, or use it.")
            }
            progress = "1/3 · The set…"
            try await api.createSet(name: setName)
            progress = "2/3 · The rig…"
            if useExistingRig {
                try await api.makeDefaultRig(rig)
            } else {
                try await api.createRig(name: rig, template: template.rawValue, width: width, height: height, depth: depth,
                                        screen: ledWall)
            }
            var layout = try await api.rig(rig: rig, set: setName)
            var items: [[String: Any]] = []
            for p in planned {
                progress = "Adding \(p.count)× \(p.entry.model)…"
                let key = p.entry.isLocal ? p.entry.key : try await api.addToLibrary(p.entry.key)
                for _ in 0..<p.count { items.append(["fixture": key, "mode": p.mode, "universe": 1]) }
            }
            progress = "Patching addresses…"
            let placementKeys = Set(RigDocument.placementKeys)
            layout["fixtures"] = try await autopatch(api, items).compactMap { ($0 as? [String: Any])?.filter { !placementKeys.contains($0.key) } }
            var artnet = layout["artnet"] as? [String: Any] ?? ["port": 6454, "fps": 40]
            artnet["ip"] = artnetIP
            layout["artnet"] = artnet
            if let spec = outputSpec { layout["output"] = spec } else { layout.removeValue(forKey: "output") }
            layout["director"] = director
            layout["description"] = "\(fixtureCount) fixtures, made with the Mac app"
            try await api.saveRig(layout, rigName: rig, setName: setName)
            if autoMount {
                progress = "3/3 · Mounting the fixtures on \(rig)…"
                try await api.automount(rig: rig, set: setName)
            }
            model.reloadSets()
            model.selectedSet = setName
            model.selectedRig = rig
            name = setName
            rigName = rig
            step = .done
        } catch {
            self.error = error.localizedDescription
        }
        progress = ""
    }

    private func autopatch(_ api: SetupAPI, _ items: [[String: Any]]) async throws -> [Any] {
        var req = URLRequest(url: api.base.appending(path: "api/autopatch"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["fixtures": items])
        let (data, _) = try await URLSession.shared.data(for: req)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let e = obj?["error"] as? String { throw SetupAPIError.server(e) }
        return obj?["fixtures"] as? [Any] ?? []
    }
}
