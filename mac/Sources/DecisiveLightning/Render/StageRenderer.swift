// The Metal stage: scenery, volumetric beams, spots, lasers, flares and the LED wall into an HDR target,
// then bloom (MPS blur at half and quarter resolution) and a tone curve into the window.
import DecisiveKit
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
}

@MainActor
final class StageRenderer: NSObject, MTKViewDelegate {
    let device: MTLDevice
    let queue: MTLCommandQueue
    var solidPipe, beamPipe, spritePipe, decalPipe, linePipe, wallPipe, compositePipe, zonePipe: MTLRenderPipelineState!
    var zoneBuffer: MTLBuffer?
    var zoneCount = 0
    var zoneEdges: [LineInstance] = []
    var solidDepth, lightDepth: MTLDepthStencilState!
    var coneBuffer: MTLBuffer!
    var coneCount = 0
    var sceneryBuffer: MTLBuffer?
    var sceneryCount = 0
    var wallBuffer: MTLBuffer?
    var wallTexture: MTLTexture!
    var hdr, depth, halfA, halfB, quarterA, quarterB: MTLTexture?
    var scenery: Scenery?
    var sceneryKey = ""
    let wall = WallRenderer()

    // inputs
    var input: (() -> (StageInput?, Frame?))?
    var highlight: Set<String> = []
    var haze: Float = 0.75
    var exposure: Float = 1.0
    var autoExposure: Float = 1.0
    lazy var statsTexture: MTLTexture? = {
        let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba32Float, width: 1, height: 1, mipmapped: false)
        d.usage = [.shaderRead, .shaderWrite]
        return device.makeTexture(descriptor: d)
    }()
    lazy var statsBuf: MTLBuffer? = device.makeBuffer(length: 16, options: .storageModeShared)
    var autoOrbit = false
    /// Light the room so the rig is easy to see (rig pages, no show).
    var workLight: Float = 0
    var wallScene: WallScene { get { wall.force } set { wall.force = newValue } }
    /// What the wall shows right now (for the UI).
    private(set) var wallNow: WallScene = .off

    // camera
    private(set) var pose = CameraPose(target: [3, -1, 2], yaw: 0, pitch: 0.15, distance: 12)
    var goal: CameraPose?
    private(set) var preset: CameraPreset = .frontOfHouse
    var lastTime = CACurrentMediaTime()
    var startTime = CACurrentMediaTime()
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
        goal = nil
        pose.yaw -= dx * 0.005
        pose.pitch = min(1.45, max(-0.05, pose.pitch + dy * 0.004))
    }

    func zoom(_ factor: Float) {
        goal = nil
        pose.distance = min(80, max(2, pose.distance * factor))
    }

    func pan(dx: Float, dy: Float) {
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
        let now = CACurrentMediaTime()
        let dt = Float(min(0.1, now - lastTime))
        lastTime = now
        let (inp, frame) = input?() ?? (nil, nil)
        if Self.gpuStats, let f = frame, f.t != Self.lastFrameT { Self.lastFrameT = f.t; Self.newFrames += 1 }
        if let inp, inp.key != sceneryKey { rebuildScenery(inp) }
        if let g = goal {
            pose = .lerp(pose, g, 1 - exp(-dt * 4))
            if abs(pose.distance - g.distance) < 0.01 && simd_length(pose.target - g.target) < 0.01 { pose = g; goal = nil }
        }
        if autoOrbit && goal == nil { pose.yaw += dt * 0.05 }

        ensureTargets(view.drawableSize)
        guard let hdr, let depth, let halfA, let halfB, let quarterA, let quarterB,
              let drawable = view.currentDrawable, let cmd = queue.makeCommandBuffer() else { return }

        // camera
        let eye = pose.eye
        let aspect = Float(max(1, view.drawableSize.width) / max(1, view.drawableSize.height))
        let viewM = float4x4.lookAt(eye: eye, target: pose.target, up: [0, 0, 1])
        let proj = float4x4.perspective(fovY: 0.75, aspect: aspect, near: 0.1, far: 300)
        let f = simd_normalize(pose.target - eye), right = simd_normalize(simd_cross(f, [0, 0, 1])), up = simd_cross(right, f)

        // lights
        var beams: [BeamInstance] = [], sprites: [SpriteInstance] = [], decals: [DecalInstance] = [], lines: [LineInstance] = []
        var ambient = SIMD3<Float>(repeating: 0)
        if let inp, let s = scenery {
            buildLights(inp, frame, s, eye: eye, t: Float(now - startTime), beams: &beams, sprites: &sprites,
                        decals: &decals, lines: &lines, ambient: &ambient)
        }

        var u = Uniforms(viewProj: proj * viewM, camPos: SIMD4(eye, 1), camRight: SIMD4(right, 0), camUp: SIMD4(up, 0),
                         params: [Float(now - startTime), haze, exposure, 0.9], ambient: SIMD4(ambient, workLight))

        // the wall's picture
        var wp = WallParams(info: .zero, bands: .zero, pal: (.zero, .zero, .zero, .zero))
        if let inp, let h = inp.hello, let frame, scenery?.wall != nil {
            let out = wall.update(frame: frame, hello: h, dt: dt)
            wallNow = out.scene
            if !out.psychedelic, let data = wall.context.data {
                wallTexture.replace(region: MTLRegionMake2D(0, 0, WallRenderer.W, WallRenderer.H), mipmapLevel: 0,
                                    withBytes: data, bytesPerRow: WallRenderer.W * 4)
            }
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
            if let wb = wallBuffer {
                enc.setRenderPipelineState(wallPipe)
                enc.setDepthStencilState(solidDepth)
                enc.setVertexBuffer(wb, offset: 0, index: 0)
                enc.setFragmentTexture(wallTexture, index: 0)
                enc.setFragmentBytes(&wp, length: MemoryLayout<WallParams>.stride, index: 3)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6)
            }
            enc.setDepthStencilState(lightDepth)
            if !decals.isEmpty {
                enc.setRenderPipelineState(decalPipe)
                enc.setVertexBytes(decals, length: decals.count * MemoryLayout<DecalInstance>.stride, index: 2)
                enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 6, instanceCount: decals.count)
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
        fp.colorAttachments[0].texture = drawable.texture
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
        cmd.present(drawable)
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
        if Self.gpuStats {  // -gpuStats YES: average GPU time per frame → $TMPDIR/gpu-stats.txt
            cmd.addCompletedHandler { b in
                let ms = (b.gpuEndTime - b.gpuStartTime) * 1000
                DispatchQueue.main.async { StageRenderer.recordGPU(ms, beams: beams.count, size: view.drawableSize) }
            }
        }
        cmd.commit()
    }

}
