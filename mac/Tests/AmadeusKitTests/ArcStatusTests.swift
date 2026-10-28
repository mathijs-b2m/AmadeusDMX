// The show arc's status as the engine sends it (a frame from amadeus/show/arc.py) decodes in full.
import Foundation
import Testing

@testable import AmadeusKit

@Test func arcStatusDecodesFromAnEngineFrame() throws {
    let json = #"""
    {"type": "frame", "lite": true, "t": 0, "phrase": 0, "arc": {"on": true, "length": 14400, "elapsed": 10.0,
     "stage": "warmup", "stages": [["warmup", "Dinner & Drinks"], ["build", "Opening the Floor"], ["peak", "Party"],
     ["deep", "Slow Dances"], ["finale", "Last Dances"], ["outro", "Goodnight"]], "event": "wedding",
     "events": [["club", "DJ Set / Club Night"], ["wedding", "Wedding"]], "locked": false, "heat": 0.628,
     "trend": 0.0, "bpm": 124.0, "base_bpm": 124.0, "values": {"groups": 0.4, "specials": 0.0, "response": 0.315,
     "smoke": 0.2, "colour": 0.2, "intensity": 0.565, "flashes": 0.0}, "manual": ["smoke"], "groups": 8, "playing": 8}}
    """#
    guard case .frame(let f) = try #require(FeedMessage.decode(Data(json.utf8))) else { Issue.record("not a frame"); return }
    let arc = try #require(f.arc)
    #expect(arc.stageName == "Dinner & Drinks")
    #expect(arc.remaining == 14390)
    #expect(arc.baseBpm == 124 && arc.manual == ["smoke"] && arc.values["intensity"] == 0.565)
    #expect(f.lite && f.fx.isEmpty)
}

@Test func outdoorStageRoundTrips() throws {
    let st = try JSONDecoder().decode(Stage.self, from: Data(#"{"width_m": 12, "outdoor": true}"#.utf8))
    #expect(st.outdoor)
    let back = try JSONSerialization.jsonObject(with: JSONEncoder().encode(st)) as? [String: Any]
    #expect(back?["outdoor"] as? Bool == true)
    let room = Room(stage: st, fixtures: [])
    #expect(room.hit([0, 0, 2], [0, 0, 1]).surface == .air)  // straight up: no ceiling
}

@Test func aHeadsRingColourDecodesPerElement() throws {
    let json = #"{"type": "frame", "t": 1, "phrase": 0, "fx": [[1, 1, 0, 0, 0, 0.5, 0.5], [0, 0, 0, 0, 0, 0.5, 0.5]], "ring": [[1, 0, 0], null]}"#
    guard case .frame(let f) = try #require(FeedMessage.decode(Data(json.utf8))) else { Issue.record("not a frame"); return }
    #expect(f.ring.count == 2 && f.ring[0] == SIMD3(1, 0, 0) && f.ring[1] == nil)
    guard case .frame(let older) = try #require(FeedMessage.decode(Data(#"{"type": "frame", "t": 1, "phrase": 0}"#.utf8))) else { return }
    #expect(older.ring.isEmpty)  // an engine without rings
}
