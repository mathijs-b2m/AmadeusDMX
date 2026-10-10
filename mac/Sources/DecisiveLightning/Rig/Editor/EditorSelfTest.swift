// `-editorSelfTest NAME`: runs the rig editor's picking, dragging, snapping, grouping, dropping, auto-mount, undo
// and save on the set NAME placed on the rig NAME (use copies: it saves!) and writes a report to
// $TMPDIR/editor-selftest.txt, then quits. For development.
import AppKit
import DecisiveKit
import Foundation
import simd

@MainActor
enum EditorSelfTest {
    static func runIfRequested(_ model: AppModel) {
        guard let name = UserDefaults.standard.string(forKey: "editorSelfTest"), let ws = model.workspace,
              let e = RigEditorModel(workspace: ws, rig: name, set: name) else { return }
        Task { await run(model, ws, e, name) }
    }

    private static func run(_ model: AppModel, _ ws: Workspace, _ e: RigEditorModel, _ name: String) async {
        var out: [String] = []
        let undo = UndoManager()
        undo.groupsByEvent = false
        undo.beginUndoGrouping()          // one open group for everything after the undo test
        e.undoManager = undo
        func log(_ s: String) { out.append(s) }
        func check(_ name: String, _ ok: Bool, _ detail: String = "") { log("\(ok ? "PASS" : "FAIL")  \(name)\(detail.isEmpty ? "" : "  (\(detail))")") }
        let down = SIMD3<Float>(0, 0, -1)
        func above(_ x: Double, _ y: Double) -> SIMD3<Float> { SIMD3(Float(x), Float(y), 30) }
        func fx(_ id: String) -> PlacedFixture { e.doc.fixtures.first { $0.id == id }! }
        func tr(_ id: String) -> Truss { e.doc.trusses.first { $0.id == id }! }
        let W = e.doc.width

        // 1. pick a truss between its fixtures
        let front = tr("front")
        undo.endUndoGrouping()
        undo.beginUndoGrouping()
        check("pick truss", e.pick(origin: above(front.xM, front.yM), dir: down, extend: false) && e.selection == .truss("front"))
        // 2. drag it 0.8 m back: its fixtures follow
        e.drag(origin: above(front.xM, front.yM - 0.8), dir: down, free: false)
        e.endDrag()
        undo.endUndoGrouping()
        check("truss moved (snapped to 25 cm)", abs(tr("front").yM - ((front.yM - 0.8) / 0.25).rounded() * 0.25) < 0.01, "y \(tr("front").yM)")
        check("fixtures follow", abs(fx("sharpy1").yM - tr("front").yM) < 0.01, "sharpy1 y \(fx("sharpy1").yM)")
        // 3. undo
        undo.undo()
        undo.beginUndoGrouping()
        check("undo", abs(tr("front").yM - front.yM) < 0.01 && abs(fx("sharpy1").yM - front.yM) < 0.01)
        // 4. pick a fixture under the truss (fixtures win)
        let s1 = fx("sharpy1").position(width: W)
        check("pick fixture under truss", e.pick(origin: above(s1.x, s1.y), dir: down, extend: false) && e.selection == .fixture("sharpy1"))
        // 5. slide along the truss, snapping to 25 cm
        e.drag(origin: above(s1.x + 1.37, s1.y + 0.1), dir: down, free: false)
        check("slide along truss", fx("sharpy1").truss == "front" && abs((fx("sharpy1").trussPos ?? 0) - (-4.5 + 1.25)) < 0.01,
              "pos \(fx("sharpy1").trussPos ?? .nan)")
        // 5b. drag across the truss: onto its front face, then its back face, then back under it
        let fr = tr("front")
        e.drag(origin: above(s1.x + 1.37, fr.yM + 0.5), dir: down, free: false)
        check("front face (90°)", fx("sharpy1").side == "front" && fx("sharpy1").mountRoll == 90 && abs(fx("sharpy1").yM - (fr.yM + 0.4)) < 0.01
              && abs(fx("sharpy1").zM - fr.zM) < 0.01 && simd_length(fx("sharpy1").up - SIMD3(0, 1, 0)) < 0.01,
              "side \(fx("sharpy1").side ?? "-") y \(fx("sharpy1").yM)")
        e.drag(origin: above(s1.x + 1.37, fr.yM - 0.5), dir: down, free: false)
        check("back face (270°)", fx("sharpy1").side == "back" && fx("sharpy1").mountRoll == 270 && abs(fx("sharpy1").yM - (fr.yM - 0.4)) < 0.01
              && simd_length(fx("sharpy1").up - SIMD3(0, -1, 0)) < 0.01)
        e.drag(origin: above(s1.x + 1.37, fr.yM + 0.05), dir: down, free: false)
        check("centre: under again (0°)", fx("sharpy1").side == "under" && fx("sharpy1").mountRoll == nil
              && abs(fx("sharpy1").zM - (fr.zM - 0.42)) < 0.01)
        // 6. drag far from any truss: drops to the floor
        e.drag(origin: above(s1.x + 4.5, s1.y + 4), dir: down, free: false)
        check("detach to floor", fx("sharpy1").truss == nil && fx("sharpy1").mount == "floor" && fx("sharpy1").zM < 0.5)
        e.endDrag()
        // 7. drag onto the back truss: hangs there
        let back = tr("back")
        let p = fx("sharpy1").position(width: W)
        _ = e.pick(origin: above(p.x, p.y), dir: down, extend: false)
        e.drag(origin: above(back.xM + 0.6, back.yM + 0.2), dir: down, free: false)
        e.endDrag()
        let f = fx("sharpy1")
        check("attach to back truss", f.truss == "back" && f.mount == "hang" && abs(f.zM - (back.zM - 0.42)) < 0.01,
              "truss \(f.truss ?? "-") z \(f.zM)")
        // 8. a new truss with two Katanas on it
        e.addTruss(length: 3)
        guard case .truss(let newID) = e.selection else { check("add truss", false); return finish(out) }
        check("add truss", e.doc.trusses.contains { $0.id == newID })
        e.addFixtures(key: "dts/katana", mode: "Extended", count: 2)
        let ks = e.doc.fixtures.filter { $0.truss == newID }
        check("add fixtures on truss", ks.count == 2 && ks.allSatisfy { $0.mount == "hang" },
              ks.map { "\($0.id)@\($0.universe).\($0.address)" }.joined(separator: " "))
        let used = e.doc.fixtures.map { ($0.universe, $0.address) }
        check("unique addresses", Set(used.map { "\($0.0).\($0.1)" }).count == used.count)
        // 9. rotate the new truss 90°: the Katanas turn with it (they now run front to back)
        let before = ks.map { $0.position(width: W) }
        e.selection = .truss(newID)
        e.rotateSelection(by: 90)
        let after = e.doc.fixtures.filter { $0.truss == newID }.map { $0.position(width: W) }
        check("bars turn with the truss", e.doc.fixtures.filter { $0.truss == newID }.allSatisfy { abs($0.rotDeg - 90) < 0.01 })
        check("fixtures follow rotation", abs(after[0].x - after[1].x) < 0.01 && abs(after[0].y - after[1].y) > 0.5,
              "before dx \(String(format: "%.2f", before[1].x - before[0].x)) after dy \(String(format: "%.2f", after[1].y - after[0].y))")
        // 9b. zones: one of each preset; pick one where nothing else is; drag it; trusses still win
        let zonesBefore = e.doc.zones.count
        for p in RigEditorModel.ZonePreset.allCases { e.addZone(p) }
        check("add zones", e.doc.zones.count == zonesBefore + RigEditorModel.ZonePreset.allCases.count,
              e.doc.zones.map { "\($0.kind)/\($0.shape)" }.joined(separator: " "))
        let floorZone = e.doc.zones.first { $0.name == "VIP corner" }!
        e.selection = nil
        let zc = floorZone.centerV
        check("pick zone", e.pick(origin: above(zc.x, zc.y), dir: down, extend: false) && e.selection == .zone(floorZone.id))
        e.drag(origin: above(zc.x - 1.3, zc.y + 0.6), dir: down, free: false)
        e.endDrag()
        let moved = e.doc.zones.first { $0.id == floorZone.id }!.centerV
        check("drag zone (snapped)", abs(moved.x - ((zc.x - 1.3) / 0.25).rounded() * 0.25) < 0.01 && abs(moved.z - zc.z) < 1e-6,
              String(format: "x %.2f y %.2f", moved.x, moved.y))
        let fb = tr("back")
        // a spot on the back truss with no fixture within reach
        let free = stride(from: -fb.lengthM / 2 + 0.3, to: fb.lengthM / 2 - 0.3, by: 0.1).first { u in
            let p = fb.point(u)
            return e.doc.fixtures.allSatisfy { simd_length(SIMD2($0.position(width: W).x, $0.position(width: W).y) - SIMD2(p.x, p.y)) > 1.0 }
        } ?? 0
        check("trusses win over zones", e.pick(origin: above(fb.point(free).x, fb.yM), dir: down, extend: false) && e.selection == .truss("back"),
              String(format: "at u %.1f", free))
        e.selection = .zone(floorZone.id)
        e.rotateSelection(by: 15)
        e.nudge(0.1, 0)
        let z2 = e.doc.zones.first { $0.id == floorZone.id }!
        check("rotate + nudge zone", abs(z2.rotDeg - 15) < 1e-6 && abs(z2.centerV.x - moved.x - 0.1) < 1e-6)
        let plane = e.doc.zones.first { $0.name == "No lasers below" }!
        let pc = plane.centerV
        check("plane hit maths", plane.hit(SIMD3(pc.x, pc.y, 6), SIMD3(0, 0, -1)).map { abs($0 - (6 - pc.z)) < 1e-6 } == true
              && plane.hit(SIMD3(pc.x, pc.y, 6), SIMD3(0, 0, 1)) == nil)
        // 10. unmount: back to waiting in front of the stage
        e.selection = .fixture("sharpy2")
        e.deleteSelection()
        check("unmount", fx("sharpy2").waiting && fx("sharpy2").truss == nil && abs(fx("sharpy2").yM + 0.3) < 0.01,
              "y \(fx("sharpy2").yM)")
        // 11. drop two fixtures from the inspector onto the back truss: a row, 60 cm apart
        let bt = tr("back")
        let two = ["sharpy2", "sharpy3"]
        check("drop a group on a truss", e.drop(RigEditorModel.payload(two), origin: above(bt.xM, bt.yM), dir: down))
        let a = fx("sharpy2"), b = fx("sharpy3")
        check("a row on that truss", a.truss == "back" && b.truss == "back" && !a.waiting
              && abs(abs((a.trussPos ?? 0) - (b.trussPos ?? 0)) - RigEditorModel.spacing) < 0.01,
              String(format: "%.2f / %.2f", a.trussPos ?? .nan, b.trussPos ?? .nan))
        // 12. ⇧-click two fixtures, drag one onto the front truss: the other comes along
        e.selection = nil
        let pa = fx("sharpy2").position(width: W), pb = fx("sharpy3").position(width: W)
        _ = e.pick(origin: above(pa.x, pa.y), dir: down, extend: false)
        e.endDrag()
        _ = e.pick(origin: above(pb.x, pb.y), dir: down, extend: true)
        check("⇧-click selects more", e.selectedFixtures == Set(two), e.selectedFixtures.sorted().joined(separator: ","))
        let ft = tr("front")
        e.drag(origin: above(ft.xM + 2.0, ft.yM), dir: down, free: false)
        e.endDrag()
        check("group drag onto a truss", fx("sharpy2").truss == "front" && fx("sharpy3").truss == "front",
              "\(fx("sharpy2").truss ?? "-") \(fx("sharpy3").truss ?? "-")")
        // 13. auto-mount what waits (through the engine)
        e.unmount(["sharpy2", "sharpy3", "sharpy4"])
        await e.autoMount(model)
        check("auto-mount", e.doc.waitingCount == 0 && fx("sharpy4").truss != nil,
              "waiting \(e.doc.waitingCount), sharpy4 on \(fx("sharpy4").truss ?? "-")")
        // 14. save (through the engine: the rig and the set files) and read back; a waiting fixture stays unmounted
        e.unmount(["sharpy4"])
        do {
            try await e.save(model)
            let back = ws.document(rig: name, set: name)!
            check("save + reload", back.trusses.count == e.doc.trusses.count && back.fixtures.count == e.doc.fixtures.count
                  && back.zones == e.doc.zones && back.fixtures.first { $0.id == "sharpy1" }?.truss == "back")
            check("waiting stays unmounted", back.fixtures.first { $0.id == "sharpy4" }?.waiting == true
                  && ws.mounted(rig: name, set: name).placed == back.fixtures.count - 1)
        } catch {
            check("save", false, error.localizedDescription)
        }
        finish(out)
    }

    private static func finish(_ out: [String]) {
        let url = FileManager.default.temporaryDirectory.appending(path: "editor-selftest.txt")
        try? out.joined(separator: "\n").write(to: url, atomically: true, encoding: .utf8)
        NSApp.terminate(nil)
    }
}
