// The DMX mapper: what each channel of a fixture's mode does, set by hand, for fixtures the show can't play from
// their library file (effect lights, colour macros, numbered or unnamed channels). Each channel is played (a
// dimmer, a colour, pan or tilt, optionally for one cell of a bar) or held at a value. "Try on the Lights" sends
// the values as they are to one fixture of the set, so you can find what a channel does; the library's names and
// ranges are shown where QLC+ or the Open Fixture Library has them. Saved into your copy of the definition
// (amadeus/library/mapper.py): every fixture of that model plays by it.
import AmadeusKit
import SwiftUI

struct MapTarget: Identifiable {
    var key: String
    var mode: String
    var fixture: String      // the one tried on the lights
    var address: Int?        // nil: no start address yet (nothing can be tried)
    var universe: Int
    var id: String { "\(key)|\(mode)" }
}

struct MapperSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: MapTarget
    let tryRefusal: String?          // why it can't be tried on the lights now (nil: it can)
    let saved: () -> Void

    @State private var mapping: FixtureMapping?
    @State private var problems: [String] = []
    @State private var error: String?
    @State private var trying = false
    @State private var sending: Task<Void, Never>?
    @State private var saving = false
    // the check, channel by channel on the fixture
    @State private var checking: Int?        // the channel being checked
    @State private var probe = 0
    @State private var sweeping = true
    @State private var checkLoop: Task<Void, Never>?
    @State private var checkedAll = false    // every channel was checked: saved as checked
    @State private var colours: Int?         // the colour wheel (or ring colour) channel whose colours are being named
    @State private var loadedWheel: [FixtureMapping.Slot] = []   // the wheel as loaded: saved again only when changed
    @State private var loadedRing: [FixtureMapping.Slot] = []

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let m = mapping {
                if !m.refusal.isEmpty {
                    ContentUnavailableView("Not Mapped Here", systemImage: "exclamationmark.triangle", description: Text(m.refusal))
                } else if let i = checking {
                    ChannelCheck(mapping: Binding(get: { mapping! }, set: { mapping = $0 }),
                                 index: Binding(get: { i }, set: { checking = $0 }),
                                 probe: $probe, sweeping: $sweeping) {
                        checkedAll = true
                        stopCheck()
                    }
                } else if let i = colours {
                    ColourWheelEditor(mapping: Binding(get: { mapping! }, set: { mapping = $0 }), index: i,
                                      probe: $probe, sweeping: $sweeping) { closeColours() }
                } else {
                    channels(m)
                }
            } else if let error {
                ContentUnavailableView("Couldn’t Read the Fixture", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            Divider()
            footer
        }
        .frame(minWidth: 760, idealWidth: 860, minHeight: 520, idealHeight: 640)
        .task { await load() }
        .onDisappear { stopTrying(); stopCheck(); closeColours() }
    }

    // MARK: parts

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("Map DMX Channels").font(.title2.weight(.semibold))
                Text(mapping?.name ?? target.key).foregroundStyle(.secondary)
                Spacer()
                if let m = mapping, m.refusal.isEmpty {
                    Picker("Kind", selection: Binding(get: { m.kind }, set: { mapping?.kind = $0 })) {
                        ForEach(kindChoices(m), id: \.0) { Text($0.1).tag($0.0) }
                    }
                    .fixedSize()
                    .help("What it is, when its channels don't say: pan and tilt make a moving head, cells a bar")
                }
            }
            HStack(spacing: 14) {
                Text("Mode \(target.mode)").font(.callout).foregroundStyle(.secondary)
                if let m = mapping {
                    Label(m.plays ? "The show plays it" : "The show plays nothing in this mode yet",
                          systemImage: m.plays ? "checkmark.circle" : "exclamationmark.triangle.fill")
                        .font(.callout).foregroundStyle(m.plays ? Color.secondary : Color.orange)
                }
                Spacer()
                if checking == nil && colours == nil {
                    Toggle(isOn: Binding(get: { trying }, set: { $0 ? startTrying() : stopTrying() })) {
                        Label("Try on the Lights", systemImage: trying ? "lightbulb.fill" : "lightbulb")
                    }
                    .toggleStyle(.button)
                    .tint(trying ? .yellow : nil)
                    .disabled(tryRefusal != nil || mapping == nil || !(mapping?.refusal.isEmpty ?? false))
                    .help(tryRefusal ?? "Send these values as they are to \(target.fixture) (the rest of the set dark, a running show paused), to see what each channel does")
                }
                Button(checking == nil ? "Check Channels" : "Stop Checking",
                       systemImage: checking == nil ? "checklist" : "stop.fill") {
                    checking == nil ? startCheck() : stopCheck()
                }
                .buttonStyle(.bordered)
                .tint(needsCheck && checking == nil ? .orange : nil)
                .disabled(tryRefusal != nil || mapping == nil || !(mapping?.refusal.isEmpty ?? false) || colours != nil)
                .help(tryRefusal ?? "Go through the channels one by one on \(target.fixture): each sweeps while you say what the fixture does")
            }
            if needsCheck && !checkedAll && checking == nil {
                Label("Made from a common layout: check it channel by channel on the fixture, manuals of these are often wrong.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.callout).foregroundStyle(.orange)
            } else if checkedAll && checking == nil {
                Label("Every channel checked: save it.", systemImage: "checkmark.circle.fill").font(.callout).foregroundStyle(.green)
            } else {
                Text("Give each channel what the show plays on it, or hold it at a value (programs off, a shutter open, a macro on a colour). Every \(mapping?.name ?? "fixture of this model") in your sets plays by it.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
    }

    private func channels(_ m: FixtureMapping) -> some View {
        List {
            ForEach(m.channels.indices, id: \.self) { i in
                ChannelRow(channel: binding(i), roles: m.roles, address: target.address.map { $0 + i }, universe: target.universe,
                           colours: tryRefusal == nil ? { openColours(i) } : nil) {
                    valuesChanged()
                }
            }
        }
        .listStyle(.inset(alternatesRowBackgrounds: true))
    }

    private var footer: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(problems, id: \.self) { p in
                    Label(p, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange).font(.callout)
                }
            }
            Spacer()
            Button("Cancel", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
            Button("Save Mapping") { Task { await save() } }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(mapping == nil || !(mapping?.refusal.isEmpty ?? false) || saving || model.engineRunning)
                .help(model.engineRunning ? "Stop the show to change a fixture" : "Save it into your copy of the fixture")
        }
        .padding(16)
    }

    // MARK: helpers

    private func binding(_ i: Int) -> Binding<FixtureMapping.Channel> {
        Binding(get: { mapping!.channels[i] }, set: { mapping?.channels[i] = $0 })
    }

    private func kindChoices(_ m: FixtureMapping) -> [(String, String)] {
        var out = m.kinds.sorted { $0.value < $1.value }.map { ($0.key, $0.value) }
        if m.kinds[m.kind] == nil { out.insert((m.kind, m.kind.replacingOccurrences(of: "_", with: " ").capitalized), at: 0) }
        return out
    }

    private func load() async {
        guard await model.ensureSetupService() else { error = SetupAPIError.notRunning.localizedDescription; return }
        do {
            mapping = try await model.api.mapping(key: target.key, mode: target.mode)
            loadedWheel = mapping?.wheel ?? []
            loadedRing = mapping?.ring ?? []
        }
        catch { self.error = error.localizedDescription }
    }

    private func save() async {
        guard let m = mapping else { return }
        saving = true
        defer { saving = false }
        do {
            problems = try await model.api.saveMapping(m, checked: checkedAll, wheel: m.wheel != loadedWheel, ring: m.ring != loadedRing)
            if problems.isEmpty { stopTrying(); saved(); dismiss() }
        } catch { problems = [error.localizedDescription] }
    }

    // MARK: the check

    private var needsCheck: Bool { (mapping?.made ?? false) && !(mapping?.checked ?? true) }

    private func startCheck() {
        stopTrying()
        checking = 0
        probe = 0
        sweeping = true
        startProbing()
    }

    /// The colour wheel's (or the ring's) colours, shown one by one on the fixture (the light on, the head in the middle).
    private func openColours(_ i: Int) {
        stopTrying()
        let ring = mapping?.channels[i].role == "ring_color"
        if ring, mapping?.ring.isEmpty ?? false { mapping?.ring = FixtureMapping.usualRing }
        if !ring, mapping?.wheel.isEmpty ?? false { mapping?.wheel = FixtureMapping.usualWheel }
        colours = i
        probe = (ring ? mapping?.ring.first?.mid : mapping?.wheel.first?.mid) ?? 0
        sweeping = false
        startProbing()
    }

    private func closeColours() {
        guard colours != nil else { return }
        colours = nil
        stopCheck()
    }

    /// Sends the probed channel's value (sweeping, or as set) with the others holding the light on, ~10 times a second.
    private func startProbing() {
        checkLoop?.cancel()
        let id = target.fixture, rig = model.selectedRig, set = model.editingSet
        checkLoop = Task {
            var up = true
            while !Task.isCancelled, let i = checking ?? colours, let m = mapping {
                if sweeping {  // 0 → 255 → 0 in about 8 s
                    probe = up ? min(probe + 6, 255) : max(probe - 6, 0)
                    if probe == 255 || probe == 0 { up.toggle() }
                }
                do {
                    _ = try await model.api.testLight(fixture: id, on: true, raw: m.checkValues(probe: i, value: probe),
                                                      light: m.lightChannels, rig: rig, set: set)
                } catch {
                    problems = [error.localizedDescription]
                    checking = nil
                    colours = nil
                    break
                }
                try? await Task.sleep(for: .milliseconds(90))
            }
        }
    }

    private func stopCheck() {
        guard checking != nil || checkLoop != nil else { return }
        checking = nil
        checkLoop?.cancel()
        checkLoop = nil
        let id = target.fixture, rig = model.selectedRig, set = model.editingSet
        Task { _ = try? await model.api.testLight(fixture: id, on: false, rig: rig, set: set) }
    }

    // MARK: trying on the lights

    private var raw: [Int] { mapping?.channels.map(\.value) ?? [] }
    /// The channels given a light role: the engine keeps them under the brightness limiter.
    private var light: [Int] { mapping?.lightChannels ?? [] }

    private func startTrying() {
        trying = true
        send()
    }

    private func stopTrying() {
        guard trying else { return }
        trying = false
        sending?.cancel()
        let id = target.fixture, rig = model.selectedRig, set = model.editingSet
        Task { _ = try? await model.api.testLight(fixture: id, on: false, rig: rig, set: set) }
    }

    private func valuesChanged() { if trying { send() } }

    /// The values to the fixture, at most ~20 times a second while a slider moves.
    private func send() {
        sending?.cancel()
        let values = raw, lit = light, id = target.fixture, rig = model.selectedRig, set = model.editingSet
        sending = Task {
            try? await Task.sleep(for: .milliseconds(50))
            guard !Task.isCancelled, trying else { return }
            do { _ = try await model.api.testLight(fixture: id, on: true, raw: values, light: lit, rig: rig, set: set) }
            catch { trying = false; problems = [error.localizedDescription] }
        }
    }
}

/// One channel: its number and address, the library's name and ranges, what the show does with it, its value.
private struct ChannelRow: View {
    @Binding var channel: FixtureMapping.Channel
    let roles: [FixtureMapping.Role]
    let address: Int?
    let universe: Int
    let colours: (() -> Void)?   // name the colour wheel's or the ring's colours (nil: can't be tried on the lights now)
    let changed: () -> Void

    private var role: FixtureMapping.Role? { roles.first { $0.role == channel.role } }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text("\(channel.n)").font(.body.monospacedDigit().weight(.semibold))
                Text(address.map { "\(universe).\(String(format: "%03d", $0))" } ?? "–").font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            }
            .frame(width: 44, alignment: .leading)

            HStack(spacing: 4) {
                Text(channel.name).lineLimit(1).truncationMode(.tail)
                if !channel.ranges.isEmpty {
                    Menu {
                        ForEach(channel.ranges, id: \.self) { r in
                            Button("\(r.lo)–\(r.hi)  \(r.what.isEmpty ? "–" : r.what)") { channel.value = r.mid; changed() }
                        }
                    } label: { Image(systemName: "list.bullet") }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                    .help("What its values do (from the fixture library): pick one to set it")
                }
            }
            .frame(width: 200, alignment: .leading)

            Picker("", selection: Binding(get: { channel.role }, set: { channel.role = $0 })) {
                Text("Hold at value").tag("hold")
                if channel.role == "keep" { Text("Keep (\(channel.attr.replacingOccurrences(of: "_", with: " ")))").tag("keep") }
                Divider()
                ForEach(Array(Set(roles.map(\.group))).sorted(), id: \.self) { g in
                    SwiftUI.Section(g) {
                        ForEach(roles.filter { $0.group == g }, id: \.role) { Text($0.label).tag($0.role) }
                    }
                }
            }
            .labelsHidden()
            .frame(width: 150)

            if role?.cell == true {
                Stepper(channel.cell == 0 ? "Whole" : "Cell \(channel.cell)", value: $channel.cell, in: 0...64)
                    .frame(width: 110, alignment: .leading)
                    .help("Which cell of a bar it belongs to (Whole: the fixture as one)")
            } else if channel.role == "color_wheel" || channel.role == "ring_color" {
                Button("Colours…") { colours?() }
                    .disabled(colours == nil)
                    .frame(width: 110, alignment: .leading)
                    .help(colours == nil ? "Give the fixture a start address and a DMX output to see its colours"
                                         : channel.role == "ring_color"
                                         ? "Show each colour of the ring on the fixture, name it and set its values (name the one where it is off \"off\")"
                                         : "Show each colour of the wheel on the fixture, name it and set its values")
            } else {
                Color.clear.frame(width: 110, height: 1)
            }

            Slider(value: Binding(get: { Double(channel.value) }, set: { channel.value = Int($0.rounded()); changed() }), in: 0...255)
                .frame(minWidth: 120)
                .help(channel.role == "hold" ? "The value it is held at" : "A value to try on the lights (the show plays this channel)")
            TextField("", value: Binding(get: { channel.value }, set: { channel.value = min(max($0, 0), 255); changed() }),
                      format: .number)
                .frame(width: 44)
                .multilineTextAlignment(.trailing)
                .foregroundStyle(channel.role == "hold" ? .primary : .secondary)
        }
        .padding(.vertical, 2)
    }
}
