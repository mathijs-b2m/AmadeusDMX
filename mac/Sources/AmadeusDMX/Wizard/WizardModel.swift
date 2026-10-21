// The setup wizard's state: 1. a set (where the DMX goes, then your fixtures), 2. a rig (the venue: a new one from a
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
    var channels: [String: Int] = [:]   // mode → channels (empty: not known)

    var footprint: Int { channels[mode] ?? 0 }
}

enum WizardStep: Int, CaseIterable {
    case welcome, engine, network, fixtures, rig, director, review, done

    var title: String {
        switch self {
        case .welcome: "Welcome"
        case .engine: "Engine"
        case .fixtures: "Your Fixtures"
        case .network: "DMX Output"
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
    /// The nodes the set plays on, in the order its universes go to them (several: one after the other).
    var chosenNodes: [ArtNetNode] = []
    var node: ArtNetNode? { chosenNodes.first }
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
        case .network: (output != .node || !chosenNodes.isEmpty) && (output != .usb || !usb.isEmpty || usbPort == "auto")
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
        var channels = e.modes ?? [:]
        if channels.isEmpty, let d = try? await api.details(e.key) {
            channels = Dictionary(d.modeList.map { ($0.name, $0.channels) }, uniquingKeysWith: { a, _ in a })
        }
        let modes = channels.sorted { $0.value > $1.value }.map(\.key)
        planned.append(PlannedFixture(entry: e, mode: modes.first ?? "", modes: modes,
                                      count: e.type == "moving head" ? 4 : 2, channels: channels))
    }

    /// The universes the fixtures take, packed as the engine patches them (amadeus/dmx/discover.py
    /// assign_addresses: a fixture never straddles two universes).
    var universesNeeded: Int {
        var u = planned.isEmpty ? 0 : 1, next = 1
        for p in planned where p.footprint > 0 {
            for _ in 0..<p.count {
                if next + p.footprint - 1 > 512 { u += 1; next = 1 }
                next += p.footprint
            }
        }
        return u
    }

    /// How many universes the chosen output carries (nil: no limit, or not known).
    var universesAvailable: Int? {
        switch output {
        case .visualiser, .manual: return nil
        case .usb: return 1
        case .node:
            if sacn && multicast { return nil }
            let outs = chosenNodes.map { $0.outputs ?? 0 }
            return outs.contains(0) || outs.isEmpty ? nil : outs.reduce(0, +)
        }
    }

    // MARK: network

    func discover(_ api: SetupAPI) async {
        discovering = true
        discoverError = nil
        defer { discovering = false }
        do {
            nodes = try await api.discover()
            if chosenNodes.isEmpty, let first = nodes.first { chosenNodes = [first] }
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
        case .node where chosenNodes.count > 1:
            "\(sacn ? "sACN" : "Art-Net") → \(chosenNodes.count) nodes (\(chosenNodes.map(\.ip).joined(separator: ", ")))"
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
            if output != .visualiser {
                progress = "Adding your DMX devices…"
                let fixtures = layout["fixtures"] as? [[String: Any]] ?? []
                let universes = Set(fixtures.compactMap { ($0["universe"] as? NSNumber)?.intValue }).sorted()
                if let dmx = try await addDevices(api, universes: universes) { layout["dmx"] = dmx }
            }
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

    /// The chosen output as DMX devices (config/devices.json; one already there is kept), and the set's universes
    /// over their outputs in order: node 1 output 1, output 2, …, then node 2. Returns the set's "dmx" mapping
    /// (nil: the visualiser only, nothing to add).
    private func addDevices(_ api: SetupAPI, universes: [Int]) async throws -> [String: Any]? {
        var devices = try await api.dmxDevices().devices
        var slots: [(device: String, output: Int)] = []
        /// A device there already (same kind, same address), or this one added with a free id.
        func use(_ new: DMXDevice, same: (DMXDevice) -> Bool) -> DMXDevice {
            if let d = devices.first(where: same) { return d }
            var d = new, i = 1
            while devices.contains(where: { $0.id == d.id }) { i += 1; d.id = "\(new.id)-\(i)" }
            devices.append(d)
            return d
        }
        let count = max(universes.count, 1)
        switch output {
        case .visualiser:
            return nil
        case .usb:
            var d = DMXDevice(id: "usb", name: usb.first { $0.port == usbPort }?.description ?? "USB DMX interface", type: "enttec_pro")
            d.port = usbPort; d.serial = usb.first { $0.port == usbPort }?.widgetSerial
            let u = use(d) { $0.type == "enttec_pro" && ($0.port == usbPort || ($0.serial != nil && $0.serial == d.serial)) }
            slots = [(u.id, 1)]
        case .node where sacn && multicast, .manual where sacn && multicast:  // one sender: every sACN node listens
            var d = DMXDevice(id: "sacn", name: "sACN multicast", type: "sacn")
            d.firstUniverse = 1; d.priority = 100; d.outputs = count
            let u = use(d) { $0.type == "sacn" && $0.ip == nil }
            slots = (1...max(count, u.outputCount)).map { (u.id, $0) }
        case .manual:
            var d = DMXDevice(id: "node", name: "Node \(manualIP)", type: sacn ? "sacn" : "artnet")
            d.ip = manualIP; d.outputs = max(count, 2); d.firstUniverse = sacn ? 1 : 0
            if sacn { d.priority = 100 }
            let u = use(d) { $0.type == d.type && $0.ip == manualIP }
            slots = (1...u.outputCount).map { (u.id, $0) }
        case .node:
            for n in chosenNodes {
                var d = DMXDevice(id: DMXModel.slug(n.name), name: n.longName?.isEmpty == false ? n.longName! : n.name,
                                  type: sacn ? "sacn" : "artnet")
                d.ip = n.ip; d.outputs = n.outputs ?? 2
                d.firstUniverse = sacn ? 1 : n.universes?.min() ?? 0
                if sacn { d.priority = 100 }
                let u = use(d) { $0.type == d.type && $0.ip == n.ip }
                slots += (1...u.outputCount).map { (u.id, $0) }
            }
        }
        let problems = try await api.saveDMXDevices(devices)
        if !problems.isEmpty { throw SetupAPIError.server(problems.joined(separator: "\n")) }
        var dmx: [String: Any] = [:]
        for (u, slot) in zip(universes, slots) { dmx[String(u)] = ["device": slot.device, "output": slot.output] }
        return dmx
    }

    // MARK: save and close: what is chosen so far, made for real, to go on with on the pages

    /// Whether there is anything to save before the end (an output, fixtures).
    var hasSomethingToSave: Bool { output != .visualiser || !planned.isEmpty }

    /// Saves the DMX output as your devices and the fixtures as a set of their own (on no rig yet). Returns what
    /// was saved and where to go on, nil when it failed (`error` says why).
    func saveAndClose(_ model: AppModel) async -> String? {
        creating = true
        error = nil
        defer { creating = false; progress = "" }
        let api = model.api
        do {
            progress = "Starting the engine’s setup service…"
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            var saved: [String] = []
            if planned.isEmpty {
                if output != .visualiser {
                    progress = "Adding your DMX devices…"
                    _ = try await addDevices(api, universes: [])
                    saved.append("Your DMX output (\(outputText)) is on the **DMX Output** page.")
                }
            } else {
                var setName = Self.safe(name), i = 1
                while model.sets.contains(where: { $0.name == setName }) { i += 1; setName = "\(Self.safe(name))-\(i)" }
                progress = "The set…"
                try await api.createSet(name: setName)
                var items: [[String: Any]] = []
                for p in planned {
                    progress = "Adding \(p.count)× \(p.entry.model)…"
                    let key = p.entry.isLocal ? p.entry.key : try await api.addToLibrary(p.entry.key)
                    for _ in 0..<p.count { items.append(["fixture": key, "mode": p.mode, "universe": 1]) }
                }
                progress = "Patching addresses…"
                let placementKeys = Set(RigDocument.placementKeys)
                let fixtures = try await autopatch(api, items).compactMap { ($0 as? [String: Any])?.filter { !placementKeys.contains($0.key) } }
                var layout = model.workspace?.composed(rig: "", set: setName)
                    .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
                layout["fixtures"] = fixtures
                layout["description"] = "\(fixtureCount) fixtures, made with the Mac app"
                if output != .visualiser {
                    progress = "Adding your DMX devices…"
                    let universes = Set(fixtures.compactMap { ($0["universe"] as? NSNumber)?.intValue }).sorted()
                    if let dmx = try await addDevices(api, universes: universes) { layout["dmx"] = dmx }
                }
                try await api.saveSet(layout, set: setName)
                model.reloadSets()
                model.editingSet = setName
                saved.append("Your set **\(setName)** (\(fixtureCount) fixtures) is on the **Sets** page"
                             + (output == .visualiser ? "." : ", its DMX output on the **DMX Output** page."))
                saved.append("To hang it: the **Rigs** page, pick or make a rig (New Rig…) and **Place a Set**.")
            }
            saved.append("Or start over any time with **File › New Set…**.")
            return saved.joined(separator: "\n\n")
        } catch {
            self.error = error.localizedDescription
            return nil
        }
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
