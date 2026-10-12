// Amadeus Link's djay Pro and Mixxx readers against the engine's own (amadeus/show/sources/djay.py and
// mixxx.py): the expected values are what the Python code gives for the same input.
import Foundation
import Testing

@testable import AmadeusLink

private func near(_ a: Double, _ b: Double, _ eps: Double = 1e-9) -> Bool { abs(a - b) < eps }

@Test func playheadFollowsWholeSecondTicks() {
    let h = Playhead()
    h.setPlay(true, 0)
    h.seen(10, 0)
    #expect(near(h.at(0), 10.5) && near(h.at(0.5), 11.0))  // the first label: ± half a second
    h.seen(11, 0.55)
    #expect(near(h.at(0.55), 11.0) && near(h.at(1.0), 11.45))  // a tick: exact, at most 150 ms late
    h.seen(12, 1.53)
    #expect(near(h.at(1.53), 12.0) && near(h.at(2.0), 12.47))  // the least late tick wins
    h.setSpeed(1.05, 2.0)
    #expect(near(h.at(2.0), 12.47) && near(h.at(3.0), 13.52))
    h.seen(40, 3.1)
    #expect(near(h.at(3.1), 40.5) && near(h.at(3.6), 41.025))  // a jump: half a second uncertain again
    h.setPlay(false, 4.0)
    #expect(near(h.at(4.0), 41.445) && near(h.at(9.0), 41.445))  // paused: stands still
}

@Test func djayLabels() {
    #expect(["01:07", "1:02:03", "-0:05", "x", "7"].map(Djay.clock) == [67, 3723, 5, nil, nil])
    #expect(Djay.percent("73%") == 0.73 && Djay.percent(" 100 ") == 1.0 && Djay.percent("x") == nil)
}

@Test func djayLibraryRecordStrings() {
    var blob = Data("junk\u{8}file:///Users/x/Music/A%20B.mp3\u{0}\u{8}Song\u{0}\u{8}title\u{0}\u{8}Art\u{0}\u{8}artist\u{0}\u{8}".utf8)
    blob.append(Data(repeating: UInt8(ascii: "z"), count: 1001))
    blob.append(Data("\u{0}tail".utf8))
    #expect(DjayLibrary.strings(blob) == ["file:///Users/x/Music/A%20B.mp3", "Song", "title", "Art", "artist"])
}

@Test func titleWords() {
    #expect(Resolver.words("Café del Mar – Energy 52 (Original_Mix)") == ["cafe", "del", "mar", "energy", "52", "original", "mix"])
}

@Test func mixxxDeckMessage() throws {
    let msg: [UInt8] = [240, 125, 68, 76, 1, 1, 2, 15, 4, 0, 4, 12, 51, 0, 8, 74, 81, 0, 2, 88, 68, 64, 62, 71, 104, 0, 7, 92,
                        36, 102, 50, 0, 77, 247]
    let m = try #require(Mixxx.decode(msg))
    #expect(m["deck"] == 2 && m["play"] == 1 && m["loop"] == 1 && m["orientation"] == 1)
    #expect(near(m["pos"]!, 67.123) && m["samples"] == 18_000_000 && m["rate"] == 44100)
    #expect(near(m["ratio"]!, 1.025) && near(m["bpm"]!, 126.5) && near(m["vol"]!, 0.7999755844472929))
}

@Test func mixxxCrossfader() throws {
    let m = try #require(Mixxx.decode([240, 125, 68, 76, 1, 2, 32, 0, 247]))
    #expect(near(m["xfader"]!, -0.49996948055911616))
    #expect(near(Mixxx.xfadeGain(0.6, 0), 0.4) && Mixxx.xfadeGain(0.6, 2) == 1 && Mixxx.xfadeGain(-0.3, 0) == 1)
    #expect(Mixxx.decode([1, 2, 3]) == nil)
}

@Test func packetLeavesOutDecksWithoutAFile() throws {
    let decks = [DeckReading(deck: 1, file: "/a.mp3", pos: 10, length: 200, play: true, bpm: 125, bpm0: 125, vol: 1, received: 5, sync: true),
                 DeckReading(deck: 2, file: "", pos: 0, length: 0, play: false, bpm: 0, bpm0: 0, vol: 0, received: 5, title: "Spotify")]
    let data = try #require(Packet.make(app: "djay Pro", decks: decks, now: 5.5, start: 5))
    let o = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    let list = try #require(o["decks"] as? [[String: Any]])
    #expect(o["app"] as? String == "djay Pro" && o["t"] as? Int == 500 && list.count == 1)
    #expect(list[0]["pos"] as? Double == 10.5 && list[0]["sync"] as? Int == 1)
}
