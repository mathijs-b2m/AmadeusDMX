// The DMX mapper's check, channel by channel: what the others hold while one sweeps, and what an answer makes a
// channel. The description is the engine's (amadeus/library/mapper.py describe) for a fixture made from a layout.
import Foundation
import Testing

@testable import AmadeusKit

private func mapping() throws -> FixtureMapping {
    let json = #"""
    {"key":"chegit/spot","name":"Chegit Spot","mode":"9ch","kind":"moving_head","kinds":{"par":"Par / wash / effect","moving_head":"Moving head"},
     "roles":[{"role":"dimmer","label":"Dimmer","group":"Intensity","cell":true,"light":true,"check":255},
              {"role":"color_wheel","label":"Colour wheel","group":"Colour","cell":false,"light":false,"check":0},
              {"role":"pan","label":"Pan","group":"Position","cell":false,"light":false,"check":128},
              {"role":"tilt","label":"Tilt","group":"Position","cell":false,"light":false,"check":128}],
     "channels":[{"n":1,"attr":"pan","role":"pan","cell":0,"value":0,"name":"Pan","ranges":[]},
                 {"n":2,"attr":"tilt","role":"tilt","cell":0,"value":0,"name":"Tilt","ranges":[]},
                 {"n":3,"attr":"color_wheel","role":"color_wheel","cell":0,"value":0,"name":"Colour wheel","ranges":[[0,9,"open / white"]]},
                 {"n":4,"attr":"gobo","role":"hold","cell":0,"value":5,"name":"Gobo","ranges":[]},
                 {"n":5,"attr":"dimmer","role":"dimmer","cell":0,"value":0,"name":"Dimmer","ranges":[]}],
     "plays":true,"mapped":false,"refusal":"","made":true,"checked":false,
     "check":[{"answer":"Turns left and right","role":"pan"},{"answer":"Tilts up and down","role":"tilt"},
              {"answer":"Gobos change","role":"hold","attr":"gobo","value":0},{"answer":"Nothing I can see","role":"hold","value":0}],
     "wheel":[{"name":"open","from":0,"to":15,"rgb":[1.0,1.0,1.0]},{"name":"red","from":16,"to":31,"rgb":[1.0,0.0,0.0]}]}
    """#
    return try JSONDecoder().decode(FixtureMapping.self, from: Data(json.utf8))
}

@Test func theOthersKeepTheLightOnWhileOneSweeps() throws {
    let m = try mapping()
    #expect(m.made && !m.checked && m.wheel.count == 2)
    #expect(m.checkValues(probe: 2, value: 77) == [128, 128, 77, 5, 255])  // head centred, gobo held, dimmer up
    #expect(m.lightChannels == [4])
}

@Test func anAnswerMakesTheChannel() throws {
    var m = try mapping()
    m.answer(m.check[1], for: 0)  // channel 1 tilts: the manual had pan and tilt swapped
    #expect(m.channels[0].role == "tilt")
    m.answer(m.check[2], for: 2)  // channel 3 is the gobo wheel
    #expect(m.channels[2].role == "hold" && m.channels[2].attr == "gobo" && m.channels[2].value == 0)
    m.answer(m.check[3], for: 3)  // channel 4 does nothing: not the gobo any more
    #expect(m.channels[3].role == "hold" && m.channels[3].attr == "channel_4")
}

@Test func anOlderEngineWithoutTheCheckStillDecodes() throws {
    let json = #"""
    {"key":"k","name":"n","mode":"m","kind":"par","kinds":{},"roles":[{"role":"dimmer","label":"Dimmer","group":"Intensity","cell":true}],
     "channels":[],"plays":false,"mapped":false,"refusal":""}
    """#
    let m = try JSONDecoder().decode(FixtureMapping.self, from: Data(json.utf8))
    #expect(!m.made && m.checked && m.check.isEmpty && m.roles[0].check == nil)
}
