// Adding fixtures to the set: search a model (our library, QLC+, Open Fixture Library, DMXControl DDF), choose its mode and how
// many. No start addresses: you give each the one set on the fixture (in the inspector). Where they hang is done
// on the Rigs page. A fixture in no library is made here: from its manual (a PDF or a pasted screenshot of its DMX
// chart, read with AI), its GDTF file, or a common layout.
import AmadeusKit
import AppKit
import SwiftUI
import UniformTypeIdentifiers

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
    @State private var showNew = false
    @State private var madeKey: String?   // a fixture just made from a template, a GDTF file or a manual
    @State private var madeFrom = ""      // what it was made from, for the note
    @State private var hasKey = false     // an OpenAI key in the app: manuals can be read
    @State private var reading: Task<Void, Never>?   // a manual is being read with AI
    @State private var pasteKey: Any?     // ⌘V with a picture on the clipboard: it is read as the manual

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Add Fixtures to \(model.editingSet)").font(.title2.weight(.semibold))
            Text("Search by brand or model. Then give each its start address (the one set on the fixture) on the right; where they hang is set on the Rigs page.")
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
                        Text([e.type, e.look, e.isLocal ? "in your library" : e.source?.uppercased()].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .tag(e.key)
            }
            .frame(minHeight: 200)
            .onChange(of: chosen) { Task { await prepare() } }
            Text(reading != nil ? "Reading the manual with AI: this takes up to a few minutes."
                 : madeKey == nil ? "Not in any library? Make it from its manual: a PDF, or a screenshot of its DMX chart (paste it with ⌘V). Or import the maker's GDTF file, or start from a common layout."
                 : "Made for you\(madeFrom): once added, give it its start address and check its channels on the fixture once.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Menu {
                    Button("Choose a PDF or Picture…") { chooseManual() }
                    Button("Paste from Clipboard") { pasteManual() }
                } label: {
                    Label("From Manual", systemImage: "doc.text.magnifyingglass")
                }
                .menuStyle(.button).fixedSize()
                .disabled(!hasKey || reading != nil)
                .help(hasKey ? "Read the fixture's manual with AI and make the fixture from its DMX chart: a PDF, or a picture of the chart (copy a screenshot and paste it here with ⌘V). It is sent to OpenAI with your own key."
                      : "Reading a manual needs your own OpenAI API key (Settings › Director)")
                if reading != nil {
                    Button("Stop") { reading?.cancel(); reading = nil }
                }
                Spacer()
                Button("Import GDTF…", systemImage: "square.and.arrow.down") { Task { await importGDTF() } }
                    .help("Convert a .gdtf file from the maker's site or your own GDTF Share account into your fixtures")
                    .disabled(reading != nil)
                Button("New Fixture…", systemImage: "plus") { showNew = true }
                    .help("Make it from a common channel layout, then check it channel by channel on the real fixture")
                    .disabled(reading != nil)
            }
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
                Button(key == nil ? "Add to the Set" : "Add \(count) to the Set") { Task { await add() } }  // a number once one is chosen
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(key == nil || mode.isEmpty || busy)
            }
        }
        .padding(22)
        .frame(width: 580, height: 640)
        .onAppear {
            hasKey = KeySource.current(model.workspace) != .none
            watchPaste()
        }
        .onDisappear {
            reading?.cancel()
            if let pasteKey { NSEvent.removeMonitor(pasteKey) }
            pasteKey = nil
        }
        .sheet(isPresented: $showNew) {
            NewFixtureSheet(brand: query.count >= 2 && results.isEmpty ? query : "") { k, m in use(k, mode: m, from: "") }
                .environment(model)
        }
    }

    /// A fixture just made (from a template, a GDTF file or a manual): chosen, in its mode.
    private func use(_ k: String, mode m: String, from: String) {
        chosen = nil
        key = k
        madeKey = k
        madeFrom = from
        definition = model.workspace?.definition(k)
        mode = m
        count = 2
        error = definition == nil ? "Couldn’t read \(k)" : nil
    }

    /// A .gdtf file you have, converted on this Mac into your fixtures, then chosen like a search result.
    private func importGDTF() async {
        let p = NSOpenPanel()
        p.canChooseDirectories = false
        p.allowedContentTypes = [UTType(filenameExtension: "gdtf") ?? .zip]
        p.message = "Choose a GDTF file: from the fixture maker's website or your own GDTF Share account"
        p.prompt = "Import"
        guard p.runModal() == .OK, let url = p.url else { return }
        busy = true
        defer { busy = false }
        do {
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            let r = try await model.api.importGDTF(name: url.lastPathComponent, data: try Data(contentsOf: url))
            guard let k = r.key, let m = r.mode else { throw SetupAPIError.server("Couldn’t import \(url.lastPathComponent)") }
            use(k, mode: m, from: "")
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: the manual

    private func chooseManual() {
        let p = NSOpenPanel()
        p.canChooseDirectories = false
        p.allowedContentTypes = [.pdf, .image]
        p.message = "Choose the fixture's manual (a PDF) or a picture of its DMX chart. It is sent to OpenAI with your own key."
        p.prompt = "Read"
        guard p.runModal() == .OK, let url = p.url else { return }
        guard let file = ManualFile(url: url) else { error = "Couldn’t read \(url.lastPathComponent)"; return }
        read(file)
    }

    private func pasteManual() {
        guard let file = ManualFile.pasted() else {
            error = "There is no picture or PDF on the clipboard. Copy a screenshot of the DMX chart first."
            return
        }
        read(file)
    }

    /// ⌘V with a picture or PDF (and no text) on the clipboard reads it as the manual, even in the search field.
    private func watchPaste() {
        guard pasteKey == nil else { return }
        pasteKey = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            guard event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command,
                  event.charactersIgnoringModifiers == "v", hasKey, reading == nil, !showNew,
                  NSPasteboard.general.string(forType: .string) == nil, ManualFile.pasted() != nil else { return event }
            pasteManual()
            return nil
        }
    }

    /// The manual read with AI into a new fixture in your library (its largest mode), then chosen like a search result.
    private func read(_ file: ManualFile) {
        error = nil
        reading = Task {
            defer { reading = nil }
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                let r = try await model.api.fixtureFromManual(name: file.name, data: file.data)
                guard !Task.isCancelled else { return }
                guard let k = r.key, let m = r.mode else {
                    throw SetupAPIError.server(r.problems?.joined(separator: " ") ?? "Couldn’t make a fixture from \(file.name)")
                }
                use(k, mode: m, from: " from \(file.name)")
            } catch {
                if !Task.isCancelled { self.error = error.localizedDescription }
            }
        }
    }

    private func icon(_ e: CatalogEntry) -> String {
        switch e.type ?? "" {
        case "moving head": "light.overhead.right"
        case "laser": "rays"
        case "par": "light.recessed"
        case "blinder": "light.panel"
        case "smoke": "cloud.fog"
        default: "lightbulb"
        }
    }

    private func prepare() async {
        guard let e = chosen else { return }
        madeKey = nil
        busy = true
        defer { busy = false }
        do {
            let k = e.isLocal ? e.key : try await model.api.addToLibrary(e.key)  // QLC+/OFL/DDF → our library
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
            let base = key.split(separator: "/").last.map { String($0.prefix { $0.isLetter }) }.flatMap { $0.isEmpty ? nil : $0 } ?? "fx"
            var ids = Set(fixtures.compactMap { $0["id"] as? String })
            for _ in 0..<count {  // no start address: a guess is usually wrong, and then they overlap
                var n = 1
                while ids.contains("\(base)\(n)") { n += 1 }
                ids.insert("\(base)\(n)")
                fixtures.append(["id": "\(base)\(n)", "fixture": key, "mode": mode, "universe": 1])
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
