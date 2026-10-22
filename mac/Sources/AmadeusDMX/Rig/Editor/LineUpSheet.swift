// Line Up: put a drawing right under the rig with two clicks on its page, the stage's front edge at stage left and
// at stage right, and how far apart those are. The engine moves the drawing's fixtures (and their trusses) to
// where it then puts them and saves the rig (POST /api/underlay/align); the editor reads it again.
import AmadeusKit
import SwiftUI

struct LineUpSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let editor: RigEditorModel
    let underlay: Underlay
    @State private var clicks: [SIMD2<Double>] = []   // page fractions: stage left, then stage right
    @State private var width = 8.0
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Line Up “\(underlay.title)”").font(.title2.weight(.semibold))
                Text("Click the stage's front edge at stage left, then at stage right.")
                Text("Stage left is the performers' left: on the usual plan, with the audience at the bottom, that is on the right of the page. On a hall plan without the stage, click where the hall meets the stage at its two side walls, and type the hall's width.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            page
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.background.secondary, in: .rect(cornerRadius: 8))
            HStack {
                LabeledContent("Distance") {
                    HStack(spacing: 4) {
                        TextField("Distance", value: $width, format: .number.precision(.fractionLength(0...2)))
                            .labelsHidden().frame(width: 70).multilineTextAlignment(.trailing)
                        Text("m").foregroundStyle(.secondary)
                    }
                }
                .fixedSize()
                .help("How far apart the two points are (metres): the stage's width, or the hall's when you clicked its side walls")
                if let error { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout) }
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Line Up") { Task { await lineUp() } }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(clicks.count < 2 || width < 0.5 || busy)
                    .help("Move the drawing's fixtures and their trusses to where it now puts them, and save the rig")
            }
        }
        .padding(22)
        .frame(width: 900, height: 760)
        .onAppear { width = editor.doc.width }
    }

    /// The page, fitted to the sheet: the clicks as SL and SR with a line between, the current ones faintly, and
    /// the plan's part of the page framed faintly when the page holds more than this plan.
    @ViewBuilder private var page: some View {
        if let img = editor.page(underlay) {
            Image(decorative: img, scale: 1)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .overlay {
                    GeometryReader { g in
                        let size = g.size
                        let at = { (f: SIMD2<Double>) in CGPoint(x: f.x * size.width, y: f.y * size.height) }
                        ZStack {
                            Color.clear.contentShape(.rect)
                                .onTapGesture(coordinateSpace: .local) { p in
                                    let f = SIMD2(Double(p.x / max(1, size.width)), Double(p.y / max(1, size.height)))
                                    clicks = clicks.count >= 2 ? [f] : clicks + [f]   // a third click starts over
                                }
                            if underlay.crop != [0, 0, 1, 1] {
                                let k = underlay.crop
                                Path(CGRect(x: k[0] * size.width, y: k[1] * size.height,
                                            width: (k[2] - k[0]) * size.width, height: (k[3] - k[1]) * size.height))
                                    .stroke(Color.secondary.opacity(0.5), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                                    .allowsHitTesting(false)
                            }
                            if clicks.isEmpty, let a = underlay.a, let b = underlay.b, a.count == 2, b.count == 2 {
                                let pa = at(SIMD2(a[0], a[1])), pb = at(SIMD2(b[0], b[1]))
                                Path { p in p.move(to: pa); p.addLine(to: pb) }
                                    .stroke(Color.accentColor.opacity(0.35), style: StrokeStyle(lineWidth: 2, dash: [5, 4]))
                                marker("SL", pa).opacity(0.4)
                                marker("SR", pb).opacity(0.4)
                            }
                            if clicks.count == 2 {
                                Path { p in p.move(to: at(clicks[0])); p.addLine(to: at(clicks[1])) }
                                    .stroke(Color.accentColor, lineWidth: 2)
                            }
                            ForEach(Array(clicks.enumerated()), id: \.offset) { i, f in marker(i == 0 ? "SL" : "SR", at(f)) }
                        }
                        .frame(width: size.width, height: size.height)
                    }
                }
                .help(clicks.isEmpty ? "The faint marks: where the import thought the stage's front edge is" : "Click again to start over")
        } else {
            ProgressView("Loading the page…")
        }
    }

    private func marker(_ text: String, _ p: CGPoint) -> some View {
        ZStack {
            Circle().fill(Color.accentColor).frame(width: 10, height: 10)
            Text(text).font(.caption.weight(.bold)).foregroundStyle(.white)
                .padding(.horizontal, 5).padding(.vertical, 1)
                .background(Color.accentColor, in: .capsule)
                .offset(y: -16)
        }
        .position(p)
        .allowsHitTesting(false)
    }

    private func lineUp() async {
        guard clicks.count == 2 else { return }
        busy = true
        defer { busy = false }
        do {
            try await editor.lineUp(model, underlay, a: clicks[0], b: clicks[1], width: width)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
