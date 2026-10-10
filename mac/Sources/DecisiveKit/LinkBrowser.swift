// Finds Decisive Link (the DJ laptop's companion) on the network: Bonjour _decisivelink._tcp.
import Foundation
import Network
import Observation

@MainActor
@Observable
public final class LinkBrowser {
    public struct DJ: Identifiable, Hashable, Sendable {
        public let name: String
        public var id: String { name }
    }

    public private(set) var found: [DJ] = []
    public private(set) var searching = false
    @ObservationIgnored private var browser: NWBrowser?

    public init() {}

    public func start() {
        guard browser == nil else { return }
        let b = NWBrowser(for: .bonjour(type: "_decisivelink._tcp", domain: nil), using: .tcp)
        b.browseResultsChangedHandler = { [weak self] results, _ in
            let names = results.compactMap { r -> String? in
                if case .service(let name, _, _, _) = r.endpoint { return name }
                return nil
            }
            Task { @MainActor in self?.found = Array(Set(names)).sorted().map(DJ.init(name:)) }
        }
        b.stateUpdateHandler = { [weak self] st in
            Task { @MainActor in self?.searching = { if case .ready = st { true } else { false } }() }
        }
        b.start(queue: .main)
        browser = b
    }

    public func stop() {
        browser?.cancel()
        browser = nil
        searching = false
    }
}

/// The link's health as the engine reports it in each frame.
public struct LinkStatus: Decodable, Sendable, Equatable {
    public var name: String
    public var up: Bool
    public var offsetMs: Double
    public var jitterMs: Double
    public var lost: Int
    public var packets: Int
    public var fetching: [String]

    enum CodingKeys: String, CodingKey {
        case name, up, offsetMs = "offset_ms", jitterMs = "jitter_ms", lost, packets, fetching
    }
}
