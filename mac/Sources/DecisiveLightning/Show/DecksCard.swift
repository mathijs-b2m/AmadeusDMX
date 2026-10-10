// VirtualDJ's decks: what each one plays and how far its show is prepared.
import DecisiveKit
import SwiftUI

struct DecksCard: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let link = model.feed.link {  // VirtualDJ on a DJ laptop: how the link is doing
                HStack(spacing: 6) {
                    Image(systemName: "laptopcomputer").foregroundStyle(link.up ? Color.green : Color.orange)
                    Text(link.name).font(.caption.weight(.semibold)).lineLimit(1)
                    Spacer()
                    Text(link.up ? String(format: "±%.0f ms · %d lost", link.jitterMs, link.lost) : "link down")
                        .font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                }
                if !link.fetching.isEmpty {
                    Label("Fetching \(link.fetching.joined(separator: ", "))", systemImage: "arrow.down.circle")
                        .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            ForEach(model.feed.decks) { d in
                DeckRow(deck: d)
            }
        }
        .padding(14)
        .frame(width: 330)
        .glassEffect(.regular, in: .rect(cornerRadius: 18))
    }
}

struct DeckRow: View {
    var deck: DeckInfo

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Text("\(deck.deck)")
                    .font(.caption.weight(.bold))
                    .frame(width: 20, height: 20)
                    .background(deck.play ? Color.accentColor : Color.secondary.opacity(0.3), in: .circle)
                    .foregroundStyle(.white)
                Text(deck.track).font(.callout.weight(.medium)).lineLimit(1)
                Spacer()
                Image(systemName: deck.play ? "play.fill" : "pause.fill").font(.caption).foregroundStyle(.secondary)
            }
            ProgressView(value: min(1, deck.vol)).progressViewStyle(.linear).tint(deck.play ? .green : .gray)
            if let s = deck.status {
                HStack(spacing: 6) {
                    StepChip(title: "Analysis", state: s.analysis)
                    StepChip(title: "Instruments", state: s.stems,
                             extra: s.stems == "running" ? s.elapsed.map { timeString(Double($0)) } : nil)
                    StepChip(title: "AI", state: s.ai,
                             extra: s.ai == "running" ? "\(s.aiDone ?? 0)/\(s.aiTotal.map(String.init) ?? "…")" : nil)
                    Spacer()
                    if let l = s.lights {
                        Text(l == "openai" ? "AI plan" : l == "rules" ? "quick plan" : l)
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

struct StepChip: View {
    var title: String
    var state: String?
    var extra: String? = nil

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: symbol)   // static: a spinning icon redraws the window every frame
            Text(extra.map { "\(title) \($0)" } ?? title)
        }
        .font(.caption2)
        .padding(.horizontal, 6).padding(.vertical, 2)
        .background(tint.opacity(0.18), in: .capsule)
        .foregroundStyle(tint)
    }

    private var symbol: String {
        switch state {
        case "done": "checkmark"
        case "running": "arrow.triangle.2.circlepath"
        case "failed": "exclamationmark.triangle"
        case "n/a": "minus"
        default: "circle.dotted"
        }
    }

    private var tint: Color {
        switch state {
        case "done": .green
        case "running": .orange
        case "failed": .red
        default: .secondary
        }
    }
}
