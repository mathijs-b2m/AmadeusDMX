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

// Settings per integration, shared with the engine: config/integrations.json ({"djay": {"streamed": true}}).
// Live mode passes them to the integration (decisive/show/sources/__init__.py); `--opt` overrides them.
extension Workspace {
    public var integrationsFile: URL { root.appending(path: "config/integrations.json") }

    private func integrations() -> [String: Any] {
        guard let data = try? Data(contentsOf: integrationsFile),
              let all = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return all
    }

    public func integrationSetting(_ source: String, _ key: String) -> Bool {
        (integrations()[source] as? [String: Any])?[key] as? Bool ?? false
    }

    /// Saves one setting, keeping every other one in the file.
    public func setIntegrationSetting(_ source: String, _ key: String, _ value: Bool) {
        var all = integrations()
        var one = all[source] as? [String: Any] ?? [:]
        one[key] = value
        all[source] = one
        guard let data = try? JSONSerialization.data(withJSONObject: all, options: [.prettyPrinted, .sortedKeys]) else { return }
        try? FileManager.default.createDirectory(at: integrationsFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: integrationsFile, options: .atomic)
    }

    /// A Python package installed in the engine's environment (e.g. yt_dlp).
    public func hasPythonPackage(_ name: String) -> Bool {
        let lib = root.appending(path: ".venv/lib")
        let versions = (try? FileManager.default.contentsOfDirectory(atPath: lib.path)) ?? []
        return versions.contains { FileManager.default.fileExists(atPath: lib.appending(path: "\($0)/site-packages/\(name)").path) }
    }
}
