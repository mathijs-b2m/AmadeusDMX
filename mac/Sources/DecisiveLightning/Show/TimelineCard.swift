// The track as a timeline: the director's sections over the energy curve, with the playhead.
import DecisiveKit
import SwiftUI

struct TimelineCard: View {
    @Environment(AppModel.self) private var model
    var hello: Hello
    @State private var hover: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if let i = hover, hello.plan.indices.contains(i) {
                    let d = hello.plan[i]
                    Text("\(timeString(d.start)) · \(d.section)\(d.dropScore >= 0.6 ? " ⚡" : "") · pars \(d["par_base"]) + \(d["par_accent"]) · heads \(d["movement"]) / \(d["aim"]) · \(d.palette)")
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                } else {
                    Text("Timeline").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    if model.playingFile != nil {
                        Text("· click to jump").font(.caption).foregroundStyle(.tertiary)
                    }
                }
                Spacer()
            }
            GeometryReader { geo in
                Canvas { ctx, size in draw(ctx, size) }
                    .overlay(alignment: .leading) { Playhead(duration: hello.duration, width: geo.size.width) }
                    .contentShape(Rectangle())
                    .onContinuousHover { phase in
                        if case .active(let p) = phase {
                            let t = Double(p.x / geo.size.width) * hello.duration
                            hover = hello.phraseIndex(at: t)
                        } else { hover = nil }
                    }
                    .onTapGesture { p in
                        guard let file = model.playingFile else { return }
                        let t = Double(p.x / geo.size.width) * hello.duration
                        model.engine.stopAndWait()
                        model.play(file, from: t)
                    }
            }
            .frame(height: 54)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .glassEffect(.regular, in: .rect(cornerRadius: 18))
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize) {
        let W = size.width, H = size.height, dur = max(hello.duration, 1)
        let barH: CGFloat = 12
        // phrases, coloured by section
        for (i, d) in hello.plan.enumerated() {
            let x0 = d.start / dur * W, x1 = d.end / dur * W
            let r = CGRect(x: x0, y: H - barH, width: max(1, x1 - x0 - 1), height: barH)
            ctx.fill(Path(roundedRect: r, cornerRadius: 3),
                     with: .color(Color(simd: Sections.color(d.section)).opacity(i == model.feed.phrase ? 1 : 0.7)))
        }
        // loudness
        let e = hello.energy
        if e.count > 1 {
            var p = Path()
            p.move(to: CGPoint(x: 0, y: H - barH - 3))
            for (i, v) in e.enumerated() {
                p.addLine(to: CGPoint(x: CGFloat(i) / CGFloat(e.count - 1) * W, y: H - barH - 3 - CGFloat(v) * (H - barH - 6)))
            }
            p.addLine(to: CGPoint(x: W, y: H - barH - 3))
            ctx.fill(p, with: .color(.white.opacity(0.13)))
            ctx.stroke(p, with: .color(.white.opacity(0.45)), lineWidth: 1)
        }
        // drops
        for d in hello.plan where d.dropScore >= 0.6 {
            let x = d.start / dur * W
            ctx.fill(Path(CGRect(x: x - 0.75, y: 0, width: 1.5, height: H - barH)), with: .color(.yellow.opacity(0.8)))
        }
    }
}

/// The moving playhead, in its own view: only it refreshes as time runs, the timeline drawing stays put.
private struct Playhead: View {
    @Environment(AppModel.self) private var model
    var duration: Double
    var width: CGFloat
    var body: some View {
        Rectangle().fill(.white).frame(width: 2)
            .offset(x: width * min(1, max(0, model.feed.time / max(duration, 1))) - 1)
    }
}
