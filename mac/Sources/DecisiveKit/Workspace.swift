// Where the engine lives (the Decisive Lightning project folder with its Python environment) and the files
// the app shares with it: config/sets/*.json, config/active-set, fixtures/, .env.
import Foundation

public struct Workspace: Sendable, Equatable {
    public var root: URL

    public init(root: URL) { self.root = root }

    public var python: URL { root.appending(path: ".venv/bin/python") }
    public var setsDir: URL { root.appending(path: "config/sets") }
    public var activeSetFile: URL { root.appending(path: "config/active-set") }
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

    // MARK: sets

    public var exampleSetsDir: URL { root.appending(path: "examples/sets") }

    public func setNames() -> [String] {
        seedSetsIfEmpty()
        let files = (try? FileManager.default.contentsOfDirectory(at: setsDir, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.pathExtension == "json" }.map { $0.deletingPathExtension().lastPathComponent }.sorted()
    }

    /// A fresh checkout has no sets of its own yet: start with copies of the example sets (as the engine does).
    private func seedSetsIfEmpty() {
        let fm = FileManager.default
        let own = (try? fm.contentsOfDirectory(at: setsDir, includingPropertiesForKeys: nil)) ?? []
        guard !own.contains(where: { $0.pathExtension == "json" }),
              let examples = try? fm.contentsOfDirectory(at: exampleSetsDir, includingPropertiesForKeys: nil) else { return }
        try? fm.createDirectory(at: setsDir, withIntermediateDirectories: true)
        for file in examples where file.pathExtension == "json" {
            try? fm.copyItem(at: file, to: setsDir.appending(path: file.lastPathComponent))
        }
        if !fm.fileExists(atPath: activeSetFile.path) {
            try? "showcase\n".write(to: activeSetFile, atomically: true, encoding: .utf8)
        }
    }

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

// MARK: rig preview (before a show runs)

extension Workspace {
    public func definition(_ key: String) -> FixtureDefinition? {
        let url = root.appending(path: "fixtures/\(key).json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(FixtureDefinition.self, from: data)
    }

    public func document(_ name: String) -> RigDocument? {
        guard let data = try? Data(contentsOf: setURL(name)) else { return nil }
        return try? RigDocument(name: name, data: data)
    }

    /// The set as the visualiser would place it (the same rules as decisive/fixtures.py + geometry.py).
    public func preview(_ name: String) -> (fixtures: [FixtureInfo], stage: Stage, screen: Bool, trusses: [Truss])? {
        guard let doc = document(name) else { return nil }
        var defs: [String: FixtureDefinition] = [:]
        let els = RigElements.elements(doc) { key in
            if defs[key] == nil { defs[key] = definition(key) }
            return defs[key]
        }
        return (els, doc.stage, loadSet(name)?.hasScreen ?? false, doc.trusses)
    }
}
