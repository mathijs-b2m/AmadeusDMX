// The LED wall's picture, once for the whole app. The 3D stages show it on their wall, and the LED Wall Output puts
// it on a real one (a display: the HDMI into the LED processor). WallRenderer draws the picture on the CPU, once per
// show frame. Here it goes onto the GPU and the psychedelic shader is drawn in its place (the wall's level is light:
// each reader applies it, the stage to its light, the output to what it sends),
// so every one of them shows the same picture, also while no 3D stage is open (Perform mode).
//
// A big output (a 4K projector) gets a big picture: the composed picture is the size of the wall on the display, and
// the CPU draws the figures that fine, on a queue of its own (a 4K picture takes too long to draw beside the UI). When
// a picture takes longer than the show's frames allow, it draws coarser, and finer again when there is room.
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

    /// The composed picture, the wall's shape: twice the canvas (1280×720 for 16:9), or the output's wall when that
    /// is bigger, at most 4096 on its long side (the stage samples it with mipmaps, the output fits it to the wall).
    private(set) var picture: MTLTexture?
    /// The output's wall in pixels (the picture fitted into its rectangle), nil while there is no output.
    var outputPicture: (w: Int, h: Int)? {
        didSet { if outputPicture.map({ "\($0)" }) != oldValue.map({ "\($0)" }) { makePicture() } }
    }
    /// What the wall showed last.
    private(set) var state: WallState?

    /// The director's choice, or one scene tried out (the stage's LED wall menu).
    var force: WallScene = .auto
    /// How much finer than its units the CPU should draw (WallOutputLayout.pictureScale: the output's wall).
    var scale: Double = 1
    /// How fine it does draw: `scale`, unless that takes too long (adapt()).
    private(set) var drawScale: Double = 1
    private var scaleCap: Double = .infinity
    private var adaptedAt: CFTimeInterval = 0
    /// The wall's shape, width over height: the show's rig (its pixels), 16:9 without them.
    private(set) var aspect: Double = ScreenShape.defaultAspect { didSet { if aspect != oldValue { state = nil; makePicture() } } }
    /// Seconds the picture runs ahead of the show's clock (the output's lead).
    var lead: Double = 0

    private let painter = Painter()
    private var paintedSeq = 0
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

    private func makePicture() {
        guard let gpu = Self.gpu else { return }
        let c = WallRenderer.canvas(aspect)
        var w = c.w * 2, h = c.h * 2
        if let o = outputPicture, CGFloat(o.w) > w { w = CGFloat(o.w); h = w * c.h / c.w }
        let k = min(1, 4096 / max(w, h))
        let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba16Float, width: max(1, Int((w * k).rounded())),
                                                          height: max(1, Int((h * k).rounded())), mipmapped: true)
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
        adapt(now)
        // the next picture, drawn on the painter's queue; one at a time (a show frame that comes while it draws waits
        // for the next, its time passed on)
        if state == nil || f.t != lastShowT || now - updatedAt >= Self.updateInterval,
           painter.submit(.init(frame: f, hello: h, dt: pending, force: force, scale: drawScale, aspect: aspect)) {
            pending = 0
            updatedAt = now
            lastShowT = f.t
        }
        // the newest picture drawn, onto the GPU
        if let p = painter.take(after: paintedSeq) {
            paintedSeq = p.seq
            state = p.state
            if let bytes = p.bytes {
                if cpu?.width != p.w || cpu?.height != p.h {
                    let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .bgra8Unorm, width: p.w, height: p.h, mipmapped: false)
                    td.usage = .shaderRead
                    cpu = gpu.device.makeTexture(descriptor: td)
                }
                bytes.withUnsafeBytes { b in
                    cpu?.replace(region: MTLRegionMake2D(0, 0, p.w, p.h), mipmapLevel: 0, withBytes: b.baseAddress!, bytesPerRow: p.w * 4)
                }
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

    /// Draw coarser when a picture takes longer than the show's frames allow (40 a second: 25 ms, kept to 20), finer
    /// again when there is room: looked at once a second, a step at a time.
    private func adapt(_ now: CFTimeInterval) {
        let ms = painter.drawMs
        if now - adaptedAt >= 1 {
            adaptedAt = now
            if ms > 20, drawScale > 1 {
                scaleCap = max(1, ((drawScale * 0.75) * 2).rounded(.down) / 2)
            } else if ms > 0, ms < 9, scaleCap < scale {
                scaleCap += 0.5
            }
        }
        drawScale = max(1, min(scale, scaleCap))
    }

    /// Wait for the picture being drawn (development: the stage snapshot).
    func flush() { painter.queue.sync {} }

    private func compose(_ s: WallState, now: CFTimeInterval, cmd: MTLCommandBuffer) {
        guard let picture, let composePipe, s.psychedelic || cpu != nil else { return }
        let rp = MTLRenderPassDescriptor()
        rp.colorAttachments[0].texture = picture
        rp.colorAttachments[0].loadAction = .dontCare
        rp.colorAttachments[0].storeAction = .store
        guard let enc = cmd.makeRenderCommandEncoder(descriptor: rp) else { return }
        let p = s.palette + Array(repeating: s.palette.last ?? .one, count: max(0, 4 - s.palette.count))
        var wp = WallParams(info: [s.level, s.psychedelic ? 1 : 0, Float(now - startTime), Float(aspect)],
                            bands: SIMD4(s.bands.x, s.bands.y, s.bands.z, s.flash), layer: s.layer,
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

/// Draws the wall's pictures on a queue of its own (WallRenderer keeps the last picture: its trails fade on it).
private final class Painter: @unchecked Sendable {
    struct Job {
        var frame: Frame, hello: Hello, dt: Float, force: WallScene, scale: Double, aspect: Double
    }
    struct Picture {
        var seq: Int, state: WallState, bytes: Data?, w: Int, h: Int
    }

    let queue = DispatchQueue(label: "amadeus.wall.paint", qos: .userInteractive)
    private let lock = NSLock()
    private var renderer: WallRenderer?   // only on the queue
    private var busy = false, seq = 0, latest: Picture?, ms: Double = 0   // under the lock

    /// Milliseconds a picture takes to draw (smoothed); 0 before the first.
    var drawMs: Double { lock.withLock { ms } }

    /// Starts drawing the next picture; false while the last one is still being drawn.
    func submit(_ job: Job) -> Bool {
        guard lock.withLock({ busy ? false : { busy = true; return true }() }) else { return false }
        queue.async { [self] in
            if renderer.map({ $0.scale != CGFloat(job.scale) || $0.aspect != job.aspect }) ?? true {
                let next = WallRenderer(scale: CGFloat(job.scale), aspect: job.aspect)
                if let old = renderer { next.takeOver(from: old) }   // finer or coarser: no fade, no lost trails
                renderer = next
            }
            let r = renderer!
            r.force = job.force
            let t0 = CACurrentMediaTime()
            let s = r.update(frame: job.frame, hello: job.hello, dt: job.dt)
            let w = r.pixelWidth, h = r.pixelHeight
            let bytes = s.psychedelic ? nil : r.context.data.map { Data(bytes: $0, count: w * h * 4) }
            let took = (CACurrentMediaTime() - t0) * 1000
            lock.withLock {
                seq += 1
                latest = Picture(seq: seq, state: s, bytes: bytes, w: w, h: h)
                ms = ms == 0 ? took : ms * 0.8 + took * 0.2
                busy = false
            }
        }
        return true
    }

    /// The newest picture, if it is newer than `after`.
    func take(after: Int) -> Picture? {
        lock.withLock { latest.flatMap { $0.seq > after ? $0 : nil } }
    }
}

enum WallShaders {
    static let source = #"""
#include <metal_stdlib>
using namespace metal;

// info: x level, y psychedelic, z time, w aspect; bands.w: the flash; layer: x mask, y beat pulse, z beat phase, w beat parity
struct WallParams { float4 info; float4 bands; float4 layer; float4 pal[4]; };
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

// The overlay layer's mask, as a VJ lays one over the picture: where the beat's lift and the strobe's flash show.
// 0 the whole wall, 1 bars across, 2 bars down, 3 blocks, 4 a diamond opening with the beat, 5 slashes, 6 a frame,
// 7 the whole wall with the flash as the picture's negative. Bars, blocks and slashes swap places every beat.
float layer_mask(float2 uv, float kind, float aspect, float u, float parity) {
    float2 p = float2(uv.x * aspect, uv.y);   // in wall heights: the pattern is as coarse on any shape
    if (kind < 0.5 || kind > 6.5) return 1.0;
    if (kind < 1.5) return fmod(floor(p.y * 8.0) + parity, 2.0) < 0.5 ? 1.0 : 0.0;
    if (kind < 2.5) return fmod(floor(p.x * 8.0) + parity, 2.0) < 0.5 ? 1.0 : 0.0;
    if (kind < 3.5) return fmod(floor(p.x * 4.0) + floor(p.y * 4.0) + parity, 2.0) < 0.5 ? 1.0 : 0.0;
    if (kind < 4.5) {
        float d = abs(p.x - aspect * 0.5) + abs(p.y - 0.5), r = u * (aspect * 0.5 + 0.5);
        return abs(d - r) < 0.1 ? 1.0 : (d < r ? 0.3 : 0.0);
    }
    if (kind < 5.5) return fmod(floor((p.x + (parity > 0.5 ? p.y : -p.y)) * 5.0 + 40.0), 2.0) < 0.5 ? 1.0 : 0.0;
    float e = min(min(p.x, aspect - p.x), min(p.y, 1.0 - p.y));
    return e < 0.06 ? 1.0 : 0.0;
}

// the picture as the wall shows it, at full level: the CPU's drawing or the psychedelic shader (HDR: the stage's bloom
// sees the rings; the output clamps). The level is applied by who shows it.
fragment float4 wall_compose(FSOut in [[stage_in]], texture2d<float> tex [[texture(0)]], constant WallParams &w [[buffer(0)]]) {
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    float3 c = w.info.y > 0.5 ? psychedelic(in.uv, w.info.z, w.info.w > 0.0 ? w.info.w : 16.0 / 9.0, w.bands, w.pal) : tex.sample(smp, in.uv).rgb;
    // the overlay layer: on the beat the picture lifts through the mask (and a breath of colour with it); when the
    // lights strobe the mask flashes with them, near white with a touch of the palette, or as the picture's negative
    float aspect = w.info.w > 0.0 ? w.info.w : 16.0 / 9.0;
    float m = layer_mask(in.uv, w.layer.x, aspect, w.layer.z, w.layer.w);
    c = c * (1.0 + 0.6 * w.layer.y * m) + w.pal[1].rgb * (0.1 * w.layer.y * m);
    float3 white = mix(w.pal[0].rgb, float3(1.0), 0.8);
    float3 lit = w.layer.x > 6.5 ? white * (1.0 - saturate(c)) : white;
    c = mix(c, lit, saturate(w.bands.w) * m);
    return float4(c, 1);
}

// the output: the picture in the wall's rectangle (the viewport). info.x is a share of the wall's light (its level,
// the brightness ceiling, the fade): the picture is sRGB-encoded, so it goes out as that share of light, not of the
// encoded value (18% of the value would be 2% of the light: black on a wall that should glow faintly).
struct OutParams { float4 info; };   // x light 0..1, y time, z test card's moving bar on (1)

fragment float4 wall_output(FSOut in [[stage_in]], texture2d<float> tex [[texture(0)]], constant OutParams &o [[buffer(0)]]) {
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    float k = pow(saturate(o.info.x), 1.0 / 2.2);
    float3 c = clamp(tex.sample(smp, in.uv).rgb, 0.0, 1.0) * k;
    if (o.info.z > 0.5) {   // the test card: a bar crossing every two seconds shows tearing and dropped frames
        float x = fract(o.info.y * 0.5);
        if (abs(in.uv.x - x) < 0.006) c = float3(k);
    }
    return float4(c, 1);
}
"""#
}
