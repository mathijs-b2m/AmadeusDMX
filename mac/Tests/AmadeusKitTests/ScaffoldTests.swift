import Foundation
import Testing
@testable import AmadeusKit

// amadeus/rig/trusses.py: tests/test_scaffold.py asks the engine the same.
@Suite struct ScaffoldTests {
    @Test func sharesItsSizeIntoBaysAndLifts() {
        let t = Truss.scaffold(id: "w", width: 16, height: 9, xM: 8, yM: -7)
        #expect(t.isScaffold && !t.isStand && !t.isLoop)
        #expect(t.scaffoldBays == 6 && t.scaffoldLifts == 9)
        #expect(t.liftHeight(3) == 3 && t.nearestLift(4.2) == 4 && t.nearestLift(0) == 1 && t.nearestLift(30) == 9)
    }

    @Test func aDjOnTheFloorStaysWithTheStage() throws {
        var st = Stage(widthM: 12)
        #expect(!st.djFloor)
        st.djFloor = true
        let back = try JSONDecoder().decode(Stage.self, from: JSONEncoder().encode(st))
        #expect(back.djFloor)
        #expect(try !JSONDecoder().decode(Stage.self, from: Data("{}".utf8)).djFloor)
    }

    @Test func itsHeadsPlayToTheAudience() {
        var t = Truss.scaffold(id: "w", width: 16, height: 9, xM: 8, yM: -7)
        #expect(t.lightAim == "audience")
        t.aim = "down"
        #expect(t.lightAim == "down")
    }

    @Test func ledgersAreOnItsFrontFrame() {
        let t = Truss.scaffold(id: "w", width: 16, height: 9, xM: 8, yM: -7)
        let l = t.ledger(4)
        #expect(l.yM == -6.5 && l.zM == 4 && l.isTube && !l.isScaffold)
        #expect(t.ledger(40).zM == 9)
        #expect(t.pieces().count == 9)
    }

    @Test func theWidestFacingTheAudienceCarriesTheScreen() {
        var side = Truss.scaffold(id: "s", width: 30, height: 9, xM: 0, yM: -3); side.rotDeg = 90
        let back = Truss.scaffold(id: "b", width: 16, height: 9, xM: 8, yM: -7)
        #expect(Truss.screenWall([side, back])?.id == "b")
        #expect(Truss.screenWall([side]) == nil)
    }
}

@Suite struct InsideTheRoomTests {
    private func stage(_ json: String) throws -> Stage { try JSONDecoder().decode(Stage.self, from: Data(json.utf8)) }

    @Test func aBackWallTheRigFixesStaysThere() throws {
        let st = try stage(#"{"width_m": 6, "ceiling_m": 3.4, "room_depth_m": 6, "room_width_m": 6, "room_back_m": 2.5}"#)
        let room = Room(stage: st, fixtures: [])
        #expect(room.back == -2.5 && room.backFixed)
        #expect(room.depth - room.back == 8.5 && room.width + 2 * room.side == 6)
        let back = try JSONDecoder().decode(Stage.self, from: JSONEncoder().encode(st))
        #expect(back.roomBackM == 2.5)
        #expect(!Room(stage: try stage("{}"), fixtures: []).backFixed)
    }

    @Test func theCameraBoxStaysOffTheWalls() throws {
        let st = try stage(#"{"width_m": 6, "ceiling_m": 3.4, "room_depth_m": 6, "room_width_m": 6, "room_back_m": 2.5}"#)
        let box = try #require(Room(stage: st, fixtures: []).cameraBox)
        #expect(box.clamp([-5, 20, 9]) == [0.25, 5.75, 3.15])
        #expect(box.clamp([3, 1, 2]) == [3, 1, 2])
        #expect(box.targets.lo.x == 0.75 && box.targets.hi.y == 5.25)
        #expect(abs(box.exit(from: [3, 1, 2], along: [0, 1, 0]) - 4.75) < 1e-4)
        #expect(abs(box.exit(from: [3, 1, 2], along: [0, 0, -1]) - 1.85) < 1e-4)
    }

    @Test func outdoorsThereIsNoRoomToStayIn() throws {
        #expect(Room(stage: try stage(#"{"outdoor": true}"#), fixtures: []).cameraBox == nil)
    }
}
