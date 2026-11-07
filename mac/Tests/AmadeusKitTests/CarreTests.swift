// A carré (a rectangle of truss on four legs) goes round the same way as amadeus/rig/trusses.py has it.
import Foundation
import Testing
import simd

@testable import AmadeusKit

@Test func aCarreDecodesAndGoesRoundFromItsFrontMiddle() throws {
    let json = #"{"id": "c", "type": "quatro", "shape": "carre", "width_m": 4, "depth_m": 3, "x_m": 4, "y_m": -1, "z_m": 3}"#
    let t = try JSONDecoder().decode(Truss.self, from: Data(json.utf8))
    #expect(t.isCarre && t.isLoop && t.isClosed && !t.isRing && !t.isStand)
    #expect(t.lengthM == 14)
    #expect(t.carreCorners == [SIMD2(6, 0.5), SIMD2(6, -2.5), SIMD2(2, -2.5), SIMD2(2, 0.5)])
    #expect(t.point(0) == SIMD3(4, 0.5, 3))  // the middle of the front side
    #expect(t.point(3.5) == SIMD3(6, -1, 3) && t.directionDeg(3.5) == -90)  // the +x side, going upstage
    #expect(t.point(-5) == SIMD3(2, -2.5, 3) && t.directionDeg(-4) == 90)  // the -x side, coming back
    #expect(t.carreClear(2.0) == 2.25 && t.carreClear(1.9) == 1.75)  // off the corner, on its own side
    #expect(t.wrapped(7.5) == -6.5)  // no ends
    let p = t.project(SIMD2(6.3, -1.2))
    #expect(abs(p.u - 3.7) < 1e-9 && abs(p.distance - 0.3) < 1e-9)
    #expect(t.pieces().count == 4)
}

@Test func aTurnedCarreTurnsItsFrame() {
    let t = Truss.carre(id: "c", width: 4, depth: 2, xM: 0, yM: 0, zM: 3, rotDeg: 90)
    #expect(simd_length(t.carreCorners[0] - SIMD2(-1, 2)) < 1e-9)
    #expect(t.directionDeg(0) == 90)
}

@Test func aStandCanCarryDecoTruss() throws {
    let json = #"{"id": "b", "type": "bridge", "bar": "deco", "length_m": 3, "x_m": 2, "y_m": -1.5, "z_m": 3}"#
    let t = try JSONDecoder().decode(Truss.self, from: Data(json.utf8))
    #expect(t.isDeco && t.isStand && t.isTube)
    let again = try JSONDecoder().decode(Truss.self, from: JSONEncoder().encode(t))
    #expect(again.bar == "deco")
}
