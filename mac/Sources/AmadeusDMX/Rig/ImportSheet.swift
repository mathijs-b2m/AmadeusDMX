// Import from a venue's documents: an MVR file, patch sheets, or PDFs (patch lists, riders, light plots) read with
// AI become a set and a rig of the same name, the light plots lying under the rig as drawings. The engine reads
// them (amadeus/rig/importer/, POST /api/import, a job); this sheet picks the files, follows the job, and shows
// what it found, what to check and what is missing.
import AmadeusKit
import SwiftUI
import UniformTypeIdentifiers

struct ImportSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openSettings) private var openSettings
    @State private var files: [URL] = []
    @State private var name = ""
    @State private var typedName = false   // the name was typed: picking files leaves it alone
    @State private var hasKey = false
    @State private var phase = Phase.pick
    @State private var replacing: String?
    @State private var error: String?
    @State private var job: String?        // the running import, to cancel it

    enum Phase {
        case pick
        case running(String)      // the job's step
        case done(ImportJob)
        case failed(ImportJob?, String)
    }

    static let extensions = ["pdf", "mvr", "csv", "tsv", "txt", "xlsx", "xlsm"]

    private var hasPDF: Bool { files.contains { $0.pathExtension.lowercased() == "pdf" } }
    private var safeName: String { Self.safe(name) }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            switch phase {
            case .pick: pick
            case .running(let step): running(step)
            case .done(let job): report(job)
            case .failed(let job, let text): failed(job, text)
            }
        }
        .padding(22)
        .frame(width: 600)
        .onAppear { hasKey = KeySource.current(model.workspace) != .none }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            hasKey = KeySource.current(model.workspace) != .none   // back from Settings with a key
        }
        .confirmationDialog("Replace the set and rig “\(replacing ?? "")”?",
                            isPresented: Binding(get: { replacing != nil }, set: { if !$0 { replacing = nil } }),
                            titleVisibility: .visible) {
            Button("Replace", role: .destructive) { replacing = nil; start(replace: true) }
            Button("Cancel", role: .cancel) { replacing = nil }
        } message: {
            Text("A set or rig of that name exists already. Its fixtures, trusses and drawings are replaced by what is read from these files.")
        }
    }

    // MARK: - the files and the name

    private var pick: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Import from Documents").font(.title2.weight(.semibold))
                Text("A venue's documents become a set (the fixtures and their patch) and a rig (the trusses they hang on) of the same name; light plots lie under the rig as drawings.")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: 6) {
                List {
                    if files.isEmpty {
                        Text("No files yet: an MVR file, patch sheets (CSV, Excel), or PDFs").foregroundStyle(.secondary)
                    }
                    ForEach(files, id: \.self) { url in
                        HStack {
                            Image(systemName: url.pathExtension.lowercased() == "pdf" ? "doc.richtext" : "doc.text")
                                .foregroundStyle(.secondary)
                            Text(url.lastPathComponent).lineLimit(1).truncationMode(.middle)
                            Spacer()
                            Button("Remove", systemImage: "minus.circle") { files.removeAll { $0 == url } }
                                .labelStyle(.iconOnly).buttonStyle(.borderless)
                                .help("Leave this file out")
                        }
                    }
                }
                .frame(height: 150)
                .listStyle(.bordered(alternatesRowBackgrounds: true))
                Button("Add Files…", systemImage: "plus") { choose() }
                    .help("Pick the documents: several at once (.pdf .mvr .csv .tsv .txt .xlsx .xlsm)")
            }
            Form {
                TextField("Name", text: Binding(get: { name }, set: { name = $0; typedName = true }))
                    .help("The set and the rig get this name")
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            .frame(height: 70)
            VStack(alignment: .leading, spacing: 8) {
                Label("MVR files and patch sheets are read here. PDFs (patch lists, riders, light plots) are read with AI using your own OpenAI API key; every page is sent to OpenAI.",
                      systemImage: "info.circle")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                if hasPDF && !hasKey {
                    HStack {
                        Label("There is no OpenAI API key in the app: PDFs can't be read without one.", systemImage: "key")
                            .font(.callout).foregroundStyle(.orange)
                        Spacer()
                        Button("Open Settings…") { model.settingsTab = "director"; openSettings() }
                            .help("Settings ▸ Director: enter your OpenAI API key (the same key the AI director uses)")
                    }
                }
            }
            HStack {
                if let error { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout) }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Import") { start(replace: false) }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(files.isEmpty || safeName.isEmpty || (hasPDF && !hasKey))
            }
        }
    }

    private func choose() {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = true
        p.canChooseDirectories = false
        p.allowedContentTypes = Self.extensions.compactMap { UTType(filenameExtension: $0) }
        p.message = "Choose a venue's documents: an MVR file, patch sheets, PDFs (patch lists, riders, light plots)"
        p.prompt = "Add"
        guard p.runModal() == .OK else { return }
        for url in p.urls where !files.contains(url) { files.append(url) }
        if !typedName || name.isEmpty, let first = files.first {
            name = Self.safe(first.deletingPathExtension().lastPathComponent)
            typedName = false
        }
    }

    /// A name the engine takes as it is: lower case, letters, digits, - and _.
    static func safe(_ s: String) -> String {
        s.lowercased().replacingOccurrences(of: #"[^a-z0-9_-]+"#, with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    }

    // MARK: - the job

    private func start(replace: Bool) {
        error = nil
        let rigName = safeName
        let picked = files
        phase = .running("Sending the files…")
        Task {
            do {
                guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
                let payload = try picked.map { (name: $0.lastPathComponent, data: try Data(contentsOf: $0)) }
                let job = try await model.api.startImport(name: rigName, files: payload, replace: replace)
                self.job = job
                await follow(job)
            } catch SetupAPIError.nameTaken {
                phase = .pick
                replacing = rigName
            } catch {
                phase = .pick
                self.error = error.localizedDescription
            }
        }
    }

    /// Once a second until it is done. Closing the sheet leaves it running: the rig appears in the list when done.
    private func follow(_ job: String) async {
        while true {
            try? await Task.sleep(for: .seconds(1))
            guard let s = try? await model.api.importStatus(job) else { continue }
            switch s.state {
            case "done":
                model.reloadSets()
                phase = .done(s)
                return
            case "failed":
                phase = .failed(s, s.error ?? "The import failed.")
                return
            case "cancelled":
                phase = .pick
                error = "The import was cancelled: nothing was saved."
                return
            default:
                phase = .running(s.step ?? "Reading the files…")
            }
        }
    }

    private func running(_ step: String) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Importing “\(safeName)”").font(.title2.weight(.semibold))
            HStack(spacing: 12) {
                ProgressView().controlSize(.small)
                Text(step).foregroundStyle(.secondary)
            }
            Text(hasPDF ? "Reading PDFs with AI takes up to a few minutes. You can close this and carry on: the import goes on, and the rig shows up in the list when it's done."
                 : "You can close this and carry on: the import goes on, and the rig shows up in the list when it's done.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Cancel Import", role: .destructive) {
                    guard let job else { return }
                    phase = .running("Cancelling…")
                    Task { _ = try? await model.api.cancelImport(job) }
                }
                .disabled(job == nil || step == "Cancelling…")
                .help("Stop the import: nothing is saved (what was already read with AI is remembered, so trying again costs less)")
                Spacer()
                Button("Close") { dismiss() }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .help("Close this and carry on: the import goes on, and the rig shows up in the list when it's done")
            }
        }
    }

    // MARK: - the report

    private func report(_ job: ImportJob) -> some View {
        let done = job.name ?? safeName
        var counts = ["\(job.fixtures ?? 0) fixtures", "\(job.trusses ?? 0) trusses"]
        if let u = job.underlays, u > 0 { counts.append("\(u) drawing\(u == 1 ? "" : "s")") }
        return VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Imported “\(done)”").font(.title2.weight(.semibold))
                Text(counts.joined(separator: " · ") + ". Look over what is marked before the show: a line with fixtures selects them in the rig editor.")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            notes(job.notes, rig: done)
            HStack {
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Open in Rig Editor") { open(done) }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private func failed(_ job: ImportJob?, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Couldn’t Import “\(safeName)”").font(.title2.weight(.semibold))
                Label(text, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let job, !job.notes.isEmpty { notes(job.notes, rig: nil) }
            HStack {
                Spacer()
                Button("Back") { phase = .pick }
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)
            }
        }
    }

    /// The missing first, then what to check, then what was found.
    private func notes(_ notes: [ImportJob.Note], rig: String?) -> some View {
        let order = ["missing", "check", "ok"]
        let sorted = notes.enumerated().sorted { l, r in
            let a = order.firstIndex(of: l.element.level) ?? 3, b = order.firstIndex(of: r.element.level) ?? 3
            return a != b ? a < b : l.offset < r.offset
        }.map(\.element)
        return List(Array(sorted.enumerated()), id: \.offset) { _, n in
            let ids = n.ids ?? []
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: n.level == "missing" ? "xmark.circle.fill" : n.level == "check" ? "questionmark.circle.fill" : "checkmark.circle.fill")
                    .foregroundStyle(n.level == "missing" ? .red : n.level == "check" ? .orange : .green)
                Text(n.text).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                if let rig, !ids.isEmpty {
                    Button("Select", systemImage: "scope") { open(rig, selecting: ids) }
                        .labelStyle(.iconOnly).buttonStyle(.borderless)
                        .help("Open the rig with \(ids.count == 1 ? ids[0] : "these \(ids.count) fixtures") selected")
                }
            }
            .contentShape(.rect)
            .onTapGesture { if let rig, !ids.isEmpty { open(rig, selecting: ids) } }
        }
        .frame(minHeight: 160, idealHeight: 300, maxHeight: 360)
        .listStyle(.bordered(alternatesRowBackgrounds: true))
    }

    /// The Rigs page on the new rig, with the new set showing (and the fixtures of a report line selected).
    private func open(_ rig: String, selecting ids: [String]? = nil) {
        model.reloadSets()
        model.pendingRigSelection = ids
        model.section = .rig
        model.editingRig = rig
        model.editingRigSet = model.setsOn(rig).contains(rig) ? rig : model.rigSetDefault(rig)
        dismiss()
    }
}
