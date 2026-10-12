// What the director decided for the phrase that is playing (or the one you pick).
import AmadeusKit
import SwiftUI

struct DirectorInspector: View {
    @Environment(AppModel.self) private var model
    @State private var pinned: Int?

    var body: some View {
        if let h = model.feed.hello, model.feed.state == .connected, !h.plan.isEmpty {
            let i = min(h.plan.count - 1, pinned ?? model.feed.phrase)
            let d = h.plan[i]
            let hasLasers = h.fixtures.contains { $0.kind == .laser }
            let hasGroups = d.fields["grouping"] != nil && h.fixtures.filter { $0.kind == .head }.count > 4
            Form {
                SwiftUI.Section {
                    HStack {
                        Button { pinned = max(0, i - 1) } label: { Image(systemName: "chevron.left") }
                            .buttonStyle(.borderless).disabled(i == 0)
                        VStack(spacing: 2) {
                            Text("Phrase \(i + 1) of \(h.plan.count)").font(.headline)
                            Text("\(timeString(d.start)) – \(timeString(d.end))").font(.caption).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        Button { pinned = min(h.plan.count - 1, i + 1) } label: { Image(systemName: "chevron.right") }
                            .buttonStyle(.borderless).disabled(i == h.plan.count - 1)
                    }
                    if pinned != nil {
                        Button("Follow the Show") { pinned = nil }.frame(maxWidth: .infinity)
                    }
                }
                SwiftUI.Section("Moment") {
                    LabeledContent("Section") {
                        HStack(spacing: 6) {
                            Circle().fill(Color(simd: Sections.color(d.section))).frame(width: 9, height: 9)
                            Text(d.section.capitalized)
                            if d.dropScore >= 0.6 { Image(systemName: "bolt.fill").foregroundStyle(.yellow) }
                            Confidence(d.confidence["section"])
                        }
                    }
                    LabeledContent("Intensity") { IntensityPips(level: d.intensity).labelsHidden() }
                    LabeledContent("Palette") {
                        HStack(spacing: 4) {
                            Text(d.palette.capitalized)
                            ForEach(Array(Palettes.colors(d.palette).enumerated()), id: \.offset) { _, c in
                                RoundedRectangle(cornerRadius: 3).fill(Color(simd: c)).frame(width: 12, height: 12)
                            }
                        }
                    }
                    LabeledContent("Decided by", value: source(d.source))
                }
                SwiftUI.Section("Pars") {
                    Row("Between hits", d, "par_base")
                    Row("On a hit", d, "par_accent")
                    Row("A hit is", d, "trigger")
                }
                SwiftUI.Section("Moving Heads") {
                    Row("Light", d, "head_light")
                    Row("Path", d, "movement")
                    Row("Formation", d, "formation")
                    Row("Aim", d, "aim")
                    Row("Colour", d, "head_color")
                    Row("Beam", d, "beam_fx")
                    Row("Gobos", d, "gobo_style")
                    Row("Dynamics", d, "dynamics")
                }
                if hasGroups {
                    SwiftUI.Section("Groups") {
                        Row("Together", d, "grouping")
                        if d["featured"] != "–" && !d["featured"].isEmpty { Row("Featured", d, "featured") }
                        Row("Layering", d, "layer_split")
                        Row("Base glow", d, "base_glow")
                    }
                }
                if hasLasers {
                    SwiftUI.Section("Lasers") {
                        Row("Look", d, "laser_look")
                        if d["laser_look"] != "off" {
                            Row("Movement", d, "laser_move")
                            Row("Colour", d, "laser_color")
                        }
                    }
                }
                if h.screen {
                    SwiftUI.Section("LED Wall") { Row("Shows", d, "screen") }
                }
                if let probs = bestProbabilities(d) {
                    SwiftUI.Section("How Sure: \(probs.title)") {
                        ForEach(probs.values, id: \.0) { k, p in
                            HStack {
                                Text(k.replacingOccurrences(of: "_", with: " ")).frame(width: 110, alignment: .leading)
                                ProgressView(value: p)
                                Text("\(Int((p * 100).rounded()))%").monospacedDigit().foregroundStyle(.secondary)
                                    .frame(width: 38, alignment: .trailing)
                            }
                            .font(.callout)
                        }
                    }
                } else if d.source == "rules" {
                    SwiftUI.Section {
                        Text(rulesNote).font(.callout).foregroundStyle(.secondary)
                    }
                }
                if !d.prompt.isEmpty {
                    SwiftUI.Section {
                        DisclosureGroup("What the AI was told") {
                            Text(d.prompt).font(.caption.monospaced()).textSelection(.enabled)
                        }
                    }
                }
            }
            .formStyle(.grouped)
        } else {
            ContentUnavailableView("No Show Running", systemImage: "wand.and.stars",
                                   description: Text("The director's decisions appear here, phrase by phrase."))
        }
    }

    private func source(_ s: String) -> String {
        switch s {
        case "openai": "AI (Decisions API)"
        case "openai+hold": "AI, unsure: held the look"
        case "rules": "Rules"
        default: s.hasPrefix("ollama") ? "Local AI" : s
        }
    }

    private var rulesNote: String {
        let st = model.feed.decks.compactMap(\.status).first { $0.lights == "rules" }
        if st?.ai == "running" {
            return "Quick plan for now: the AI is still deciding this track (\(st?.aiDone ?? 0)/\(st?.aiTotal.map(String.init) ?? "…") phrases). It takes over when it is done."
        }
        if st?.stems == "running" { return "Quick plan for now: the instruments are separated first, then the AI decides." }
        return "The rule-based director has no probabilities. Choose an AI director in the set's settings to see how sure it is."
    }

    private func bestProbabilities(_ d: Decision) -> (title: String, values: [(String, Double)])? {
        for key in ["par_accent", "movement", "section", "screen"] {
            if let p = d.probabilities[key], !p.isEmpty {
                return (key.replacingOccurrences(of: "_", with: " "), p.sorted { $0.value > $1.value }.prefix(5).map { ($0.key, $0.value) })
            }
        }
        return nil
    }
}

private struct Row: View {
    var title: String
    var d: Decision
    var key: String

    init(_ title: String, _ d: Decision, _ key: String) { self.title = title; self.d = d; self.key = key }

    var body: some View {
        LabeledContent(title) {
            HStack(spacing: 6) {
                Text(d[key].replacingOccurrences(of: "_", with: " "))
                Confidence(d.confidence[key])
            }
        }
    }
}

private struct Confidence: View {
    var value: Double?
    init(_ v: Double?) { value = v }
    var body: some View {
        if let v = value {
            Text("\(Int((v * 100).rounded()))%")
                .font(.caption2.monospacedDigit())
                .padding(.horizontal, 5).padding(.vertical, 1)
                .background((v >= 0.6 ? Color.green : v >= 0.4 ? .orange : .red).opacity(0.18), in: .capsule)
                .foregroundStyle(v >= 0.6 ? Color.green : v >= 0.4 ? .orange : .red)
        }
    }
}
