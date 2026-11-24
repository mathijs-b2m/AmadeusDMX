// The DMX trace (amadeus/dmx/trace.py): every value that goes out to the lights, as it changes. The engine writes
// it to a file while a flag file exists; this switches the flag and follows the file's end.
import Foundation
import Observation

@MainActor
@Observable
public final class DMXTrace {
    public struct Line: Identifiable, Sendable, Equatable {
        public let id: Int
        public let text: String
        /// The engine's own notes ("# … trace on"), not a value.
        public var isNote: Bool { text.hasPrefix("#") }
    }

    public let data: URL
    public let flag: URL
    public let log: URL
    public private(set) var isOn = false
    public private(set) var lines: [Line] = []

    /// How many lines are kept to look back in (the file keeps them all).
    public static let kept = 20_000
    /// Further behind than this (the page was away, or the file is old): skip to the end.
    static let behind: UInt64 = 2 << 20

    @ObservationIgnored private var offset: UInt64 = 0
    @ObservationIgnored private var partial = Data()
    @ObservationIgnored private var nextID = 0

    public init(data: URL) {
        self.data = data
        let cache = data.appendingPathComponent(".cache")
        flag = cache.appendingPathComponent("dmx-trace")
        log = cache.appendingPathComponent("dmx-trace.log")
        isOn = FileManager.default.fileExists(atPath: flag.path)
    }

    /// Switches the trace on or off: a running engine follows within half a second.
    public func set(_ on: Bool) {
        let fm = FileManager.default
        if on {
            try? fm.createDirectory(at: flag.deletingLastPathComponent(), withIntermediateDirectories: true)
            fm.createFile(atPath: flag.path, contents: nil)
        } else {
            try? fm.removeItem(at: flag)
        }
        isOn = fm.fileExists(atPath: flag.path)
    }

    /// Empties the trace: the file too (the engine goes on writing at its start).
    public func clear() {
        try? Data().write(to: log)
        lines.removeAll()
        offset = 0
        partial.removeAll()
    }

    /// Reads what the engine wrote since the last time. `read: false` only follows the switch.
    public func poll(read: Bool = true) {
        let on = FileManager.default.fileExists(atPath: flag.path)
        if on != isOn { isOn = on }
        guard read, let h = try? FileHandle(forReadingFrom: log) else { return }
        defer { try? h.close() }
        guard let size = try? h.seekToEnd() else { return }
        var skipped = false
        if size < offset {  // started over (cleared, or full)
            offset = 0
            partial.removeAll()
        }
        if size - offset > Self.behind {
            offset = size - Self.behind
            partial.removeAll()
            skipped = true
        }
        guard size > offset, (try? h.seek(toOffset: offset)) != nil, let data = try? h.read(upToCount: Int(size - offset)) else { return }
        offset += UInt64(data.count)
        partial.append(data)
        guard let end = partial.lastIndex(of: 0x0A) else { return }
        var new = String(decoding: partial[..<end], as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: true)
        partial = Data(partial[partial.index(after: end)...])
        if skipped, !new.isEmpty { new.removeFirst() }  // cut in the middle of a line
        guard !new.isEmpty else { return }
        var all = lines
        if skipped { all.removeAll() }
        for text in new {
            all.append(Line(id: nextID, text: String(text)))
            nextID += 1
        }
        if all.count > Self.kept { all.removeFirst(all.count - Self.kept) }
        lines = all
    }
}
