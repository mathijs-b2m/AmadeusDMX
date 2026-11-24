// The DMX trace's follower: the switch is the engine's flag file, and the lines are the file's end as it grows.
import Foundation
import Testing

@testable import AmadeusKit

@MainActor
@Test func theTraceFollowsTheFileAndItsSwitch() throws {
    let data = FileManager.default.temporaryDirectory.appendingPathComponent("dmx-trace-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: data) }
    let trace = DMXTrace(data: data)
    #expect(!trace.isOn)
    trace.set(true)
    #expect(trace.isOn && FileManager.default.fileExists(atPath: trace.flag.path))
    trace.poll()  // no file yet
    #expect(trace.lines.isEmpty)

    func write(_ text: String) throws {
        let h = try FileHandle(forWritingTo: trace.log)
        try h.seekToEnd()
        try h.write(contentsOf: Data(text.utf8))
        try h.close()
    }
    try Data("# 14:03:07.412  trace on\n14:03:07.412  U1.017  fx1  pan  · → 131\n14:03:07.43".utf8).write(to: trace.log)
    trace.poll()
    #expect(trace.lines.map(\.text) == ["# 14:03:07.412  trace on", "14:03:07.412  U1.017  fx1  pan  · → 131"])
    #expect(trace.lines[0].isNote && !trace.lines[1].isNote)
    try write("7  U1.021  fx1  dimmer  0 → 255\n")  // the half line is finished
    trace.poll()
    #expect(trace.lines.last?.text == "14:03:07.437  U1.021  fx1  dimmer  0 → 255" && trace.lines.count == 3)
    trace.poll(read: false)
    #expect(trace.lines.count == 3)

    try Data("14:04:00.000  U1.001  -  -  1 → 2\n".utf8).write(to: trace.log)  // started over, shorter
    trace.poll()
    #expect(trace.lines.last?.text == "14:04:00.000  U1.001  -  -  1 → 2")

    trace.clear()
    #expect(trace.lines.isEmpty)
    trace.set(false)
    #expect(!trace.isOn)
}
