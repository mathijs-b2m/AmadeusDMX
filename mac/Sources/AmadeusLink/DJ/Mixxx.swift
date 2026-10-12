// Mixxx on the DJ laptop: its official controller scripting, through a MIDI device of our own (a port of
// amadeus/show/sources/mixxx.py). Amadeus Link creates the virtual MIDI device "Amadeus DMX"; in Mixxx
// (Preferences › Controllers) it gets the "Amadeus DMX" mapping (mixxx/ in the repository, carried by Link and
// copied into Mixxx's controllers folder), whose script sends every deck's state 50 times a second as SysEx.
// A script can't read a track's title or file: the track is found in Mixxx's library by its length in samples.
//
// Mixxx looks for MIDI devices only when it starts: start Mixxx after Amadeus Link.
import CoreMIDI
import Foundation
import SQLite3

final class Mixxx: DJReader, @unchecked Sendable {
    let app = "Mixxx"
    static let name = "Amadeus DMX"
    static let header: [UInt8] = [0xF0, 0x7D, 0x44, 0x4C, 0x01]
    static let loadingS = 0.3  // while Mixxx loads a track its position is briefly meaningless

    /// Where Mixxx keeps its settings: sandboxed (the macOS download), else not sandboxed.
    static var settings: URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return [home.appending(path: "Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx"),
                home.appending(path: "Library/Application Support/Mixxx")]
            .first { FileManager.default.fileExists(atPath: $0.path) }
    }

    private let lock = NSLock()
    private var client = MIDIClientRef()
    private var input = MIDIEndpointRef()
    private var output = MIDIEndpointRef()
    private var sysex: [UInt8] = []
    private var state: [Int: [String: Double]] = [:]
    private var xfader = 0.0
    private var midiError = ""
    private let library: MixxxLibrary
    private let resolver = Resolver()

    init() {
        library = MixxxLibrary(path: Self.settings?.appending(path: "mixxxdb.sqlite"))
        Self.installMapping()
        var status = MIDIClientCreateWithBlock(Self.name as CFString, &client, nil)
        // Mixxx pairs a device's input and output by name: one of each
        if status == noErr { status = MIDISourceCreateWithProtocol(client, Self.name as CFString, ._1_0, &output) }
        if status == noErr {
            status = MIDIDestinationCreateWithProtocol(client, Self.name as CFString, ._1_0, &input) { [weak self] list, _ in
                self?.receive(list)
            }
        }
        if status != noErr { midiError = "Can't create the MIDI device \"\(Self.name)\" (error \(status))." }
    }

    var note: String {
        lock.lock(); defer { lock.unlock() }
        if !midiError.isEmpty { return midiError }
        if state.isEmpty {
            return "In Mixxx: Preferences › Controllers › \(Self.name), mapping \"\(Self.name)\", enabled. Start Mixxx after Amadeus Link."
        }
        return ""
    }

    func stop() {
        if input != 0 { MIDIEndpointDispose(input) }
        if output != 0 { MIDIEndpointDispose(output) }
        if client != 0 { MIDIClientDispose(client) }
        input = 0; output = 0; client = 0
    }

    /// Copies our mapping into Mixxx's controllers folder (Mixxx reads it at its next start).
    static func installMapping() {
        guard let settings, let ours = Bundle.main.url(forResource: "mixxx", withExtension: nil) else { return }
        let dest = settings.appending(path: "controllers")
        let fm = FileManager.default
        try? fm.createDirectory(at: dest, withIntermediateDirectories: true)
        for f in (try? fm.contentsOfDirectory(at: ours, includingPropertiesForKeys: nil)) ?? []
        where ["xml", "js"].contains(f.pathExtension) {
            let to = dest.appending(path: f.lastPathComponent)
            if (try? Data(contentsOf: to)) != (try? Data(contentsOf: f)) {
                try? fm.removeItem(at: to)
                try? fm.copyItem(at: f, to: to)
            }
        }
    }

    // MARK: MIDI in (MIDI 1.0 SysEx, carried as 7-bit SysEx in universal MIDI packets)

    private func receive(_ list: UnsafePointer<MIDIEventList>) {
        for packet in list.unsafeSequence() {
            let n = Int(packet.pointee.wordCount)
            var p = packet.pointee
            withUnsafeBytes(of: &p.words) { raw in
                let words = Array(raw.bindMemory(to: UInt32.self).prefix(n))
                var i = 0
                while i < words.count {
                    let w = words[i]
                    guard w >> 28 == 0x3, i + 1 < words.count else { i += 1; continue }  // a SysEx7 packet: two words
                    let status = (w >> 20) & 0xF, count = Int((w >> 16) & 0xF)
                    let w2 = words[i + 1]
                    var bytes: [UInt8] = [UInt8((w >> 8) & 0x7F), UInt8(w & 0x7F)]
                    for shift: UInt32 in [24, 16, 8, 0] { bytes.append(UInt8((w2 >> shift) & 0x7F)) }
                    if status == 0 || status == 1 { sysex = [] }  // complete or start
                    sysex += bytes.prefix(count)
                    if status == 0 || status == 3 { message([0xF0] + sysex + [0xF7]) }  // complete or end
                    i += 2
                }
            }
        }
    }

    private func message(_ msg: [UInt8]) {
        let now = monotonic()
        guard let m = Self.decode(msg) else { return }
        lock.lock(); defer { lock.unlock() }
        if let x = m["xfader"] { xfader = x; return }
        let deck = Int(m["deck"]!)
        var m2 = m
        m2["at"] = now
        let old = state[deck]
        let newTrack = old == nil || old!["samples"] != m["samples"] || old!["rate"] != m["rate"]
        m2["since"] = newTrack ? now : old!["since"]!
        state[deck] = m2
    }

    static func u7(_ b: [UInt8], _ i: Int, _ n: Int) -> Int { b[i..<(i + n)].reduce(0) { $0 * 128 + Int($1) } }

    /// One SysEx message from the script (format in mixxx/Amadeus-DMX-scripts.js) → its numbers.
    static func decode(_ msg: [UInt8]) -> [String: Double]? {
        guard msg.count > header.count, Array(msg.prefix(header.count)) == header, msg.last == 0xF7 else { return nil }
        let body = Array(msg[header.count..<(msg.count - 1)])
        if body.first == 0x02, body.count >= 3 { return ["xfader": Double(u7(body, 1, 2)) / 16383 * 2 - 1] }
        guard body.first == 0x01, body.count >= 28 else { return nil }
        let flags = Int(body[2])
        return [
            "deck": Double(body[1]), "play": Double(flags & 1), "loop": Double((flags >> 2) & 1),
            "orientation": Double((flags >> 3) & 3), "pos": Double(u7(body, 3, 5) - (1 << 30)) / 1000,
            "samples": Double(u7(body, 8, 5)), "rate": Double(u7(body, 13, 3)),
            "ratio": Double(u7(body, 16, 4) - (1 << 27)) / 1e6, "bpm": Double(u7(body, 20, 4)) / 1000,
            "vol": Double(u7(body, 24, 2)) / 16383,
        ]
    }

    /// Mixxx's crossfader (-1 left .. 1 right) → a deck's gain; orientation 0 left, 1 centre, 2 right.
    static func xfadeGain(_ x: Double, _ orientation: Int) -> Double {
        if orientation == 1 { return 1 }
        let far = orientation == 0 ? x : -x  // how far towards the other side
        return far > 0 ? min(1, 1 - far) : 1
    }

    func decks(at now: Double) -> [DeckReading] {
        lock.lock()
        let s = state, x = xfader
        lock.unlock()
        return s.keys.sorted().compactMap { n in
            let m = s[n]!
            guard now - m["at"]! <= 1, now - m["since"]! >= Self.loadingS else { return nil }  // unloaded, or loading
            let samples = Int(m["samples"]!), rate = Int(m["rate"]!), bpm = m["bpm"]!
            let t = library.find(samples: samples, rate: rate, bpm: bpm)
            let file = t.file.isEmpty ? "" : resolver.find(path: t.file, artist: t.artist, title: t.title)
            let ratio = m["ratio"]! == 0 ? 1 : m["ratio"]!
            let play = m["play"]! == 1
            return DeckReading(deck: n, file: file, pos: m["pos"]!, length: rate > 0 ? Double(samples) / 2 / Double(rate) : 0,
                               play: play, bpm: bpm, bpm0: bpm > 0 ? bpm / ratio : 0,
                               vol: m["vol"]! * Self.xfadeGain(x, Int(m["orientation"]!)), received: m["at"]!,
                               title: t.title, artist: t.artist, id: "\(samples)@\(rate)", rate: play ? ratio : 0)
        }
    }
}

extension Mixxx {
    func summary(at now: Double) -> String { decks(at: now).map(\.line).joined(separator: "\n") }
}

/// Mixxx's track library (mixxxdb.sqlite, read only): which track is this many samples at this rate.
final class MixxxLibrary: @unchecked Sendable {
    let path: URL?
    private let lock = NSLock()
    private var memo: [String: (file: String, artist: String, title: String)] = [:]

    init(path: URL?) { self.path = path }

    /// Mixxx counts samples in stereo (frames × 2) whatever the file has.
    func find(samples: Int, rate: Int, bpm: Double) -> (file: String, artist: String, title: String) {
        let key = "\(samples)@\(rate)"
        lock.lock()
        if let hit = memo[key] { lock.unlock(); return hit }
        lock.unlock()
        var found = (file: "", artist: "", title: "")
        guard let path, rate > 0, FileManager.default.fileExists(atPath: path.path) else { return found }
        var db: OpaquePointer?
        defer { sqlite3_close(db) }
        guard sqlite3_open_v2(path.path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else { return found }
        var st: OpaquePointer?
        defer { sqlite3_finalize(st) }
        let sql = "SELECT l.location, t.artist, t.title, t.bpm FROM library t JOIN track_locations l ON l.id = t.location "
            + "WHERE t.samplerate = ? AND abs(t.duration - ?) < 0.05 AND t.mixxx_deleted = 0"
        guard sqlite3_prepare_v2(db, sql, -1, &st, nil) == SQLITE_OK else { return found }
        sqlite3_bind_int(st, 1, Int32(rate))
        sqlite3_bind_double(st, 2, Double(samples) / 2 / Double(rate))
        var best = Double.infinity
        while sqlite3_step(st) == SQLITE_ROW {
            let text = { (i: Int32) in sqlite3_column_text(st, i).map { String(cString: $0) } ?? "" }
            let d = abs(sqlite3_column_double(st, 3) - bpm)
            if d < best { best = d; found = (text(0), text(1), text(2)) }
        }
        lock.lock()
        memo[key] = found
        lock.unlock()
        return found
    }
}
