// The OpenAI key for the AI director: which key the engine uses, and entering, checking or removing your own.
// Settings ▸ Director and the wizard's engine step share it. The key goes into the Keychain only.
import AmadeusKit
import SwiftUI

/// Where the engine's key comes from: the app's (Keychain) wins over the engine folder's .env.
enum KeySource: Equatable {
    case keychain(String), envFile, none

    static func current(_ ws: Workspace?) -> KeySource {
        if let k = Keychain.openAIKey, !k.isEmpty { return .keychain(k) }
        return ws?.hasEnvKey == true ? .envFile : .none
    }
}

/// "sk-proj-…a1B2": enough to recognise a key, not enough to use it.
func maskedKey(_ k: String) -> String {
    k.count > 12 ? "\(k.prefix(k.hasPrefix("sk-proj-") ? 8 : 3))…\(k.suffix(4))" : "…"
}

struct OpenAIKeyView: View {
    @Environment(AppModel.self) private var model
    @State private var entry = ""
    @State private var source = KeySource.none
    @State private var check: (ok: Bool, text: String)?
    @State private var checking = false
    @State private var note: String?

    private var trimmed: String { entry.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            inUse
            SecureField("OpenAI API key", text: $entry, prompt: Text("Paste your key: sk-…"))
                .labelsHidden()
                .textFieldStyle(.roundedBorder)
                .onSubmit(save)
                .onChange(of: entry) { check = nil; note = nil }
            if !trimmed.isEmpty && !trimmed.hasPrefix("sk-") {
                Label("OpenAI keys start with sk-", systemImage: "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.orange)
            }
            HStack(spacing: 8) {
                Button("Save", action: save).keyboardShortcut(.defaultAction).disabled(!trimmed.hasPrefix("sk-"))
                Button(checking ? "Checking…" : "Check Key", action: { Task { await verify() } })
                    .disabled(checking || (trimmed.isEmpty && source == .none))
                if case .keychain = source { Button("Remove", role: .destructive, action: remove) }
                Spacer()
                Link("Get a key", destination: URL(string: "https://platform.openai.com/api-keys")!).font(.callout)
            }
            if let check {
                Label(check.text, systemImage: check.ok ? "checkmark.circle.fill" : "xmark.octagon.fill")
                    .font(.callout).foregroundStyle(check.ok ? .green : .red)
            }
            if let note { Text(note).font(.callout).foregroundStyle(.secondary) }
        }
        .onAppear { source = .current(model.workspace) }
    }

    @ViewBuilder private var inUse: some View {
        switch source {
        case .keychain(let k):
            Label("In use: your key \(maskedKey(k)), from the Keychain", systemImage: "key.fill")
        case .envFile:
            Label("In use: the key in the engine folder's .env. A key saved here is used instead.", systemImage: "doc.text")
        case .none:
            Label("No key: the rule-based director lights the show. Add a key to let the AI decide.", systemImage: "key")
                .foregroundStyle(.secondary)
        }
    }

    private func save() {
        guard trimmed.hasPrefix("sk-") else { return }
        Keychain.openAIKey = trimmed
        entry = ""
        changed("Saved.")
        Task { await verify(Keychain.openAIKey) }
    }

    private func remove() {
        Keychain.openAIKey = nil
        changed(model.workspace?.hasEnvKey == true ? "Removed. The engine folder's .env key is used again." : "Removed.")
    }

    private func changed(_ text: String) {
        source = .current(model.workspace)
        check = nil
        Task { await model.restartSetupService() }  // the setup page shows which directors can run: the new key
        note = text + (model.engineRunning ? " The running show keeps the old key until it is started again." : "")
    }

    /// Asks OpenAI whether it accepts the key (the one typed, else the one in use): lists the models, nothing more.
    private func verify(_ given: String? = nil) async {
        let key: String? = given ?? (trimmed.isEmpty ? keyInUse() : trimmed)
        guard let key else { check = (false, "The .env key is checked when the engine uses it."); return }
        checking = true
        defer { checking = false }
        var req = URLRequest(url: URL(string: "https://api.openai.com/v1/models")!, timeoutInterval: 10)
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            switch (resp as? HTTPURLResponse)?.statusCode ?? 0 {
            case 200: check = (true, "OpenAI accepts this key.")
            case 401: check = (false, "OpenAI doesn't accept this key (wrong, revoked, or from another account).")
            case 429: check = (true, "The key works, but its quota or rate limit is reached for now.")
            case let code: check = (false, "OpenAI answered \(code). Try again later.")
            }
        } catch {
            check = (false, "Couldn't reach OpenAI: \(error.localizedDescription)")
        }
    }

    private func keyInUse() -> String? {
        if case .keychain(let k) = source { return k }
        return nil
    }
}
