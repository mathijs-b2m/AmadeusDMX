// The Metal stage: scenery, volumetric beams, spots, lasers, flares and the LED wall into an HDR target,
// then bloom (MPS blur at half and quarter resolution) and a tone curve into the window.
import AmadeusKit
import AppKit
import Metal
import MetalKit
import MetalPerformanceShaders
import QuartzCore
import simd

/// What the stage shows: a rig (from a running show's hello, or from a set file as a preview).
struct StageInput {
    var key: String               // changes when the rig changes (rebuild the scenery)
    var fixtures: [FixtureInfo]
    var stage: Stage
    var screen: Bool
    var hello: Hello?
    var trusses: [Truss] = []
    var selected: Set<String> = []   // "truss:ID" / "fixture:ID" (rig editor)
    var keepCamera = false           // the editor rebuilds the scene on every change: leave the camera alone
    var zones: [Zone] = []           // drawn translucent (rig editor)
    var drawings: [FloorDrawing] = []  // a venue's light plots on the floor (rig editor)
}

/// A drawing lying on the stage floor (a page of a venue's light plot under the rig, rig editor).
struct FloorDrawing {
    var key: String                  // its page: the texture is made once
    var image: CGImage
    var corners: [SIMD2<Float>]      // the page's top-left, top-right, bottom-right, bottom-left on the rig (m)
    var opacity: Float
}

extension StageInput {
    /// Where the trusses and fixtures are, for the key: a truss moved (same count) is a different rig to draw.
    static func layout(_ fixtures: [FixtureInfo], _ trusses: [Truss]) -> Int {
        var h = Hasher()
        h.combine(trusses)
        for f in fixtures {
            h.combine(f.id); h.combine(f.pos); h.combine(f.rot); h.combine(f.mount); h.combine(f.up); h.combine(f.truss)
        }
        return h.finalize()
    }
}

@MainActor
final class StageRenderer: NSObject, MTKViewDelegate {
    let device: MTLDevice
    let queue: MTLCommandQueue
    var solidPipe, beamPipe, spritePipe, decalPipe, linePipe, wallPipe, compositePipe, zonePipe, drawingPipe: MTLRenderPipelineState!
    var goboBeamPipe, goboDecalPipe: MTLRenderPipelineState!
    var zoneBuffer: MTLBuffer?
    var zoneCount = 0
    var zoneEdges: [LineInstance] = []
    var solidDepth, lightDepth: MTLDepthStencilState!
    var coneBuffer: MTLBuffer!
    var coneCount = 0
    var cappedConeBuffer: MTLBuffer!
    var cappedConeCount = 0
    // gobos: the hello's pictures as texture slices, and per head how far its gobo has turned (radians) and the
    // direction its picture's x axis lies in (kept while the beam points along the mount, where it is undefined)
    static let goboSize = 128, maxGobos = 256
    var goboTexture: MTLTexture?
    var goboKeys: [String] = []
    var goboSlices = 0
    var goboTurn: [String: Float] = [:]
    var goboAxis: [String: SIMD3<Float>] = [:]
    var goboT: Float = 0
    var sceneryBuffer: MTLBuffer?
    var sceneryCount = 0
    var wallBuffer: MTLBuffer?
    // the drawings on the floor: their pages as textures (kept per page), and what to draw this rig
    var drawingTextures: [String: MTLTexture] = [:]
    var drawingDraws: [(buffer: MTLBuffer, count: Int, texture: MTLTexture, opacity: Float)] = []
    var wallTexture: MTLTexture!
    var hdr, depth, halfA, halfB, quarterA, quarterB: MTLTexture?
    var scenery: Scenery?
    var sceneryKey = ""
    let wall = WallRenderer()

    // inputs
    var input: (() -> (StageInput?, Frame?))?
    var highlight: Set<String> = [] { didSet { wake() } }
    var haze: Float = 0.75 { didSet { wake() } }
    // smoke machines: each one's plume (how much, how long since it last fired) and the haze they built up
    var fogPuffs: [String: SIMD2<Float>] = [:]
    var roomFog: Float = 0
    var fogT: Float = 0
    var exposure: Float = 1.0 { didSet { wake() } }

    static let wallInterval: CFTimeInterval = 0.05
    private var wallOut: WallOutput?
    private var wallAt: CFTimeInterval = 0
    private var wallShowT: Double?
    private var wallDt: Float = 0

    /// Every frame's GPU time (seconds), for the power meter.
    static var onGPUTime: ((Double) -> Void)?

    // idle: with nothing changing (no show frames, no camera move, no input) the stage draws only a few frames a
    // second, so an open window with no show doesn't keep the GPU (and the window server) busy
    // a running show changes 40 times a second (the engine's frame rate): drawn at 40; at 60 only while the camera
    // moves (you, an animation, auto-orbit), which is where smoothness shows
    static let activeFPS = 60, showFPS = 40, idleFPS = 4
    static let idleAfter: CFTimeInterval = 1.5, interactionFor: CFTimeInterval = 2
    private var lastActive = CACurrentMediaTime()
    private var lastInteraction = 0.0
    private var lastShowT: Double?
    private weak var drawingView: MTKView?

    // adaptive resolution: the scene renders at a share of the window's pixels, lowered while the GPU takes too long
    // per frame (beams and bloom are soft: it barely shows) and raised again when there's room
    static let gpuBudgetMs = 9.0, gpuRoomMs = 4.5, minScale: CGFloat = 0.5
    private(set) var renderScale: CGFloat = 1
    private var gpuMs = 0.0
    private var scaledAt = CACurrentMediaTime()

    /// Something changed (input, a setting): draw at full rate again.
    func wake() {
        lastActive = CACurrentMediaTime()
        lastInteraction = lastActive
        if let v = drawingView, v.preferredFramesPerSecond != Self.activeFPS { v.preferredFramesPerSecond = Self.activeFPS }
    }

    private func adaptScale(_ now: CFTimeInterval) {
        guard now - scaledAt > 1 else { return }
        scaledAt = now
        if gpuMs > Self.gpuBudgetMs && renderScale > Self.minScale {
            renderScale = max(Self.minScale, renderScale * 0.85)
        } else if gpuMs < Self.gpuRoomMs && renderScale < 1 {
            renderScale = min(1, renderScale * 1.1)
        }
    }
    var autoExposure: Float = 1.0
    lazy var statsTexture: MTLTexture? = {
        let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba32Float, width: 1, height: 1, mipmapped: false)
        d.usage = [.shaderRead, .shaderWrite]
        return device.makeTexture(descriptor: d)
    }()
    lazy var statsBuf: MTLBuffer? = device.makeBuffer(length: 16, options: .storageModeShared)
    var autoOrbit = false { didSet { wake() } }
    /// Light the room so the rig is easy to see (rig pages, no show).
    var workLight: Float = 0 { didSet { wake() } }
    var wallScene: WallScene { get { wall.force } set { wall.force = newValue; wake() } }
    /// What the wall shows right now (for the UI).
    private(set) var wallNow: WallScene = .off

    // camera
    private(set) var pose = CameraPose(target: [3, -1, 2], yaw: 0, pitch: 0.15, distance: 12)
    var goal: CameraPose?
    private(set) var preset: CameraPreset = .frontOfHouse
    var lastTime = CACurrentMediaTime()
    var startTime = CACurrentMediaTime()
    /// Development (StageSnapshot): draw into this texture on a clock of its own instead of the window's.
    var snapshot: (target: MTLTexture, now: CFTimeInterval)?
    var viewSize = CGSize(width: 1, height: 1)

    init?(view: MTKView) {
        guard let device = MTLCreateSystemDefaultDevice(), let queue = device.makeCommandQueue() else { return nil }
        self.device = device
        self.queue = queue
        super.init()
        view.device = device
        view.colorPixelFormat = .bgra8Unorm_srgb
        view.depthStencilPixelFormat = .invalid
        // 60 fps: the engine sends 40 frames a second, more only costs the window server (glass over a moving
        // picture is re-blurred every frame) and can starve the audio of a DJ app on the same Mac
        view.preferredFramesPerSecond = 60
        view.clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        do { try buildPipelines(view) } catch { print("stage shaders: \(error)"); return nil }
        buildCone()
        let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .bgra8Unorm, width: WallRenderer.W,
                                                          height: WallRenderer.H, mipmapped: false)
        td.usage = .shaderRead
        wallTexture = device.makeTexture(descriptor: td)
        view.delegate = self
    }

    // MARK: camera

    func setPreset(_ p: CameraPreset, animated: Bool = true) {
        wake()
        preset = p
        guard let s = scenery else { return }
        let target = p.pose(width: s.room.width, top: s.top, back: s.room.back, ceiling: s.room.ceiling)
        if animated { goal = target } else { pose = target; goal = nil }
    }

    /// The ray through a point of the view (in points, origin bottom-left like AppKit), for picking.
    func ray(at p: CGPoint, in size: CGSize) -> (origin: SIMD3<Float>, dir: SIMD3<Float>) {
        let eye = pose.eye, f = simd_normalize(pose.target - eye)
        let right = simd_normalize(simd_cross(f, [0, 0, 1])), up = simd_cross(right, f)
        let aspect = Float(max(1, size.width) / max(1, size.height)), t = tan(Float(0.75) / 2)
        let nx = Float(p.x / max(1, size.width)) * 2 - 1, ny = Float(p.y / max(1, size.height)) * 2 - 1
        return (eye, simd_normalize(f + right * (nx * t * aspect) + up * (ny * t)))
    }

    func orbit(dx: Float, dy: Float) {
        wake()
        goal = nil
        if fly { look(dx: dx, dy: dy); return }
        pose.yaw -= dx * 0.005
        pose.pitch = min(1.45, max(-0.05, pose.pitch + dy * 0.004))
    }

    func zoom(_ factor: Float) {
        wake()
        goal = nil
        if fly { move(forward: (1 - factor) * 6); return }
        pose.distance = min(120, max(0.6, pose.distance * factor))
    }

    // MARK: flying

    /// Fly mode: you are the camera. Drag turns your head, scroll/pinch and the keys move you through the room.
    var fly = false {
        didSet {
            guard fly != oldValue else { return }
            wake()
            goal = nil
            // keep the eye where it is; only the point it turns around changes: right in front of you while flying
            // (looking around turns your head), a stage-sized step ahead again when orbiting
            setDistance(fly ? Self.flyReach : max(6, simd_length(pose.target - pose.eye)))
        }
    }
    static let flyReach: Float = 1

    /// Keys held down (key codes, by position so other layouts fly the same), read every frame.
    var heldKeys: Set<UInt16> = [] { didSet { if !heldKeys.isEmpty { wake() } } }

    private func setDistance(_ d: Float) {
        let eye = pose.eye, dir = simd_normalize(pose.target - eye)
        pose.distance = d
        pose.target = eye + dir * d
    }

    /// Turn the head: the eye stays put, the view swings. Drag right looks right, drag up looks up.
    private func look(dx: Float, dy: Float) {
        let eye = pose.eye
        pose.yaw += dx * 0.004
        pose.pitch = min(1.5, max(-1.5, pose.pitch - dy * 0.004))
        let dir = SIMD3(sin(pose.yaw) * cos(pose.pitch), cos(pose.yaw) * cos(pose.pitch), sin(pose.pitch))
        pose.target = eye - dir * pose.distance
    }

    /// Move the eye (and what it looks at) in metres: forward along the floor, right, up.
    func move(forward: Float = 0, right: Float = 0, up: Float = 0) {
        wake()
        goal = nil
        let fwd = SIMD3<Float>(-sin(pose.yaw), -cos(pose.yaw), 0), r = SIMD3<Float>(-cos(pose.yaw), sin(pose.yaw), 0)
        pose.target += fwd * forward + r * right + SIMD3(0, 0, up)
        let floor: Float = 0.15  // never below the floor
        let z = pose.eye.z
        if z < floor { pose.target.z += floor - z }
    }

    // key codes (ANSI positions)
    enum Key {
        static let w: UInt16 = 13, a: UInt16 = 0, s: UInt16 = 1, d: UInt16 = 2, q: UInt16 = 12, e: UInt16 = 14
        static let left: UInt16 = 123, right: UInt16 = 124, down: UInt16 = 125, up: UInt16 = 126
        static let plus: UInt16 = 24, minus: UInt16 = 27, keypadPlus: UInt16 = 69, keypadMinus: UInt16 = 78
        static let movement: Set<UInt16> = [w, a, s, d, q, e, left, right, down, up, plus, minus, keypadPlus, keypadMinus]
    }

    /// Walk/fly with the held keys: WASD or arrows move, Q/E go down/up, +/− zoom (or move forward/back while
    /// flying). ⇧ is faster, ⌥ slower.
    private func applyHeldKeys(_ dt: Float) {
        guard !heldKeys.isEmpty else { return }
        func axis(_ pos: [UInt16], _ neg: [UInt16]) -> Float {
            (pos.contains(where: heldKeys.contains) ? 1 : 0) - (neg.contains(where: heldKeys.contains) ? 1 : 0)
        }
        let mods = NSEvent.modifierFlags
        let speed: Float = 4 * (mods.contains(.shift) ? 3 : 1) * (mods.contains(.option) ? 0.3 : 1) * dt
        let fwd = axis([Key.w, Key.up], [Key.s, Key.down]), side = axis([Key.d, Key.right], [Key.a, Key.left])
        let lift = axis([Key.e], [Key.q]), zoomIn = axis([Key.plus, Key.keypadPlus], [Key.minus, Key.keypadMinus])
        if fly {
            move(forward: (fwd + zoomIn) * speed, right: side * speed, up: lift * speed)
        } else {
            move(forward: fwd * speed, right: side * speed, up: lift * speed)
            if zoomIn != 0 { zoom(1 - zoomIn * min(0.5, speed / max(1, pose.distance) * 1.5)) }
        }
    }

    func pan(dx: Float, dy: Float) {
        wake()
        goal = nil
        let eye = pose.eye, f = simd_normalize(pose.target - eye)
        let r = simd_normalize(simd_cross(f, [0, 0, 1])), u = simd_cross(r, f)
        let k = pose.distance * 0.0012
        pose.target += (-r * dx + u * dy) * k
    }

    // MARK: drawing

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        viewSize = size
        hdr = nil
    }

    func ensureTargets(_ size: CGSize) {
        let w = max(1, Int(size.width)), h = max(1, Int(size.height))
        if let t = hdr, t.width == w, t.height == h { return }
        func tex(_ f: MTLPixelFormat, _ w: Int, _ h: Int, _ usage: MTLTextureUsage) -> MTLTexture? {
            let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: f, width: max(1, w), height: max(1, h), mipmapped: false)
            d.usage = usage
            d.storageMode = .private
            return device.makeTexture(descriptor: d)
        }
        let rw: MTLTextureUsage = [.shaderRead, .shaderWrite, .renderTarget]
        hdr = tex(.rgba16Float, w, h, rw)
        depth = tex(.depth32Float, w, h, .renderTarget)
        halfA = tex(.rgba16Float, w / 2, h / 2, rw); halfB = tex(.rgba16Float, w / 2, h / 2, rw)
        quarterA = tex(.rgba16Float, w / 4, h / 4, rw); quarterB = tex(.rgba16Float, w / 4, h / 4, rw)
    }

    func draw(in view: MTKView) {
        let now = snapshot?.now ?? CACurrentMediaTime()
        let dt = Float(min(0.1, now - lastTime))
        lastTime = now
        let (inp, frame) = input?() ?? (nil, nil)
        drawingView = view
        if let f = frame, f.t != lastShowT { lastShowT = f.t; lastActive = now }  // the show moves
        if goal != nil || autoOrbit || !heldKeys.isEmpty || (inp.map { $0.key != sceneryKey } ?? false) { lastActive = now; lastInteraction = now }
        let moving = now - lastInteraction < Self.interactionFor
        let fps = now - lastActive > Self.idleAfter ? Self.idleFPS : moving ? Self.activeFPS : Self.showFPS
        if view.preferredFramesPerSecond != fps { view.preferredFramesPerSecond = fps }
        if Self.gpuStats, let f = frame, f.t != Self.lastFrameT { Self.lastFrameT = f.t; Self.newFrames += 1 }
        if let inp, inp.key != sceneryKey { rebuildScenery(inp) }
        if let g = goal {
            pose = .lerp(pose, g, 1 - exp(-dt * 4))
            if abs(pose.distance - g.distance) < 0.01 && simd_length(pose.target - g.target) < 0.01 { pose = g; goal = nil }
        }
        if !heldKeys.isEmpty, !(view.window?.isKeyWindow ?? false) { heldKeys = [] }  // keyUp went elsewhere
        applyHeldKeys(dt)
        if autoOrbit && goal == nil && !fly { pose.yaw += dt * 0.05 }

        adaptScale(now)
        ensureTargets(CGSize(width: (view.drawableSize.width * renderScale).rounded(),
                             height: (view.drawableSize.height * renderScale).rounded()))
        guard let hdr, let depth, let halfA, let halfB, let quarterA, let quarterB,
              let target = snapshot?.target ?? view.currentDrawable?.texture, let cmd = queue.makeCommandBuffer() else { return }

        // camera
        let eye = pose.eye
        let aspect = Float(max(1, view.drawableSize.width) / max(1, view.drawableSize.height))
        let viewM = float4x4.lookAt(eye: eye, target: pose.target, up: [0, 0, 1])
        let proj = float4x4.perspective(fovY: 0.75, aspect: aspect, near: 0.1, far: 300)
        let f = simd_normalize(pose.target - eye), right = simd_normalize(simd_cross(f, [0, 0, 1])), up = simd_cross(right, f)

        // lights
        var beams: [BeamInstance] = [], sprites: [SpriteInstance] = [], decals: [DecalInstance] = [], lines: [LineInstance] = []
        var goboBeams: [GoboBeamInstance] = [], goboDecals: [GoboDecalInstance] = []
        var ambient = SIMD3<Float>(repeating: 0)
        if let pics = inp?.hello?.gobos, pics.map(\.key) != goboKeys || goboTexture == nil { buildGobos(pics) }
        if let inp, let s = scenery {
            buildLights(inp, frame, s, eye: eye, t: Float(now - startTime), beams: &beams, sprites: &sprites,
                        decals: &decals, lines: &lines, goboBeams: &goboBeams, goboDecals: &goboDecals, ambient: &ambient)
        }

        var u = Uniforms(viewProj: proj * viewM, camPos: SIMD4(eye, 1), camRight: SIMD4(right, 0), camUp: SIMD4(up, 0),
                         params: [Float(now - startTime), haze * (1 + roomFog), exposure, 0.9], ambient: SIMD4(ambient, workLight))

        // the wall's picture
        var wp = WallParams(info: .zero, bands: .zero, pal: (.zero, .zero, .zero, .zero))
        if let inp, let h = inp.hello, let frame, scenery?.wall != nil {
            // the wall's picture is drawn on the CPU, once per show frame (the engine's 40 a second: its figures move
            // with the music as fluently as the lights); while the show stands still, wallInterval keeps it alive
            wallDt += dt
            if wallOut == nil || frame.t != wallShowT || now - wallAt >= Self.wallInterval {
                let o = wall.update(frame: frame, hello: h, dt: wallDt)
                wallOut = o
                wallAt = now
                wallShowT = frame.t
                wallDt = 0
                if !o.psychedelic, let data = wall.context.data {
                    wallTexture.replace(region: MTLRegionMake2D(0, 0, WallRenderer.W, WallRenderer.H), mipmapLevel: 0,
                                        withBytes: data, bytesPerRow: WallRenderer.W * 4)
                }
            }
            let out = wallOut!
            wallNow = out.scene
            let p = out.palette + Array(repeating: out.palette.last ?? .one, count: max(0, 4 - out.palette.count))
            wp = WallParams(info: [out.level, out.psychedelic ? 1 : 0, Float(now - startTime), 0], bands: out.bands,
                            pal: (SIMD4(p[0], 1), SIMD4(p[1], 1), SIMD4(p[2], 1), SIMD4(p[3], 1)))
            // the wall lights the stage around it a little
            ambient += (out.psychedelic ? (p[0] + p[1]) * 0.5 : SIMD3(repeating: 0.4)) * out.level * 0.08
            u.ambient = SIMD4(ambient, workLight)
        }

        // scene → HDR
        let rp = MTLRenderPassDescriptor()
        rp.colorAttachments[0].texture = hdr
        rp.colorAttachments[0].loadAction = .clear
        rp.colorAttachments[0].clearColor = MTLClearColor(red: 0.004, green: 0.004, blue: 0.007, alpha: 1)
        rp.colorAttachments[0].storeAction = .store
        rp.depthAttachment.texture = depth
        rp.depthAttachment.loadAction = .clear
        rp.depthAttachment.clearDepth = 1
        rp.depthAttachment.storeAction = .dontCare
        if let enc = cmd.makeRenderCommandEncoder(descriptor: rp) {
            enc.setCullMode(.none)
            enc.setVertexBytes(&u, length: MemoryLayout<Uniforms>.stride, index: 1)
            enc.setFragmentBytes(&u, length: MemoryLayout<Uniforms>.stride, index: 1)
            if let sb = sceneryBuffer {
                enc.setRenderPipelineState(solidPipe)
                enc.setDepthStencilState(solidDepth)
                enc.setVertexBuffer(sb, offset: 0, index: 0)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: sceneryCount)
            }
            // the fixtures' moving parts and lenses: where the beams point, in the colours they play
            if let s = scenery, let inp {
                let parts = s.models.dynamic(fixtures: inp.fixtures, frame: frame, highlight: highlight)
                if !parts.isEmpty, let buf = device.makeBuffer(bytes: parts, length: parts.count * MemoryLayout<SolidVertex>.stride) {
                    enc.setRenderPipelineState(solidPipe)
                    enc.setDepthStencilState(solidDepth)
                    enc.setVertexBuffer(buf, offset: 0, index: 0)
                    enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: parts.count)
                }
            }
            if let wb = wallBuffer {
                enc.setRenderPipelineState(wallPipe)
                enc.setDepthStencilState(solidDepth)
                enc.setVertexBuffer(wb, offset: 0, index: 0)
                enc.setFragmentTexture(wallTexture, index: 0)
                enc.setFragmentBytes(&wp, length: MemoryLayout<WallParams>.stride, index: 3)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6)
            }
            // the drawings on the floor: over it, under everything standing on it (they don't hide the spots)
            for d in drawingDraws {
                var params = SIMD4<Float>(d.opacity, Self.drawingBrightness, 0, 0)
                enc.setRenderPipelineState(drawingPipe)
                enc.setDepthStencilState(lightDepth)
                enc.setVertexBuffer(d.buffer, offset: 0, index: 0)
                enc.setFragmentTexture(d.texture, index: 0)
                enc.setFragmentBytes(&params, length: MemoryLayout<SIMD4<Float>>.stride, index: 3)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: d.count)
            }
            enc.setDepthStencilState(lightDepth)
            if !decals.isEmpty {
                enc.setRenderPipelineState(decalPipe)
                enc.setVertexBytes(decals, length: decals.count * MemoryLayout<DecalInstance>.stride, index: 2)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6, instanceCount: decals.count)
            }
            if !goboDecals.isEmpty, let tex = goboTexture {
                enc.setRenderPipelineState(goboDecalPipe)
                let buf = device.makeBuffer(bytes: goboDecals, length: goboDecals.count * MemoryLayout<GoboDecalInstance>.stride)
                enc.setVertexBuffer(buf, offset: 0, index: 2)
                enc.setFragmentBuffer(buf, offset: 0, index: 2)
                enc.setFragmentTexture(tex, index: 0)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6, instanceCount: goboDecals.count)
            }
            if !goboBeams.isEmpty, let tex = goboTexture {
                enc.setRenderPipelineState(goboBeamPipe)
                enc.setVertexBuffer(cappedConeBuffer, offset: 0, index: 0)
                let buf = device.makeBuffer(bytes: goboBeams, length: goboBeams.count * MemoryLayout<GoboBeamInstance>.stride)
                enc.setVertexBuffer(buf, offset: 0, index: 2)
                enc.setFragmentBuffer(buf, offset: 0, index: 2)
                enc.setFragmentTexture(tex, index: 0)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: cappedConeCount, instanceCount: goboBeams.count)
            }
            if !beams.isEmpty {
                enc.setRenderPipelineState(beamPipe)
                enc.setVertexBuffer(coneBuffer, offset: 0, index: 0)
                let buf = device.makeBuffer(bytes: beams, length: beams.count * MemoryLayout<BeamInstance>.stride)
                enc.setVertexBuffer(buf, offset: 0, index: 2)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: coneCount, instanceCount: beams.count)
            }
            if !lines.isEmpty {
                enc.setRenderPipelineState(linePipe)
                let buf = device.makeBuffer(bytes: lines, length: lines.count * MemoryLayout<LineInstance>.stride)
                enc.setVertexBuffer(buf, offset: 0, index: 2)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6, instanceCount: lines.count)
            }
            if let zb = zoneBuffer {
                enc.setRenderPipelineState(zonePipe)
                enc.setVertexBuffer(zb, offset: 0, index: 0)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: zoneCount)
            }
            if !zoneEdges.isEmpty {
                enc.setRenderPipelineState(linePipe)
                let buf = device.makeBuffer(bytes: zoneEdges, length: zoneEdges.count * MemoryLayout<LineInstance>.stride)
                enc.setVertexBuffer(buf, offset: 0, index: 2)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6, instanceCount: zoneEdges.count)
            }
            if !sprites.isEmpty {
                enc.setRenderPipelineState(spritePipe)
                let buf = device.makeBuffer(bytes: sprites, length: sprites.count * MemoryLayout<SpriteInstance>.stride)
                enc.setVertexBuffer(buf, offset: 0, index: 2)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6, instanceCount: sprites.count)
            }
            enc.endEncoding()
        }

        // bloom
        let scale = MPSImageBilinearScale(device: device)
        scale.encode(commandBuffer: cmd, sourceTexture: hdr, destinationTexture: halfA)
        MPSImageGaussianBlur(device: device, sigma: 4).encode(commandBuffer: cmd, sourceTexture: halfA, destinationTexture: halfB)
        scale.encode(commandBuffer: cmd, sourceTexture: hdr, destinationTexture: quarterA)
        MPSImageGaussianBlur(device: device, sigma: 9).encode(commandBuffer: cmd, sourceTexture: quarterA, destinationTexture: quarterB)

        // auto exposure: the average light of this frame (read back a frame later) steers the exposure, like a camera
        if let stats = statsTexture, let statsBuf {
            MPSImageStatisticsMean(device: device).encode(commandBuffer: cmd, sourceTexture: quarterA, destinationTexture: stats)
            if let blit = cmd.makeBlitCommandEncoder() {
                blit.copy(from: stats, sourceSlice: 0, sourceLevel: 0, sourceOrigin: MTLOrigin(), sourceSize: MTLSize(width: 1, height: 1,
                          depth: 1), to: statsBuf, destinationOffset: 0, destinationBytesPerRow: 16, destinationBytesPerImage: 16)
                blit.endEncoding()
            }
        }
        let m = statsBuf.map { $0.contents().bindMemory(to: Float.self, capacity: 4) }
        if let m {
            let lum = max(0, 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2])
            let target = lum.isFinite ? min(1, max(0.3, 0.22 / max(lum, 1e-4))) : 1
            autoExposure += (target - autoExposure) * min(1, dt * (target < autoExposure ? 4 : 1.2))  // close fast, open slowly
            u.params.z = exposure * autoExposure
            Self.lastLum = lum; Self.lastExposure = autoExposure
        }

        // composite → window
        let fp = MTLRenderPassDescriptor()
        fp.colorAttachments[0].texture = target
        fp.colorAttachments[0].loadAction = .dontCare
        fp.colorAttachments[0].storeAction = .store
        if let enc = cmd.makeRenderCommandEncoder(descriptor: fp) {
            enc.setRenderPipelineState(compositePipe)
            enc.setFragmentTexture(hdr, index: 0)
            enc.setFragmentTexture(halfB, index: 1)
            enc.setFragmentTexture(quarterB, index: 2)
            enc.setFragmentBytes(&u, length: MemoryLayout<Uniforms>.stride, index: 1)
            enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
            enc.endEncoding()
        }
        if snapshot == nil, let drawable = view.currentDrawable { cmd.present(drawable) }
        if Self.gpuStats, Date().timeIntervalSince(Self.nanCheckAt) > 3, let blit = cmd.makeBlitCommandEncoder() {
            // development: count invalid (NaN/inf) pixels in the light buffer
            Self.nanCheckAt = Date()
            let bytes = hdr.width * hdr.height * 8
            if let buf = device.makeBuffer(length: bytes, options: .storageModeShared) {
                blit.copy(from: hdr, sourceSlice: 0, sourceLevel: 0, sourceOrigin: MTLOrigin(), sourceSize: MTLSize(width: hdr.width,
                          height: hdr.height, depth: 1), to: buf, destinationOffset: 0, destinationBytesPerRow: hdr.width * 8,
                          destinationBytesPerImage: bytes)
                blit.endEncoding()
                cmd.addCompletedHandler { _ in
                    let p = buf.contents().bindMemory(to: UInt16.self, capacity: bytes / 2)
                    var bad = 0, neg = 0
                    for k in stride(from: 0, to: bytes / 2, by: 1) {
                        let h = p[k]
                        if h & 0x7C00 == 0x7C00 { bad += 1 } else if h & 0x8000 != 0 && h & 0x7FFF > 0x0400 { neg += 1 }
                    }
                    let line = "invalid values in the light buffer: \(bad) negative: \(neg)\n"
                    let url = FileManager.default.temporaryDirectory.appending(path: "gpu-stats.txt")
                    if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
                }
            } else { blit.endEncoding() }
        }
        cmd.addCompletedHandler { [weak self] b in  // the stage's GPU time: the power meter, the adaptive resolution
            let s = max(0, b.gpuEndTime - b.gpuStartTime)
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    StageRenderer.onGPUTime?(s)
                    if let self { self.gpuMs = self.gpuMs * 0.9 + s * 1000 * 0.1 }
                }
            }
        }
        if Self.gpuStats {  // -gpuStats YES: average GPU time per frame → $TMPDIR/gpu-stats.txt
            cmd.addCompletedHandler { b in
                let ms = (b.gpuEndTime - b.gpuStartTime) * 1000
                let size = CGSize(width: hdr.width, height: hdr.height)  // what was rendered (adaptive resolution)
                DispatchQueue.main.async { StageRenderer.recordGPU(ms, beams: beams.count, size: size) }
            }
        }
        cmd.commit()
    }

}
