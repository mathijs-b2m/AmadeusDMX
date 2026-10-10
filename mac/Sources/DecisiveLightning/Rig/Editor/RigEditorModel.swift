// The rig editor's state: one set being laid out. Trusses can be placed, moved, raised, turned and resized;
// fixtures snap onto trusses (and move along with them), slide along them, turn, and aim.
// Everything is written back into the set file; the engine reads plain positions (x, y_m, z_m, rot_deg, aim).
import AppKit
import DecisiveKit
import Foundation
import Observation
import simd

enum EditorSelection: Hashable {
    case truss(String)
    case fixture(String)
    case zone(String)

    var key: String {
        switch self {
        case .truss(let id): "truss:\(id)"
        case .fixture(let id): "fixture:\(id)"
        case .zone(let id): "zone:\(id)"
        }
    }
}

@MainActor
@Observable
final class RigEditorModel: StageEditing {
    private(set) var doc: RigDocument
    private var saved: RigDocument
    var selection: EditorSelection?
    var snap = true
    var showZones = true { didSet { version += 1 } }
    var message: String?
    @ObservationIgnored var undoManager: UndoManager?
    @ObservationIgnored private var defs: [String: FixtureDefinition] = [:]
    @ObservationIgnored private let workspace: Workspace
    @ObservationIgnored private var drag: (sel: EditorSelection, grab: SIMD3<Double>, start: SIMD3<Double>, before: RigDocument)?
    @ObservationIgnored private var version = 0

    static let hangDrop = 0.42    // a fixture under a truss: its beam centre below the truss centre
    static let sideOut = 0.4      // a fixture on the front/back face: its centre out from the truss centre
    static let sides = ["under", "top", "front", "back"]
    static let grid = 0.25        // snapping step (m)

    init?(workspace: Workspace, set: String) {
        guard let d = workspace.document(set) else { return nil }
        self.workspace = workspace
        doc = d
        saved = d
    }

    var isDirty: Bool { doc != saved }
    var setName: String { doc.name }

    func definition(_ key: String) -> FixtureDefinition? {
        if let d = defs[key] { return d }
        let d = workspace.definition(key)
        defs[key] = d
        return d
    }

    // MARK: - what the stage shows

    func stageInput() -> StageInput {
        let els = RigElements.elements(doc) { [unowned self] in definition($0) }
        return StageInput(key: "edit:\(doc.name):\(version)", fixtures: els, stage: doc.stage, screen: false, hello: nil,
                          trusses: doc.trusses, selected: selection.map { [$0.key] } ?? [], keepCamera: true,
                          zones: doc.zones.filter { z in showZones || selection == .zone(z.id) })
    }

    // MARK: - changes (all undoable)

    private func change(_ name: String, _ body: (inout RigDocument) -> Void) {
        let before = doc
        body(&doc)
        guard doc != before else { return }
        version += 1
        registerUndo(name, before)
    }

    private func registerUndo(_ name: String, _ before: RigDocument) {
        undoManager?.registerUndo(withTarget: self) { m in
            let now = m.doc
            m.doc = before
            m.version += 1
            m.registerUndo(name, now)
        }
        undoManager?.setActionName(name)
    }

    private func refresh() { version += 1 }

    // MARK: - trusses

    func addTruss(length: Double, vertical: Bool = false) {
        let n = (1...).first { i in !doc.trusses.contains { $0.id == "truss\(i)" } }!
        let W = doc.width
        var t = Truss(id: "truss\(n)", lengthM: length, xM: W / 2, yM: -1.5 - Double(doc.trusses.count % 4) * 1.2,
                      zM: vertical ? length / 2 : min(doc.stage.ceilingM - 1, 4.5), vertical: vertical)
        if vertical { t.xM = doc.trusses.filter(\.vertical).count % 2 == 0 ? -0.6 : W + 0.6; t.yM = -1.5 }
        change(vertical ? "Add Tower" : "Add Truss") { $0.trusses.append(t) }
        selection = .truss(t.id)
    }

    func updateTruss(_ id: String, _ name: String = "Change Truss", _ body: (inout Truss) -> Void) {
        change(name) { d in
            guard let i = d.trusses.firstIndex(where: { $0.id == id }) else { return }
            let oldRot = d.trusses[i].rotDeg
            body(&d.trusses[i])
            let turn = d.trusses[i].rotDeg - oldRot
            if turn != 0 {  // clamped fixtures turn with their truss
                for j in d.fixtures.indices where d.fixtures[j].truss == id {
                    d.fixtures[j].rotDeg = Self.wrap(d.fixtures[j].rotDeg + turn)
                }
            }
            Self.followTruss(&d, d.trusses[i])
        }
    }

    /// Fixtures on a truss go where the truss goes.
    private static func followTruss(_ d: inout RigDocument, _ t: Truss) {
        for i in d.fixtures.indices where d.fixtures[i].truss == t.id {
            place(&d.fixtures[i], on: t, at: d.fixtures[i].trussPos ?? 0, width: d.width)
        }
    }

    static func place(_ f: inout PlacedFixture, on t: Truss, at u: Double, width: Double) {
        let u = t.vertical ? max(0.2, min(t.lengthM, u)) : max(-t.lengthM / 2, min(t.lengthM / 2, u))
        if f.truss != t.id && !t.vertical { f.rotDeg = t.rotDeg }  // clamped on: square to the truss
        f.truss = t.id
        f.trussPos = u
        if t.vertical {  // clamped to the tower's front, facing the audience
            let base = t.zM - t.lengthM / 2
            f.x = t.xM / width
            f.yM = t.yM + 0.32
            f.zM = base + u
            if f.mount == "floor" { f.mount = "stand" }
        } else {
            // the box truss's four sides: under it, on top, on the front (audience) or the back face
            let side = f.side.flatMap { sides.contains($0) ? $0 : nil } ?? (f.mount == "stand" ? "top" : "under")
            let p = t.point(u), r = t.rotDeg * .pi / 180, n = SIMD2(-sin(r), cos(r))  // n: towards the audience
            var q = SIMD2(p.x, p.y), z = p.z
            // under = 0°, front = 90°, on top = 180°, back = 270°: the fixture rolled about the truss
            switch side {
            case "top": z += hangDrop
            case "front": q += n * sideOut
            case "back": q -= n * sideOut
            default: z -= hangDrop
            }
            f.side = side
            f.mount = side == "top" ? "stand" : "hang"
            f.mountRoll = side == "front" ? 90 : side == "back" ? 270 : nil
            f.x = q.x / width
            f.yM = q.y
            f.zM = z
        }
    }

    func setSide(_ id: String, _ side: String) {
        updateFixture(id, "Move to \(side.capitalized)") { $0.side = side }
    }

    // MARK: - fixtures

    func updateFixture(_ id: String, _ name: String = "Change Fixture", _ body: (inout PlacedFixture) -> Void) {
        change(name) { d in
            guard let i = d.fixtures.firstIndex(where: { $0.id == id }) else { return }
            body(&d.fixtures[i])
            if let tid = d.fixtures[i].truss, let t = d.trusses.first(where: { $0.id == tid }) {
                Self.place(&d.fixtures[i], on: t, at: d.fixtures[i].trussPos ?? 0, width: d.width)
            }
        }
    }

    func attach(_ id: String, to trussID: String?) {
        updateFixture(id, trussID == nil ? "Take Off Truss" : "Put on Truss") { f in
            if let trussID {
                f.truss = trussID
                f.trussPos = 0
                if f.mount == "floor" { f.mount = "hang" }
            } else {
                f.truss = nil; f.trussPos = nil
                f.mount = "floor"; f.zM = 0.25
            }
        }
    }

    /// Adds fixtures: spread along the selected truss, or in a row on the stage floor. Addresses are filled in
    /// after the last used channel, universe by universe.
    func addFixtures(key: String, mode: String, count: Int) {
        guard let def = definition(key), count > 0 else { return }
        let footprint = max(1, def.channels(mode))
        let base = key.split(separator: "/").last.map { String($0.prefix { $0.isLetter }) }.flatMap { $0.isEmpty ? nil : $0 } ?? "fx"
        change("Add \(count) × \(def.model)") { d in
            var used: [Int: [ClosedRange<Int>]] = [:]
            for f in d.fixtures {
                let n = definition(f.key)?.channels(f.mode) ?? 1
                used[f.universe, default: []].append(f.address...(f.address + max(1, n) - 1))
            }
            func free(_ u: Int, _ a: Int) -> Bool {
                a + footprint - 1 <= 512 && !(used[u] ?? []).contains { $0.overlaps(a...(a + footprint - 1)) }
            }
            let truss: Truss? = if case .truss(let id) = selection { d.trusses.first { $0.id == id } } else { nil }
            var newIDs: [String] = []
            for k in 0..<count {
                var u = 1, a = 1
                while !free(u, a) { a += 1; if a > 512 { a = 1; u += 1 } }
                used[u, default: []].append(a...(a + footprint - 1))
                var n = 1
                while d.fixtures.contains(where: { $0.id == "\(base)\(n)" }) || newIDs.contains("\(base)\(n)") { n += 1 }
                let id = "\(base)\(n)"
                newIDs.append(id)
                var f = PlacedFixture(id: id, key: key, mode: mode, universe: u, address: a, mount: "floor",
                                      x: (Double(k) + 1) / Double(count + 1), yM: -0.6, zM: 0.25, rotDeg: 0, aim: nil,
                                      truss: nil, trussPos: nil)
                if let t = truss {
                    let span = t.vertical ? t.lengthM : t.lengthM * 0.9
                    let pos = t.vertical ? span * (Double(k) + 1) / Double(count + 1)
                        : -span / 2 + span * (Double(k) + 0.5) / Double(count)
                    f.mount = t.vertical ? "stand" : "hang"
                    Self.place(&f, on: t, at: pos, width: d.width)
                }
                d.fixtures.append(f)
            }
        }
    }

    // MARK: - zones

    enum ZonePreset: String, CaseIterable, Identifiable {
        case wall, floorArea, keepIn, laserAudience, laserPlane
        var id: String { rawValue }
        var title: String {
            switch self {
            case .wall: "Keep Beams Off a Wall or Set Piece"
            case .floorArea: "Keep Beams Off a Floor Area"
            case .keepIn: "Keep Beams Inside an Area"
            case .laserAudience: "Laser Safety: Audience Box (no lasers)"
            case .laserPlane: "Laser Safety: Floating Plane"
            }
        }
        var symbol: String {
            switch self {
            case .wall: "rectangle.portrait"
            case .floorArea: "rectangle.dashed"
            case .keepIn: "cube.transparent"
            case .laserAudience: "person.3.fill"
            case .laserPlane: "square.3.layers.3d.down.right"
            }
        }
    }

    func addZone(_ p: ZonePreset) {
        let W = doc.width, D = doc.stage.roomDepthM
        let back = min(-2.5, (doc.fixtures.map(\.yM).min() ?? -1) - 1.5)   // the room's back wall (as the visualisers place it)
        let n = (1...).first { i in !doc.zones.contains { $0.id == "zone\(i)" } }!
        let z: Zone = switch p {
        case .wall: Zone(id: "zone\(n)", name: "Back wall", kind: "avoid", shape: "rect",
                         center: [W / 2, back + 0.1, 3], size: [min(W, 8), 4])
        case .floorArea: Zone(id: "zone\(n)", name: "VIP corner", kind: "avoid", shape: "rect",
                              center: [W * 0.85, D * 0.3, 0.05], size: [3, 3], tiltDeg: 90)
        case .keepIn: Zone(id: "zone\(n)", name: "Dance floor and sky", kind: "keep_in", shape: "box",
                           center: [W / 2, D * 0.35, doc.stage.ceilingM / 2], size: [W + 2, D * 0.7, doc.stage.ceilingM])
        case .laserAudience: Zone(id: "zone\(n)", name: "Audience (no lasers)", kind: "laser_out", shape: "box",
                                  center: [W / 2, D / 2 + 0.25, 1.5], size: [W + 6, D - 0.5, 3])
        case .laserPlane: Zone(id: "zone\(n)", name: "No lasers below", kind: "laser_out", shape: "rect",
                               center: [W / 2, D / 2, 3.0], size: [W + 6, D], tiltDeg: 90)
        }
        change("Add Zone") { $0.zones.append(z) }
        selection = .zone(z.id)
    }

    func updateZone(_ id: String, _ name: String = "Change Zone", _ body: (inout Zone) -> Void) {
        change(name) { d in
            guard let i = d.zones.firstIndex(where: { $0.id == id }) else { return }
            body(&d.zones[i])
        }
    }

    func deleteSelection() {
        guard let sel = selection else { return }
        switch sel {
        case .zone(let id):
            change("Delete Zone") { $0.zones.removeAll { $0.id == id } }
        case .truss(let id):
            change("Delete Truss") { d in
                d.trusses.removeAll { $0.id == id }
                for i in d.fixtures.indices where d.fixtures[i].truss == id {
                    d.fixtures[i].truss = nil; d.fixtures[i].trussPos = nil
                    d.fixtures[i].mount = "floor"; d.fixtures[i].zM = 0.25
                }
            }
        case .fixture(let id):
            change("Delete Fixture") { $0.fixtures.removeAll { $0.id == id } }
        }
        selection = nil
    }

    func duplicateSelection() {
        if case .zone(let id) = selection, let z = doc.zones.first(where: { $0.id == id }) {
            let n = (1...).first { i in !doc.zones.contains { $0.id == "zone\(i)" } }!
            var c = z
            c.id = "zone\(n)"; c.name = z.name + " copy"
            c.centerV += [1, 1, 0]
            change("Duplicate Zone") { $0.zones.append(c) }
            selection = .zone(c.id)
            return
        }
        guard case .truss(let id) = selection, let t = doc.trusses.first(where: { $0.id == id }) else { return }
        let n = (1...).first { i in !doc.trusses.contains { $0.id == "truss\(i)" } }!
        var c = t
        c.id = "truss\(n)"
        if t.vertical { c.xM += 1.0 } else { c.yM -= 1.5 }
        change("Duplicate Truss") { $0.trusses.append(c) }
        selection = .truss(c.id)
    }

    func rotateSelection(by deg: Double) {
        switch selection {
        case .truss(let id): updateTruss(id, "Rotate Truss") { $0.rotDeg = Self.wrap($0.rotDeg + deg) }
        case .fixture(let id): updateFixture(id, "Rotate Fixture") { $0.rotDeg = Self.wrap($0.rotDeg + deg) }
        case .zone(let id): updateZone(id, "Rotate Zone") { $0.rotDeg = Self.wrap($0.rotDeg + deg) }
        case nil: break
        }
    }

    func nudge(_ dx: Double, _ dy: Double) {
        switch selection {
        case .truss(let id): updateTruss(id, "Move Truss") { $0.xM += dx; $0.yM += dy }
        case .fixture(let id):
            updateFixture(id, "Move Fixture") { f in
                if f.truss != nil { f.trussPos = (f.trussPos ?? 0) + dx } else { f.x += dx / doc.width; f.yM += dy }
            }
        case .zone(let id): updateZone(id, "Move Zone") { $0.centerV += [dx, dy, 0] }
        case nil: break
        }
    }

    static func wrap(_ a: Double) -> Double {
        var a = a.truncatingRemainder(dividingBy: 360)
        if a > 180 { a -= 360 }
        if a <= -180 { a += 360 }
        return a
    }

    // MARK: - save / revert

    func save() throws {
        let data = try doc.json()
        try data.write(to: workspace.setURL(doc.name), options: .atomic)
        saved = doc
        message = "Saved \(doc.name)"
    }

    func revert() {
        let before = doc
        doc = saved
        refresh()
        registerUndo("Revert", before)
    }

    // MARK: - picking and dragging (StageEditing)

    private func s(_ v: SIMD3<Float>) -> SIMD3<Double> { SIMD3(Double(v.x), Double(v.y), Double(v.z)) }

    /// Distance from a ray to a segment, and how far along the ray.
    private static func rayToSegment(_ o: SIMD3<Double>, _ d: SIMD3<Double>, _ a: SIMD3<Double>, _ b: SIMD3<Double>)
        -> (dist: Double, t: Double) {
        let u = b - a, w = o - a
        let A = simd_dot(d, d), B = simd_dot(d, u), C = simd_dot(u, u), D = simd_dot(d, w), E = simd_dot(u, w)
        let den = A * C - B * B
        var sc = den > 1e-9 ? (B * E - C * D) / den : 0
        var tc = den > 1e-9 ? (A * E - B * D) / den : E / max(C, 1e-9)
        tc = max(0, min(1, tc))
        sc = max(0, (B * tc - D) / A)
        return (simd_length((o + d * sc) - (a + u * tc)), sc)
    }

    func pick(origin: SIMD3<Float>, dir: SIMD3<Float>) -> Bool {
        let o = s(origin), d = s(dir)
        var best: (sel: EditorSelection, score: Double, at: SIMD3<Double>)?
        func consider(_ sel: EditorSelection, _ a: SIMD3<Double>, _ b: SIMD3<Double>, radius: Double) {
            let (dist, t) = Self.rayToSegment(o, d, a, b)
            // fixtures win from the truss they hang on (it's right in front of them, seen from above)
            let score = t - (sel.isFixture ? 0.8 : 0)
            if dist < radius, best == nil || score < best!.score {
                best = (sel, score, o + d * t)
            }
        }
        for f in doc.fixtures {
            let p = f.position(width: doc.width)
            let def = definition(f.key)
            let L = (def?.cells(f.mode) ?? 1) > 1 ? (def?.size.x ?? 1) : 0.0
            let r = f.rotDeg * .pi / 180, ax = SIMD3(cos(r), sin(r), 0) * (L / 2)
            consider(.fixture(f.id), p - ax, p + ax, radius: 0.28)
        }
        for t in doc.trusses {
            if t.vertical {
                consider(.truss(t.id), [t.xM, t.yM, 0], [t.xM, t.yM, t.zM + t.lengthM / 2], radius: 0.3)
            } else {
                consider(.truss(t.id), t.point(-t.lengthM / 2), t.point(t.lengthM / 2), radius: 0.3)
            }
        }
        if best == nil {  // zones last: they're big and see-through, never in the way of rigging
            // overlapping zones: the smallest wins (a big keep-in box would otherwise grab every click;
            // it stays selectable from the list)
            var pickZone: (z: Zone, t: Double, size: Double)?
            for z in doc.zones {
                guard let t = z.hit(o, d) else { continue }
                let size = z.shape == "box" ? pow(z.size.reduce(1, *), 2.0 / 3.0) : z.size.prefix(2).reduce(1, *)
                if pickZone == nil || size < pickZone!.size { pickZone = (z, t, size) }
            }
            if let p = pickZone { best = (.zone(p.z.id), p.t, o + d * p.t) }
        }
        guard let b = best else { return false }
        selection = b.sel
        refresh()
        let start: SIMD3<Double>
        switch b.sel {
        case .truss(let id): let t = doc.trusses.first { $0.id == id }!; start = [t.xM, t.yM, t.zM]
        case .fixture(let id): start = doc.fixtures.first { $0.id == id }!.position(width: doc.width)
        case .zone(let id): start = doc.zones.first { $0.id == id }!.centerV
        }
        drag = (b.sel, b.at, start, doc)
        return true
    }

    func drag(origin: SIMD3<Float>, dir: SIMD3<Float>, free: Bool) {
        guard let g = drag else { return }
        let o = s(origin), d = s(dir)
        // move in the horizontal plane at the height where it was grabbed
        guard abs(d.z) > 1e-4 else { return }
        let t = (g.grab.z - o.z) / d.z
        guard t > 0 else { return }
        let hit = o + d * t
        var target = g.start + (hit - g.grab)
        let grid = Self.grid
        let snapOn = snap && !free
        switch g.sel {
        case .zone(let id):
            if snapOn { target.x = (target.x / grid).rounded() * grid; target.y = (target.y / grid).rounded() * grid }
            if let i = doc.zones.firstIndex(where: { $0.id == id }) {
                doc.zones[i].centerV = SIMD3(target.x, target.y, doc.zones[i].centerV.z)
            }
        case .truss(let id):
            if snapOn { target.x = (target.x / grid).rounded() * grid; target.y = (target.y / grid).rounded() * grid }
            if let i = doc.trusses.firstIndex(where: { $0.id == id }) {
                doc.trusses[i].xM = target.x
                doc.trusses[i].yM = target.y
                Self.followTruss(&doc, doc.trusses[i])
            }
        case .fixture(let id):
            guard let i = doc.fixtures.firstIndex(where: { $0.id == id }) else { return }
            var f = doc.fixtures[i]
            let p2 = SIMD2(target.x, target.y)
            // snap onto the nearest truss within reach (towers by their footprint)
            let near = doc.trusses.map { ($0, $0.project(p2)) }.filter { $0.1.distance < 0.9 }.min { $0.1.distance < $1.1.distance }
            if let (tr, pr) = near, snap || !free {
                var u = tr.vertical ? (f.truss == tr.id ? (f.trussPos ?? 1) : min(tr.lengthM - 0.3, 1.0)) : pr.u
                if snapOn && !tr.vertical { u = (u / grid).rounded() * grid }
                if f.truss != tr.id && f.mount == "floor" { f.mount = tr.vertical ? "stand" : "hang"; f.side = nil }
                if !tr.vertical {  // dragged across the truss: onto its front or back face (centre: under / on top)
                    let r = tr.rotDeg * .pi / 180, n = SIMD2(-sin(r), cos(r))
                    let across = simd_dot(p2 - SIMD2(tr.point(pr.u).x, tr.point(pr.u).y), n)
                    if across > 0.2 { f.side = "front" }
                    else if across < -0.2 { f.side = "back" }
                    else if f.side == "front" || f.side == "back" || f.truss != tr.id { f.side = f.mount == "stand" ? "top" : "under" }
                }
                Self.place(&f, on: tr, at: u, width: doc.width)
            } else {
                if snapOn { target.x = (target.x / grid).rounded() * grid; target.y = (target.y / grid).rounded() * grid }
                if f.truss != nil { f.truss = nil; f.trussPos = nil; f.side = nil; f.mountRoll = nil; f.mount = "floor"; f.zM = 0.25 }
                f.x = target.x / doc.width
                f.yM = target.y
            }
            doc.fixtures[i] = f
        }
        refresh()
    }

    func endDrag() {
        guard let g = drag else { return }
        drag = nil
        if doc != g.before {
            registerUndo(g.sel.isFixture ? "Move Fixture" : g.sel.isZone ? "Move Zone" : "Move Truss", g.before)
        }
    }

    func clickedEmpty() {
        if selection != nil { selection = nil; refresh() }
    }

    func key(_ e: NSEvent) -> Bool {
        let shift = e.modifierFlags.contains(.shift)
        let step = shift ? 0.5 : 0.1
        switch e.keyCode {
        case 51, 117: deleteSelection(); return selection == nil  // ⌫ / ⌦
        case 123: nudge(-step, 0); return true                       // ←
        case 124: nudge(step, 0); return true                        // →
        case 125: nudge(0, step); return true                        // ↓ (towards the audience)
        case 126: nudge(0, -step); return true                       // ↑ (towards the back)
        default: break
        }
        switch e.charactersIgnoringModifiers?.lowercased() {
        case "r": rotateSelection(by: shift ? 90 : 15); return true
        case "\u{1b}": clickedEmpty(); return true
        default: return false
        }
    }
}

extension EditorSelection {
    var isFixture: Bool { if case .fixture = self { true } else { false } }
    var isZone: Bool { if case .zone = self { true } else { false } }
}
