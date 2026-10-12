// Adding fixtures to the set: search a model (our library, QLC+, Open Fixture Library), choose its mode and how
// many. They get free DMX addresses. Where they hang is done on the Rigs page.
import DecisiveKit
import SwiftUI

struct AddToSetSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var onDone: () -> Void
    @State private var query = ""
    @State private var results: [CatalogEntry] = []
    @State private var chosen: CatalogEntry?
    @State private var key: String?
    @State private var definition: FixtureDefinition?
    @State private var mode = ""
    @State private var count = 4
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Add Fixtures to \(model.editingSet)").font(.title2.weight(.semibold))
            Text("Search by brand or model. They get free DMX addresses; where they hang is set on the Rigs page.")
                .foregroundStyle(.secondary)
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("e.g. sharpy, fuze, katana, pixbar, atomic, laserworld", text: $query)
                    .textFieldStyle(.plain)
                if busy { ProgressView().controlSize(.small) }
            }
            .padding(9)
            .background(.background.secondary, in: .rect(cornerRadius: 9))
            .task(id: query) {
                try? await Task.sleep(for: .milliseconds(300))
                guard query.count >= 2, await model.ensureSetupService() else { return }
                results = (try? await model.api.catalog(query, limit: 20)) ?? []
            }
            List(results, selection: Binding(get: { chosen?.key }, set: { k in chosen = results.first { $0.key == k } })) { e in
                HStack {
                    Image(systemName: icon(e)).frame(width: 22).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("\(e.manufacturer) \(e.model)")
                        Text([e.type, e.look, e.isLocal ? "in your library" : e.source?.uppercased()].compactMap { $0 }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .tag(e.key)
            }
            .frame(minHeight: 200)
            .onChange(of: chosen) { Task { await prepare() } }
            if let definition {
                Form {
                    Picker("DMX mode", selection: $mode) {
                        ForEach(definition.modes.keys.sorted { definition.channels($0) > definition.channels($1) }, id: \.self) { m in
                            Text("\(m) · \(definition.channels(m)) channels").tag(m)
                        }
                    }
                    Stepper("How many: \(count)", value: $count, in: 1...96)
                }
                .formStyle(.grouped)
                .scrollDisabled(true)
                .frame(height: 110)
            }
            if let note = definition?.addingNote {
                Text(note).font(.callout).foregroundStyle(definition?.warning == nil ? Color.secondary : Color.red)
            }
            if let error { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Add \(count) to the Set") { Task { await add() } }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(key == nil || mode.isEmpty || busy)
            }
        }
        .padding(22)
        .frame(width: 560, height: 560)
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

    private func prepare() async {
        guard let e = chosen else { return }
        busy = true
        defer { busy = false }
        do {
            let k = e.isLocal ? e.key : try await model.api.addToLibrary(e.key)  // QLC+/OFL → our library
            key = k
            definition = model.workspace?.definition(k)
            mode = definition?.defaultMode ?? ""
            count = definition?.isMoving == true ? 4 : 2
            error = definition == nil ? "Couldn’t read \(k)" : nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func add() async {
        guard let key, let definition, let ws = model.workspace else { return }
        busy = true
        defer { busy = false }
        let set = model.editingSet
        do {
            guard await model.ensureSetupService(), let data = ws.composed(rig: "", set: set),
                  var layout = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw SetupAPIError.notRunning }
            var fixtures = layout["fixtures"] as? [[String: Any]] ?? []
            // free addresses after what is patched, universe by universe
            let footprint = max(1, definition.channels(mode))
            var used: [Int: [ClosedRange<Int>]] = [:]
            for f in fixtures {
                let n = (f["fixture"] as? String).flatMap { ws.definition($0)?.channels(f["mode"] as? String ?? "") } ?? 1
                let a = f["address"] as? Int ?? 1
                used[f["universe"] as? Int ?? 1, default: []].append(a...(a + max(1, n) - 1))
            }
            let base = key.split(separator: "/").last.map { String($0.prefix { $0.isLetter }) }.flatMap { $0.isEmpty ? nil : $0 } ?? "fx"
            var ids = Set(fixtures.compactMap { $0["id"] as? String })
            for _ in 0..<count {
                var u = 1, a = 1
                while a + footprint - 1 > 512 || (used[u] ?? []).contains(where: { $0.overlaps(a...(a + footprint - 1)) }) {
                    a += 1
                    if a + footprint - 1 > 512 { a = 1; u += 1 }
                }
                used[u, default: []].append(a...(a + footprint - 1))
                var n = 1
                while ids.contains("\(base)\(n)") { n += 1 }
                ids.insert("\(base)\(n)")
                fixtures.append(["id": "\(base)\(n)", "fixture": key, "mode": mode, "universe": u, "address": a])
            }
            layout["fixtures"] = fixtures
            try await model.api.saveSet(layout, set: set)
            model.reloadSets()
            onDone()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
