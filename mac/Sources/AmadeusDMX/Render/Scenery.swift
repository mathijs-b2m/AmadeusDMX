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
    /// What stands at the back (the room's back wall, the LED wall and its frame): its vertices and the depth of its
    /// back. While the camera is behind that (orbiting round the stage), it isn't drawn, so it doesn't hide the stage.
    var cutaways: [(range: Range<Int>, y: Float)] = []
    /// The rest of the room's shell (side walls, the far wall, the ceiling), drawn only while the room is shown: its
    /// vertices and a point and direction of its inside. Seen from behind (Plan, gliding out) it isn't drawn.
    var shell: [(range: Range<Int>, at: SIMD3<Float>, inward: SIMD3<Float>)] = []

    init(fixtures: [FixtureInfo], stage: Stage, screen: Bool, trusses: [Truss] = [], selected: Set<String> = []) {
        room = Room(stage: stage, fixtures: fixtures, trusses: trusses)
        models = FixtureModels(fixtures: fixtures, selected: selected)
        let W = room.width, cx = W / 2
        let heads = fixtures.filter { $0.kind == .head }.count
        big = W >= 6 || heads >= 8
        top = max(2, Float(fixtures.map(\.pos.z).max() ?? 2))
        // a scaffold wall behind the stage: the LED wall hangs on its front, the stage stops at it
        let scaffoldWall = Truss.screenWall(trusses)
        if screen && scaffoldWall == nil {  // the LED wall stands behind the DJ: the room's back wall is behind it
            let wallY = big ? min(-4.5, room.back + 1.5) - 2.2 : -2.0
            if !room.backFixed { room.back = min(room.back, wallY - 0.8) }
        }
        let back = room.back

        // floor and room
        let floorC: SIMD3<Float> = [0.030, 0.032, 0.040]
        quad([-room.side - 8, back - 4, 0], [W + room.side + 8, back - 4, 0], [W + room.side + 8, room.depth, 0],
             [-room.side - 8, room.depth, 0], floorC)
        let wallAt = vertices.count
        quad([-room.side - 8, back, 0], [W + room.side + 8, back, 0], [W + room.side + 8, back, room.ceiling],
             [-room.side - 8, back, room.ceiling], [0.018, 0.019, 0.024], normal: [0, 1, 0])
        cutaways.append((wallAt..<vertices.count, back))
        roomShell()

        // stage, DJ riser and booth
        // a raised stage (stage.deck_m): a solid platform that high up to the stage's front edge, its face to the
        // audience; else a big rig's deck stands 15 cm high. A DJ on the floor (stage.dj_floor) has no riser, no such
        // deck under them (a raised stage stays: that is their floor) and a lower, narrower console
        var boothY: Float = room.backFixed ? max(-1.3, back + 1.1) : -1.3, boothZ: Float = 0
        let raised = Float(max(0, stage.deckM))
        let wallFront = scaffoldWall.map { Float($0.yM + $0.scaffoldDepth / 2) }
        let deckBack = wallFront ?? (room.backFixed ? back : min(-3, back + 1.0))
        if raised > 0 || (big && !stage.djFloor) {
            let deckTop: Float = raised > 0 ? raised : 0.15, front: Float = raised > 0 ? 0 : -0.2
            if stage.deckScaffold && raised > 0 {  // a plate on open tube
                box(-0.5, W + 0.5, deckBack, front, deckTop - 0.1, deckTop, [0.055, 0.058, 0.07])
                scaffoldDeck(-0.5, W + 0.5, deckBack, front, deckTop - 0.1)
            } else {
                box(-0.5, W + 0.5, deckBack, front, 0, deckTop, [0.055, 0.058, 0.07])
            }
            deck = (-0.5, W + 0.5, deckBack, front, deckTop)
            boothZ = deckTop
            // a lit edge along the front of the deck
            box(-0.5, W + 0.5, front - 0.04, front, deckTop - 0.02, deckTop, [0.25, 0.27, 0.35], emissive: 0.6)
        }
        if big {
            // (against a scaffold: the riser and the DJ stay in front of the LED wall)
            // (a back wall the rig fixes: all of it in front of that wall)
            var ry = max(deckBack + (wallFront == nil ? 0.5 : 2.8), -4.5)
            if room.backFixed && wallFront == nil { ry = min(-0.3, max(ry, back + 2.2)) }
            let rd = wallFront == nil && !room.backFixed ? 2.2 : min(2.2, ry - deckBack), rw = min(5, W * 0.3)
            boothY = ry - 0.4
            if !stage.djFloor {
                box(cx - rw / 2, cx + rw / 2, ry - rd, ry, boothZ, boothZ + 0.8, [0.07, 0.074, 0.09])
                boothZ += 0.8
            }
        }
        let bw: Float = big && !stage.djFloor ? 2.4 : 1.6, bh: Float = stage.djFloor ? 0.8 : 1.0
        box(cx - bw / 2, cx + bw / 2, boothY - 0.55, boothY, boothZ, boothZ + bh, [0.08, 0.085, 0.10])
        box(cx - bw / 2 - 0.05, cx + bw / 2 + 0.05, boothY - 0.6, boothY + 0.05, boothZ + bh, boothZ + bh + 0.05,
            [0.12, 0.13, 0.16])
        // decks: two faintly lit platters
        for dx: Float in [-0.45, 0.45] {
            box(cx + dx - 0.18, cx + dx + 0.18, boothY - 0.45, boothY - 0.1, boothZ + bh + 0.05, boothZ + bh + 0.08,
                [0.3, 0.35, 0.5], emissive: 0.5)
        }
        // the DJ (where the engine thinks their head is, to keep beams from meeting on it: geometry.dj_head)
        let dy = boothY - 0.9, dz = boothZ
        box(cx - 0.12, cx + 0.12, dy - 0.1, dy + 0.1, dz, dz + 0.85, [0.05, 0.05, 0.06])          // legs
        box(cx - 0.22, cx + 0.22, dy - 0.13, dy + 0.13, dz + 0.85, dz + 1.45, [0.06, 0.06, 0.07]) // torso
        box(cx - 0.11, cx + 0.11, dy - 0.11, dy + 0.11, dz + 1.5, dz + 1.75, [0.07, 0.065, 0.065]) // head
        box(cx - 0.36, cx - 0.22, dy + 0.0, dy + 0.4, dz + bh + 0.15, dz + bh + 0.25, [0.06, 0.06, 0.07])   // arms on the decks
        box(cx + 0.22, cx + 0.36, dy + 0.0, dy + 0.4, dz + bh + 0.15, dz + bh + 0.25, [0.06, 0.06, 0.07])
        djHead = [cx, dy, dz + 1.62]

        // the LED wall behind the DJ
        if screen {
            let sw = big ? min(10, W * 0.55) : 2.6, sh = sw * 9 / 16
            let free = big ? min(-4.5, Room(stage: stage, fixtures: fixtures, trusses: trusses).back + 1.5) - 2.2 : -2.0
            let sy = scaffoldWall.map { Float($0.yM + $0.scaffoldDepth / 2) + 0.37 }
                ?? (room.backFixed ? max(free, back + 0.45) : free)  // (its frame against a back wall the rig fixes)
            let sz: Float = (big ? 1.4 : 1.15) + raised  // over the stage, as high as it stands
            wall = WallPlacement(center: [cx, sy, sz + sh / 2], width: sw, height: sh)
            let screenAt = vertices.count
            box(cx - sw / 2 - 0.12, cx + sw / 2 + 0.12, sy - 0.35, sy - 0.02, sz - 0.12, sz + sh + 0.12, [0.03, 0.03, 0.035])
            if big && scaffoldWall == nil {  // legs
                box(cx - sw / 2 - 0.1, cx - sw / 2 + 0.1, sy - 0.3, sy - 0.1, 0, sz, [0.06, 0.06, 0.07])
                box(cx + sw / 2 - 0.1, cx + sw / 2 + 0.1, sy - 0.3, sy - 0.1, 0, sz, [0.06, 0.06, 0.07])
            }
            cutaways.append((screenAt..<vertices.count, sy - 0.35))
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
                if t.isStand {
                    lightStand(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6 : hov ? 0.3 : 0)
                } else if t.isScaffold {
                    scaffold(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6 : hov ? 0.3 : 0)
                } else {
                    trussBeam(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6 : hov ? 0.3 : 0)
                }
                if sel && !t.isLoop {  // the end handles: drag one to stretch or turn the truss
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

    /// The parts of `vertices` to draw with the camera at `eye`: all but what stands at the back while the camera is
    /// behind it, and the room's shell unless it is shown (`inRoom`) and seen from inside.
    func visibleRanges(eye: SIMD3<Float>, inRoom: Bool = false) -> [Range<Int>] {
        var out: [Range<Int>] = [], at = 0
        let hidden = cutaways.filter { eye.y < $0.y }.map(\.range)
            + shell.filter { !inRoom || simd_dot(eye - $0.at, $0.inward) < 0 }.map(\.range)
        for r in hidden.sorted(by: { $0.lowerBound < $1.lowerBound }) {
            if r.lowerBound > at { out.append(at..<r.lowerBound) }
            at = max(at, r.upperBound)
        }
        if at < vertices.count { out.append(at..<vertices.count) }
        return out
    }

    /// Whether the room's back wall is cut away with the camera at `eye` (beams then leave no spot on it).
    func backCut(eye: SIMD3<Float>) -> Bool { eye.y < room.back }

    /// Whether a surface of the room shown (`inRoom`) is seen from behind, and so not drawn.
    func shellCut(_ surf: Room.Surface, eye: SIMD3<Float>) -> Bool {
        let n = Room.normal(surf)
        return shell.contains { simd_dot($0.inward, n) > 0.5 && simd_dot(eye - $0.at, n) < 0 }
    }

    /// Whether the LED wall is cut away with the camera at `eye`.
    func screenCut(eye: SIMD3<Float>) -> Bool { wall.map { eye.y < $0.center.y - 0.35 } ?? false }

    // MARK: building blocks

    /// The walls and ceiling that make the room a room. Outdoors there is none.
    private mutating func roomShell() {
        guard !room.outdoor else { return }
        let x0 = -room.side, x1 = room.width + room.side, y0 = room.back, y1 = room.depth, h = room.ceiling
        let wall: SIMD3<Float> = [0.075, 0.078, 0.09], ceiling: SIMD3<Float> = [0.05, 0.052, 0.06]
        func add(_ s: inout Scenery, _ a: SIMD3<Float>, _ b: SIMD3<Float>, _ c: SIMD3<Float>, _ d: SIMD3<Float>,
                 _ color: SIMD3<Float>, _ inward: SIMD3<Float>) {
            let at = s.vertices.count
            s.quad(a, b, c, d, color, normal: inward)
            s.shell.append((at..<s.vertices.count, a, inward))
        }
        // (the back wall as well, just in front of the darker one the stage always has)
        add(&self, [x0, y0 + 0.002, 0], [x1, y0 + 0.002, 0], [x1, y0 + 0.002, h], [x0, y0 + 0.002, h], wall, [0, 1, 0])
        add(&self, [x0, y0, 0], [x0, y1, 0], [x0, y1, h], [x0, y0, h], wall, [1, 0, 0])
        add(&self, [x1, y1, 0], [x1, y0, 0], [x1, y0, h], [x1, y1, h], wall, [-1, 0, 0])
        add(&self, [x0, y1, 0], [x1, y1, 0], [x1, y1, h], [x0, y1, h], wall, [0, -1, 0])
        add(&self, [x0, y0, h], [x1, y0, h], [x1, y1, h], [x0, y1, h], ceiling, [0, 0, -1])
    }

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

    /// A scaffold wall: two frames of standards and ledgers, transoms between them, every other bay braced, base plates.
    private mutating func scaffold(_ t: Truss, color: SIMD3<Float>, emissive: Float) {
        let rot = Float(t.rotDeg), r = rot * .pi / 180, L = Float(t.lengthM), H = Float(t.zM), D = Float(t.scaffoldDepth)
        let ax = SIMD3<Float>(cos(r), sin(r), 0), ay = SIMD3<Float>(-sin(r), cos(r), 0)
        let c = SIMD3<Float>(Float(t.xM), Float(t.yM), 0), bays = t.scaffoldBays, lifts = t.scaffoldLifts
        let tube: Float = 0.05, bay = L / Float(bays), lift = H / Float(lifts)
        func at(_ u: Float, _ v: Float, _ z: Float) -> SIMD3<Float> { c + ax * u + ay * v + SIMD3(0, 0, z) }
        for v in [D / 2, -D / 2] {
            for k in 0...bays {
                let u = -L / 2 + bay * Float(k)
                rotatedBox(at(u, v, H / 2 + 0.15), [tube, tube, H + 0.3], rot, color, emissive: emissive)
                rotatedBox(at(u, v, 0.015), [0.2, 0.2, 0.03], rot, color * 0.7, emissive: emissive)
            }
            for k in 1...lifts { rotatedBox(at(0, v, lift * Float(k)), [L, tube, tube], rot, color, emissive: emissive) }
            for k in stride(from: 0, to: bays, by: 2) {  // a brace up each braced bay, zigzag from lift to lift
                let u = -L / 2 + bay * Float(k)
                for j in 0..<lifts {
                    let z = lift * Float(j), up = j % 2 == 0
                    strut(at(up ? u : u + bay, v, z), at(up ? u + bay : u, v, z + lift), color * 0.85, emissive: emissive)
                }
            }
        }
        for k in 0...bays {  // transoms between the frames
            let u = -L / 2 + bay * Float(k)
            for j in 1...lifts { rotatedBox(at(u, 0, lift * Float(j)), [tube * 0.8, D, tube * 0.8], rot, color * 0.9, emissive: emissive) }
        }
    }

    /// Open tube under a raised stage's plate: standards about 2 m apart, a ledger round each row, braces.
    private mutating func scaffoldDeck(_ x0: Float, _ x1: Float, _ y0: Float, _ y1: Float, _ top: Float) {
        let c: SIMD3<Float> = [0.16, 0.17, 0.2], t: Float = 0.025
        let nx = max(1, Int(((x1 - x0) / 2.5).rounded())), ny = max(1, Int(((y1 - y0) / 2.5).rounded()))
        let dx = (x1 - x0) / Float(nx), dy = (y1 - y0) / Float(ny)
        for i in 0...nx {
            for j in 0...ny {
                let x = x0 + dx * Float(i), y = y0 + dy * Float(j)
                box(x - t, x + t, y - t, y + t, 0, top, c)
            }
        }
        for z in [top * 0.5, top - 0.05] {
            for j in 0...ny { let y = y0 + dy * Float(j); box(x0, x1, y - t, y + t, z - t, z + t, c) }
            for i in 0...nx { let x = x0 + dx * Float(i); box(x - t, x + t, y0, y1, z - t, z + t, c) }
        }
        for i in 0..<nx where i % 2 == 0 {  // the bays along the front and the back, braced
            let x = x0 + dx * Float(i)
            for y in [y0, y1] { strut([x, y, 0], [x + dx, y, top - 0.05], c * 0.85) }
        }
    }

    /// A thin tube from `a` to `b` in any direction (a brace).
    private mutating func strut(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ color: SIMD3<Float>, emissive: Float = 0) {
        var m = MeshBuilder()
        m.cylinder((a + b) / 2, simd_normalize(b - a), radius: 0.016, length: simd_length(b - a), color, emissive: emissive, segments: 5)
        vertices += m.v
    }

    /// A light stand: its bar (a 40 mm tube, or a triangle of deco truss) and a tripod under each end of a bridge, under the middle of a T-bar,
    /// from the floor up to the bar.
    private mutating func lightStand(_ t: Truss, color: SIMD3<Float>, emissive: Float) {
        var m = MeshBuilder()
        let z = Float(t.zM), r = Float(t.rotDeg) * .pi / 180
        let foot = t.isDeco ? z - 0.095 : z - 0.02  // where the stand's pole meets the bar
        if t.isDeco {
            // three chords, point up, laced on each face
            let ax = SIMD3<Float>(cos(r), sin(r), 0), n = SIMD3<Float>(-sin(r), cos(r), 0)
            let L = Float(t.lengthM), mid = SIMD3<Float>(Float(t.xM), Float(t.yM), z)
            let chords: [SIMD3<Float>] = [n * -0.11 + [0, 0, -0.095], n * 0.11 + [0, 0, -0.095], [0, 0, 0.095]]
            for c in chords {
                m.cylinder(mid + c, ax, radius: 0.012, length: L, color, emissive: emissive, segments: 6)
            }
            let bays = max(1, Int((L / 0.22).rounded()))
            for (i, c) in chords.enumerated() {
                let d = chords[(i + 1) % 3]
                for k in 0..<bays {
                    let u0 = -L / 2 + L * Float(k) / Float(bays), u1 = u0 + L / Float(bays)
                    let a = mid + ax * u0 + (k % 2 == 0 ? c : d), b = mid + ax * u1 + (k % 2 == 0 ? d : c)
                    m.cylinder((a + b) / 2, simd_normalize(b - a), radius: 0.006, length: simd_length(b - a), color,
                               emissive: emissive, segments: 4)
                }
            }
        } else {
            m.cylinder(SIMD3(Float(t.xM), Float(t.yM), z), [cos(r), sin(r), 0], radius: 0.02, length: Float(t.lengthM), color,
                       emissive: emissive, segments: 10)
        }
        let spread = min(0.75, 0.25 + z * 0.15)  // a taller stand stands wider
        for f in t.standFeet {
            let p = SIMD2<Float>(Float(f.x), Float(f.y))
            m.cylinder(SIMD3(p.x, p.y, foot / 2), [0, 0, 1], radius: 0.025, length: foot, color * 0.85,
                       emissive: emissive, segments: 8)
            let hub = SIMD3<Float>(p.x, p.y, min(0.7, z * 0.3))
            // three legs out from the hub to the floor: a bridge's with one leg in along the bar (as a crew sets it,
            // so the others stick out least past its ends), a T-bar's with one towards the audience
            let first = t.type == "tbar" ? r + .pi / 2 : atan2(Float(t.yM) - p.y, Float(t.xM) - p.x)
            for k in 0..<3 {
                let a = Float(k) / 3 * 2 * .pi + first
                let foot = SIMD3<Float>(p.x + cos(a) * spread, p.y + sin(a) * spread, 0.01)
                let v = hub - foot
                m.cylinder((hub + foot) / 2, simd_normalize(v), radius: 0.015, length: simd_length(v), color * 0.85,
                           emissive: emissive, segments: 6)
            }
        }
        vertices += m.v
    }

    /// A horizontal quatro truss from the set: four chords along it and lacing, turned with it.
    private mutating func trussBeam(_ t: Truss, color: SIMD3<Float>, emissive: Float) {
        if t.isCarre {  // its four sides, end plates at the corners, and a tower under each corner down to the floor
            for (a, b) in t.pieces() {
                var side = Truss(id: t.id, lengthM: simd_length(b - a), xM: (a.x + b.x) / 2, yM: (a.y + b.y) / 2,
                                 zM: t.zM, rotDeg: atan2(b.y - a.y, b.x - a.x) * 180 / .pi)
                side.type = t.type
                straightBeam(side, color: color, emissive: emissive, ends: [-1, 1])
            }
            for c in t.carreCorners {
                trussTower(Float(c.x), Float(c.y), Float(t.zM) - 0.05, color: color, emissive: emissive)
            }
            return
        }
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
