// Colours and room geometry shared by every view of the show (same values as web/index.html).
import Foundation
import simd

public enum Palettes {
    public static let all: [String: [SIMD3<Float>]] = [
        "warm": [[1, 0.45, 0], [1, 0.15, 0], [0.9, 0, 0.05], [1, 0.7, 0.2]],
        "cool": [[0, 0.3, 1], [0, 0.8, 1], [0.45, 0, 1], [0.1, 0.1, 0.9]],
        "neon": [[1, 0, 0.8], [0.4, 1, 0], [0, 1, 0.9], [0.8, 0, 1]],
        "fire": [[1, 0, 0], [1, 0.35, 0], [1, 0.9, 0.7], [0.8, 0.05, 0]],
        "ice": [[0.85, 0.95, 1], [0.3, 0.8, 1], [0.1, 0.35, 1], [1, 1, 1]],
        "gold": [[1, 0.65, 0.1], [0.55, 0, 0.9], [1, 0.85, 0.45], [0.9, 0.3, 0.6]],
        "stage": [[1, 0.85, 0.65], [1, 0.55, 0.1], [0.1, 0.2, 0.9], [1, 1, 1]],
    ]

    public static func colors(_ name: String?) -> [SIMD3<Float>] {
        all[name ?? ""] ?? [[1, 0.3, 0.8], [0.2, 0.7, 1]]
    }
}

public enum Sections {
    public static let order = ["intro", "groove", "buildup", "drop", "breakdown", "outro"]
    public static let colors: [String: SIMD3<Float>] = [
        "intro": [0.357, 0.420, 0.549], "groove": [0.247, 0.561, 0.420], "buildup": [0.788, 0.510, 0.169],
        "drop": [0.847, 0.271, 0.310], "breakdown": [0.424, 0.333, 0.722], "outro": [0.290, 0.322, 0.376],
    ]
    public static func color(_ s: String) -> SIMD3<Float> { colors[s] ?? [0.4, 0.4, 0.45] }
}

/// The room the show happens in: floor, ceiling, walls. Beams stop where they would hit one.
public struct Room: Sendable {
    public enum Surface: Sendable { case floor, ceiling, back, front, left, right, air }

    public var width: Float
    public var ceiling: Float
    public var depth: Float
    public var back: Float
    public var side: Float = 2

    public init(stage: Stage, fixtures: [FixtureInfo]) {
        width = Float(stage.widthM)
        ceiling = Float(stage.ceilingM)
        depth = Float(stage.roomDepthM)
        back = min(-2.5, Float(fixtures.map(\.pos.y).min() ?? -1) - 1.5)
    }

    /// Where a beam from `p` along `d` ends: distance and surface (at most `maxLen`).
    public func hit(_ p: SIMD3<Float>, _ d: SIMD3<Float>, maxLen: Float = 30) -> (t: Float, surface: Surface) {
        var best: (Float, Surface) = (maxLen, .air)
        func consider(_ t: Float, _ s: Surface) { if t > 0, t < best.0 { best = (t, s) } }
        if d.z < -1e-3 { consider(-p.z / d.z, .floor) }
        if d.z > 1e-3 { consider((ceiling - p.z) / d.z, .ceiling) }
        if d.y > 1e-3 { consider((depth - p.y) / d.y, .front) }
        if d.y < -1e-3 { consider((back - p.y) / d.y, .back) }
        if d.x > 1e-3 { consider((width + side - p.x) / d.x, .right) }
        if d.x < -1e-3 { consider((-side - p.x) / d.x, .left) }
        return best
    }

    public static func normal(_ s: Surface) -> SIMD3<Float> {
        switch s {
        case .floor: [0, 0, 1]
        case .ceiling: [0, 0, -1]
        case .front: [0, -1, 0]
        case .back: [0, 1, 0]
        case .left: [1, 0, 0]
        case .right: [-1, 0, 0]
        case .air: [0, 1, 0]
        }
    }
}
