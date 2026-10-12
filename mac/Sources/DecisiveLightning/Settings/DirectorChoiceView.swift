// Which director decides the show: the rules, OpenAI, or a local decision model in Ollama (which one, and
// where Ollama runs). The choice belongs to the selected set on its rig, like the toolbar's director menu.
import DecisiveKit
import SwiftUI

enum DirectorKind: String, CaseIterable, Identifiable {
    case rules, openai, local
    var id: String { rawValue }
    var title: String { ["rules": "Rules", "openai": "OpenAI", "local": "Local model"][rawValue]! }

    init(_ value: String) {
        self = value.hasPrefix("ollama") ? .local : value == "openai" ? .openai : .rules
    }
}

struct DirectorChoiceSection: View {
    @Environment(AppModel.self) private var model
    @State private var options: [DirectorOption] = []
    @State private var current = "rules"
    @State private var loading = false
    @State private var problem: String?
    @State private var host = UserDefaults.standard.string(forKey: "ollamaHost") ?? ""

    private var local: [DirectorOption] { options.filter { $0.value.hasPrefix("ollama:") } }
    private var option: DirectorOption? { options.first { $0.value == current } }
    private var kind: DirectorKind { DirectorKind(current) }

    var body: some View {
        SwiftUI.Section {
            Picker("Director", selection: Binding(get: { kind }, set: { pick($0) })) {
                ForEach(DirectorKind.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .disabled(model.selectedSet.isEmpty || loading)

            if kind == .local {
                Picker("Model", selection: Binding(get: { current }, set: { choose($0) })) {
                    ForEach(local) { o in
                        Text(o.value.dropFirst(7)).tag(o.value).selectionDisabled(!o.available)
                    }
                }
                LabeledContent("Ollama address") {
                    TextField("Ollama address", text: $host, prompt: Text("localhost:11434"))
                        .labelsHidden().multilineTextAlignment(.trailing).frame(maxWidth: 220)
                        .onSubmit { Task { await saveHost() } }
                }
            }
            HStack(alignment: .firstTextBaseline) {
                if let problem {
                    Label(problem, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                } else if let o = option {
                    Label(o.note ?? o.label, systemImage: o.available ? "checkmark.circle" : "exclamationmark.triangle")
                        .foregroundStyle(o.available ? Color.secondary : Color.orange)
                }
                Spacer()
                Button(loading ? "Refreshing…" : "Refresh") { Task { await load() } }.disabled(loading)
            }
            .font(.callout)
            if kind == .local, local.contains(where: { !$0.available && $0.note?.hasPrefix("no decision") == true }) {
                Text("Models without decision support are listed but can't be chosen: the director needs one that gives probabilities per option (ollama pull nimble).")
                    .font(.callout).foregroundStyle(.secondary)
            }
        } header: {
            Text("Who decides the show")
        } footer: {
            Text(model.selectedSet.isEmpty ? "Choose a set first."
                 : "For the set \(model.selectedSet) on the rig \(model.selectedRig), like the director menu in the toolbar. A running show switches at once; tracks already decided keep their plan until they are decided again. Rules: instant, offline. OpenAI: needs the key below, ~1 s per phrase. Local: free and offline in Ollama, slower (~7 s per phrase on a laptop).")
        }
        .task(id: "\(model.selectedRig)|\(model.selectedSet)") { await load() }
    }

    private func load() async {
        guard !model.selectedSet.isEmpty else { return }
        loading = true
        defer { loading = false }
        guard await model.ensureSetupService() else { problem = "The engine's setup service doesn't start."; return }
        options = (try? await model.api.directors()) ?? []
        let raw = try? await model.api.rig(rig: model.selectedRig, set: model.selectedSet)
        current = raw?["director"] as? String ?? "rules"
        if current == "ollama" { current = "ollama:nimble" }
        problem = nil
    }

    private func pick(_ k: DirectorKind) {
        switch k {
        case .rules: choose("rules")
        case .openai: choose("openai")
        case .local:
            if let o = local.first(where: \.available) { choose(o.value) }
            else { current = local.first?.value ?? "ollama:nimble"; problem = local.first?.note ?? "No local decision model found." }
        }
    }

    private func choose(_ value: String) {
        guard value != current || problem != nil else { return }
        if let o = options.first(where: { $0.value == value }), !o.available {
            problem = o.note ?? "Not available right now."
            return
        }
        let before = current
        current = value
        Task {
            do {
                try await model.api.setDirector(value, rig: model.selectedRig, set: model.selectedSet)
                problem = nil
            } catch {
                current = before
                problem = "Couldn't switch: \(error.localizedDescription)"
            }
        }
    }

    private func saveHost() async {
        let h = host.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(h, forKey: "ollamaHost")
        await model.restartSetupService()  // it lists the models of the Ollama at that address
        await load()
    }
}
