// The calibration's picture: where the software expects a head's beam to go, drawn twice, as you see it from the
// audience and from above. The real head is then turned (its calibration, a press at a time) until it does the same.
// Both are drawn as the audience sees the stage: stage left (x = 0) on the right.
import SwiftUI

struct BeamPicture: View {
    struct Beam: Equatable {
        var pos: SIMD3<Float>     // metres: x from stage left, y towards the audience from the stage's front edge, z up
        var dir: SIMD3<Float>
        var stage: SIMD2<Float>   // width, height
    }

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
            Canvas { g, size in draw(&g, size, above: above) }
                .frame(width: 250, height: 140)
                .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 8))
                .clipShape(.rect(cornerRadius: 8))
            Text(title).font(.caption).foregroundStyle(.secondary)
        }
    }

    /// The beam's length in the picture, in metres.
    private var reach: CGFloat { max(1.5, CGFloat(beam.stage.x) * 0.4) }

    private func draw(_ g: inout GraphicsContext, _ size: CGSize, above: Bool) {
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
        let pad: CGFloat = 16
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

        // the beam: a cone from the head, widening; seen end-on it is short, and a glow says it comes at you
        let a = pt(at.x, at.y), flat = hypot(to.dx, to.dy)
        let beamColor = Color.yellow
        if flat > 0.05 {
            let len = reach * s * flat, ux = to.dx / flat, uy = to.dy / flat
            let b = CGPoint(x: a.x + ux * len, y: a.y + uy * len), half = 3 + len * 0.12
            let cone = Path {
                $0.move(to: a)
                $0.addLine(to: CGPoint(x: b.x - uy * half, y: b.y + ux * half))
                $0.addLine(to: CGPoint(x: b.x + uy * half, y: b.y - ux * half))
                $0.closeSubpath()
            }
            g.fill(cone, with: .color(beamColor.opacity(0.45)))
            g.stroke(Path { $0.move(to: a); $0.addLine(to: b) }, with: .color(beamColor), lineWidth: 1.5)
        }
        if !above, d.y > 0.3 {   // towards you
            let r = 6 + 12 * CGFloat(d.y)
            g.fill(Path(ellipseIn: CGRect(x: a.x - r, y: a.y - r, width: 2 * r, height: 2 * r)), with: .color(beamColor.opacity(0.3)))
        }
        g.fill(Path(ellipseIn: CGRect(x: a.x - 4, y: a.y - 4, width: 8, height: 8)), with: .color(.primary))
    }
}
