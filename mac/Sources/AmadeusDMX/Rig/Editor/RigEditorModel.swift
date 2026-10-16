// The rig editor's state: a set placed on a rig. The rig's trusses can be placed, moved, raised, turned and
// resized; the set's fixtures snap onto trusses (and move along with them), slide along them, turn, and aim.
// Fixtures not mounted yet wait on the floor in front of the stage. Several fixtures can be selected and
// dragged together, or dropped onto a truss from the inspector; auto-mount places the rest.
// Saving goes through the engine, which writes the rig (trusses, stage, zones, placements) and the set.
import AppKit
import AmadeusKit
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
    /// The primary selection (what the inspector shows); `group` holds more fixtures selected along with it.
    var selection: EditorSelection? { didSet { if case .fixture = selection {} else if selection != nil { group = [] } } }
    var group: Set<String> = []
    /// While something is dragged over the stage from the inspector: the truss it would land on.
    private(set) var dropTarget: String?
    /// What the pointer is over (a click would pick it): lit a little.
    @ObservationIgnored private var hovered: String?
    var snap = true
    var showZones = true { didSet { version += 1 } }

    // building trusses in the stage, like a construction game: draw a truss on the floor, click to set a tower,
    // drag a truss's end handles to stretch or turn it, a tower's top to make it taller
    enum Tool: String {
        case select, truss, tower

        var hint: String? {
            switch self {
            case .select: nil
            case .truss: "Drag on the floor to draw a truss (½ m steps, 15° turns; ⌥: free). Esc: done"
            case .tower: "Click on the floor to set a tower. Esc: done"
            }
        }
    }
    var tool: Tool = .select { didSet { message = tool.hint } }
    var buildHeight = 4.5     // a new truss goes up to this height (m)
    var towerHeight = 4.0     // a new tower is this tall (m)
    static let buildGrid = 0.5, buildAngle = 15.0
    @ObservationIgnored private var stretch: (id: String, fixed: SIMD2<Double>, planeZ: Double, before: RigDocument, new: Bool)?
    @ObservationIgnored private var raise: (id: String, before: RigDocument)?
    var message: String?
    var busy = false
    @ObservationIgnored var undoManager: UndoManager?
    @ObservationIgnored private var defs: [String: FixtureDefinition] = [:]
    @ObservationIgnored private let workspace: Workspace
    @ObservationIgnored private var drag: (sel: EditorSelection, grab: SIMD3<Double>, start: SIMD3<Double>, before: RigDocument)?
    @ObservationIgnored private var version = 0

    static let hangDrop = 0.42    // a fixture under a truss: its beam centre below the truss centre
    static let sideOut = 0.4      // a fixture on the front/back face: its centre out from the truss centre
    static let sides = ["under", "top", "front", "back"]
    static let towerSides = ["front", "back", "left", "right", "top"]
    static let towerOut = 0.32    // a fixture on a tower's face: its centre out from the tower's centre
    static let towerTop = 0.3     // a fixture on top of a tower: its centre above the top

    /// The outward direction of a tower's face (front: towards the audience; left/right: across the stage).
    static func towerNormal(_ t: Truss, _ side: String) -> SIMD2<Double> {
        let r = t.rotDeg * .pi / 180, front = SIMD2(-sin(r), cos(r))
        switch side {
        case "back": return -front
        case "right": return SIMD2(front.y, -front.x)
        case "left": return SIMD2(-front.y, front.x)
        default: return front
        }
    }
    static let grid = 0.25        // snapping step (m)
    static let spacing = 0.6      // fixtures dropped or dragged as a group: this far apart on a truss
    static let payloadPrefix = "fixtures:"

    init?(workspace: Workspace, rig: String, set: String) {
        guard var d = workspace.document(rig: rig, set: set) else { return nil }
        // fixtures placed on a tower before towers had faces stood in front of it: onto its front face now
        for i in d.fixtures.indices {
            guard let tid = d.fixtures[i].truss, let t = d.trusses.first(where: { $0.id == tid }), t.vertical,
                  !Self.towerSides.contains(d.fixtures[i].side ?? "") else { continue }
            d.fixtures[i].side = "front"
            Self.place(&d.fixtures[i], on: t, at: d.fixtures[i].trussPos ?? t.lengthM - 0.3, width: d.width)
        }
        self.workspace = workspace
        doc = d
        saved = d
    }

    var isDirty: Bool { doc != saved }
    var rigName: String { doc.rig }
    var setName: String { doc.set }

    func definition(_ key: String) -> FixtureDefinition? {
        if let d = defs[key] { return d }
        let d = workspace.definition(key)
        defs[key] = d
        return d
    }

    /// Every selected fixture: the primary one and the group.
    var selectedFixtures: Set<String> {
        var s = group
        if case .fixture(let id) = selection { s.insert(id) }
        return s
    }

    func select(fixtures ids: [String]) {
        guard let first = ids.first else { selection = nil; group = []; return }
        selection = .fixture(first)
        group = Set(ids.dropFirst())
        refresh()
    }

    // MARK: - what the stage shows

    func stageInput() -> StageInput {
        let els = RigElements.elements(doc) { [unowned self] in definition($0) }
        var selected = selection.map { [$0.key] } ?? []
        selected += group.map { "fixture:\($0)" }
        if let t = dropTarget { selected.append("truss:\(t)") }
        if let h = hovered, !selected.contains(h) { selected.append("hover:" + h) }
        return StageInput(key: "edit:\(doc.label):\(version)", fixtures: els, stage: doc.stage, screen: doc.hasScreen, hello: nil,
                          trusses: doc.trusses, selected: Set(selected), keepCamera: true,
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

    // MARK: - the venue

    func updateStage(_ name: String = "Change Stage", _ body: (inout Stage) -> Void) {
        change(name) { d in
            body(&d.stage)
            // merged into what was there: the stage keeps the settings the editor doesn't show (eye safety…)
            var merged = d.raw["stage"]?.object ?? [:]
            if let o = (try? JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(d.stage)))?.object {
                merged.merge(o) { _, new in new }
            }
            d.raw["stage"] = .object(merged)
        }
    }

    func setScreen(_ on: Bool) {
        change(on ? "Add LED Wall" : "Remove LED Wall") { d in
            d.raw["screen"] = on ? .object(["width_m": .number(min(10, d.width * 0.55).rounded())]) : nil
        }
    }

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

    /// A round truss (a circle, or a half circle opening towards the audience) over the middle of the stage.
    func addRing(diameter: Double, arc: Double = 360) {
        let W = doc.width
        let t = Truss.ring(id: newTrussID(arc >= 359.5 ? "ring" : "arc"), diameter: diameter, arc: arc, xM: W / 2,
                           yM: -0.6 - diameter / 2, zM: min(doc.stage.ceilingM - 1, 4.5), rotDeg: arc >= 359.5 ? 0 : 180)
        change(arc >= 359.5 ? "Add Round Truss" : "Add Half Circle") { $0.trusses.append(t) }
        selection = .truss(t.id)
    }

    func updateTruss(_ id: String, _ name: String = "Change Truss", _ body: (inout Truss) -> Void) {
        change(name) { d in
            guard let i = d.trusses.firstIndex(where: { $0.id == id }) else { return }
            let oldRot = d.trusses[i].rotDeg
            body(&d.trusses[i])
            d.trusses[i].normalise()
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

    /// Clamp a fixture to a truss (amadeus/rig/trusses.py place: the same rules).
    static func place(_ f: inout PlacedFixture, on t: Truss, at u: Double, width: Double) {
        var u = u
        if t.isFullRing {  // round the circle: past one end is the other
            u = (u + t.lengthM / 2).truncatingRemainder(dividingBy: t.lengthM)
            if u < 0 { u += t.lengthM }
            u -= t.lengthM / 2
        }
        u = t.vertical ? max(0.2, min(t.lengthM, u)) : max(-t.lengthM / 2, min(t.lengthM / 2, u))
        if f.truss != t.id && !t.vertical { f.rotDeg = t.rotDeg }  // clamped on: square to the truss
        if t.isRing {  // on a ring: always turned with the arc, its front out of the circle
            var r = (t.directionDeg(u) + 180).truncatingRemainder(dividingBy: 360)
            if r < 0 { r += 360 }
            f.rotDeg = ((r - 180) * 10).rounded() / 10
        }
        f.truss = t.id
        f.trussPos = u
        f.waiting = false
        if t.vertical {
            // a tower's four faces: the fixture hangs off the face (base against the truss, head out of it, like
            // on a box truss's side); only on top does it stand
            let side = f.side.flatMap { towerSides.contains($0) ? $0 : nil } ?? "front"
            let base = t.zM - t.lengthM / 2
            f.side = side
            if side == "top" {
                f.trussPos = t.lengthM
                f.x = t.xM / width
                f.yM = t.yM
                f.zM = base + t.lengthM + towerTop
                f.mount = "stand"
                f.mountRoll = nil
            } else {
                let n = towerNormal(t, side)
                f.trussPos = max(0.2, min(t.lengthM - 0.2, u))
                f.x = (t.xM + n.x * towerOut) / width
                f.yM = t.yM + n.y * towerOut
                f.zM = base + f.trussPos!
                f.mount = "hang"
                f.mountRoll = 90
                var r = atan2(-n.x, n.y) * 180 / .pi
                if r < 0 { r += 360 }
                f.rotDeg = (r * 10).rounded() / 10
            }
        } else {
            // the box truss's four sides: under it, on top, on the front (audience) or the back face
            let side = f.side.flatMap { sides.contains($0) ? $0 : nil } ?? (f.mount == "stand" ? "top" : "under")
            // n: towards the audience (on a ring: out of the circle)
            let p = t.point(u), r = t.directionDeg(u) * .pi / 180, n = SIMD2(-sin(r), cos(r))
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

    /// Every selected fixture on a box truss: onto this side of it.
    func setSide(_ ids: Set<String>, _ side: String) {
        change("Move to \(side.capitalized)") { d in
            for i in d.fixtures.indices where ids.contains(d.fixtures[i].id) {
                guard let tid = d.fixtures[i].truss, let t = d.trusses.first(where: { $0.id == tid }),
                      (t.vertical ? Self.towerSides : Self.sides).contains(side) else { continue }
                d.fixtures[i].side = side
                Self.place(&d.fixtures[i], on: t, at: d.fixtures[i].trussPos ?? 0, width: d.width)
            }
        }
    }

    // MARK: - fixtures

    func updateFixture(_ id: String, _ name: String = "Change Fixture", _ body: (inout PlacedFixture) -> Void) {
        change(name) { d in
            guard let i = d.fixtures.firstIndex(where: { $0.id == id }) else { return }
            body(&d.fixtures[i])
            d.fixtures[i].waiting = false
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
                f.truss = nil; f.trussPos = nil; f.side = nil; f.mountRoll = nil
                f.mount = "floor"; f.zM = 0.25
            }
        }
    }

    /// Back to waiting in front of the stage: not mounted on this rig any more (the set keeps them).
    func unmount(_ ids: Set<String>) {
        change(ids.count == 1 ? "Unmount Fixture" : "Unmount \(ids.count) Fixtures") { d in
            for i in d.fixtures.indices where ids.contains(d.fixtures[i].id) {
                d.fixtures[i].waiting = true
                d.fixtures[i].truss = nil; d.fixtures[i].trussPos = nil; d.fixtures[i].side = nil; d.fixtures[i].mountRoll = nil
                d.fixtures[i].rotDeg = 0; d.fixtures[i].aim = nil
            }
            Self.lineUpWaiting(&d)
        }
        selection = nil
        group = []
    }

    /// Waiting fixtures stand in a row on the floor at the front of the stage (as the engine puts them).
    private static func lineUpWaiting(_ d: inout RigDocument) {
        let waiting = d.fixtures.indices.filter { d.fixtures[$0].waiting }
        for (k, i) in waiting.enumerated() {
            d.fixtures[i].x = (Double(k) + 1) / Double(waiting.count + 1)
            d.fixtures[i].yM = -0.3
            d.fixtures[i].zM = 0.25
            d.fixtures[i].mount = "floor"
        }
    }

    /// Fixtures in a row along a truss, centred as near `u` as there is room (or one above the other on a tower),
    /// `spacing` apart, clear of the fixtures already on that side of the truss.
    private static func arrange(_ d: inout RigDocument, _ ids: [String], on t: Truss, at u: Double, side: String?,
                                width: (PlacedFixture) -> Double) {
        let n = Double(ids.count)
        let own = ids.compactMap { id in d.fixtures.first { $0.id == id } }.map(width).max() ?? 0.4
        let step = t.vertical ? 0.6 : max(spacing, own + 0.15)
        let span = step * (n - 1)
        // keep the whole row on the truss
        let lo = t.vertical ? 0.3 : -t.lengthM / 2, hi = t.vertical ? t.lengthM - 0.3 : t.lengthM / 2
        let mine = Set(ids)
        let busy = d.fixtures.filter { f in
            !mine.contains(f.id) && f.truss == t.id && (t.vertical || (f.side ?? "under") == (side ?? "under"))
        }.compactMap { f in f.trussPos.map { ($0, t.vertical ? 0.45 : width(f)) } }
        func fits(_ start: Double) -> Bool {   // housings at least 15 cm apart
            start >= lo - 1e-6 && start + span <= hi + 1e-6
                && (0..<ids.count).allSatisfy { k in
                    busy.allSatisfy { abs(start + step * Double(k) - $0.0) >= (own + $0.1) / 2 + 0.15 }
                }
        }
        let wanted = max(lo, min(hi - span, u - span / 2))
        // the nearest free stretch: try further and further to either side
        let start = stride(from: 0.0, through: t.lengthM, by: 0.05).lazy
            .flatMap { off in [wanted - off, wanted + off] }
            .first(where: fits) ?? wanted
        for (k, id) in ids.enumerated() {
            guard let i = d.fixtures.firstIndex(where: { $0.id == id }) else { continue }
            if d.fixtures[i].truss != t.id {
                d.fixtures[i].side = side
                if d.fixtures[i].mount == "floor" || d.fixtures[i].waiting { d.fixtures[i].mount = "hang" }
            }
            place(&d.fixtures[i], on: t, at: start + step * Double(k), width: d.width)
        }
    }

    /// Fixtures in a row on the floor around a point, left to right.
    private static func lineUp(_ d: inout RigDocument, _ ids: [String], at p: SIMD2<Double>) {
        let span = spacing * Double(ids.count - 1)
        for (k, id) in ids.enumerated() {
            guard let i = d.fixtures.firstIndex(where: { $0.id == id }) else { continue }
            d.fixtures[i].truss = nil; d.fixtures[i].trussPos = nil; d.fixtures[i].side = nil; d.fixtures[i].mountRoll = nil
            d.fixtures[i].waiting = false
            d.fixtures[i].mount = "floor"
            d.fixtures[i].zM = 0.25
            d.fixtures[i].x = (p.x - span / 2 + spacing * Double(k)) / d.width
            d.fixtures[i].yM = p.y
        }
    }

    /// Adds fixtures to the set: spread along the selected truss, or in a row on the stage floor. Addresses are
    /// filled in after the last used channel, universe by universe.
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
                    f.mount = "hang"
                    Self.place(&f, on: t, at: pos, width: d.width)
                }
                d.fixtures.append(f)
            }
        }
    }

    // MARK: - auto-mount

    /// Mount fixtures the engine's way (amadeus/rig/automount.py): `ids`, or the ones waiting, or `all`.
    /// One undoable change; nothing is saved until Save.
    func autoMount(_ model: AppModel, ids: [String]? = nil, all: Bool = false) async {
        busy = true
        defer { busy = false }
        do {
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            guard let layout = try JSONSerialization.jsonObject(with: try doc.json()) as? [String: Any] else { return }
            let (places, trusses) = try await model.api.automountPlacements(layout: layout, ids: ids, all: all)
            apply(places, trusses: trusses, name: places.count == 1 ? "Auto-Mount Fixture" : "Auto-Mount \(places.count) Fixtures")
            if let trusses, !trusses.isEmpty, doc.trusses.count == trusses.count {
                message = "The rig had no trusses: it has \(trusses.count) now (where its fixtures hung, or a standard set-up)"
                return
            }
            message = places.isEmpty ? "Everything is mounted already" : "Mounted \(places.count) fixture\(places.count == 1 ? "" : "s")"
        } catch {
            message = error.localizedDescription
        }
    }

    /// The hang sheet of the layout as it is now (saved or not), opened in the browser to print or save as PDF:
    /// where every fixture goes, which way round, its DMX address, and labels for the fixtures.
    func hangSheet(_ model: AppModel) async {
        busy = true
        defer { busy = false }
        do {
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            guard let layout = try JSONSerialization.jsonObject(with: try doc.json()) as? [String: Any] else { return }
            let page = try await model.api.hangSheet(layout: layout, set: doc.set, rig: doc.rig)
            let url = FileManager.default.temporaryDirectory.appending(path: "Hang Sheet – \(doc.set) on \(doc.rig).html")
            try page.write(to: url)
            NSWorkspace.shared.open(url)
            message = doc.waitingCount > 0 ? "\(doc.waitingCount) fixtures aren’t mounted yet: they’re not on the sheet" : "Hang sheet opened in your browser"
        } catch {
            message = error.localizedDescription
        }
    }

    /// Placements (fixture id → position fields, as in a rig file) onto the fixtures.
    func apply(_ places: [String: [String: JSONValue]], trusses: [Truss]? = nil, name: String) {
        change(name) { d in
            if let trusses, d.trusses.isEmpty { d.trusses = trusses }  // a rig without trusses got its structure
            for i in d.fixtures.indices {
                guard let p = places[d.fixtures[i].id] else { continue }
                var f = d.fixtures[i]
                f.waiting = false
                f.mount = p["mount"]?.string ?? "stand"
                f.x = p["x"]?.number ?? f.x
                f.yM = p["y_m"]?.number ?? f.yM
                f.zM = p["z_m"]?.number ?? f.zM
                f.rotDeg = p["rot_deg"]?.number ?? 0
                f.aim = p["aim"]?.array.flatMap { a in a.count == 2 ? SIMD2(a[0].number ?? 0, a[1].number ?? 0) : nil }
                f.truss = p["truss"]?.string
                f.trussPos = p["truss_pos_m"]?.number
                f.side = p["truss_side"]?.string
                f.mountRoll = p["mount_roll_deg"]?.number
                d.fixtures[i] = f
            }
            Self.lineUpWaiting(&d)
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

    /// ⌫: a zone or truss is deleted; fixtures are unmounted (they stay in the set, waiting in front).
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
        case .fixture:
            unmount(selectedFixtures)
            return
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
        case .fixture:
            let ids = selectedFixtures
            change("Rotate") { d in
                for i in d.fixtures.indices where ids.contains(d.fixtures[i].id) {
                    d.fixtures[i].rotDeg = Self.wrap(d.fixtures[i].rotDeg + deg)
                    d.fixtures[i].waiting = false
                }
            }
        case .zone(let id): updateZone(id, "Rotate Zone") { $0.rotDeg = Self.wrap($0.rotDeg + deg) }
        case nil: break
        }
    }

    func nudge(_ dx: Double, _ dy: Double) {
        switch selection {
        case .truss(let id): updateTruss(id, "Move Truss") { $0.xM += dx; $0.yM += dy }
        case .fixture:
            let ids = selectedFixtures
            change("Move") { d in
                for i in d.fixtures.indices where ids.contains(d.fixtures[i].id) {
                    var f = d.fixtures[i]
                    f.waiting = false
                    if let tid = f.truss, let t = d.trusses.first(where: { $0.id == tid }) {
                        Self.place(&f, on: t, at: (f.trussPos ?? 0) + dx, width: d.width)
                    } else {
                        f.x += dx / d.width; f.yM += dy
                    }
                    d.fixtures[i] = f
                }
            }
        case .zone(let id): updateZone(id, "Move Zone") { $0.centerV += [dx, dy, 0] }
        case nil: break
        }
    }

    /// ↑ / ↓ on fixtures clamped to a truss: round the truss to its next side (under → front → top → back), or
    /// round a tower to its next face (front → right → back → left). False if none of them is on a truss.
    func rollAround(_ step: Int) -> Bool {
        guard case .fixture = selection else { return false }
        let ids = selectedFixtures
        guard doc.fixtures.contains(where: { ids.contains($0.id) && $0.truss != nil }) else { return false }
        change(step > 0 ? "Round the Truss" : "Round the Truss Back") { d in
            for i in d.fixtures.indices where ids.contains(d.fixtures[i].id) {
                guard let tid = d.fixtures[i].truss, let t = d.trusses.first(where: { $0.id == tid }) else { continue }
                let order = t.vertical ? ["front", "right", "back", "left"] : ["under", "front", "top", "back"]
                let now = d.fixtures[i].side ?? (t.vertical ? "front" : (d.fixtures[i].mount == "stand" ? "top" : "under"))
                let k = order.firstIndex(of: now) ?? 0
                d.fixtures[i].side = order[((k + step) % order.count + order.count) % order.count]
                d.fixtures[i].waiting = false
                Self.place(&d.fixtures[i], on: t, at: d.fixtures[i].trussPos ?? 0, width: d.width)
            }
        }
        return true
    }

    static func wrap(_ a: Double) -> Double {
        var a = a.truncatingRemainder(dividingBy: 360)
        if a > 180 { a -= 360 }
        if a <= -180 { a += 360 }
        return a
    }

    // MARK: - save / revert

    /// Saved through the engine's setup API: it splits the layout into the rig file and the set file.
    func save(_ model: AppModel) async throws {
        guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
        guard let layout = try JSONSerialization.jsonObject(with: try doc.json()) as? [String: Any] else { return }
        if doc.set.isEmpty {  // the rig alone
            try await model.api.saveRigStructure(layout, rig: doc.rig)
        } else {
            try await model.api.saveRig(layout, rigName: doc.rig, setName: doc.set)
        }
        saved = doc
        message = "Saved \(doc.rig)"
        model.reloadSets()
    }

    /// The files changed (an auto-mount from elsewhere, a fixture added to the set): read them again, unless
    /// there are unsaved changes here.
    func reloadIfClean() {
        guard !isDirty, let d = workspace.document(rig: doc.rig, set: doc.set), d != doc else { return }
        doc = d
        saved = d
        selection = nil
        group = []
        refresh()
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

    /// The truss a ray passes closest to (within `radius`), and where along it.
    private func truss(near o: SIMD3<Double>, _ d: SIMD3<Double>, radius: Double) -> (Truss, Double)? {
        var best: (Truss, Double, Double)?
        for t in doc.trusses {
            let pieces = t.vertical ? [(SIMD3(t.xM, t.yM, 0), SIMD3(t.xM, t.yM, t.zM + t.lengthM / 2))] : t.pieces()
            for (a, b) in pieces {
                let (dist, along) = Self.rayToSegment(o, d, a, b)
                guard dist < radius, best == nil || dist < best!.2 else { continue }
                let hit = o + d * along
                let u = t.vertical ? hit.z - (t.zM - t.lengthM / 2) : t.project(SIMD2(hit.x, hit.y)).u
                best = (t, u, dist)
            }
        }
        return best.map { ($0.0, $0.1) }
    }

    // MARK: - building trusses

    private static func plane(_ o: SIMD3<Double>, _ d: SIMD3<Double>, z: Double) -> SIMD2<Double>? {
        guard abs(d.z) > 1e-4 else { return nil }
        let t = (z - o.z) / d.z
        guard t > 0 else { return nil }
        let p = o + d * t
        return SIMD2(p.x, p.y)
    }

    private func snapped(_ p: SIMD2<Double>) -> SIMD2<Double> {
        guard snap else { return p }
        let g = Self.buildGrid
        return SIMD2((p.x / g).rounded() * g, (p.y / g).rounded() * g)
    }

    private func newTrussID(_ base: String) -> String {
        "\(base)\((1...).first { i in !doc.trusses.contains { $0.id == "\(base)\(i)" } }!)"
    }

    /// The end points of a horizontal truss, seen from above.
    private static func ends(_ t: Truss) -> (SIMD2<Double>, SIMD2<Double>) {
        let a = t.point(-t.lengthM / 2), b = t.point(t.lengthM / 2)
        return (SIMD2(a.x, a.y), SIMD2(b.x, b.y))
    }

    /// A press in a build tool, or on a selected truss's handle: true if it starts a build drag.
    private func pickBuild(_ o: SIMD3<Double>, _ d: SIMD3<Double>) -> Bool {
        switch tool {
        case .truss:
            guard let p = Self.plane(o, d, z: 0).map(snapped) else { return false }
            let before = doc
            let t = Truss(id: newTrussID("truss"), lengthM: 0, xM: p.x, yM: p.y, zM: buildHeight)
            doc.trusses.append(t)
            selection = .truss(t.id)
            stretch = (t.id, p, 0, before, true)
            refresh()
            return true
        case .tower:
            guard let p = Self.plane(o, d, z: 0).map(snapped) else { return false }
            let t = Truss(id: newTrussID("tower"), lengthM: towerHeight, xM: p.x, yM: p.y, zM: towerHeight / 2, vertical: true)
            change("Place Tower") { $0.trusses.append(t) }
            selection = .truss(t.id)
            return true
        case .select:
            guard case .truss(let id) = selection, let t = doc.trusses.first(where: { $0.id == id }) else { return false }
            if t.vertical {  // the handle on top: taller or shorter
                let top = SIMD3(t.xM, t.yM, t.zM + t.lengthM / 2)
                if Self.rayToSegment(o, d, top, top + [0, 0, 0.01]).0 < 0.35 { raise = (id, doc); return true }
                return false
            }
            if t.isRing { return false }  // a ring has no ends to stretch: its size is in the inspector
            let (a, b) = Self.ends(t)
            for (end, other) in [(a, b), (b, a)] {
                let p = SIMD3(end.x, end.y, t.zM)
                if Self.rayToSegment(o, d, p, p + [0, 0, 0.01]).0 < 0.35 {  // an end handle: stretch or turn
                    stretch = (id, other, t.zM, doc, false)
                    return true
                }
            }
            return false
        }
    }

    /// Dragging a build: true if one is going on.
    private func dragBuild(_ o: SIMD3<Double>, _ d: SIMD3<Double>, free: Bool) -> Bool {
        if let st = stretch {
            guard let i = doc.trusses.firstIndex(where: { $0.id == st.id }), var p = Self.plane(o, d, z: st.planeZ) else { return true }
            if !free { p = snapped(p) }
            var v = p - st.fixed
            var length = simd_length(v)
            var angle = atan2(v.y, v.x) * 180 / .pi
            if snap && !free {
                length = (length / Self.buildGrid).rounded() * Self.buildGrid
                angle = (angle / Self.buildAngle).rounded() * Self.buildAngle
            }
            let r = angle * .pi / 180
            v = SIMD2(cos(r), sin(r)) * length
            doc.trusses[i].lengthM = length
            doc.trusses[i].rotDeg = Self.wrap(angle)
            doc.trusses[i].xM = st.fixed.x + v.x / 2
            doc.trusses[i].yM = st.fixed.y + v.y / 2
            Self.followTruss(&doc, doc.trusses[i])
            message = String(format: "%.1f m at %.0f°", length, Self.wrap(angle))
            refresh()
            return true
        }
        if let r = raise {
            guard let i = doc.trusses.firstIndex(where: { $0.id == r.id }) else { return true }
            let t = doc.trusses[i]
            // the pointer on an upright plane through the tower, facing the camera
            let n = simd_normalize(SIMD3(d.x, d.y, 0) + [1e-9, 0, 0])
            let a = SIMD3(t.xM, t.yM, 0.0)
            let den = simd_dot(d, n)
            guard abs(den) > 1e-6 else { return true }
            let z = (o + d * (simd_dot(a - o, n) / den)).z
            var length = max(1, z)
            if snap && !free { length = max(1, (length / Self.buildGrid).rounded() * Self.buildGrid) }
            doc.trusses[i].lengthM = length
            doc.trusses[i].zM = length / 2
            Self.followTruss(&doc, doc.trusses[i])
            message = String(format: "tower %.1f m", length)
            refresh()
            return true
        }
        return false
    }

    func pick(origin: SIMD3<Float>, dir: SIMD3<Float>, extend: Bool) -> Bool {
        let o = s(origin), d = s(dir)
        if pickBuild(o, d) { return true }
        if tool != .select { return true }  // building: the camera doesn't turn under the pointer
        guard let b = hit(o, d) else { return false }
        return grab(b, extend: extend)
    }

    /// What is under the pointer: a fixture when the ray passes right over it, else the nearest truss (as seen
    /// from the camera: a tolerance of about 1.5° of view, at least 30 cm), else a zone.
    private func hit(_ o: SIMD3<Double>, _ d: SIMD3<Double>) -> (sel: EditorSelection, score: Double, at: SIMD3<Double>)? {
        var best: (sel: EditorSelection, score: Double, at: SIMD3<Double>)?
        func consider(_ sel: EditorSelection, _ a: SIMD3<Double>, _ b: SIMD3<Double>, radius: Double) {
            let (dist, t) = Self.rayToSegment(o, d, a, b)
            let tolerance = max(radius, t * Self.pickAngle)
            guard dist < tolerance else { return }
            // how close the pointer is, as seen from the camera; a fixture right under the pointer wins from the
            // truss it hangs on, but a click on the truss between fixtures is the truss
            var score = dist / max(t, 0.5)
            if sel.isFixture && dist < Self.fixtureCore { score -= 1 }
            if best == nil || score < best!.score { best = (sel, score, o + d * t) }
        }
        for f in doc.fixtures {
            let p = f.position(width: doc.width)
            let def = definition(f.key)
            let L = (def?.cells(f.mode) ?? 1) > 1 ? (def?.size.x ?? 1) : 0.0
            let r = f.rotDeg * .pi / 180, ax = SIMD3(cos(r), sin(r), 0) * (L / 2)
            consider(.fixture(f.id), p - ax, p + ax, radius: 0.22)
            if f.mount == "stand" && f.truss == nil && p.z > 0.6 {  // its stand is the fixture too
                consider(.fixture(f.id), [p.x, p.y, 0], [p.x, p.y, p.z - 0.2], radius: 0.15)
            }
        }
        for t in doc.trusses {
            if t.vertical {
                consider(.truss(t.id), [t.xM, t.yM, 0], [t.xM, t.yM, t.zM + t.lengthM / 2], radius: 0.3)
            } else {
                for (a, b) in t.pieces() { consider(.truss(t.id), a, b, radius: 0.3) }
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
        return best
    }

    static let pickAngle = 0.026          // ~1.5° of view: how close to something a click must be
    static let fixtureCore = 0.2          // a click this close to a fixture (m) is the fixture, not its truss

    /// The pointer moved over the stage: light up what a click would pick.
    func hover(origin: SIMD3<Float>, dir: SIMD3<Float>) {
        let key = tool == .select ? hit(s(origin), s(dir)).map { $0.sel.key } : nil
        if key != hovered { hovered = key; refresh() }
    }

    private func grab(_ b: (sel: EditorSelection, score: Double, at: SIMD3<Double>), extend: Bool) -> Bool {
        if case .fixture(let id) = b.sel {
            if extend {  // ⇧-click: add to (or take out of) the selection
                var all = selectedFixtures
                if all.contains(id) { all.remove(id) } else { all.insert(id) }
                let ordered = [id] + all.filter { $0 != id }.sorted()
                select(fixtures: all.contains(id) ? ordered : Array(all.sorted()))
                if !all.contains(id) { return true }
            } else if !selectedFixtures.contains(id) {
                group = []
                selection = b.sel
            } else {  // a click on one of the selected fixtures: it leads, the others come along
                var rest = selectedFixtures
                rest.remove(id)
                selection = b.sel
                group = rest
            }
        } else {
            group = []
            selection = b.sel
        }
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
        if dragBuild(s(origin), s(dir), free: free) { return }
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
            f.waiting = false
            let p2 = SIMD2(target.x, target.y)
            // snap onto the nearest truss within reach (towers by their footprint)
            let near = doc.trusses.map { ($0, $0.project(p2)) }.filter { $0.1.distance < 0.9 }.min { $0.1.distance < $1.1.distance }
            if let (tr, pr) = near, snap || !free {
                var u = tr.vertical ? (f.truss == tr.id ? (f.trussPos ?? 1) : min(tr.lengthM - 0.3, 1.0)) : pr.u
                if snapOn && !tr.vertical { u = (u / grid).rounded() * grid }
                if f.truss != tr.id && f.mount == "floor" { f.mount = "hang"; f.side = nil }
                if tr.vertical {  // dragged off one side of the tower: onto that face (on top stays on top)
                    let off = p2 - SIMD2(tr.xM, tr.yM)
                    if simd_length(off) > 0.12 && f.side != "top" {
                        f.side = ["front", "back", "left", "right"].max { simd_dot(off, Self.towerNormal(tr, $0)) < simd_dot(off, Self.towerNormal(tr, $1)) }
                    } else if f.truss != tr.id { f.side = "front" }
                } else {  // dragged across the truss: onto its front or back face (centre: under / on top)
                    let r = tr.rotDeg * .pi / 180, n = SIMD2(-sin(r), cos(r))
                    let across = simd_dot(p2 - SIMD2(tr.point(pr.u).x, tr.point(pr.u).y), n)
                    if across > 0.2 { f.side = "front" }
                    else if across < -0.2 { f.side = "back" }
                    else if f.side == "front" || f.side == "back" || f.truss != tr.id { f.side = f.mount == "stand" ? "top" : "under" }
                }
                Self.place(&f, on: tr, at: u, width: doc.width)
                doc.fixtures[i] = f
                if !group.isEmpty {  // the others come along, in a row on the same truss
                    let ids = rowOrder([id] + group, from: g.before)
                    Self.arrange(&doc, ids, on: tr, at: groupCentre(ids, lead: id, leadU: u), side: f.side, width: housingWidth)
                }
            } else {
                if snapOn { target.x = (target.x / grid).rounded() * grid; target.y = (target.y / grid).rounded() * grid }
                let delta = SIMD2(target.x - g.start.x, target.y - g.start.y)
                if f.truss != nil { f.truss = nil; f.trussPos = nil; f.side = nil; f.mountRoll = nil; f.mount = "floor"; f.zM = 0.25 }
                f.x = target.x / doc.width
                f.yM = target.y
                doc.fixtures[i] = f
                for other in group {  // the others move by as much, onto the floor
                    guard let j = doc.fixtures.firstIndex(where: { $0.id == other }),
                          let was = g.before.fixtures.first(where: { $0.id == other }) else { continue }
                    var o2 = doc.fixtures[j]
                    let p = was.position(width: doc.width)
                    o2.waiting = false
                    o2.truss = nil; o2.trussPos = nil; o2.side = nil; o2.mountRoll = nil; o2.mount = "floor"; o2.zM = 0.25
                    o2.x = (p.x + delta.x) / doc.width
                    o2.yM = (was.waiting ? f.yM : p.y + delta.y)
                    doc.fixtures[j] = o2
                }
            }
        }
        refresh()
    }

    /// How much of a truss a fixture takes up: its housing's width (a bar's length).
    private func housingWidth(_ f: PlacedFixture) -> Double { definition(f.key)?.size.x ?? 0.4 }

    /// The order of a group in a row: as they were, left to right.
    private func rowOrder(_ ids: [String], from before: RigDocument) -> [String] {
        ids.sorted { a, b in
            let pa = before.fixtures.first { $0.id == a }?.x ?? 0, pb = before.fixtures.first { $0.id == b }?.x ?? 0
            return pa < pb
        }
    }

    /// Where a group's row is centred so that the leading fixture stays under the pointer.
    private func groupCentre(_ ids: [String], lead: String, leadU: Double) -> Double {
        let k = Double(ids.firstIndex(of: lead) ?? 0), n = Double(ids.count)
        return leadU - (k - (n - 1) / 2) * Self.spacing
    }

    func endDrag() {
        if let st = stretch {
            stretch = nil
            if let t = doc.trusses.first(where: { $0.id == st.id }), t.lengthM < Self.buildGrid {  // a click, no drag
                doc.trusses.removeAll { $0.id == st.id }
                if st.new { selection = nil }
            }
            if doc != st.before { registerUndo(st.new ? "Draw Truss" : "Stretch Truss", st.before) }
            refresh()
            return
        }
        if let r = raise {
            raise = nil
            if doc != r.before { registerUndo("Change Tower Height", r.before) }
            return
        }
        guard let g = drag else { return }
        drag = nil
        if doc != g.before {
            registerUndo(g.sel.isFixture ? (group.isEmpty ? "Move Fixture" : "Move Fixtures") : g.sel.isZone ? "Move Zone" : "Move Truss",
                         g.before)
        }
    }

    func clickedEmpty() {
        if selection != nil || !group.isEmpty { selection = nil; group = []; refresh() }
    }

    // MARK: - dropping fixtures from the inspector

    static func payload(_ ids: [String]) -> String { payloadPrefix + ids.joined(separator: ",") }

    private static func ids(from payload: String) -> [String]? {
        guard payload.hasPrefix(payloadPrefix) else { return nil }
        let ids = payload.dropFirst(payloadPrefix.count).split(separator: ",").map(String.init)
        return ids.isEmpty ? nil : ids
    }

    func dropHover(origin: SIMD3<Float>, dir: SIMD3<Float>) {
        let t = truss(near: s(origin), s(dir), radius: 0.8)?.0.id
        if t != dropTarget { dropTarget = t; refresh() }
    }

    func dropEnded() {
        if dropTarget != nil { dropTarget = nil; refresh() }
    }

    /// Fixtures dropped on the stage: in a row on the truss under the pointer, else on the floor there.
    func drop(_ payload: String, origin: SIMD3<Float>, dir: SIMD3<Float>) -> Bool {
        defer { dropEnded() }
        guard let ids = Self.ids(from: payload)?.filter({ id in doc.fixtures.contains { $0.id == id } }), !ids.isEmpty else { return false }
        let o = s(origin), d = s(dir)
        if let (t, u) = truss(near: o, d, radius: 0.8) {
            change(ids.count == 1 ? "Mount Fixture" : "Mount \(ids.count) Fixtures") { doc in
                Self.arrange(&doc, ids, on: t, at: u, side: nil, width: housingWidth)
                Self.lineUpWaiting(&doc)
            }
        } else {
            guard d.z < -1e-4 else { return false }
            let hit = o + d * (-o.z / d.z)
            change(ids.count == 1 ? "Place Fixture" : "Place \(ids.count) Fixtures") { doc in
                Self.lineUp(&doc, ids, at: SIMD2(hit.x, hit.y))
                Self.lineUpWaiting(&doc)
            }
        }
        select(fixtures: ids)
        return true
    }

    func key(_ e: NSEvent) -> Bool {
        let shift = e.modifierFlags.contains(.shift)
        let step = shift ? 0.5 : 0.1
        switch e.keyCode {
        case 51, 117: deleteSelection(); return selection == nil  // ⌫ / ⌦
        case 123 where !e.modifierFlags.contains(.option): nudge(-step, 0); return true  // ←
        case 124: nudge(step, 0); return true                        // →
        case 125 where !e.modifierFlags.contains(.option):  // ↓: round the truss back, or towards the audience
            if !rollAround(-1) { nudge(0, step) }
            return true
        case 126 where !e.modifierFlags.contains(.option):  // ↑: round the truss, or towards the back
            if !rollAround(1) { nudge(0, -step) }
            return true
        default: break
        }
        if e.modifierFlags.contains(.command), e.charactersIgnoringModifiers == "a" {  // ⌘A: every fixture
            select(fixtures: doc.fixtures.map(\.id))
            return true
        }
        if e.modifierFlags.contains(.option), e.keyCode == 126 || e.keyCode == 125, case .truss(let id) = selection {
            let up = e.keyCode == 126 ? 0.25 : -0.25  // ⌥↑ / ⌥↓: raise or lower the truss
            updateTruss(id, up > 0 ? "Raise Truss" : "Lower Truss") { t in
                if t.vertical { t.lengthM = max(1, t.lengthM + up); t.zM = t.lengthM / 2 } else { t.zM = max(0.5, t.zM + up) }
            }
            return true
        }
        switch e.charactersIgnoringModifiers?.lowercased() {
        case "r": rotateSelection(by: shift ? 90 : 15); return true
        case "t": tool = .truss; return true
        case "\u{1b}":
            if tool != .select { tool = .select } else { clickedEmpty() }
            return true
        default: return false
        }
    }
}

extension EditorSelection {
    var isFixture: Bool { if case .fixture = self { true } else { false } }
    var isZone: Bool { if case .zone = self { true } else { false } }
}
