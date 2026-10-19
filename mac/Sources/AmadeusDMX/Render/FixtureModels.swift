// The fixtures as they look: a moving head is a base, a yoke that pans and a head that tilts to where its beam
// points; a moving bar tilts on its yoke ends; pixel bars, pars, strobes, blinders and lasers have their
// housings, and every lens glows in the colour the fixture plays. Sized from the fixture's real dimensions.
//
// What never moves (bases, bar housings, cans, boxes) is built once with the scenery; the moving parts and the
// lenses are built every frame from the show's frame (beam directions, colours).
import AmadeusKit
import simd

/// An orthonormal frame: x across, y the other way across, z "up" (the part's own axis).
struct Basis {
    var x: SIMD3<Float>, y: SIMD3<Float>, z: SIMD3<Float>

    /// z along `axis`, x as close to `hint` as possible.
    static func along(_ axis: SIMD3<Float>, hint: SIMD3<Float>) -> Basis {
        let z = simd_normalize(axis)
        var x = hint - z * simd_dot(hint, z)
        if simd_length(x) < 1e-4 { x = abs(z.z) < 0.9 ? simd_cross([0, 0, 1], z) : [1, 0, 0] }
        x = simd_normalize(x)
        return Basis(x: x, y: simd_cross(z, x), z: z)
    }
}

/// Triangles for the solid pipeline.
struct MeshBuilder {
    var v: [SolidVertex] = []

    mutating func quad(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ c: SIMD3<Float>, _ d: SIMD3<Float>, _ n: SIMD3<Float>,
                       _ col: SIMD4<Float>) {
        for p in [a, b, c, a, c, d] { v.append(SolidVertex(pos: p, normal: n, color: col)) }
    }

    /// A box around `c`, its edges along the basis; size = (x, y, z).
    mutating func box(_ c: SIMD3<Float>, _ b: Basis, _ size: SIMD3<Float>, _ color: SIMD3<Float>, emissive: Float = 0) {
        let col = SIMD4(color, emissive), h = size / 2
        func P(_ i: Float, _ j: Float, _ k: Float) -> SIMD3<Float> { c + b.x * (i * h.x) + b.y * (j * h.y) + b.z * (k * h.z) }
        quad(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), b.z, col)
        quad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), -b.z, col)
        quad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), b.y, col)
        quad(P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), P(-1, -1, -1), -b.y, col)
        quad(P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), P(1, -1, -1), b.x, col)
        quad(P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), -b.x, col)
    }

    /// A cylinder around `c` along `axis` (unit), with caps.
    mutating func cylinder(_ c: SIMD3<Float>, _ axis: SIMD3<Float>, radius r: Float, length L: Float,
                           _ color: SIMD3<Float>, emissive: Float = 0, segments n: Int = 16, caps: Bool = true) {
        let b = Basis.along(axis, hint: [1, 0, 0]), col = SIMD4(color, emissive)
        let top = c + b.z * (L / 2), bottom = c - b.z * (L / 2)
        for k in 0..<n {
            let a0 = Float(k) / Float(n) * 2 * .pi, a1 = Float(k + 1) / Float(n) * 2 * .pi
            let r0 = b.x * cos(a0) + b.y * sin(a0), r1 = b.x * cos(a1) + b.y * sin(a1)
            quad(bottom + r0 * r, bottom + r1 * r, top + r1 * r, top + r0 * r, simd_normalize(r0 + r1), col)
            if caps {
                for p in [top, top + r0 * r, top + r1 * r] { v.append(SolidVertex(pos: p, normal: b.z, color: col)) }
                for p in [bottom, bottom + r1 * r, bottom + r0 * r] { v.append(SolidVertex(pos: p, normal: -b.z, color: col)) }
            }
        }
    }

    /// A flat disc facing `normal`.
    mutating func disc(_ c: SIMD3<Float>, _ normal: SIMD3<Float>, radius r: Float, _ color: SIMD3<Float>,
                       emissive: Float = 0, segments n: Int = 16) {
        let b = Basis.along(normal, hint: [1, 0, 0]), col = SIMD4(color, emissive)
        for k in 0..<n {
            let a0 = Float(k) / Float(n) * 2 * .pi, a1 = Float(k + 1) / Float(n) * 2 * .pi
            for p in [c, c + (b.x * cos(a0) + b.y * sin(a0)) * r, c + (b.x * cos(a1) + b.y * sin(a1)) * r] {
                v.append(SolidVertex(pos: p, normal: b.z, color: col))
            }
        }
    }
}

/// The rig's fixtures as models.
final class FixtureModels {
    enum Shape { case beamHead, spotHead, washHead, movingBar, curveBar, parBar, par, strobe, blinder, laser, smoke }

    struct Unit {
        var id: String
        var shape: Shape
        var idx: [Int]             // its elements (cells) in the hello's fixture list
        var p: SIMD3<Float>        // centre (a head: the tilt axis)
        var up: SIMD3<Float>       // base → head (heads), the static aim (others)
        var across: SIMD3<Float>   // along a bar, across a head's base
        var length: Float          // a bar's length
        var scale: Float           // the model's size against a typical fixture of its kind
        var size: SIMD3<Float>?    // real housing size (m) when known
        var selected: Bool
        var hovered = false
        var onStand = false        // standing in the air, not on a truss: it has its own tripod stand
    }

    static let bodyColor: SIMD3<Float> = [0.075, 0.078, 0.088]
    static let yokeColor: SIMD3<Float> = [0.095, 0.098, 0.11]
    static let glassColor: SIMD3<Float> = [0.05, 0.06, 0.075]
    static let pick: SIMD3<Float> = [0.25, 0.55, 1.0]
    static let lit: SIMD3<Float> = [0.35, 0.45, 0.6]  // under the pointer
    static let standColor: SIMD3<Float> = [0.13, 0.135, 0.15]

    private(set) var units: [Unit] = []
    private var tiltAxis: [String: SIMD3<Float>] = [:]   // the last tilt axis per head (when the beam is along the pan axis)
    private let positions: [SIMD3<Float>]

    init(fixtures: [FixtureInfo], selected: Set<String>) {
        positions = fixtures.map { SIMD3<Float>(Float($0.pos.x), Float($0.pos.y), Float($0.pos.z)) }
        var groups: [String: [Int]] = [:], order: [String] = []
        for (i, f) in fixtures.enumerated() {
            let k = f.fixture ?? f.id
            if groups[k] == nil { order.append(k) }
            groups[k, default: []].append(i)
        }
        for k in order {
            let idx = groups[k]!, f = fixtures[idx[0]]
            let p = idx.map { positions[$0] }.reduce(.zero, +) / Float(idx.count)
            let r = Float(f.rot) * .pi / 180
            var across = SIMD3<Float>(cos(r), sin(r), 0)
            if idx.count > 1, let a = idx.first, let b = idx.last, simd_length(positions[b] - positions[a]) > 0.05 {
                across = simd_normalize(positions[b] - positions[a])
            }
            let size = f.size.flatMap { $0.count >= 3 ? SIMD3<Float>(Float($0[0]), Float($0[1]), Float($0[2])) : nil }
            let body = f.body ?? (f.kind == .head ? "moving_head" : f.kind.rawValue)
            let hang = f.mount == "hang"
            var up = SIMD3<Float>(0, 0, hang ? -1 : 1)
            if let u = f.up { up = simd_normalize(SIMD3(Float(u.x), Float(u.y), Float(u.z))) }
            if let d = f.dir, f.kind != .head { up = simd_normalize(SIMD3(Float(d.x), Float(d.y), Float(d.z))) }
            let shape: Shape
            switch body {
            case "moving_bar": shape = .movingBar
            case "curve_bar": shape = .curveBar
            case "par_bar": shape = .parBar
            case "strobe": shape = .strobe
            case "blinder": shape = .blinder
            case "laser": shape = .laser
            case "smoke": shape = .smoke
            case "moving_head": shape = f.beamDeg <= 6 ? .beamHead : f.beamDeg <= 20 ? .spotHead : .washHead
            default: shape = f.kind == .head ? .spotHead : idx.count > 1 ? .parBar : .par
            }
            if shape == .laser { up = simd_normalize(SIMD3(0, 1, 0.15)) }
            // heads: the model's height against a typical 55 cm head
            let scale = shape == .beamHead || shape == .spotHead || shape == .washHead
                ? min(1.5, max(0.6, (size.map { max($0.x, $0.z) } ?? 0.55) / 0.55)) : 1
            let length = Float(f.length ?? Double(size?.x ?? 1))
            let stand = f.mount == "stand" && f.truss == nil && p.z > 0.6
            units.append(Unit(id: k, shape: shape, idx: idx, p: p, up: up, across: across, length: length, scale: scale,
                              size: size, selected: selected.contains("fixture:\(k)"), hovered: selected.contains("hover:fixture:\(k)"),
                              onStand: stand))
        }
    }

    // MARK: the parts that never move (built with the scenery)

    /// A tripod stand from the floor up to `top`, under a fixture that stands in the air.
    private func tripod(_ m: inout MeshBuilder, at p: SIMD3<Float>, top: Float, _ col: SIMD3<Float>, em: Float) {
        guard top > 0.3 else { return }
        m.cylinder(SIMD3(p.x, p.y, top / 2), [0, 0, 1], radius: 0.022, length: top, col, emissive: em, segments: 8)
        m.cylinder(SIMD3(p.x, p.y, top - 0.01), [0, 0, 1], radius: 0.04, length: 0.03, col, emissive: em, segments: 8)
        let hub = SIMD3<Float>(p.x, p.y, min(0.55, top * 0.4))
        for k in 0..<3 {  // three legs out from the hub to the floor
            let a = Float(k) / 3 * 2 * .pi + 0.5
            let foot = SIMD3<Float>(p.x + cos(a) * 0.38, p.y + sin(a) * 0.38, 0.01)
            let v = hub - foot
            m.cylinder((hub + foot) / 2, simd_normalize(v), radius: 0.014, length: simd_length(v), col, emissive: em, segments: 6)
        }
    }

    func addStatic(into m: inout MeshBuilder) {
        for u in units {
            let col = u.selected ? Self.pick : u.hovered ? Self.lit : Self.bodyColor, em: Float = u.selected ? 0.7 : u.hovered ? 0.3 : 0
            if u.onStand {  // its own stand, under the fixture's lowest point
                let bottom: Float
                switch u.shape {
                case .beamHead, .spotHead, .washHead: bottom = u.p.z - (headGeometry(u).armLen + 0.12 * u.scale)
                case .movingBar, .curveBar: bottom = u.p.z - 0.25
                default: bottom = u.p.z - 0.2
                }
                tripod(&m, at: u.p, top: bottom, u.selected ? Self.pick : u.hovered ? Self.lit : Self.standColor, em: em)
            }
            switch u.shape {
            case .beamHead, .spotHead, .washHead:
                let s = u.scale, g = headGeometry(u)
                let b = Basis.along(u.up, hint: u.across)
                let baseC = u.p - u.up * (g.armLen + 0.06 * s)
                m.box(baseC, b, [g.armOffset * 2 + 0.1 * s, 0.3 * s, 0.12 * s], col, emissive: em)
                // the display on the base, faintly lit
                m.box(baseC + b.y * (0.151 * s), b, [0.08 * s, 0.002, 0.035 * s], [0.25, 0.45, 0.9], emissive: 0.5)
            case .movingBar:
                let b = Basis.along([0, 0, 1], hint: u.across)
                let h: Float = 0.12, hang: Float = u.up.z < 0 ? 1 : -1
                for e: Float in [-1, 1] {   // the yoke ends that carry the tilting bar
                    m.box(u.p + u.across * (u.length / 2 + 0.05) * e + [0, 0, hang * h * 0.55], b, [0.07, 0.12, h * 1.9],
                          col * 1.1, emissive: em)
                }
            case .curveBar:
                // the base that stays put; its cells tilt on their own above it (dynamic)
                let b = Basis.along(u.up, hint: u.across)
                m.box(u.p - u.up * 0.1, b, [u.length, 0.16, 0.08], col, emissive: em)
            case .parBar:
                let b = Basis.along(u.up, hint: u.across)
                let d = min(0.25, u.size?.y ?? 0.12), h = min(0.25, u.size?.z ?? 0.1)
                m.box(u.p - u.up * (h / 2), b, [u.length, d, h], col, emissive: em)
                for e: Float in [-1, 1] {   // the brackets
                    m.box(u.p - u.up * (h * 0.9) + u.across * (u.length / 2 - 0.08) * e, b, [0.03, d * 1.2, h * 0.9],
                          col * 1.2, emissive: em)
                }
            case .par:
                m.cylinder(u.p - u.up * 0.1, u.up, radius: 0.1, length: 0.2, col, emissive: em)
                m.cylinder(u.p - u.up * 0.205, u.up, radius: 0.06, length: 0.02, col * 0.8, emissive: em)
                let b = Basis.along(u.up, hint: u.across)
                for e: Float in [-1, 1] {   // a U bracket
                    m.box(u.p - u.up * 0.1 + b.x * 0.12 * e, b, [0.015, 0.04, 0.24], col * 1.2, emissive: em)
                }
            case .strobe:
                let b = Basis.along(u.up, hint: u.across)
                let w = u.size?.x ?? 0.42, h = u.size?.z ?? 0.24
                m.box(u.p - u.up * 0.08, b, [w, h, 0.16], col, emissive: em)
                m.box(u.p - u.up * 0.165, b, [w * 0.6, h * 0.6, 0.02], col * 0.8, emissive: em)   // the cooling back
            case .blinder:
                let b = Basis.along(u.up, hint: u.across)
                m.box(u.p - u.up * 0.06, b, [0.42, 0.24, 0.12], col, emissive: em)
            case .smoke:
                // a level box (the real housing when known), its nozzle towards where it blows
                let s = u.size ?? [0.4, 0.25, 0.22]
                var fwd = SIMD3<Float>(u.up.x, u.up.y, 0)
                fwd = simd_length(fwd) > 0.05 ? simd_normalize(fwd) : SIMD3(0, 1, 0)
                let b = Basis(x: simd_cross(fwd, [0, 0, 1]), y: [0, 0, 1], z: fwd)
                let c = u.p - fwd * (s.y / 2) + SIMD3(0, 0, s.z / 2 - 0.1)
                m.box(c, b, [s.x, s.z, s.y], col, emissive: em)
                m.cylinder(u.p + SIMD3(0, 0, s.z / 2 - 0.12) + u.up * 0.02, u.up, radius: min(0.045, s.x * 0.15), length: 0.06,
                           col * 1.4, emissive: em)
            case .laser:
                let b = Basis.along(u.up, hint: [1, 0, 0])
                m.box(u.p - u.up * 0.12, b, [0.24, 0.12, 0.24], col * 0.9, emissive: em)
                m.box(u.p - u.up * 0.12 + b.y * 0.061, b, [0.2, 0.002, 0.08], [0.6, 0.6, 0.65], emissive: 0.05)  // the label
            }
        }
    }

    // MARK: every frame: the moving parts and the lenses

    /// What an element shows this frame: its dimmer and colour (normalised).
    private func light(_ i: Int, _ frame: Frame?, _ hl: Bool) -> (Float, SIMD3<Float>) {
        var dim: Float = 0, col = SIMD3<Float>(repeating: 1)
        if let frame, i < frame.fx.count, frame.fx[i].count >= 5 {
            let v = frame.fx[i]
            dim = min(1, v[0]); col = SIMD3(v[1] + v[4], v[2] + v[4], v[3] + v[4])
        }
        if hl { dim = 1; col = [1, 1, 1] }
        return (dim, col / max(col.max(), 1))
    }

    private func lens(_ m: inout MeshBuilder, _ c: SIMD3<Float>, _ n: SIMD3<Float>, _ r: Float, _ dim: Float,
                      _ col: SIMD3<Float>, glow: Float = 1.4) {
        if dim > 0.01 {
            m.disc(c, n, radius: r, col, emissive: glow * dim + 0.05)
        } else {
            m.disc(c, n, radius: r, Self.glassColor, emissive: 0)
        }
    }

    private struct HeadGeometry { var headR, headL, lensR, armOffset, armLen: Float }

    private func headGeometry(_ u: Unit) -> HeadGeometry {
        let s = u.scale
        switch u.shape {
        case .beamHead: return HeadGeometry(headR: 0.1 * s, headL: 0.3 * s, lensR: 0.08 * s, armOffset: 0.14 * s, armLen: 0.22 * s)
        case .washHead: return HeadGeometry(headR: 0.17 * s, headL: 0.2 * s, lensR: 0.155 * s, armOffset: 0.2 * s, armLen: 0.26 * s)
        default: return HeadGeometry(headR: 0.13 * s, headL: 0.4 * s, lensR: 0.09 * s, armOffset: 0.17 * s, armLen: 0.26 * s)
        }
    }

    func dynamic(fixtures: [FixtureInfo], frame: Frame?, highlight: Set<String>) -> [SolidVertex] {
        var m = MeshBuilder()
        m.v.reserveCapacity(units.count * 400)
        for u in units {
            let col = u.selected ? Self.pick : u.hovered ? Self.lit : Self.yokeColor, em: Float = u.selected ? 0.7 : u.hovered ? 0.3 : 0
            let hl = u.idx.contains { highlight.contains(fixtures[$0].id) }
            switch u.shape {
            case .beamHead, .spotHead, .washHead:
                let i = u.idx[0], g = headGeometry(u), s = u.scale
                var d = frame.flatMap { i < $0.dirs.count ? $0.dirs[i] : nil } ?? simd_normalize(u.up + SIMD3(0, 0.6, 0))
                d = simd_normalize(d)
                // the yoke pans so the tilt axis is square to the beam; along the pan axis it keeps its last angle
                var t = simd_cross(u.up, d)
                if simd_length(t) < 0.05 { t = tiltAxis[u.id] ?? Basis.along(u.up, hint: u.across).x }
                t = simd_normalize(t)
                if let last = tiltAxis[u.id], simd_dot(last, t) < 0 { t = -t }   // a symmetric yoke: no sudden flips
                tiltAxis[u.id] = t
                let yoke = Basis(x: t, y: simd_cross(u.up, t), z: u.up)
                // the yoke: a turntable, a bridge and two arms up to the tilt axis
                m.cylinder(u.p - u.up * (g.armLen - 0.005 * s), u.up, radius: 0.07 * s, length: 0.03 * s, col * 0.8, emissive: em)
                m.box(u.p - u.up * (g.armLen - 0.03 * s), yoke, [g.armOffset * 2 + 0.05 * s, 0.11 * s, 0.04 * s], col, emissive: em)
                for e: Float in [-1, 1] {
                    m.box(u.p - u.up * (g.armLen / 2 - 0.01 * s) + t * g.armOffset * e, yoke,
                          [0.04 * s, 0.1 * s, g.armLen + 0.02 * s], col, emissive: em)
                    m.cylinder(u.p + t * (g.armOffset - 0.025 * s) * e, t, radius: 0.045 * s, length: 0.03 * s,
                               col * 1.15, emissive: em)
                }
                // the head: a barrel along the beam, a bezel and the lens
                let headCol = u.selected ? Self.pick : Self.bodyColor
                m.cylinder(u.p - d * (g.headL * 0.15), d, radius: g.headR, length: g.headL, headCol, emissive: em)
                let front = u.p + d * (g.headL * 0.35)
                m.cylinder(front, d, radius: g.headR * 1.04, length: 0.025 * s, headCol * 1.6, emissive: em, caps: false)
                let (dim, lc) = light(i, frame, hl)
                lens(&m, front + d * 0.003, d, g.lensR, dim, lc, glow: u.shape == .washHead ? 0.6 : 1.6)
                if u.shape == .washHead {   // the LEDs of a wash: one in the middle, a ring around it
                    let b = Basis.along(d, hint: t)
                    for k in 0..<7 {
                        let a = Float(k) / 6 * 2 * .pi
                        let off = k == 6 ? SIMD3<Float>.zero : (b.x * cos(a) + b.y * sin(a)) * (g.lensR * 0.62)
                        lens(&m, front + d * 0.006 + off, d, g.lensR * 0.22, dim, lc, glow: 1.8)
                    }
                }
            case .movingBar:
                // the bar tilts on its long axis towards where its cells shine
                var face = SIMD3<Float>(0, 0, 0)
                for i in u.idx {
                    if let v = frame.flatMap({ i < $0.dirs.count ? $0.dirs[i] : nil }) { face += simd_normalize(v) }
                }
                if simd_length(face) < 1e-3 { face = u.up + SIMD3(0, 0.6, 0) }
                face -= u.across * simd_dot(face, u.across)
                if simd_length(face) < 1e-3 { face = u.up }
                face = simd_normalize(face)
                let b = Basis.along(face, hint: u.across)
                let h: Float = 0.12, d: Float = 0.1
                m.box(u.p - face * 0.02, b, [u.length, d, h], u.selected ? Self.pick : Self.bodyColor, emissive: em)
                for e: Float in [-1, 1] {
                    m.cylinder(u.p + u.across * (u.length / 2 + 0.01) * e, u.across, radius: 0.04, length: 0.03, col, emissive: em)
                }
                let pitch = u.length / Float(max(1, u.idx.count))
                for i in u.idx {
                    let (dim, lc) = light(i, frame, hl)
                    let along = simd_dot(positions[i] - u.p, u.across)
                    lens(&m, u.p + u.across * along + face * (h / 2 - 0.02 + 0.002), face, min(0.04, pitch * 0.38), dim, lc)
                }
            case .curveBar:
                // every cell its own little head, tilting on its own motor towards where it shines
                let pitch = u.length / Float(max(1, u.idx.count))
                for i in u.idx {
                    var face = frame.flatMap { i < $0.dirs.count ? $0.dirs[i] : nil } ?? (u.up + SIMD3(0, 0.6, 0))
                    face -= u.across * simd_dot(face, u.across)
                    face = simd_length(face) < 1e-3 ? u.up : simd_normalize(face)
                    let along = simd_dot(positions[i] - u.p, u.across)
                    let c = u.p + u.across * along
                    m.box(c - u.up * 0.04, Basis.along(u.up, hint: u.across), [pitch * 0.25, 0.08, 0.06], col, emissive: em)
                    m.box(c, Basis.along(face, hint: u.across), [pitch * 0.8, 0.09, 0.1],
                          u.selected ? Self.pick : Self.bodyColor, emissive: em)
                    let (dim, lc) = light(i, frame, hl)
                    lens(&m, c + face * 0.052, face, min(0.035, pitch * 0.33), dim, lc)
                }
            case .parBar:
                let h = min(0.25, u.size?.z ?? 0.1), pitch = u.length / Float(max(1, u.idx.count))
                let d = min(0.25, u.size?.y ?? 0.12)
                for i in u.idx {
                    let (dim, lc) = light(i, frame, hl)
                    let along = simd_dot(positions[i] - u.p, u.across)
                    lens(&m, u.p + u.across * along + u.up * 0.002, u.up, min(min(0.05, d * 0.4), pitch * 0.4), dim, lc)
                }
                _ = h
            case .par:
                let (dim, lc) = light(u.idx[0], frame, hl)
                lens(&m, u.p + u.up * 0.002, u.up, 0.085, dim, lc)
            case .strobe:
                let (dim, _) = light(u.idx[0], frame, hl)
                let b = Basis.along(u.up, hint: u.across)
                let w = u.size?.x ?? 0.42, hh = u.size?.z ?? 0.24
                m.box(u.p + u.up * 0.002, b, [w * 0.86, hh * 0.62, 0.004], dim > 0.01 ? [0.9, 0.95, 1] : Self.glassColor,
                      emissive: dim > 0.01 ? dim * 3 : 0)
            case .blinder:
                let (dim, lc) = light(u.idx[0], frame, hl)
                let b = Basis.along(u.up, hint: u.across)
                let warm = simd_mix(lc, [1, 0.75, 0.45], SIMD3(repeating: 0.5))
                for e: Float in [-1, 1] {
                    let c = u.p + u.up * 0.002 + b.x * 0.1 * e
                    m.cylinder(c - u.up * 0.01, u.up, radius: 0.09, length: 0.02, Self.bodyColor * 1.5, caps: false)
                    lens(&m, c, u.up, 0.08, dim, warm, glow: 1.8)
                }
            case .laser:
                let (dim, lc) = light(u.idx[0], frame, hl)
                lens(&m, u.p + u.up * 0.002, u.up, 0.025, dim, lc, glow: 3)
            case .smoke:
                // its ready light: green, amber while it fires
                let firing = hl || (frame?.fog[fixtures[u.idx[0]].id] ?? 0) > 0
                let s = u.size ?? [0.4, 0.25, 0.22]
                m.disc(u.p + SIMD3(0, 0, s.z / 2 - 0.1 + 0.001), [0, 0, 1], radius: 0.012,
                       firing ? [1, 0.6, 0.2] : [0.3, 0.8, 0.45], emissive: firing ? 3 : 0.8)
            }
        }
        return m.v
    }
}
