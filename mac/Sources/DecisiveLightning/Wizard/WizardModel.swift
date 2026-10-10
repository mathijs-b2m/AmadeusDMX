// The setup wizard's state and the steps that create a set through the engine's setup API.
import DecisiveKit
import Foundation
import Observation

enum Venue: String, CaseIterable, Identifiable {
    case mobile, club, stage
    var id: String { rawValue }
    var title: String {
        switch self {
        case .mobile: "Mobile DJ"
        case .club: "Club"
        case .stage: "Concert Stage"
        }
    }
    var detail: String {
        switch self {
        case .mobile: "A DJ booth with a few pars and moving heads on stands."
        case .club: "Heads on a truss over the booth, maybe lasers and an LED wall."
        case .stage: "Overhead trusses, towers, a row at the back: audience scanning."
        }
    }
    var symbol: String {
        switch self {
        case .mobile: "car.side"
        case .club: "music.note.house"
        case .stage: "theatermasks"
        }
    }
    /// width, trim height, room depth (m)
    var size: (Double, Double, Double) {
        switch self {
        case .mobile: (4, 3, 8)
        case .club: (8, 5, 15)
        case .stage: (12, 7, 25)
        }
    }
}

struct PlannedFixture: Identifiable, Hashable {
    var id = UUID()
    var entry: CatalogEntry
    var mode: String
    var modes: [String]
    var count: Int
    var mount: String
}

enum WizardStep: Int, CaseIterable {
    case welcome, engine, venue, fixtures, network, director, review, done

    var title: String {
        switch self {
        case .welcome: "Welcome"
        case .engine: "Engine"
        case .venue: "Venue"
        case .fixtures: "Fixtures"
        case .network: "Lights"
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
    var venue: Venue = .club { didSet { applyVenue() } }
    var width = 8.0
    var height = 5.0
    var depth = 15.0
    var ledWall = true

    // fixtures
    var quickRig = false
    var quickEntry: CatalogEntry?
    var quickCount = 24
    var quickLasers = 4
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

    // director
    var directors: [DirectorOption] = []
    var director = "rules"

    // create
    var name = ""
    var creating = false
    var progress = ""
    var error: String?

    init() {
        applyVenue()
        if let raw = UserDefaults.standard.string(forKey: "wizardStep"),  // -wizardStep network (testing)
           let st = WizardStep.allCases.first(where: { $0.title.lowercased() == raw || "\($0)" == raw }) {
            step = st
            if st == .network { output = .usb }
        }
    }

    private func applyVenue() {
        (width, height, depth) = venue.size
        ledWall = venue != .mobile
        quickRig = venue == .stage
        if name.isEmpty || ["mobile", "club", "stage"].contains(where: { name.hasPrefix($0) }) {
            name = venue.rawValue
        }
    }

    var fixtureCount: Int { quickRig ? quickCount + quickLasers : planned.reduce(0) { $0 + $1.count } }

    var canContinue: Bool {
        switch step {
        case .fixtures: quickRig ? quickEntry != nil : !planned.isEmpty
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
        let mount = e.type == "moving head" ? (venue == .mobile ? "stand" : "hang") : "stand"
        planned.append(PlannedFixture(entry: e, mode: modes.first ?? "", modes: modes,
                                      count: e.type == "moving head" ? 4 : 2, mount: mount))
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

    // MARK: create the set

    func create(_ model: AppModel) async {
        creating = true
        error = nil
        defer { creating = false }
        let api = model.api
        let setName = name.lowercased().replacingOccurrences(of: #"[^a-z0-9_-]+"#, with: "-", options: .regularExpression)
        do {
            progress = "Starting the engine’s setup service…"
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            if model.sets.contains(where: { $0.name == setName }) {
                throw SetupAPIError.server("A set called “\(setName)” already exists. Choose another name.")
            }
            if quickRig, let e = quickEntry {
                progress = "Building a concert rig of \(quickCount)× \(e.model)…"
                try await api.createSet(name: setName, grid: [
                    "layout": "concert", "model": e.key, "count": quickCount, "width": width, "height": height,
                    "depth": min(8, max(3, width * 0.4)), "lasers": quickLasers,   // depth of the stage, not the room
                ])
            } else {
                progress = "Creating the set…"
                try await api.createSet(name: setName)
            }
            var rig = try await api.rig()
            if !quickRig {
                var items: [[String: Any]] = []
                for p in planned {
                    progress = "Adding \(p.count)× \(p.entry.model)…"
                    let key = p.entry.isLocal ? p.entry.key : try await api.addToLibrary(p.entry.key)
                    for _ in 0..<p.count {
                        var f: [String: Any] = ["fixture": key, "mode": p.mode, "universe": 1, "mount": p.mount]
                        if p.entry.type == "laser" || key.contains("laser") {  // lasers: always above the audience
                            f["mount"] = "hang"; f["y_m"] = -1.0; f["z_m"] = max(2.6, height - 0.4)
                        } else if p.mount == "hang" {
                            f["z_m"] = max(2.4, height - 0.6)
                        }
                        items.append(f)
                    }
                }
                progress = "Patching addresses…"
                rig["fixtures"] = try await autopatch(api, items)
            }
            progress = "Saving…"
            var stage = rig["stage"] as? [String: Any] ?? [:]
            stage["width_m"] = width
            stage["ceiling_m"] = max(height + 1.5, stage["ceiling_m"] as? Double ?? 0)
            stage["room_depth_m"] = depth
            rig["stage"] = stage
            var artnet = rig["artnet"] as? [String: Any] ?? ["port": 6454, "fps": 40]
            artnet["ip"] = artnetIP
            rig["artnet"] = artnet
            if let spec = outputSpec { rig["output"] = spec } else { rig.removeValue(forKey: "output") }
            rig["director"] = director
            if ledWall { rig["screen"] = ["_note": "LED wall behind the DJ (visualiser only for now)", "width_m": min(10, width * 0.55)] }
            else { rig.removeValue(forKey: "screen") }
            if (rig["description"] as? String ?? "").isEmpty || quickRig {
                rig["description"] = "\(venue.title), \(fixtureCount) fixtures, made with the Mac app"
            }
            try await api.saveRig(rig)
            model.reloadSets()
            model.selectedSet = setName
            name = setName
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
