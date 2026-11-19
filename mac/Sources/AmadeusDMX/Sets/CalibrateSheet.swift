// Calibrate: the fixtures of one model put right on the real rig when they behave oddly (a head that goes the
// wrong way, a bar that runs backwards), one at a time, as `amadeus test` asks in the terminal. Each fixture is lit
// as it hangs on the rig: a head straight out to the audience (where does it really point?), then the check after
// hanging's way (does it pan the right way round?); a bar's cells red, green, blue, white along it (reversed?).
// Every answer puts the fixture right at once (its calibration in the set, a bar's `reverse` on the rig) and lights
// it again to see.
import AmadeusKit
import SwiftUI

struct CalibrateTarget: Identifiable {
    var key: String
    var name: String
    var fixtures: [String]   // in the set's order
    var start: Int = 0       // the one to begin with
    var id: String { key }
}

struct CalibrateSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: CalibrateTarget
    let definition: FixtureDefinition?
    let rig: String
    let set: String
    let saved: () -> Void

    enum Step: Hashable { case front, check, cells }

    @State private var layout: [String: Any] = [:]   // the set on the rig, calibrations and all
    @State private var checks: [String: HangCheckStep] = [:]
    @State private var index = 0
    @State private var step: Step?
    @State private var order = ""         // which end of the bar red should be at
    @State private var output = ""
    @State private var fixed: [String: [String]] = [:]   // what was put right, per fixture
    @State private var note: String?
    @State private var error: String?
    @State private var busy = false
    @State private var lit: String?
    @State private var confirmed = Set<String>()   // said right, or put right on its own: siblings' fixes pass it by

    private var id: String? { target.fixtures.indices.contains(index) ? target.fixtures[index] : nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            Group {
                if let error {
                    ContentUnavailableView("Couldn’t Light It", systemImage: "exclamationmark.triangle", description: Text(error))
                } else if let id {
                    fixtureView(id)
                } else {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            Divider()
            footer
        }
        .frame(minWidth: 720, idealWidth: 760, minHeight: 440, idealHeight: 480)
        .task { await load() }
        .onDisappear { switchOff() }
    }

    // MARK: parts

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text("Calibrate").font(.title2.weight(.semibold))
                Text(target.name).foregroundStyle(.secondary)
                Spacer()
                if !target.fixtures.isEmpty {
                    Text("\(index + 1) of \(target.fixtures.count)").foregroundStyle(.secondary).monospacedDigit()
                }
            }
            Text("Stand where the audience would be, facing the stage. Each one lights as it hangs on \(rig); say what the real one does and it is put right, and the others of this model with it (except those you already went through).")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
    }

    @ViewBuilder
    private func fixtureView(_ id: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(id).font(.system(size: 26, weight: .bold).monospaced())
                if let c = checks[id] { Text("\(c.label) · \(c.dmx)").foregroundStyle(.secondary) }
            }
            if let c = checks[id] { Text(c.where).font(.callout) }
            if unplaced(id) {
                Label("Not placed on \(rig) yet: place it on the Rigs page first, so the calibration knows how it hangs.",
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            } else if let step {
                stepView(id, step)
            }
            if let done = fixed[id], !done.isEmpty {
                Label("Put right: \(done.joined(separator: ", ")). Saved\(siblingNote(id)).", systemImage: "checkmark.circle.fill")
                    .font(.callout).foregroundStyle(.green).fixedSize(horizontal: false, vertical: true)
            }
            if let note {
                Text(note).font(.callout).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            if !output.isEmpty { Text(output).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
        }
        .padding(16)
    }

    @ViewBuilder
    private func stepView(_ id: String, _ step: Step) -> some View {
        switch step {
        case .front:
            Label("Its beam should point straight out at the audience, a little down (up when it stands on the floor). Where does the real one point?",
                  systemImage: "light.beacon.max")
                .font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("At the Audience", systemImage: "checkmark") { advance() }
                    .fixedSize()
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                Button("Left", systemImage: "arrow.left") { fix(id, "left", "its pan home turned") }
                Button("Right", systemImage: "arrow.right") { fix(id, "right", "its pan home turned") }
                Button("Back at the Stage", systemImage: "arrow.uturn.down") { fix(id, "back", "turned round") }
                    .fixedSize()
                Button("Up or Down") {
                    note = "A head that points at the ceiling or the floor here is placed the wrong way up: on the Rigs page, put it hanging under the truss or standing, as it really is."
                }
            }
            .disabled(busy)
            .help("Left and right as you see it, facing the stage. Pressed the wrong one, it ends up the other way: press that one")
        case .check:
            let c = checks[id]
            Label(c?.expect.isEmpty == false ? c!.expect : "Its beam points to one side.", systemImage: "light.beacon.max")
                .font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            Text("This catches a head that pans the other way: pointing straight out, that looks right.")
                .font(.caption).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 6) {
                Button("Yes, There", systemImage: "checkmark") { advance() }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                ForEach(c?.faults ?? [], id: \.self) { f in
                    Button {
                        fix(id, f.fix, HangCheckPanel.cause[f.fix] ?? f.fix)
                    } label: {
                        Text("No, it points \(f.seen)").fixedSize()
                    }
                }
            }
            .disabled(busy)
        case .cells:
            Label(order.isEmpty ? "Its cells light red, green, blue, white along it." : order, systemImage: "light.strip.2")
                .font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Yes", systemImage: "checkmark") { advance() }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                Button("The Other Way Round", systemImage: "arrow.left.arrow.right") { reverse(id) }
            }
            .disabled(busy)
        }
    }

    private var footer: some View {
        HStack {
            Button("Previous", systemImage: "chevron.left") { go(index - 1) }
                .disabled(index == 0 || busy)
            Button("Skip", systemImage: "chevron.right") { go(index + 1) }
                .disabled(index + 1 >= target.fixtures.count || busy)
                .help("On to the next one, without finishing this one")
            Spacer()
            Button("Done") { switchOff(); saved(); dismiss() }
                .keyboardShortcut(.cancelAction)
        }
        .padding(12)
    }

    // MARK: steps

    private func steps(_ id: String) -> [Step] {
        guard let f = fixture(id), let d = definition else { return [] }
        var out: [Step] = []
        if d.isMoving {
            out.append(.front)
            if !(checks[id]?.faults.isEmpty ?? true) { out.append(.check) }
        }
        if d.cells(f["mode"] as? String ?? "") > 1 { out.append(.cells) }
        return out
    }

    private func advance() {
        guard let id else { return }
        note = nil
        let all = steps(id)
        if let s = step, let i = all.firstIndex(of: s), i + 1 < all.count {
            step = all[i + 1]
            Task { await light() }
        } else if index + 1 < target.fixtures.count {
            confirmed.insert(id)
            go(index + 1)
        } else {
            confirmed.insert(id)
            switchOff()
            saved()
            dismiss()
        }
    }

    private func go(_ i: Int) {
        guard target.fixtures.indices.contains(i) else { return }
        index = i
        note = nil
        step = steps(target.fixtures[i]).first
        Task { await light() }
    }

    // MARK: the engine

    private func load() async {
        do {
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            layout = try await model.api.rig(rig: rig, set: set)
            try await refreshChecks()
            index = min(max(target.start, 0), max(target.fixtures.count - 1, 0))
            step = id.flatMap { steps($0).first }
            await light()
        } catch { self.error = error.localizedDescription }
    }

    private func refreshChecks() async throws {
        let all = try await model.api.hangCheck(layout: layout)
        checks = Dictionary(all.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
    }

    /// The fixture lit for its step (the one lit before switched off).
    private func light() async {
        guard let id else { return }
        if let was = lit, was != id { _ = try? await model.api.testLight(fixture: was, on: false, layout: layout, point: nil, cells: false) }
        lit = nil
        guard let step, !unplaced(id) else { output = ""; return }
        do {
            let r = try await model.api.testLight(fixture: id, on: true, layout: layout,
                                                  point: step == .front ? "front" : step == .check ? "check" : nil,
                                                  cells: step == .cells)
            lit = id
            output = r.summary
            order = r.order
        } catch {
            output = error.localizedDescription
        }
    }

    private func switchOff() {
        guard let was = lit else { return }
        lit = nil
        let l = layout
        Task { _ = try? await model.api.testLight(fixture: was, on: false, layout: l, point: nil, cells: false) }
    }

    /// The head's calibration put right for what was seen (the rig editor's front test, the hang check's faults),
    /// saved, and lit again to see.
    private func fix(_ id: String, _ seen: String, _ what: String) {
        note = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                let fields = try await model.api.hangCheckFix(layout: layout, fixture: id, fix: seen)
                let any = try JSONSerialization.jsonObject(with: JSONEncoder().encode(fields)) as? [String: Any] ?? [:]
                let also = try await update(id, keys: Array(any.keys)) { f in f.merge(any) { _, new in new } }
                fixed[id, default: []].append(what)
                for o in also { fixed[o, default: []].append("\(what) (as \(id))") }
                await light()
            } catch { note = error.localizedDescription }
        }
    }

    /// The bar runs the other way on the real rig: its `reverse` (where it hangs, on the rig) flipped.
    private func reverse(_ id: String) {
        note = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                let also = try await update(id, keys: ["reverse"]) { f in f["reverse"] = (f["reverse"] as? Bool ?? false) ? nil : true }
                fixed[id, default: []].append("its cells the other way round")
                for o in also { fixed[o, default: []].append("its cells the other way round (as \(id))") }
                await light()
            } catch { note = error.localizedDescription }
        }
    }

    /// A change to one fixture, its `keys` then copied to the siblings of its model in the set that weren't said
    /// right or put right on their own yet (hung alike, they are wrong alike); saved at once (the engine splits it
    /// into the set and the rig). Returns the siblings it went to.
    @discardableResult
    private func update(_ id: String, keys: [String], _ body: (inout [String: Any]) -> Void) async throws -> [String] {
        var l = layout
        var fixtures = l["fixtures"] as? [[String: Any]] ?? []
        guard let i = fixtures.firstIndex(where: { $0["id"] as? String == id }) else { return [] }
        body(&fixtures[i])
        var also: [String] = []
        for j in fixtures.indices where j != i && fixtures[j]["fixture"] as? String == fixtures[i]["fixture"] as? String {
            guard let sid = fixtures[j]["id"] as? String, !confirmed.contains(sid) else { continue }
            for k in keys { fixtures[j][k] = fixtures[i][k] }
            also.append(sid)
        }
        l["fixtures"] = fixtures
        try await model.api.saveRig(l, rigName: rig, setName: set)
        layout = l
        confirmed.insert(id)
        try await refreshChecks()
        model.reloadSets()
        return also
    }

    /// The siblings a fix of this one went to, in words.
    private func siblingNote(_ id: String) -> String {
        let others = target.fixtures.filter { $0 != id && (fixed[$0] ?? []).contains { $0.hasSuffix("(as \(id))") } }
        return others.isEmpty ? "" : ", and for \(others.joined(separator: ", ")) too"
    }

    private func fixture(_ id: String) -> [String: Any]? {
        (layout["fixtures"] as? [[String: Any]] ?? []).first { $0["id"] as? String == id }
    }

    private func unplaced(_ id: String) -> Bool { fixture(id)?[RigDocument.unplacedKey] != nil }
}
