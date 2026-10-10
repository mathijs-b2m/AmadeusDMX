// Wizard: the fixtures, from the library or found on the network.
import DecisiveKit
import SwiftUI

struct FixturesStep: View {
    @Environment(AppModel.self) private var model
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StepHeader(symbol: "light.overhead.right.fill", title: "Your Fixtures",
                       text: "Search our library, QLC+ and the Open Fixture Library by brand or model.")
            if w.venue == .stage {
                Picker("", selection: $w.quickRig) {
                    Text("Concert rig from one model").tag(true)
                    Text("My own list").tag(false)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("e.g. beamz fuze, mac encore, laserworld", text: $w.query)
                    .textFieldStyle(.plain)
                    .onSubmit { Task { await w.search(model.api) } }
                if w.searching { ProgressView().controlSize(.small) }
            }
            .padding(9)
            .background(.background.secondary, in: .rect(cornerRadius: 9))
            .task(id: w.query) {
                try? await Task.sleep(for: .milliseconds(350))
                await w.search(model.api)
            }
            if !w.results.isEmpty {
                VStack(spacing: 0) {
                    ForEach(w.results.prefix(6)) { e in
                        HStack {
                            Image(systemName: icon(e)).frame(width: 22).foregroundStyle(.secondary)
                            VStack(alignment: .leading, spacing: 1) {
                                Text("\(e.manufacturer) \(e.model)")
                                Text([e.type, e.look, e.isLocal ? "in your library" : e.source?.uppercased()].compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button(w.quickRig ? "Use" : "Add") {
                                if w.quickRig { w.quickEntry = e } else { Task { await w.add(e, model.api) } }
                                w.query = ""; w.results = []
                            }
                        }
                        .padding(.vertical, 6).padding(.horizontal, 8)
                        Divider()
                    }
                }
                .background(.background.secondary, in: .rect(cornerRadius: 9))
            }
            if w.quickRig {
                GroupBox {
                    VStack(alignment: .leading, spacing: 10) {
                        LabeledContent("Moving heads") {
                            Text(w.quickEntry.map { "\($0.manufacturer) \($0.model)" } ?? "Search and choose a model above")
                                .foregroundStyle(w.quickEntry == nil ? .secondary : .primary)
                        }
                        Stepper("Count: \(w.quickCount)", value: $w.quickCount, in: 4...120, step: 2)
                        Stepper("Lasers (Laserworld CS-1000RGB): \(w.quickLasers)", value: $w.quickLasers, in: 0...16)
                        Text("Spread over two overhead trusses, a row at the back, the front edge and two towers.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(6)
                }
            } else if !w.planned.isEmpty {
                VStack(spacing: 8) {
                    ForEach($w.planned) { $p in
                        HStack(spacing: 10) {
                            Image(systemName: icon(p.entry)).frame(width: 22).foregroundStyle(.tint)
                            Text("\(p.entry.manufacturer) \(p.entry.model)").lineLimit(1)
                            Spacer()
                            if p.modes.count > 1 {
                                Picker("", selection: $p.mode) { ForEach(p.modes, id: \.self) { Text($0).tag($0) } }
                                    .labelsHidden().frame(width: 90)
                            }
                            Picker("", selection: $p.mount) {
                                Text("Hung").tag("hang"); Text("Stand").tag("stand"); Text("Floor").tag("floor")
                            }
                            .labelsHidden().frame(width: 80)
                            Stepper("\(p.count)×", value: $p.count, in: 1...64).monospacedDigit()
                            Button { w.planned.removeAll { $0.id == p.id } } label: { Image(systemName: "minus.circle.fill") }
                                .buttonStyle(.borderless).foregroundStyle(.secondary)
                        }
                        .padding(10)
                        .background(.background.secondary, in: .rect(cornerRadius: 10))
                    }
                }
            } else if w.results.isEmpty {
                Text("No fixtures yet.").foregroundStyle(.secondary)
            }
        }
    }

    private func icon(_ e: CatalogEntry) -> String {
        switch e.type ?? "" {
        case "moving head": "light.overhead.right"
        case "laser": "rays"
        case "par": "light.recessed"
        case "blinder": "light.panel"
        default: "lightbulb"
        }
    }
}
