// Wizard: where the DMX goes (Art-Net / sACN node, USB interface or the visualiser only).
import AmadeusKit
import SwiftUI

struct NetworkStep: View {
    @Environment(AppModel.self) private var model
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "cable.connector", title: "Connect the Lights",
                       text: "DMX goes to a network node (Art-Net or sACN) or a USB interface on this Mac. No lights here? Run in the visualiser only.")
            Picker("", selection: $w.output) {
                Text("Visualiser only").tag(WizardModel.Output.visualiser)
                Text("Network node").tag(WizardModel.Output.node)
                Text("Node address").tag(WizardModel.Output.manual)
                Text("USB interface").tag(WizardModel.Output.usb)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            switch w.output {
            case .visualiser:
                Label("The show runs on screen only. You can add an output later on the setup page.", systemImage: "eye")
                    .foregroundStyle(.secondary)
            case .node, .manual:
                protocolPicker
                if w.output == .node { nodeList } else {
                    Form { TextField("Node IP address", text: $w.manualIP) }
                        .formStyle(.grouped).frame(height: 80)
                }
            case .usb:
                usbList
            }
        }
        .task(id: w.output) {
            if w.output == .node && w.nodes.isEmpty { await w.discover(model.api) }
            if w.output == .usb && w.usb.isEmpty { await w.findUSB(model.api) }
        }
    }

    private var protocolPicker: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Protocol", selection: $w.sacn) {
                Text("Art-Net").tag(false)
                Text("sACN (E1.31)").tag(true)
            }
            .pickerStyle(.radioGroup)
            .horizontalRadioGroupLayout()
            if w.sacn {
                Toggle("Multicast (every sACN node on the network listens; usual)", isOn: $w.multicast)
                Text("Set the node’s input to sACN too. On a Showtec NET-2/3 or NET-2/5 Pocket: in its menu or web page. Universe 1 = its first output.")
                    .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    @ViewBuilder
    private var nodeList: some View {
        HStack {
            Button(w.discovering ? "Searching…" : "Search the Network") { Task { await w.discover(model.api) } }
                .disabled(w.discovering)
            if w.discovering { ProgressView().controlSize(.small) }
        }
        if let e = w.discoverError { Text(e).foregroundStyle(.secondary).font(.callout) }
        ForEach(w.nodes) { n in
            Button { w.node = n } label: {
                HStack {
                    Image(systemName: w.node == n ? "largecircle.fill.circle" : "circle")
                    VStack(alignment: .leading) {
                        Text(n.name.isEmpty ? n.ip : n.name)
                        Text("\(n.ip)\(n.longName.map { " · \($0)" } ?? "")").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(10)
                .background(.background.secondary, in: .rect(cornerRadius: 10))
            }
            .buttonStyle(.plain)
        }
    }

    @ViewBuilder
    private var usbList: some View {
        HStack {
            Button(w.searchingUSB ? "Looking…" : "Find USB Interfaces") { Task { await w.findUSB(model.api) } }
                .disabled(w.searchingUSB)
            if w.searchingUSB { ProgressView().controlSize(.small) }
        }
        Text("ENTTEC DMX USB Pro / Pro Mk2, DMXking ultraDMX, Eurolite USB-DMX512-PRO and other Pro-compatible interfaces. One universe per interface.")
            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        if w.usb.isEmpty && !w.searchingUSB {
            Label("Nothing found. Plug it in, or keep “first one found”: the engine looks again when the show starts.",
                  systemImage: "cable.connector.slash").foregroundStyle(.secondary).font(.callout)
        }
        ForEach(w.usb) { u in
            Button { w.usbPort = u.port } label: {
                HStack {
                    Image(systemName: w.usbPort == u.port ? "largecircle.fill.circle" : "circle")
                    VStack(alignment: .leading) {
                        Text(u.isPro ? "DMX USB Pro\(u.widgetSerial.map { " #\($0)" } ?? "")" : (u.description ?? u.port))
                        Text([u.port, u.manufacturer, u.firmware.map { "firmware \($0)" }].compactMap { $0 }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if u.isPro { Image(systemName: "checkmark.seal.fill").foregroundStyle(.green) }
                }
                .padding(10)
                .background(.background.secondary, in: .rect(cornerRadius: 10))
            }
            .buttonStyle(.plain)
        }
    }
}
