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
