// The live feed client: connects to the engine's WebSocket (ws://127.0.0.1:8765 by default), keeps
// reconnecting, and keeps the last hello + frame.
//
// Frames (40 a second) are received and decoded off the main thread: if they were decoded on it, every busy
// moment of the UI (layout, glass, the inspector) would hold them up and the show would stutter. The renderer
// reads `latestFrame` (thread-safe) every display frame; the UI observes the slower fields, updated a few
// times a second.
import Foundation
import Observation
import os

@MainActor
@Observable
public final class LiveFeed {
    public enum State: Equatable, Sendable { case idle, connecting, connected }

    public private(set) var state: State = .idle
    public private(set) var hello: Hello?
    /// Updated a few times a second for the UI.
    public private(set) var time: Double = 0
    public private(set) var phrase: Int = 0
    public private(set) var decks: [DeckInfo] = []
    /// The laser guard's latest actions (laser id → what it did).
    public private(set) var laserGuard: [String: String] = [:]
    /// VirtualDJ on another computer (Decisive Link): the link's health, else nil.
    public private(set) var link: LinkStatus?
    /// Frames per second actually received.
    public private(set) var fps: Double = 0

    /// The newest frame (any thread may read it; the receiver writes it).
    @ObservationIgnored private let box = OSAllocatedUnfairLock<(Frame?, Date)>(initialState: (nil, .distantPast))
    public nonisolated var latestFrame: Frame? { box.withLock { $0.0 } }
    public nonisolated var latestFrameArrival: Date { box.withLock { $0.1 } }

    @ObservationIgnored private var loop: Task<Void, Never>?
    public let url: URL
    /// Status frames only, a few a second (Perform mode: no 3D stage to feed). Reconnects when it changes.
    public var lite = false {
        didSet {
            guard lite != oldValue, loop != nil else { return }
            stop()
            box.withLock { $0 = (nil, .distantPast) }   // a lite frame has no fixtures: never hand it to the renderer
            start()
        }
    }

    public init(url: URL = URL(string: "ws://127.0.0.1:8765")!) {
        self.url = url
    }

    public func start() {
        guard loop == nil else { return }
        let url = lite ? self.url.appending(path: "lite") : self.url, box = self.box
        loop = Task.detached(priority: .userInitiated) { [weak self] in
            while !Task.isCancelled {
                await Self.receive(url: url, box: box, feed: self)
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    public func stop() {
        loop?.cancel(); loop = nil
        state = .idle
    }

    /// True while frames keep arriving (the engine is sending, i.e. a show runs).
    public var isReceiving: Bool { Date().timeIntervalSince(latestFrameArrival) < 1.5 }

    /// The newest frame, when it carries the fixtures (not a lite status frame).
    public nonisolated var latestFullFrame: Frame? { latestFrame.flatMap { $0.lite ? nil : $0 } }

    /// One connection: receive until it drops. Runs off the main thread.
    private nonisolated static func receive(url: URL, box: OSAllocatedUnfairLock<(Frame?, Date)>, feed: LiveFeed?) async {
        await feed?.set(state: .connecting)
        let task = URLSession.shared.webSocketTask(with: url)
        task.maximumMessageSize = 16 << 20
        task.resume()
        var connected = false
        var count = 0, since = Date(), lastUI = Date.distantPast, lastPhrase = -1
        do {
            while !Task.isCancelled {
                let msg = try await task.receive()
                if !connected { connected = true; await feed?.set(state: .connected) }
                let data: Data
                switch msg {
                case .string(let s): data = Data(s.utf8)
                case .data(let d): data = d
                @unknown default: continue
                }
                guard let m = FeedMessage.decode(data) else { continue }
                switch m {
                case .hello(let h):
                    await feed?.set(hello: h)
                case .frame(let f):
                    let now = Date()
                    box.withLock { $0 = (f, now) }
                    count += 1
                    var fps: Double?
                    if now.timeIntervalSince(since) >= 1 {
                        fps = Double(count) / now.timeIntervalSince(since)
                        count = 0; since = now
                        if UserDefaults.standard.bool(forKey: "gpuStats") {  // development: what the counter shows
                            let line = String(format: "feed counter %.1f fps\n", fps!)
                            let url = FileManager.default.temporaryDirectory.appending(path: "gpu-stats.txt")
                            if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
                        }
                    }
                    // the UI: a few times a second, or at once when the phrase changes
                    if now.timeIntervalSince(lastUI) >= 0.2 || f.phrase != lastPhrase || fps != nil {
                        lastUI = now; lastPhrase = f.phrase
                        let t = f.t, p = f.phrase, d = f.decks, g = f.laserGuard ?? [:], l = f.link
                        // hand the UI its update without waiting: a busy main thread must never hold up the frames
                        Task { @MainActor in feed?.update(time: t, phrase: p, decks: d, guard: g, link: l, fps: fps) }
                    }
                }
            }
        } catch {
            // engine not running (yet) or it went away: try again
        }
        task.cancel(with: .goingAway, reason: nil)
        await feed?.set(state: .connecting)
    }

    private func set(state s: State) { if state != s { state = s } }
    private func set(hello h: Hello) { hello = h }

    private func update(time t: Double, phrase p: Int, decks d: [DeckInfo]?, guard g: [String: String], link l: LinkStatus?,
                        fps f: Double?) {
        if l != link { link = l }
        time = t
        if p != phrase { phrase = p }
        if let d, d != decks { decks = d }
        if g != laserGuard { laserGuard = g }
        if let f { fps = f }
    }
}
