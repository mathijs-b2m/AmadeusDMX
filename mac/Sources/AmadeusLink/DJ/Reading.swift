// What Amadeus Link reads from a DJ software other than VirtualDJ (djay Pro, Mixxx) and how it passes it on:
// as the AmadeusLink plugin's packets, so the lighting computer can't tell them apart (the same format as
// amadeus/show/probe.py plugin_packet). VirtualDJ's own plugin sends these packets itself.
import Foundation

/// One deck as the DJ software reports it.
struct DeckReading {
    var deck: Int
    var file: String  // the track on this laptop ("" while unknown: not passed on)
    var pos: Double  // seconds, at `received`
    var length: Double
    var play: Bool
    var bpm: Double
    var bpm0: Double
    var vol: Double  // what reaches the master: channel fader × crossfader, 0..1
    var received: Double  // monotonic seconds
    var title = ""
    var artist = ""
    var id = ""
    var rate: Double = 0  // playback speed when the DJ software reports it
    var sync = false  // synced to Ableton Link: the lighting computer reads the beat from Link itself

    var speed: Double { rate > 0 ? rate : (bpm0 > 1 && bpm > 1 ? bpm / bpm0 : 1) }

    func now(_ t: Double) -> Double { play ? pos + (t - received) * speed : pos }
}

/// A DJ software Amadeus Link reads itself.
protocol DJReader: AnyObject {
    /// The DJ software's name, as the lighting computer shows it.
    var app: String { get }
    /// What the DJ should know or do ("needs the Accessibility permission", "start Mixxx after Link"), "" when fine.
    var note: String { get }
    /// The decks right now.
    func decks(at now: Double) -> [DeckReading]
    /// Every deck the DJ software shows, one line each, with why a deck isn't passed on (for Link's menu).
    func summary(at now: Double) -> String
    func stop()
}

extension DeckReading {
    /// "2: ▶ Artist – Title", and why it isn't passed on when it has no file here.
    var line: String {
        let what = title.isEmpty ? (file as NSString).lastPathComponent : (artist.isEmpty ? title : "\(artist) – \(title)")
        return "\(deck): \(play ? "▶" : "■") \(what.isEmpty ? "no track" : what)\(file.isEmpty && !title.isEmpty ? "  (no file on this laptop: not sent)" : "")"
    }
}

enum Packet {
    /// The decks as the AmadeusLink plugin sends them, positions brought to `now`. Decks without a file stay out:
    /// the lighting computer can only light a track it can fetch.
    static func make(app: String, decks: [DeckReading], now: Double, start: Double) -> Data? {
        let list: [[String: Any]] = decks.filter { !$0.file.isEmpty }.sorted { $0.deck < $1.deck }.map { d in
            var o: [String: Any] = [
                "deck": d.deck, "file": d.file, "pos": round4(d.now(now)), "len": d.length, "play": d.play ? 1 : 0,
                "bpm": d.bpm, "bpm0": d.bpm0, "vol": round4(d.vol),
            ]
            if !d.title.isEmpty { o["title"] = d.title }
            if !d.artist.isEmpty { o["artist"] = d.artist }
            if !d.id.isEmpty { o["id"] = d.id }
            if d.sync { o["sync"] = 1 }
            return o
        }
        let obj: [String: Any] = ["t": Int((now - start) * 1000), "app": app, "master": 0, "decks": list]
        return try? JSONSerialization.data(withJSONObject: obj)
    }

    private static func round4(_ x: Double) -> Double { (x * 10000).rounded() / 10000 }
}

func monotonic() -> Double { Double(DispatchTime.now().uptimeNanoseconds) / 1e9 }
