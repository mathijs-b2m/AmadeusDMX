// djay Pro on the DJ laptop: what its window says, read through the macOS Accessibility API, like VoiceOver
// would (a port of amadeus/show/sources/djay.py: the same labels, the same playhead, the same library lookup).
//
// Amadeus Link only reads: whether it may (AXIsProcessTrusted), djay's window, and the text of its deck controls.
// It never clicks, types or changes anything. A deck on SYNC is marked so; the lighting computer reads the
// exact beat from Ableton Link itself. Tracks djay streams (Spotify) have no file here: they stay dark over Link.
import AppKit
import ApplicationServices
import Foundation
import SQLite3

final class Djay: DJReader, @unchecked Sendable {
    let app = "djay Pro"
    static let bundle = "com.algoriddim.djay"
    static let library = FileManager.default.homeDirectoryForCurrentUser
        .appending(path: "Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db")

    private let lock = NSLock()
    private var running = true
    private var controls = Controls()
    private var heads: [Int: Playhead] = [:]
    private var info: [Int: (title: String, artist: String, file: String, length: Double, vol: Double?, bpm: Double, sync: Bool)] = [:]
    private var xfader = 0.5
    private var trusted = false
    private var found = false
    private var streamed: Set<Int> = []
    private let resolver = Resolver()
    private let tracks: DjayLibrary

    init() {
        tracks = DjayLibrary(path: Self.library)
        trusted = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
        tracks.read()
        resolver.add(tracks.folders)
        Thread.detachNewThread { [weak self] in self?.scanLoop() }
        let t = Thread { [weak self] in self?.readLoop() }
        t.qualityOfService = .userInteractive
        t.start()
    }

    var note: String {
        lock.lock(); defer { lock.unlock() }
        if !trusted { return "Amadeus Link may not read djay's window yet: System Settings › Privacy & Security › Accessibility, switch on Amadeus Link." }
        if !found { return "Waiting for djay Pro." }
        if !streamed.isEmpty { return "Streamed tracks (Spotify) stay dark over Amadeus Link: play files from your library." }
        return ""
    }

    func stop() {
        lock.lock(); running = false; lock.unlock()
    }

    private var isRunning: Bool { lock.lock(); defer { lock.unlock() }; return running }

    // MARK: finding djay's controls (~0.1 s: never in the way of the playhead)

    private func scanLoop() {
        while isRunning {
            if !trusted { trusted = AXIsProcessTrusted() }
            let found = Controls(trusted ? scan() : [:])
            lock.lock()
            controls = found
            self.found = !found.labels.isEmpty
            lock.unlock()
            Thread.sleep(forTimeInterval: found.labels.isEmpty ? 0.5 : 2.0)
        }
    }

    private func scan() -> [String: [AXUIElement]] {
        guard let app = NSWorkspace.shared.runningApplications.first(where: { ($0.bundleIdentifier ?? "").hasPrefix(Self.bundle) })
        else { return [:] }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        var out: [String: [AXUIElement]] = [:]
        for win in elements(root, "AXWindows") {
            for group in elements(win, "AXChildren") where string(group, "AXDescription") == "Decks" {
                for e in elements(group, "AXChildren") { out[string(e, "AXDescription") ?? "", default: []].append(e) }
            }
        }
        return out
    }

    private func attr(_ e: AXUIElement, _ name: String) -> AnyObject? {
        var v: AnyObject?
        return AXUIElementCopyAttributeValue(e, name as CFString, &v) == .success ? v : nil
    }

    private func elements(_ e: AXUIElement, _ name: String) -> [AXUIElement] { (attr(e, name) as? [AXUIElement]) ?? [] }
    private func string(_ e: AXUIElement, _ name: String) -> String? { attr(e, name) as? String }

    private func value(_ c: Controls, _ label: String) -> String? {
        guard let e = c.labels[label]?.first, let v = attr(e, "AXValue") else { return nil }
        return (v as? String) ?? (v as? NSNumber)?.stringValue
    }

    // MARK: reading

    private func readLoop() {
        var slow = 0.0
        while isRunning {
            lock.lock()
            let c = controls
            lock.unlock()
            if c.labels.isEmpty {
                Thread.sleep(forTimeInterval: 0.2)
                continue
            }
            let now = monotonic()
            if now - slow > 0.2 {  // what changes slowly: track, tempo, faders
                slow = now
                readSlow(c, now)
            }
            for n in c.decks {  // what must be on time: the playhead
                let play = value(c, "Play / Pause, Deck \(n)") == "Active"
                let secs = Self.clock(value(c, "Elapsed time, Deck \(n)"))
                lock.lock()
                let head = heads[n] ?? Playhead()
                heads[n] = head
                head.setPlay(play, now)
                if let secs, secs != head.label { head.seen(secs, monotonic()) }
                lock.unlock()
            }
            Thread.sleep(forTimeInterval: 0.005)
        }
    }

    private func readSlow(_ c: Controls, _ now: Double) {
        let x = Self.percent(value(c, "Crossfader"))
        var streams: Set<Int> = []
        for n in c.decks {
            let title = value(c, "Title, Deck \(n)") ?? "", artist = value(c, "Artist, Deck \(n)") ?? ""
            lock.lock()
            var i = info[n] ?? (title: "", artist: "", file: "", length: 0, vol: nil, bpm: 0, sync: false)
            lock.unlock()
            if (title, artist) != (i.title, i.artist) || (!title.isEmpty && i.file.isEmpty) {
                let known = title.isEmpty ? "" : tracks.find(title: title, artist: artist)
                let file = title.isEmpty ? "" : resolver.find(path: known, artist: artist, title: title)
                i.title = title
                i.artist = artist
                i.file = file
                i.length = file.isEmpty ? 0 : (Resolver.length(of: URL(filePath: file)) ?? 0)
            }
            if !title.isEmpty && i.file.isEmpty { streams.insert(n) }
            i.vol = Self.percent(value(c, "Line volume, Deck \(n)"))
            i.bpm = c.bpm[n] ?? 0
            i.sync = value(c, "Sync, Deck \(n)") == "Active"
            let tempo = Self.percent(value(c, "Tempo, Deck \(n)")) ?? 0
            lock.lock()
            info[n] = i
            let head = heads[n] ?? Playhead()
            heads[n] = head
            head.setSpeed(1 + tempo, now)
            lock.unlock()
        }
        lock.lock()
        if let x { xfader = x }
        streamed = streams
        lock.unlock()
    }

    func decks(at now: Double) -> [DeckReading] {
        lock.lock(); defer { lock.unlock() }
        return heads.keys.sorted().compactMap { n in
            guard let head = heads[n], let i = info[n], !i.title.isEmpty else { return nil }
            let x = n % 2 == 1 ? xfader : 1 - xfader  // decks 1/3 on the left of the crossfader, 2/4 on the right
            let gain = min(1, 2 * (1 - x))
            return DeckReading(deck: n, file: i.file, pos: head.at(now), length: i.length, play: head.play, bpm: i.bpm,
                               bpm0: i.bpm > 0 ? i.bpm / head.speed : 0, vol: (i.vol ?? 1) * gain, received: now,
                               title: i.title, artist: i.artist, rate: head.play ? head.speed : 0, sync: i.sync && head.play)
        }
    }

    func summary(at now: Double) -> String {
        lock.lock()
        let numbers = controls.decks
        lock.unlock()
        let read = Dictionary(uniqueKeysWithValues: decks(at: now).map { ($0.deck, $0) })
        return numbers.map { read[$0]?.line ?? "\($0): no track" }.joined(separator: "\n")
    }

    /// "01:07" → 67, "1:02:03" → 3723; anything else → nil. (No regex: it runs 200 times a second per deck.)
    static func clock(_ text: String?) -> Int? {
        var t = Substring((text ?? "").trimmingCharacters(in: .whitespaces))
        if t.hasPrefix("-") { t = t.dropFirst() }
        let parts = t.split(separator: ":", omittingEmptySubsequences: false)
        guard (2...3).contains(parts.count), parts.last!.count == 2,
              parts.allSatisfy({ !$0.isEmpty && $0.allSatisfy(\.isASCII) && $0.allSatisfy(\.isNumber) }) else { return nil }
        let n = parts.map { Int($0)! }
        return n.count == 3 ? n[0] * 3600 + n[1] * 60 + n[2] : n[0] * 60 + n[1]
    }

    /// "73%" → 0.73.
    static func percent(_ text: String?) -> Double? {
        guard let t = text?.trimmingCharacters(in: .whitespaces) else { return nil }
        return Double(t.hasSuffix("%") ? String(t.dropLast()) : t).map { $0 / 100 }
    }
}

/// djay's deck controls by their VoiceOver labels, with what the labels themselves say: the deck numbers
/// ("Elapsed time, Deck 1") and each deck's tempo (its tempo button is labelled "125.0, Deck 1").
struct Controls {
    var labels: [String: [AXUIElement]] = [:]
    var decks: [Int] = []
    var bpm: [Int: Double] = [:]

    init(_ labels: [String: [AXUIElement]] = [:]) {
        self.labels = labels
        var decks = Set<Int>()
        for k in labels.keys {
            guard let r = k.range(of: ", Deck ", options: .backwards), let n = Int(k[r.upperBound...]) else { continue }
            let head = k[..<r.lowerBound]
            if head == "Elapsed time" { decks.insert(n) } else if let b = Double(head) { bpm[n] = b }
        }
        self.decks = decks.sorted()
    }
}

/// One deck's position from its whole-second label: a new second is seen at most `late` after the playhead
/// crossed it, never before. Over the last ticks, the one predicting the furthest position is the least late.
final class Playhead {
    static let late = 0.15  // djay redraws ~10× a second, plus our polling
    static let keep = 8

    private var ticks: [(seen: Double, pos: Double)] = []
    private var coarse: (seen: Double, pos: Double)?
    private(set) var label: Int?
    private(set) var speed = 1.0
    private(set) var play = false
    private var frozen = 0.0

    func at(_ t: Double) -> Double {
        let s = play ? speed : 0
        if !ticks.isEmpty { return ticks.map { $0.pos + (t - $0.seen) * s }.max()! }
        if let c = coarse { return c.pos + (t - c.seen) * s }
        return frozen
    }

    /// Speed or play state changes: what we know becomes one anchor at the current position.
    private func rebase(_ t: Double) {
        let exact = !ticks.isEmpty
        let pos = at(t)
        ticks.removeAll()
        if exact { ticks.append((t, pos)); coarse = nil } else { coarse = (t, pos) }
        frozen = pos
    }

    func setPlay(_ p: Bool, _ t: Double) {
        guard p != play else { return }
        rebase(t)
        play = p
    }

    func setSpeed(_ s: Double, _ t: Double) {
        guard abs(s - speed) > 1e-4 else { return }
        rebase(t)
        speed = s
    }

    /// A new label value: a tick (the playhead crossed a whole second) or a jump (seek, loop).
    func seen(_ new: Int, _ t: Double) {
        let old = label
        label = new
        guard let old else {
            coarse = (t, Double(new) + 0.5)
            frozen = Double(new) + 0.5
            return
        }
        if new == old + 1 {
            if !ticks.isEmpty, !(-0.05...(Self.late + 0.05)).contains(at(t) - Double(new)) { ticks.removeAll() }  // a nudge meanwhile
            ticks.append((t, Double(new)))
            if ticks.count > Self.keep { ticks.removeFirst() }
            coarse = nil
            frozen = Double(new)
            return
        }
        ticks.removeAll()  // anything else: the DJ moved the playhead
        coarse = (t, Double(new) + 0.5)
        frozen = Double(new) + 0.5
    }
}

/// djay's library (MediaLibrary.db, read only): a track's file by its title and artist.
final class DjayLibrary: @unchecked Sendable {
    let path: URL
    private let lock = NSLock()
    private var files: [String: String] = [:]  // "title\u{0}artist" → path
    private var readAt = 0.0

    init(path: URL) { self.path = path }

    var folders: [URL] {
        lock.lock(); defer { lock.unlock() }
        return Array(Set(files.values.map { URL(filePath: $0).deletingLastPathComponent() }))
    }

    func find(title: String, artist: String) -> String {
        lock.lock()
        let missing = files["\(title)\u{0}\(artist)"] == nil && monotonic() - readAt > 2
        lock.unlock()
        if missing { read() }  // a track djay hasn't told us about yet: it may have just been added
        lock.lock(); defer { lock.unlock() }
        return files["\(title)\u{0}\(artist)"] ?? files.first { $0.key.hasPrefix("\(title)\u{0}") }?.value ?? ""
    }

    func read() {
        var found: [String: String] = [:]
        var db: OpaquePointer?
        defer { sqlite3_close(db) }
        guard sqlite3_open_v2(path.path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else { return }
        var st: OpaquePointer?
        defer { sqlite3_finalize(st) }
        guard sqlite3_prepare_v2(db, "SELECT data FROM database2 WHERE collection = 'localMediaItemLocations'", -1, &st, nil) == SQLITE_OK
        else { return }
        while sqlite3_step(st) == SQLITE_ROW {
            guard let p = sqlite3_column_blob(st, 0) else { continue }
            let s = Self.strings(Data(bytes: p, count: Int(sqlite3_column_bytes(st, 0))))
            guard let url = s.first(where: { $0.hasPrefix("file://") }), let file = URL(string: url)?.path else { continue }
            let title = s.firstIndex(of: "title").flatMap { $0 > 0 ? s[$0 - 1] : nil } ?? ""
            let artist = s.firstIndex(of: "artist").flatMap { $0 > 0 ? s[$0 - 1] : nil } ?? ""
            found["\(title)\u{0}\(artist)"] = file
        }
        lock.lock()
        files.merge(found) { _, new in new }
        readAt = monotonic()
        lock.unlock()
    }

    /// The strings in djay's record format: 0x08, 1–1000 bytes, 0x00 (as re.findall(rb"\x08([^\x00]{1,1000})\x00")).
    static func strings(_ data: Data) -> [String] {
        let b = [UInt8](data)
        var out: [String] = []
        var i = 0
        while i < b.count {
            if b[i] == 0x08, let end = b[(i + 1)..<min(b.count, i + 1002)].firstIndex(of: 0), end - i - 1 >= 1, end - i - 1 <= 1000 {
                out.append(String(decoding: b[(i + 1)..<end], as: UTF8.self))
                i = end + 1
            } else {
                i += 1
            }
        }
        return out
    }
}
