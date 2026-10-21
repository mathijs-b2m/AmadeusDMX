// Development: draw the stage from recorded feed messages into pictures, without the app (-stageSnapshot DIR).
// DIR holds hello.json and frame files (feed messages, e.g. from the engine); every frame-NAME.json becomes
// NAME.png, drawn after a second of show time on that frame (gobos turn, the exposure settles). Optional:
// -camera "Front of House" (a preset), -snapshotSize 1600x900. The app quits when done, before it starts anything.
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
        let input = StageInput(key: "snapshot", fixtures: hello.fixtures, stage: hello.stage, screen: hello.screen, hello: hello,
                               trusses: hello.trusses)
        let files = try FileManager.default.contentsOfDirectory(atPath: dir.path).filter { $0.hasPrefix("frame") && $0.hasSuffix(".json") }.sorted()
        var frame: Frame?
        r.input = { (input, frame) }
        let preset = UserDefaults.standard.string(forKey: "camera").flatMap(CameraPreset.init(rawValue:)) ?? .frontOfHouse
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
                if k == 0 { r.setPreset(preset, animated: false) }
            }
            guard let cmd = r.queue.makeCommandBuffer() else { continue }
            cmd.commit()
            cmd.waitUntilCompleted()
            let out = dir.appending(path: name.replacingOccurrences(of: "frame-", with: "").replacingOccurrences(of: ".json", with: ".png"))
            try save(target, to: out)
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
