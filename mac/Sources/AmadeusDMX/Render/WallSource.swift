// The LED wall's picture, once for the whole app. The 3D stages show it on their wall, and the LED Wall Output puts
// it on a real one (a display: the HDMI into the LED processor). WallRenderer draws the picture on the CPU, once per
// show frame. Here it goes onto the GPU, the psychedelic shader is drawn in its place and the wall's level is applied,
// so every one of them shows the same picture, also while no 3D stage is open (Perform mode).
import AmadeusKit
import CoreGraphics
import Foundation
import Metal
import QuartzCore
import simd

@MainActor
final class WallSource {
    static let shared = WallSource()

    /// The GPU and the one queue every stage and the output draw with: the picture is written and read in order.
    static let gpu: (device: MTLDevice, queue: MTLCommandQueue)? = {
        guard let d = MTLCreateSystemDefaultDevice(), let q = d.makeCommandQueue() else { return nil }
        return (d, q)
    }()

    /// The composed picture: twice the canvas (1280×720 for 16:9), the wall's shape, at most 2560 on its long side
    /// (the stage samples it with mipmaps, the output fits it to the wall).
    private(set) var picture: MTLTexture?
    /// What the wall showed last.
    private(set) var state: WallState?

    /// The director's choice, or one scene tried out (the stage's LED wall menu).
    var force: WallScene = .auto { didSet { renderer.force = force } }
    /// How much finer than its units the CPU draws (WallOutputLayout.pictureScale: the output's wall).
    var scale: Double = 1 { didSet { if scale != oldValue { rebuild() } } }
    /// The wall's shape, width over height: the show's rig (its pixels), 16:9 without them.
    private(set) var aspect: Double = ScreenShape.defaultAspect { didSet { if aspect != oldValue { rebuild(); makePicture() } } }
    /// Seconds the picture runs ahead of the show's clock (the output's lead).
    var lead: Double = 0

    private var renderer = WallRenderer()
    private var cpu: MTLTexture?
    private var composePipe: MTLRenderPipelineState?
    private var lastShowT: Double?
    private var updatedAt: CFTimeInterval = 0
    private var composedAt: CFTimeInterval = 0
    private var lastTick: CFTimeInterval?
    private var pending: Float = 0
    private var dirty = false
    private let startTime = CACurrentMediaTime()
    static let updateInterval: CFTimeInterval = 0.05   // a still show keeps the wall alive (its fades, the equaliser)

    private init() {
        guard let gpu = Self.gpu else { return }
        do {
            let lib = try gpu.device.makeLibrary(source: WallShaders.source, options: nil)
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = lib.makeFunction(name: "wall_fs_vertex")
            d.fragmentFunction = lib.makeFunction(name: "wall_compose")
            d.colorAttachments[0].pixelFormat = .rgba16Float
            composePipe = try gpu.device.makeRenderPipelineState(descriptor: d)
        } catch { print("wall shaders: \(error)") }
        makePicture()
    }

    private func rebuild() {
        renderer = WallRenderer(scale: CGFloat(scale), aspect: aspect)
        renderer.force = force
        cpu = nil
        state = nil
    }

    private func makePicture() {
        guard let gpu = Self.gpu else { return }
        let c = WallRenderer.canvas(aspect), k = min(2, 2560 / max(c.w, c.h))
        let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba16Float, width: Int((c.w * k).rounded()),
                                                          height: Int((c.h * k).rounded()), mipmapped: true)
        td.usage = [.shaderRead, .renderTarget]
        td.storageMode = .private
        picture = gpu.device.makeTexture(descriptor: td)
        dirty = true
    }

    /// Brings the picture up to date for this moment of the show and encodes its drawing into `cmd` (only when it
    /// changed: every caller in the same display frame shares it). Returns what the wall shows, or nil without a
    /// show on a rig with an LED wall.
    @discardableResult
    func prepare(frame: Frame?, hello: Hello?, now: CFTimeInterval, cmd: MTLCommandBuffer) -> WallState? {
        let dt = Float(min(0.1, max(0, now - (lastTick ?? now))))
        lastTick = max(lastTick ?? now, now)
        // (a stage without a show, the rig editor's, leaves the picture to the ones that have one)
        guard let h = hello, h.screen, var f = frame, !f.lite, let gpu = Self.gpu else { return nil }
        aspect = h.screenAspect
        pending += dt
        if lead != 0 {   // ahead of the lights: the clock and the beat move on, the plan is known in advance
            f.t += lead
            if let bp = f.bp { f.bp = bp + lead * h.bpm / 60 }
        }
        if state == nil || f.t != lastShowT || now - updatedAt >= Self.updateInterval {
            let s = renderer.update(frame: f, hello: h, dt: pending)
            pending = 0
            updatedAt = now
            lastShowT = f.t
            state = s
            if !s.psychedelic, let data = renderer.context.data {
                let w = renderer.pixelWidth, ht = renderer.pixelHeight
                if cpu?.width != w || cpu?.height != ht {
                    let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .bgra8Unorm, width: w, height: ht, mipmapped: false)
                    td.usage = .shaderRead
                    cpu = gpu.device.makeTexture(descriptor: td)
                }
                cpu?.replace(region: MTLRegionMake2D(0, 0, w, ht), mipmapLevel: 0, withBytes: data, bytesPerRow: w * 4)
            }
            dirty = true
        }
        // psychedelic moves on the GPU's own clock: drawn again every display frame (not twice in one)
        if let s = state, dirty || (s.psychedelic && now - composedAt > 1.0 / 90) {
            compose(s, now: now, cmd: cmd)
            composedAt = now
            dirty = false
        }
        return state
    }

    private func compose(_ s: WallState, now: CFTimeInterval, cmd: MTLCommandBuffer) {
        guard let picture, let composePipe, s.psychedelic || cpu != nil else { return }
        let rp = MTLRenderPassDescriptor()
        rp.colorAttachments[0].texture = picture
        rp.colorAttachments[0].loadAction = .dontCare
        rp.colorAttachments[0].storeAction = .store
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rp) else { return }
        let p = s.palette + Array(repeating: s.palette.last ?? .one, count: max(0, 4 - s.palette.count))
        var wp = WallParams(info: [s.level, s.psychedelic ? 1 : 0, Float(now - startTime), Float(aspect)], bands: s.bands,
                            pal: (SIMD4(p[0], 1), SIMD4(p[1], 1), SIMD4(p[2], 1), SIMD4(p[3], 1)))
        enc.setRenderPipelineState(composePipe)
        enc.setFragmentTexture(cpu, index: 0)
        enc.setFragmentBytes(&wp, length: MemoryLayout<WallParams>.stride, index: 0)
        enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        enc.endEncoding()
        if picture.mipmapLevelCount > 1, let blit = cmd.makeBlitCommandEncoder() {   // the stage's wall, seen small
            blit.generateMipmaps(for: picture)
            blit.endEncoding()
        }
    }
}

enum WallShaders {
    static let source = #"""
#include <metal_stdlib>
using namespace metal;

struct WallParams { float4 info; float4 bands; float4 pal[4]; };   // info: x level, y psychedelic, z time, w aspect
struct FSOut { float4 pos [[position]]; float2 uv; };

vertex FSOut wall_fs_vertex(uint vid [[vertex_id]]) {
    float2 p = float2((vid << 1) & 2, vid & 2);
    FSOut o; o.pos = float4(p * 2.0 - 1.0, 0, 1); o.uv = float2(p.x, 1.0 - p.y); return o;
}

float3 psychedelic(float2 uv, float t, float aspect, float4 bands, constant float4 *pal) {
    float2 p = (uv - 0.5) * float2(aspect, 1.0) * 2.0;   // round on a wall of any shape
    // kaleidoscope: fold the angle into 6 slices, then a flowing plasma that the bass pushes outwards
    float a = atan2(p.y, p.x), r = length(p);
    float k = 3.14159 / 3.0;
    a = abs(fmod(a + t * 0.15 + 100.0 * k, 2.0 * k) - k);
    float2 q = float2(cos(a), sin(a)) * r;
    float bass = bands.x, mid = bands.y, hi = bands.z;
    float v = sin(q.x * 6.0 + t * 1.3) + sin(q.y * 7.0 - t * 0.9 + bass * 3.0)
            + sin((q.x + q.y) * 5.0 + t * 0.7) + sin(r * (10.0 + mid * 8.0) - t * 3.0 - bass * 6.0);
    float s = v * 0.25 + 0.5;
    float3 c0 = pal[0].rgb, c1 = pal[1].rgb, c2 = pal[2].rgb, c3 = pal[3].rgb;
    float3 c = s < 0.33 ? mix(c0, c1, s / 0.33) : s < 0.66 ? mix(c1, c2, (s - 0.33) / 0.33) : mix(c2, c3, (s - 0.66) / 0.34);
    float rings = smoothstep(0.85, 1.0, sin(r * 18.0 - t * 5.0 - bass * 8.0) * 0.5 + 0.5);
    c += rings * (0.4 + hi);
    c *= 0.55 + 0.6 * bass + 0.25 * smoothstep(1.2, 0.0, r);
    return c;
}

// the picture as the wall shows it: the CPU's drawing or the psychedelic shader, at the wall's level (HDR: the
// stage's bloom sees the rings; the output clamps)
fragment float4 wall_compose(FSOut in [[stage_in]], texture2d<float> tex [[texture(0)]], constant WallParams &w [[buffer(0)]]) {
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    float3 c = w.info.y > 0.5 ? psychedelic(in.uv, w.info.z, w.info.w > 0.0 ? w.info.w : 16.0 / 9.0, w.bands, w.pal) : tex.sample(smp, in.uv).rgb;
    return float4(c * w.info.x, 1);
}

// the output: the picture in the wall's rectangle (the viewport), under the brightness ceiling
struct OutParams { float4 info; };   // x brightness, y time, z test card's moving bar on (1)

fragment float4 wall_output(FSOut in [[stage_in]], texture2d<float> tex [[texture(0)]], constant OutParams &o [[buffer(0)]]) {
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    float3 c = clamp(tex.sample(smp, in.uv).rgb, 0.0, 1.0) * o.info.x;
    if (o.info.z > 0.5) {   // the test card: a bar crossing every two seconds shows tearing and dropped frames
        float x = fract(o.info.y * 0.5);
        if (abs(in.uv.x - x) < 0.006) c = float3(o.info.x);
    }
    return float4(c, 1);
}
"""#
}
