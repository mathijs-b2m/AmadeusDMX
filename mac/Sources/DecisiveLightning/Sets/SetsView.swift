// The sets (rigs side by side): a card each. A show runs with one set; it can't change while running.
import DecisiveKit
import SwiftUI

struct SetsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow
    @State private var confirmDelete: SetSummary?
    @State private var error: String?

    private let columns = [GridItem(.adaptive(minimum: 280, maximum: 380), spacing: 16)]

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 16) {
                ForEach(model.sets) { set in
                    SetCard(set: set, selected: set.name == model.selectedSet)
                        .onTapGesture { if !model.engineRunning { model.selectedSet = set.name } }
                        .onTapGesture(count: 2) {
                            if !model.engineRunning { model.selectedSet = set.name; model.section = .show }
                        }
                        .contextMenu {
                            Button("Edit Layout…", systemImage: "square.split.bottomrightquarter") { model.editLayout(set.name) }
                                .disabled(model.engineRunning && set.name != model.selectedSet)
                            Button("Show the Patch", systemImage: "tablecells") {
                                model.selectedSet = set.name; model.rigMode = "patch"; model.section = .rig
                            }
                            .disabled(model.engineRunning && set.name != model.selectedSet)
                            Button("Make Default", systemImage: "star") { run { try await model.api.makeDefault(set.name) } }
                                .disabled(set.isDefault)
                            Button("Duplicate", systemImage: "plus.square.on.square") {
                                run { try await model.api.createSet(name: uniqueName(set.name + "-copy"), copyOf: set.name) }
                            }
                            Divider()
                            Button("Show in Finder", systemImage: "folder") {
                                if let url = model.workspace?.setURL(set.name) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                            }
                            Divider()
                            Button("Delete…", systemImage: "trash", role: .destructive) { confirmDelete = set }
                                .disabled(model.sets.count <= 1 || (model.engineRunning && set.name == model.selectedSet))
                        }
                }
                NewSetCard { openWindow(id: "wizard") }
            }
            .padding(20)
        }
        .toolbar {
            ToolbarItem {
                Button("New Set", systemImage: "plus") { openWindow(id: "wizard") }
            }
        }
        .onAppear { model.reloadSets() }
        .confirmationDialog("Delete the set “\(confirmDelete?.name ?? "")”?", isPresented: Binding(
            get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } }), titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                if let s = confirmDelete { run { try await model.api.deleteSet(s.name) } }
            }
        } message: {
            Text("Its fixture list and patch are removed. Other sets are not affected.")
        }
        .alert("Couldn’t Change the Sets", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
        } message: { Text(error ?? "") }
    }

    private func uniqueName(_ base: String) -> String {
        var n = base, i = 2
        while model.sets.contains(where: { $0.name == n }) { n = "\(base)\(i)"; i += 1 }
        return n
    }

    private func run(_ op: @escaping () async throws -> Void) {
        Task {
            guard await model.ensureSetupService() else { error = "The engine's setup service did not start."; return }
            do { try await op() } catch { self.error = error.localizedDescription }
            model.reloadSets()
        }
    }
}

struct SetCard: View {
    var set: SetSummary
    var selected: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: set.hasScreen ? "tv.and.mediabox" : "light.overhead.right")
                    .font(.title2).foregroundStyle(.tint).symbolRenderingMode(.hierarchical)
                VStack(alignment: .leading, spacing: 2) {
                    Text(set.name).font(.title3.weight(.semibold))
                    Text("\(set.fixtureCount) fixtures").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if set.isDefault {
                    Text("Default").font(.caption2.weight(.semibold)).padding(.horizontal, 7).padding(.vertical, 2)
                        .background(.tint.opacity(0.18), in: .capsule).foregroundStyle(.tint)
                }
            }
            if !set.description.isEmpty {
                Text(set.description).font(.callout).foregroundStyle(.secondary).lineLimit(2)
            }
            FlowChips(items: set.models.map { "\($0.count)× \($0.model)" })
            Divider()
            HStack(spacing: 14) {
                Label(set.isVirtual ? "Visualiser only" : set.outputText,
                      systemImage: set.isVirtual ? "eye" : set.outputText.hasPrefix("USB") ? "cable.connector" : "network")
                    .lineLimit(1)
                Label(set.director == "openai" ? "AI director" : set.director.hasPrefix("ollama") ? "Local AI" : "Rules",
                      systemImage: set.director == "rules" ? "list.bullet.rectangle" : "wand.and.stars")
            }
            .font(.caption).foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 170, alignment: .topLeading)
        .background(.background.secondary, in: .rect(cornerRadius: 16))
        .overlay {
            RoundedRectangle(cornerRadius: 16).strokeBorder(selected ? Color.accentColor : .clear, lineWidth: 2)
        }
        .contentShape(.rect(cornerRadius: 16))
    }
}

struct NewSetCard: View {
    var action: () -> Void
    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                Image(systemName: "plus.circle.fill").font(.largeTitle).symbolRenderingMode(.hierarchical)
                Text("New Set").font(.headline)
                Text("Set up a rig step by step").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 170)
            .background(.background.secondary.opacity(0.5), in: .rect(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).strokeBorder(.quaternary, style: StrokeStyle(lineWidth: 1.5, dash: [6])) }
        }
        .buttonStyle(.plain)
    }
}

struct FlowChips: View {
    var items: [String]
    var body: some View {
        HStack(spacing: 6) {
            ForEach(items.prefix(4), id: \.self) { t in
                Text(t).font(.caption).lineLimit(1)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(.quaternary.opacity(0.6), in: .capsule)
            }
            if items.count > 4 { Text("+\(items.count - 4)").font(.caption).foregroundStyle(.secondary) }
        }
    }
}
