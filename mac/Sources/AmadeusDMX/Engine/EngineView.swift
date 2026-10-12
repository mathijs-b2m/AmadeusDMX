// The engine's own output: what it prints (analysis, AI progress, VirtualDJ health), for when something
// needs explaining.
import AmadeusKit
import SwiftUI

struct EngineView: View {
    @Environment(AppModel.self) private var model
    @State private var which = 0
    @State private var filter = ""
    @State private var follow = true

    var body: some View {
        let proc = which == 0 ? model.engine : model.setup
        let lines = filter.isEmpty ? proc.log : proc.log.filter { $0.text.localizedCaseInsensitiveContains(filter) }
        VStack(spacing: 0) {
            if proc.log.isEmpty {
                ContentUnavailableView(which == 0 ? "The Show Engine Hasn’t Run Yet" : "Setup Service Not Started",
                                       systemImage: "terminal",
                                       description: Text(which == 0 ? "Start a show (⌘R) and its output appears here."
                                                         : "It starts when the wizard or the rig tools need it."))
            } else {
                ScrollViewReader { proxy in
                    List(lines) { line in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Text(line.date, format: .dateTime.hour().minute().second())
                                .foregroundStyle(.tertiary)
                            Text(line.text)
                                .foregroundStyle(line.isError ? .red : line.text.contains("✓") ? .green
                                                 : line.text.contains("⚠") ? .orange : .primary)
                                .textSelection(.enabled)
                        }
                        .font(.system(.callout, design: .monospaced))
                        .id(line.id)
                        .listRowSeparator(.hidden)
                    }
                    .listStyle(.plain)
                    .onChange(of: proc.log.last?.id) {
                        if follow, let id = lines.last?.id { proxy.scrollTo(id, anchor: .bottom) }
                    }
                }
            }
        }
        .searchable(text: $filter, placement: .toolbar, prompt: "Filter")
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Picker("Process", selection: $which) {
                    Text("Show Engine").tag(0)
                    Text("Setup Service").tag(1)
                }
                .pickerStyle(.segmented)
            }
            ToolbarItem {
                Toggle(isOn: $follow) { Label("Follow", systemImage: "arrow.down.to.line") }
                    .help("Keep scrolling to the newest line")
            }
            ToolbarItem {
                Button("Copy", systemImage: "doc.on.doc") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(lines.map(\.text).joined(separator: "\n"), forType: .string)
                }
            }
            ToolbarItem {
                Button("Clear", systemImage: "trash") { proc.clearLog() }
            }
        }
    }
}
