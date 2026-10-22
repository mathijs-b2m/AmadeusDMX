// The stage renderer's setup: pipelines, the beam cone mesh, the scenery and the zones.
import AmadeusKit
import ImageIO
import Metal
import MetalKit
import MetalPerformanceShaders
import QuartzCore
import simd

extension StageRenderer {
    func buildPipelines(_ view: MTKView) throws {
        let lib = try device.makeLibrary(source: Shaders.source, options: nil)
        func pipe(_ v: String, _ f: String, _ vd: MTLVertexDescriptor?, additive: Bool, final: Bool = false) throws -> MTLRenderPipelineState {
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = lib.makeFunction(name: v)
            d.fragmentFunction = lib.makeFunction(name: f)
            d.vertexDescriptor = vd
            let ca = d.colorAttachments[0]!
            ca.pixelFormat = final ? view.colorPixelFormat : .rgba16Float
            if additive {
                ca.isBlendingEnabled = true
                ca.rgbBlendOperation = .add; ca.alphaBlendOperation = .add
                ca.sourceRGBBlendFactor = .one; ca.destinationRGBBlendFactor = .one
                ca.sourceAlphaBlendFactor = .one; ca.destinationAlphaBlendFactor = .one
            }
            if !final { d.depthAttachmentPixelFormat = .depth32Float }
            return try device.makeRenderPipelineState(descriptor: d)
        }
        let solidVD = MTLVertexDescriptor()
        solidVD.attributes[0].format = .float3; solidVD.attributes[0].offset = 0
        solidVD.attributes[1].format = .float3; solidVD.attributes[1].offset = MemoryLayout<SolidVertex>.offset(of: \.normal)!
        solidVD.attributes[2].format = .float4; solidVD.attributes[2].offset = MemoryLayout<SolidVertex>.offset(of: \.color)!
        solidVD.layouts[0].stride = MemoryLayout<SolidVertex>.stride
        let coneVD = MTLVertexDescriptor()
        coneVD.attributes[0].format = .float3; coneVD.attributes[0].offset = 0
        coneVD.layouts[0].stride = MemoryLayout<SIMD3<Float>>.stride
        let wallVD = MTLVertexDescriptor()
        wallVD.attributes[0].format = .float3; wallVD.attributes[0].offset = 0
        wallVD.attributes[1].format = .float2; wallVD.attributes[1].offset = MemoryLayout<WallVertex>.offset(of: \.uv)!
        wallVD.layouts[0].stride = MemoryLayout<WallVertex>.stride

        solidPipe = try pipe("solid_vertex", "solid_fragment", solidVD, additive: false)
        wallPipe = try pipe("wall_vertex", "wall_fragment", wallVD, additive: false)
        beamPipe = try pipe("beam_vertex", "beam_fragment", coneVD, additive: true)
        spritePipe = try pipe("sprite_vertex", "sprite_fragment", nil, additive: true)
        decalPipe = try pipe("decal_vertex", "decal_fragment", nil, additive: true)
        linePipe = try pipe("line_vertex", "line_fragment", nil, additive: true)
        goboBeamPipe = try pipe("gobo_beam_vertex", "gobo_beam_fragment", coneVD, additive: true)
        goboDecalPipe = try pipe("gobo_decal_vertex", "gobo_decal_fragment", nil, additive: true)
        compositePipe = try pipe("fullscreen_vertex", "composite_fragment", nil, additive: false, final: true)
        do {  // drawings on the floor: a page (the wall's quad) in premultiplied alpha over the scene
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = lib.makeFunction(name: "wall_vertex")
            d.fragmentFunction = lib.makeFunction(name: "drawing_fragment")
            d.vertexDescriptor = wallVD
            let ca = d.colorAttachments[0]!
            ca.pixelFormat = .rgba16Float
            ca.isBlendingEnabled = true
            ca.sourceRGBBlendFactor = .one; ca.destinationRGBBlendFactor = .oneMinusSourceAlpha
            ca.sourceAlphaBlendFactor = .one; ca.destinationAlphaBlendFactor = .oneMinusSourceAlpha
            d.depthAttachmentPixelFormat = .depth32Float
            drawingPipe = try device.makeRenderPipelineState(descriptor: d)
        }
        do {  // zones: premultiplied alpha over the scene
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = lib.makeFunction(name: "solid_vertex")
            d.fragmentFunction = lib.makeFunction(name: "zone_fragment")
            d.vertexDescriptor = solidVD
            let ca = d.colorAttachments[0]!
            ca.pixelFormat = .rgba16Float
            ca.isBlendingEnabled = true
            ca.sourceRGBBlendFactor = .one; ca.destinationRGBBlendFactor = .oneMinusSourceAlpha
            ca.sourceAlphaBlendFactor = .one; ca.destinationAlphaBlendFactor = .oneMinusSourceAlpha
            d.depthAttachmentPixelFormat = .depth32Float
            zonePipe = try device.makeRenderPipelineState(descriptor: d)
        }

        let sd = MTLDepthStencilDescriptor()
        sd.depthCompareFunction = .less; sd.isDepthWriteEnabled = true
        solidDepth = device.makeDepthStencilState(descriptor: sd)
        sd.isDepthWriteEnabled = false
        lightDepth = device.makeDepthStencilState(descriptor: sd)
    }

    /// A unit cone (open), x/y = direction around the axis, z = 0 (lens) … 1 (end), in rings for a smooth fade.
    func buildCone() {
        let seg = 40, rings = 10
        var v: [SIMD3<Float>] = []
        for r in 0..<rings {
            let z0 = Float(r) / Float(rings), z1 = Float(r + 1) / Float(rings)
            for s in 0..<seg {
                let a0 = Float(s) / Float(seg) * 2 * .pi, a1 = Float(s + 1) / Float(seg) * 2 * .pi
                let p00 = SIMD3(cos(a0), sin(a0), z0), p10 = SIMD3(cos(a1), sin(a1), z0)
                let p01 = SIMD3(cos(a0), sin(a0), z1), p11 = SIMD3(cos(a1), sin(a1), z1)
                v += [p00, p10, p11, p00, p11, p01]
            }
        }
        coneCount = v.count
        coneBuffer = device.makeBuffer(bytes: v, length: v.count * MemoryLayout<SIMD3<Float>>.stride)
        // a gobo beam is marched through: closed at its end, so a view from inside towards the end still has a face
        for s in 0..<seg {
            let a0 = Float(s) / Float(seg) * 2 * .pi, a1 = Float(s + 1) / Float(seg) * 2 * .pi
            v += [SIMD3(0, 0, 1), SIMD3(cos(a1), sin(a1), 1), SIMD3(cos(a0), sin(a0), 1)]
        }
        cappedConeCount = v.count
        cappedConeBuffer = device.makeBuffer(bytes: v, length: v.count * MemoryLayout<SIMD3<Float>>.stride)
    }

    /// The rig's gobo pictures (the hello's) as texture slices, mipmapped: slice i is picture i.
    func buildGobos(_ pictures: [GoboPicture]) {
        goboKeys = pictures.map(\.key)
        let n = min(max(pictures.count, 1), Self.maxGobos), size = Self.goboSize
        let d = MTLTextureDescriptor()
        d.textureType = .type2DArray
        d.pixelFormat = .rgba8Unorm
        d.width = size; d.height = size; d.arrayLength = n
        d.mipmapLevelCount = Int(log2(Double(size))) + 1
        d.usage = .shaderRead
        guard let tex = device.makeTexture(descriptor: d) else { return }
        var px = [UInt8](repeating: 0, count: size * size * 4)
        for (i, p) in pictures.prefix(n).enumerated() {
            px.withUnsafeMutableBytes { buf in
                buf.initializeMemory(as: UInt8.self, repeating: 0)
                guard let data = Data(base64Encoded: p.img), let src = CGImageSourceCreateWithData(data as CFData, nil),
                      let img = CGImageSourceCreateImageAtIndex(src, 0, nil),
                      let ctx = CGContext(data: buf.baseAddress, width: size, height: size, bitsPerComponent: 8, bytesPerRow: size * 4,
                                          space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
                else { return }
                ctx.interpolationQuality = .high
                ctx.draw(img, in: CGRect(x: 0, y: 0, width: size, height: size))
            }
            tex.replace(region: MTLRegionMake2D(0, 0, size, size), mipmapLevel: 0, slice: i, withBytes: px,
                        bytesPerRow: size * 4, bytesPerImage: size * size * 4)
        }
        if let cmd = queue.makeCommandBuffer(), let blit = cmd.makeBlitCommandEncoder() {
            blit.generateMipmaps(for: tex)
            blit.endEncoding()
            cmd.commit()
        }
        goboTexture = tex
        goboSlices = pictures.isEmpty ? 0 : n
    }

    func rebuildScenery(_ inp: StageInput) {
        let first = scenery == nil
        let s = Scenery(fixtures: inp.fixtures, stage: inp.stage, screen: inp.screen, trusses: inp.trusses, selected: inp.selected)
        scenery = s
        sceneryKey = inp.key
        sceneryCount = s.vertices.count
        sceneryBuffer = s.vertices.isEmpty ? nil
            : device.makeBuffer(bytes: s.vertices, length: s.vertices.count * MemoryLayout<SolidVertex>.stride)
        buildZones(inp)
        if let w = s.wall {
            let c = w.corners
            // seen from the audience, world +x is on the left: the picture's left edge goes on the +x side
            let v = [WallVertex(pos: c.bl, uv: [1, 1]), WallVertex(pos: c.br, uv: [0, 1]), WallVertex(pos: c.tr, uv: [0, 0]),
                     WallVertex(pos: c.bl, uv: [1, 1]), WallVertex(pos: c.tr, uv: [0, 0]), WallVertex(pos: c.tl, uv: [1, 0])]
            wallBuffer = device.makeBuffer(bytes: v, length: v.count * MemoryLayout<WallVertex>.stride)
        } else {
            wallBuffer = nil
        }
        buildDrawings(inp, s)
        if first || !inp.keepCamera { setPreset(preset, animated: false) }
    }

    /// The drawings on the floor: each plan a quad on its corners showing its part of the page (rig metres are world
    /// metres: x from stage left, y towards the audience, as the trusses), a few mm over the hall floor, and again
    /// over the stage deck where it covers the deck (the deck stands 15 cm high, or as high as the stage: the
    /// floor's copy is hidden under it).
    func buildDrawings(_ inp: StageInput, _ s: Scenery) {
        drawingDraws = []
        for d in inp.drawings where d.corners.count == 4 {
            guard let tex = drawingTexture(d) else { continue }
            let c = d.corners
            let k = d.crop
            let uv: [SIMD2<Float>] = [[k.x, k.y], [k.z, k.y], [k.z, k.w], [k.x, k.w]]
            var v: [WallVertex] = []
            func fan(_ poly: [(p: SIMD2<Float>, uv: SIMD2<Float>)], z: Float) {
                guard poly.count >= 3 else { return }
                for i in 1..<(poly.count - 1) {
                    for q in [poly[0], poly[i], poly[i + 1]] { v.append(WallVertex(pos: SIMD3(q.p, z), uv: q.uv)) }
                }
            }
            let quad = Array(zip(c, uv)).map { (p: $0.0, uv: $0.1) }
            fan(quad, z: Self.drawingLift)
            if let deck = s.deck { fan(Self.clip(quad, x0: deck.x0, x1: deck.x1, y0: deck.y0, y1: deck.y1), z: deck.top + Self.drawingLift) }
            guard !v.isEmpty, let buf = device.makeBuffer(bytes: v, length: v.count * MemoryLayout<WallVertex>.stride) else { continue }
            drawingDraws.append((buf, v.count, tex, max(0, min(1, d.opacity))))
        }
    }

    static let drawingLift: Float = 0.01        // over the floor (m): no fighting with it, seen from afar too
    static let drawingBrightness: Float = 0.3   // white paper as the work-lit floor shows it, not a light

    /// A convex polygon cut to a rectangle (Sutherland–Hodgman), its texture coordinates along.
    static func clip(_ poly: [(p: SIMD2<Float>, uv: SIMD2<Float>)], x0: Float, x1: Float, y0: Float, y1: Float)
        -> [(p: SIMD2<Float>, uv: SIMD2<Float>)] {
        typealias P = (p: SIMD2<Float>, uv: SIMD2<Float>)
        func cut(_ poly: [P], _ inside: (SIMD2<Float>) -> Float) -> [P] {  // inside(p) >= 0: kept
            var out: [P] = []
            for i in poly.indices {
                let a = poly[i], b = poly[(i + 1) % poly.count]
                let da = inside(a.p), db = inside(b.p)
                if da >= 0 { out.append(a) }
                if (da >= 0) != (db >= 0) {
                    let t = da / (da - db)
                    out.append((a.p + (b.p - a.p) * t, a.uv + (b.uv - a.uv) * t))
                }
            }
            return out
        }
        var out = poly
        out = cut(out) { $0.x - x0 }
        out = cut(out) { x1 - $0.x }
        out = cut(out) { $0.y - y0 }
        out = cut(out) { y1 - $0.y }
        return out
    }

    /// A drawing's page as a texture (sRGB, mipmapped: it stays smooth seen from afar), made once per page.
    func drawingTexture(_ d: FloorDrawing) -> MTLTexture? {
        if let t = drawingTextures[d.key] { return t }
        let w = d.image.width, h = d.image.height
        guard w > 0, h > 0 else { return nil }
        let desc = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .rgba8Unorm_srgb, width: w, height: h, mipmapped: true)
        desc.usage = .shaderRead
        guard let tex = device.makeTexture(descriptor: desc) else { return nil }
        var px = [UInt8](repeating: 255, count: w * h * 4)
        let drawn = px.withUnsafeMutableBytes { buf -> Bool in
            guard let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                      space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            ctx.draw(d.image, in: CGRect(x: 0, y: 0, width: w, height: h))  // row 0 is the page's top
            return true
        }
        guard drawn else { return nil }
        tex.replace(region: MTLRegionMake2D(0, 0, w, h), mipmapLevel: 0, withBytes: px, bytesPerRow: w * 4)
        if let cmd = queue.makeCommandBuffer(), let blit = cmd.makeBlitCommandEncoder() {
            blit.generateMipmaps(for: tex)
            blit.endEncoding()
            cmd.commit()
        }
        drawingTextures[d.key] = tex
        return tex
    }

    /// Zone faces (translucent) and their edges (thin glowing lines), coloured by kind.
    func buildZones(_ inp: StageInput) {
        var v: [SolidVertex] = []
        zoneEdges = []
        for z in inp.zones {
            let sel = inp.selected.contains("zone:\(z.id)")
            let col: SIMD3<Float> = z.kind == "laser_out" ? [1, 0.25, 0.2] : z.kind == "keep_in" ? [0.2, 0.9, 0.5] : [0.3, 0.55, 1]
            let alpha: Float = !z.enabled ? 0.05 : sel ? 0.3 : 0.16
            let c = z.corners.map { SIMD3<Float>(Float($0.x), Float($0.y), Float($0.z)) }
            func face(_ a: Int, _ b: Int, _ cc: Int, _ d: Int) {
                let n = simd_normalize(simd_cross(c[b] - c[a], c[d] - c[a]))
                for i in [a, b, cc, a, cc, d] { v.append(SolidVertex(pos: c[i], normal: n, color: SIMD4(col, alpha))) }
            }
            var edges: [(Int, Int)]
            if z.shape == "box" {
                face(0, 1, 2, 3); face(4, 5, 6, 7); face(0, 1, 5, 4); face(2, 3, 7, 6); face(1, 2, 6, 5); face(0, 3, 7, 4)
                edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
            } else {
                face(0, 1, 2, 3)
                edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
            }
            let glow: Float = !z.enabled ? 0.15 : sel ? 2.2 : 0.9
            for (a, b) in edges {
                zoneEdges.append(LineInstance(p0Width: SIMD4(c[a], sel ? 0.03 : 0.018), p1: SIMD4(c[b], 0), color: SIMD4(col, glow)))
            }
        }
        zoneCount = v.count
        zoneBuffer = v.isEmpty ? nil : device.makeBuffer(bytes: v, length: v.count * MemoryLayout<SolidVertex>.stride)
    }
}
