// Perform Only: what the operator needs at a glance, big, instead of the 3D stage.
import DecisiveKit
import SwiftUI

/// Perform Only: what the operator needs at a glance, big, instead of the 3D stage.
struct PerformBoard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack {
            Color(nsColor: .underPageBackgroundColor).ignoresSafeArea()
            VStack(spacing: 14) {
                if let h = model.feed.hello, model.showState.isActive, h.plan.indices.contains(model.feed.phrase) {
                    let i = model.feed.phrase, d = h.plan[i]
                    Text(d.section.uppercased())
                        .font(.system(size: 72, weight: .heavy, design: .rounded))
                        .foregroundStyle(Color(simd: Sections.color(d.section)))
                    IntensityPips(level: d.intensity).scaleEffect(1.6).padding(.bottom, 6)
                    if h.plan.indices.contains(i + 1) {
                        let next = h.plan[i + 1], left = max(0, next.start - model.feed.time)
                        Text("\(next.dropScore >= 0.6 || next.section == "drop" ? "⚡ " : "")\(next.section) in \(Int(left)) s")
                            .font(.title2.monospacedDigit()).foregroundStyle(.secondary)
                    }
                } else {
                    Image(systemName: ShowMode.perform.symbol).font(.system(size: 44)).foregroundStyle(.secondary)
                    Text(ShowMode.perform.title).font(.title.bold())
                    Text("The 3D stage is off: the computer's power goes to the lights.")
                        .foregroundStyle(.secondary)
                }
                HStack(spacing: 8) {
                    Image(systemName: "cable.connector")
                    Text(model.currentSet.map { $0.isVirtual ? "No lights in this set (visualiser only)" : $0.outputText } ?? "No set")
                }
                .font(.callout).foregroundStyle(.secondary).padding(.top, 10)
                Button("Show the Stage") { model.setMode(.both) }
                    .buttonStyle(.glass)
                    .help("Perform + Visualise: the 3D stage alongside the lights")
            }
            .padding(40)
        }
    }
}
