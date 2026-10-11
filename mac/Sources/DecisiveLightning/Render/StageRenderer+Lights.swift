// The lights of one frame: beams, spots on surfaces, lens flares and laser lines, from the feed's frame.
import DecisiveKit
import Metal
import MetalKit
import MetalPerformanceShaders
import QuartzCore
import simd

extension StageRenderer {
    func buildLights(_ inp: StageInput, _ frame: Frame?, _ s: Scenery, eye: SIMD3<Float>, t: Float,
                             beams: inout [BeamInstance], sprites: inout [SpriteInstance], decals: inout [DecalInstance],
                             lines: inout [LineInstance], ambient: inout SIMD3<Float>) {
        let room = s.room
        let nHeads = max(1, inp.fixtures.filter { $0.kind == .head }.count)
        let density = min(1, 4 / Float(nHeads).squareRoot())
        var lightSum = SIMD3<Float>(repeating: 0)

        func beam(_ p: SIMD3<Float>, _ d: SIMD3<Float>, spreadDeg: Float, color: SIMD3<Float>, intensity: Float,
                  maxLen: Float = 30, spot: Bool = true) {
            let (len, surf) = room.hit(p, d, maxLen: maxLen)
            let R = max(0.05, len * tan(spreadDeg * .pi / 360))
            beams.append(BeamInstance(apexLen: SIMD4(p, len), dirRadius: SIMD4(d, R), color: SIMD4(color, intensity),
                                      extra: [0.05, 0, 0, 0]))
            if spot && surf != .air {
                let n = Room.normal(surf)
                let squash = surf == .floor ? max(1, min(3, 1 / max(0.25, abs(d.z)))) : 1
                decals.append(DecalInstance(centerRadius: SIMD4(p + d * len, max(0.12, R * 1.3)), normal: SIMD4(n, Float(squash)),
                                            color: SIMD4(color, intensity * 0.9)))
            }
        }

        for (i, fx) in inp.fixtures.enumerated() {
            let p = SIMD3<Float>(Float(fx.pos.x), Float(fx.pos.y), Float(fx.pos.z))
            var dim: Float = 0, col = SIMD3<Float>(repeating: 1)
            if let frame, i < frame.fx.count {
                let v = frame.fx[i]
                if v.count >= 5 { dim = min(1, v[0]); col = SIMD3(v[1] + v[4], v[2] + v[4], v[3] + v[4]) }
            } else if highlight.contains(fx.id) {
                dim = 1
            }
            if highlight.contains(fx.id) { dim = max(dim, 0.9); col = [1, 1, 1] }
            let cm = max(col.max(), 1)
            col /= cm
            if dim <= 0.01 { continue }   // a dark fixture: its model shows it (dark glass in the lens)
            lightSum += col * dim

            switch fx.kind {
            case .head:
                let rest = fx.up.map { SIMD3<Float>(Float($0.x), Float($0.y), Float($0.z)) } ?? SIMD3(0, 0, -1)
                var d = frame.flatMap { i < $0.dirs.count ? $0.dirs[i] : nil } ?? simd_normalize(rest + SIMD3(0, 0.6, 0))
                d = simd_normalize(d)
                let name = frame.flatMap { i < $0.beam.count ? $0.beam[i] : nil } ?? "open"
                var rays = [d]
                if name.hasPrefix("prism") || name == "gobo_rotate" {
                    let side: SIMD3<Float> = abs(d.z) > 0.9 ? [1, 0, 0] : [0, 0, 1]
                    let a1 = simd_normalize(simd_cross(d, side)), a2 = simd_cross(d, a1)
                    let off: Float = name == "gobo_rotate" ? 0.035 : 0.07
                    rays = (0..<3).map { k in
                        let a = (name != "prism" ? t * 2.5 : 0) + Float(k) * 2.094
                        return simd_normalize(d + off * (cos(a) * a1 + sin(a) * a2))
                    }
                }
                let frost = name == "frost"
                let spread = frost ? max(Float(fx.beamWide), 25) * 1.2 : max(Float(fx.beamDeg) * 1.6, 2.5)
                let strength = Float(frost ? fx.outputWide : fx.output)
                var a = (frost ? dim * 0.45 : rays.count > 1 ? dim * 0.6 : dim) * density * strength * 0.75
                if highlight.contains(fx.id) { a = 2.5 }
                for r in rays { beam(p, r, spreadDeg: spread, color: col, intensity: a) }
                // the lens glows in the model; a flare only when the head points at the viewer (audience scanning),
                // smaller for the cells of a bar (many small lenses, not one big one)
                let toEye = simd_normalize(eye - p)
                let glare = pow(max(0, simd_dot(d, toEye)), 8)
                if glare > 0.05 {
                    let cellK = 1 / Float(max(1, fx.cells ?? 1)).squareRoot()
                    let size = min(0.08 + 0.3 * glare, max(0.1, simd_length(eye - p) * 0.035)) * cellK
                    sprites.append(SpriteInstance(centerSize: SIMD4(p, size), color: SIMD4(col, min(2.0, dim * glare * 2) * cellK),
                                                  extra: [glare > 0.6 ? 1 : 0.3, 0, 0, 0]))
                }
            case .laser:
                guard let beamsLZ = frame.flatMap({ i < $0.lz.count ? $0.lz[i] : nil }), !beamsLZ.isEmpty else {
                    if highlight.contains(fx.id) {
                        sprites.append(SpriteInstance(centerSize: SIMD4(p, 0.2), color: SIMD4(0, 1, 0.3, 2), extra: [1, 0, 0, 0]))
                    }
                    continue
                }
                let thin = 1 / max(1, (Float(beamsLZ.count) / 6).squareRoot())
                var hot = SIMD3<Float>(repeating: 0)
                for b in beamsLZ {
                    let a = b.bright * dim
                    if a <= 0.02 { continue }
                    let d = simd_normalize(b.dir)
                    let (len, surf) = room.hit(p, d, maxLen: 40)
                    let end = p + d * len
                    lines.append(LineInstance(p0Width: SIMD4(p, 0.05 * thin), p1: SIMD4(end, 0), color: SIMD4(b.color, a * 0.22 * thin)))
                    lines.append(LineInstance(p0Width: SIMD4(p, 0.008), p1: SIMD4(end, 0), color: SIMD4(b.color, a * 2.6)))
                    if surf != .air {
                        decals.append(DecalInstance(centerRadius: SIMD4(end, 0.06), normal: SIMD4(Room.normal(surf), 1),
                                                    color: SIMD4(b.color, a * 3)))
                    }
                    hot += b.color * a / Float(beamsLZ.count)
                }
                let hm = max(hot.max(), 0.01)
                sprites.append(SpriteInstance(centerSize: SIMD4(p, 0.22), color: SIMD4(hot / hm, min(1, dim) * 2.5), extra: [1, 0, 0, 0]))
            case .blinder:
                let bd = fx.dir.map { SIMD3<Float>(Float($0.x), Float($0.y), Float($0.z)) } ?? SIMD3(0, 1, 0.12)
                beam(p, simd_normalize(bd), spreadDeg: 70, color: col, intensity: dim * 0.5, maxLen: 5, spot: false)
                sprites.append(SpriteInstance(centerSize: SIMD4(p + simd_normalize(bd) * 0.02, 0.18 * (1 + dim)),
                                              color: SIMD4(simd_mix(col, [1, 0.95, 0.85], SIMD3(repeating: 0.5)), dim * 0.9),
                                              extra: [0.3, 0, 0, 0]))
            case .strobe:
                // one blinding white flash from the face, flooding the room for a moment
                let sd = fx.dir.map { SIMD3<Float>(Float($0.x), Float($0.y), Float($0.z)) } ?? SIMD3(0, 1, 0.14)
                beam(p, simd_normalize(sd), spreadDeg: 100, color: [1, 1, 1], intensity: dim * 0.9, maxLen: 8)
                sprites.append(SpriteInstance(centerSize: SIMD4(p, 0.35 * (1 + 1.5 * dim)), color: SIMD4(0.9, 0.95, 1, dim * 3),
                                              extra: [1, 0, 0, 0]))
                lightSum += SIMD3(repeating: dim * 8)   // the whole room lights up
            case .par, .other:
                // a bar's cells share its light: many small beams, not many full-strength ones
                let cellK: Float = (fx.cells ?? 1) > 1 ? 1.6 / Float(fx.cells!) : 1
                let pd = fx.dir.map { SIMD3<Float>(Float($0.x), Float($0.y), Float($0.z)) } ?? SIMD3(0, 0.18, 1)
                beam(p, simd_normalize(pd), spreadDeg: min(Float(fx.beamDeg), 40), color: col, intensity: dim * 0.8 * cellK,
                     maxLen: 3.5)
                if (fx.cells ?? 1) <= 1 {   // a bar's cells glow in its model; a single par gets a soft halo
                    sprites.append(SpriteInstance(centerSize: SIMD4(p, 0.16), color: SIMD4(col, dim * 0.35), extra: .zero))
                }
            }
        }
        ambient = lightSum / Float(max(1, inp.fixtures.count)) * 0.8
    }
}
