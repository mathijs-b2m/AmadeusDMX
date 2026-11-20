// The calibration's picture: a moving head as the software expects it, and where its beam goes, drawn twice, as you
// see it from the audience and from above. The real head is then turned (its calibration, a press at a time) until
// it does the same. Both are drawn as the audience sees the stage: stage left (x = 0) on the right. The pan test's
// picture moves: the head turns from `dir` to `to` and back, held at each end, as the engine's sweep does (not in
// step with the real one, only the same way round), the far end drawn faint.
import simd
import SwiftUI

struct BeamPicture: View {
    struct Beam: Equatable {
        var pos: SIMD3<Float>     // metres: x from stage left, y towards the audience from the stage's front edge, z up
        var dir: SIMD3<Float>
        var stage: SIMD2<Float>   // width, height
        var hanging = true        // its base above it (under a truss), or below (standing)
        var to: SIMD3<Float>?     // the pan test: it turns from `dir` to here and back
    }

    /// The engine's sweep (web/rig.py SWEEP_HOLD_S, SWEEP_MOVE_S): held, turned, held, turned back.
    static let hold = 1.5, move = 2.0

    let beam: Beam

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            panel("From where you stand", above: false)
            panel("From above", above: true)
        }
        .accessibilityElement()
        .accessibilityLabel("Where the beam should go, from where you stand and from above")
    }

    private func panel(_ title: String, above: Bool) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Group {
                if beam.to != nil {
                    TimelineView(.animation) { tl in
                        Canvas { g, size in draw(&g, size, above: above, at: Self.sweep(tl.date.timeIntervalSinceReferenceDate)) }
                    }
                } else {
                    Canvas { g, size in draw(&g, size, above: above) }
                }
            }
                .frame(width: 270, height: 170)
                .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 8))
                .clipShape(.rect(cornerRadius: 8))
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }

    /// The beam's length in the picture, in metres.
    private var reach: CGFloat { max(1.5, CGFloat(beam.stage.x) * 0.4) }

    /// How far along the pan test's turn (0: `dir`, 1: `to`), eased, at time `t` in seconds.
    static func sweep(_ t: Double) -> Float {
        let cycle = 2 * (hold + move), x = t.truncatingRemainder(dividingBy: cycle)
        let k = x < hold ? 0 : x < hold + move ? (x - hold) / move : x < 2 * hold + move ? 1 : 1 - (x - 2 * hold - move) / move
        return Float(k * k * (3 - 2 * k))
    }

    private func draw(_ g: inout GraphicsContext, _ size: CGSize, above: Bool, at k: Float = 0) {
        var turned = beam
        if let to = beam.to {   // the far end faint, then the head where it is now
            turned.dir = to
            turned.to = nil
            var faint = g
            faint.opacity = 0.3
            BeamPicture(beam: turned).drawOne(&faint, size, above: above)
            turned.dir = simd_normalize(beam.dir * (1 - k) + to * k)
        }
        BeamPicture(beam: turned).drawOne(&g, size, above: above)
    }

    /// The picture with the head pointing `beam.dir`.
    private func drawOne(_ g: inout GraphicsContext, _ size: CGSize, above: Bool) {
        let w = max(CGFloat(beam.stage.x), 1), p = beam.pos, d = beam.dir
        // the world box in the picture's own metres: h from the left (stage right's edge), v down
        let top: CGFloat, height: CGFloat, at: CGPoint, to: CGVector
        if above {
            let back = min(CGFloat(p.y), -2) - 0.8, front = max(CGFloat(p.y), 0) + reach + 0.3
            top = back; height = front - back
            at = CGPoint(x: w - CGFloat(p.x), y: CGFloat(p.y) - back)
            to = CGVector(dx: -CGFloat(d.x), dy: CGFloat(d.y))
        } else {
            let h = max(CGFloat(beam.stage.y), CGFloat(p.z) + 0.5, 2)
            top = 0; height = h
            at = CGPoint(x: w - CGFloat(p.x), y: h - CGFloat(p.z))
            to = CGVector(dx: -CGFloat(d.x), dy: -CGFloat(d.z))
        }
        let pad: CGFloat = 22
        let s = min((size.width - 2 * pad) / w, (size.height - 2 * pad) / height)
        let ox = (size.width - w * s) / 2, oy = (size.height - height * s) / 2
        func pt(_ h: CGFloat, _ v: CGFloat) -> CGPoint { CGPoint(x: ox + h * s, y: oy + v * s) }

        let line = GraphicsContext.Shading.color(.secondary.opacity(0.7))
        if above {   // the stage's floor, its front edge heavy; the audience below it
            let edge = -top
            g.fill(Path(CGRect(x: ox, y: oy, width: w * s, height: edge * s)), with: .color(.secondary.opacity(0.12)))
            g.stroke(Path { $0.move(to: pt(0, edge)); $0.addLine(to: pt(w, edge)) }, with: line, lineWidth: 2)
            g.draw(Text("Audience").font(.caption2).foregroundStyle(.secondary), at: CGPoint(x: size.width / 2, y: size.height - 2), anchor: .bottom)
            g.draw(Text("Stage").font(.caption2).foregroundStyle(.secondary), at: CGPoint(x: size.width / 2, y: 2), anchor: .top)
        } else {     // the floor heavy, the room's height light
            g.stroke(Path(CGRect(x: ox, y: oy, width: w * s, height: height * s)), with: .color(.secondary.opacity(0.25)), lineWidth: 1)
            g.stroke(Path { $0.move(to: pt(0, height)); $0.addLine(to: pt(w, height)) }, with: line, lineWidth: 2)
        }
        g.draw(Text("SR").font(.caption2.weight(.semibold)).foregroundStyle(.secondary), at: CGPoint(x: 4, y: size.height - 2), anchor: .bottomLeading)
        g.draw(Text("SL").font(.caption2.weight(.semibold)).foregroundStyle(.secondary), at: CGPoint(x: size.width - 4, y: size.height - 2), anchor: .bottomTrailing)

        let a = pt(at.x, at.y)
        Self.head(&g, mount: a, base: above ? nil : CGVector(dx: 0, dy: beam.hanging ? -1 : 1), aim: to,
                  towards: above ? 0 : CGFloat(d.y), beam: reach * s)
    }

    /// A moving head: its base (at `mount`, the yoke hanging from it or standing on it along -`base`; nil: seen from
    /// above, the base under the head), the head turned to `aim` (the beam's direction as this view sees it: shorter
    /// the more it points at or away from you, `towards` > 0 at you), and `beam` points of beam from its lens.
    static func head(_ g: inout GraphicsContext, mount: CGPoint, base: CGVector?, aim: CGVector, towards: CGFloat,
                     beam: CGFloat, unit u: CGFloat = 1) {
        let body = GraphicsContext.Shading.color(Color(white: 0.82)), dark = GraphicsContext.Shading.color(Color(white: 0.25))
        let yellow = Color.yellow
        var pivot = mount
        if let base {
            // the base, and the yoke's two arms from it to the head's pivot
            let drop = 24 * u, bx = -base.dy, by = base.dx   // across the base
            pivot = CGPoint(x: mount.x - base.dx * drop, y: mount.y - base.dy * drop)
            var plate = Path()
            plate.addRoundedRect(in: CGRect(x: -17 * u, y: -5 * u, width: 34 * u, height: 10 * u), cornerSize: CGSize(width: 3 * u, height: 3 * u))
            let turn = CGAffineTransform(a: bx, b: by, c: base.dx, d: base.dy, tx: mount.x, ty: mount.y)
            g.fill(plate.applying(turn), with: body)
            for side in [-1.0, 1.0] {
                let o = CGFloat(side) * 14 * u
                g.stroke(Path {
                    $0.move(to: CGPoint(x: mount.x + bx * o, y: mount.y + by * o))
                    $0.addLine(to: CGPoint(x: pivot.x + bx * o, y: pivot.y + by * o))
                }, with: body, style: StrokeStyle(lineWidth: 4 * u, lineCap: .round))
            }
        } else {
            var plate = Path()
            plate.addRoundedRect(in: CGRect(x: mount.x - 15 * u, y: mount.y - 15 * u, width: 30 * u, height: 30 * u),
                                 cornerSize: CGSize(width: 5 * u, height: 5 * u))
            g.stroke(plate, with: body, lineWidth: 2 * u)
        }
        let flat = hypot(aim.dx, aim.dy)
        if flat > 0.35 {   // the head from its side: a barrel, its lens at the front
            let ux = aim.dx / flat, uy = aim.dy / flat
            let turn = CGAffineTransform(a: ux, b: uy, c: -uy, d: ux, tx: pivot.x, ty: pivot.y)
            let long = (16 + 12 * flat) * u   // shorter when it points partly at you
            let lens = CGPoint(x: pivot.x + ux * (long - 10 * u), y: pivot.y + uy * (long - 10 * u))
            if beam > 0 {
                let len = beam * flat, half = 4 * u + len * 0.12
                let end = CGPoint(x: lens.x + ux * len, y: lens.y + uy * len)
                g.fill(Path {
                    $0.move(to: CGPoint(x: lens.x - uy * 5 * u, y: lens.y + ux * 5 * u))
                    $0.addLine(to: CGPoint(x: end.x - uy * half, y: end.y + ux * half))
                    $0.addLine(to: CGPoint(x: end.x + uy * half, y: end.y - ux * half))
                    $0.addLine(to: CGPoint(x: lens.x + uy * 5 * u, y: lens.y - ux * 5 * u))
                    $0.closeSubpath()
                }, with: .color(yellow.opacity(0.45)))
            }
            var barrel = Path()
            barrel.addRoundedRect(in: CGRect(x: -10 * u, y: -9 * u, width: long, height: 18 * u), cornerSize: CGSize(width: 5 * u, height: 5 * u))
            g.fill(barrel.applying(turn), with: body)
            g.fill(Path(CGRect(x: long - 13 * u, y: -7 * u, width: 3 * u, height: 14 * u)).applying(turn), with: .color(yellow))
            g.fill(Path(ellipseIn: CGRect(x: pivot.x - 2.5 * u, y: pivot.y - 2.5 * u, width: 5 * u, height: 5 * u)), with: dark)
        } else {           // end-on: its round front (the lens lit, at you) or its back
            func disc(_ r: CGFloat) -> Path { Path(ellipseIn: CGRect(x: pivot.x - r, y: pivot.y - r, width: 2 * r, height: 2 * r)) }
            if towards > 0, beam > 0 { g.fill(disc(24 * u), with: .color(yellow.opacity(0.3))) }
            g.fill(disc(11 * u), with: body)
            if towards > 0 { g.fill(disc(7 * u), with: .color(yellow)) } else { g.stroke(disc(5 * u), with: dark, lineWidth: 1.5 * u) }
        }
    }
}

/// A moving head hanging under a truss or standing on the floor: the calibration's first question.
struct MovingHeadIcon: View {
    let hanging: Bool

    var body: some View {
        Canvas { g, size in
            let rail = hanging ? 12.0 : size.height - 8
            g.stroke(Path { $0.move(to: CGPoint(x: 6, y: rail)); $0.addLine(to: CGPoint(x: size.width - 6, y: rail)) },
                     with: .color(.secondary), style: StrokeStyle(lineWidth: hanging ? 5 : 2, lineCap: .round))
            BeamPicture.head(&g, mount: CGPoint(x: size.width / 2, y: hanging ? rail + 8 : rail - 6),
                             base: CGVector(dx: 0, dy: hanging ? -1 : 1),
                             aim: CGVector(dx: 0.62, dy: hanging ? 0.62 : -0.62), towards: 0, beam: 34)
        }
        .frame(width: 120, height: 84)
    }
}
