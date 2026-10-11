// A set on a rig, editable: the rig's trusses, stage and zones, and where every fixture of the set sits on it.
// It is the combined view the engine reads (decisive/rig/store.py compose); saving goes through the engine's
// setup API, which splits it back into the set file (the gear) and the rig file (the venue and placements).
// Unknown keys are kept as they are, so the engine and the web UI keep working.
//
// Placement model (shared with decisive/geometry.py):
//   fixture.x       position across the stage as a fraction of stage.width_m
//   fixture.y_m     towards the audience (y = 0: the stage's front edge), z_m: height
//   fixture.rot_deg the fixture turned counter-clockwise seen from above; a bar runs along +x at 0°
//   fixture.aim     [azimuth°, elevation°] for fixtures without motors (pars, bars, strobes, blinders)
//   fixture.mount   hang (under a truss) | stand (on top / on a stand) | floor
//   fixture.truss, truss_pos_m, truss_side: the truss it is clamped to, where along it, and on which of the
//                   box truss's four sides: under | top | front (audience side) | back (editor bookkeeping)
import Foundation
import simd

public struct Truss: Codable, Sendable, Identifiable, Equatable, Hashable {
    public var id: String
    public var type: String = "quatro"
    public var lengthM: Double
    public var xM: Double
    public var yM: Double
    public var zM: Double
    public var rotDeg: Double = 0
    public var vertical: Bool = false

    enum CodingKeys: String, CodingKey {
        case id, type, lengthM = "length_m", xM = "x_m", yM = "y_m", zM = "z_m", rotDeg = "rot_deg", vertical
    }

    public init(id: String, lengthM: Double, xM: Double, yM: Double, zM: Double, rotDeg: Double = 0, vertical: Bool = false) {
        self.id = id; self.lengthM = lengthM; self.xM = xM; self.yM = yM; self.zM = zM; self.rotDeg = rotDeg
        self.vertical = vertical
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? "quatro"
        lengthM = try c.decodeIfPresent(Double.self, forKey: .lengthM) ?? 2
        xM = try c.decodeIfPresent(Double.self, forKey: .xM) ?? 0
        yM = try c.decodeIfPresent(Double.self, forKey: .yM) ?? -1
        zM = try c.decodeIfPresent(Double.self, forKey: .zM) ?? 3
        rotDeg = try c.decodeIfPresent(Double.self, forKey: .rotDeg) ?? 0
        vertical = try c.decodeIfPresent(Bool.self, forKey: .vertical) ?? false
    }

    /// Unit vector along the truss (horizontal trusses).
    public var axis: SIMD2<Double> { SIMD2(cos(rotDeg * .pi / 180), sin(rotDeg * .pi / 180)) }

    /// A point on the truss: `u` metres from its centre along it (or above its base, for a tower).
    public func point(_ u: Double) -> SIMD3<Double> {
        if vertical { return SIMD3(xM, yM, zM - lengthM / 2 + u) }
        return SIMD3(xM + axis.x * u, yM + axis.y * u, zM)
    }

    /// Where a point (seen from above) lands on the truss, and how far it is from it.
    public func project(_ p: SIMD2<Double>) -> (u: Double, distance: Double) {
        if vertical { return (0, simd_length(p - SIMD2(xM, yM))) }
        let d = p - SIMD2(xM, yM)
        let u = max(-lengthM / 2, min(lengthM / 2, simd_dot(d, axis)))
        let q = SIMD2(xM, yM) + axis * u
        return (u, simd_length(p - q))
    }
}

/// A fixture definition (fixtures/BRAND/MODEL.json), the parts placement and drawing need.
public struct FixtureDefinition: Decodable, Sendable {
    public struct Physical: Decodable, Sendable {
        public var beamDeg: Double?
        public var beamDegMax: Double?
        public var lumens: Double?
        public var sizeMM: [Double]?
        enum CodingKeys: String, CodingKey { case beamDeg = "beam_deg", beamDegMax = "beam_deg_max", lumens, sizeMM = "size_mm" }
    }
    public var manufacturer: String
    public var model: String
    public var kind: String
    public var physical: Physical?
    public var modes: [String: [[String: JSONValue]]]

    enum CodingKeys: String, CodingKey { case manufacturer, model, kind, physical, modes }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        manufacturer = try c.decodeIfPresent(String.self, forKey: .manufacturer) ?? ""
        model = try c.decodeIfPresent(String.self, forKey: .model) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "par"
        physical = try c.decodeIfPresent(Physical.self, forKey: .physical)
        modes = (try? c.decodeIfPresent([String: [[String: JSONValue]]].self, forKey: .modes)) ?? [:]
    }

    public var name: String { "\(manufacturer) \(model)" }
    public var isMoving: Bool { kind == "moving_head" || kind == "moving_bar" }
    /// Housing size in metres (width = along a bar, height, depth).
    public var size: SIMD3<Double> {
        guard let s = physical?.sizeMM, s.count == 3, s.allSatisfy({ $0 > 0 }) else {
            return kind == "par_bar" || kind == "moving_bar" ? [1.0, 0.15, 0.1] : [0.3, 0.35, 0.25]
        }
        return SIMD3(s[0], s[1], s[2]) / 1000
    }
    public var elementKind: FixtureKind {
        switch kind {
        case "moving_head", "moving_bar": .head
        case "laser": .laser
        case "blinder": .blinder
        case "strobe": .strobe
        default: .par
        }
    }
    /// Cells per mode (1 = the fixture is one element).
    public func cells(_ mode: String) -> Int {
        let heads = Set((modes[mode] ?? []).compactMap { $0["head"]?.number }.map(Int.init))
        return max(1, heads.count)
    }
    public func channels(_ mode: String) -> Int { modes[mode]?.count ?? 0 }
    public var defaultMode: String { modes.max { $0.value.count < $1.value.count }?.key ?? "" }
}

public struct PlacedFixture: Identifiable, Equatable, Sendable {
    public var id: String
    public var key: String
    public var mode: String
    public var universe: Int
    public var address: Int
    public var mount: String
    public var x: Double          // fraction of the stage width
    public var yM: Double
    public var zM: Double
    public var rotDeg: Double
    public var aim: SIMD2<Double>?  // azimuth, elevation (fixtures without motors)
    public var truss: String?
    public var trussPos: Double?
    public var side: String?        // under | top | front | back (on a truss)
    public var mountRoll: Double?   // 90: on the front face, 270: on the back face (rolled about the truss)
    /// Not mounted on this rig yet: it waits on the floor at the front (the engine's waiting spot).
    public var waiting = false

    /// Base → head, as the engine sees it (geometry.mount_up).
    public var up: SIMD3<Double> {
        let down = mount == "hang"
        guard down, let roll = mountRoll, roll != 0 else { return [0, 0, down ? -1 : 1] }
        let t = roll * .pi / 180, r = rotDeg * .pi / 180
        let n = SIMD3(-sin(r), cos(r), 0)               // R(-z) = -z cos t + n sin t
        return SIMD3(0, 0, -cos(t)) + n * sin(t)
    }

    public func position(width: Double) -> SIMD3<Double> { SIMD3(x * width, yM, zM) }

    public init(id: String, key: String, mode: String, universe: Int, address: Int, mount: String, x: Double, yM: Double,
                zM: Double, rotDeg: Double, aim: SIMD2<Double>?, truss: String?, trussPos: Double?, side: String? = nil,
                mountRoll: Double? = nil) {
        self.id = id; self.key = key; self.mode = mode; self.universe = universe; self.address = address
        self.mount = mount; self.x = x; self.yM = yM; self.zM = zM; self.rotDeg = rotDeg; self.aim = aim
        self.truss = truss; self.trussPos = trussPos; self.side = side; self.mountRoll = mountRoll
    }
}

/// A set on a rig, editable. `raw` keeps everything the editor doesn't touch.
public struct RigDocument: Equatable {
    public var rig: String
    public var set: String
    public var raw: [String: JSONValue]
    public var trusses: [Truss]
    public var fixtures: [PlacedFixture]
    public var zones: [Zone]
    public var stage: Stage

    /// What belongs to the rig rather than the set, and a fixture's fields that say where it is
    /// (decisive/rig/store.py: RIG_KEYS, PLACEMENT_KEYS).
    public static let rigKeys = ["stage", "trusses", "zones", "screen"]
    public static let placementKeys = ["x", "y_m", "z_m", "mount", "rot_deg", "aim", "truss", "truss_pos_m", "truss_side",
                                       "mount_roll_deg", "reverse", "width", "group"]
    public static let unplacedKey = "_unplaced"

    /// The set placed on the rig (decisive/rig/store.py compose).
    public static func compose(set: [String: JSONValue], rig: [String: JSONValue], setName: String) -> [String: JSONValue] {
        var out = set.filter { !rigKeys.contains($0.key) }
        for k in rigKeys { if let v = rig[k] { out[k] = v } }
        let places = rig["placements"]?.object?[setName]?.object ?? [:]
        var fixtures = (out["fixtures"]?.array ?? []).compactMap(\.object)
        let waiting = fixtures.filter { places[$0["id"]?.string ?? ""] == nil }.count
        var k = 0
        for i in fixtures.indices {
            for key in placementKeys { fixtures[i][key] = nil }
            if let p = places[fixtures[i]["id"]?.string ?? ""]?.object {
                fixtures[i].merge(p) { _, new in new }
            } else {
                let spot: [String: JSONValue] = ["x": .number(((Double(k) + 1) / Double(waiting + 1) * 10000).rounded() / 10000),
                                                 "y_m": .number(-0.3), "z_m": .number(0.25), "mount": .string("floor")]
                fixtures[i].merge(spot) { _, new in new }
                fixtures[i][unplacedKey] = .object(spot)
                k += 1
            }
        }
        out["fixtures"] = .array(fixtures.map(JSONValue.object))
        return out
    }

    public init(rig: String, set: String, data: Data) throws {
        self.rig = rig
        self.set = set
        raw = try JSONDecoder().decode([String: JSONValue].self, from: data)
        stage = (raw["stage"]).flatMap { try? JSONDecoder().decode(Stage.self, from: JSONEncoder().encode($0)) } ?? Stage()
        trusses = (raw["trusses"]).flatMap { try? JSONDecoder().decode([Truss].self, from: JSONEncoder().encode($0)) } ?? []
        zones = (raw["zones"]).flatMap { try? JSONDecoder().decode([Zone].self, from: JSONEncoder().encode($0)) } ?? []
        let mounts: [String: (Double, Double)] = ["stand": (-0.6, 1.8), "hang": (-1.0, 3.0), "floor": (-0.4, 0.3)]
        fixtures = (raw["fixtures"]?.array ?? []).compactMap { v in
            guard let o = v.object, let id = o["id"]?.string, let key = o["fixture"]?.string else { return nil }
            let mount = o["mount"]?.string ?? "stand"
            let d = mounts[mount] ?? (-0.6, 1.8)
            let aim = o["aim"]?.array.flatMap { a in a.count == 2 ? SIMD2(a[0].number ?? 0, a[1].number ?? 0) : nil }
            var f = PlacedFixture(id: id, key: key, mode: o["mode"]?.string ?? "", universe: Int(o["universe"]?.number ?? 1),
                                  address: Int(o["address"]?.number ?? 1), mount: mount, x: o["x"]?.number ?? 0.5,
                                  yM: o["y_m"]?.number ?? d.0, zM: o["z_m"]?.number ?? d.1, rotDeg: o["rot_deg"]?.number ?? 0,
                                  aim: aim, truss: o["truss"]?.string, trussPos: o["truss_pos_m"]?.number,
                                  side: o["truss_side"]?.string, mountRoll: o["mount_roll_deg"]?.number)
            f.waiting = o[Self.unplacedKey] != nil
            return f
        }
    }

    public var width: Double { stage.widthM }
    public var label: String { "\(set) on \(rig)" }
    public var waitingCount: Int { fixtures.filter(\.waiting).count }

    public var hasScreen: Bool {
        switch raw["screen"] {
        case nil, .some(.null), .some(.bool(false)): false
        default: true
        }
    }

    /// The set as JSON, with the editor's changes merged into what was there.
    public func json() throws -> Data {
        var out = raw
        out["trusses"] = trusses.isEmpty ? nil : try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(trusses))
        out["zones"] = zones.isEmpty ? nil : try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(zones))
        let old = Dictionary((raw["fixtures"]?.array ?? []).compactMap { v -> (String, [String: JSONValue])? in
            guard let o = v.object, let id = o["id"]?.string else { return nil }
            return (id, o)
        }, uniquingKeysWith: { a, _ in a })
        out["fixtures"] = .array(fixtures.map { f in
            var o = old[f.id] ?? [:]
            let r = { (v: Double, k: Double) in (v * k).rounded() / k }
            if f.waiting {  // not mounted: its waiting spot, marked as such (the engine doesn't save it as a place)
                for k in Self.placementKeys { o[k] = nil }
                let spot: [String: JSONValue] = ["x": .number(r(f.x, 10000)), "y_m": .number(r(f.yM, 1000)),
                                                 "z_m": .number(r(f.zM, 1000)), "mount": .string(f.mount)]
                o.merge(spot) { _, new in new }
                o[Self.unplacedKey] = .object(spot)
                o["id"] = .string(f.id); o["fixture"] = .string(f.key); o["mode"] = .string(f.mode)
                o["universe"] = .number(Double(f.universe)); o["address"] = .number(Double(f.address))
                return .object(o)
            }
            o[Self.unplacedKey] = nil
            o["id"] = .string(f.id); o["fixture"] = .string(f.key); o["mode"] = .string(f.mode)
            o["universe"] = .number(Double(f.universe)); o["address"] = .number(Double(f.address))
            o["mount"] = .string(f.mount)
            o["x"] = .number(r(f.x, 10000)); o["y_m"] = .number(r(f.yM, 1000)); o["z_m"] = .number(r(f.zM, 1000))
            o["rot_deg"] = f.rotDeg == 0 ? nil : .number(r(f.rotDeg, 10))
            o["aim"] = f.aim.map { .array([.number(r($0.x, 10)), .number(r($0.y, 10))]) }
            o["truss"] = f.truss.map(JSONValue.string)
            o["truss_pos_m"] = f.trussPos.map { .number(r($0, 1000)) }
            o["truss_side"] = f.truss == nil ? nil : f.side.map(JSONValue.string)
            o["mount_roll_deg"] = (f.mountRoll ?? 0) == 0 ? nil : .number(f.mountRoll!)
            return .object(o)
        })
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try enc.encode(out)
    }
}

// MARK: - elements, as the engine expands them (decisive/fixtures.py expand + geometry.position)

public enum RigElements {
    static let staticAim: [FixtureKind: SIMD2<Double>] = [.par: [0, 80], .blinder: [0, 7], .strobe: [0, 8]]

    public static func direction(azimuth: Double, elevation: Double) -> SIMD3<Double> {
        let a = azimuth * .pi / 180, e = elevation * .pi / 180
        return SIMD3(cos(e) * sin(a), cos(e) * cos(a), sin(e))
    }

    /// Visualiser elements for a set (cells of bars along the bar), with the extra drawing facts.
    public static func elements(_ doc: RigDocument, definitions: (String) -> FixtureDefinition?) -> [FixtureInfo] {
        var out: [FixtureInfo] = []
        for f in doc.fixtures {
            let def = definitions(f.key)
            let kind = def?.elementKind ?? .par
            let n = def?.cells(f.mode) ?? 1
            let length = def?.size.x ?? 1
            let base = f.position(width: doc.width)
            let r = f.rotDeg * .pi / 180
            for k in 0..<n {
                let off = n == 1 ? 0 : -length / 2 + length * (Double(k) + 0.5) / Double(n)
                let pos = base + SIMD3(off * cos(r), off * sin(r), 0)
                var info = FixtureInfo(id: n == 1 ? f.id : "\(f.id).\(k + 1)", kind: kind, label: def?.name ?? f.key,
                                       pos: pos, mount: f.mount, beamDeg: def?.physical?.beamDeg ?? 25,
                                       beamWide: def?.physical?.beamDegMax)
                info.fixture = f.id
                info.body = def?.kind
                info.rot = f.rotDeg
                info.truss = f.truss
                if kind == .head { info.up = f.up }
                info.size = def.map { [$0.size.x, $0.size.y, $0.size.z] }
                if n > 1 { info.cells = n; info.length = length }
                if kind == .par || kind == .blinder || kind == .strobe {
                    let aim = f.aim ?? staticAim[kind] ?? [0, 80]
                    info.dir = direction(azimuth: aim.x - f.rotDeg, elevation: aim.y)
                }
                out.append(info)
            }
        }
        return out
    }
}

// MARK: - zones: where beams may (not) go

/// A zone in the room that limits beams (`zones` in the set file; decisive/zones.py enforces them).
///
///   kind  avoid     artistic: moving-head beams stay off it (a wall, the set, the LED wall, a VIP corner)
///         keep_in   artistic: moving-head beams land only inside it (e.g. the dance floor and the sky)
///         laser_out safety: no laser beam may enter it (with a safety margin); the engine lifts/shrinks
///                   the pattern, or blanks the laser. On top of the laser's masking plate, never instead.
///   shape rect  a flat rectangle: `size` = [width, height], turned by `rot_deg` (around z) and tilted by
///               `tilt_deg` (0 = upright, facing the audience; 90 = lying flat, like a ceiling over the crowd)
///         box   `size` = [width, depth, height], turned by `rot_deg`
public struct Zone: Codable, Sendable, Identifiable, Equatable, Hashable {
    public var id: String
    public var name: String
    public var kind: String          // avoid | keep_in | laser_out
    public var shape: String         // rect | box
    public var center: [Double]      // x, y, z (m)
    public var size: [Double]
    public var rotDeg: Double = 0
    public var tiltDeg: Double = 0
    public var marginDeg: Double = 3
    public var applies: String = "auto"  // auto (heads for avoid/keep_in, lasers for laser_out) | heads | lasers | all
    public var enabled: Bool = true

    enum CodingKeys: String, CodingKey {
        case id, name, kind, shape, center, size, rotDeg = "rot_deg", tiltDeg = "tilt_deg", marginDeg = "margin_deg"
        case applies, enabled
    }

    public init(id: String, name: String, kind: String, shape: String, center: SIMD3<Double>, size: [Double],
                rotDeg: Double = 0, tiltDeg: Double = 0) {
        self.id = id; self.name = name; self.kind = kind; self.shape = shape
        self.center = [center.x, center.y, center.z]; self.size = size; self.rotDeg = rotDeg; self.tiltDeg = tiltDeg
        marginDeg = kind == "laser_out" ? 5 : 2
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "avoid"
        shape = try c.decodeIfPresent(String.self, forKey: .shape) ?? "rect"
        center = try c.decodeIfPresent([Double].self, forKey: .center) ?? [0, 0, 2]
        size = try c.decodeIfPresent([Double].self, forKey: .size) ?? [2, 2, 2]
        rotDeg = try c.decodeIfPresent(Double.self, forKey: .rotDeg) ?? 0
        tiltDeg = try c.decodeIfPresent(Double.self, forKey: .tiltDeg) ?? 0
        marginDeg = try c.decodeIfPresent(Double.self, forKey: .marginDeg) ?? 3
        applies = try c.decodeIfPresent(String.self, forKey: .applies) ?? "auto"
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
    }

    public var centerV: SIMD3<Double> {
        get { SIMD3(center[0], center[1], center.count > 2 ? center[2] : 0) }
        set { center = [newValue.x, newValue.y, newValue.z] }
    }
    public var isSafety: Bool { kind == "laser_out" }

    /// The zone's own axes: u along its width, v along its height (rect) / depth (box), n its normal (rect) / up (box).
    public var axes: (u: SIMD3<Double>, v: SIMD3<Double>, n: SIMD3<Double>) {
        let r = rotDeg * .pi / 180
        let u = SIMD3(cos(r), sin(r), 0)
        if shape == "box" { return (u, SIMD3(-sin(r), cos(r), 0), SIMD3(0, 0, 1)) }
        let t = tiltDeg * .pi / 180
        let facing = SIMD3(-sin(r), cos(r), 0)                    // upright: faces the audience
        let n = facing * cos(t) + SIMD3(0, 0, 1) * sin(t)          // tilted back to lie flat (normal up)
        let v = SIMD3(0, 0, 1) * cos(t) - facing * sin(t)
        return (u, v, n)
    }

    /// The rectangle's four corners (rect), or the box's eight corners.
    public var corners: [SIMD3<Double>] {
        let (u, v, n) = axes, c = centerV
        if shape == "box" {
            let w = size[0] / 2, d = (size.count > 1 ? size[1] : 1) / 2, h = (size.count > 2 ? size[2] : 1) / 2
            return [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
                .map { c + u * (Double($0.0) * w) + v * (Double($0.1) * d) + n * (Double($0.2) * h) }
        }
        let w = size[0] / 2, h = (size.count > 1 ? size[1] : 1) / 2
        return [c - u * w - v * h, c + u * w - v * h, c + u * w + v * h, c - u * w + v * h]
    }

    /// Where a ray enters the zone (distance), or nil.
    public func hit(_ o: SIMD3<Double>, _ d: SIMD3<Double>) -> Double? {
        let (u, v, n) = axes, c = centerV
        if shape == "box" {  // slab test in the box's frame
            let p = o - c
            let lo = [simd_dot(p, u), simd_dot(p, v), simd_dot(p, n)], dd = [simd_dot(d, u), simd_dot(d, v), simd_dot(d, n)]
            let half = [size[0] / 2, (size.count > 1 ? size[1] : 1) / 2, (size.count > 2 ? size[2] : 1) / 2]
            var t0 = -Double.infinity, t1 = Double.infinity
            for k in 0..<3 {
                if abs(dd[k]) < 1e-9 { if abs(lo[k]) > half[k] { return nil }; continue }
                var a = (-half[k] - lo[k]) / dd[k], b = (half[k] - lo[k]) / dd[k]
                if a > b { swap(&a, &b) }
                t0 = max(t0, a); t1 = min(t1, b)
                if t0 > t1 { return nil }
            }
            return t1 < 0 ? nil : max(t0, 0)
        }
        let den = simd_dot(d, n)
        guard abs(den) > 1e-9 else { return nil }
        let t = simd_dot(c - o, n) / den
        guard t > 0 else { return nil }
        let q = o + d * t - c
        return abs(simd_dot(q, u)) <= size[0] / 2 && abs(simd_dot(q, v)) <= (size.count > 1 ? size[1] : 1) / 2 ? t : nil
    }
}
