// The DMX mapper's check, channel by channel on the real fixture: one channel sweeps slowly from 0 to 255 while
// the others keep the light on and the head in the middle, and you say what the fixture does. That puts right what
// the manual (or the layout a fixture was made from) has wrong; a colour wheel's (or LED ring's) colours are named on
// the way.
import AmadeusKit
import SwiftUI

struct ChannelCheck: View {
    @Binding var mapping: FixtureMapping
    @Binding var index: Int
    @Binding var probe: Int          // the value the checked channel gets now
    @Binding var sweeping: Bool
    let finish: () -> Void

    private var channel: FixtureMapping.Channel { mapping.channels[index] }
    private var last: Bool { index == mapping.channels.count - 1 }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Channel \(channel.n) of \(mapping.channels.count)").font(.title3.weight(.semibold))
                    Text("now: \(now)").foregroundStyle(.secondary)
                    Spacer()
                }
                Text("Watch the fixture: this channel sweeps slowly from 0 to 255, the others keep the light on and the head in the middle. What does it do?")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                HStack {
                    Toggle(isOn: $sweeping) { Label(sweeping ? "Sweeping" : "Sweep", systemImage: sweeping ? "pause.fill" : "play.fill") }
                        .toggleStyle(.button)
                    Slider(value: Binding(get: { Double(probe) }, set: { probe = Int($0.rounded()); sweeping = false }), in: 0...255)
                    Text("\(probe)").font(.body.monospacedDigit()).frame(width: 34, alignment: .trailing)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 8)], alignment: .leading, spacing: 8) {
                    ForEach(mapping.check, id: \.self) { a in
                        Button { pick(a) } label: {
                            Text(a.answer).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.bordered)
                        .tint(chosen(a) ? .accentColor : nil)
                        .overlay(alignment: .trailing) {
                            if chosen(a) { Image(systemName: "checkmark").padding(.trailing, 8).foregroundStyle(.tint) }
                        }
                    }
                }
                if channel.role == "hold" {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Held at a value: set it where the light is on and steady (no strobe, no programs)").font(.callout)
                        HStack {
                            Slider(value: Binding(get: { Double(channel.value) }, set: { hold(Int($0.rounded())) }), in: 0...255)
                            Text("\(channel.value)").font(.body.monospacedDigit()).frame(width: 34, alignment: .trailing)
                        }
                        if !channel.ranges.isEmpty {
                            Text(channel.ranges.map { "\($0.lo)–\($0.hi) \($0.what)" }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                if channel.role == "color_wheel" { WheelNaming(slots: $mapping.wheel, probe: $probe, sweeping: $sweeping) }
                if channel.role == "ring_color" { WheelNaming(slots: $mapping.ring, probe: $probe, sweeping: $sweeping, ring: true) }
                HStack {
                    Button("Previous", systemImage: "chevron.left") { go(index - 1) }.disabled(index == 0)
                    Spacer()
                    if last {
                        Button("Finish Check") { finish() }.buttonStyle(.borderedProminent)
                    } else {
                        Button("Next Channel", systemImage: "chevron.right") { go(index + 1) }.buttonStyle(.borderedProminent)
                    }
                }
            }
            .padding(16)
        }
    }

    /// What the channel is now, in words.
    private var now: String {
        if channel.role == "hold" { return "held at \(channel.value) (\(channel.attr.replacingOccurrences(of: "_", with: " ")))" }
        return mapping.roles.first { $0.role == channel.role }?.label ?? channel.role
    }

    private func chosen(_ a: FixtureMapping.Answer) -> Bool {
        if a.role != "hold" { return channel.role == a.role }
        guard channel.role == "hold" else { return false }
        if let attr = a.attr { return channel.attr == attr }
        return !mapping.check.contains { $0.attr == channel.attr }  // "nothing": held, and none of the named ones
    }

    private func pick(_ a: FixtureMapping.Answer) {
        mapping.answer(a, for: index)
        if a.role == "hold" { sweeping = false; probe = channel.value }  // held there from now on
    }

    private func hold(_ v: Int) {
        mapping.channels[index].value = v
        sweeping = false
        probe = v
    }

    private func go(_ i: Int) {
        index = i
        probe = 0
        sweeping = true
    }
}

/// The mapper's Colours…: the colour wheel's (or the ring's) colours named and their values put right, without the
/// whole check.
struct ColourWheelEditor: View {
    @Binding var mapping: FixtureMapping
    let index: Int
    @Binding var probe: Int
    @Binding var sweeping: Bool
    let done: () -> Void

    private var ring: Bool { mapping.channels[index].role == "ring_color" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text(ring ? "Ring Colour" : "Colour Wheel").font(.title3.weight(.semibold))
                    Text("channel \(mapping.channels[index].n)").foregroundStyle(.secondary)
                    Spacer()
                    Button("Done") { done() }.buttonStyle(.borderedProminent)
                }
                Text(ring ? "The light is on and the head in the middle. Show each colour of the ring round the lens, say what you see, and set its values. Name the one where the ring is off \"off\": the ring rests with the head. Sweep goes through the whole channel."
                          : "The light is on and the head in the middle. Show each colour, say what you see, and set its values where the colour is whole (not between two). Sweep goes through the whole wheel.")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                HStack {
                    Toggle(isOn: $sweeping) { Label(sweeping ? "Sweeping" : "Sweep", systemImage: sweeping ? "pause.fill" : "play.fill") }
                        .toggleStyle(.button)
                    Slider(value: Binding(get: { Double(probe) }, set: { probe = Int($0.rounded()); sweeping = false }), in: 0...255)
                    Text("\(probe)").font(.body.monospacedDigit()).frame(width: 34, alignment: .trailing)
                }
                if ring {
                    WheelNaming(slots: $mapping.ring, probe: $probe, sweeping: $sweeping, ring: true)
                } else {
                    WheelNaming(slots: $mapping.wheel, probe: $probe, sweeping: $sweeping)
                }
            }
            .padding(16)
        }
    }
}

/// The colour wheel's (or a ring's) colours: show each on the fixture, say what it is, put its values right.
private struct WheelNaming: View {
    @Binding var slots: [FixtureMapping.Slot]
    @Binding var probe: Int
    @Binding var sweeping: Bool
    var ring = false             // a ring round the lens: "off" and "white" instead of the wheel's "open"

    private var choices: [(String, [Double])] {
        ring ? [("off", [0, 0, 0]), ("white", [1, 1, 1])] + Self.colours.dropFirst() : Self.colours
    }

    static let colours: [(String, [Double])] = [
        ("open", [1, 1, 1]), ("red", [1, 0, 0]), ("orange", [1, 0.45, 0]), ("yellow", [1, 0.9, 0]),
        ("green", [0, 1, 0]), ("cyan", [0, 0.9, 1]), ("light blue", [0.4, 0.7, 1]), ("blue", [0, 0.2, 1]),
        ("purple", [0.5, 0, 1]), ("magenta", [1, 0, 0.8]), ("pink", [1, 0.4, 0.7]), ("uv", [0.35, 0, 1]),
        ("warm white", [1, 0.8, 0.55]),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Name the colours: show each, say what you see, and set its values where the colour is whole").font(.callout)
            ForEach(slots.indices, id: \.self) { i in
                HStack(spacing: 8) {
                    Button("Show") { sweeping = false; probe = slots[i].mid }
                        .tint(probe >= slots[i].from && probe <= slots[i].to && !sweeping ? .accentColor : nil)
                    TextField("", value: $slots[i].from, format: .number).frame(width: 44)
                    Text("–")
                    TextField("", value: $slots[i].to, format: .number).frame(width: 44)
                    Circle().fill(Color(red: slots[i].rgb[0], green: slots[i].rgb[1], blue: slots[i].rgb[2]))
                        .frame(width: 14, height: 14).overlay(Circle().stroke(.secondary.opacity(0.5)))
                    Picker("", selection: Binding(get: { slots[i].name }, set: { name in
                        slots[i].name = name
                        if let c = choices.first(where: { $0.0 == name }) { slots[i].rgb = c.1 }
                    })) {
                        if !choices.contains(where: { $0.0 == slots[i].name }) { Text(slots[i].name).tag(slots[i].name) }
                        ForEach(choices, id: \.0) { Text($0.0).tag($0.0) }
                    }
                    .labelsHidden().frame(width: 130)
                    Button("Remove", systemImage: "minus.circle") { slots.remove(at: i) }
                        .labelStyle(.iconOnly).buttonStyle(.borderless).disabled(slots.count <= 1)
                }
            }
            Button("Add a Colour", systemImage: "plus") {
                let from = min((slots.last?.to ?? -1) + 1, 255)
                slots.append(.init(name: "red", from: from, to: min(from + 15, 255), rgb: [1, 0, 0]))
            }
            .buttonStyle(.borderless)
        }
        .padding(10)
        .background(.background.secondary, in: .rect(cornerRadius: 8))
    }
}
