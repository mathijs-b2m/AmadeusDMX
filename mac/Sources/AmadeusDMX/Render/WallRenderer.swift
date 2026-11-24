// The LED wall's picture (the native version of web/js/screen.js). The director picks a mode per phrase
// (decision.screen): off | ambient | figure | words | equalizer | psychedelic. Figures are playful neon
// outlines on the beat: a runner, a dancer, a jumping crowd, pong. The modes also bring abstract scenes: geometric
// shapes among the figures, a scope for the equaliser, a starfield for ambient, a tunnel in drops (pick()). Into a
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
    case auto, off, ambient, starfield, runner, dancer, crowd, pong, shapes, words, equalizer, scope, tunnel, psychedelic
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
    private var amb: Double = 0
    private var fromPose: [[Float]] = WallRenderer.moves["down"]!
    private var lastBeat = -1
    /// This picture's fade (the share of the last picture darkened) and the fade at the show's 40 pictures a second.
    private var fadeNow: CGFloat = 0.59, fadeRef: CGFloat = 0.59
    /// The time between pictures, smoothed: the trail's fade follows it (one picture 25 ms after the last, the next 50,
    /// would brighten and dim every glow that builds up on the trail).
    private var fadeDt: Double = 1.0 / 40

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
        travel = old.travel; lastBp = old.lastBp; sound = old.sound
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

    private func wanted(_ f: Frame, _ d: Decision?) -> (String, WallScene) {
        if force != .auto {
            return (WallScene.figures.contains(force) ? "figure" : force.rawValue, force)
        }
        var mode = d?.screen ?? ""
        if mode.isEmpty {
            let opts = Self.rules[d?.section ?? ""] ?? ["off"]
            mode = opts[Self.hash(f.phrase, 2) % opts.count]
        }
        return (mode, Self.pick(mode, phrase: f.phrase, drop: d?.section == "drop"))
    }

    /// The scene a mode shows this phrase: the director's modes are few, each brings a small family of scenes.
    static func pick(_ mode: String, phrase: Int, drop: Bool) -> WallScene {
        let pool: [WallScene]
        switch mode {
        case "figure": pool = WallScene.figures + (drop ? [.shapes, .tunnel] : [.shapes])
        case "equalizer": pool = [.equalizer, .scope]
        case "ambient": pool = [.ambient, .ambient, .starfield]
        case "psychedelic": pool = [.psychedelic, .psychedelic, .tunnel]
        default: return WallScene(rawValue: mode) ?? .off
        }
        return pool[hash(phrase, 9) % pool.count]
    }

    func update(frame f: Frame, hello h: Hello, dt: Float) -> WallState {
        let d = h.plan.indices.contains(f.phrase) ? h.plan[f.phrase] : nil
        var want = wanted(f, d)
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
        return WallState(level: level, psychedelic: cur.scene == .psychedelic, palette: Palettes.colors(d?.palette),
                          bands: bandsV, scene: cur.scene)
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

    private func draw(_ f: Frame, _ d: Decision?, _ h: Hello, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ dt: Float) {
        g.saveGState()
        g.setShadow(offset: .zero, blur: 0, color: nil)
        // a short trail behind moving lines: how much of the last picture fades is set per 1/60 s, so the trail
        // is as short at any drawing rate (a fixed share per picture ghosted when the wall was drawn less often)
        let fadeShare = cur.scene == .words ? 0.8 : cur.scene == .tunnel || cur.scene == .scope ? 0.6 : 0.45
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

    private func equalizer(_ f: Frame, _ cols: [SIMD3<Float>], _ dt: Float) {
        let b = f.bands, n = eq.count, now = Float(Date().timeIntervalSinceReferenceDate)
        for i in 0..<n {
            let pos = Float(i) / Float(n - 1) * Float(max(b.count - 1, 1)), j = Int(pos), k = pos - Float(j)
            let lo = j < b.count ? b[j] : 0, hi = j + 1 < b.count ? b[j + 1] : lo
            let v = min(1, max(0, (lo + (hi - lo) * k) * (0.85 + 0.3 * sin(Float(i) * 2.3 + now * 5.5))))
            eq[i] = max(v, eq[i] - dt * 2.2)   // a held level holds (falling only where the music fell)
            caps[i] = max(eq[i], caps[i] - dt * 0.6)
        }
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
