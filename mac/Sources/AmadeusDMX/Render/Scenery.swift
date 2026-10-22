// The solid part of the scene, built once per rig: floor, back wall, stage deck, DJ riser + booth + DJ,
// trusses and towers the fixtures hang on, the fixtures' fixed parts and the LED wall's frame.
import AmadeusKit
import Foundation
import simd

struct SolidVertex {
    var pos: SIMD3<Float>
    var normal: SIMD3<Float>
    var color: SIMD4<Float>   // rgb, a = emissive
}

/// Where the LED wall hangs (same rule as the web visualiser).
struct WallPlacement {
    var center: SIMD3<Float>   // middle of the picture
    var width: Float
    var height: Float

    var corners: (bl: SIMD3<Float>, br: SIMD3<Float>, tr: SIMD3<Float>, tl: SIMD3<Float>) {
        let hw = width / 2, hh = height / 2, c = center
        return ([c.x - hw, c.y, c.z - hh], [c.x + hw, c.y, c.z - hh], [c.x + hw, c.y, c.z + hh], [c.x - hw, c.y, c.z + hh])
    }
}

struct Scenery {
    var vertices: [SolidVertex] = []
    var wall: WallPlacement?
    /// The stage deck (a big rig's): where it stands and how high its top is.
    var deck: (x0: Float, x1: Float, y0: Float, y1: Float, top: Float)?
    var room: Room
    var big: Bool
    var top: Float
    var djHead: SIMD3<Float> = .zero
    var models: FixtureModels

    init(fixtures: [FixtureInfo], stage: Stage, screen: Bool, trusses: [Truss] = [], selected: Set<String> = []) {
        room = Room(stage: stage, fixtures: fixtures, trusses: trusses)
        models = FixtureModels(fixtures: fixtures, selected: selected)
        let W = room.width, cx = W / 2
        let heads = fixtures.filter { $0.kind == .head }.count
        big = W >= 6 || heads >= 8
        top = max(2, Float(fixtures.map(\.pos.z).max() ?? 2))
        if screen {  // the LED wall stands behind the DJ: the room's back wall is behind it
            let wallY = big ? min(-4.5, room.back + 1.5) - 2.2 : -2.0
            room.back = min(room.back, wallY - 0.8)
        }
        let back = room.back

        // floor and room
        let floorC: SIMD3<Float> = [0.030, 0.032, 0.040]
        quad([-room.side - 8, back - 4, 0], [W + room.side + 8, back - 4, 0], [W + room.side + 8, room.depth, 0],
             [-room.side - 8, room.depth, 0], floorC)
        quad([-room.side - 8, back, 0], [W + room.side + 8, back, 0], [W + room.side + 8, back, room.ceiling],
             [-room.side - 8, back, room.ceiling], [0.018, 0.019, 0.024], normal: [0, 1, 0])

        // stage, DJ riser and booth
        // a raised stage (stage.deck_m): a solid platform that high up to the stage's front edge, its face to the
        // audience; else a big rig's deck stands 15 cm high
        var boothY: Float, boothZ: Float
        let raised = Float(max(0, stage.deckM))
        if big || raised > 0 {
            let deckBack = min(-3, back + 1.0)
            let deckTop: Float = raised > 0 ? raised : 0.15, front: Float = raised > 0 ? 0 : -0.2
            box(-0.5, W + 0.5, deckBack, front, 0, deckTop, [0.055, 0.058, 0.07])
            deck = (-0.5, W + 0.5, deckBack, front, deckTop)
            if big {
                let ry = max(deckBack + 0.5, -4.5), rd: Float = 2.2, rw = min(5, W * 0.3)
                box(cx - rw / 2, cx + rw / 2, ry - rd, ry, deckTop, deckTop + 0.8, [0.07, 0.074, 0.09])
                boothY = ry - 0.4; boothZ = deckTop + 0.8
            } else {
                boothY = -1.3; boothZ = deckTop
            }
            // a lit edge along the front of the deck
            box(-0.5, W + 0.5, front - 0.04, front, deckTop - 0.02, deckTop, [0.25, 0.27, 0.35], emissive: 0.6)
        } else {
            boothY = -1.3; boothZ = 0
        }
        let bw: Float = big ? 2.4 : 1.6
        box(cx - bw / 2, cx + bw / 2, boothY - 0.55, boothY, boothZ, boothZ + 1.0, [0.08, 0.085, 0.10])
        box(cx - bw / 2 - 0.05, cx + bw / 2 + 0.05, boothY - 0.6, boothY + 0.05, boothZ + 1.0, boothZ + 1.05,
            [0.12, 0.13, 0.16])
        // decks: two faintly lit platters
        for dx: Float in [-0.45, 0.45] {
            box(cx + dx - 0.18, cx + dx + 0.18, boothY - 0.45, boothY - 0.1, boothZ + 1.05, boothZ + 1.08,
                [0.3, 0.35, 0.5], emissive: 0.5)
        }
        // the DJ
        let dy = boothY - 0.9, dz = boothZ
        box(cx - 0.12, cx + 0.12, dy - 0.1, dy + 0.1, dz, dz + 0.85, [0.05, 0.05, 0.06])          // legs
        box(cx - 0.22, cx + 0.22, dy - 0.13, dy + 0.13, dz + 0.85, dz + 1.45, [0.06, 0.06, 0.07]) // torso
        box(cx - 0.11, cx + 0.11, dy - 0.11, dy + 0.11, dz + 1.5, dz + 1.75, [0.07, 0.065, 0.065]) // head
        box(cx - 0.36, cx - 0.22, dy + 0.0, dy + 0.4, dz + 1.15, dz + 1.25, [0.06, 0.06, 0.07])   // arms on the decks
        box(cx + 0.22, cx + 0.36, dy + 0.0, dy + 0.4, dz + 1.15, dz + 1.25, [0.06, 0.06, 0.07])
        djHead = [cx, dy, dz + 1.62]

        // the LED wall behind the DJ
        if screen {
            let sw = big ? min(10, W * 0.55) : 2.6, sh = sw * 9 / 16
            let sy = big ? min(-4.5, Room(stage: stage, fixtures: fixtures, trusses: trusses).back + 1.5) - 2.2 : -2.0
            let sz: Float = (big ? 1.4 : 1.15) + raised  // over the stage, as high as it stands
            wall = WallPlacement(center: [cx, sy, sz + sh / 2], width: sw, height: sh)
            box(cx - sw / 2 - 0.12, cx + sw / 2 + 0.12, sy - 0.35, sy - 0.02, sz - 0.12, sz + sh + 0.12, [0.03, 0.03, 0.035])
            if big {  // legs
                box(cx - sw / 2 - 0.1, cx - sw / 2 + 0.1, sy - 0.3, sy - 0.1, 0, sz, [0.06, 0.06, 0.07])
                box(cx + sw / 2 - 0.1, cx + sw / 2 + 0.1, sy - 0.3, sy - 0.1, 0, sz, [0.06, 0.06, 0.07])
            }
        }

        // trusses: the set's own (rig editor), else: hanging fixtures at the same depth and height share one bar
        let truss: SIMD3<Float> = [0.16, 0.17, 0.2]
        let pick: SIMD3<Float> = [0.25, 0.55, 1.0]
        let lit: SIMD3<Float> = [0.35, 0.45, 0.6]  // under the pointer: what a click would pick
        for t in trusses {
            let sel = selected.contains("truss:\(t.id)")
            let hov = selected.contains("hover:truss:\(t.id)")
            let handle: SIMD3<Float> = [0.85, 0.95, 1.0]
            if t.vertical {
                trussTower(Float(t.xM), Float(t.yM), Float(t.zM + t.lengthM / 2), color: sel ? pick : hov ? lit : truss,
                           emissive: sel ? 0.6 : hov ? 0.3 : 0)
                if sel {  // the handle on top: drag it to make the tower taller or shorter
                    let x = Float(t.xM), y = Float(t.yM), z = Float(t.zM + t.lengthM / 2) + 0.2
                    box(x - 0.13, x + 0.13, y - 0.13, y + 0.13, z - 0.13, z + 0.13, handle, emissive: 1.5)
                }
            } else {
                trussBeam(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6 : hov ? 0.3 : 0)
                if sel && !t.isRing {  // the end handles: drag one to stretch or turn the truss
                    let r = Float(t.rotDeg) * .pi / 180, ax = SIMD3<Float>(cos(r), sin(r), 0)
                    for e: Float in [-1, 1] {
                        let p = SIMD3<Float>(Float(t.xM), Float(t.yM), Float(t.zM)) + ax * (Float(t.lengthM) / 2 * e)
                        box(p.x - 0.13, p.x + 0.13, p.y - 0.13, p.y + 0.13, p.z - 0.13, p.z + 0.13, handle, emissive: 1.5)
                    }
                }
            }
        }
        var rows: [SIMD2<Int>: [FixtureInfo]] = [:]
        for f in fixtures where f.mount == "hang" && trusses.isEmpty {
            rows[SIMD2(Int((f.pos.y * 2).rounded()), Int((f.pos.z * 2).rounded())), default: []].append(f)
        }
        for (_, fs) in rows {
            let xs = fs.map { Float($0.pos.x) }, y = Float(fs[0].pos.y), z = Float(fs.map(\.pos.z).max()!) + 0.3
            trussBar(xs.min()! - 0.5, xs.max()! + 0.5, y, z, truss)
            if fs.count >= 3 || big {  // chain motors up to the ceiling
                for x in [xs.min()! - 0.3, xs.max()! + 0.3] {
                    box(x - 0.015, x + 0.015, y - 0.015, y + 0.015, z + 0.15, room.outdoor ? z + 1.2 : room.ceiling, [0.08, 0.08, 0.09])
                }
            }
        }
        // (a fixture standing in the air has its own stand: part of the fixture, see FixtureModels)

        // the fixtures: what never moves now, the moving parts and lenses every frame (FixtureModels)
        var mb = MeshBuilder()
        models.addStatic(into: &mb)
        vertices += mb.v
    }

    // MARK: building blocks

    private mutating func quad(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ c: SIMD3<Float>, _ d: SIMD3<Float>,
                               _ color: SIMD3<Float>, normal: SIMD3<Float>? = nil, emissive: Float = 0) {
        let n = normal ?? simd_normalize(simd_cross(b - a, d - a))
        let col = SIMD4(color, emissive)
        for p in [a, b, c, a, c, d] { vertices.append(SolidVertex(pos: p, normal: n, color: col)) }
    }

    mutating func box(_ x0: Float, _ x1: Float, _ y0: Float, _ y1: Float, _ z0: Float, _ z1: Float,
                      _ color: SIMD3<Float>, emissive: Float = 0) {
        let p = { (x: Float, y: Float, z: Float) in SIMD3<Float>(x, y, z) }
        quad(p(x0, y0, z1), p(x1, y0, z1), p(x1, y1, z1), p(x0, y1, z1), color, normal: [0, 0, 1], emissive: emissive)
        quad(p(x0, y1, z0), p(x1, y1, z0), p(x1, y1, z1), p(x0, y1, z1), color, normal: [0, 1, 0], emissive: emissive)
        quad(p(x1, y0, z0), p(x0, y0, z0), p(x0, y0, z1), p(x1, y0, z1), color, normal: [0, -1, 0], emissive: emissive)
        quad(p(x0, y0, z0), p(x0, y1, z0), p(x0, y1, z1), p(x0, y0, z1), color, normal: [-1, 0, 0], emissive: emissive)
        quad(p(x1, y1, z0), p(x1, y0, z0), p(x1, y0, z1), p(x1, y1, z1), color, normal: [1, 0, 0], emissive: emissive)
        quad(p(x0, y1, z0), p(x1, y1, z0), p(x1, y0, z0), p(x0, y0, z0), color, normal: [0, 0, -1], emissive: emissive)
    }

    /// A box with its own axes: `ex` along it, `ez` its "up"; size = (along ex, across, along ez).
    mutating func orientedBox(_ c: SIMD3<Float>, _ ex0: SIMD3<Float>, _ ez0: SIMD3<Float>, _ size: SIMD3<Float>,
                              _ color: SIMD3<Float>, emissive: Float = 0) {
        let ez = simd_normalize(ez0)
        var ex = ex0 - ez * simd_dot(ex0, ez)
        if simd_length(ex) < 1e-4 { ex = abs(ez.z) < 0.9 ? simd_cross([0, 0, 1], ez) : [1, 0, 0] }
        ex = simd_normalize(ex)
        let ey = simd_cross(ez, ex)
        let hx = size.x / 2, hy = size.y / 2, hz = size.z / 2
        func P(_ i: Float, _ j: Float, _ k: Float) -> SIMD3<Float> { c + ex * (i * hx) + ey * (j * hy) + ez * (k * hz) }
        quad(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), color, normal: ez, emissive: emissive)
        quad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), color, normal: -ez, emissive: emissive)
        quad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), color, normal: ey, emissive: emissive)
        quad(P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), P(-1, -1, -1), color, normal: -ey, emissive: emissive)
        quad(P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), P(1, -1, -1), color, normal: ex, emissive: emissive)
        quad(P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), color, normal: -ex, emissive: emissive)
    }

    /// A box turned around z (counter-clockwise from above) about its centre; size = (along, across, height).
    mutating func rotatedBox(_ c: SIMD3<Float>, _ size: SIMD3<Float>, _ rotDeg: Float, _ color: SIMD3<Float>, emissive: Float = 0) {
        let r = rotDeg * .pi / 180, ax = SIMD3<Float>(cos(r), sin(r), 0), ay = SIMD3<Float>(-sin(r), cos(r), 0)
        let hx = size.x / 2, hy = size.y / 2, hz = size.z / 2
        func P(_ i: Float, _ j: Float, _ k: Float) -> SIMD3<Float> { c + ax * (i * hx) + ay * (j * hy) + SIMD3(0, 0, k * hz) }
        quad(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), color, normal: [0, 0, 1], emissive: emissive)
        quad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), color, normal: [0, 0, -1], emissive: emissive)
        quad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), color, normal: ay, emissive: emissive)
        quad(P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), P(-1, -1, -1), color, normal: -ay, emissive: emissive)
        quad(P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), P(1, -1, -1), color, normal: ax, emissive: emissive)
        quad(P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), color, normal: -ax, emissive: emissive)
    }

    /// A horizontal quatro truss from the set: four chords along it and lacing, turned with it.
    private mutating func trussBeam(_ t: Truss, color: SIMD3<Float>, emissive: Float) {
        if t.isRing {  // round: short straight pieces round the arc, end plates only where an arc ends
            let pieces = t.pieces(0.3)
            for (k, (a, b)) in pieces.enumerated() {
                var piece = Truss(id: t.id, lengthM: simd_length(b - a) + 0.02, xM: (a.x + b.x) / 2, yM: (a.y + b.y) / 2,
                                  zM: t.zM, rotDeg: atan2(b.y - a.y, b.x - a.x) * 180 / .pi)
                piece.type = t.type
                straightBeam(piece, color: color, emissive: emissive,
                             ends: t.isFullRing ? [] : [k == 0 ? -1 : nil, k == pieces.count - 1 ? 1 : nil].compactMap { $0 })
            }
            return
        }
        straightBeam(t, color: color, emissive: emissive, ends: [-1, 1])
    }

    private mutating func straightBeam(_ t: Truss, color: SIMD3<Float>, emissive: Float, ends: [Float]) {
        let r = Float(t.rotDeg), L = Float(t.lengthM), h: Float = 0.15
        let c = SIMD3<Float>(Float(t.xM), Float(t.yM), Float(t.zM))
        let ay = SIMD3<Float>(-sin(r * .pi / 180), cos(r * .pi / 180), 0), ax = SIMD3<Float>(cos(r * .pi / 180), sin(r * .pi / 180), 0)
        for dy in [-h, h] { for dz in [-h, h] { rotatedBox(c + ay * dy + [0, 0, dz], [L, 0.045, 0.045], r, color, emissive: emissive) } }
        var u = -L / 2 + 0.15
        while u < L / 2 - 0.15 {
            for dy in [-h, h] { rotatedBox(c + ax * u + ay * dy, [0.016, 0.016, 2 * h], r, color * 0.8, emissive: emissive) }
            u += 0.5
        }
        for e in ends { rotatedBox(c + ax * (L / 2) * e, [0.05, 2 * h + 0.05, 2 * h + 0.05], r, color * 0.9, emissive: emissive) }
    }

    /// A 30 cm box truss: four chords and diagonal lacing.
    private mutating func trussBar(_ x0: Float, _ x1: Float, _ y: Float, _ z: Float, _ c: SIMD3<Float>) {
        let h: Float = 0.15, t: Float = 0.022
        for dy in [-h, h] { for dz in [-h, h] { box(x0, x1, y + dy - t, y + dy + t, z + dz - t, z + dz + t, c) } }
        var x = x0
        while x < x1 - 0.3 {
            for dy in [-h, h] { box(x, x + 0.3, y + dy - 0.008, y + dy + 0.008, z - h, z + h, c * 0.8) }
            x += 0.6
        }
    }

    private mutating func trussTower(_ x: Float, _ y: Float, _ h: Float, color: SIMD3<Float> = [0.16, 0.17, 0.2],
                                     emissive: Float = 0) {
        let c = color, w: Float = 0.15, t: Float = 0.02
        for dx in [-w, w] { for dy in [-w, w] { box(x + dx - t, x + dx + t, y + dy - t, y + dy + t, 0, h + 0.2, c, emissive: emissive) } }
        var z: Float = 0.3
        while z < h { box(x - w, x + w, y - w - 0.008, y - w + 0.008, z, z + 0.02, c * 0.8, emissive: emissive); z += 0.5 }
        box(x - 0.4, x + 0.4, y - 0.4, y + 0.4, 0, 0.03, c * 0.7, emissive: emissive)
    }
}
