// Client for the engine's setup API (amadeus/web/): the same endpoints the web setup page uses.
// The app runs `amadeus setup --port 8181` in the background for it.
import Foundation

public struct CatalogEntry: Decodable, Sendable, Identifiable, Hashable {
    public var key: String
    public var manufacturer: String
    public var model: String
    public var source: String?
    public var type: String?
    public var look: String?
    public var modes: [String: Int]?
    public var id: String { key }
    public var isLocal: Bool { source == "local" || !key.contains(":") }
}

public struct CatalogDetails: Decodable, Sendable {
    public var key: String
    public var manufacturer: String?
    public var model: String?
    public var modes: [String: JSONValue]
    public var defaultMode: String?

    enum CodingKeys: String, CodingKey { case key, manufacturer, model, modes, defaultMode = "default_mode" }

    /// Mode name → channel count, sorted by size (largest first: most features).
    public var modeList: [(name: String, channels: Int)] {
        modes.map { (name: $0.key, channels: $0.value.array?.count ?? Int($0.value.number ?? 0)) }
            .sorted { $0.channels > $1.channels }
    }
}

public struct ArtNetNode: Decodable, Sendable, Identifiable, Hashable {
    public var ip: String
    public var name: String
    public var longName: String?
    public var outputs: Int?
    /// The Art-Net universes of its outputs, as the node reports them (its first output's tells where it counts from).
    public var universes: [Int]?
    public var id: String { ip }
    enum CodingKeys: String, CodingKey { case ip, name, longName = "long_name", outputs, universes }
}

public struct USBInterface: Decodable, Sendable, Identifiable, Hashable {
    public var port: String
    public var description: String?
    public var manufacturer: String?
    public var pro: Bool?
    public var widgetSerial: String?
    public var firmware: String?
    public var id: String { port }
    enum CodingKeys: String, CodingKey {
        case port, description, manufacturer, pro, widgetSerial = "widget_serial", firmware
    }
    /// Answers the DMX USB Pro protocol (ENTTEC Pro and compatibles).
    public var isPro: Bool { pro ?? false }
}

public struct DirectorOption: Decodable, Sendable, Identifiable, Hashable {
    public var value: String
    public var label: String
    public var available: Bool
    public var note: String?
    public var id: String { value }
}

public struct SaveResult: Decodable, Sendable {
    public var saved: Bool?
    public var problems: [String]?
    public var error: String?
}

public enum SetupAPIError: LocalizedError {
    case server(String)
    case notRunning
    public var errorDescription: String? {
        switch self {
        case .server(let s): s
        case .notRunning: "The engine's setup service is not running."
        }
    }
}

public struct SetupAPI: Sendable {
    public var base: URL

    public init(port: Int = 8181) { base = URL(string: "http://127.0.0.1:\(port)")! }

    public func isUp() async -> Bool {
        var req = URLRequest(url: base.appending(path: "api/sets"))
        req.timeoutInterval = 1
        return (try? await URLSession.shared.data(for: req)) != nil
    }

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        var comps = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var req = URLRequest(url: comps.url!)
        req.timeoutInterval = 30
        return try decode(try await URLSession.shared.data(for: req).0)
    }

    func post<T: Decodable>(_ path: String, _ body: Any, query: [String: String] = [:], timeout: TimeInterval = 60) async throws -> T {
        var comps = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var req = URLRequest(url: comps.url!)
        req.httpMethod = "POST"
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try decode(try await URLSession.shared.data(for: req).0)
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let e = obj["error"] as? String {
            throw SetupAPIError.server(e)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    // MARK: endpoints

    public func catalog(_ query: String, limit: Int = 25) async throws -> [CatalogEntry] {
        try await get("api/catalog", query: ["q": query, "limit": String(limit)])
    }

    public func details(_ key: String) async throws -> CatalogDetails {
        try await get("api/catalog/details", query: ["key": key])
    }

    /// Converts a QLC+/OFL entry into the local fixture library; returns its library key.
    public func addToLibrary(_ key: String) async throws -> String {
        struct R: Decodable { var key: String }
        let r: R = try await post("api/catalog/add", ["key": key])
        return r.key
    }

    /// USB DMX interfaces plugged into this Mac (probed for the DMX USB Pro protocol).
    public func usbInterfaces() async throws -> [USBInterface] {
        struct R: Decodable { var usb: [USBInterface] }
        let r: R = try await get("api/outputs")
        return r.usb
    }

    public func directors() async throws -> [DirectorOption] { try await get("api/directors") }

    /// The decision model of a set (on a rig; the active ones by default). A live show follows the change.
    public func setDirector(_ value: String, rig: String? = nil, set: String? = nil) async throws {
        let _: SaveResult = try await post("api/director", ["director": value], query: pair(rig, set))
    }

    public func discover() async throws -> [ArtNetNode] {
        struct R: Decodable { var nodes: [ArtNetNode] }
        let r: R = try await post("api/discover", [String: Any](), timeout: 20)
        return r.nodes
    }

    // MARK: sets (gear) and rigs (venues)

    /// Creates a set and makes it the active one. `grid`: a generated test rig (`layout: "concert"` with
    /// model/count/width/height/depth/lasers; its positions become a rig of the same name), or an empty set.
    public func createSet(name: String, grid: [String: Any]? = nil, copyOf: String? = nil) async throws {
        var body: [String: Any] = ["name": name]
        if let grid { body["grid"] = grid }
        if let copyOf { body["copy"] = copyOf }
        let _: [String: JSONValue] = try await post("api/sets", body)
    }

    public func makeDefault(_ name: String) async throws {
        let _: [String: JSONValue] = try await post("api/sets", ["active": name])
    }

    public func deleteSet(_ name: String) async throws {
        let _: [String: JSONValue] = try await post("api/sets", ["delete": name])
    }

    public func renameSet(_ name: String, to new: String) async throws {
        let _: [String: JSONValue] = try await post("api/sets", ["rename": name, "to": new])
    }

    /// A new rig from a template (floor, stands, booth, club, stage), or a copy of a rig; it becomes active.
    public func createRig(name: String, template: String = "booth", width: Double = 8, height: Double = 4.5,
                          depth: Double = 15, screen: Bool = false, copyOf: String? = nil) async throws {
        var body: [String: Any] = ["name": name, "template": template, "width": width, "height": height,
                                   "depth": depth, "screen": screen]
        if let copyOf { body["copy"] = copyOf }
        let _: [String: JSONValue] = try await post("api/rigs", body)
    }

    public func makeDefaultRig(_ name: String) async throws {
        let _: [String: JSONValue] = try await post("api/rigs", ["active": name])
    }

    /// Puts a set on a rig: a combination the show can run (`auto`: auto-mount its fixtures).
    public func placeSet(_ set: String, on rig: String, auto: Bool) async throws {
        let _: [String: JSONValue] = try await post("api/rigs", ["rig": rig, "place": set, "auto": auto], timeout: 120)
    }

    /// Takes a set off a rig (its placements there are forgotten).
    public func unplaceSet(_ set: String, from rig: String) async throws {
        let _: [String: JSONValue] = try await post("api/rigs", ["rig": rig, "unplace": set])
    }

    /// Renames a fixture of a set, and where it hangs on every rig.
    public func renameFixture(_ old: String, to new: String, in set: String) async throws {
        let _: [String: JSONValue] = try await post("api/fixture/rename", ["set": set, "from": old, "to": new])
    }

    /// Saves a set alone (its fixtures, patch, output): no rig is touched.
    public func saveSet(_ layout: [String: Any], set: String) async throws {
        let r: SaveResult = try await post("api/rig", layout, query: ["set": set, "setonly": "1"])
        if r.saved == false { throw SetupAPIError.server((r.problems ?? []).joined(separator: "\n")) }
    }

    /// Saves a rig's structure alone (stage, trusses, zones, LED wall), no set placed on it.
    public func saveRigStructure(_ layout: [String: Any], rig: String) async throws {
        let _: SaveResult = try await post("api/rig", layout, query: ["rig": rig, "structure": "1"])
    }

    public func deleteRig(_ name: String) async throws {
        let _: [String: JSONValue] = try await post("api/rigs", ["delete": name])
    }

    public func renameRig(_ name: String, to new: String) async throws {
        let _: [String: JSONValue] = try await post("api/rigs", ["rename": name, "to": new])
    }

    private func pair(_ rig: String?, _ set: String?) -> [String: String] {
        var q: [String: String] = [:]
        if let rig { q["rig"] = rig }
        if let set { q["set"] = set }
        return q
    }

    /// A set on a rig (the active ones by default), as raw JSON for editing.
    public func rig(rig: String? = nil, set: String? = nil) async throws -> [String: Any] {
        var comps = URLComponents(url: base.appending(path: "api/rig"), resolvingAgainstBaseURL: false)!
        let q = pair(rig, set)
        if !q.isEmpty { comps.queryItems = q.map { URLQueryItem(name: $0.key, value: $0.value) } }
        let (data, _) = try await URLSession.shared.data(from: comps.url!)
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    /// Saves a set on a rig: the engine splits it into the set file and the rig file.
    @discardableResult
    public func saveRig(_ rig: [String: Any], rigName: String? = nil, setName: String? = nil) async throws -> SaveResult {
        let r: SaveResult = try await post("api/rig", rig, query: pair(rigName, setName))
        if r.saved == false { throw SetupAPIError.server((r.problems ?? []).joined(separator: "\n")) }
        return r
    }

    /// Auto-mount on the saved rig: `ids`, else the fixtures not mounted yet (`all`: every one). Saves.
    public func automount(rig: String, set: String, ids: [String]? = nil, all: Bool = false) async throws {
        var body: [String: Any] = ["all": all]
        if let ids { body["ids"] = ids }
        let _: [String: JSONValue] = try await post("api/automount", body, query: pair(rig, set))
    }

    /// Auto-mount on an unsaved layout (a combined set-on-rig dict): the placements come back, and for a rig
    /// that had no trusses the structure it got (read from where its fixtures hang, or a standard one).
    public func automountPlacements(layout: [String: Any], ids: [String]?, all: Bool) async throws
        -> (placements: [String: [String: JSONValue]], trusses: [Truss]?) {
        struct R: Decodable { var placements: [String: [String: JSONValue]]; var trusses: [Truss]? }
        var body: [String: Any] = ["rig": layout, "all": all]
        if let ids { body["ids"] = ids }
        let r: R = try await post("api/automount", body)
        return (r.placements, r.trusses)
    }

    /// The hang sheet of a layout (a combined set-on-rig dict, saved or not): a printable HTML page saying where
    /// every fixture goes, its DMX address and labels for it.
    public func hangSheet(layout: [String: Any], set: String, rig: String) async throws -> Data {
        var req = URLRequest(url: base.appending(path: "api/hangsheet"))
        req.httpMethod = "POST"
        req.timeoutInterval = 30
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["rig": layout, "names": [set, rig]])
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("text/html") == true else {
            let _: [String: JSONValue] = try decode(data)  // throws the engine's error
            throw SetupAPIError.server("The engine sent no hang sheet.")
        }
        return data
    }

    /// The mounted fixtures of a layout put in name order on the spots they take (top1 at the first place along
    /// the rig, top2 at the next): the placements that change. Nothing moves to a new spot.
    public func inOrderPlacements(layout: [String: Any]) async throws -> [String: [String: JSONValue]] {
        struct R: Decodable { var placements: [String: [String: JSONValue]] }
        let r: R = try await post("api/automount", ["rig": layout, "order": true])
        return r.placements
    }

    /// Free start addresses for `count` fixtures of a mode: tightly packed, or on easy-to-dial numbers.
    public func suggest(key: String, mode: String, count: Int, universe: Int = 1) async throws -> [Int] {
        struct R: Decodable { var packed: [Int]?; var easy: [Int]? }
        let r: R = try await post("api/suggest", ["key": key, "mode": mode, "count": count, "universe": universe])
        return r.easy ?? r.packed ?? []
    }

    public func addFixtures(key: String, mode: String, addresses: [Int], universe: Int = 1) async throws {
        let r: SaveResult = try await post("api/rig/add",
                                           ["key": key, "mode": mode, "addresses": addresses, "universe": universe])
        if r.saved == false { throw SetupAPIError.server((r.problems ?? []).joined(separator: "\n")) }
    }

    /// Lights one fixture white for 2 s (on the real rig).
    public func identify(fixture: String, rig rigName: String? = nil, set: String? = nil) async throws {
        let rig = try await rig(rig: rigName, set: set)
        let _: [String: JSONValue] = try await post("api/identify", ["fixture": fixture, "rig": rig])
    }

    /// Keeps one fixture lit on the real rig (the show pauses), or switches it off again: is it patched and
    /// connected? It goes dark by itself after `seconds`. Lasers and smoke machines are refused.
    /// With `raw`, its channels get those values as they are (the DMX mapper: what does this channel do?);
    /// `light`: the channels (from 0) that carry light, kept under the brightness limiter.
    public func testLight(fixture: String, on: Bool, raw: [Int]? = nil, light: [Int] = [], rig rigName: String? = nil,
                          set: String? = nil) async throws -> LightTest {
        let rig = try await rig(rig: rigName, set: set)
        var body: [String: Any] = ["fixture": fixture, "rig": rig, "on": on]
        if let raw { body["raw"] = raw; body["light"] = light }
        return try await post("api/test-light", body)
    }

    /// Light one fixture of a layout (an editor's, saved or not); `point`: a moving head points its beam the way the
    /// check after hanging says.
    public func testLight(fixture: String, on: Bool, layout: [String: Any], point: Bool) async throws -> LightTest {
        try await post("api/test-light", ["fixture": fixture, "rig": layout, "on": on, "point": point])
    }

    /// The check after hanging for a layout: its fixtures in the hang sheet's order, with what to see.
    public func hangCheck(layout: [String: Any]) async throws -> [HangCheckStep] {
        struct R: Decodable { var steps: [HangCheckStep] }
        let r: R = try await post("api/hangcheck", ["rig": layout])
        return r.steps
    }

    /// The calibration that puts a head right the check found hung wrong ("mirrored", "turned", "both").
    public func hangCheckFix(layout: [String: Any], fixture: String, fix: String) async throws -> [String: JSONValue] {
        struct R: Decodable { var fields: [String: JSONValue] }
        let r: R = try await post("api/hangcheck/fix", ["rig": layout, "fixture": fixture, "fix": fix])
        return r.fields
    }

    /// A fixture mode channel by channel, for the DMX mapper.
    public func mapping(key: String, mode: String) async throws -> FixtureMapping {
        try await get("api/fixture/map", query: ["key": key, "mode": mode])
    }

    /// Saves a hand mapping into your copy of the definition (every fixture of that model plays by it).
    public func saveMapping(_ m: FixtureMapping) async throws -> [String] {
        let chans = m.channels.map { ["role": $0.role, "cell": $0.cell, "value": $0.value] as [String: Any] }
        let r: SaveResult = try await post("api/fixture/map", ["key": m.key, "mode": m.mode, "kind": m.kind, "channels": chans])
        return r.problems ?? []
    }
}

/// A fixture mode as the DMX mapper shows it (amadeus/library/mapper.py).
public struct FixtureMapping: Decodable, Sendable {
    public struct Role: Decodable, Sendable, Hashable {
        public var role: String
        public var label: String
        public var group: String
        public var cell: Bool
    }
    /// What a range of a channel's values does, from the QLC+ or OFL file.
    public struct Range: Decodable, Sendable, Hashable {
        public var lo: Int, hi: Int, what: String
        public init(from decoder: Decoder) throws {
            var c = try decoder.unkeyedContainer()
            lo = try c.decode(Int.self); hi = try c.decode(Int.self); what = try c.decode(String.self)
        }
        public var mid: Int { (lo + hi) / 2 }
    }
    public struct Channel: Decodable, Sendable, Identifiable {
        public var n: Int
        public var attr: String
        public var role: String          // a Role's role, "hold" (held at value) or "keep" (as converted)
        public var cell: Int             // 0: the whole fixture
        public var value: Int
        public var name: String
        public var ranges: [Range]
        public var id: Int { n }
    }
    public var key: String
    public var name: String
    public var mode: String
    public var kind: String
    public var kinds: [String: String]
    public var roles: [Role]
    public var channels: [Channel]
    public var plays: Bool
    public var mapped: Bool
    public var refusal: String
}

/// Where a tested fixture's DMX goes.
/// One step of the check after hanging (amadeus/rig/hangsheet.py check_steps).
public struct HangCheckStep: Decodable, Sendable, Identifiable, Hashable {
    public struct Fault: Decodable, Sendable, Hashable {
        public var fix: String   // mirrored | turned | both
        public var seen: String  // where the beam goes then, in words
    }
    public var id: String
    public var label: String
    public var model: String
    public var `where`: String
    public var facing: String
    public var moving: Bool
    public var expect: String
    public var faults: [Fault]
    public var dark: String      // why it can't be lit (a laser, a smoke machine), or ""
    public var dmx: String
}

public struct LightTest: Decodable, Sendable {
    public var on: Bool
    public var seconds: Double
    public var output: String           // the set's output, in words ("Art-Net → 192.168.2.18:6454")
    public var universe: Int
    public var wireUniverse: Int?       // the Art-Net / sACN universe it goes out as
    public var channels: [Int]          // first and last DMX channel

    enum CodingKeys: String, CodingKey {
        case on, seconds, output, universe, wireUniverse = "wire_universe", channels
    }

    /// "universe 1, channels 43–50 · Art-Net → 192.168.2.18:6454 (universe 1 on the wire)"
    public var summary: String {
        let first = channels.first ?? 0, last = channels.last ?? first
        var s = "universe \(universe), channels \(first)–\(last) · \(output)"
        if let w = wireUniverse { s += " (universe \(w) on the wire)" }
        return s
    }
}

// MARK: - DMX devices (config/devices.json): the controllers, apart from the sets

/// A DMX device you have: an Art-Net node, an sACN node or a USB interface. A set maps its universes onto them.
public struct DMXDevice: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var name: String
    public var type: String            // artnet | sacn | enttec_pro
    public var ip: String?             // Art-Net: the node; sACN: unicast to it (nil: multicast)
    public var udpPort: Int?           // Art-Net (default 6454)
    public var priority: Int?          // sACN
    public var firstUniverse: Int?     // the protocol universe of its first output (Art-Net usually 0, sACN 1)
    public var outputs: Int?           // how many DMX outputs it has
    public var port: String?           // USB: the device path, or "auto"
    public var serial: String?         // USB: the widget's serial (to recognise it)

    enum CodingKeys: String, CodingKey {
        case id, name, type, ip, udpPort = "udp_port", priority, firstUniverse = "first_universe", outputs, port, serial
    }

    public init(id: String, name: String, type: String) { self.id = id; self.name = name; self.type = type }

    public var kindText: String {
        switch type {
        case "sacn": "sACN"
        case "enttec_pro": "USB"
        default: "Art-Net"
        }
    }

    public var addressText: String {
        switch type {
        case "sacn": ip ?? "multicast"
        case "enttec_pro": port.map { $0 == "auto" ? "first one found" : ($0 as NSString).lastPathComponent } ?? "auto"
        default: ip ?? "–"
        }
    }

    /// How many outputs to offer (a USB interface has one).
    public var outputCount: Int { type == "enttec_pro" ? 1 : max(1, outputs ?? 4) }

    /// JSON for the setup API (nil fields left out).
    public var json: [String: Any] {
        var o: [String: Any] = ["id": id, "name": name, "type": type]
        if let ip, !ip.isEmpty { o["ip"] = ip }
        if let udpPort { o["udp_port"] = udpPort }
        if let priority { o["priority"] = priority }
        if let firstUniverse { o["first_universe"] = firstUniverse }
        if let outputs { o["outputs"] = outputs }
        if let port { o["port"] = port }
        if let serial, !serial.isEmpty { o["serial"] = serial }
        return o
    }
}

extension SetupAPI {
    /// Your DMX devices, and the USB DMX interfaces plugged in now.
    public func dmxDevices() async throws -> (devices: [DMXDevice], usb: [USBInterface]) {
        struct R: Decodable { var devices: [DMXDevice]; var usb: [USBInterface] }
        let r: R = try await get("api/devices")
        return (r.devices, r.usb)
    }

    /// Saves your DMX devices; returns the problems (nothing saved if any).
    public func saveDMXDevices(_ devices: [DMXDevice]) async throws -> [String] {
        struct R: Decodable { var ok: Bool; var problems: [String] }
        let r: R = try await post("api/devices", ["devices": devices.map(\.json)])
        return r.problems
    }
}
