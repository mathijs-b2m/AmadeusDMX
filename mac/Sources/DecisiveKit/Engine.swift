// Runs the Python engine (`python -m decisive …`) as a child process: start, stop (Ctrl-C first, so the
// engine blacks out the lights itself), and its output line by line for the log.
import Foundation
import Observation

@MainActor
@Observable
public final class EngineProcess {
    public enum State: Equatable, Sendable {
        case stopped
        case starting
        case running
        case failed(String)
    }

    public struct LogLine: Identifiable, Sendable {
        public let id: Int
        public let date: Date
        public let text: String
        public let isError: Bool
    }

    public let name: String
    public private(set) var state: State = .stopped
    public private(set) var log: [LogLine] = []
    public private(set) var arguments: [String] = []
    /// The last line the engine printed (for a status line).
    public private(set) var lastLine: String = ""

    @ObservationIgnored private var process: Process?
    @ObservationIgnored private var nextID = 0
    @ObservationIgnored private var activity: NSObjectProtocol?
    @ObservationIgnored private var readyMarker: String?
    @ObservationIgnored private var buffers: [ObjectIdentifier: String] = [:]
    @ObservationIgnored public var onLine: ((String) -> Void)?

    public init(name: String) { self.name = name }

    /// The engine's process id while it runs (for the power meter).
    public var pid: Int32? { process.flatMap { $0.isRunning ? $0.processIdentifier : nil } }

    public var isRunning: Bool {
        switch state { case .running, .starting: true; default: false }
    }

    /// Starts `python -m decisive <args>` in the workspace. `readyWhen`: a text in the output that means the
    /// engine is up (until then the state is .starting).
    public func start(_ ws: Workspace, _ args: [String], environment: [String: String] = [:], readyWhen: String? = nil,
                      keepAwake: Bool = false) {
        guard !isRunning else { return }
        let p = Process()
        p.executableURL = ws.python
        p.arguments = ["-m", "decisive"] + args
        p.currentDirectoryURL = ws.root
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        for (k, v) in environment { env[k] = v }
        p.environment = env
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        p.standardInput = FileHandle.nullDevice
        // the light loop must tick 40 times a second on time: top priority, also when the app is in the background
        p.qualityOfService = keepAwake ? .userInteractive : .default
        for (pipe, isErr) in [(out, false), (err, true)] {
            pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
                let data = h.availableData
                guard !data.isEmpty else { h.readabilityHandler = nil; return }
                let text = String(decoding: data, as: UTF8.self)
                Task { @MainActor in self?.ingest(text, from: pipe, isError: isErr) }
            }
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus, reason = proc.terminationReason
            Task { @MainActor in self?.ended(code: code, reason: reason, process: proc) }
        }
        arguments = args
        readyMarker = readyWhen
        append("$ decisive \(args.joined(separator: " "))", isError: false)
        do {
            try p.run()
            process = p
            Self.remember(pid: p.processIdentifier, name: name)
            state = readyWhen == nil ? .running : .starting
            if keepAwake {  // like `caffeinate -i`: no idle sleep while a show runs, the display may still sleep
                // latencyCritical: no App Nap and no timer coalescing for the app and the engine it started (they share
                // the app's coalition); otherwise macOS may throttle the show while you work in VirtualDJ
                activity = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled, .userInitiated, .latencyCritical],
                                                                 reason: "Decisive Lightning show running")
            }
        } catch {
            state = .failed(error.localizedDescription)
            append("could not start: \(error.localizedDescription)", isError: true)
        }
    }

    /// Ctrl-C (the engine stops cleanly and blacks out), then terminate if it doesn't stop.
    public func stop() {
        guard let p = process, p.isRunning else { state = .stopped; return }
        p.interrupt()
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { if p.isRunning { p.terminate() } }
    }

    /// Stops and waits until the process has ended (e.g. before quitting the app).
    public func stopAndWait(timeout: TimeInterval = 5) {
        guard let p = process, p.isRunning else { return }
        p.interrupt()
        let end = Date().addingTimeInterval(timeout)
        while p.isRunning && Date() < end { usleep(50_000) }
        if p.isRunning { p.terminate() }
    }

    public func clearLog() { log.removeAll() }

    // MARK: engines left behind

    private static func pidKey(_ name: String) -> String { "enginePID.\(name)" }

    private static func remember(pid: Int32?, name: String) {
        if let pid { UserDefaults.standard.set(Int(pid), forKey: pidKey(name)) }
        else { UserDefaults.standard.removeObject(forKey: pidKey(name)) }
    }

    /// An engine this app started before and that outlived it (the app crashed or was killed): stop it, so it
    /// doesn't keep driving the lights or hold the ports. Only if that pid is still a `decisive` process.
    public static func stopLeftover(name: String) {
        let pid = Int32(UserDefaults.standard.integer(forKey: pidKey(name)))
        guard pid > 0, kill(pid, 0) == 0 else { remember(pid: nil, name: name); return }
        var size = 0
        var mib: [Int32] = [CTL_KERN, KERN_PROCARGS2, pid]
        sysctl(&mib, 3, nil, &size, nil, 0)
        var buf = [UInt8](repeating: 0, count: max(size, 1))
        sysctl(&mib, 3, &buf, &size, nil, 0)
        let args = String(decoding: buf.prefix(size).map { $0 == 0 ? 32 : $0 }, as: UTF8.self)
        if args.contains("-m decisive") {
            kill(pid, SIGINT)
            for _ in 0..<40 where kill(pid, 0) == 0 { usleep(100_000) }
            if kill(pid, 0) == 0 { kill(pid, SIGTERM) }
        }
        remember(pid: nil, name: name)
    }

    private func ingest(_ text: String, from pipe: Pipe, isError: Bool) {
        let key = ObjectIdentifier(pipe)
        var buf = (buffers[key] ?? "") + text
        while let nl = buf.firstIndex(of: "\n") {
            let line = String(buf[..<nl]).replacingOccurrences(of: "\r", with: "")
            buf = String(buf[buf.index(after: nl)...])
            if !line.isEmpty { append(line, isError: isError && Self.looksLikeError(line)) }
        }
        buffers[key] = buf
    }

    private static func looksLikeError(_ line: String) -> Bool {
        let l = line.lowercased()
        return l.contains("error") || l.contains("traceback") || l.contains("exception")
    }

    private func append(_ line: String, isError: Bool) {
        log.append(LogLine(id: nextID, date: Date(), text: line, isError: isError))
        nextID += 1
        if log.count > 4000 { log.removeFirst(log.count - 4000) }
        lastLine = line
        if state == .starting, let m = readyMarker, line.contains(m) { state = .running }
        onLine?(line)
    }

    private func ended(code: Int32, reason: Process.TerminationReason, process p: Process) {
        guard p === process else { return }
        process = nil
        Self.remember(pid: nil, name: name)
        if let a = activity { ProcessInfo.processInfo.endActivity(a); activity = nil }
        let clean = code == 0 || reason == .uncaughtSignal || code == 130 || code == 2 && lastLine.contains("KeyboardInterrupt")
        if clean || log.last?.text.contains("KeyboardInterrupt") == true {
            state = .stopped
            append("engine stopped", isError: false)
        } else {
            let why = log.last(where: \.isError)?.text ?? lastLine
            state = .failed(why)
            append("engine exited with code \(code)", isError: true)
        }
    }
}
