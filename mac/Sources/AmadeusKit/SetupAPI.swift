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
    /// An import's name is a set or rig already (POST /api/import answers 409).
    case nameTaken(String)
    public var errorDescription: String? {
        switch self {
        case .server(let s), .nameTaken(let s): s
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

    /// A GET whose answer is not JSON (a PDF): the bytes, or the engine's error.
    func data(_ path: String, query: [String: String] = [:]) async throws -> Data {
        var comps = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { comps.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var req = URLRequest(url: comps.url!)
        req.timeoutInterval = 30
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
              http.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("application/json") != true else {
            let _: [String: JSONValue] = try decode(data)  // throws the engine's error
            throw SetupAPIError.server("The engine sent nothing.")
        }
        return data
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

    /// Converts a .gdtf file (from the maker's site or your own GDTF Share account) into your fixtures; returns its
    /// library key and default mode. Your copy only: GDTF fixtures are never shipped.
    public func importGDTF(name: String, data: Data) async throws -> NewFixture {
        try await post("api/fixture/gdtf", ["name": name, "data": data.base64EncodedString()], timeout: 120)
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

    // MARK: importing a venue's documents (amadeus/web/importer.py)

    /// Starts building a set and a rig (of the same name) from documents: MVR files and patch sheets, PDFs read with
    /// AI. Returns the job to follow; a name already taken (and not `replace`) throws `.nameTaken`.
    public func startImport(name: String, files: [(name: String, data: Data)], replace: Bool) async throws -> String {
        var req = URLRequest(url: base.appending(path: "api/import"))
        req.httpMethod = "POST"
        req.timeoutInterval = 300  // a few MB of base64
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let list = files.map { ["name": $0.name, "data": $0.data.base64EncodedString()] }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["name": name, "files": list, "replace": replace] as [String: Any])
        let (data, resp) = try await URLSession.shared.data(for: req)
        if (resp as? HTTPURLResponse)?.statusCode == 409 {
            let e = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw SetupAPIError.nameTaken(e ?? "A set or rig called “\(name)” exists already")
        }
        struct R: Decodable { var job: String }
        let r: R = try decode(data)
        return r.job
    }

    /// Where an import is: its step while it runs, the report when it is done.
    public func importStatus(_ job: String) async throws -> ImportJob {
        try await get("api/import", query: ["job": job])
    }

    /// Stop an import at its next step; nothing is saved.
    public func cancelImport(_ job: String) async throws -> ImportJob {
        try await post("api/import/cancel", ["job": job])
    }

    /// The drawings under a rig (a venue's light plots), each with its corners on the rig.
    public func underlays(rig: String) async throws -> [Underlay] {
        struct R: Decodable { var underlays: [Underlay] }
        let r: R = try await get("api/underlays", query: ["rig": rig])
        return r.underlays
    }

    /// One drawing's page, as a one-page PDF.
    public func underlayPage(file: String) async throws -> Data {
        try await data("api/underlay/page", query: ["file": file])
    }

    /// Lines a drawing up again: `a` and `b` (page fractions) are the stage's front edge at stage left and stage
    /// right, `widthM` apart. The rig is saved: the drawing's fixtures (and their trusses) move with it.
    public func alignUnderlay(rig: String, id: String, a: [Double], b: [Double], widthM: Double) async throws -> Underlay {
        struct R: Decodable { var underlay: Underlay }
        let r: R = try await post("api/underlay/align", ["rig": rig, "id": id, "a": a, "b": b, "width_m": widthM])
        return r.underlay
    }

    /// Takes a drawing away from under the rig (the fixtures stay where they are); the ones left come back.
    public func removeUnderlay(rig: String, id: String) async throws -> [Underlay] {
        struct R: Decodable { var underlays: [Underlay] }
        let r: R = try await post("api/underlay/remove", ["rig": rig, "id": id])
        return r.underlays
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

    /// The rig editor's test: a moving head straight out to the audience (the reply's `dir`), whatever its placing.
    public func testLightFront(fixture: String, on: Bool, layout: [String: Any]) async throws -> LightTest {
        try await post("api/test-light", ["fixture": fixture, "rig": layout, "on": on, "point": "front"])
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

    /// Saves a hand mapping into your copy of the definition (every fixture of that model plays by it). `checked`:
    /// every channel was checked on the fixture; `wheel`, `ring`: the colour wheel's or the ring's colours were named
    /// (saved with it, as they are after a check too).
    public func saveMapping(_ m: FixtureMapping, checked: Bool = false, wheel: Bool = false, ring: Bool = false) async throws -> [String] {
        let chans = m.channels.map { ["role": $0.role, "cell": $0.cell, "value": $0.value, "attr": $0.attr] as [String: Any] }
        var body: [String: Any] = ["key": m.key, "mode": m.mode, "kind": m.kind, "channels": chans, "checked": checked]
        if checked || wheel, m.channels.contains(where: { $0.role == "color_wheel" }), !m.wheel.isEmpty {
            body["wheel"] = m.wheel.map { ["name": $0.name, "from": $0.from, "to": $0.to, "rgb": $0.rgb] as [String: Any] }
        }
        if checked || ring, m.channels.contains(where: { $0.role == "ring_color" }), !m.ring.isEmpty {
            body["ring"] = m.ring.map { ["name": $0.name, "from": $0.from, "to": $0.to, "rgb": $0.rgb] as [String: Any] }
        }
        let r: SaveResult = try await post("api/fixture/map", body)
        return r.problems ?? []
    }

    /// The common layouts a fixture without a brand is made from, the closest to `type` and `channels` first.
    public func fixtureTemplates(type: String = "", channels: Int = 0) async throws -> FixtureTemplates {
        try await get("api/fixture/templates", query: ["type": type, "channels": String(channels)])
    }

    /// Makes a fixture in your library from a template; returns its key and mode, or the problems.
    public func newFixture(manufacturer: String, model: String, template: String, channels: Int, type: String,
                           watts: Int, panDeg: Int, tiltDeg: Int) async throws -> NewFixture {
        try await post("api/fixture/new", ["manufacturer": manufacturer, "model": model, "template": template,
                                           "channels": channels, "type": type, "watts": watts,
                                           "pan_deg": panDeg, "tilt_deg": tiltDeg])
    }
}

/// An import from a venue's documents (GET /api/import): running, then done or failed with its report.
public struct ImportJob: Decodable, Sendable {
    /// A line of the report: what was found (ok), what to look at (check), what is missing.
    public struct Note: Decodable, Sendable, Hashable {
        public var level: String          // ok | check | missing
        public var text: String
        public var ids: [String]?         // the fixtures it is about
    }
    public var state: String              // running | done | failed
    public var step: String?
    public var notes: [Note]
    public var name: String?
    public var fixtures: Int?
    public var trusses: Int?
    public var underlays: Int?
    public var error: String?

    enum CodingKeys: String, CodingKey { case state, step, notes, name, fixtures, trusses, underlays, error }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = try c.decode(String.self, forKey: .state)
        step = try c.decodeIfPresent(String.self, forKey: .step)
        notes = try c.decodeIfPresent([Note].self, forKey: .notes) ?? []
        name = try c.decodeIfPresent(String.self, forKey: .name)
        fixtures = try c.decodeIfPresent(Int.self, forKey: .fixtures)
        trusses = try c.decodeIfPresent(Int.self, forKey: .trusses)
        underlays = try c.decodeIfPresent(Int.self, forKey: .underlays)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

/// A drawing under a rig (a page of a venue's light plot, rig/importer/underlay.py): where it lies on the rig.
public struct Underlay: Decodable, Sendable, Identifiable, Hashable {
    public var id: String
    public var title: String
    public var source: String?
    public var file: String               // its page (GET /api/underlay/page)
    public var set: String?               // the set it was imported with
    public var a: [Double]?               // the stage's front edge on the page (fractions from the top left): stage left
    public var b: [Double]?               // … and stage right
    public var fixtures: [String: [Double]]  // where it shows each fixture (page fractions)
    /// The plan's part of the page (a page can hold several plans): x0, y0, x1, y1 in page fractions from the top
    /// left; [0, 0, 1, 1] when the whole page.
    public var crop: [Double]
    /// That part's top-left, top-right, bottom-right and bottom-left corners on the rig (metres: x from stage left,
    /// y towards the audience), the frame trusses are in.
    public var corners: [SIMD2<Double>]

    enum CodingKeys: String, CodingKey { case id, title, source, file, set, a, b, fixtures, crop, corners }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? id
        source = try c.decodeIfPresent(String.self, forKey: .source)
        file = try c.decode(String.self, forKey: .file)
        set = try c.decodeIfPresent(String.self, forKey: .set)
        a = try c.decodeIfPresent([Double].self, forKey: .a)
        b = try c.decodeIfPresent([Double].self, forKey: .b)
        fixtures = try c.decodeIfPresent([String: [Double]].self, forKey: .fixtures) ?? [:]
        crop = (try c.decodeIfPresent([Double].self, forKey: .crop)).flatMap { $0.count == 4 ? $0 : nil } ?? [0, 0, 1, 1]
        corners = (try c.decodeIfPresent([[Double]].self, forKey: .corners) ?? []).compactMap { p in
            p.count >= 2 ? SIMD2(p[0], p[1]) : nil
        }
    }
}

/// The layouts a new fixture is made from (amadeus/library/generic.py).
public struct FixtureTemplates: Decodable, Sendable {
    public struct Kind: Decodable, Sendable, Hashable {
        public var type: String
        public var label: String
        public var kind: String
    }
    public struct Template: Decodable, Sendable, Identifiable, Hashable {
        public var id: String
        public var label: String
        public var type: String
        public var about: String
        public var channels: [String]
        public var count: Int
    }
    public var types: [Kind]
    public var templates: [Template]
}

public struct NewFixture: Decodable, Sendable {
    public var key: String?
    public var mode: String?
    public var problems: [String]?
}

/// A fixture mode as the DMX mapper shows it (amadeus/library/mapper.py).
public struct FixtureMapping: Decodable, Sendable {
    public struct Role: Decodable, Sendable, Hashable {
        public var role: String
        public var label: String
        public var group: String
        public var cell: Bool
        public var light: Bool?   // it carries light: kept under the brightness limiter when tried
        public var check: Int?    // its value while another channel is checked (the light on, the head centred)
    }
    /// An answer in the channel-by-channel check: what the channel did, and what that makes it.
    public struct Answer: Decodable, Sendable, Hashable {
        public var answer: String
        public var role: String
        public var attr: String?
        public var value: Int?
    }
    /// A colour of the wheel (or of a ring round the lens): its DMX values and how it looks.
    public struct Slot: Decodable, Sendable, Hashable, Identifiable {
        public var name: String
        public var from: Int
        public var to: Int
        public var rgb: [Double]
        public var id: Int { from }
        public var mid: Int { (from + to) / 2 }
        public init(name: String, from: Int, to: Int, rgb: [Double]) {
            self.name = name; self.from = from; self.to = to; self.rgb = rgb
        }
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
    public var made: Bool                // made here from a template: it wants the check on the fixture
    public var checked: Bool
    public var check: [Answer]
    public var wheel: [Slot]
    public var ring: [Slot]              // the colours of an LED ring or strip round the lens (a ring_color channel)

    enum CodingKeys: String, CodingKey {
        case key, name, mode, kind, kinds, roles, channels, plays, mapped, refusal, made, checked, check, wheel, ring
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        name = try c.decode(String.self, forKey: .name)
        mode = try c.decode(String.self, forKey: .mode)
        kind = try c.decode(String.self, forKey: .kind)
        kinds = try c.decode([String: String].self, forKey: .kinds)
        roles = try c.decode([Role].self, forKey: .roles)
        channels = try c.decode([Channel].self, forKey: .channels)
        plays = try c.decode(Bool.self, forKey: .plays)
        mapped = try c.decode(Bool.self, forKey: .mapped)
        refusal = try c.decode(String.self, forKey: .refusal)
        made = try c.decodeIfPresent(Bool.self, forKey: .made) ?? false
        checked = try c.decodeIfPresent(Bool.self, forKey: .checked) ?? true
        check = try c.decodeIfPresent([Answer].self, forKey: .check) ?? []
        wheel = try c.decodeIfPresent([Slot].self, forKey: .wheel) ?? []
        ring = try c.decodeIfPresent([Slot].self, forKey: .ring) ?? []
    }

    /// The values sent while channel `probe` is checked at `value`: the others hold the light on and the head in
    /// the middle (their role's check value), held ones at their value.
    public func checkValues(probe: Int, value: Int) -> [Int] {
        channels.indices.map { i in
            if i == probe { return value }
            let ch = channels[i]
            return roles.first { $0.role == ch.role }?.check ?? ch.value
        }
    }

    /// The channels that carry light (kept under the brightness limiter when tried).
    public var lightChannels: [Int] {
        let lit = Set(roles.filter { $0.light ?? ($0.group != "Position") }.map(\.role))
        return channels.indices.filter { lit.contains(channels[$0].role) }
    }

    /// What the check found channel `i` does.
    public mutating func answer(_ a: Answer, for i: Int) {
        channels[i].role = a.role
        if let attr = a.attr { channels[i].attr = attr } else if a.role == "hold" { channels[i].attr = "channel_\(channels[i].n)" }
        if let v = a.value { channels[i].value = v }
        if a.role != "hold" { channels[i].cell = 0 }
        if a.role == "color_wheel", wheel.isEmpty {  // the usual cheap wheel until its colours are named
            wheel = Self.usualWheel
        }
        if a.role == "ring_color", ring.isEmpty { ring = Self.usualRing }
    }

    public static let usualWheel: [Slot] = [
        ("open", [1, 1, 1]), ("red", [1, 0, 0]), ("green", [0, 1, 0]), ("blue", [0, 0.2, 1]),
        ("yellow", [1, 0.9, 0]), ("magenta", [1, 0, 0.8]), ("cyan", [0, 0.9, 1]), ("orange", [1, 0.45, 0]),
    ].enumerated().map { i, s in Slot(name: s.0, from: i * 16, to: i * 16 + 15, rgb: s.1) }

    /// A guess at a ring's colours until they are named (amadeus/library/generic.py RING_SLOTS).
    public static let usualRing: [Slot] = [
        ("off", [0, 0, 0]), ("red", [1, 0, 0]), ("green", [0, 1, 0]), ("blue", [0, 0.2, 1]),
        ("yellow", [1, 0.9, 0]), ("magenta", [1, 0, 0.8]), ("cyan", [0, 0.9, 1]), ("white", [1, 1, 1]),
    ].enumerated().map { i, s in Slot(name: s.0, from: i * 16, to: i * 16 + 15, rgb: s.1) }
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
    public var channels: [Int]          // first and last DMX channel (empty: no start address)
    public var dir: SIMD3<Float>?       // a pointed head: where its beam goes (world, as the feed's)

    enum CodingKeys: String, CodingKey {
        case on, seconds, output, universe, wireUniverse = "wire_universe", channels, dir
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        on = try c.decode(Bool.self, forKey: .on)
        seconds = try c.decode(Double.self, forKey: .seconds)
        output = try c.decode(String.self, forKey: .output)
        universe = try c.decode(Int.self, forKey: .universe)
        wireUniverse = try c.decodeIfPresent(Int.self, forKey: .wireUniverse)
        channels = try c.decodeIfPresent([Int].self, forKey: .channels) ?? []  // null: a fixture without an address
        dir = try c.decodeIfPresent([Float].self, forKey: .dir).flatMap { $0.count >= 3 ? SIMD3($0[0], $0[1], $0[2]) : nil }
    }

    /// "universe 1, channels 43–50 · Art-Net → 192.168.2.18:6454 (universe 1 on the wire)"
    public var summary: String {
        guard let first = channels.first else { return "universe \(universe), no start address · \(output)" }
        let last = channels.last ?? first
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
