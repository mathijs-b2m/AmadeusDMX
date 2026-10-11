// The engine's live feed (WebSocket, the same one the web visualiser uses): one "hello" per track the lights
// follow, then "frame" messages at ~40 fps. Mirrors decisive/player.py and decisive/live.py.
import Foundation

/// Any JSON value: for the parts of a message the app only shows (the director's free-form fields).
public enum JSONValue: Codable, Hashable, Sendable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        case .null: try c.encodeNil()
        }
    }

    public var string: String? { if case .string(let s) = self { s } else { nil } }
    public var number: Double? { if case .number(let n) = self { n } else { nil } }
    public var object: [String: JSONValue]? { if case .object(let o) = self { o } else { nil } }
    public var array: [JSONValue]? { if case .array(let a) = self { a } else { nil } }

    /// Short text for display.
    public var text: String {
        switch self {
        case .string(let s): s
        case .number(let n): n == n.rounded() ? String(Int(n)) : String(format: "%.2f", n)
        case .bool(let b): b ? "yes" : "no"
        case .null: "–"
        case .array(let a): a.map(\.text).joined(separator: ", ")
        case .object: "…"
        }
    }
}

public struct Stage: Codable, Sendable, Equatable {
    public var widthM: Double
    public var ceilingM: Double
    public var roomDepthM: Double
    /// Moving-head beams stay off the ceiling / never shine back at the stage and the DJ (on unless switched off).
    public var ceilingGuard = true
    public var backGuard = true

    enum CodingKeys: String, CodingKey {
        case widthM = "width_m", ceilingM = "ceiling_m", roomDepthM = "room_depth_m", ceilingGuard = "ceiling_guard"
        case backGuard = "back_guard"
    }

    public init(widthM: Double = 6, ceilingM: Double = 4.5, roomDepthM: Double = 6) {
        self.widthM = widthM; self.ceilingM = ceilingM; self.roomDepthM = roomDepthM
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        widthM = try c.decodeIfPresent(Double.self, forKey: .widthM) ?? 6
        ceilingM = try c.decodeIfPresent(Double.self, forKey: .ceilingM) ?? 4.5
        roomDepthM = try c.decodeIfPresent(Double.self, forKey: .roomDepthM) ?? 6
        ceilingGuard = try c.decodeIfPresent(Bool.self, forKey: .ceilingGuard) ?? true
        backGuard = try c.decodeIfPresent(Bool.self, forKey: .backGuard) ?? true
    }
}

public enum FixtureKind: String, Codable, Sendable {
    case head, laser, blinder, par, strobe, other
    public init(from decoder: Decoder) throws {
        self = FixtureKind(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .other
    }
}

/// One light element as the visualiser sees it (a fixture can have several, e.g. a multi-cell bar).
public struct FixtureInfo: Codable, Sendable, Identifiable {
    public var id: String
    public var kind: FixtureKind
    public var label: String
    public var pos: SIMD3<Double>
    public var mount: String
    public var beamDeg: Double
    public var beamWide: Double
    public var output: Double
    public var outputWide: Double
    // drawing facts (newer engines): the fixture it belongs to, its housing, rotation, cells, static aim
    public var fixture: String?
    public var body: String?
    public var rot: Double = 0
    public var size: [Double]?
    public var cells: Int?
    public var length: Double?
    public var dir: SIMD3<Double>?
    /// Base → head (moving heads): down when hanging, up on a stand, out of a truss face when side-mounted.
    public var up: SIMD3<Double>?
    /// The truss it is clamped to (nil: on the floor, or on its own stand).
    public var truss: String?

    public init(id: String, kind: FixtureKind, label: String, pos: SIMD3<Double>, mount: String, beamDeg: Double,
                beamWide: Double? = nil) {
        self.id = id; self.kind = kind; self.label = label; self.pos = pos; self.mount = mount
        self.beamDeg = beamDeg; self.beamWide = beamWide ?? beamDeg; output = 1; outputWide = 1
    }

    enum CodingKeys: String, CodingKey {
        case id, kind, label, pos, mount, beamDeg = "beam_deg", beamWide = "beam_wide", output, outputWide = "output_wide"
        case fixture, body, rot, size, cells, length, dir, up, truss
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decodeIfPresent(FixtureKind.self, forKey: .kind) ?? .other
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        let p = try c.decode([Double].self, forKey: .pos)
        pos = SIMD3(p[0], p[1], p.count > 2 ? p[2] : 0)
        mount = try c.decodeIfPresent(String.self, forKey: .mount) ?? "stand"
        beamDeg = try c.decodeIfPresent(Double.self, forKey: .beamDeg) ?? 25
        beamWide = try c.decodeIfPresent(Double.self, forKey: .beamWide) ?? beamDeg
        output = try c.decodeIfPresent(Double.self, forKey: .output) ?? 1
        outputWide = try c.decodeIfPresent(Double.self, forKey: .outputWide) ?? 1
        fixture = try c.decodeIfPresent(String.self, forKey: .fixture)
        body = try c.decodeIfPresent(String.self, forKey: .body)
        rot = try c.decodeIfPresent(Double.self, forKey: .rot) ?? 0
        size = try c.decodeIfPresent([Double].self, forKey: .size)
        cells = try c.decodeIfPresent(Int.self, forKey: .cells)
        length = try c.decodeIfPresent(Double.self, forKey: .length)
        if let d = try c.decodeIfPresent([Double].self, forKey: .dir), d.count == 3 { dir = SIMD3(d[0], d[1], d[2]) }
        if let u = try c.decodeIfPresent([Double].self, forKey: .up), u.count == 3 { up = SIMD3(u[0], u[1], u[2]) }
        truss = try c.decodeIfPresent(String.self, forKey: .truss)
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id); try c.encode(kind, forKey: .kind); try c.encode(label, forKey: .label)
        try c.encode([pos.x, pos.y, pos.z], forKey: .pos); try c.encode(mount, forKey: .mount)
        try c.encode(beamDeg, forKey: .beamDeg); try c.encode(beamWide, forKey: .beamWide)
        try c.encode(output, forKey: .output); try c.encode(outputWide, forKey: .outputWide)
    }
}

/// What the director decided for one phrase. The well-known fields are typed; everything is also kept in
/// `fields` (the vocabulary grows on the Python side without the app having to follow).
public struct Decision: Decodable, Sendable, Identifiable {
    public var phrase: Int
    public var start: Double
    public var end: Double
    public var section: String
    public var palette: String
    public var intensity: Int
    public var source: String
    public var dropScore: Double
    public var screen: String?
    public var prompt: String
    public var confidence: [String: Double]
    public var probabilities: [String: [String: Double]]
    public var fields: [String: JSONValue]

    public var id: Int { phrase }

    public init(from decoder: Decoder) throws {
        let all = try decoder.singleValueContainer().decode([String: JSONValue].self)
        fields = all
        phrase = Int(all["phrase"]?.number ?? 0)
        start = all["start"]?.number ?? 0
        end = all["end"]?.number ?? 0
        section = all["section"]?.string ?? "groove"
        palette = all["palette"]?.string ?? "cool"
        intensity = Int(all["intensity"]?.number ?? 1)
        source = all["source"]?.string ?? "rules"
        dropScore = all["drop_score"]?.number ?? 0
        screen = all["screen"]?.string
        prompt = all["prompt"]?.string ?? ""
        confidence = (all["confidence"]?.object ?? [:]).compactMapValues(\.number)
        probabilities = (all["probabilities"]?.object ?? [:]).compactMapValues { $0.object?.compactMapValues(\.number) }
    }

    public subscript(_ key: String) -> String { fields[key]?.text ?? "–" }
}

public struct Hello: Decodable, Sendable {
    public var track: String
    public var duration: Double
    public var bpm: Double
    public var director: String
    public var fixtures: [FixtureInfo]
    public var stage: Stage
    public var plan: [Decision]
    public var maxFlashHz: Double
    public var energy: [Double]
    public var screen: Bool
    public var trusses: [Truss]
    public var zones: [Zone]
    /// What kind of music (one word), where that came from (you, ai, tag, audio), and the program it gets.
    public var genre: String
    public var genreSource: String
    public var program: String
    /// The genre whose house style the plan follows: in a live set the set's genre, which can differ.
    public var style: String

    enum CodingKeys: String, CodingKey {
        case track, duration, bpm, director, fixtures, stage, plan, maxFlashHz = "max_flash_hz", energy, screen, trusses, zones
        case genre, genreSource = "genre_source", program, style
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        track = try c.decodeIfPresent(String.self, forKey: .track) ?? ""
        duration = try c.decodeIfPresent(Double.self, forKey: .duration) ?? 0
        bpm = try c.decodeIfPresent(Double.self, forKey: .bpm) ?? 120
        director = try c.decodeIfPresent(String.self, forKey: .director) ?? "rules"
        fixtures = try c.decodeIfPresent([FixtureInfo].self, forKey: .fixtures) ?? []
        stage = try c.decodeIfPresent(Stage.self, forKey: .stage) ?? Stage()
        plan = try c.decodeIfPresent([Decision].self, forKey: .plan) ?? []
        maxFlashHz = try c.decodeIfPresent(Double.self, forKey: .maxFlashHz) ?? 3
        energy = try c.decodeIfPresent([Double].self, forKey: .energy) ?? []
        screen = try c.decodeIfPresent(Bool.self, forKey: .screen) ?? false
        trusses = (try? c.decodeIfPresent([Truss].self, forKey: .trusses)) ?? []
        genre = (try? c.decodeIfPresent(String.self, forKey: .genre)) ?? ""
        genreSource = (try? c.decodeIfPresent(String.self, forKey: .genreSource)) ?? ""
        program = (try? c.decodeIfPresent(String.self, forKey: .program)) ?? ""
        style = (try? c.decodeIfPresent(String.self, forKey: .style)) ?? ""
        zones = (try? c.decodeIfPresent([Zone].self, forKey: .zones)) ?? []
    }

    /// The track title without the "Deck A: " prefix and the file extension.
    public var title: String {
        var t = track
        if let r = t.range(of: #"^Deck \w+:\s*"#, options: .regularExpression) { t.removeSubrange(r) }
        return (t as NSString).deletingPathExtension
    }

    public func phraseIndex(at t: Double) -> Int? {
        plan.lastIndex { $0.start <= t }
    }
}

/// What is ready for a track in live mode: analysis, separated instruments, AI plan.
public struct TrackStatus: Decodable, Sendable, Equatable {
    public var analysis: String?
    public var stems: String?
    public var ai: String?
    public var aiDone: Int?
    public var aiTotal: Int?
    public var lights: String?
    public var elapsed: Int?

    enum CodingKeys: String, CodingKey {
        case analysis, stems, ai, aiDone = "ai_done", aiTotal = "ai_total", lights, elapsed
    }
}

public struct DeckInfo: Decodable, Sendable, Identifiable, Equatable {
    public var deck: Int
    public var track: String
    public var vol: Double
    public var play: Bool
    public var ready: Bool
    public var status: TrackStatus?
    public var genre: String?
    public var style: String?
    public var id: Int { deck }
}

/// One laser beam: direction from the laser, colour and brightness.
public struct LaserBeam: Sendable {
    public var dir: SIMD3<Float>
    public var color: SIMD3<Float>
    public var bright: Float
}

public struct Frame: Decodable, Sendable {
    public var t: Double
    public var phrase: Int
    /// The beat position (beat index + phase), when the engine sends it.
    public var bp: Double?
    /// Per element: [dimmer, r, g, b, white, pan, tilt]
    public var fx: [[Float]]
    public var bands: [Float]
    public var beam: [String?]
    public var dirs: [SIMD3<Float>?]
    public var lz: [[LaserBeam]?]
    public var decks: [DeckInfo]?
    /// What the laser guard did this frame: laser id → "zone 'Audience'" / "blanked (…)".
    public var laserGuard: [String: String]?
    /// VirtualDJ on another computer: the link's health.
    public var link: LinkStatus?
    /// A status frame (Perform mode): time, phrase, decks; no fixtures.
    public var lite: Bool

    enum CodingKeys: String, CodingKey { case t, phrase, bp, fx, bands, beam, dirs, lz, decks, laserGuard = "guard", link, lite }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t = try c.decodeIfPresent(Double.self, forKey: .t) ?? 0
        phrase = try c.decodeIfPresent(Int.self, forKey: .phrase) ?? 0
        bp = try c.decodeIfPresent(Double.self, forKey: .bp)
        fx = try c.decodeIfPresent([[Float]].self, forKey: .fx) ?? []
        bands = try c.decodeIfPresent([Float].self, forKey: .bands) ?? []
        beam = try c.decodeIfPresent([String?].self, forKey: .beam) ?? []
        dirs = (try c.decodeIfPresent([[Float]?].self, forKey: .dirs) ?? []).map { d in
            d.flatMap { $0.count >= 3 ? SIMD3($0[0], $0[1], $0[2]) : nil }
        }
        lz = (try c.decodeIfPresent([[[Float]]?].self, forKey: .lz) ?? []).map { beams in
            beams?.compactMap { b in
                b.count >= 7 ? LaserBeam(dir: SIMD3(b[0], b[1], b[2]), color: SIMD3(b[3], b[4], b[5]), bright: b[6]) : nil
            }
        }
        decks = try c.decodeIfPresent([DeckInfo].self, forKey: .decks)
        laserGuard = try? c.decodeIfPresent([String: String].self, forKey: .laserGuard)
        link = try? c.decodeIfPresent(LinkStatus.self, forKey: .link)
        lite = try c.decodeIfPresent(Bool.self, forKey: .lite) ?? false
    }
}

/// A message on the feed.
public enum FeedMessage: Sendable {
    case hello(Hello)
    case frame(Frame)

    public static func decode(_ data: Data) -> FeedMessage? {
        struct Kind: Decodable { var type: String }
        guard let kind = try? JSONDecoder().decode(Kind.self, from: data) else { return nil }
        switch kind.type {
        case "hello": return (try? JSONDecoder().decode(Hello.self, from: data)).map(FeedMessage.hello)
        case "frame": return (try? JSONDecoder().decode(Frame.self, from: data)).map(FeedMessage.frame)
        default: return nil
        }
    }
}
