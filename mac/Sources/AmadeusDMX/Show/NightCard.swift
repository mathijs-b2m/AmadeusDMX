// The night (the show arc, live mode): the countdown, the stage the music is in, and the knobs the arc turns
// over the night. Any knob can be taken over (it then stays where you put it) and given back (Auto).
// The engine does the work (amadeus/show/arc.py); this card only shows it and sends what you change.
import AmadeusKit
import SwiftUI

struct NightCard: View {
    @Environment(AppModel.self) private var model
    var arc: ArcStatus
    @AppStorage("nightCardOpen") private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if open {
                Divider()
                if arc.on {
                    StageStrip(arc: arc, send: send)
                    HeatRow(arc: arc)
                    Divider()
                    ForEach(Knob.sections, id: \.title) { sec in
                        Text(sec.title.uppercased()).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                            .padding(.top, 2)
                        ForEach(sec.knobs) { k in KnobRow(knob: k, arc: arc, send: send) }
                    }
                    Divider()
                }
                NightSettings(arc: arc, send: send)
            }
        }
        .padding(14)
        .frame(width: open ? 340 : nil, alignment: .leading)
        .glassEffect(.regular, in: .rect(cornerRadius: 18))
        .animation(.snappy(duration: 0.2), value: open)
    }

    private var header: some View {
        Button { open.toggle() } label: {
            HStack(spacing: 10) {
                Image(systemName: arc.on ? "moon.stars" : "moon.zzz").foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 5) {
                        Text(arc.on ? arc.stageName : "Show Arc Off").font(.headline)
                        if arc.locked { Image(systemName: "pin.fill").font(.caption).foregroundStyle(.orange) }
                        if !arc.manual.isEmpty {
                            Image(systemName: "hand.raised.fill").font(.caption).foregroundStyle(.orange)
                                .help("You hold \(arc.manual.count) knob\(arc.manual.count == 1 ? "" : "s")")
                        }
                    }
                    Text(clockText).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                if let left = arc.remaining {
                    Text(left >= 0 ? hms(left) : "+\(hms(-left))")
                        .font(.title2.weight(.semibold).monospacedDigit())
                        .foregroundStyle(left < 0 ? .orange : .primary)
                        .help(left >= 0 ? "Left of the night" : "Over the night's length")
                }
                Image(systemName: "chevron.down").rotationEffect(.degrees(open ? 180 : 0)).foregroundStyle(.secondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("The night: its stage, countdown and the knobs the show arc turns")
    }

    private var clockText: String {
        guard let e = arc.elapsed else { return "starts with the music · \(hm(arc.length))" }
        return "\(hm(e)) of \(hm(arc.length))"
    }

    private func send(_ fields: [String: Any]) {
        model.feed.send(["type": "arc"].merging(fields) { a, _ in a })
    }
}

/// The knobs, as the engine names them.
struct Knob: Identifiable {
    var id: String
    var title: String
    var symbol: String
    var help: String
    var toggle = false

    /// The knobs as a lighting director thinks of them: what is in play tonight, the character of each track,
    /// how hard the lights react, and the master level.
    static let sections: [(title: String, knobs: [Knob])] = [
        ("In Play", [
            Knob(id: "groups", title: "Light Groups", symbol: "square.grid.2x2",
                 help: "How many groups of lights play: washes first, then the heads, the biggest group last. A group that hasn't played yet tonight is a surprise: it comes out on a drop. All the way down: none"),
            Knob(id: "specials", title: "Special Effects", symbol: "sparkles",
                 help: "Lasers, strobes and blinders: in the box (off), out for the big moments only (the drops), or free (as the director plans them)"),
            Knob(id: "screen", title: "LED Wall", symbol: "tv",
                 help: "The LED wall: below half only calm colour (no characters, words or psychedelics), at zero off"),
            Knob(id: "smoke", title: "Smoke", symbol: "cloud.fog", help: "How much of the planned smoke goes out"),
        ]),
        ("Character", [
            Knob(id: "movement", title: "Movement", symbol: "arrow.up.and.down.and.arrow.left.and.right",
                 help: "How busy the heads are: calm (slow sweeps and circles, beams stay on), mid (no wild paths), full (the director's beat-locked jumps). Each change re-plans the tracks in a few seconds"),
            Knob(id: "changes", title: "Look Changes", symbol: "rectangle.stack",
                 help: "How often the look changes within a song: low holds one look for up to eight phrases, high changes with every part the analysis finds. Re-plans the tracks in a few seconds"),
            Knob(id: "colour", title: "Colour Variety", symbol: "paintpalette",
                 help: "How much colour moves: low keeps a palette for several phrases, high swaps every eight bars"),
        ]),
        ("Reaction", [
            Knob(id: "response", title: "Beat Response", symbol: "waveform.path",
                 help: "How hard the lights hit with the beat: low glows and breathes, high punches every kick"),
            Knob(id: "drops", title: "Drops", symbol: "arrow.down.to.line",
                 help: "How big a drop lands: low a lift and (above a quarter) its own look; from a third a breath of darkness; full: blackout, bang, flash (as the director plans it)"),
            Knob(id: "flashes", title: "Flashes", symbol: "bolt", help: "White flash accents and strobes"),
        ]),
        ("Level", [
            Knob(id: "intensity", title: "Intensity", symbol: "sun.max", help: "The master: how bright the whole rig plays. All the way down: dark"),
        ]),
    ]
}

private struct KnobRow: View {
    var knob: Knob
    var arc: ArcStatus
    var send: ([String: Any]) -> Void
    @State private var draft: Double?

    var body: some View {
        let manual = arc.manual.contains(knob.id)
        let value = draft ?? arc.values[knob.id] ?? 1
        HStack(spacing: 8) {
            Image(systemName: knob.symbol).frame(width: 18).foregroundStyle(.secondary)
            Text(knob.title).frame(width: 110, alignment: .leading).lineLimit(1)
            if knob.toggle {
                Toggle("", isOn: Binding(get: { value >= 0.5 }, set: { send(["knob": [knob.id: $0 ? 1.0 : 0.0]]) }))
                    .labelsHidden().toggleStyle(.switch).controlSize(.small)
                Spacer()
            } else {
                Slider(value: Binding(get: { value }, set: { v in draft = v; send(["knob": [knob.id: v]]) }), in: 0...1) { editing in
                    if !editing { draft = nil }
                }
                .controlSize(.small)
                Text(knob.id == "movement" ? ["calm", "mid", "full"][min(2, max(0, arc.movementLevel ?? 2))]
                     : knob.id == "changes" ? (arc.hold.map { $0 <= 1 ? "all" : "÷\($0)" } ?? "")
                     : knob.id == "specials" ? (value < 0.25 ? "box" : value < 0.75 ? "drops" : "free")
                     : "\(Int((value * 100).rounded()))")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    .frame(width: 34, alignment: .trailing)
            }
            Button("Auto") { send(["auto": knob.id]) }
                .buttonStyle(.borderless)
                .font(.caption.weight(manual ? .regular : .semibold))
                .foregroundStyle(manual ? Color.secondary : Color.accentColor)
                .disabled(!manual)
                .help(manual ? "Give this knob back to the show arc" : "The show arc turns this knob")
        }
        .font(.callout)
        .help(knob.id == "groups" ? "\(knob.help) (\(arc.playing) of \(arc.groups) playing)" : knob.help)
    }
}

/// The stages, named for the event: the one the music is in lit; click one to force it.
private struct StageStrip: View {
    var arc: ArcStatus
    var send: ([String: Any]) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                ForEach(arc.stages, id: \.self) { s in
                    let key = s.first ?? "", now = key == arc.stage
                    Button { send(["stage": key]) } label: {
                        Text(s.last ?? key).font(.caption2.weight(now ? .bold : .regular)).lineLimit(2)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, minHeight: 30)
                            .background(now ? Color.accentColor.opacity(0.35) : Color.secondary.opacity(0.12),
                                        in: .rect(cornerRadius: 6))
                    }
                    .buttonStyle(.plain)
                    .help(now ? "The music is here" : "Go to this stage now (the arc carries on from there)")
                }
            }
            HStack {
                Text(arc.locked ? "Held: the arc stays in this stage" : "The music decides the stage")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Toggle("Hold", isOn: Binding(get: { arc.locked }, set: { send(["lock": $0]) }))
                    .toggleStyle(.button).controlSize(.small)
                    .help("Keep the night in this stage until you let go")
            }
        }
    }
}

/// How hot the mix runs (what the stages are detected from).
private struct HeatRow: View {
    var arc: ArcStatus

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "thermometer.medium").frame(width: 18).foregroundStyle(.secondary)
            Text("Music heat").frame(width: 110, alignment: .leading)
            ProgressView(value: arc.heat).tint(.orange)
            Image(systemName: arc.trend > 0.02 ? "arrow.up.right" : arc.trend < -0.02 ? "arrow.down.right" : "arrow.right")
                .font(.caption).foregroundStyle(.secondary)
            if let bpm = arc.bpm { Text("\(Int(bpm.rounded()))").font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
        }
        .font(.callout)
        .help("How hot the mix runs: the tracks' energy and the tempo against tonight's warm-up tempo\(arc.baseBpm.map { " (\(Int($0.rounded())) BPM)" } ?? ""). The stages are detected from it.")
    }
}

/// The event type, the night's length, on/off and a new night.
private struct NightSettings: View {
    var arc: ArcStatus
    var send: ([String: Any]) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Picker("Event", selection: Binding(get: { arc.event }, set: { send(["event": $0]) })) {
                    ForEach(arc.events, id: \.self) { e in Text(e.last ?? "").tag(e.first ?? "") }
                }
                .help("What kind of night: it names the stages, sets where in the night they may come, and the character (a wedding: fewer lasers, less smoke)")
            }
            HStack {
                Text("Length")
                Spacer()
                Button { send(["length_s": arc.length - 900]) } label: { Image(systemName: "minus") }
                    .buttonStyle(.borderless).disabled(arc.length <= 1800)
                Text(hm(arc.length)).font(.body.monospacedDigit()).frame(width: 48)
                Button { send(["length_s": arc.length + 900]) } label: { Image(systemName: "plus") }
                    .buttonStyle(.borderless).disabled(arc.length >= 12 * 3600)
            }
            .help("How long the night is: the countdown, and where the warm-up and the finale belong (a quarter of an hour per click)")
            HStack {
                Toggle("Show arc", isOn: Binding(get: { arc.on }, set: { send(["enabled": $0]) }))
                    .help("Off: the lights play every track as the director made it, at full")
                Spacer()
                if !arc.manual.isEmpty {
                    Button("All Auto") { send(["auto": "all"]) }.controlSize(.small)
                }
                Button("New Night") { send(["reset": true]) }.controlSize(.small)
                    .help("Start again: the clock waits for the music, the night begins with the warm-up")
            }
        }
        .font(.callout)
    }
}

private func hm(_ s: Double) -> String {
    let m = max(0, Int(s / 60))
    return String(format: "%d:%02d", m / 60, m % 60)
}

private func hms(_ s: Double) -> String {
    let t = max(0, Int(s))
    return String(format: "%d:%02d:%02d", t / 3600, t % 3600 / 60, t % 60)
}
