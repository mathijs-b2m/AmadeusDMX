// The brightness limiter: its toolbar button (on every page) and the banner that can't be missed while it is on.
import AmadeusKit
import SwiftUI

private let explanation = "A ceiling on every light, to test and set up without eye strain. At 70 %, a light the show plays at 50 % stays at 50 %; one at 100 % plays at 70 %. The show, the light test and Identify all keep to it. Smoke isn't limited. For a show: 100 %."

struct LimiterButton: View {
    @Environment(AppModel.self) private var model
    @State private var open = false

    var body: some View {
        Button { open.toggle() } label: {
            if model.limiterOn {
                Label("Limited to \(percent(model.limiter))", systemImage: "sun.max.trianglebadge.exclamationmark.fill")
                    .labelStyle(.titleAndIcon)
                    .foregroundStyle(.orange)
                    .fontWeight(.bold)
            } else {
                Label("Brightness Limiter", systemImage: "sun.max")
            }
        }
        .help(model.limiterOn ? "Every light is limited to \(percent(model.limiter)). Click to change" : "Brightness limiter: off (100 %)")
        .popover(isPresented: $open, arrowEdge: .bottom) { LimiterPanel().environment(model) }
        .disabled(model.workspace == nil)
    }
}

struct LimiterPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Brightness Limiter").font(.headline)
                Spacer()
                Text(model.limiterOn ? percent(model.limiter) : "Off")
                    .font(.title3.weight(.bold)).monospacedDigit()
                    .foregroundStyle(model.limiterOn ? .orange : .secondary)
            }
            Slider(value: Binding(get: { model.limiter }, set: { model.setLimiter(($0 * 20).rounded() / 20) }),
                   in: Workspace.limiterMinimum...1) {
                Text("Ceiling")
            } minimumValueLabel: { Text("5%") } maximumValueLabel: { Text("100%") }
            HStack {
                ForEach([0.25, 0.5, 0.7], id: \.self) { v in
                    Button(percent(v)) { model.setLimiter(v) }
                }
                Spacer()
                Button("100% (Off)") { model.setLimiter(1) }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.limiterOn)
            }
            Text(explanation).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Text("The app starts at 100 % every time it opens.").font(.caption).foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(width: 360)
    }
}

/// Across the top of every page while the limiter is on: hazard stripes, the level, one click back to 100 %.
struct LimiterBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if model.limiterOn {
            HStack(spacing: 12) {
                Image(systemName: "sun.max.trianglebadge.exclamationmark.fill").font(.title3)
                Text("Brightness limited to \(percent(model.limiter))").font(.headline)
                Text("lights above it play at \(percent(model.limiter)), the rest as the show plays them · set it to 100 % for a show")
                    .font(.callout).lineLimit(1).truncationMode(.tail)
                Spacer(minLength: 8)
                Button("Back to 100%") { model.setLimiter(1) }
                    .buttonStyle(.borderedProminent).tint(.black)
            }
            .foregroundStyle(.black)
            .padding(.horizontal, 14).padding(.vertical, 7)
            .background { HazardStripes() }
            .help(explanation)
        }
    }
}

private struct HazardStripes: View {
    var body: some View {
        Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(red: 1, green: 0.62, blue: 0.1)))
            let w: CGFloat = 14
            var x: CGFloat = -size.height
            while x < size.width {
                var p = Path()
                p.move(to: CGPoint(x: x, y: size.height))
                p.addLine(to: CGPoint(x: x + size.height, y: 0))
                p.addLine(to: CGPoint(x: x + size.height + w, y: 0))
                p.addLine(to: CGPoint(x: x + w, y: size.height))
                ctx.fill(p, with: .color(Color(red: 1, green: 0.72, blue: 0.3)))
                x += 2 * w
            }
        }
    }
}

private func percent(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }
