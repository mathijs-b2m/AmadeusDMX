// Amadeus Link, on the DJ's laptop: passes VirtualDJ's mix state to the lighting computer over the network.
//
// The AmadeusLink plugin in VirtualDJ sends its packets to this app (UDP 127.0.0.1:9123, as it would to a
// local engine). The app advertises itself with Bonjour (_amadeuslink._tcp, TCP port 7123), pairs with a
// lighting computer through a 4-digit code, and forwards every packet with this laptop's clock and a
// signature. It serves the lighting computer the tracks VirtualDJ has loaded (and only those).
// Protocol: docs/protocols.md (and amadeus/show/link.py, the receiving end).
import CryptoKit
import Foundation
import Network
import Observation

@MainActor
@Observable
final class LinkServer {
    struct Peer: Identifiable {
        let id: String
        var address: String
        var since = Date()
        var packets = 0
    }

    private(set) var isOn = false
    private(set) var code = LinkServer.newCode()
    private(set) var peers: [Peer] = []
    private(set) var lastPluginPacket: Date = .distantPast
    private(set) var deckSummary = ""
    /// The DJ software sending the decks: the VirtualDJ plugin, or `amadeus probe NAME --emit` (which names it).
    private(set) var djApp = "VirtualDJ"
    private(set) var error: String?
    private(set) var tracksServed = 0

    @ObservationIgnored private let net = LinkNet()
    static let servicePort: UInt16 = 7123

    init() {
        if let fixed = UserDefaults.standard.string(forKey: "code"), fixed.count == 4 { code = fixed }  // -code 1234 (tests)
        net.onPlugin = { [weak self] summary, app in Task { @MainActor in self?.plugin(summary, app: app) } }
        net.onPeers = { [weak self] peers in Task { @MainActor in self?.peers = peers } }
        net.onError = { [weak self] e in Task { @MainActor in self?.error = e } }
        net.onServed = { [weak self] in Task { @MainActor in self?.tracksServed += 1 } }
        net.code = code
        let pluginPort = UInt16(UserDefaults.standard.integer(forKey: "pluginPort"))   // -pluginPort 9124 (tests)
        net.startPlugin(port: pluginPort > 0 ? pluginPort : 9123)
        if UserDefaults.standard.object(forKey: "linkOn") as? Bool ?? true { setOn(true) }
    }

    var djConnected: Bool { Date().timeIntervalSince(lastPluginPacket) < 1.5 }

    func setOn(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: "linkOn")
        isOn = on
        error = nil
        if on { net.startService(port: Self.servicePort, name: Host.current().localizedName ?? "DJ") } else { net.stopService() }
    }

    func renewCode() {
        code = Self.newCode()
        net.code = code
    }

    func disconnect(_ id: String) { net.drop(id) }

    private func plugin(_ summary: String, app: String) {
        lastPluginPacket = Date()
        deckSummary = summary
        djApp = app
    }

    static func newCode() -> String { String(format: "%04d", Int.random(in: 0...9999)) }
}

/// The networking, on its own queue (never the main thread: the forwarding must stay on time).
final class LinkNet: @unchecked Sendable {
    var code = "0000"
    var onPlugin: ((String, String) -> Void)?
    var onPeers: (([LinkServer.Peer]) -> Void)?
    var onError: ((String) -> Void)?
    var onServed: (() -> Void)?

    private let q = DispatchQueue(label: "amadeus.link", qos: .userInteractive)
    private var pluginListener: NWListener?
    private var service: NWListener?
    private struct Session {
        var key: SymmetricKey
        var udp: NWConnection
        var control: NWConnection
        var address: String
        var since = Date()
        var packets = 0
    }
    private var sessions: [String: Session] = [:]
    private var allowed: Set<String> = []          // files the plugin has reported: the only ones served
    private var seq: Int64 = 0
    private var lastSummary = Date.distantPast
    private var hashes: [String: (size: Int, mtime: Double, sha: String)] = [:]

    // MARK: VirtualDJ's plugin (local)

    func startPlugin(port: UInt16) {
        let params = NWParameters.udp
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!)
        params.allowLocalEndpointReuse = true
        do {
            let l = try NWListener(using: params)
            l.newConnectionHandler = { [weak self] c in
                c.start(queue: self?.q ?? .main)
                self?.receivePlugin(c)
            }
            l.stateUpdateHandler = { [weak self] st in
                if case .failed(let e) = st {
                    self?.onError?("Can’t listen for the DJ software on port \(port): \(e.localizedDescription). Is a lighting engine running on this laptop?")
                }
            }
            l.start(queue: q)
            pluginListener = l
        } catch {
            onError?("Can’t listen for the DJ software: \(error.localizedDescription)")
        }
    }

    private func receivePlugin(_ c: NWConnection) {
        c.receiveMessage { [weak self] data, _, _, err in
            guard let self else { return }
            if let data, !data.isEmpty { self.forward(data) }
            if err == nil { self.receivePlugin(c) }
        }
    }

    /// One plugin packet: remember its files, then send it on, stamped and signed, to every lighting computer.
    private func forward(_ plugin: Data) {
        let now = DispatchTime.now().uptimeNanoseconds
        if let obj = try? JSONSerialization.jsonObject(with: plugin) as? [String: Any], let decks = obj["decks"] as? [[String: Any]] {
            for d in decks { if let f = d["file"] as? String, !f.isEmpty { allowed.insert(f) } }
            if Date().timeIntervalSince(lastSummary) > 0.5 {
                lastSummary = Date()
                let s = decks.map { d in
                    let name = ((d["file"] as? String) ?? "").split(separator: "/").last.map(String.init) ?? "–"
                    return "\(d["deck"] ?? "?"): \((d["play"] as? Int) == 1 ? "▶" : "■") \(name)"
                }.joined(separator: "\n")
                onPlugin?(s, (obj["app"] as? String) ?? "VirtualDJ")
            }
        }
        guard !sessions.isEmpty else { return }
        seq += 1
        var payload = Data("{\"s\":\(seq),\"ts\":\(now),\"d\":".utf8)
        payload.append(plugin)
        payload.append(Data("}".utf8))
        for (id, var s) in sessions {
            var packet = payload
            packet.append(Data("|".utf8))
            packet.append(Data(Self.sign(s.key, payload).utf8))
            s.udp.send(content: packet, completion: .idempotent)
            s.packets += 1
            sessions[id] = s
        }
    }

    // MARK: the service (Bonjour, pairing, tracks)

    func startService(port: UInt16, name: String) {
        stopService()
        do {
            let params = NWParameters.tcp
            params.allowLocalEndpointReuse = true
            let l = try NWListener(using: params, on: NWEndpoint.Port(rawValue: port)!)
            l.service = NWListener.Service(name: name, type: "_amadeuslink._tcp")
            l.newConnectionHandler = { [weak self] c in
                c.start(queue: self?.q ?? .main)
                self?.readLines(c, buffer: Data()) { msg, rest in self?.handshake(c, msg, rest) }
            }
            l.stateUpdateHandler = { [weak self] st in
                if case .failed(let e) = st { self?.onError?("Can’t advertise: \(e.localizedDescription)") }
            }
            l.start(queue: q)
            service = l
        } catch {
            onError?("Can’t advertise: \(error.localizedDescription)")
        }
    }

    func stopService() {
        q.async { [self] in
            service?.cancel(); service = nil
            for s in sessions.values { s.udp.cancel(); s.control.cancel() }
            sessions = [:]
            publish()
        }
    }

    func drop(_ id: String) {
        q.async { [self] in
            if let s = sessions.removeValue(forKey: id) { s.udp.cancel(); s.control.cancel() }
            publish()
        }
    }

    private func publish() {
        let peers = sessions.map { LinkServer.Peer(id: $0.key, address: $0.value.address, since: $0.value.since,
                                                   packets: $0.value.packets) }
        onPeers?(peers.sorted { $0.since < $1.since })
    }

    /// Reads one JSON line, then hands it over with whatever came after it.
    private func readLines(_ c: NWConnection, buffer: Data, _ handle: @escaping ([String: Any], Data) -> Void) {
        if let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<nl], rest = Data(buffer[buffer.index(after: nl)...])
            if let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any] { handle(obj, rest) } else { c.cancel() }
            return
        }
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, done, err in
            guard let self, err == nil, let data, !data.isEmpty else { c.cancel(); return }
            self.readLines(c, buffer: buffer + data, handle)
            _ = done
        }
    }

    private func send(_ c: NWConnection, _ obj: [String: Any], then: (() -> Void)? = nil) {
        var d = (try? JSONSerialization.data(withJSONObject: obj)) ?? Data()
        d.append(0x0A)
        c.send(content: d, completion: .contentProcessed { _ in then?() })
    }

    private func handshake(_ c: NWConnection, _ first: [String: Any], _ rest: Data) {
        if first["file"] != nil { serveFile(c, first); return }
        guard first["hello"] as? String == "amadeus", let cn = first["nonce"] as? String else { c.cancel(); return }
        let sn = Self.randomHex()
        send(c, ["v": 1, "name": Host.current().localizedName ?? "DJ", "nonce": sn])
        readLines(c, buffer: rest) { [weak self] msg, rest in
            guard let self else { return }
            let code = self.code
            guard let proof = msg["proof"] as? String, let udpPort = msg["udp"] as? Int,
                  proof == Self.hmac(code, "pair", sn, cn).hexString else {
                self.send(c, ["ok": false, "error": "wrong pairing code"]) { c.cancel() }
                return
            }
            let key = SymmetricKey(data: Self.hmac(code, "key", sn, cn))
            let id = Self.randomHex().prefix(12).description
            guard case .hostPort(let host, _) = c.currentPath?.remoteEndpoint ?? c.endpoint else { c.cancel(); return }
            let udp = NWConnection(host: host, port: NWEndpoint.Port(rawValue: UInt16(udpPort))!, using: .udp)
            udp.start(queue: self.q)
            self.sessions[id] = Session(key: key, udp: udp, control: c, address: "\(host)")
            self.send(c, ["ok": true, "session": id])
            self.publish()
            self.keepalive(c, id: id, buffer: rest)
        }
    }

    private func keepalive(_ c: NWConnection, id: String, buffer: Data) {
        readLines(c, buffer: buffer) { [weak self] msg, rest in
            guard let self else { return }
            if let n = msg["ping"] { self.send(c, ["pong": n]) }
            self.keepalive(c, id: id, buffer: rest)
        }
        c.stateUpdateHandler = { [weak self] st in
            switch st {
            case .failed, .cancelled:
                self?.q.async {
                    if let s = self?.sessions.removeValue(forKey: id) { s.udp.cancel() }
                    self?.publish()
                }
            default: break
            }
        }
    }

    private func serveFile(_ c: NWConnection, _ req: [String: Any]) {
        guard let path = req["file"] as? String, let sid = req["session"] as? String, let s = sessions[sid],
              let auth = req["auth"] as? String,
              auth == HMAC<SHA256>.authenticationCode(for: Data(("file" + path).utf8), using: s.key).hexString else {
            send(c, ["ok": false, "error": "not allowed"]) { c.cancel() }
            return
        }
        guard allowed.contains(path), let data = FileManager.default.contents(atPath: path),
              let attrs = try? FileManager.default.attributesOfItem(atPath: path) else {
            send(c, ["ok": false, "error": "not a track the DJ software has loaded"]) { c.cancel() }
            return
        }
        let mtime = (attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        let sha: String
        if let h = hashes[path], h.size == data.count, h.mtime == mtime { sha = h.sha } else {
            sha = SHA256.hash(data: data).hexString
            hashes[path] = (data.count, mtime, sha)
        }
        send(c, ["ok": true, "size": data.count, "mtime": mtime, "sha256": sha])
        c.send(content: data, completion: .contentProcessed { [weak self] _ in
            c.cancel()
            self?.onServed?()
        })
    }

    // MARK: crypto (same as amadeus/link.py)

    static func hmac(_ code: String, _ parts: String...) -> Data {
        var h = HMAC<SHA256>(key: SymmetricKey(data: Data(code.utf8)))
        for p in parts { h.update(data: Data(p.utf8)) }
        return Data(h.finalize())
    }

    static func sign(_ key: SymmetricKey, _ payload: Data) -> String {
        Data(HMAC<SHA256>.authenticationCode(for: payload, using: key)).prefix(16).hexString
    }

    static func randomHex() -> String {
        (0..<16).map { _ in String(format: "%02x", UInt8.random(in: 0...255)) }.joined()
    }
}

extension Data {
    var hexString: String { map { String(format: "%02x", $0) }.joined() }
}

extension Sequence where Element == UInt8 {
    var hexString: String { map { String(format: "%02x", $0) }.joined() }
}
