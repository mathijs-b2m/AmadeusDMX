// Development: draw the stage from recorded feed messages into pictures, without the app (-stageSnapshot DIR).
// DIR holds hello.json and frame files (feed messages, e.g. from the engine); every frame-NAME.json becomes
// NAME.png, drawn after a second of show time on that frame (gobos turn, the exposure settles). Optional:
// -camera "Front of House" (a preset), -cameraYaw 180 (turned round the stage that many degrees from it), -inRoom YES,
// -snapshotSize 1600x900. On a rig with an LED wall it also draws what the LED Wall Output sends: NAME-wall.png (the
// show's picture) and NAME-card.png (the test card) on a display of -wallOutputSize 1920x1080, the wall at
// -wallRect X,Y,W,H (missing: the whole display), panels of -panelPx 128, one scene with -wallScene runner. The app quits when done, before it starts
// anything.
import AmadeusKit
import AppKit
import ImageIO
import Metal
import MetalKit
import UniformTypeIdentifiers

enum StageSnapshot {
    @MainActor static func runIfAsked() {
        guard let dir = UserDefaults.standard.string(forKey: "stageSnapshot") else { return }
        let url = URL(fileURLWithPath: dir)
        do {
            try run(url)
            exit(0)
        } catch {
            FileHandle.standardError.write(Data("stage snapshot: \(error)\n".utf8))
            exit(1)
        }
    }

    struct Failure: Error, CustomStringConvertible { var description: String }

    @MainActor static func run(_ dir: URL) throws {
        guard case .hello(let hello)? = FeedMessage.decode(try Data(contentsOf: dir.appending(path: "hello.json"))) else {
            throw Failure(description: "no hello in \(dir.path)/hello.json")
        }
        let size = (UserDefaults.standard.string(forKey: "snapshotSize") ?? "1600x900").split(separator: "x").compactMap { Int($0) }
        let (w, h) = size.count == 2 ? (size[0], size[1]) : (1600, 900)
        let view = MTKView(frame: CGRect(x: 0, y: 0, width: w, height: h))
        view.autoResizeDrawable = false
        view.drawableSize = CGSize(width: w, height: h)
        guard let r = StageRenderer(view: view) else { throw Failure(description: "no Metal") }
        let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: view.colorPixelFormat, width: w, height: h, mipmapped: false)
        d.usage = [.renderTarget, .shaderRead]
        d.storageMode = .shared
        guard let target = r.device.makeTexture(descriptor: d) else { throw Failure(description: "no texture") }
        let input = StageInput(key: "snapshot", fixtures: hello.fixtures, stage: hello.stage, screen: hello.screen, screenAspect: hello.screenAspect, hello: hello,
                               trusses: hello.trusses)
        let files = try FileManager.default.contentsOfDirectory(atPath: dir.path).filter { $0.hasPrefix("frame") && $0.hasSuffix(".json") }.sorted()
        var frame: Frame?
        r.input = { (input, frame) }
        r.inRoom = UserDefaults.standard.bool(forKey: "inRoom")
        let preset = UserDefaults.standard.string(forKey: "camera").flatMap(CameraPreset.init(rawValue:)) ?? .frontOfHouse
        func ints(_ key: String, _ sep: Character) -> [Int]? {
            UserDefaults.standard.string(forKey: key).map { $0.split(separator: sep).compactMap { Int($0.trimmingCharacters(in: .whitespaces)) } }
        }
        let outSize = ints("wallOutputSize", "x").flatMap { $0.count == 2 ? (w: $0[0], h: $0[1]) : nil } ?? (w: 1920, h: 1080)
        let wallRect = ints("wallRect", ",").flatMap { $0.count == 4 ? PixelRect(x: $0[0], y: $0[1], w: $0[2], h: $0[3]) : nil }
        let wall = WallOutputLayout.wallRect(wallRect, display: outSize.w, outSize.h)
        let pic = WallOutputLayout.fit(wall, aspect: hello.screenAspect), canvas = WallRenderer.canvas(hello.screenAspect)
        let panelPx = UserDefaults.standard.integer(forKey: "panelPx") > 0 ? UserDefaults.standard.integer(forKey: "panelPx") : 128
        WallSource.shared.scale = WallOutputLayout.pictureScale(picture: pic, canvas: (Double(canvas.w), Double(canvas.h)))
        WallSource.shared.outputPicture = (pic.w, pic.h)
        let drawer = WallOutputDrawer()
        let od = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .bgra8Unorm, width: outSize.w, height: outSize.h, mipmapped: false)
        od.usage = [.renderTarget, .shaderRead]
        od.storageMode = .shared
        let outTarget = hello.screen ? r.device.makeTexture(descriptor: od) : nil
        if UserDefaults.standard.bool(forKey: "wallBench"), let f0 = files.first,
           case .frame(let bf)? = FeedMessage.decode(try Data(contentsOf: dir.appending(path: f0))) {
            // -wallBench YES: how long the CPU takes to draw one wall picture per scene, at 720p, 1080p and 4K
            for s in [2.0, 3.0, 6.0] {
                for scene in [WallScene.runner, .dancer, .crowd, .pong, .words, .equalizer, .ambient] {
                    let w = WallRenderer(scale: CGFloat(s), aspect: hello.screenAspect)
                    w.force = scene
                    var f = bf
                    for k in 0..<10 { f.t = bf.t + Double(k) / 40; f.bp = (bf.bp ?? 0) + Double(k) / 40 * hello.bpm / 60; _ = w.update(frame: f, hello: hello, dt: 1 / 40) }
                    let t0 = CACurrentMediaTime()
                    for k in 10..<50 { f.t = bf.t + Double(k) / 40; f.bp = (bf.bp ?? 0) + Double(k) / 40 * hello.bpm / 60; _ = w.update(frame: f, hello: hello, dt: 1 / 40) }
                    print(String(format: "wall bench: %@ at %d×%d: %.1f ms", scene.rawValue, w.pixelWidth, w.pixelHeight,
                                 (CACurrentMediaTime() - t0) / 40 * 1000))
                }
            }
            // and how much a scene's brightness jumps when the time between pictures does (25 ms, then 50: the
            // painter skips a show frame while busy): steady scenes stay within a few percent
            func light(_ w: WallRenderer) -> Double {
                guard let d = w.context.data else { return 0 }
                let p = d.assumingMemoryBound(to: UInt8.self), n = w.pixelWidth * w.pixelHeight
                return Double((0..<n).reduce(0) { $0 + Int(p[$1 * 4]) + Int(p[$1 * 4 + 1]) + Int(p[$1 * 4 + 2]) }) / Double(n * 3)
            }
            for scene in [WallScene.runner, .dancer, .crowd, .pong, .words, .equalizer, .ambient] {
                let w = WallRenderer(scale: 1, aspect: hello.screenAspect)
                w.force = scene
                var f = bf, t = 0.0, short = [Double](), long = [Double]()
                for k in 0..<120 {
                    let dt = k % 2 == 0 ? 1.0 / 40 : 1.0 / 20
                    t += dt; f.t = bf.t + t; f.bp = (bf.bp ?? 0) + t * hello.bpm / 60
                    _ = w.update(frame: f, hello: hello, dt: Float(dt))
                    if k >= 40 { if dt < 0.03 { short.append(light(w)) } else { long.append(light(w)) } }
                }
                let a = short.reduce(0, +) / Double(max(1, short.count)), b = long.reduce(0, +) / Double(max(1, long.count))
                print(String(format: "wall steady: %@ %.1f after 25 ms, %.1f after 50 ms (%+.0f%%)", scene.rawValue, a, b,
                             (a / max(b, 0.001) - 1) * 100))
            }
            exit(0)
        }
        if let scene = UserDefaults.standard.string(forKey: "wallScene").flatMap(WallScene.init(rawValue:)) {
            WallSource.shared.force = scene   // -wallScene runner: one scene on the wall
        }
        var gpu: [Double] = []
        StageRenderer.onGPUTime = { gpu.append($0) }
        var now: CFTimeInterval = 1000
        r.startTime = now; r.lastTime = now
        for name in files {
            guard case .frame(let f)? = FeedMessage.decode(try Data(contentsOf: dir.appending(path: name))) else { continue }
            frame = f
            for k in 0..<40 {  // a second at the show's 40 frames a second
                now += 1.0 / 40
                r.snapshot = (target, now)
                r.draw(in: view)
                if k == 0 {
                    r.setPreset(preset, animated: false)
                    if let yaw = UserDefaults.standard.string(forKey: "cameraYaw").flatMap(Float.init) { r.orbit(dx: -yaw * .pi / 180 / 0.005, dy: 0) }
                }
            }
            guard let cmd = r.queue.makeCommandBuffer() else { continue }
            cmd.commit()
            cmd.waitUntilCompleted()
            let out = dir.appending(path: name.replacingOccurrences(of: "frame-", with: "").replacingOccurrences(of: ".json", with: ".png"))
            try save(target, to: out)
            if let outTarget {   // what goes to the LED wall
                for (suffix, card) in [("wall", nil), ("card", TestCard.draw(pixels: (wall.w, wall.h), wall: wall, panelPx: panelPx))] as [(String, CGImage?)] {
                    guard let cmd = r.queue.makeCommandBuffer() else { continue }
                    let tex = try card.map { try MTKTextureLoader(device: r.device).newTexture(cgImage: $0, options: [.SRGB: false]) }
                    WallSource.shared.flush()   // the picture drawn on the painter's queue
                    let lit = WallSource.shared.prepare(frame: frame, hello: hello, now: now, cmd: cmd)?.level ?? 0
                    drawer.encode(cmd, into: outTarget, wall: wall, picture: pic, level: tex != nil ? 1 : lit, card: tex, time: 0.7)
                    cmd.commit()
                    cmd.waitUntilCompleted()
                    let url = out.deletingPathExtension().appendingPathExtension("png").path.replacingOccurrences(of: ".png", with: "-\(suffix).png")
                    try save(outTarget, to: URL(fileURLWithPath: url))
                    print("stage snapshot: \(url)")
                }
            }
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))  // the GPU times come in on the main queue
            let ms = gpu.suffix(20).reduce(0, +) / Double(max(1, min(20, gpu.count))) * 1000
            print(String(format: "stage snapshot: %@ (%.1f ms GPU per frame at %d×%d)", out.path, ms, w, h))
            gpu = []
        }
    }

    static func save(_ tex: MTLTexture, to url: URL) throws {
        let w = tex.width, h = tex.height
        var px = [UInt8](repeating: 0, count: w * h * 4)
        tex.getBytes(&px, bytesPerRow: w * 4, from: MTLRegionMake2D(0, 0, w, h), mipmapLevel: 0)
        let info = CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        guard let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: info.rawValue),
              let img = ctx.makeImage(),
              let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)
        else { throw Failure(description: "can't write \(url.path)") }
        CGImageDestinationAddImage(dest, img, nil)
        guard CGImageDestinationFinalize(dest) else { throw Failure(description: "can't write \(url.path)") }
    }
}
