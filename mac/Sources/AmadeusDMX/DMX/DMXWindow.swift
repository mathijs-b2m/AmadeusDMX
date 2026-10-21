// The DMX Output page (sidebar, Show menu, ⇧⌘D): your DMX devices (Art-Net and sACN nodes, USB interfaces), apart
// from the sets, and where each universe of the selected set goes: which device, which of its outputs.
// Replace a node or play the set somewhere else: only the mapping changes (amadeus/dmx/devices.py).
import AmadeusKit
import SwiftUI

@MainActor
@Observable
final class DMXModel {
    struct Route: Equatable { var device: String?; var output: Int }

    var devices: [DMXDevice] = []
    var usb: [USBInterface] = []
    var nodes: [ArtNetNode] = []
    var universes: [(universe: Int, fixtures: Int)] = []
    var routes: [Int: Route] = [:]
    var legacy: String?                 // the set's own output, when it has no device mapping yet
    var selection: String?
    var loading = false
    var saving = false
    var searching = false
    var message: String?
    var problems: [String] = []
    var changed = false

    private var layout: [String: Any] = [:]
    private var set = ""
    private var rig = ""

    func load(_ model: AppModel) async {
        set = model.selectedSet; rig = model.selectedRig
        guard !set.isEmpty else { return }
        loading = true
        defer { loading = false }
        do {
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }  // a page: may open first
            let d = try await model.api.dmxDevices()
            devices = d.devices
            usb = d.usb
            layout = try await model.api.rig(rig: rig.isEmpty ? nil : rig, set: set)
            var counts: [Int: Int] = [:]
            for f in layout["fixtures"] as? [[String: Any]] ?? [] {
                counts[(f["universe"] as? NSNumber)?.intValue ?? 1, default: 0] += 1
            }
            universes = counts.keys.sorted().map { ($0, counts[$0]!) }
            routes = [:]
            if let dmx = layout["dmx"] as? [String: Any] {
                legacy = nil
                for (k, v) in dmx {
                    guard let u = Int(k), let m = v as? [String: Any] else { continue }
                    routes[u] = Route(device: m["device"] as? String, output: (m["output"] as? NSNumber)?.intValue ?? 1)
                }
            } else {
                legacy = model.currentSet?.outputText
            }
            if selection == nil { selection = devices.first?.id }
            changed = false
            message = nil
            problems = []
        } catch {
            message = error.localizedDescription
        }
    }

    func route(_ u: Int) -> Route { routes[u] ?? Route(device: nil, output: u) }

    func setRoute(_ u: Int, _ r: Route) { routes[u] = r; changed = true }

    func device(_ id: String?) -> DMXDevice? { devices.first { $0.id == id } }

    /// Where a set universe ends up, in the device's own numbering.
    func target(_ u: Int) -> String? {
        let r = route(u)
        guard let d = device(r.device) else { return nil }
        switch d.type {
        case "enttec_pro": return "USB output"
        case "sacn": return "sACN universe \((d.firstUniverse ?? 1) + r.output - 1)"
        default: return "Art-Net universe \((d.firstUniverse ?? 0) + r.output - 1)"
        }
    }

    func add(_ d: DMXDevice) {
        var d = d
        var n = 1
        let base = d.id
        while devices.contains(where: { $0.id == d.id }) { n += 1; d.id = "\(base)-\(n)" }
        devices.append(d)
        selection = d.id
        changed = true
    }

    func addNode(_ n: ArtNetNode) {
        var d = DMXDevice(id: Self.slug(n.name), name: n.longName?.isEmpty == false ? n.longName! : n.name, type: "artnet")
        d.ip = n.ip; d.firstUniverse = n.universes?.min() ?? 0; d.outputs = n.outputs ?? 2
        add(d)
    }

    func addUSB(_ i: USBInterface) {
        var d = DMXDevice(id: "usb", name: i.description?.isEmpty == false ? i.description! : "USB DMX interface", type: "enttec_pro")
        d.port = "auto"; d.serial = i.widgetSerial
        add(d)
    }

    func remove(_ id: String) {
        devices.removeAll { $0.id == id }
        for (u, r) in routes where r.device == id { routes[u] = Route(device: nil, output: r.output) }
        selection = devices.first?.id
        changed = true
    }

    func search(_ api: SetupAPI) async {
        searching = true
        defer { searching = false }
        nodes = (try? await api.discover()) ?? []
        usb = (try? await api.dmxDevices().usb) ?? usb
        message = nodes.isEmpty && usb.isEmpty ? "Nothing answered: is the node on the same network (and switched on)?" : nil
    }

    func save(_ model: AppModel) async {
        saving = true
        defer { saving = false }
        do {
            problems = try await model.api.saveDMXDevices(devices)
            guard problems.isEmpty else { return }
            var dmx: [String: Any] = [:]
            for (u, r) in routes {
                if let id = r.device, device(id) != nil { dmx[String(u)] = ["device": id, "output": r.output] }
            }
            layout["dmx"] = dmx
            let result = try await model.api.saveRig(layout, rigName: rig.isEmpty ? nil : rig, setName: set)
            problems = result.problems ?? []
            guard problems.isEmpty else { return }
            model.reloadSets()
            legacy = nil
            changed = false
            message = model.engineRunning ? "Saved. The show uses it from its next start." : "Saved."
        } catch {
            message = error.localizedDescription
        }
    }

    static func slug(_ s: String) -> String {
        let t = s.lowercased().map { $0.isLetter || $0.isNumber ? $0 : "-" }
        let out = String(t).split(separator: "-").joined(separator: "-")
        return out.isEmpty ? "device" : out
    }
}

struct DMXPage: View {
    @Environment(AppModel.self) private var model
    @State private var dmx = DMXModel()

    var body: some View {
        HSplitView {
            devicesPane.frame(minWidth: 300, idealWidth: 340)
            universesPane.frame(minWidth: 380)
        }
        .task(id: model.selectedSet + "|" + model.selectedRig) { await dmx.load(model) }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(dmx.saving ? "Saving…" : "Save") { Task { await dmx.save(model) } }
                    .disabled(!dmx.changed || dmx.saving)
                    .keyboardShortcut("s", modifiers: .command)
            }
        }
    }

    // MARK: your devices

    private var devicesPane: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Your DMX Devices").font(.headline)
                Spacer()
                Menu {
                    Button("Art-Net Node") {
                        var d = DMXDevice(id: "node", name: "Art-Net node", type: "artnet")
                        d.ip = "2.0.0.10"; d.firstUniverse = 0; d.outputs = 2
                        dmx.add(d)
                    }
                    Button("sACN Node / Multicast") {
                        var d = DMXDevice(id: "sacn", name: "sACN", type: "sacn")
                        d.firstUniverse = 1; d.priority = 100; d.outputs = 4
                        dmx.add(d)
                    }
                    Button("USB Interface") {
                        var d = DMXDevice(id: "usb", name: "USB DMX interface", type: "enttec_pro")
                        d.port = "auto"
                        dmx.add(d)
                    }
                } label: { Label("Add", systemImage: "plus") }
                    .fixedSize()
                Button { Task { await dmx.search(model.api) } } label: {
                    Label(dmx.searching ? "Searching…" : "Search", systemImage: "antenna.radiowaves.left.and.right")
                }
                .disabled(dmx.searching)
                .help("Look for Art-Net nodes on the network and USB DMX interfaces on this Mac")
            }
            .padding(12)
            List(selection: $dmx.selection) {
                SwiftUI.Section("Devices") {
                    ForEach(dmx.devices) { d in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(d.name)
                            Text("\(d.kindText) · \(d.addressText)").font(.caption).foregroundStyle(.secondary)
                        }
                        .tag(d.id)
                    }
                    if dmx.devices.isEmpty {
                        Text("No devices yet: add one, or search the network.").foregroundStyle(.secondary)
                    }
                }
                let newNodes = dmx.nodes.filter { n in !dmx.devices.contains { $0.ip == n.ip } }
                let newUSB = dmx.usb.filter { $0.isPro }.filter { i in !dmx.devices.contains { $0.type == "enttec_pro" && ($0.serial == nil || $0.serial == i.widgetSerial) } }
                if !newNodes.isEmpty || !newUSB.isEmpty {
                    SwiftUI.Section("Found") {
                        ForEach(newNodes) { n in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(n.longName?.isEmpty == false ? n.longName! : n.name)
                                    Text("Art-Net · \(n.ip) · \(n.outputs ?? 0) outputs").font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Add") { dmx.addNode(n) }
                            }
                        }
                        ForEach(newUSB) { i in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(i.description ?? "USB DMX interface")
                                    Text("USB · \((i.port as NSString).lastPathComponent)").font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Add") { dmx.addUSB(i) }
                            }
                        }
                    }
                }
            }
            if let i = dmx.devices.firstIndex(where: { $0.id == dmx.selection }) {
                DeviceEditor(device: Binding(get: { dmx.devices[i] }, set: { dmx.devices[i] = $0; dmx.changed = true }),
                             usb: dmx.usb, remove: { dmx.remove(dmx.devices[i].id) })
            }
        }
    }

    // MARK: the set's universes

    private var universesPane: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Set “\(model.selectedSet)”").font(.headline)
                Text("Where each universe of the set goes. Change the devices or the venue: only this changes, the patch stays.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            if let legacy = dmx.legacy {
                Label("Now: \(legacy) (the set’s own settings). Choose a device per universe to use your devices instead.",
                      systemImage: "info.circle")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Form {
                ForEach(dmx.universes, id: \.universe) { u in
                    let r = dmx.route(u.universe)
                    LabeledContent {
                        HStack {
                            Picker("Device", selection: Binding(get: { r.device ?? "" }, set: { id in
                                dmx.setRoute(u.universe, .init(device: id.isEmpty ? nil : id, output: r.output))
                            })) {
                                Text("Not sent").tag("")
                                ForEach(dmx.devices) { d in Text(d.name).tag(d.id) }
                            }
                            .labelsHidden()
                            if let d = dmx.device(r.device), d.outputCount > 1 {
                                Picker("Output", selection: Binding(get: { r.output }, set: { o in
                                    dmx.setRoute(u.universe, .init(device: r.device, output: o))
                                })) {
                                    ForEach(1...d.outputCount, id: \.self) { o in Text("Output \(o)").tag(o) }
                                }
                                .labelsHidden()
                                .fixedSize()
                            }
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Universe \(u.universe)")
                            Text("\(u.fixtures) fixture\(u.fixtures == 1 ? "" : "s")" + (dmx.target(u.universe).map { " · \($0)" } ?? ""))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                if dmx.universes.isEmpty && !dmx.loading {
                    Text("This set has no fixtures yet.").foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
            ForEach(dmx.problems, id: \.self) { p in
                Label(p, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(.orange)
            }
            if let m = dmx.message { Text(m).font(.callout).foregroundStyle(.secondary) }
        }
        .padding(16)
    }
}

/// One device's settings.
private struct DeviceEditor: View {
    @Binding var device: DMXDevice
    let usb: [USBInterface]
    let remove: () -> Void

    var body: some View {
        Form {
            TextField("Name", text: $device.name)
            Picker("Kind", selection: $device.type) {
                Text("Art-Net node").tag("artnet")
                Text("sACN (E1.31)").tag("sacn")
                Text("USB interface (DMX USB Pro)").tag("enttec_pro")
            }
            switch device.type {
            case "enttec_pro":
                Picker("Port", selection: Binding(get: { device.port ?? "auto" }, set: { device.port = $0 })) {
                    Text("The first one found").tag("auto")
                    ForEach(usb) { i in Text((i.port as NSString).lastPathComponent).tag(i.port) }
                }
            case "sacn":
                Toggle("Multicast (every sACN node listens)", isOn: Binding(get: { device.ip == nil },
                                                                             set: { device.ip = $0 ? nil : "2.0.0.10" }))
                if device.ip != nil { TextField("Node IP address", text: Binding(get: { device.ip ?? "" }, set: { device.ip = $0 })) }
                Stepper("Priority \(device.priority ?? 100)", value: Binding(get: { device.priority ?? 100 }, set: { device.priority = $0 }),
                        in: 0...200, step: 10)
                numbering(default: 1)
            default:
                TextField("Node IP address", text: Binding(get: { device.ip ?? "" }, set: { device.ip = $0 }))
                numbering(default: 0)
            }
            HStack {
                Spacer()
                Button("Remove Device", role: .destructive, action: remove)
            }
        }
        .formStyle(.grouped)
        .frame(maxHeight: 300)
    }

    @ViewBuilder
    private func numbering(default first: Int) -> some View {
        Stepper("Outputs: \(device.outputCount)", value: Binding(get: { device.outputCount }, set: { device.outputs = $0 }), in: 1...64)
        Picker("Its first output is", selection: Binding(get: { device.firstUniverse ?? first }, set: { device.firstUniverse = $0 })) {
            Text("Universe 0").tag(0)
            Text("Universe 1").tag(1)
        }
        .help("How the device counts: most Art-Net nodes call their first output universe 0, sACN starts at 1.")
    }
}
