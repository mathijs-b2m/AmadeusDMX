// The LED wall's picture (the native version of web/js/screen.js). The director picks a mode per phrase
// (decision.screen): off | ambient | figure | words | equalizer | psychedelic. Figures are playful neon
// outlines on the beat: a runner, a dancer, a jumping crowd, pong. The modes also bring abstract scenes: geometric
// shapes among the figures, a scope for the equaliser, a starfield for ambient, a tunnel in drops (pick()). Into a
// The music's style picks the family: the harder styles (hardstyle, hardcore, metal, dubstep) get dark, sharp scenes (a wolf's
// head in facets, claws, jaws of spikes) and none of the playful figures; techno and the other club styles get hard
// lines and a ridge landscape beside them. The wall flashes when the lights strobe (frame.strobe) and when blinders
// and strobe lights fire: it is part of the light show. Into a
// drop the wall counts 3-2-1 and
// shouts DROP!. Psychedelic is drawn by a Metal shader (WallSource); everything else here, with
// Core Graphics, into a 640×360 picture (the wall's shape when the rig gives its pixels; finer for a real LED wall:
// `scale`) that WallSource puts on the GPU.
import CoreGraphics
import CoreText
import AmadeusKit
import Foundation
import simd

enum WallScene: String, CaseIterable, Identifiable {
    case auto, off, ambient, starfield, runner, dancer, crowd, pong, shapes, lines, grid, wolf, claws, spikes, words, equalizer, scope, tunnel, psychedelic
    var id: String { rawValue }
    var title: String { self == .auto ? "Director's Choice" : rawValue.capitalized }
    var symbol: String {
        switch self {
        case .auto: "wand.and.stars"
        case .off: "rectangle.slash"
        case .ambient: "cloud.fog"
        case .starfield: "sparkles"
        case .shapes: "triangle"
        case .scope: "waveform"
        case .tunnel: "circle.circle"
        case .lines: "barcode"
        case .grid: "mountain.2"
        case .wolf: "pawprint"
        case .claws: "line.diagonal"
        case .spikes: "bolt"
        case .runner: "figure.run"
        case .dancer: "figure.dance"
        case .crowd: "person.3"
        case .pong: "gamecontroller"
        case .words: "textformat.size"
        case .equalizer: "chart.bar"
        case .psychedelic: "circle.hexagongrid"
        }
    }
    static let figures: [WallScene] = [.runner, .dancer, .crowd, .pong]
}

struct WallState {
    var level: Float
    var psychedelic: Bool
    var palette: [SIMD3<Float>]
    var bands: SIMD4<Float>
    var scene: WallScene
    /// The lights strobe or the blinders fire: how much of the wall is the flash now, 0..1.
    var flash: Float = 0
    /// The overlay layer (WallSource's layer_mask): x the mask, y the beat's lift 0..1, z the beat's phase, w its parity.
    var layer = SIMD4<Float>(repeating: 0)
}

/// What kind of scenes a style of music gets.
enum WallFamily {
    case hard, club, other

    init(_ h: Hello) {
        let g = (h.style.isEmpty ? h.genre : h.style).lowercased()
        self = ["hardstyle", "hardcore", "metal", "dubstep"].contains(g) ? .hard
            : ["techno", "trance", "psytrance", "edm", "house", "dnb"].contains(g) ? .club : .other
    }
}

final class WallRenderer {
    /// The 16:9 picture's units: 640×360. A wall of another shape gets a canvas of its shape, its short side 360
    /// (cw × ch: 1440×360 for 4:1, 360×720 for 1:2): figures keep their size against the short side, scenes spread
    /// along the long one; on a tall wall the scenes that stand on a floor stand in its middle.
    static let W = 640, H = 360
    let context: CGContext
    /// The canvas in units, the wall's shape.
    let cw: CGFloat, ch: CGFloat
    let aspect: Double
    /// How much finer than the units the context is (a real LED wall wants more pixels than the 3D stage's wall).
    let scale: CGFloat
    var pixelWidth: Int { context.width }
    var pixelHeight: Int { context.height }
    var force: WallScene = .auto
    /// Where scenes that stand on something have their floor: the bottom, or on a tall wall a little below its middle.
    private var ground: CGFloat { ch > CGFloat(Self.H) ? ch - (ch - CGFloat(Self.H)) * 0.4 : ch }

    private var cur: (mode: String, scene: WallScene) = ("off", .off)
    private var fade: Float = 0
    private var level: Float = 0
    /// The equaliser's bars: 16 on a 16:9 wall, more on a wider one.
    private var eq: [Float], caps: [Float]
    /// How far the tunnel, the stars and the shapes have travelled, in beats (faster in a drop), and the beat last seen.
    private var travel: Double = 0, lastBp: Double?
    /// The music's bass, mids and highs, smoothed (the scope's lines, the bokeh's breath).
    private var sound = SIMD3<Float>(repeating: 0)
    /// The flash with the lights' strobes (its short tail).
    private var flash: Float = 0
    /// The blinders' and strobe lights' level as it has been lately: the wall flashes on what comes on top of it.
    private var blindHeld: Float = 0
    private var amb: Double = 0
    private var fromPose: [[Float]] = WallRenderer.moves["down"]!
    private var lastBeat = -1
    /// This picture's fade (the share of the last picture darkened) and the fade at the show's 40 pictures a second.
    private var fadeNow: CGFloat = 0.59, fadeRef: CGFloat = 0.59
    /// The time between pictures, smoothed: the trail's fade follows it (one picture 25 ms after the last, the next 50,
    /// would brighten and dim every glow that builds up on the trail).
    private var fadeDt: Double = 1.0 / 40

    /// One overlay mask tried out (development: the stage snapshot's -wallMask 0…7).
    nonisolated(unsafe) static var forceMask: Float?

    /// The canvas for a wall of this shape, in units.
    static func canvas(_ aspect: Double) -> (w: CGFloat, h: CGFloat) {
        let a = CGFloat(aspect)
        return a >= 1 ? ((CGFloat(H) * a).rounded(), CGFloat(H)) : (CGFloat(H), (CGFloat(H) / a).rounded())
    }

    init(scale: CGFloat = 1, aspect: Double = ScreenShape.defaultAspect) {
        self.scale = scale
        self.aspect = aspect
        (cw, ch) = Self.canvas(aspect)
        let bars = min(48, max(12, Int((16 * cw / CGFloat(Self.W)).rounded())))
        eq = [Float](repeating: 0, count: bars); caps = eq
        let w = Int((cw * scale).rounded()), h = Int((ch * scale).rounded())
        context = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
        context.translateBy(x: 0, y: CGFloat(h))
        context.scaleBy(x: scale, y: -scale)   // y down, like a canvas, in units
        context.setFillColor(CGColor(gray: 0, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
    }

    /// Carries on where `old` was (another resolution, the same shape): its scene, fades, equaliser and dancer, and its
    /// last picture (the trails fade on it), so drawing finer or coarser doesn't show.
    func takeOver(from old: WallRenderer) {
        cur = old.cur; fade = old.fade; level = old.level; amb = old.amb
        if old.eq.count == eq.count { eq = old.eq; caps = old.caps }
        travel = old.travel; lastBp = old.lastBp; sound = old.sound; flash = old.flash; blindHeld = old.blindHeld
        fromPose = old.fromPose; lastBeat = old.lastBeat; force = old.force; fadeDt = old.fadeDt
        if old.aspect == aspect, let img = old.context.makeImage() {
            context.saveGState()
            context.scaleBy(x: 1, y: -1)   // the picture's own orientation, in units
            context.translateBy(x: 0, y: -ch)
            context.interpolationQuality = .medium
            context.draw(img, in: CGRect(x: 0, y: 0, width: cw, height: ch))
            context.restoreGState()
        }
    }

    static func hash(_ n: Int, _ salt: Int = 0) -> Int {
        Int((UInt64(truncatingIfNeeded: n + 1) &* 2654435761 &+ UInt64(salt) &* 40503) % 4294967296)
    }

    private static let rules: [String: [String]] = [
        "intro": ["off", "ambient"], "groove": ["off", "figure", "equalizer", "off", "figure", "words"],
        "buildup": ["words", "figure"], "drop": ["psychedelic", "figure", "equalizer"],
        "breakdown": ["ambient", "off", "figure"], "outro": ["ambient", "off"],
        "verse": ["off", "ambient", "words"], "chorus": ["figure", "equalizer", "words"], "bridge": ["ambient", "off"],
    ]

    private func wanted(_ f: Frame, _ d: Decision?, _ h: Hello) -> (String, WallScene) {
        if force != .auto {
            return (WallScene.figures.contains(force) ? "figure" : force.rawValue, force)
        }
        var mode = d?.screen ?? ""
        if mode.isEmpty {
            let opts = Self.rules[d?.section ?? ""] ?? ["off"]
            mode = opts[Self.hash(f.phrase, 2) % opts.count]
        }
        return (mode, Self.pick(mode, phrase: f.phrase, drop: d?.section == "drop", family: WallFamily(h)))
    }

    /// The scene a mode shows this phrase: the director's modes are few, each brings a small family of scenes.
    static func pick(_ mode: String, phrase: Int, drop: Bool, family: WallFamily = .other) -> WallScene {
        let pool: [WallScene]
        switch (mode, family) {
        case ("figure", .hard): pool = [.wolf, .claws, .spikes, .shapes] + (drop ? [.wolf, .tunnel] : [])
        case ("figure", .club): pool = [.lines, .grid, .shapes, .dancer, .crowd] + (drop ? [.tunnel, .lines] : [])
        case ("figure", _): pool = WallScene.figures + (drop ? [.shapes, .tunnel] : [.shapes])
        case ("equalizer", .hard): pool = [.spikes, .scope]
        case ("equalizer", .club): pool = [.equalizer, .scope, .grid]
        case ("equalizer", _): pool = [.equalizer, .scope]
        case ("ambient", _): pool = [.ambient, .ambient, .starfield]
        case ("psychedelic", .hard): pool = [.psychedelic, .tunnel, .claws]
        case ("psychedelic", .club): pool = [.psychedelic, .psychedelic, .tunnel, .lines]
        case ("psychedelic", _): pool = [.psychedelic, .psychedelic, .tunnel]
        default: return WallScene(rawValue: mode) ?? .off
        }
        return pool[hash(phrase, 9) % pool.count]
    }

    func update(frame f: Frame, hello h: Hello, dt: Float) -> WallState {
        let d = h.plan.indices.contains(f.phrase) ? h.plan[f.phrase] : nil
        var want = wanted(f, d, h)
        // the show arc's LED wall knob (live mode): dimmer, below half only calm colour, at zero off
        let wall = force == .auto ? Float(f.arc.flatMap { $0.on ? $0.values["screen"] : nil } ?? 1) : 1
        if wall < 0.03 { want = ("off", .off) } else if wall < 0.5, want.0 != "off" { want = ("ambient", .ambient) }
        let next = h.plan.indices.contains(f.phrase + 1) ? h.plan[f.phrase + 1] : nil
        let spb = 60 / max(h.bpm, 60)
        let nextDrop = h.countdown == f.phrase + 1 && next?.section == "drop" && d?.section != "drop"  // the rare one
        let beatsLeft = nextDrop ? (next!.start - f.t) / spb : 99
        if want.0 == "off" && beatsLeft <= 4.5 && force == .auto && wall >= 0.5 { want = ("words", .words) }  // a dark wall counts in
        let shout = wall >= 0.5 && h.countdown == f.phrase && d?.section == "drop" && cur.mode != "off" && cur.scene != .psychedelic && (f.t - d!.start) / spb < 2
        if shout { fade = 1 }
        else if want.1 != cur.scene {
            fade = max(0, fade - dt * 5)
            if fade == 0 { cur = want }
        } else {
            fade = min(1, fade + dt * (d?.section == "drop" ? 6 : 1.5))
        }

        let bp = f.bp ?? f.t * h.bpm / 60
        let b = f.bands
        let bass = min(1, ((b.first ?? 0) + (b.count > 1 ? b[1] : 0)) / 2)
        let cols = colours(d?.palette)
        let bandsV = SIMD4<Float>(bass, b.count > 2 ? b[2] : 0, b.count > 3 ? b[3] : (b.last ?? 0), 0)
        var target: Float
        sound += (SIMD3(bandsV.x, bandsV.y, bandsV.z) - sound) * min(1, dt * 9)
        if cur.scene == .psychedelic {
            let fx = f.fx
            let mean = fx.isEmpty ? 0 : fx.reduce(Float(0)) { $0 + min(1, ($1.first ?? 0) + ($1.count > 4 ? $1[4] : 0)) } / Float(fx.count)
            target = mean < 0.01 ? 0.05 : min(1, 0.3 + 1.4 * mean)
        } else {
            draw(f, d, h, cols, bp, bass, dt)
            let calm = d?.section != "drop" && d?.section != "buildup"
            target = cur.mode == "off" ? 0 : cur.scene == .ambient ? 0.4 : cur.scene == .starfield && calm ? 0.55 : 0.95
        }
        level += (target * min(1, wall * 2) * fade - level) * min(1, dt * 10)
        // the wall flashes with the lights: the share of the rig that strobes, on its beat grid, and the blinders and
        // strobe lights when they fire (the engine holds all of it to the set's flash limit); a short tail after it
        var flashNow: Float = 0
        if force != .off, wall >= 0.5 {
            if let s = f.strobe, s.x >= 0.15 { flashNow = s.y * min(1, 0.35 + 1.3 * s.x) }
            var sum: Float = 0, n: Float = 0
            for (i, fixture) in h.fixtures.enumerated() where (fixture.kind == .blinder || fixture.kind == .strobe) && i < f.fx.count {
                sum += f.fx[i].first ?? 0; n += 1
            }
            // (their hit, not their light: one held on is let go of in half a second, or the wall would stay white)
            let blind = n > 0 ? sum / n : 0
            blindHeld += (blind - blindHeld) * min(1, dt * (blind > blindHeld ? 2.5 : 8))
            if blind - blindHeld > 0.15 { flashNow = max(flashNow, min(1, (blind - blindHeld) * 1.6)) }
        }
        flash = max(flashNow, flash - dt * 12)
        // the overlay layer, as a VJ lays one over the picture: a mask per phrase in the style's taste; the picture
        // lifts through it on every beat of the parts with energy, and the strobe's flash shows through it
        let beatNow = Int(floor(bp)), phase = Float(bp - floor(bp)), section = d?.section ?? ""
        let masks: [Float] = switch WallFamily(h) { case .hard: [5, 3, 1, 7, 6]; case .club: [2, 1, 3, 4, 7]; case .other: [4, 6, 1, 0] }
        let lively = force != .off && wall >= 0.5 && cur.mode != "off" && cur.scene != .ambient
            && ["drop", "chorus", "buildup"].contains(section)
        let lift = lively ? exp(-phase * 5) * (section == "drop" ? 1 : 0.6) * fade : 0
        let layer = SIMD4<Float>(Self.forceMask ?? masks[Self.hash(f.phrase, 91) % masks.count], lift, phase, Float(((beatNow % 2) + 2) % 2))
        return WallState(level: max(level, flash * 0.95), psychedelic: cur.scene == .psychedelic, palette: Palettes.colors(d?.palette),
                          bands: bandsV, scene: cur.scene, flash: flash, layer: layer)
    }

    // MARK: drawing

    private var g: CGContext { context }

    private func colours(_ palette: String?) -> [SIMD3<Float>] {
        Palettes.colors(palette).map { c in
            let m = max(c.max(), 0.01)
            return simd_min(SIMD3<Float>(repeating: 1), 0.25 + 0.75 * c / m)   // brightened: must read on a dark wall
        }
    }

    private func cg(_ c: SIMD3<Float>, _ a: CGFloat = 1) -> CGColor {
        CGColor(srgbRed: CGFloat(c.x), green: CGFloat(c.y), blue: CGFloat(c.z), alpha: a)
    }

    private func neon(_ c: SIMD3<Float>, _ width: CGFloat) {
        g.setStrokeColor(cg(c)); g.setFillColor(cg(c)); g.setLineWidth(width)
        g.setLineCap(.round); g.setLineJoin(.round)
        g.setShadow(offset: .zero, blur: width * 2.2 * scale, color: cg(c))   // a shadow's blur is in pixels, not units
    }

    /// A colour without glow (far, small or many things: a glow per star or window costs too much and reads as mud).
    private func flat(_ c: SIMD3<Float>, _ width: CGFloat) {
        g.setStrokeColor(cg(c)); g.setFillColor(cg(c)); g.setLineWidth(width)
        g.setLineCap(.round); g.setLineJoin(.round)
        g.setShadow(offset: .zero, blur: 0, color: nil)
    }

    /// A colour dimmed towards black: opaque, so it looks the same at any drawing rate (alpha would build up on the trail).
    private func dim(_ c: SIMD3<Float>, _ k: Float) -> SIMD3<Float> { c * max(0, min(1, k)) }

    private func mix(_ a: SIMD3<Float>, _ b: SIMD3<Float>, _ t: Float) -> SIMD3<Float> { a + (b - a) * max(0, min(1, t)) }

    /// A regular polygon (0 sides: a circle) round (x, y).
    private func polygon(_ x: CGFloat, _ y: CGFloat, _ r: CGFloat, sides: Int, rot: CGFloat) -> CGPath {
        let p = CGMutablePath()
        guard sides >= 3 else { p.addEllipse(in: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)); return p }
        for i in 0..<sides {
            let a = rot + CGFloat(i) * 2 * .pi / CGFloat(sides) - .pi / 2
            let pt = CGPoint(x: x + r * cos(a), y: y + r * sin(a))
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        p.closeSubpath()
        return p
    }

    private static func frac(_ v: Double) -> Double { v - floor(v) }

    /// Hard edges: mitred corners, no round caps, no glow (the sharp scenes).
    private func sharp(_ c: SIMD3<Float>, _ width: CGFloat) {
        flat(c, width)
        g.setLineCap(.butt); g.setLineJoin(.miter); g.setMiterLimit(12)
    }

    /// A glow round a wall-sized line, cheaply: a few wide translucent strokes under it (a real glow costs its whole
    /// bounding box, which for these is the wall).
    private func softGlow(_ p: CGPath, _ c: SIMD3<Float>, _ width: CGFloat) {
        g.setShadow(offset: .zero, blur: 0, color: nil)
        for (wide, alpha) in [(7.0, 0.05), (4.6, 0.08), (3.0, 0.13), (1.9, 0.22)] as [(CGFloat, CGFloat)] {
            g.setStrokeColor(cg(c, alpha)); g.setLineWidth(width * wide)
            g.addPath(p); g.strokePath()
        }
    }

    private func path(_ pts: [CGPoint]) -> CGPath {
        let p = CGMutablePath()
        p.addLines(between: pts); p.closeSubpath()
        return p
    }

    private func draw(_ f: Frame, _ d: Decision?, _ h: Hello, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ dt: Float) {
        g.saveGState()
        g.setShadow(offset: .zero, blur: 0, color: nil)
        // a short trail behind moving lines: how much of the last picture fades is set per 1/60 s, so the trail
        // is as short at any drawing rate (a fixed share per picture ghosted when the wall was drawn less often)
        let crisp: Set<WallScene> = [.lines, .grid, .wolf, .spikes]   // sharp scenes leave next to no trail
        let fadeShare = cur.scene == .words ? 0.8 : crisp.contains(cur.scene) ? 0.75 : [.tunnel, .scope, .claws].contains(cur.scene) ? 0.6 : 0.45
        // the tunnel, the stars and the shapes travel with the beat, faster in a drop (a jump in the song is no travel)
        let drop = d?.section == "drop", build = d?.section == "buildup"
        let rate = cur.scene == .starfield ? (drop ? 2.5 : build ? 1.2 : 0.5) : drop ? 2.0 : 1.0
        if let last = lastBp, bp > last, bp - last < 2 { travel += (bp - last) * rate }
        lastBp = bp
        fadeDt += (min(0.1, max(Double(dt), 1 / 240)) - fadeDt) * 0.15
        fadeNow = CGFloat(1 - pow(1 - fadeShare, fadeDt * 60))
        fadeRef = CGFloat(1 - pow(1 - fadeShare, 1.5))
        g.setFillColor(CGColor(gray: 0, alpha: fadeNow))
        g.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
        let phraseFrac = d.map { min(1, max(0, ($0.end > $0.start ? (f.t - $0.start) / ($0.end - $0.start) : 0))) } ?? 0
        if !(cur.mode != "off" && countdown(f, d, h, cols)) {
            switch cur.scene {
            case .runner: runner(d, cols, bp, bass)
            case .dancer: dancer(d, cols, bp)
            case .crowd: crowd(d, cols, bp, bass, phraseFrac)
            case .pong: pong(d, cols, bp)
            case .words: words(h, cols, bp)
            case .equalizer: equalizer(f, cols, dt)
            case .ambient: ambient(cols, dt)
            case .tunnel: tunnel(cols, bass)
            case .starfield: starfield(cols, warp: drop)
            case .scope: scope(cols, bp)
            case .shapes: shapes(cols, bp, drop)
            case .lines: lines(cols, bp, bass, drop)
            case .grid: grid(cols)
            case .wolf: wolf(cols, bp, bass, drop)
            case .claws: claws(cols, bp, drop)
            case .spikes: spikes(f, cols, bp, bass, dt)
            default: break
            }
        }
        g.restoreGState()
    }

    /// What a translucent stroke drawn on every picture settles at (it builds up on the fading last picture), at the
    /// show's 40 pictures a second.
    private func settled(_ a: CGFloat) -> CGFloat { a / (fadeRef + a - fadeRef * a) }

    /// The alpha that brings a stroke drawn on every picture to what `a` looks like at 40 pictures a second, at this
    /// picture's rate: the time between pictures varies (they are drawn on a queue of their own), and a fixed alpha
    /// would make the wall brighter and darker with it, a flicker.
    private func held(_ a: CGFloat) -> CGFloat {
        let t = settled(a)
        return min(1, t * fadeNow / max(0.001, 1 - t * (1 - fadeNow)))
    }

    /// A stick figure: hip at (x, y), size s. Angles: 0 = hanging down, positive = towards +x.
    @discardableResult
    private func figure(_ x: CGFloat, _ y: CGFloat, _ s: CGFloat, lean: CGFloat = 0, head: CGFloat = 0,
                        arms: [[Float]], legs: [[Float]]) -> (CGFloat, CGFloat, CGFloat) {
        func seg(_ x0: CGFloat, _ y0: CGFloat, _ a: CGFloat, _ len: CGFloat) -> CGPoint {
            CGPoint(x: x0 + len * sin(a), y: y0 + len * cos(a))
        }
        let path = CGMutablePath()
        func limb(_ x0: CGFloat, _ y0: CGFloat, _ a: [Float], _ len: CGFloat) {
            let p1 = seg(x0, y0, CGFloat(a[0]), len), p2 = seg(p1.x, p1.y, CGFloat(a[0] + a[1]), len)
            path.move(to: CGPoint(x: x0, y: y0)); path.addLine(to: p1); path.addLine(to: p2)
        }
        let nx = x + sin(lean) * s * 0.42, ny = y - cos(lean) * s * 0.42, r = s * 0.11
        path.move(to: CGPoint(x: x, y: y)); path.addLine(to: CGPoint(x: nx, y: ny))
        for a in arms { limb(nx - sin(lean) * s * 0.04, ny + s * 0.04, a, s * 0.21) }
        for l in legs { limb(x, y, l, s * 0.26) }
        let hx = nx + sin(lean + head) * r * 1.25, hy = ny - cos(lean + head) * r * 1.25
        path.addEllipse(in: CGRect(x: hx - r, y: hy - r, width: r * 2, height: r * 2))
        g.addPath(path); g.strokePath()
        return (hx, hy, r)
    }

    private func runner(_ d: Decision?, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float) {
        let s: CGFloat = 150, gy: CGFloat = ground - 60, rx = (cw * 0.36).rounded(), drop = d?.section == "drop"
        let speed = drop ? 90.0 : 60.0, scroll = bp * speed
        let c1 = cols[1 % cols.count]
        // a moon, and a far skyline that passes slowly
        flat(dim(c1, 0.5), 2)
        g.strokeEllipse(in: CGRect(x: cw * 0.78 - 24, y: gy - 222, width: 48, height: 48))
        g.strokeEllipse(in: CGRect(x: cw * 0.78 - 6, y: gy - 212, width: 9, height: 9))
        flat(dim(c1, 0.3), 1.5)
        let far = CGMutablePath(), offF = scroll * 0.12
        for i in -1..<(Int(cw / 44) + 2) {
            let b = i + Int(floor(offF / 44)), x = CGFloat(Double(i) * 44 - Self.frac(offF / 44) * 44)
            let h = CGFloat(70 + Self.hash(b, 14) % 85)
            far.move(to: CGPoint(x: x, y: gy)); far.addLine(to: CGPoint(x: x, y: gy - h))
            far.addLine(to: CGPoint(x: x + 36, y: gy - h)); far.addLine(to: CGPoint(x: x + 36, y: gy))
        }
        g.addPath(far); g.strokePath()
        // the near skyline, its windows lit here and there
        neon(c1, 2)
        g.setAlpha(held(0.45))
        let sky = CGMutablePath(), lit = CGMutablePath(), off = scroll * 0.3
        for i in -1..<(Int(cw / 70) + 2) {
            let b = i + Int(floor(off / 70)), x = CGFloat(Double(i) * 70 - Self.frac(off / 70) * 70)
            let h = CGFloat(40 + Self.hash(b) % 90)
            sky.move(to: CGPoint(x: x, y: gy)); sky.addLine(to: CGPoint(x: x, y: gy - h))
            sky.addLine(to: CGPoint(x: x + 52, y: gy - h)); sky.addLine(to: CGPoint(x: x + 52, y: gy))
            for row in 0..<Int((h - 12) / 16) {
                for col in 0..<3 where Self.hash(b * 31 + row * 7 + col, 6) % 3 == 0 {
                    lit.addRect(CGRect(x: x + 8 + CGFloat(col) * 14, y: gy - h + 9 + CGFloat(row) * 16, width: 8, height: 7))
                }
            }
        }
        g.addPath(sky); g.strokePath()
        g.setAlpha(1)
        flat(dim(mix(c1, [1, 0.9, 0.6], 0.5), 0.55), 1)
        g.addPath(lit); g.fillPath()
        // the road: its marks pass at the runner's speed
        flat(dim(cols[0], 0.5), 2)
        var marks: [CGPoint] = []
        for i in -1..<(Int(cw / 80) + 2) {
            let x = CGFloat(Double(i) * 80 - Self.frac(scroll / 80) * 80)
            marks += [CGPoint(x: x, y: gy + 18), CGPoint(x: x + 34, y: gy + 18)]
        }
        if gy + 18 < ch { g.strokeLineSegments(between: marks) }
        neon(cols[0], 3)
        g.strokeLineSegments(between: [CGPoint(x: 0, y: gy), CGPoint(x: cw, y: gy)])
        // a hurdle every bar, arriving at the runner on the downbeat
        let bar = bp / 4, hx = rx + CGFloat((ceil(bar) - bar) * 4 * speed)
        g.strokeLineSegments(between: [CGPoint(x: hx - 12, y: gy), CGPoint(x: hx - 12, y: gy - 38),
                                       CGPoint(x: hx + 12, y: gy), CGPoint(x: hx + 12, y: gy - 38),
                                       CGPoint(x: hx - 16, y: gy - 38), CGPoint(x: hx + 16, y: gy - 38),
                                       CGPoint(x: hx - 12, y: gy - 26), CGPoint(x: hx + 12, y: gy - 26)])
        let fromDown = (bp + 0.5).truncatingRemainder(dividingBy: 4) - 0.5
        let jump = abs(fromDown) < 0.5 ? CGFloat(cos(fromDown * .pi)) : 0
        let w = Float(bp * .pi)
        let y = gy - s * 0.5 - CGFloat(abs(cos(w))) * 6 - jump * 70
        // the runner's shadow on the road, smaller while in the air
        flat(dim(cols[0], 0.35), 2)
        let sh = 34 - jump * 14
        g.strokeEllipse(in: CGRect(x: rx - sh, y: gy + 4, width: sh * 2, height: 5))
        neon(cols[0], 5)
        let (hx2, hy2, r): (CGFloat, CGFloat, CGFloat)
        if jump > 0.05 {
            (hx2, hy2, r) = figure(rx, y, s, lean: 0.35, arms: [[-2.4, 0.3], [2.6, -0.2]], legs: [[1.3, -1.9], [-0.4, -1.2]])
        } else {
            (hx2, hy2, r) = figure(rx, y, s, lean: drop ? 0.35 : 0.22,
                                   arms: [[-0.9 * sin(w), 1.5], [0.9 * sin(w), 1.5]],
                                   legs: [[0.75 * sin(w), -0.2 - 1.1 * max(0, sin(w + 1.2))],
                                          [-0.75 * sin(w), -0.2 - 1.1 * max(0, -sin(w + 1.2))]])
        }
        if drop || bass > 0.7 {  // speed lines and a drop of sweat
            g.setLineWidth(2)
            var pts: [CGPoint] = []
            for i in 0..<4 {
                let ly = y - 40 + CGFloat(i) * 22
                pts += [CGPoint(x: rx - 80 - CGFloat(i) * 12, y: ly), CGPoint(x: rx - 120 - CGFloat(i) * 20, y: ly)]
            }
            g.strokeLineSegments(between: pts)
            let t = CGFloat(bp.truncatingRemainder(dividingBy: 1))
            g.fillEllipse(in: CGRect(x: hx2 - r - 9 - t * 20, y: hy2 - r - 3 + t * 25, width: 6, height: 6))
        }
    }

    static let moves: [String: [[Float]]] = [
        "down": [[-0.25, 0.2], [0.25, -0.2]], "up": [[-2.6, 0], [2.6, 0]], "hips": [[-0.9, 1.9], [0.9, -1.9]],
        "disco": [[-0.5, 1.5], [2.75, 0]], "disco2": [[-2.75, 0], [0.5, -1.5]], "robot": [[-1.57, -1.57], [1.57, 1.57]],
        "robot2": [[-1.57, 1.57], [1.57, -1.57]], "clap": [[-2.9, 0.6], [2.9, -0.6]], "point": [[-0.3, 0.2], [1.6, 0]],
    ]
    static let routines = [["disco", "down", "disco", "down"], ["robot", "robot2", "robot", "robot2"],
                           ["hips", "clap", "hips", "clap"], ["point", "disco2", "point", "up"], ["up", "down", "up", "clap"]]

    private func dancer(_ d: Decision?, _ cols: [SIMD3<Float>], _ bp: Double) {
        let beat = Int(floor(bp)), u = Float(bp - floor(bp)), drop = d?.section == "drop"
        let routine = Self.routines[Self.hash(beat / 8, 3) % Self.routines.count]
        let want = drop && beat % 4 == 0 ? Self.moves["up"]! : Self.moves[routine[beat % 4]]!
        if beat != lastBeat { fromPose = Self.moves[routine[(beat + 3) % 4]]!; lastBeat = beat }
        let k = min(1, u / 0.18)
        let arms = (0..<2).map { i in (0..<2).map { j in fromPose[i][j] + (want[i][j] - fromPose[i][j]) * k } }
        let dip = sin(u * .pi)
        let hop: CGFloat = drop && beat % 4 == 0 ? CGFloat(sin(u * .pi)) * 60 : 0
        let legs: [[Float]] = hop > 0 ? [[-0.6, 1.4], [0.6, -1.4]] : [[-0.25 - 0.25 * dip, 0.5 * dip], [0.25 + 0.25 * dip, -0.5 * dip]]
        let mx = cw / 2, floorY = ground - 15, hipY = ground - 155
        // two spotlights from above, swaying over the dancer
        g.setShadow(offset: .zero, blur: 0, color: nil)
        for (i, x0) in [mx - min(cw * 0.32, 260), mx + min(cw * 0.32, 260)].enumerated() {
            let xf = mx + CGFloat(sin(bp * .pi / 4 + Double(i) * 2.4)) * 70
            let cone = CGMutablePath()
            cone.move(to: CGPoint(x: x0 - 6, y: floorY - 330)); cone.addLine(to: CGPoint(x: x0 + 6, y: floorY - 330))
            cone.addLine(to: CGPoint(x: xf + 75, y: floorY)); cone.addLine(to: CGPoint(x: xf - 75, y: floorY)); cone.closeSubpath()
            g.setFillColor(cg(cols[(i + 1) % cols.count], held(0.07)))
            g.addPath(cone); g.fillPath()
        }
        // a disco ball: it turns, and throws a few sparks on the beat
        let by = floorY - 318, br: CGFloat = 20
        flat(dim(cols[1 % cols.count], 0.7), 1.5)
        g.strokeLineSegments(between: [CGPoint(x: mx, y: by - br), CGPoint(x: mx, y: by - br - 22)])
        g.strokeEllipse(in: CGRect(x: mx - br, y: by - br, width: br * 2, height: br * 2))
        for j in 0..<3 {
            let wj = br * CGFloat(abs(cos(bp * .pi / 8 + Double(j) * .pi / 3)))
            g.strokeEllipse(in: CGRect(x: mx - wj, y: by - br, width: wj * 2, height: br * 2))
        }
        g.strokeLineSegments(between: [CGPoint(x: mx - br * 0.95, y: by - 7), CGPoint(x: mx + br * 0.95, y: by - 7),
                                       CGPoint(x: mx - br * 0.95, y: by + 7), CGPoint(x: mx + br * 0.95, y: by + 7)])
        neon(cols[0], 2)
        var sparks: [CGPoint] = []
        for j in 0..<6 {
            let a = Double(Self.hash(beat * 6 + j, 17) % 628) / 100, r0 = br + 6 + CGFloat(u) * 26
            sparks += [CGPoint(x: mx + r0 * CGFloat(cos(a)), y: by + r0 * CGFloat(sin(a))),
                       CGPoint(x: mx + (r0 + 9) * CGFloat(cos(a)), y: by + (r0 + 9) * CGFloat(sin(a)))]
        }
        if u < 0.6 { g.strokeLineSegments(between: sparks) }
        let n = 8 + 2 * max(0, Int((cw - 640) / 140))
        for i in 0..<n {  // the dance floor lights up with the beat
            let on = Self.hash(i + beat * 8, 1) % 3 == 0
            neon(cols[i % cols.count], 2)
            let x0 = mx + CGFloat(i - n / 2) * 70, x1 = x0 + 70
            let p = CGMutablePath()
            p.move(to: CGPoint(x: x0 + (x0 - mx) * 0.4, y: floorY)); p.addLine(to: CGPoint(x: x1 + (x1 - mx) * 0.4, y: floorY))
            p.addLine(to: CGPoint(x: x1, y: floorY - 45)); p.addLine(to: CGPoint(x: x0, y: floorY - 45)); p.closeSubpath()
            if on {   // a lit tile glows
                g.setFillColor(cg(cols[i % cols.count], held(0.16)))
                g.addPath(p); g.fillPath()
            }
            g.setAlpha(held(on ? 0.55 : 0.12))
            g.addPath(p); g.strokePath()
            g.setAlpha(1)
        }
        // two backing dancers, a move behind and mirrored
        if cw >= 600 {
            let side = min(cw * 0.3, 250)
            for (i, sx) in [-side, side].enumerated() {
                let pose = i == 0 ? arms : [arms[1].map { -$0 }, arms[0].map { -$0 }]
                neon(dim(cols[(i + 1) % cols.count], 0.75), 3.5)
                figure(mx + sx, hipY + 52 - CGFloat(dip) * 5 - hop * 0.5, 125, head: CGFloat(-0.15 * sin(bp * .pi)),
                       arms: pose, legs: [[-0.25 - 0.2 * dip, 0.4 * dip], [0.25 + 0.2 * dip, -0.4 * dip]])
            }
        }
        neon(cols[0], 6)
        figure(mx, hipY - CGFloat(dip) * 8 - hop, 190, lean: CGFloat(0.07 * sin(bp * .pi)), head: CGFloat(0.15 * sin(bp * .pi)),
               arms: arms, legs: legs)
        if hop > 0 { neon(cols[1 % cols.count], 4); text("!", at: CGPoint(x: mx + 90, y: hipY - 145 - hop * 0.3), size: 46, fill: true) }
    }

    private func crowd(_ d: Decision?, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ phraseFrac: Double) {
        let n = max(4, Int((11 * cw / 640).rounded())), drop = d?.section == "drop", hands = drop || (d?.intensity ?? 1) >= 2
        // light sweeps over the heads
        g.setShadow(offset: .zero, blur: 0, color: nil)
        for k in 0..<2 {
            let x0 = cw * (k == 0 ? 0.25 : 0.75), xf = x0 + CGFloat(sin(bp * .pi / 4 + Double(k) * 2)) * ground * 0.55
            let beam = CGMutablePath()
            beam.move(to: CGPoint(x: x0 - 5, y: ground - 345)); beam.addLine(to: CGPoint(x: x0 + 5, y: ground - 345))
            beam.addLine(to: CGPoint(x: xf + 55, y: ground)); beam.addLine(to: CGPoint(x: xf - 55, y: ground)); beam.closeSubpath()
            g.setFillColor(cg(cols[(k + 1) % cols.count], held(0.06)))
            g.addPath(beam); g.fillPath()
        }
        // the back row: smaller, dimmer, half a beat behind
        for i in 0...n {
            let x = 40 + (CGFloat(i) - 0.5) * (cw - 80) / CGFloat(n - 1), s = CGFloat(72 + Self.hash(i, 8) % 16)
            let u = Self.frac(bp - 0.5 - Double(i) * 0.09)
            let jump = CGFloat(max(0, sin(u * .pi))) * (drop ? 24 : 8 + 12 * CGFloat(bass))
            flat(dim(cols[(i + 1) % cols.count], 0.42), 2)
            figure(x, ground - 62 - s * 0.5 - jump, s,
                   arms: hands ? [[-2.8, 0.2], [2.8, -0.2]] : [[-0.3, 0.4], [0.3, -0.4]], legs: [[-0.2, 0], [0.2, 0]])
        }
        for i in 0..<n {
            let x = 40 + CGFloat(i) * (cw - 80) / CGFloat(n - 1), s = CGFloat(105 + Self.hash(i, 5) % 25)
            let u = drop ? bp.truncatingRemainder(dividingBy: 1) : (bp - Double(i) * 0.12).truncatingRemainder(dividingBy: 1)
            let jump = CGFloat(max(0, sin(u * .pi))) * (drop ? 40 : 14 + 22 * CGFloat(bass))
            let wave = hands ? Float(0.25 * sin(bp * .pi + Double(i))) : 0
            neon(cols[i % cols.count], 3)
            figure(x, ground - 15 - s * 0.5 - jump, s, head: CGFloat(0.12 * sin(bp * .pi + Double(i))),
                   arms: hands ? [[-2.7 + wave, 0], [2.7 + wave, 0]] : [[-0.3, 0.4], [0.3, -0.4]],
                   legs: jump > 4 ? [[-0.5, 0.6], [0.5, -0.6]] : [[-0.2, 0], [0.2, 0]])
        }
        if drop {  // confetti comes down over a drop
            g.setShadow(offset: .zero, blur: 0, color: nil)
            for i in 0..<Int(46 * cw / 640) {
                let fall = Self.frac(Double(Self.hash(i, 22) % 1000) / 1000 + bp * (0.1 + Double(Self.hash(i, 23) % 10) / 80))
                let x = CGFloat(Self.hash(i, 21) % Int(cw)) + CGFloat(sin(bp * 2 + Double(i))) * 10
                g.setFillColor(cg(cols[i % cols.count]))
                g.fill(CGRect(x: x, y: CGFloat(fall) * ground, width: i % 2 == 0 ? 6 : 3, height: i % 2 == 0 ? 3 : 6))
            }
        }
        if hands {  // a crowd surfer, carried across during the phrase
            neon(cols[0], 4)
            g.saveGState()
            g.translateBy(x: 20 + CGFloat(phraseFrac) * (cw - 40), y: ground - 232 + CGFloat(4 * sin(bp * .pi)))
            g.rotate(by: -.pi / 2)
            figure(0, 0, 80, arms: [[-2.9, 0], [2.6, 0.3]], legs: [[Float(-0.25 + 0.3 * sin(bp * 2)), 0.3], [0.25, 0]])
            g.restoreGState()
        }
    }

    private func pong(_ d: Decision?, _ cols: [SIMD3<Float>], _ bp: Double) {
        let drop = d?.section == "drop"
        func tri(_ v: Double) -> Double { 1 - abs(((v.truncatingRemainder(dividingBy: 2)) + 2).truncatingRemainder(dividingBy: 2) - 1) }
        neon(cols[0], 3)
        g.setLineDash(phase: 0, lengths: [10, 14])
        g.strokeLineSegments(between: [CGPoint(x: cw / 2, y: 10), CGPoint(x: cw / 2, y: ch - 10)])
        g.setLineDash(phase: 0, lengths: [])
        text(String(Int(bp / 4) % 100), at: CGPoint(x: cw / 2 - 70, y: 70), size: 54, fill: true, mono: true)
        text(String(Int(bp / 7) % 100), at: CGPoint(x: cw / 2 + 70, y: 70), size: 54, fill: true, mono: true)
        var yL: CGFloat = ch / 2, yR: CGFloat = ch / 2
        let offsets: [Double] = drop ? [0, 0.33, 0.66] : [0]
        for (i, o) in offsets.enumerated() {
            let x = 52 + CGFloat(tri(bp + o)) * (cw - 104), y = 20 + CGFloat(tri(bp * 0.37 + o * 1.7 + 0.3)) * (ch - 40)
            neon(cols[i % cols.count], 3)
            g.fill(CGRect(x: x - 8, y: y - 8, width: 16, height: 16))
            if x < cw / 2 { yL = y } else { yR = y }
        }
        neon(cols[0], 3)
        g.fill(CGRect(x: 28, y: yL - 40, width: 12, height: 80))
        g.fill(CGRect(x: cw - 40, y: yR - 40, width: 12, height: 80))
    }

    private func words(_ h: Hello, _ cols: [SIMD3<Float>], _ bp: Double) {
        var title = h.title
        for pattern in [#"^\d+\s*[-_.]\s*"#, #"[\[(].*?[\])]"#] {
            title = title.replacingOccurrences(of: pattern, with: "", options: .regularExpression)
        }
        let ws = title.replacingOccurrences(of: "_", with: " ").components(separatedBy: CharacterSet(charactersIn: " -"))
            .filter { !$0.isEmpty }
        guard !ws.isEmpty else { return }
        let beat = Int(floor(bp)), u = bp - floor(bp), w = ws[beat % ws.count].uppercased()
        let c = cols[beat % cols.count]
        // every word comes in its own way: punched in, slid in from a side, dropped from above
        let kind = Self.hash(beat, 31) % 4, arrive = CGFloat(1 - pow(1 - min(1, u * 5), 3))
        var size = min(170, 1000 / CGFloat(max(3, w.count))) * min(1.6, cw / 640), at = CGPoint(x: cw / 2, y: ch / 2)
        switch kind {
        case 1: at.x += (beat % 2 == 0 ? -1 : 1) * cw * 0.5 * (1 - arrive)
        case 2: at.y -= ch * 0.45 * (1 - arrive) - CGFloat(sin(min(1, u * 5) * .pi)) * 10
        default: size *= CGFloat(1 + 0.25 * max(0, 1 - u * 4))
        }
        // on the bar's first beat the word echoes outwards
        if beat % 4 == 0 {
            for e in 1...2 {
                flat(dim(c, 0.45 - 0.15 * Float(e)), 2)
                text(w, at: at, size: size * (1 + CGFloat(e) * 0.16 * (0.4 + CGFloat(u))), fill: false)
            }
        }
        // two bars frame it, opening with the beat
        let half = cw * 0.36 * (0.35 + 0.65 * arrive), by = size * 0.48
        flat(dim(cols[(beat + 1) % cols.count], 0.6), 3)
        g.strokeLineSegments(between: [CGPoint(x: cw / 2 - half, y: ch / 2 - by), CGPoint(x: cw / 2 + half, y: ch / 2 - by),
                                       CGPoint(x: cw / 2 - half, y: ch / 2 + by), CGPoint(x: cw / 2 + half, y: ch / 2 + by)])
        neon(c, 5)
        text(w, at: at, size: size, fill: u < 0.15)
    }

    /// The spectrum's bars (and their falling caps), from the frame's bands.
    private func meter(_ f: Frame, _ dt: Float) {
        let b = f.bands, n = eq.count, now = Float(Date().timeIntervalSinceReferenceDate)
        for i in 0..<n {
            let pos = Float(i) / Float(n - 1) * Float(max(b.count - 1, 1)), j = Int(pos), k = pos - Float(j)
            let lo = j < b.count ? b[j] : 0, hi = j + 1 < b.count ? b[j + 1] : lo
            let v = min(1, max(0, (lo + (hi - lo) * k) * (0.85 + 0.3 * sin(Float(i) * 2.3 + now * 5.5))))
            eq[i] = max(v, eq[i] - dt * 2.2)   // a held level holds (falling only where the music fell)
            caps[i] = max(eq[i], caps[i] - dt * 0.6)
        }
    }

    private func equalizer(_ f: Frame, _ cols: [SIMD3<Float>], _ dt: Float) {
        meter(f, dt)
        let n = eq.count
        // the bars stand on a line with their reflection under it
        let bw = cw / CGFloat(n), mirror = min(64, ch * 0.16), base = ch - 16 - mirror, top = base - 44
        let white = SIMD3<Float>(repeating: 1)
        for i in 0..<n {
            let t = Float(i) / Float(n - 1) * Float(cols.count - 1), ci = min(cols.count - 1, Int(t))
            let c = mix(cols[ci], cols[min(cols.count - 1, ci + 1)], t - Float(ci))   // the palette runs across the wall
            let h = CGFloat(eq[i]) * top, x = CGFloat(i) * bw + 6, segs = Int(ceil(h / 16))
            flat(dim(c, 0.22), 2)
            for sgm in 0..<min(segs, Int(mirror / 16)) {
                g.stroke(CGRect(x: x, y: base + 6 + CGFloat(sgm) * 16, width: bw - 12, height: 10))
            }
            neon(c, 3)
            for sgm in 0..<segs {
                if sgm == segs - 1, segs > 1 {   // the top of a bar burns hot
                    neon(mix(c, white, 0.6), 3)
                    g.fill(CGRect(x: x, y: base - 12 - CGFloat(sgm) * 16, width: bw - 12, height: 10))
                }
                g.stroke(CGRect(x: x, y: base - 12 - CGFloat(sgm) * 16, width: bw - 12, height: 10))
            }
            neon(mix(c, white, 0.35), 3)
            g.fill(CGRect(x: x, y: base - 10 - CGFloat(caps[i]) * top - 8, width: bw - 12, height: 4))
        }
        flat(dim(cols[0], 0.5), 1.5)
        g.strokeLineSegments(between: [CGPoint(x: 0, y: base + 2), CGPoint(x: cw, y: base + 2)])
    }

    private func ambient(_ cols: [SIMD3<Float>], _ dt: Float) {
        amb += Double(dt) * 0.15
        g.setShadow(offset: .zero, blur: 0, color: nil)
        // slow clouds need no trail: drawn afresh on black each picture, as bright as they settled at 40 a second
        g.setFillColor(CGColor(gray: 0, alpha: 1))
        g.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
        let stops: [CGFloat] = [0, 0.25, 0.5, 0.75, 1]
        for (i, c) in cols.enumerated() {
            let x = Double(cw) / 2 + (Double(cw) / 2 - 90) * sin(amb * (0.7 + Double(i) * 0.23) + Double(i) * 2)
            let y = Double(ch) / 2 + (Double(ch) / 2 - 70) * cos(amb * (0.5 + Double(i) * 0.17) + Double(i))
            let grad = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                                  colors: stops.map { cg(c, settled(0.5 * (1 - $0))) } as CFArray,
                                  locations: stops)!
            g.drawRadialGradient(grad, startCenter: CGPoint(x: x, y: y), startRadius: 0,
                                 endCenter: CGPoint(x: x, y: y), endRadius: max(260, max(cw, ch) * 0.4), options: [])
        }
        // out-of-focus lights drift up through the clouds and breathe with the bass
        let count = max(8, Int(14 * cw * ch / CGFloat(Self.W * Self.H)))
        for i in 0..<count {
            let rise = Self.frac(Double(Self.hash(i, 41) % 1000) / 1000 + amb * (0.05 + Double(Self.hash(i, 42) % 10) / 150))
            let x = CGFloat(Self.hash(i, 43) % Int(cw)) + CGFloat(sin(amb * 0.8 + Double(i))) * 18
            let y = ch + 40 - CGFloat(rise) * (ch + 80)
            let r = CGFloat(10 + Self.hash(i, 44) % 22) * CGFloat(1 + 0.25 * sound.x)
            let near = CGFloat(sin(rise * .pi))   // in and out softly at the edges
            let c = mix(cols[i % cols.count], [1, 1, 1], 0.25)
            g.setFillColor(cg(c, 0.07 * near)); g.fillEllipse(in: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2))
            g.setStrokeColor(cg(c, 0.16 * near)); g.setLineWidth(1.5)
            g.strokeEllipse(in: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2))
        }
    }

    // MARK: abstract scenes

    /// A neon tunnel flown through: a ring passes on every beat travelled, the far end sways.
    private func tunnel(_ cols: [SIMD3<Float>], _ bass: Float) {
        let n = 16, first = Int(floor(travel)), f = Self.frac(travel)
        var last: [CGPoint]?
        let rails = CGMutablePath()
        var rings: [(pts: [CGPoint], s: CGFloat, idx: Int)] = []
        for k in 0..<n {   // from the nearest ring into the depth
            let z = Double(k) + 1 - f, s = CGFloat(1 / (1 + z * 0.55))
            let far = CGFloat(1 - s)   // the depth sways, the opening stays put
            let bend = far * far   // only the far end leaves the middle: the tunnel bends, it doesn't slide
            let cx = cw / 2 + CGFloat(sin(travel * 0.21 + z * 0.18)) * cw * 0.13 * bend
            let cy = ch / 2 + CGFloat(cos(travel * 0.17 + z * 0.15)) * ch * 0.11 * bend
            let hw = cw * 0.86 * s, hh = ch * 0.86 * s, tilt = CGFloat(sin(travel * 0.13 + z * 0.1)) * 0.1 * bend
            let pts = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)].map { (sx: Double, sy: Double) -> CGPoint in
                let x = CGFloat(sx) * hw, y = CGFloat(sy) * hh
                return CGPoint(x: cx + x * cos(tilt) - y * sin(tilt), y: cy + x * sin(tilt) + y * cos(tilt))
            }
            if let l = last { for j in 0..<4 { rails.move(to: l[j]); rails.addLine(to: pts[j]) } }
            last = pts
            rings.append((pts, s, first + k))
        }
        flat(dim(cols[1 % cols.count], 0.4), 1.5)
        g.addPath(rails); g.strokePath()
        for r in rings.reversed() {   // far rings first
            let c = cols[((r.idx % cols.count) + cols.count) % cols.count]
            let hit = r.idx % 4 == 0 ? 1 + CGFloat(bass) * 0.8 : 1   // every fourth ring swells with the kick
            let p = CGMutablePath()
            p.addLines(between: r.pts); p.closeSubpath()
            // the glow is a wide dim stroke under the line: a real glow round sixteen wall-sized rings costs too much
            let k = Float(0.25 + 1.1 * r.s), width = (1.2 + 5 * r.s) * hit
            if r.s > 0.3 {
                flat(dim(c, k), 1)
                for (wide, alpha) in [(7.0, 0.05), (4.6, 0.08), (3.0, 0.13), (1.9, 0.22)] as [(CGFloat, CGFloat)] {
                    g.setStrokeColor(cg(dim(c, k), alpha)); g.setLineWidth(width * wide)
                    g.addPath(p); g.strokePath()
                }
            }
            flat(dim(c, k), width)
            g.addPath(p); g.strokePath()
        }
    }

    /// Stars streaming out of the middle: a calm drift, streaks at warp speed in a drop.
    private func starfield(_ cols: [SIMD3<Float>], warp: Bool) {
        let n = min(420, Int(150 * cw * ch / CGFloat(Self.W * Self.H))), reach = Double(hypot(cw, ch)) / 2 * 1.05
        let white = SIMD3<Float>(repeating: 1)
        var tiers = [[CGPoint]](repeating: [], count: 3 * cols.count)
        var bright: [(CGPoint, CGFloat, SIMD3<Float>)] = []
        for i in 0..<n {
            let a = Double(Self.hash(i, 11) % 6283) / 1000, speed = 0.3 + Double(Self.hash(i, 12) % 100) / 140
            let u = Self.frac(Double(Self.hash(i, 13) % 1000) / 1000 + travel * speed * 0.22)
            let r1 = 6 + u * u * reach, streak = (warp ? 0.22 : 0.035) * (0.3 + u), r0 = r1 * (1 - streak)
            let p1 = CGPoint(x: cw / 2 + CGFloat(cos(a) * r1), y: ch / 2 + CGFloat(sin(a) * r1))
            let p0 = CGPoint(x: cw / 2 + CGFloat(cos(a) * r0), y: ch / 2 + CGFloat(sin(a) * r0))
            let tier = u < 0.35 ? 0 : u < 0.7 ? 1 : 2
            tiers[tier * cols.count + i % cols.count] += [p0, p1]
            if i % 9 == 0, u > 0.45 { bright.append((p1, CGFloat(2 + 5 * u), mix(cols[i % cols.count], white, 0.5))) }
        }
        for tier in 0..<3 {
            for ci in 0..<cols.count where !tiers[tier * cols.count + ci].isEmpty {
                flat(dim(mix(cols[ci], white, 0.35), [0.35, 0.7, 1][tier]), [1, 1.6, 2.4][tier])
                g.strokeLineSegments(between: tiers[tier * cols.count + ci])
            }
        }
        for (p, r, c) in bright {   // a few near stars flare
            neon(c, 1.5)
            g.strokeLineSegments(between: [CGPoint(x: p.x - r, y: p.y), CGPoint(x: p.x + r, y: p.y),
                                           CGPoint(x: p.x, y: p.y - r), CGPoint(x: p.x, y: p.y + r)])
        }
    }

    /// An oscilloscope: one line each for the bass, the mids and the highs, over a faint graticule.
    private func scope(_ cols: [SIMD3<Float>], _ bp: Double) {
        flat(dim(cols[1 % cols.count], 0.16), 1)
        var grid: [CGPoint] = []
        let cell = ch / 6
        var gx = cw / 2 - floor(cw / 2 / cell) * cell
        while gx < cw { grid += [CGPoint(x: gx, y: 0), CGPoint(x: gx, y: ch)]; gx += cell }
        var gy = ch / 2 - floor(ch / 2 / cell) * cell
        while gy < ch { grid += [CGPoint(x: 0, y: gy), CGPoint(x: cw, y: gy)]; gy += cell }
        g.strokeLineSegments(between: grid)
        let levels = [sound.x, sound.y, sound.z], waves = [1.5, 4.0, 9.0], runs = [1.0, 2.0, 4.0], widths: [CGFloat] = [5, 3.5, 2.5]
        for r in 0..<3 {
            let y0 = ch * (0.5 + CGFloat(r - 1) * 0.25), amp = ch * 0.17 * CGFloat(0.12 + min(1, levels[r] * 1.3))
            let cycles = waves[r] * Double(cw) / Double(Self.W)
            let p = CGMutablePath()
            var x: CGFloat = 0
            while x <= cw {
                let t = Double(x / cw), env = sin(t * .pi)   // pinned at both ends
                let v = 0.7 * sin(2 * .pi * cycles * t - bp * .pi * runs[r])
                      + 0.3 * sin(2 * .pi * cycles * 2.7 * t + bp * .pi * 1.3 + Double(r))
                let pt = CGPoint(x: x, y: y0 + amp * CGFloat(env * v))
                if x == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
                x += 5
            }
            neon(cols[r % cols.count], widths[r])
            g.addPath(p); g.strokePath()
        }
    }

    /// Nested triangles, squares, hexagons and circles turning against each other; one of them kicks out every beat.
    private func shapes(_ cols: [SIMD3<Float>], _ bp: Double, _ drop: Bool) {
        let beat = Int(floor(bp)), u = bp - floor(bp), bar = beat / 4
        let wide = cw >= ch, long = max(cw, ch), short = min(cw, ch)
        let groups = max(1, Int((long / short / 1.6).rounded()))
        let kinds = [3, 4, 6, 0]
        for gi in 0..<groups {
            let along = long * (CGFloat(gi) + 0.5) / CGFloat(groups)
            let x = wide ? along : cw / 2, y = wide ? ch / 2 : along
            let radius = min(long / CGFloat(groups), short) * 0.44
            for j in 0..<(drop ? 5 : 4) {
                let sides = kinds[(j + Self.hash(bar, 4) + gi) % 4]
                let kick = (beat + gi) % 4 == j % 4 ? CGFloat(exp(-u * 4)) : 0
                let r = radius * (1 - CGFloat(j) * 0.19) * (1 + kick * 0.13)
                let turn = CGFloat(travel * .pi / 8) * (j % 2 == 0 ? 1 : -1) * (1 + CGFloat(j) * 0.25) + CGFloat(j + gi)
                neon(cols[(j + gi) % cols.count], 4 - CGFloat(j) * 0.5 + kick * 4)
                g.addPath(polygon(x, y, r, sides: sides, rot: turn)); g.strokePath()
            }
            neon(cols[gi % cols.count], 3)
            let dot = 5 + CGFloat(exp(-u * 5)) * 9
            g.fillEllipse(in: CGRect(x: x - dot, y: y - dot, width: dot * 2, height: dot * 2))
        }
    }

    // MARK: techno and club

    /// Hard vertical bars, a barcode that steps along with the beat; a scanner crosses once a bar.
    private func lines(_ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ drop: Bool) {
        let n = max(12, Int((28 * cw / CGFloat(Self.W)).rounded())), bw = cw / CGFloat(n)
        let beat = Int(floor(bp)), u = bp - floor(bp), bar = beat / 4
        let white = SIMD3<Float>(repeating: 1), kick = Float(exp(-u * 5))
        let shift = Int(floor(travel * 2))   // the code moves two bars' width a beat
        g.setShadow(offset: .zero, blur: 0, color: nil)
        for i in 0..<n {
            let k = i + shift
            guard Self.hash(k, 51 + bar % 4) % 5 < (drop ? 3 : 2) else { continue }
            let thin = Self.hash(k, 52) % 3 == 0, accent = Self.hash(k, 53) % 6 == 0
            // a band that breathes across the wall; in a drop the bars stand wall-high
            let wave = 0.5 + 0.5 * sin(Double(i) * 0.45 - bp * .pi / 2)
            let h = drop ? ch : ch * CGFloat(0.22 + 0.5 * wave + 0.25 * Double(bass))
            let c = accent ? cols[0] : mix(cols[1 % cols.count], white, 0.75)
            g.setFillColor(cg(dim(c, 0.4 + 0.6 * kick)))
            let w = thin ? max(2, bw * 0.22) : bw * 0.82
            g.fill(CGRect(x: CGFloat(i) * bw + (bw - w) / 2, y: (ch - h) / 2, width: w, height: h))
        }
        // two cuts through the bars, and the scanner
        g.setFillColor(CGColor(gray: 0, alpha: 1))
        for y in [ch * 0.36, ch * 0.64] { g.fill(CGRect(x: 0, y: y - 2.5, width: cw, height: 5)) }
        let sx = CGFloat(Self.frac(bp / 4)) * cw
        neon(cols[0], 3)
        g.setLineCap(.butt)
        g.strokeLineSegments(between: [CGPoint(x: sx, y: 0), CGPoint(x: sx, y: ch)])
    }

    /// A landscape of ridges coming on, line behind line, rising with the music.
    private func grid(_ cols: [SIMD3<Float>]) {
        let rows = 16, horizon = ch * 0.14, f = Self.frac(travel * 0.5), first = Int(floor(travel * 0.5))
        let loud = CGFloat(0.22 + 0.7 * sound.x + 0.5 * sound.y), white = SIMD3<Float>(repeating: 1)
        g.setShadow(offset: .zero, blur: 0, color: nil)
        for k in stride(from: rows - 1, through: 0, by: -1) {   // the far ridges first: the near ones hide them
            let z = (Double(k) + 1 - f) * 1.35, s = CGFloat(1 / (0.4 + z * 0.3))   // near 1.2 .. far 0.15
            let near = min(1, s / 1.4)
            let y0 = horizon + (ch * 1.08 - horizon) * near
            let half = cw * (0.42 + 0.5 * near), amp = ch * 0.4 * pow(near, 0.55) * loud
            let row = first + k
            let p1 = Double(Self.hash(row, 81) % 628) / 100, p2 = Double(Self.hash(row, 82) % 628) / 100, p3 = Double(Self.hash(row, 83) % 628) / 100
            var pts: [CGPoint] = []
            let steps = 56
            for i in 0...steps {
                let t = Double(i) / Double(steps), env = pow(sin(t * .pi), 2.4)   // the ridge stands in the middle
                let v = abs(0.5 * sin(t * 11 + p1) + 0.32 * sin(t * 27 + p2) + 0.18 * sin(t * 53 + p3))
                pts.append(CGPoint(x: cw / 2 + CGFloat(t * 2 - 1) * half, y: y0 - amp * CGFloat(env * v)))
            }
            let body = CGMutablePath()
            body.addLines(between: pts)
            body.addLine(to: CGPoint(x: pts.last!.x, y: ch + 4)); body.addLine(to: CGPoint(x: pts[0].x, y: ch + 4)); body.closeSubpath()
            g.setFillColor(CGColor(gray: 0, alpha: 1))
            g.setShouldAntialias(false)   // (the line drawn over its edge is the smooth one)
            g.addPath(body); g.fillPath()
            g.setShouldAntialias(true)
            let c = mix(cols[row % cols.count < 0 ? 0 : row % cols.count], white, 0.25)
            let line = CGMutablePath()
            line.addLines(between: pts)
            let shade = dim(c, Float(0.2 + 0.8 * near)), width = 1 + 1.6 * near
            g.setLineCap(.round); g.setLineJoin(.round)
            if k < 3 { softGlow(line, shade, width) }
            flat(shade, width)
            g.setLineJoin(.miter)
            g.addPath(line); g.strokePath()
        }
    }

    // MARK: the harder styles

    private static let wolfPoints: [String: (Double, Double)] = [
        "E": (0.62, -1.18), "Eo": (0.84, -0.42), "En": (0.52, -0.62), "Ei": (0.26, -0.66), "T": (0, -0.56), "B": (0, -0.2),
        "Bo": (0.5, -0.3), "Tm": (0.88, -0.08), "C1": (1.02, 0.34), "C2": (0.7, 0.36), "J": (0.5, 0.74), "Yi": (0.15, -0.06),
        "Yo": (0.56, -0.22), "Yb": (0.38, 0.02), "Nb": (0.13, 0.32), "M": (0.3, 0.56), "N": (0.13, 0.64), "Nt": (0, 0.8),
        "Mc": (0.25, 0.82), "Ch": (0, 1.04), "Nc": (0, 0.3),
    ]
    /// The right half of the head in facets (mirrored for the left); the last one is the lower jaw, which opens.
    private static let wolfFacets: [[String]] = [
        ["E", "Eo", "En"], ["E", "En", "Ei"], ["T", "Ei", "Bo", "B"], ["Ei", "En", "Eo", "Tm", "Bo"], ["B", "Bo", "Yo", "Yi"],
        ["Yo", "Bo", "Tm"], ["Yo", "Tm", "C1", "C2"], ["Yo", "C2", "Yb"], ["B", "Yi", "Nb", "Nc"], ["Yi", "Yb", "M", "Nb"],
        ["Yb", "C2", "J", "M"], ["Nb", "M", "N"], ["Nc", "Nb", "N", "Nt"], ["N", "M", "Mc", "Nt"], ["M", "J", "Mc"],
        ["Nt", "Mc", "Ch"],
    ]

    /// A wolf's head in hard facets: its eyes burn with the bass, facets catch light on the kick, in a drop it bares
    /// its teeth. A wide wall shows a pack.
    private func wolf(_ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ drop: Bool) {
        let beat = Int(floor(bp)), u = bp - floor(bp), kick = Float(exp(-u * 4)), white = SIMD3<Float>(repeating: 1)
        let open = drop ? Double(min(1, 0.25 + bass)) * (0.55 + 0.45 * Double(kick)) : Double(max(0, bass - 0.75)) * 1.2
        func head(_ x0: CGFloat, _ y0: CGFloat, _ size: CGFloat, _ lightK: Float, _ salt: Int) {
            let s = size * CGFloat(1 + 0.035 * Double(bass))
            func pt(_ name: String, _ side: CGFloat) -> CGPoint {
                var (x, y) = Self.wolfPoints[name]!
                if name == "Ch" { y += 0.24 * open } else if name == "Mc" { y += 0.06 * open }
                return CGPoint(x: x0 + side * CGFloat(x) * s, y: y0 + CGFloat(y) * s)
            }
            // a mane of spikes behind the head, thrown out on the kick
            sharp(dim(cols[1 % cols.count], 0.5 * lightK), 1.5)
            let mane = CGMutablePath(), spikes = 18
            for i in 0..<spikes {
                let a = Double(i) / Double(spikes) * 2 * .pi + travel * 0.05
                guard sin(a) < 0.55 else { continue }   // none under the chin
                let long = 1.34 + 0.2 * Double(Self.hash(i + salt, 73) % 100) / 100 + 0.3 * Double(kick)
                let tip = CGPoint(x: x0 + CGFloat(cos(a) * long) * s, y: y0 - 0.1 * s + CGFloat(sin(a) * long) * s)
                for da in [-0.07, 0.07] {
                    mane.move(to: CGPoint(x: x0 + CGFloat(cos(a + da) * 1.02) * s, y: y0 - 0.1 * s + CGFloat(sin(a + da) * 1.02) * s))
                    mane.addLine(to: tip)
                }
            }
            g.addPath(mane); g.strokePath()
            // the facets: each its own shade, the left side in the light, some lit by the kick
            let edges = CGMutablePath()
            for side in [CGFloat(1), -1] {
                for (fi, facet) in Self.wolfFacets.enumerated() {
                    let p = path(facet.map { pt($0, side) })
                    var shade = 0.05 + 0.15 * Float(Self.hash(fi + salt, side > 0 ? 71 : 74) % 100) / 100
                    if side < 0 { shade *= 1.7 }
                    if Self.hash(fi + beat * 17 + (side > 0 ? 0 : 50), 72) % 4 == 0 { shade += 0.4 * kick }
                    g.setShadow(offset: .zero, blur: 0, color: nil)
                    g.setFillColor(cg(dim(mix(cols[1 % cols.count], white, 0.2), shade * lightK)))
                    g.addPath(p); g.fillPath()
                    edges.addPath(p)
                }
            }
            sharp(dim(cols[0], 0.85 * lightK), 1.4)
            g.addPath(edges); g.strokePath()
            // the open mouth is dark, with fangs
            if open > 0.12 {
                g.setFillColor(CGColor(gray: 0, alpha: 1))
                g.addPath(path([pt("Mc", 1), pt("Nt", 1), pt("Mc", -1), CGPoint(x: x0, y: y0 + CGFloat(0.8 + 0.2 * open) * s)])); g.fillPath()
                sharp(dim(white, lightK), 1.2)
                for side in [CGFloat(1), -1] {
                    for (fx, len) in [(0.1, 0.17), (0.2, 0.09)] {
                        let fang = path([CGPoint(x: x0 + side * CGFloat(fx - 0.035) * s, y: y0 + 0.81 * s),
                                         CGPoint(x: x0 + side * CGFloat(fx + 0.035) * s, y: y0 + 0.82 * s),
                                         CGPoint(x: x0 + side * CGFloat(fx) * s, y: y0 + CGFloat(0.82 + len * min(1, open * 1.6)) * s)])
                        g.setFillColor(cg(dim(white, 0.85 * lightK)))
                        g.addPath(fang); g.fillPath()
                    }
                }
            }
            // the nose, and the eyes: they burn
            g.setShadow(offset: .zero, blur: 0, color: nil)
            g.setFillColor(cg(dim(cols[0], 0.5 * lightK)))
            g.addPath(path([pt("N", 1), pt("Nt", 1), pt("N", -1)])); g.fillPath()
            let burn = mix(cols[0], white, 0.35 + 0.65 * max(bass, kick))
            neon(dim(burn, lightK), 2.5 + 2.5 * CGFloat(kick))
            g.setLineJoin(.miter)
            for side in [CGFloat(1), -1] {
                let eye = path([pt("Yi", side), pt("Yo", side), pt("Yb", side)])
                g.addPath(eye); g.fillPath()
                g.addPath(eye); g.strokePath()
            }
        }
        let size = min(cw, ch) * 0.36, cy = ch / 2 + size * 0.06
        if cw / ch > 2.4 {   // a pack: two more behind, smaller and darker
            head(cw / 2 - cw * 0.3, cy + size * 0.12, size * 0.68, 0.55, 5)
            head(cw / 2 + cw * 0.3, cy + size * 0.12, size * 0.68, 0.55, 9)
        }
        head(cw / 2, cy, size, 1, 0)
    }

    /// Claws rip across the wall, one slash every other beat (every beat in a drop); the scars stay a while.
    private func claws(_ cols: [SIMD3<Float>], _ bp: Double, _ drop: Bool) {
        let step = drop ? 1.0 : 2.0, hit = Int(floor(bp / step)), u = bp - Double(hit) * step
        let white = SIMD3<Float>(repeating: 1), long = min(max(cw, ch) * 0.8, min(cw, ch) * 1.9)
        for age in stride(from: 2, through: 0, by: -1) {   // the oldest scar first
            let h = hit - age, since = u + Double(age) * step
            let reveal = age == 0 ? CGFloat(min(1, u / 0.14)) : 1, heat = Float(exp(-since * (drop ? 1.5 : 0.9)))
            let dir: CGFloat = Self.hash(h, 61) % 2 == 0 ? 1 : -1
            let cx = cw * CGFloat(0.3 + 0.4 * Double(Self.hash(h, 62) % 100) / 100), cy = ch * CGFloat(0.4 + 0.2 * Double(Self.hash(h, 63) % 100) / 100)
            let a = 0.85 + 0.35 * Double(Self.hash(h, 64) % 100) / 100   // from the vertical
            let d = CGPoint(x: dir * CGFloat(sin(a)), y: CGFloat(cos(a))), nrm = CGPoint(x: d.y, y: -d.x)
            let count = 3 + Self.hash(h, 65) % 2
            for c in 0..<count {
                let off = (CGFloat(c) - CGFloat(count - 1) / 2) * min(cw, ch) * 0.13
                let len = long * (c == 0 || c == count - 1 ? 0.78 : 1), wide = min(cw, ch) * 0.028
                let start = CGPoint(x: cx + nrm.x * off - d.x * len / 2, y: cy + nrm.y * off - d.y * len / 2)
                let end = CGPoint(x: start.x + d.x * len * reveal, y: start.y + d.y * len * reveal)
                let mid = CGPoint(x: start.x + (end.x - start.x) * 0.4, y: start.y + (end.y - start.y) * 0.4)
                let blade = path([start, CGPoint(x: mid.x + nrm.x * wide, y: mid.y + nrm.y * wide), end,
                                  CGPoint(x: mid.x - nrm.x * wide, y: mid.y - nrm.y * wide)])
                if age == 0 {
                    let hot = mix(cols[0], white, heat)
                    g.setLineCap(.round); g.setLineJoin(.round)
                    softGlow(blade, hot, 2)
                    sharp(hot, 1.5)
                    g.setFillColor(cg(hot))
                } else {
                    sharp(dim(cols[0], 0.18 + 0.6 * heat), 1.2)
                    g.setFillColor(cg(dim(cols[0], 0.08 + 0.3 * heat)))
                }
                g.setLineJoin(.miter)
                g.addPath(blade); g.fillPath()
                g.addPath(blade); g.strokePath()
            }
            if age == 0 {   // shards fly off the fresh slash
                sharp(dim(mix(cols[1 % cols.count], white, 0.5), heat), 1)
                for i in 0..<16 {
                    let along = CGFloat(Self.hash(h * 16 + i, 66) % 100) / 100 - 0.5, sideways: CGFloat = i % 2 == 0 ? 1 : -1
                    let fly = CGFloat(u) * min(cw, ch) * CGFloat(0.25 + 0.5 * Double(Self.hash(h * 16 + i, 67) % 100) / 100)
                    let o = CGPoint(x: cx + d.x * long * along + nrm.x * sideways * (min(cw, ch) * 0.1 + fly),
                                    y: cy + d.y * long * along + nrm.y * sideways * (min(cw, ch) * 0.1 + fly))
                    let r = 3 + CGFloat(Self.hash(i, 68) % 5), turn = CGFloat(u * 5 + Double(i))
                    g.setFillColor(cg(dim(mix(cols[1 % cols.count], white, 0.5), heat)))
                    g.addPath(polygon(o.x, o.y, r, sides: 3, rot: turn)); g.fillPath()
                }
            }
        }
    }

    /// Jaws: rows of spikes from the top and the bottom, as long as the music is loud there; they bite on the kick.
    private func spikes(_ f: Frame, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ dt: Float) {
        meter(f, dt)
        let n = eq.count, tw = cw / CGFloat(n), u = bp - floor(bp), kick = CGFloat(exp(-u * 5))
        let white = SIMD3<Float>(repeating: 1), bite = ch * 0.07 * kick * CGFloat(0.4 + bass)
        for side in 0..<2 {
            let edge: CGFloat = side == 0 ? 0 : ch, dir: CGFloat = side == 0 ? 1 : -1
            var pts = [CGPoint(x: -tw, y: edge)]
            for i in -1...n {
                let j = min(n - 1, max(0, side == 0 ? i : n - 1 - i))
                let len = ch * (0.09 + 0.33 * CGFloat(eq[j])) + bite
                let x0 = CGFloat(i) * tw + (side == 1 ? tw / 2 : 0)   // the rows interlock
                pts += [CGPoint(x: x0, y: edge), CGPoint(x: x0 + tw / 2, y: edge + dir * len)]
            }
            pts.append(CGPoint(x: cw + tw * 2, y: edge))
            let jaw = path(pts), c = cols[side % cols.count]
            g.setShadow(offset: .zero, blur: 0, color: nil)
            g.setFillColor(cg(dim(c, 0.14 + 0.2 * Float(kick))))
            g.addPath(jaw); g.fillPath()
            neon(mix(c, white, 0.5 * Float(kick)), 2)
            g.setLineJoin(.miter); g.setMiterLimit(12)
            g.addPath(jaw); g.strokePath()
        }
        // between the jaws a cut of light on the kick
        sharp(dim(mix(cols[0], white, 0.7), Float(kick)), 1 + 5 * kick)
        g.strokeLineSegments(between: [CGPoint(x: 0, y: ch / 2), CGPoint(x: cw, y: ch / 2)])
    }

    /// 3-2-1 into the drop the engine picked (hello.countdown: once or twice a night), then DROP!
    private func countdown(_ f: Frame, _ d: Decision?, _ h: Hello, _ cols: [SIMD3<Float>]) -> Bool {
        let spb = 60 / max(h.bpm, 60)
        var label: String?, u = 0.0
        if h.countdown == f.phrase + 1, h.plan.indices.contains(f.phrase + 1), h.plan[f.phrase + 1].section == "drop", d?.section != "drop" {
            let left = (h.plan[f.phrase + 1].start - f.t) / spb
            if left > 0 && left <= 4 { label = String(Int(ceil(left))); u = 1 - (left.truncatingRemainder(dividingBy: 1) == 0 ? 1 : left.truncatingRemainder(dividingBy: 1)) }
        }
        if let d, h.countdown == f.phrase, d.section == "drop", f.t - d.start < spb * 2 { label = "DROP!"; u = (f.t - d.start) / (spb * 2) }
        guard let label else { return false }
        g.setShadow(offset: .zero, blur: 0, color: nil)
        g.setFillColor(CGColor(gray: 0, alpha: 0.85))
        g.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
        neon(cols[0], 7)
        let fit = min(1, cw / 520)   // DROP! fits a narrow wall too
        text(label, at: CGPoint(x: cw / 2, y: ch / 2 + 5), size: (label.count > 1 ? 150 : 230 * CGFloat(1.3 - 0.3 * u)) * fit, fill: false)
        return true
    }

    /// Centred outlined (or filled) text in the current colour.
    private func text(_ s: String, at p: CGPoint, size: CGFloat, fill: Bool, mono: Bool = false) {
        let font = CTFontCreateWithName((mono ? "Menlo-Bold" : "HelveticaNeue-CondensedBlack") as CFString, size, nil)
        let attr = NSAttributedString(string: s, attributes: [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorFromContextAttributeName as String): true,
        ])
        let line = CTLineCreateWithAttributedString(attr)
        let bounds = CTLineGetBoundsWithOptions(line, .useGlyphPathBounds)
        g.saveGState()
        g.textMatrix = CGAffineTransform(scaleX: 1, y: -1)
        g.setTextDrawingMode(fill ? .fillStroke : .stroke)
        g.textPosition = CGPoint(x: p.x - bounds.midX, y: p.y + bounds.midY)
        CTLineDraw(line, g)
        g.restoreGState()
    }
}
