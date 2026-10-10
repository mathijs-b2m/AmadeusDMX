// Where the engine lives (the Decisive Lightning project folder with its Python environment) and the files
// the app shares with it: config/sets (your gear), config/rigs (venues), config/active-set and active-rig,
// fixtures/, .env. The file format is the engine's (decisive/rig/store.py, docs/rig-format.md).
import Foundation

public struct Workspace: Sendable, Equatable {
    public var root: URL

    public init(root: URL) { self.root = root }

    public var python: URL { root.appending(path: ".venv/bin/python") }
    public var setsDir: URL { root.appending(path: "config/sets") }
    public var rigsDir: URL { root.appending(path: "config/rigs") }
    public var activeSetFile: URL { root.appending(path: "config/active-set") }
    public var activeRigFile: URL { root.appending(path: "config/active-rig") }
    public var envFile: URL { root.appending(path: ".env") }
    public var pluginBundle: URL { root.appending(path: "vdj/build/DecisiveLink.bundle") }

    /// Looks like an engine folder: the package and a Python environment.
    public var isValid: Bool {
        let fm = FileManager.default
        return fm.fileExists(atPath: root.appending(path: "decisive/__main__.py").path) && fm.isExecutableFile(atPath: python.path)
    }

    public var hasPackage: Bool {
        FileManager.default.fileExists(atPath: root.appending(path: "decisive/__main__.py").path)
    }

    public var hasEnvKey: Bool {
        (try? String(contentsOf: envFile, encoding: .utf8))?.contains("OPENAI_API_KEY") ?? false
    }

    // MARK: first run and old files

    /// A fresh checkout (no sets yet) or old combined set files: let the engine set things up, so the
    /// migration lives in one place (decisive/rig/store.py). Fast; runs only when needed.
    public func prepare() {
        let fm = FileManager.default
        let sets = names(in: setsDir)
        let combined = sets.contains { name in
            guard let o = (try? Data(contentsOf: setURL(name))).flatMap({ try? JSONDecoder().decode([String: JSONValue].self, from: $0) })
            else { return false }
            return RigDocument.rigKeys.contains { o[$0] != nil }
        }
        guard sets.isEmpty || combined || !fm.fileExists(atPath: rigsDir.path), isValid else { return }
        let p = Process()
        p.executableURL = python
        p.arguments = ["-c", "from decisive.rig import store; store.sets.names(); store.rigs.names()"]
        p.currentDirectoryURL = root
        p.environment = ProcessInfo.processInfo.environment.merging(["DECISIVE_ROOT": root.path]) { _, new in new }
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        try? p.run()
        p.waitUntilExit()
    }

    private func names(in dir: URL) -> [String] {
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.pathExtension == "json" }.map { $0.deletingPathExtension().lastPathComponent }.sorted()
    }

    // MARK: sets (your gear)

    public func setNames() -> [String] { names(in: setsDir) }

    public var activeSet: String? {
        (try? String(contentsOf: activeSetFile, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public func setURL(_ name: String) -> URL { setsDir.appending(path: "\(name).json") }

    public func loadSet(_ name: String) -> RigFile? {
        guard let data = try? Data(contentsOf: setURL(name)) else { return nil }
        return try? JSONDecoder().decode(RigFile.self, from: data)
    }

    public func sets() -> [SetSummary] {
        let active = activeSet
        return setNames().compactMap { name in
            guard let rig = loadSet(name) else { return nil }
            return SetSummary(name: name, rig: rig, isDefault: name == active)
        }
    }

    // MARK: rigs (venues)

    public func rigNames() -> [String] { names(in: rigsDir) }

    public var activeRig: String? {
        (try? String(contentsOf: activeRigFile, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public func rigURL(_ name: String) -> URL { rigsDir.appending(path: "\(name).json") }

    public func rigs() -> [RigSummary] {
        let active = activeRig
        return rigNames().compactMap { name in
            guard let data = try? Data(contentsOf: rigURL(name)),
                  let o = try? JSONDecoder().decode([String: JSONValue].self, from: data) else { return nil }
            return RigSummary(name: name, json: o, isDefault: name == active)
        }
    }

    // MARK: a set on a rig

    /// The set placed on the rig, in the shape the engine reads (decisive/rig/store.py compose): fixtures with
    /// their places on this rig; fixtures without one wait in a row on the floor at the front ("_unplaced").
    public func composed(rig: String, set: String) -> Data? {
        guard let setData = try? Data(contentsOf: setURL(set)),
              let setDoc = try? JSONDecoder().decode([String: JSONValue].self, from: setData) else { return nil }
        let rigDoc = (try? Data(contentsOf: rigURL(rig))).flatMap { try? JSONDecoder().decode([String: JSONValue].self, from: $0) } ?? [:]
        return try? JSONEncoder().encode(RigDocument.compose(set: setDoc, rig: rigDoc, setName: set))
    }

    /// Which of the set's fixtures have a place on the rig: (mounted, all).
    public func mounted(rig: String, set: String) -> (placed: Int, total: Int) {
        let ids = loadSet(set)?.fixtures.map(\.id) ?? []
        let rigDoc = (try? Data(contentsOf: rigURL(rig))).flatMap { try? JSONDecoder().decode([String: JSONValue].self, from: $0) }
        let places = rigDoc?["placements"]?.object?[set]?.object ?? [:]
        return (ids.filter { places[$0] != nil }.count, ids.count)
    }

    // MARK: finding the engine

    /// The engine folder: the one chosen before, the one baked in at build time, or next to the app.
    public static func locate(saved: String?) -> Workspace? {
        var candidates: [URL] = []
        if let saved { candidates.append(URL(filePath: saved)) }
        if let built = Bundle.main.object(forInfoDictionaryKey: "DLEngineRoot") as? String {
            candidates.append(URL(filePath: built))
        }
        var dir = Bundle.main.bundleURL
        for _ in 0..<5 { dir = dir.deletingLastPathComponent(); candidates.append(dir) }
        return candidates.map(Workspace.init(root:)).first { $0.isValid }
    }
}

/// A set file (config/sets/NAME.json), the parts the app shows.
public struct RigFile: Codable, Sendable {
    public struct ArtNet: Codable, Sendable { public var ip: String?; public var port: Int?; public var fps: Int? }
    public struct Fixture: Codable, Sendable, Identifiable, Hashable {
        public var id: String
        public var fixture: String
        public var mode: String?
        public var universe: Int?
        public var address: Int?
        public var mount: String?
        public var x: Double?
        public var yM: Double?
        public var zM: Double?

        enum CodingKeys: String, CodingKey {
            case id, fixture, mode, universe, address, mount, x, yM = "y_m", zM = "z_m"
        }

        /// "beamz/fuze75b-beam" → "fuze75b-beam"
        public var model: String { fixture.split(separator: "/").last.map(String.init) ?? fixture }
        public var brand: String { fixture.split(separator: "/").first.map(String.init) ?? "" }
    }

    public var description: String?
    public var artnet: ArtNet?
    public var fixtures: [Fixture]
    public var stage: Stage?
    public var director: String?
    public var screen: JSONValue?
    /// Where the DMX goes (decisive/outputs.py): absent = Art-Net to `artnet.ip`.
    public var output: JSONValue?

    /// The output in words, like the engine says it.
    public var outputText: String {
        let specs: [[String: JSONValue]] = switch output {
        case .some(.object(let o)): [o]
        case .some(.array(let a)): a.compactMap(\.object)
        default: [["type": .string("artnet")]]
        }
        return specs.map { s in
            switch s["type"]?.string ?? "artnet" {
            case "sacn": "sACN → \(s["ip"]?.string ?? "multicast")"
            case "enttec_pro": "USB ENTTEC Pro → \(s["port"]?.string.map { $0 == "auto" ? "auto" : ($0 as NSString).lastPathComponent } ?? "auto")"
            default: "Art-Net → \(s["ip"]?.string ?? artnet?.ip ?? "127.0.0.1")"
            }
        }.joined(separator: " + ")
    }

    /// Only the visualiser: Art-Net to this Mac, no other output.
    public var isVirtual: Bool { output == nil && (artnet?.ip == nil || artnet?.ip == "127.0.0.1") }

    public var hasScreen: Bool {
        if case .some(.null) = screen { return false }
        if case .some(.bool(false)) = screen { return false }
        return screen != nil
    }
}

public struct SetSummary: Sendable, Identifiable, Hashable {
    public var name: String
    public var description: String
    public var fixtureCount: Int
    public var models: [(model: String, count: Int)]
    public var artnetIP: String?
    public var outputText: String
    public var isVirtual: Bool
    public var director: String
    public var hasScreen: Bool
    public var isDefault: Bool

    public var id: String { name }

    init(name: String, rig: RigFile, isDefault: Bool) {
        self.name = name
        description = rig.description ?? ""
        fixtureCount = rig.fixtures.count
        var counts: [String: Int] = [:], order: [String] = []
        for f in rig.fixtures {
            if counts[f.model] == nil { order.append(f.model) }
            counts[f.model, default: 0] += 1
        }
        models = order.map { ($0, counts[$0]!) }
        artnetIP = rig.artnet?.ip
        outputText = rig.outputText
        isVirtual = rig.isVirtual
        director = rig.director ?? "rules"
        hasScreen = rig.hasScreen
        self.isDefault = isDefault
    }

    public static func == (a: SetSummary, b: SetSummary) -> Bool {
        a.name == b.name && a.fixtureCount == b.fixtureCount && a.isDefault == b.isDefault && a.description == b.description
    }
    public func hash(into h: inout Hasher) { h.combine(name) }

}

/// A rig (config/rigs/NAME.json): a venue's structure, the parts the app lists.
public struct RigSummary: Sendable, Identifiable, Hashable {
    public var name: String
    public var description: String
    public var widthM: Double
    public var trusses: Int
    public var towers: Int
    public var hasScreen: Bool
    public var zones: Int
    /// Sets with fixtures mounted on this rig, and how many.
    public var mounted: [String: Int]
    public var isDefault: Bool

    public var id: String { name }

    init(name: String, json o: [String: JSONValue], isDefault: Bool) {
        self.name = name
        description = o["description"]?.string ?? ""
        widthM = o["stage"]?.object?["width_m"]?.number ?? 6
        let ts = o["trusses"]?.array ?? []
        towers = ts.filter { $0.object?["vertical"] == .bool(true) }.count
        trusses = ts.count - towers
        switch o["screen"] {
        case nil, .some(.null), .some(.bool(false)): hasScreen = false
        default: hasScreen = true
        }
        zones = o["zones"]?.array?.count ?? 0
        mounted = (o["placements"]?.object ?? [:]).mapValues { $0.object?.count ?? 0 }
        self.isDefault = isDefault
    }

    /// "12 m · 2 trusses · 2 towers · LED wall"
    public var summary: String {
        var parts = ["\(widthM.formatted()) m wide"]
        if trusses > 0 { parts.append("\(trusses) truss\(trusses == 1 ? "" : "es")") }
        if towers > 0 { parts.append("\(towers) tower\(towers == 1 ? "" : "s")") }
        if trusses + towers == 0 { parts.append("floor and stands") }
        if hasScreen { parts.append("LED wall") }
        return parts.joined(separator: " · ")
    }
}

// MARK: rig preview (before a show runs)

extension Workspace {
    public func definition(_ key: String) -> FixtureDefinition? {
        let url = root.appending(path: "fixtures/\(key).json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(FixtureDefinition.self, from: data)
    }

    public func document(rig: String, set: String) -> RigDocument? {
        guard let data = composed(rig: rig, set: set) else { return nil }
        return try? RigDocument(rig: rig, set: set, data: data)
    }

    /// The set on the rig as the visualiser would place it (the same rules as decisive/fixtures.py + geometry.py).
    public func preview(rig: String, set: String) -> (fixtures: [FixtureInfo], stage: Stage, screen: Bool, trusses: [Truss])? {
        guard let doc = document(rig: rig, set: set) else { return nil }
        var defs: [String: FixtureDefinition] = [:]
        let els = RigElements.elements(doc) { key in
            if defs[key] == nil { defs[key] = definition(key) }
            return defs[key]
        }
        return (els, doc.stage, doc.hasScreen, doc.trusses)
    }
}
