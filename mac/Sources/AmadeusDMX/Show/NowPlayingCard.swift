// The track, the section and what comes next; the laser guard's actions.
import AmadeusKit
import SwiftUI

struct NowPlayingCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let state = model.showState
        Group {
            if let h = model.feed.hello, state.isActive {
                let i = model.feed.phrase
                let d = h.plan.indices.contains(i) ? h.plan[i] : nil
                let next = h.plan.indices.contains(i + 1) ? h.plan[i + 1] : nil
                VStack(alignment: .leading, spacing: 8) {
                    ProgramBanner(program: h.program)
                    HStack(spacing: 8) {
                        Image(systemName: state == .playing ? "music.note" : "dot.radiowaves.left.and.right")
                            .foregroundStyle(.secondary)
                        Text(h.title).font(.headline).lineLimit(1)
                        GenreChip(genre: h.genre, source: h.genreSource, style: h.style)
                    }
                    HStack(spacing: 14) {
                        Metric(value: "\(Int(h.bpm.rounded()))", label: "BPM")
                        Metric(value: timeString(model.feed.time), label: "of \(timeString(h.duration))")
                        if let d { Metric(value: d.section.capitalized, label: "now", color: Color(simd: Sections.color(d.section))) }
                        if let next {
                            let left = max(0, next.start - model.feed.time)
                            Metric(value: next.dropScore >= 0.6 || next.section == "drop" ? "⚡ \(Int(left))s" : "\(Int(left))s",
                                   label: "→ \(next.section)")
                        }
                    }
                    if let d { IntensityPips(level: d.intensity) }
                    if !model.feed.laserGuard.isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(model.feed.laserGuard.sorted { $0.key < $1.key }, id: \.key) { id, note in
                                Label("\(id): \(note)", systemImage: note.hasPrefix("blanked") || note.hasPrefix("dark")
                                      ? "exclamationmark.octagon.fill" : "arrow.up.circle")
                                    .font(.caption)
                                    .foregroundStyle(note.hasPrefix("blanked") || note.hasPrefix("dark") ? .red : .orange)
                            }
                        }
                        .help("The laser guard keeps laser beams out of the laser safety zones (rig editor)")
                    }
                }
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.currentSet?.name ?? "No set").font(.headline)
                    Text(idleText(state)).font(.callout).foregroundStyle(.secondary)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: 420, alignment: .leading)
        .glassEffect(.regular, in: .rect(cornerRadius: 18))
    }

    private func idleText(_ s: ShowState) -> String {
        switch s {
        case .stopped: "Rig preview. Press Start (⌘R) for a live show, or play a track (⌘O)."
        case .starting: "The engine is starting…"
        case .waitingForDJ: "\(model.showTitle). \(model.djWaiting)"
        case .failed(let why): why
        default: ""
        }
    }
}

struct Metric: View {
    var value: String
    var label: String
    var color: Color? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value).font(.title3.weight(.semibold).monospacedDigit()).foregroundStyle(color ?? .primary)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
    }
}

struct IntensityPips: View {
    var level: Int
    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<4) { k in
                Capsule().fill(k <= level ? Color.orange : Color.secondary.opacity(0.25)).frame(width: 18, height: 4)
            }
            Text("intensity").font(.caption2).foregroundStyle(.secondary).padding(.leading, 4)
        }
    }
}
