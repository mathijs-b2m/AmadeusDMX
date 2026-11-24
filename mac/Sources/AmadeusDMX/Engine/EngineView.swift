// The engine's own output: what it prints (analysis, AI progress, VirtualDJ health), for when something
// needs explaining. And the DMX trace: every value that goes out to the lights, as it changes.
import AmadeusKit
import SwiftUI

struct EngineView: View {
    @Environment(AppModel.self) private var model
    @State private var which = 0
    @State private var filter = ""
    @State private var follow = true
    @State private var trace: DMXTrace?

    /// The trace shows at most this many lines at once (the filter looks through all that are kept).
    private static let shown = 3000

    var body: some View {
        VStack(spacing: 0) {
            if which == 2 { traceList } else { logList }
        }
        .searchable(text: $filter, placement: .toolbar, prompt: which == 2 ? "Filter (a fixture, a channel, U1.017)" : "Filter")
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Picker("Process", selection: $which) {
                    Text("Show Engine").tag(0)
                    Text("Setup Service").tag(1)
                    Text("DMX Trace").tag(2)
                }
                .pickerStyle(.segmented)
            }
            ToolbarItem {
                Toggle(isOn: Binding(get: { trace?.isOn ?? false }, set: { on in
                    trace?.set(on)
                    if on { which = 2 }
                })) { Label("Trace DMX", systemImage: "waveform.path.ecg") }
                    .help("Write down every value that goes out to the lights, as it changes: when, which fixture, which channel")
                    .disabled(trace == nil)
            }
            ToolbarItem {
                Toggle(isOn: $follow) { Label("Follow", systemImage: "arrow.down.to.line") }
                    .help("Keep scrolling to the newest line")
            }
            ToolbarItem {
                Button("Copy", systemImage: "doc.on.doc") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(copyText, forType: .string)
                }
            }
            if which == 2, let trace {
                ToolbarItem {
                    Button("Show in Finder", systemImage: "folder") { NSWorkspace.shared.activateFileViewerSelecting([trace.log]) }
                        .help("The whole trace as a file (dmx-trace.log)")
                        .disabled(!FileManager.default.fileExists(atPath: trace.log.path))
                }
            }
            ToolbarItem {
                Button("Clear", systemImage: "trash") {
                    if which == 2 { trace?.clear() } else { proc.clearLog() }
                }
            }
        }
        .task(id: TraceWatch(data: model.workspace?.data, reading: which == 2)) {
            guard let data = model.workspace?.data else { trace = nil; return }
            if trace?.data.path != data.path { trace = DMXTrace(data: data) }
            while !Task.isCancelled {  // the file's end four times a second while it shows; else only the switch
                trace?.poll(read: which == 2)
                try? await Task.sleep(for: .milliseconds(which == 2 ? 250 : 1000))
            }
        }
    }

    private struct TraceWatch: Equatable {
        var data: URL?
        var reading: Bool
    }

    private var proc: EngineProcess { which == 0 ? model.engine : model.setup }

    private var logLines: [EngineProcess.LogLine] {
        filter.isEmpty ? proc.log : proc.log.filter { $0.text.localizedCaseInsensitiveContains(filter) }
    }

    private var traceLines: [DMXTrace.Line] {
        let all = trace?.lines ?? []
        let match = filter.isEmpty ? all : all.filter { $0.text.localizedCaseInsensitiveContains(filter) }
        return Array(match.suffix(Self.shown))
    }

    private var copyText: String {
        (which == 2 ? traceLines.map(\.text) : logLines.map(\.text)).joined(separator: "\n")
    }

    @ViewBuilder private var logList: some View {
        let lines = logLines
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

    @ViewBuilder private var traceList: some View {
        let lines = traceLines
        if trace?.lines.isEmpty ?? true {
            if trace?.isOn == true {
                ContentUnavailableView("Nothing Sent Yet", systemImage: "waveform.path.ecg",
                                       description: Text("Start a show or light a fixture: every DMX value that goes out appears here as it changes, with its time, fixture and channel."))
            } else {
                ContentUnavailableView {
                    Label("The DMX Trace Is Off", systemImage: "waveform.path.ecg")
                } description: {
                    Text("Switched on, every DMX value that goes out to the lights is written down as it changes: when, to which fixture, on which channel. It can be switched on and off while a show runs.")
                } actions: {
                    Button("Trace DMX") { trace?.set(true) }.disabled(trace == nil)
                }
            }
        } else {
            ScrollViewReader { proxy in
                List(lines) { line in
                    Text(line.text)
                        .foregroundStyle(line.isNote ? .secondary : .primary)
                        .textSelection(.enabled)
                        .font(.system(.callout, design: .monospaced))
                        .id(line.id)
                        .listRowSeparator(.hidden)
                }
                .listStyle(.plain)
                .onChange(of: lines.last?.id) {
                    if follow, let id = lines.last?.id { proxy.scrollTo(id, anchor: .bottom) }
                }
            }
        }
    }
}
