// The DJ software live mode can follow: the engine's own list (decisive/show/sources/sources.json), so a new
// integration shows up in the app without a change here.
import Foundation

public struct DJSource: Decodable, Identifiable, Sendable, Equatable {
    public var name: String
    public var app: String
    public var position: String   // exact | beat | metadata: only "exact" can light a show
    public var verified: String
    public var menu: Bool?
    public var waiting: String?   // what to do while the show waits for it
    public var id: String { name }
}

extension Workspace {
    public var djSourcesFile: URL { root.appending(path: "decisive/show/sources/sources.json") }

    /// The DJ software to offer in the Start menu (VirtualDJ first), from the engine's list.
    public func djSources() -> [DJSource] {
        guard let data = try? Data(contentsOf: djSourcesFile),
              let all = try? JSONDecoder().decode([DJSource].self, from: data) else { return [] }
        return all.filter { $0.menu ?? true }
    }

    /// One DJ software from the engine's list by its name (vdj, mixxx, djay, …).
    public func djSource(_ name: String) -> DJSource? {
        guard let data = try? Data(contentsOf: djSourcesFile),
              let all = try? JSONDecoder().decode([DJSource].self, from: data) else { return nil }
        return all.first { $0.name == name }
    }
}
