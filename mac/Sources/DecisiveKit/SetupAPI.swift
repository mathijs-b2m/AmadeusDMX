// Client for the engine's setup API (decisive/web/): the same endpoints the web setup page uses.
// The app runs `decisive setup --port 8181` in the background for it.
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
    public var id: String { ip }
    enum CodingKeys: String, CodingKey { case ip, name, longName = "long_name", outputs }
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

    public func setDirector(_ value: String) async throws {
        let _: SaveResult = try await post("api/director", ["director": value])
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

    /// Auto-mount on an unsaved layout (a combined set-on-rig dict): only the placements come back.
    public func automountPlacements(layout: [String: Any], ids: [String]?, all: Bool) async throws -> [String: [String: JSONValue]] {
        struct R: Decodable { var placements: [String: [String: JSONValue]] }
        var body: [String: Any] = ["rig": layout, "all": all]
        if let ids { body["ids"] = ids }
        let r: R = try await post("api/automount", body)
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
}
