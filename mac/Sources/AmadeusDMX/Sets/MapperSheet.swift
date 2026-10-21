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

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let m = mapping {
                if !m.refusal.isEmpty {
                    ContentUnavailableView("Not Mapped Here", systemImage: "exclamationmark.triangle", description: Text(m.refusal))
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
        .onDisappear { stopTrying() }
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
                Toggle(isOn: Binding(get: { trying }, set: { $0 ? startTrying() : stopTrying() })) {
                    Label("Try on the Lights", systemImage: trying ? "lightbulb.fill" : "lightbulb")
                }
                .toggleStyle(.button)
                .tint(trying ? .yellow : nil)
                .disabled(tryRefusal != nil || mapping == nil || !(mapping?.refusal.isEmpty ?? false))
                .help(tryRefusal ?? "Send these values as they are to \(target.fixture) (the rest of the set dark, a running show paused), to see what each channel does")
            }
            Text("Give each channel what the show plays on it, or hold it at a value (programs off, a shutter open, a macro on a colour). Every \(mapping?.name ?? "fixture of this model") in your sets plays by it.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(16)
    }

    private func channels(_ m: FixtureMapping) -> some View {
        List {
            ForEach(m.channels.indices, id: \.self) { i in
                ChannelRow(channel: binding(i), roles: m.roles, address: target.address.map { $0 + i }, universe: target.universe) {
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
        do { mapping = try await model.api.mapping(key: target.key, mode: target.mode) }
        catch { self.error = error.localizedDescription }
    }

    private func save() async {
        guard let m = mapping else { return }
        saving = true
        defer { saving = false }
        do {
            problems = try await model.api.saveMapping(m)
            if problems.isEmpty { stopTrying(); saved(); dismiss() }
        } catch { problems = [error.localizedDescription] }
    }

    // MARK: trying on the lights

    private var raw: [Int] { mapping?.channels.map(\.value) ?? [] }
    /// The channels given a light role: the engine keeps them under the brightness limiter.
    private var light: [Int] {
        let roles = Set((mapping?.roles ?? []).filter { $0.group != "Position" }.map(\.role))
        return (mapping?.channels ?? []).enumerated().filter { roles.contains($0.element.role) }.map(\.offset)
    }

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
