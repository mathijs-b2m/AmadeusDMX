// The check after hanging's fixes on a set on a rig: two fixtures trading places, a head calibrated.
import Foundation
import Testing

@testable import AmadeusKit

private func document() throws -> RigDocument {
    let json = #"""
    {"stage": {"width_m": 8}, "trusses": [{"id": "front", "type": "quatro", "length_m": 6, "x_m": 4, "y_m": -1, "z_m": 4}],
     "fixtures": [
      {"id": "a", "fixture": "claypaky/sharpy", "mode": "Standard", "universe": 1, "address": 1, "pan_home_deg": 270,
       "truss": "front", "truss_pos_m": -2, "truss_side": "under", "mount": "hang", "x": 0.25, "y_m": -1, "z_m": 3.58},
      {"id": "b", "fixture": "beamz/fuze75b-beam", "mode": "12ch", "universe": 2, "address": 21, "group": "left",
       "truss": "front", "truss_pos_m": 1.5, "truss_side": "top", "mount": "stand", "x": 0.69, "y_m": -1, "z_m": 4.42,
       "rot_deg": 30}]}
    """#
    return try RigDocument(rig: "r", set: "s", data: Data(json.utf8))
}

@Test func swappedFixturesTradePlacesButKeepTheirPatch() throws {
    var d = try document()
    d.swapPlacements("a", "b")
    let a = try #require(d.fixtures.first { $0.id == "a" }), b = try #require(d.fixtures.first { $0.id == "b" })
    #expect(a.trussPos == 1.5 && a.side == "top" && a.mount == "stand" && a.rotDeg == 30 && a.x == 0.69)
    #expect(b.trussPos == -2 && b.side == "under" && b.mount == "hang" && b.rotDeg == 0)
    #expect(a.universe == 1 && a.address == 1 && a.key == "claypaky/sharpy" && b.address == 21)
    let out = try JSONSerialization.jsonObject(with: d.json()) as? [String: Any]
    let fx = (out?["fixtures"] as? [[String: Any]]) ?? []
    let ra = try #require(fx.first { $0["id"] as? String == "a" }), rb = try #require(fx.first { $0["id"] as? String == "b" })
    #expect(ra["group"] as? String == "left" && rb["group"] == nil)  // placement fields the editor doesn't model too
    #expect(ra["pan_home_deg"] as? Double == 270 && rb["pan_home_deg"] == nil)  // calibration stays with the fixture
}

@Test func aCalibratedHeadIsSavedWithItsFix() throws {
    var d = try document()
    d.calibrate("a", ["pan_invert": .bool(true), "pan_home_deg": .number(90)])
    let out = try JSONSerialization.jsonObject(with: d.json()) as? [String: Any]
    let a = try #require(((out?["fixtures"] as? [[String: Any]]) ?? []).first { $0["id"] as? String == "a" })
    #expect(a["pan_invert"] as? Bool == true && a["pan_home_deg"] as? Double == 90)
}

@Test func headsGroupedByHandAreSavedAndCanGoBackToAutomatic() throws {
    var d = try document()
    d.setGroup(["a", "b"], "  floor left ")
    #expect(d.group("a") == "floor left" && d.group("b") == "floor left" && d.groupNames == ["floor left"])
    d.setGroup(["b"], "")
    let saved = try RigDocument(rig: "r", set: "s", data: d.json())
    #expect(saved.group("a") == "floor left" && saved.group("b") == nil)
}

@Test func theHallIsTwoMetresEitherSideUnlessTheRigSaysHowWide() throws {
    var st = try JSONDecoder().decode(Stage.self, from: Data(#"{"width_m": 4}"#.utf8))
    #expect(st.roomWidth == 8 && Room(stage: st, fixtures: []).side == 2)
    st.roomWidthM = 20
    let back = try JSONDecoder().decode(Stage.self, from: JSONEncoder().encode(st))
    #expect(back.roomWidthM == 20 && Room(stage: back, fixtures: []).side == 8)
    st.roomWidthM = 2  // never narrower than the stage
    #expect(st.roomWidth == 4 && Room(stage: st, fixtures: []).side == 0)
}
