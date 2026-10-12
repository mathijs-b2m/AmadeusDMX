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

// djay's library records, built as tests/test_streamed.py builds them
private func s8(_ text: String) -> [UInt8] { [0x08] + Array(text.utf8) + [0x00] }

private func f32(_ data: [UInt8], _ value: Float) -> [UInt8] {
    var d = data + [0x13]
    d += [UInt8](repeating: 0, count: (4 - d.count % 4) % 4)
    return d + withUnsafeBytes(of: value.bitPattern.littleEndian) { Array($0) }
}

private func location(_ title: String, _ artist: String, _ uri: String, _ isrc: String, _ length: Float) -> Data {
    var d: [UInt8] = Array("TSAF".utf8) + [3, 0, 3, 0] + s8("ADCMediaItemLocation") + s8("ab12") + s8("uuid") + [5, 2]
    d += s8(title) + s8("title") + s8(artist) + s8("artist")
    d = f32(d, length) + s8("duration")
    return Data(d + s8(isrc) + s8("isrc") + s8(uri) + s8("sourceURIs"))
}

@Test func djayStreamedRecord() throws {
    let s = try #require(DjayStreams.stream(location("Toxic", "Britney Spears", "spotify:track:6I9VzX", "USJI10301102", 198.8)))
    #expect(s.service == "spotify" && s.id == "6I9VzX" && s.isrc == "USJI10301102")
    #expect(s.title == "Toxic" && s.artist == "Britney Spears" && abs(s.length - 198.8) < 1e-3)
    #expect(DjayStreams.stream(Data(s8("file:///x.mp3") + s8("Local") + s8("title"))) == nil)  // a file: not streamed
}

@Test func djayMissingArtistIsNotAKey() {
    let f = DjayStreams.fields(Data(s8("Zebra") + s8("title") + s8("artist") + s8("spotify:track:x") + s8("sourceURIs")))
    #expect(f.text["title"] == "Zebra" && f.text["artist"] == nil && f.uris == ["spotify:track:x"])
}

@Test func packetCarriesAStreamedDeck() throws {
    let st = StreamedTrack(service: "spotify", id: "6I9", title: "Toxic", artist: "Britney Spears", isrc: "US1", length: 198.8)
    let d = DeckReading(deck: 2, file: "", pos: 30, length: 198.8, play: true, bpm: 143, bpm0: 143, vol: 1, received: 1,
                        title: "Toxic", artist: "Britney Spears", stream: st)
    let data = try #require(Packet.make(app: "djay Pro", decks: [d], now: 1, start: 0))
    let o = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    let deck = try #require((o["decks"] as? [[String: Any]])?.first)
    #expect(deck["file"] as? String == "" && deck["title"] as? String == "Toxic")
    #expect((deck["stream"] as? [String: String]) == ["service": "spotify", "id": "6I9", "isrc": "US1"])
}

private let vdjDatabase = """
<?xml version="1.0" encoding="UTF-8"?>
<VirtualDJ_Database Version="2025">
 <Song FilePath="netsearch://sp1fI4E7jeOiyfa3LmwNnD0o" Flag="256">
  <Tags Author="Paul Kalkbrenner" Title="DIE TROMPETEN VON BERLIN" Album="THE ESSENCE" Year="2025" />
  <Infos SongLength="330.022109" Bitrate="320" />
 </Song>
 <Song FilePath="netsearch://sp4eE4vEaakr3ZnSt1UNfOhz" Flag="256">
  <Tags Author="Emrod" Title="Tango" />
  <Infos SongLength="240.0" />
 </Song>
 <Song FilePath="/Music/local.mp3"><Tags Author="A" Title="Local" /><Infos SongLength="200.5" /></Song>
</VirtualDJ_Database>
"""

@Test func virtualDJDatabase() throws {
    let found = VirtualDJStreams.parse(Data(vdjDatabase.utf8))
    #expect(found.count == 2)
    let s = try #require(found["netsearch://sp1fI4E7jeOiyfa3LmwNnD0o"])
    #expect(s.service == "spotify" && s.id == "1fI4E7jeOiyfa3LmwNnD0o" && s.artist == "Paul Kalkbrenner")
    #expect(s.title == "DIE TROMPETEN VON BERLIN" && abs(s.length - 330.022109) < 1e-6)
    #expect(found["netsearch://sp4eE4vEaakr3ZnSt1UNfOhz"]?.length == 0)  // 240.0: VirtualDJ's guess, unknown
    #expect(VirtualDJStreams.netsearch("/Music/local.mp3") == nil)
}

@Test func virtualDJPacketNamesItsStreams() throws {
    let url = FileManager.default.temporaryDirectory.appending(path: "vdj-\(UUID().uuidString).xml")
    try Data(vdjDatabase.utf8).write(to: url)
    defer { try? FileManager.default.removeItem(at: url) }
    let packet = Data("""
    {"t":1,"master":2,"decks":[{"deck":1,"pos":0,"len":240,"play":0,"bpm":125,"bpm0":124,"vol":1,"file":"/Music/local.mp3"},\
    {"deck":2,"pos":34.4,"len":330,"play":1,"bpm":125.4,"bpm0":137.4,"vol":1,"file":"netsearch://sp1fI4E7jeOiyfa3LmwNnD0o"}]}
    """.utf8)
    let o = try #require(try JSONSerialization.jsonObject(with: VirtualDJStreams(path: url).enrich(packet)) as? [String: Any])
    let decks = try #require(o["decks"] as? [[String: Any]])
    #expect(decks[0]["file"] as? String == "/Music/local.mp3" && decks[0]["stream"] == nil)  // a file: as it was
    #expect(decks[1]["file"] as? String == "" && decks[1]["title"] as? String == "DIE TROMPETEN VON BERLIN")
    #expect(decks[1]["artist"] as? String == "Paul Kalkbrenner" && abs((decks[1]["len"] as? Double ?? 0) - 330.022109) < 1e-6)
    #expect((decks[1]["stream"] as? [String: String]) == ["service": "spotify", "id": "1fI4E7jeOiyfa3LmwNnD0o", "isrc": ""])
    let plain = Data(#"{"decks":[{"deck":1,"file":"/x.mp3"}]}"#.utf8)
    #expect(VirtualDJStreams(path: url).enrich(plain) == plain)  // nothing streams: untouched
}
