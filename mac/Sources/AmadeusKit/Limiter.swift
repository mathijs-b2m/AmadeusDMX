// The brightness limiter, shared with every engine: config/limiter.json ({"level": 0.7}). A ceiling on every
// light, for testing and setting up without eye strain; 1 is off (amadeus/dmx/limiter.py).
import Foundation

extension Workspace {
    public static let limiterMinimum = 0.05

    public var limiterFile: URL { data.appending(path: "config/limiter.json") }

    /// The saved level, 0.05...1 (1: off, also when there is no file).
    public func limiterLevel() -> Double {
        guard let data = try? Data(contentsOf: limiterFile),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let v = (obj["level"] as? NSNumber)?.doubleValue, v.isFinite else { return 1 }
        return min(max(v, Self.limiterMinimum), 1)
    }

    /// Saves the level; a running engine follows within a quarter of a second.
    public func setLimiterLevel(_ level: Double) {
        let v = min(max(level, Self.limiterMinimum), 1)
        guard let data = try? JSONSerialization.data(withJSONObject: ["level": (v * 1000).rounded() / 1000]) else { return }
        try? FileManager.default.createDirectory(at: limiterFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: limiterFile, options: .atomic)
    }
}
