// A fixture without a brand (or not in any library): made from a common channel layout. Cheap moving heads and
// pars are mostly the same few designs under many names, so their manuals look alike; you pick the layout closest
// to yours and say how many channels it has, and it is made in your library (amadeus/library/generic.py). Its
// channels are then checked one by one on the real fixture in the DMX mapper (Check Channels).
import AmadeusKit
import SwiftUI

struct NewFixtureSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var brand: String = ""
    let made: (_ key: String, _ mode: String) -> Void

    @State private var manufacturer = ""
    @State private var name = ""
    @State private var type = "spot"
    @State private var channels = 9
    @State private var watts = 0
    @State private var beamDeg = 0.0
    @State private var panDeg = 540
    @State private var tiltDeg = 270
    @State private var catalogue: FixtureTemplates?
    @State private var template: String?
    @State private var autoPicked = true   // the closest layout follows the type and channels until one is picked
    @State private var problems: [String] = []
    @State private var busy = false

    private var moving: Bool { catalogue?.types.first { $0.type == type }?.kind == "moving_head" }
    private var chosen: FixtureTemplates.Template? { catalogue?.templates.first { $0.id == template } }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("New Fixture").font(.title2.weight(.semibold))
            Text("For a fixture no library knows, often sold without a real brand. Most share a few common channel layouts: pick the one closest to the DMX table in its manual, then check it channel by channel on the fixture.")
                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Form {
                TextField("Brand", text: $manufacturer, prompt: Text("as on the box or label, or leave empty"))
                TextField("Name", text: $name, prompt: Text("e.g. 60W LED Spot"))
                Picker("Type", selection: $type) {
                    ForEach(catalogue?.types ?? [], id: \.type) { Text($0.label).tag($0.type) }
                }
                Stepper("Channels: \(channels)", value: $channels, in: 1...64)
                    .help("How many DMX channels it uses in the mode you'll run it in: the manual says, and the fixture's display often shows it (\"9CH\", \"d-11\")")
                if moving {
                    HStack {
                        Picker("Pan", selection: $panDeg) { ForEach([360, 540, 630], id: \.self) { Text("\($0)°").tag($0) } }
                        Picker("Tilt", selection: $tiltDeg) { ForEach([180, 220, 270], id: \.self) { Text("\($0)°").tag($0) } }
                    }
                    .help("How far it turns and tilts (the manual says; most cheap heads: 540° and 270°)")
                }
                TextField("Power (W)", value: $watts, format: .number, prompt: Text("optional"))
                    .help("From the label: how bright the show thinks it is")
                TextField("Beam angle (°)", value: $beamDeg, format: .number, prompt: Text("optional, typical for the type"))
                    .help("The manual's beam angle (not the field angle): the visualiser draws its beam this wide")
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            .frame(height: moving ? 296 : 262)

            Text("Closest layouts").font(.headline)
            List(catalogue?.templates ?? [], selection: Binding(get: { template }, set: { template = $0; autoPicked = false })) { t in
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(t.label)
                        Spacer()
                        if t.id != "blank", t.count != channels {
                            Text(t.count > channels ? "last \(t.count - channels) left off" : "\(channels - t.count) more as unknown")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Text(t.about).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
                .tag(t.id)
            }
            .frame(minHeight: 150)
            if let t = chosen, !t.channels.isEmpty {
                Text(preview(t)).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(problems, id: \.self) { Label($0, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Make Fixture") { Task { await make() } }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(template == nil || name.trimmingCharacters(in: .whitespaces).isEmpty || busy)
            }
        }
        .padding(22)
        .frame(width: 560, height: 740)
        .onAppear { manufacturer = brand }
        .task(id: "\(type)|\(channels)") { await loadTemplates() }
    }

    /// The channels it gets, as numbered on the fixture.
    private func preview(_ t: FixtureTemplates.Template) -> String {
        (0..<channels).map { i in "\(i + 1) \(i < t.channels.count ? t.channels[i] : "unknown")" }.joined(separator: " · ")
    }

    private func loadTemplates() async {
        guard await model.ensureSetupService(),
              let c = try? await model.api.fixtureTemplates(type: type, channels: channels) else { return }
        catalogue = c
        // the closest one, unless one was picked by hand
        if autoPicked || template == nil {
            template = c.templates.first?.id
        }
    }

    private func make() async {
        guard let template else { return }
        busy = true
        defer { busy = false }
        do {
            let r = try await model.api.newFixture(manufacturer: manufacturer, model: name, template: template,
                                                   channels: channels, type: type, watts: watts,
                                                   panDeg: panDeg, tiltDeg: tiltDeg, beamDeg: beamDeg)
            if let key = r.key, let mode = r.mode {
                made(key, mode)
                dismiss()
            } else {
                problems = r.problems ?? ["Couldn’t make it"]
            }
        } catch {
            problems = [error.localizedDescription]
        }
    }
}
