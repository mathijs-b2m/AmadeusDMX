// An orbit camera around the stage (drag to turn, scroll/pinch to zoom, ⌥-drag to pan) with presets that
// glide into place.
import Foundation
import simd

extension float4x4 {
    static func lookAt(eye: SIMD3<Float>, target: SIMD3<Float>, up: SIMD3<Float>) -> float4x4 {
        let f = simd_normalize(target - eye), s = simd_normalize(simd_cross(f, up)), u = simd_cross(s, f)
        return float4x4(columns: (
            SIMD4(s.x, u.x, -f.x, 0), SIMD4(s.y, u.y, -f.y, 0), SIMD4(s.z, u.z, -f.z, 0),
            SIMD4(-simd_dot(s, eye), -simd_dot(u, eye), simd_dot(f, eye), 1)))
    }

    static func perspective(fovY: Float, aspect: Float, near: Float, far: Float) -> float4x4 {
        let ys = 1 / tan(fovY / 2), xs = ys / aspect, zs = far / (near - far)
        return float4x4(columns: (SIMD4(xs, 0, 0, 0), SIMD4(0, ys, 0, 0), SIMD4(0, 0, zs, -1), SIMD4(0, 0, zs * near, 0)))
    }
}

struct CameraPose: Equatable {
    var target: SIMD3<Float>
    var yaw: Float       // around z; 0 = looking from the audience (+y) towards the stage
    var pitch: Float     // up from horizontal (radians)
    var distance: Float

    var eye: SIMD3<Float> {
        target + SIMD3(sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch)) * distance
    }

    static func lerp(_ a: CameraPose, _ b: CameraPose, _ k: Float) -> CameraPose {
        var dy = b.yaw - a.yaw
        while dy > .pi { dy -= 2 * .pi }
        while dy < -.pi { dy += 2 * .pi }
        return CameraPose(target: simd_mix(a.target, b.target, SIMD3(repeating: k)), yaw: a.yaw + dy * k,
                          pitch: a.pitch + (b.pitch - a.pitch) * k, distance: a.distance + (b.distance - a.distance) * k)
    }

    static func from(eye: SIMD3<Float>, target: SIMD3<Float>) -> CameraPose {
        let v = eye - target, d = simd_length(v)
        return CameraPose(target: target, yaw: atan2(v.x, v.y), pitch: asin(v.z / max(d, 1e-3)), distance: d)
    }
}

enum CameraPreset: String, CaseIterable, Identifiable {
    case frontOfHouse = "Front of House"
    case crowd = "In the Crowd"
    case drone = "Drone"
    case side = "Side"
    case dj = "DJ"
    case plan = "Plan"

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .frontOfHouse: "person.2"
        case .crowd: "person.3.sequence"
        case .drone: "airplane"
        case .side: "arrow.left.and.right"
        case .dj: "headphones"
        case .plan: "square.grid.3x3"
        }
    }

    /// The pose for a room (fits the rig, like the web visualiser's camera).
    func pose(width W: Float, top: Float, back: Float, ceiling: Float) -> CameraPose {
        let cx = W / 2
        let roomH = max(top + 1, min(ceiling, top + 4))
        let tz = max(1.3, roomH * 0.5)
        let dist = max(9.5, (roomH - tz + 0.5) * 2.2, (W / 2 + 2) * 1.6)
        switch self {
        case .frontOfHouse:
            return .from(eye: [cx, dist * 1.12, max(2.6, roomH * 0.38)], target: [cx, max(-0.5, back / 3), tz * 0.9])
        case .crowd:
            return .from(eye: [cx - W * 0.12, dist * 0.45, 1.7], target: [cx, back / 2, tz * 1.15])
        case .drone:
            return .from(eye: [cx + W * 0.45, dist * 1.25, roomH + dist * 0.75], target: [cx, back / 2.5, 1.0])
        case .side:
            return .from(eye: [cx + W * 0.5 + dist * 0.75, dist * 0.35, roomH * 0.55], target: [cx, back / 3, tz])
        case .dj:
            return .from(eye: [cx, back + 1.6, 2.6], target: [cx, 8, 1.8])
        case .plan:  // top-down (almost: straight down has no "up" for the camera)
            let span = max(W + 6, -back + 8)
            return CameraPose(target: [cx, back / 2 + 1, 0], yaw: 0, pitch: 1.45, distance: span * 1.25)
        }
    }
}
