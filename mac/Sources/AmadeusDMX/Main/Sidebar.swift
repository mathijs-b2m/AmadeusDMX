// The sidebar: the pages, and the engine's state at the bottom.
import AmadeusKit
import SwiftUI

struct Sidebar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        List(selection: $model.sidebarSelection) {
            // id: \.self - a selectable list tags ForEach rows with their id; it must be the selection's type
            ForEach(Section.allCases, id: \.self) { s in
                NavigationLink(value: s) {
                    Label(s.title, systemImage: s.symbol)
                }
                .badge(badge(s))
                .help(s.help)
            }
        }
        .listStyle(.sidebar)
        .safeAreaInset(edge: .bottom) { EngineFooter().padding(10) }
    }

    private func badge(_ s: Section) -> Text? {
        if s == .engine, case .failed = model.showState { return Text("!") }
        return nil
    }
}

/// The engine at a glance, at the bottom of the sidebar.
struct EngineFooter: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        let state = model.showState
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: state.symbol)   // no symbolEffect: a running animation redraws every frame
                    .foregroundStyle(color(state))
                Text(model.showTitle).font(.callout.weight(.semibold))
                Spacer()
                if model.feed.state == .connected, state.isActive, !model.feed.lite {
                    Text("\(Int(model.feed.fps.rounded())) fps")
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            if model.engineRunning && model.power.measured {
                PowerLine(power: model.power, stageOn: model.mode.renders3D)
                if model.mode.sendsDMX && model.mode.renders3D && model.power.stageIsHeavy {
                    PowerWarning(power: model.power) { model.setMode(.perform) }
                }
            }
            if case .failed(let why) = state {
                Text(why).font(.caption).foregroundStyle(.secondary).lineLimit(3)
            } else if let link = model.feed.link, model.engineRunning {
                Label(link.up ? "\(link.name) · \(String(format: "%.0f", link.jitterMs)) ms jitter" : "\(link.name): link down",
                      systemImage: link.up ? "laptopcomputer" : "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(link.up ? Color.secondary : Color.orange)
            } else if state == .waitingForDJ {
                Text(model.djWaiting)
                    .font(.caption).foregroundStyle(.secondary)
            } else if state == .attached {
                Text("An engine started outside the app is running; the app shows its lights.")
                    .font(.caption).foregroundStyle(.secondary)
            } else if let set = model.currentSet {
                Button { openWindow(id: "dmx") } label: {
                    Label(set.isVirtual || !model.sendArtNet ? "Visualiser only" : set.outputText, systemImage: "cable.connector")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help("DMX Devices & Output… (⇧⌘D)")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassEffect(.regular, in: .rect(cornerRadius: 14))
        .onAppear { meter(model.engineRunning) }
        .onChange(of: model.engineRunning) { _, running in meter(running) }
    }

    private func meter(_ running: Bool) {
        if StageRenderer.onGPUTime == nil {
            let power = model.power
            StageRenderer.onGPUTime = { power.gpuSeconds += $0 }
        }
        if running { model.power.start { [engine = model.engine] in engine.pid } } else { model.power.stop() }
    }

    private func color(_ s: ShowState) -> Color {
        switch s {
        case .live, .playing: .green
        case .waitingForDJ, .starting: .orange
        case .attached: .blue
        case .failed: .red
        case .stopped: .secondary
        }
    }
}


/// What the show costs the computer: the lights against the 3D stage.
struct PowerLine: View {
    let power: PowerMeter
    let stageOn: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            row("Lights", power.engine.cpu, gpu: nil)
            if stageOn { row("3D stage", power.stage.cpu, gpu: power.gpu) }
        }
        .font(.caption.monospacedDigit())
        .foregroundStyle(.secondary)
        .help("CPU use (100% = one core) of the light engine and of the app's 3D stage, and the GPU time the "
              + "stage takes. Measured every \(Int(PowerMeter.interval)) s.")
    }

    // one line each, however narrow the sidebar: a taller footer would push the show's timeline out of the window
    private func row(_ name: String, _ cpu: Double, gpu: Double?) -> some View {
        HStack(spacing: 6) {
            Text(name).frame(width: 58, alignment: .leading)
            Text(String(format: "%.0f%% CPU", cpu * 100) + (gpu.map { String(format: " · GPU %.0f%%", $0 * 100) } ?? ""))
                .lineLimit(1).minimumScaleFactor(0.75)
        }
    }
}

/// The 3D stage costs more than the show can spare: say so, and offer Perform Only.
struct PowerWarning: View {
    let power: PowerMeter
    let performOnly: () -> Void

    // short, on one line with its button (the whole story in the tooltip): the footer must stay low
    var body: some View {
        HStack(spacing: 6) {
            Label(short, systemImage: "exclamationmark.triangle.fill")
                .font(.caption).foregroundStyle(.orange)
                .lineLimit(1).minimumScaleFactor(0.8)
            Spacer(minLength: 4)
            Button("Perform Only", action: performOnly)
                .controlSize(.mini)
        }
        .help(reason + " Perform Only: the lights only, no 3D stage, so the computer's power goes to the show.")
    }

    private var why: String? {
        power.hot ? "The Mac is getting hot" : power.lowPower ? "Low Power Mode is on" : power.onBattery ? "On battery" : nil
    }

    private var ratio: Double { (power.stage.cpu + power.gpu) / max(power.engine.cpu, 0.05) }

    private var short: String {
        let cost = ratio >= 1.5 ? "3D \(Int(ratio.rounded()))× the lights" : "3D stage is heavy"
        return power.hot ? "Hot · \(cost)" : power.lowPower ? "Low Power · \(cost)" : power.onBattery ? "Battery · \(cost)" : cost
    }

    private var reason: String {
        let cost = ratio >= 1.5 ? "the 3D stage takes \(Int(ratio.rounded()))× what the lights do" : "the 3D stage adds to the load"
        return (why.map { "\($0): " } ?? "") + cost + ". During a gig, Perform Only keeps the lights on time."
    }
}
