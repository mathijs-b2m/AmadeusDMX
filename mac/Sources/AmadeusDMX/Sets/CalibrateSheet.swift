// Calibrate: a model's fixtures put right on the real rig when they behave oddly (a head that goes the wrong way,
// a bar that runs backwards), by going through one of them: the others of the model get the same calibration. It
// stays with the fixture it was opened on (another one is chosen at the top, for one that behaves differently).
// First whether the head hangs or stands; then it is lit as it is placed on the rig: straight out to the audience
// (a head that doesn't gets its pan home a quarter on at a press, until it does), then from there turning slowly to
// one side and back (one that turns the other way gets its pan the other way round, straight out kept as it was:
// straight out alone can't tell a mirrored pan from a head turned round, and the show then sent it the wrong way),
// each with a picture of the head and where its beam should go; a bar's cells red, green, blue, white along it
// (reversed?). One step never undoes another's.
// Every press puts the fixture right at once (its calibration in the set, its placing on the rig) and lights it
// again to see.
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

    enum Step: String, Hashable, CaseIterable { case mount, front, pan, cells }

    @State private var layout: [String: Any] = [:]   // the set on the rig, calibrations and all
    @State private var checks: [String: HangCheckStep] = [:]
    @State private var index = 0
    @State private var step: Step?
    @State private var order = ""         // which end of the bar red should be at
    @State private var side = ""          // the pan test turns to the audience's left or right
    @State private var output = ""
    @State private var fixed: [String: [String: String]] = [:]   // what was put right, per fixture and step
    @State private var beam: BeamPicture.Beam?   // where the lit head's beam should go
    // the calibrations a head is tried with in this step, a press at a time: [0] the one it came with (nothing changed)
    @State private var ways: [[String: Any]] = []
    @State private var wayNames: [String] = []
    @State private var wayBase: [String: Any] = [:]   // the fixture as it came
    @State private var way = 0
    @State private var finished = false          // this fixture is through its steps
    @State private var followers: [String] = []  // the others of the model its calibration went to

    /// What a head's calibration is made of: copied to the others of its model when it is through.
    static let calibration = ["pan_home_deg", "pan_invert", "tilt_invert"]
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
        .frame(minWidth: 720, idealWidth: 760, minHeight: 600, idealHeight: 640)
        .task { await load() }
        .task(id: lit) {   // the engine's light test goes dark after a minute: kept lit for as long as it is looked at
            guard let id = lit else { return }
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                if Task.isCancelled { break }
                if (try? await model.api.keepLight(fixture: id)) == false, !busy { Task { await light() } }
            }
        }
        .onDisappear { switchOff() }
    }

    // MARK: parts

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text("Calibrate").font(.title2.weight(.semibold))
                Text(target.name).foregroundStyle(.secondary)
                Spacer()
                if target.fixtures.count > 1 {
                    Picker("Fixture", selection: Binding(get: { index }, set: { go($0) })) {
                        ForEach(target.fixtures.indices, id: \.self) { Text(target.fixtures[$0]).tag($0) }
                    }
                    .labelsHidden().fixedSize().disabled(busy)
                    .help("The fixture you go through. One is enough: the others of this model get its calibration. Choose another one only when it behaves differently")
                }
            }
            Text("Go through one fixture of this model: the others get the same calibration. Stand where the audience would be, facing the stage. It lights as it is placed on \(rig), with a picture of what it should do. When the real one does something else, press until it matches.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Text(HangCheckPanel.sides)
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
            } else if finished {
                finishedView(id)
            } else if let step {
                stepView(id, step)
            }
            if let done = fixed[id], !done.isEmpty {
                let said = Step.allCases.compactMap { done[$0.rawValue] }
                Label("Put right: \(said.joined(separator: ", ")). Saved\(siblingNote(id)).", systemImage: "checkmark.circle.fill")
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
        case .mount:
            let hangs = fixture(id)?["mount"] as? String == "hang"
            Label("How is the real \(id) mounted?", systemImage: "questionmark.circle")
                .font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 12) {
                mountButton(id, hanging: true, placed: hangs)
                mountButton(id, hanging: false, placed: !hangs)
            }
            .disabled(busy)
            Text("On \(rig) it is placed \(hangs ? "hanging" : "standing"). The pictures that follow show it the way you say here.")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        case .front:
            Label("Its beam should point straight out at the audience, as in the picture. Only the direction counts: level, or a little up or down, is all fine.",
                  systemImage: "light.beacon.max")
                .font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            matchView(id)
        case .pan:
            Label("From straight out it turns slowly to your \(side.isEmpty ? "left" : side) and back, again and again, as in the picture. Does the real one turn that way?",
                  systemImage: "arrow.left.and.right")
                .font(.callout.weight(.medium)).fixedSize(horizontal: false, vertical: true)
            Text("Pointing straight out, a head that pans the other way round can look right; the show then sends it the wrong way. Watch which way it goes, not how far.")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let beam { BeamPicture(beam: beam) }
            HStack {
                Button("Turns That Way", systemImage: "checkmark") { advance() }
                    .fixedSize()
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                Button("Turns the Other Way", systemImage: "arrow.uturn.left") { flipPan(id) }
                    .fixedSize()
                    .help("Its pan the other way round. Straight out stays as you just saw it; it now turns the other way. Press again to put it back")
            }
            .disabled(busy)
            Text("Nothing lights up or moves? Then \(id) is not connected, or its address is not \(checks[id]?.dmx ?? "the one in the set").")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
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

    /// The picture of where the beam should go, and the two answers: it does, or try the next calibration.
    @ViewBuilder
    private func matchView(_ id: String) -> some View {
        if let beam { BeamPicture(beam: beam) }
        HStack {
            Button("Like the Picture", systemImage: "checkmark") { advance() }
                .fixedSize()
                .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
            Button("Not Like It: Try Another Way", systemImage: "arrow.triangle.2.circlepath") { tryNext(id) }
                .fixedSize()
                .help("The head is tried another way round (its pan home a quarter or half a turn on). Press until the real beam goes where the picture’s does")
            if ways.count > 1 {
                Text("Way \(way + 1) of \(ways.count)").font(.callout).foregroundStyle(.secondary).monospacedDigit()
            }
        }
        .disabled(busy)
        Text("Nothing lights up or moves? Then \(id) is not connected, or its address is not \(checks[id]?.dmx ?? "the one in the set").")
            .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }

    /// One of the two answers to how the head is mounted: a drawing of it, the way it is placed on the rig marked.
    private func mountButton(_ id: String, hanging: Bool, placed: Bool) -> some View {
        Button {
            if placed { advance() } else { setMount(id, hanging: hanging) }
        } label: {
            VStack(spacing: 4) {
                MovingHeadIcon(hanging: hanging)
                Text(hanging ? "Hanging" : "Standing").font(.headline)
                Text(hanging ? "Under a truss or a bar" : "On the floor, or on top of something")
                    .font(.caption).foregroundStyle(.secondary)
                Text(placed ? "As placed on \(rig)" : " ").font(.caption2).foregroundStyle(.tint)
            }
            .padding(10)
            .frame(width: 210)
            .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(placed ? AnyShapeStyle(.tint) : AnyShapeStyle(.clear), lineWidth: 2))
            .contentShape(.rect(cornerRadius: 10))
        }
        .buttonStyle(.plain)
    }

    /// The fixture is through: what was done, and what happens to the others of its model.
    @ViewBuilder
    private func finishedView(_ id: String) -> some View {
        Label("\(id) is calibrated.", systemImage: "checkmark.seal.fill")
            .font(.title3.weight(.semibold)).foregroundStyle(.green)
        if !followers.isEmpty {
            Text("The other \(followers.count) of this model use the same calibration now: \(followers.joined(separator: ", ")). Mounted the same way round, they are right too; there is no need to go through them.")
                .font(.callout).fixedSize(horizontal: false, vertical: true)
            Text("One of them does behave differently? Choose it at the top right and go through it on its own.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        Text("Colours, gobos or a prism that come out wrong are not put right here: that is Check Channels, on the Sets page.")
            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        Button("Done") { switchOff(); saved(); dismiss() }
            .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
    }

    private var footer: some View {
        HStack {
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
            // hanging or standing is asked of a head on the floor, under or on top of a truss (not one on a truss's side)
            if ["under", "top"].contains(f["truss_side"] as? String ?? "under") { out.append(.mount) }
            out.append(.front)
            // its pan's way round (a moving bar only tilts; on a truss's face its pan isn't left and right)
            if d.kind == "moving_head", (f["mount_roll_deg"] as? Double ?? 0) == 0 { out.append(.pan) }
        }
        if d.cells(f["mode"] as? String ?? "") > 1 { out.append(.cells) }
        return out
    }

    private func advance() {
        guard let id else { return }
        note = nil
        let all = steps(id)
        ways = []
        way = 0
        if let s = step, let i = all.firstIndex(of: s), i + 1 < all.count {
            step = all[i + 1]
            Task { await light() }
        } else {
            finish(id)
        }
    }

    /// The fixture is through its steps: its calibration goes to the others of its model (those not gone through on
    /// their own), and the sheet stays with it.
    private func finish(_ id: String) {
        busy = true
        Task {
            defer { busy = false }
            do {
                followers = definition?.isMoving == true ? try await update(id, keys: Self.calibration) { _ in } : []
                confirmed.insert(id)
                switchOff()
                beam = nil
                finished = true
            } catch { note = error.localizedDescription }
        }
    }

    /// The real head is mounted the other way than it is placed on the rig: its placing put right (under or on top
    /// of its truss), this one only.
    private func setMount(_ id: String, hanging: Bool) {
        note = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                try await update(id, keys: []) { f in
                    f["mount"] = hanging ? "hang" : "stand"
                    if f["truss"] != nil {
                        f["truss_side"] = hanging ? "under" : "top"
                        f["mount_roll_deg"] = nil
                    }
                }
                fixed[id, default: [:]][Step.mount.rawValue] = hanging ? "it hangs" : "it stands"
                advance()
            } catch { note = error.localizedDescription }
        }
    }

    private func go(_ i: Int) {
        guard target.fixtures.indices.contains(i) else { return }
        index = i
        note = nil
        ways = []
        way = 0
        finished = false
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
        guard let step, !unplaced(id) else { output = ""; beam = nil; return }
        do {
            let r = try await model.api.testLight(fixture: id, on: true, layout: layout,
                                                  point: step == .front ? "front" : step == .pan ? "pan" : nil,
                                                  cells: step == .cells)
            lit = id
            output = r.summary
            order = r.order
            side = r.side
            beam = step == .cells ? nil : r.dir.flatMap { d in r.pos.flatMap { p in r.stage.map {
                BeamPicture.Beam(pos: p, dir: d, stage: $0, hanging: fixture(id)?["mount"] as? String == "hang",
                                 to: step == .pan ? r.to : nil)
            } } }
            if step == .mount { beam = nil }
            if step == .pan, r.side.isEmpty { advance() }   // its pan has no room to turn: nothing to see
        } catch {
            output = error.localizedDescription
            beam = nil
        }
    }

    private func switchOff() {
        guard let was = lit else { return }
        lit = nil
        let l = layout
        Task { _ = try? await model.api.testLight(fixture: was, on: false, layout: l, point: nil, cells: false) }
    }

    /// The real head turns the other way than its picture: its pan the other way round, its pan home moved so
    /// straight out stays as it was seen (the engine's "pan" fix), saved, and lit again to see. Pressed again: back.
    private func flipPan(_ id: String) {
        note = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                let fields = try await model.api.hangCheckFix(layout: layout, fixture: id, fix: "pan")
                guard let any = try JSONSerialization.jsonObject(with: JSONEncoder().encode(fields)) as? [String: Any], !any.isEmpty else {
                    note = "Its pan has no room to turn the other way round and still point straight out. Check its pan range on the Fixtures page."
                    return
                }
                let keys = Array(any.keys)
                let also = try await update(id, keys: keys) { f in for k in keys { f[k] = any[k] } }
                let was = fixed[id]?[Step.pan.rawValue] != nil
                fixed[id, default: [:]][Step.pan.rawValue] = was ? nil : "its pan the other way round"
                for o in also { fixed[o, default: [:]][Step.pan.rawValue] = was ? nil : "its pan the other way round (as \(id))" }
                await light()
            } catch { note = error.localizedDescription }
        }
    }

    /// The real head doesn't point straight out like its picture: the next calibration it could have, saved, and lit
    /// again to see: its pan home a quarter on, a press at a time (the rig editor's front test's fixes). Round again,
    /// it is back as it came.
    private func tryNext(_ id: String) {
        guard let step, let base = fixture(id) else { return }
        note = nil
        busy = true
        Task {
            defer { busy = false }
            do {
                if ways.isEmpty {
                    let options: [(String, String)] = [("left", "its pan home turned"), ("back", "turned round"), ("right", "its pan home turned")]
                    var found: [[String: Any]] = [[:]], names = [""]
                    for (option, name) in options {
                        guard let fields = try? await model.api.hangCheckFix(layout: layout, fixture: id, fix: option),
                              let any = try JSONSerialization.jsonObject(with: JSONEncoder().encode(fields)) as? [String: Any],
                              !any.isEmpty, !found.contains(where: { NSDictionary(dictionary: $0).isEqual(to: any) })
                        else { continue }
                        found.append(any)
                        names.append(name)
                    }
                    guard found.count > 1 else {
                        note = "There is no other way to try this head. If it doesn’t do as the picture, it is placed differently here than it really hangs or stands: put that right on the Rigs page."
                        return
                    }
                    ways = found
                    wayNames = names
                    wayBase = base
                    way = 0
                }
                let next = (way + 1) % ways.count
                let keys = Array(Set(ways.flatMap(\.keys)))
                let to = ways[next], from = wayBase
                let also = try await update(id, keys: keys) { f in for k in keys { f[k] = to[k] ?? from[k] } }
                way = next
                fixed[id, default: [:]][step.rawValue] = next == 0 ? nil : wayNames[next]
                for o in also { fixed[o, default: [:]][step.rawValue] = next == 0 ? nil : "\(wayNames[next]) (as \(id))" }
                if next == 0 {
                    note = "That was every way, and it is back as it came. If none looked like the picture, it is placed differently here than it really hangs or stands (hanging or standing, or on another side of the truss): put that right on the Rigs page. Or its mode or address is off: see Check Channels."
                }
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
                let was = fixed[id]?[Step.cells.rawValue] != nil   // pressed again: back as it came
                fixed[id, default: [:]][Step.cells.rawValue] = was ? nil : "its cells the other way round"
                for o in also { fixed[o, default: [:]][Step.cells.rawValue] = was ? nil : "its cells the other way round (as \(id))" }
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
        let others = target.fixtures.filter { $0 != id && (fixed[$0] ?? [:]).values.contains { $0.hasSuffix("(as \(id))") } }
        return others.isEmpty ? "" : ", and for \(others.joined(separator: ", ")) too"
    }

    private func fixture(_ id: String) -> [String: Any]? {
        (layout["fixtures"] as? [[String: Any]] ?? []).first { $0["id"] as? String == id }
    }

    private func unplaced(_ id: String) -> Bool { fixture(id)?[RigDocument.unplacedKey] != nil }
}
