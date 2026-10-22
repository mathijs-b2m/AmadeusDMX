// Adding fixtures in the editor: pick a model and how many.
import AmadeusKit
import SwiftUI

struct AddFixturesView: View {
    @Environment(AppModel.self) private var model
    let editor: RigEditorModel
    @Binding var isPresented: Bool
    @State private var query = ""
    @State private var results: [CatalogEntry] = []
    @State private var chosen: CatalogEntry?
    @State private var key: String?
    @State private var modes: [String] = []
    @State private var mode = ""
    @State private var count = 4
    @State private var busy = false
    @State private var error: String?
    @State private var note: String?
    @State private var warns = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Add Fixtures").font(.headline)
            Text(isOnTruss ? "They’re spread along the selected truss." : "They’re placed on the stage floor; drag them onto a truss.")
                .font(.caption).foregroundStyle(.secondary)
            TextField("Search: sharpy, katana, pixbar, atomic…", text: $query)
                .textFieldStyle(.roundedBorder)
                .task(id: query) {
                    try? await Task.sleep(for: .milliseconds(300))
                    guard query.count >= 2, await model.ensureSetupService() else { return }
                    results = (try? await model.api.catalog(query, limit: 12)) ?? []
                }
            List(results, selection: Binding(get: { chosen?.key }, set: { k in chosen = results.first { $0.key == k } })) { e in
                VStack(alignment: .leading) {
                    Text("\(e.manufacturer) \(e.model)")
                    Text([e.type, e.isLocal ? "in your library" : e.source?.uppercased()].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .frame(height: 200)
            .onChange(of: chosen) { Task { await prepare() } }
            if !modes.isEmpty {
                Picker("Mode", selection: $mode) { ForEach(modes, id: \.self) { Text($0).tag($0) } }
                Stepper("Count: \(count)", value: $count, in: 1...48)
            }
            if let note { Text(note).font(.caption).foregroundStyle(warns ? Color.red : Color.secondary) }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            HStack {
                if busy { ProgressView().controlSize(.small) }
                Spacer()
                Button("Cancel") { isPresented = false }
                Button("Add") {
                    if let key { editor.addFixtures(key: key, mode: mode, count: count) }
                    isPresented = false
                }
                .buttonStyle(.borderedProminent)
                .disabled(key == nil || mode.isEmpty)
            }
        }
        .padding(16)
        .frame(width: 380)
    }

    private var isOnTruss: Bool { if case .truss = editor.selection { true } else { false } }

    private func prepare() async {
        guard let e = chosen else { return }
        busy = true
        defer { busy = false }
        do {
            let k = e.isLocal ? e.key : try await model.api.addToLibrary(e.key)  // QLC+/OFL/DDF → our library
            key = k
            guard let def = editor.definition(k) else { error = "Couldn’t read \(k)"; return }
            note = def.addingNote
            warns = def.warning != nil
            modes = def.modes.keys.sorted { def.channels($0) > def.channels($1) }
            mode = def.defaultMode
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
