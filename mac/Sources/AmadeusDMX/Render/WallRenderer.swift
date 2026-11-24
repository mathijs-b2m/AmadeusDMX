// The LED wall's picture (the native version of web/js/screen.js). The director picks a mode per phrase
// (decision.screen): off | ambient | figure | words | equalizer | psychedelic. Figures are playful neon
// outlines on the beat: a runner, a dancer, a jumping crowd, pong. Into a drop the wall counts 3-2-1 and
// shouts DROP!. Psychedelic is drawn by a Metal shader (WallSource); everything else here, with
// Core Graphics, into a 640×360 picture (the wall's shape when the rig gives its pixels; finer for a real LED wall:
// `scale`) that WallSource puts on the GPU.
import CoreGraphics
import CoreText
import AmadeusKit
import Foundation
import simd

enum WallScene: String, CaseIterable, Identifiable {
    case auto, off, ambient, runner, dancer, crowd, pong, words, equalizer, psychedelic
    var id: String { rawValue }
    var title: String { self == .auto ? "Director's Choice" : rawValue.capitalized }
    var symbol: String {
        switch self {
        case .auto: "wand.and.stars"
        case .off: "rectangle.slash"
        case .ambient: "cloud.fog"
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
    private var eq = [Float](repeating: 0, count: 16), caps = [Float](repeating: 0, count: 16)
    private var amb: Double = 0
    private var fromPose: [[Float]] = WallRenderer.moves["down"]!
    private var lastBeat = -1

    /// The canvas for a wall of this shape, in units.
    static func canvas(_ aspect: Double) -> (w: CGFloat, h: CGFloat) {
        let a = CGFloat(aspect)
        return a >= 1 ? ((CGFloat(H) * a).rounded(), CGFloat(H)) : (CGFloat(H), (CGFloat(H) / a).rounded())
    }

    init(scale: CGFloat = 1, aspect: Double = ScreenShape.defaultAspect) {
        self.scale = scale
        self.aspect = aspect
        (cw, ch) = Self.canvas(aspect)
        let w = Int((cw * scale).rounded()), h = Int((ch * scale).rounded())
        context = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
        context.translateBy(x: 0, y: CGFloat(h))
        context.scaleBy(x: scale, y: -scale)   // y down, like a canvas, in units
        context.setFillColor(CGColor(gray: 0, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: cw, height: ch))
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
        let scene: WallScene = mode == "figure" ? WallScene.figures[Self.hash(f.phrase, 9) % WallScene.figures.count]
            : WallScene(rawValue: mode) ?? .off
        return (mode, scene)
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
        let shout = wall >= 0.5 && h.countdown == f.phrase && d?.section == "drop" && cur.mode != "off" && cur.mode != "psychedelic" && (f.t - d!.start) / spb < 2
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
        if cur.mode == "psychedelic" {
            let fx = f.fx
            let mean = fx.isEmpty ? 0 : fx.reduce(Float(0)) { $0 + min(1, ($1.first ?? 0) + ($1.count > 4 ? $1[4] : 0)) } / Float(fx.count)
            target = mean < 0.01 ? 0.05 : min(1, 0.3 + 1.4 * mean)
        } else {
            draw(f, d, h, cols, bp, bass, dt)
            target = cur.mode == "off" ? 0 : cur.mode == "ambient" ? 0.4 : 0.95
        }
        level += (target * min(1, wall * 2) * fade - level) * min(1, dt * 10)
        return WallState(level: level, psychedelic: cur.mode == "psychedelic", palette: Palettes.colors(d?.palette),
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

    private func draw(_ f: Frame, _ d: Decision?, _ h: Hello, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ dt: Float) {
        g.saveGState()
        g.setShadow(offset: .zero, blur: 0, color: nil)
        // a short trail behind moving lines: how much of the last picture fades is set per 1/60 s, so the trail
        // is as short at any drawing rate (a fixed share per picture ghosted when the wall was drawn less often)
        let fadeShare = cur.scene == .words ? 0.8 : 0.45
        g.setFillColor(CGColor(gray: 0, alpha: CGFloat(1 - pow(1 - fadeShare, Double(max(dt, 1 / 240)) * 60))))
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
            default: break
            }
        }
        g.restoreGState()
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
        neon(cols[1 % cols.count], 2)
        g.setAlpha(0.45)
        let sky = CGMutablePath(), off = scroll * 0.3
        for i in -1..<(Int(cw / 70) + 2) {
            let x = CGFloat(Double(i) * 70 - off.truncatingRemainder(dividingBy: 70))
            let h = CGFloat(40 + Self.hash(i + Int(off / 70)) % 90)
            sky.move(to: CGPoint(x: x, y: gy)); sky.addLine(to: CGPoint(x: x, y: gy - h))
            sky.addLine(to: CGPoint(x: x + 52, y: gy - h)); sky.addLine(to: CGPoint(x: x + 52, y: gy))
        }
        g.addPath(sky); g.strokePath()
        g.setAlpha(1)
        neon(cols[0], 3)
        g.strokeLineSegments(between: [CGPoint(x: 0, y: gy), CGPoint(x: cw, y: gy)])
        // a hurdle every bar, arriving at the runner on the downbeat
        let bar = bp / 4, hx = rx + CGFloat((ceil(bar) - bar) * 4 * speed)
        g.strokeLineSegments(between: [CGPoint(x: hx, y: gy), CGPoint(x: hx, y: gy - 38),
                                       CGPoint(x: hx - 14, y: gy - 38), CGPoint(x: hx + 14, y: gy - 38)])
        let fromDown = (bp + 0.5).truncatingRemainder(dividingBy: 4) - 0.5
        let jump = abs(fromDown) < 0.5 ? CGFloat(cos(fromDown * .pi)) : 0
        let w = Float(bp * .pi)
        let y = gy - s * 0.5 - CGFloat(abs(cos(w))) * 6 - jump * 70
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
        for i in 0..<(8 + 2 * max(0, Int((cw - 640) / 140))) {  // the dance floor lights up with the beat
            let on = Self.hash(i + beat * 8, 1) % 3 == 0
            neon(cols[i % cols.count], 2)
            g.setAlpha(on ? 0.55 : 0.12)
            let n = 8 + 2 * max(0, Int((cw - 640) / 140))
            let x0 = mx + CGFloat(i - n / 2) * 70, x1 = x0 + 70
            let p = CGMutablePath()
            p.move(to: CGPoint(x: x0 + (x0 - mx) * 0.4, y: floorY)); p.addLine(to: CGPoint(x: x1 + (x1 - mx) * 0.4, y: floorY))
            p.addLine(to: CGPoint(x: x1, y: floorY - 45)); p.addLine(to: CGPoint(x: x0, y: floorY - 45)); p.closeSubpath()
            g.addPath(p); g.strokePath()
        }
        g.setAlpha(1)
        neon(cols[0], 6)
        figure(mx, hipY - CGFloat(dip) * 8 - hop, 190, head: CGFloat(0.15 * sin(bp * .pi)), arms: arms, legs: legs)
        if hop > 0 { neon(cols[1 % cols.count], 4); text("!", at: CGPoint(x: mx + 90, y: hipY - 145 - hop * 0.3), size: 46, fill: true) }
    }

    private func crowd(_ d: Decision?, _ cols: [SIMD3<Float>], _ bp: Double, _ bass: Float, _ phraseFrac: Double) {
        let n = max(4, Int((11 * cw / 640).rounded())), drop = d?.section == "drop", hands = drop || (d?.intensity ?? 1) >= 2
        for i in 0..<n {
            let x = 40 + CGFloat(i) * (cw - 80) / CGFloat(n - 1), s = CGFloat(105 + Self.hash(i, 5) % 25)
            let u = drop ? bp.truncatingRemainder(dividingBy: 1) : (bp - Double(i) * 0.12).truncatingRemainder(dividingBy: 1)
            let jump = CGFloat(max(0, sin(u * .pi))) * (drop ? 40 : 14 + 22 * CGFloat(bass))
            let wave = hands ? Float(0.25 * sin(bp * .pi + Double(i))) : 0
            neon(cols[i % cols.count], 3)
            figure(x, ground - 15 - s * 0.5 - jump, s,
                   arms: hands ? [[-2.7 + wave, 0], [2.7 + wave, 0]] : [[-0.3, 0.4], [0.3, -0.4]],
                   legs: jump > 4 ? [[-0.5, 0.6], [0.5, -0.6]] : [[-0.2, 0], [0.2, 0]])
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
        let size = min(170, 1000 / CGFloat(max(3, w.count))) * CGFloat(1 + 0.25 * max(0, 1 - u * 4))
        neon(cols[beat % cols.count], 5)
        text(w, at: CGPoint(x: cw / 2, y: ch / 2), size: size * min(1.6, cw / 640), fill: u < 0.15)
    }

    private func equalizer(_ f: Frame, _ cols: [SIMD3<Float>], _ dt: Float) {
        let b = f.bands, n = eq.count, now = Float(Date().timeIntervalSinceReferenceDate)
        for i in 0..<n {
            let pos = Float(i) / Float(n - 1) * Float(max(b.count - 1, 1)), j = Int(pos), k = pos - Float(j)
            let lo = j < b.count ? b[j] : 0, hi = j + 1 < b.count ? b[j + 1] : lo
            let v = min(1, max(0, (lo + (hi - lo) * k) * (0.85 + 0.3 * sin(Float(i) * 2.3 + now * 5.5))))
            eq[i] = v > eq[i] ? v : eq[i] - dt * 2.2
            caps[i] = max(eq[i], caps[i] - dt * 0.6)
        }
        let bw = cw / CGFloat(n), top = ch - 60, base = ch - 20
        for i in 0..<n {
            neon(cols[min(cols.count - 1, i * cols.count / n)], 3)
            let h = CGFloat(eq[i]) * top, x = CGFloat(i) * bw + 6
            var y: CGFloat = base
            while y > base - h { g.stroke(CGRect(x: x, y: y - 12, width: bw - 12, height: 10)); y -= 16 }
            g.fill(CGRect(x: x, y: base - 10 - CGFloat(caps[i]) * top - 8, width: bw - 12, height: 4))
        }
    }

    private func ambient(_ cols: [SIMD3<Float>], _ dt: Float) {
        amb += Double(dt) * 0.15
        g.setShadow(offset: .zero, blur: 0, color: nil)
        for (i, c) in cols.enumerated() {
            let x = Double(cw) / 2 + (Double(cw) / 2 - 90) * sin(amb * (0.7 + Double(i) * 0.23) + Double(i) * 2)
            let y = Double(ch) / 2 + (Double(ch) / 2 - 70) * cos(amb * (0.5 + Double(i) * 0.17) + Double(i))
            let grad = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                                  colors: [cg(c, 0.5), cg(c, 0)] as CFArray, locations: [0, 1])!
            g.drawRadialGradient(grad, startCenter: CGPoint(x: x, y: y), startRadius: 0,
                                 endCenter: CGPoint(x: x, y: y), endRadius: max(260, max(cw, ch) * 0.4), options: [])
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
