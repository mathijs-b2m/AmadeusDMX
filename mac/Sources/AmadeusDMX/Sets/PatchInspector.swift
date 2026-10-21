// The selected fixtures of a set: name, DMX mode, universe and start address (checked against the 512 channels and
// the other fixtures), and for moving heads the direction of pan and tilt. With several selected: one mode or
// universe for all of them, or patch them one after another.
import AmadeusKit
import SwiftUI

struct PatchInspector: View {
    let ids: Set<String>
    let fixtures: [[String: Any]]                       // the set's fixtures, as in its file
    let definition: (String) -> FixtureDefinition?
    /// Change the set's fixtures (the closure gets them, returns them changed); saved at once.
    let apply: (String, (inout [[String: Any]]) -> Void) -> Void
    let rename: (String, String) -> Void

    @State private var name = ""
    @State private var address = ""
    @State private var firstAddress = "1"
    /// The text field being edited: what is typed there is saved on Return, on leaving it or on Save.
    @FocusState private var focus: Field?
    enum Field { case name, address }
    @State private var sent = ""   // the last change sent ("id:address" or "id>name"): sent once, not on every blur

    private func string(_ f: [String: Any], _ k: String) -> String { f[k] as? String ?? "" }
    private func int(_ f: [String: Any], _ k: String, _ d: Int) -> Int { (f[k] as? NSNumber)?.intValue ?? d }
    /// The start address, nil when it has none yet (added fixtures wait for you to give them one).
    private func addr(_ f: [String: Any]) -> Int? { (f["address"] as? NSNumber)?.intValue }

    private var selected: [[String: Any]] {
        fixtures.filter { ids.contains(string($0, "id")) }
            .sorted { (int($0, "universe", 1), addr($0) ?? 513) < (int($1, "universe", 1), addr($1) ?? 513) }
    }

    /// How many DMX channels a fixture takes.
    private func footprint(_ f: [String: Any]) -> Int {
        max(1, definition(string(f, "fixture"))?.channels(string(f, "mode")) ?? 1)
    }

    /// The fixtures (by id) whose channels overlap these, in a universe.
    private func clashes(universe u: Int, from a: Int, count n: Int, except: Set<String>) -> [String] {
        fixtures.filter { f in
            let id = string(f, "id")
            guard !except.contains(id), int(f, "universe", 1) == u, let b = addr(f) else { return false }
            return b <= a + n - 1 && a <= b + footprint(f) - 1
        }.map { string($0, "id") }
    }

    /// The first start address in a universe where `n` channels fit.
    private func free(universe u: Int, count n: Int, except: Set<String>, from start: Int = 1) -> Int? {
        var a = max(1, start)
        while a + n - 1 <= 512 {
            if clashes(universe: u, from: a, count: n, except: except).isEmpty { return a }
            a += 1
        }
        return nil
    }

    var body: some View {
        let sel = selected
        Form {
            if sel.count == 1, let f = sel.first { single(f) } else if sel.count > 1 { several(sel) }
        }
        .formStyle(.grouped)
        .onAppear(perform: sync)
        .onChange(of: ids) { old, _ in commit(old); sync() }   // another fixture picked: keep what was typed
        .onChange(of: focus) { old, _ in if old != nil { commit(ids) } }
    }

    /// What is typed in the name and address fields, saved (for the one fixture `ids` holds).
    private func commit(_ ids: Set<String>) {
        guard ids.count == 1, let id = ids.first, let f = fixtures.first(where: { string($0, "id") == id }) else { return }
        let typed = address.trimmingCharacters(in: .whitespaces)
        if typed.isEmpty, addr(f) != nil, sent != "\(id):-" {  // cleared: no start address (until given one)
            sent = "\(id):-"
            apply("Clear Address") { all in Self.set(&all, id) { $0["address"] = nil } }
        } else if let v = Int(typed), v != addr(f), sent != "\(id):\(v)" {
            if (1...512).contains(v) {
                sent = "\(id):\(v)"
                apply("Change Address") { all in Self.set(&all, id) { $0["address"] = v } }
            } else { address = addr(f).map(String.init) ?? "" }
        }
        let new = name.trimmingCharacters(in: .whitespaces)
        if new.isEmpty { name = id } else if new != id, sent != "\(id)>\(new)" { sent = "\(id)>\(new)"; rename(id, new) }
    }

    private func sync() {
        if let f = selected.first, selected.count == 1 {
            name = string(f, "id")
            address = addr(f).map(String.init) ?? ""
        }
    }

    // MARK: one fixture

    @ViewBuilder
    private func single(_ f: [String: Any]) -> some View {
        let id = string(f, "id"), key = string(f, "fixture"), def = definition(key)
        let u = int(f, "universe", 1), a = addr(f), n = footprint(f)
        SwiftUI.Section(def?.name ?? key) {
            HStack {
                TextField("Name", text: $name)
                    .focused($focus, equals: .name)
                    .onSubmit { commit(ids) }
                    .help("The fixture's name in the set (renaming keeps where it hangs on your rigs). Saved on Return or when you leave the field.")
                if name != id {
                    Button("Rename") { sent = ""; commit(ids) }.buttonStyle(.borderedProminent)
                }
            }
            Picker("DMX mode", selection: Binding(get: { string(f, "mode") }, set: { m in
                apply("Change Mode") { all in Self.set(&all, id) { $0["mode"] = m } }
            })) {
                ForEach((def?.modes.keys.sorted() ?? []), id: \.self) { m in
                    Text("\(m) · \(def?.channels(m) ?? 0) ch").tag(m)
                }
            }
        }
        SwiftUI.Section("DMX patch") {
            Stepper("Universe \(u)", value: Binding(get: { u }, set: { nu in
                apply("Change Universe") { all in Self.set(&all, id) { $0["universe"] = nu } }
            }), in: 1...64)
            let text = address.trimmingCharacters(in: .whitespaces)
            let typed = Int(text).flatMap { (1...512).contains($0) ? $0 : nil }
            let edited = text.isEmpty ? a != nil : typed != nil && typed != a
            HStack {
                TextField("Start address", text: $address, prompt: Text("not set"))
                    .focused($focus, equals: .address)
                    .onSubmit { commit(ids) }
                    .help("The address set on the fixture itself. Saved on Return, when you leave the field, or with Save; empty: none yet")
                if edited {
                    Button("Save") { sent = ""; commit(ids) }.buttonStyle(.borderedProminent)
                    Button("Revert") { address = a.map(String.init) ?? "" }
                } else {
                    Button("Next Free") {
                        if let v = free(universe: u, count: n, except: [id]) {
                            address = String(v)
                            apply("Change Address") { all in Self.set(&all, id) { $0["address"] = v } }
                        }
                    }
                    .help("The first address in this universe where its \(n) channels fit")
                }
            }
            if Int(address) != nil && typed == nil {
                Label("A start address is 1 to 512.", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            }
            if let shown = text.isEmpty ? nil : typed ?? a {   // what is typed, checked before it is saved
                LabeledContent("Channels", value: "\(u).\(String(format: "%03d", shown)) – \(u).\(String(format: "%03d", shown + n - 1))"
                               + (shown != a ? " (not saved yet)" : ""))
                if shown + n - 1 > 512 {
                    Label("It doesn't fit in the universe: \(shown + n - 1 - 512) channels past 512.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                let c = clashes(universe: u, from: shown, count: n, except: [id])
                if !c.isEmpty {
                    Label("Overlaps \(c.joined(separator: ", ")). It is saved anyway, so you can move the others next.",
                          systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
                }
            } else {
                Label("No start address yet: it plays in the visualiser only until it has one. Type the address set on the fixture, or Next Free.",
                      systemImage: "info.circle")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
        if def?.isMoving == true {
            SwiftUI.Section("Motion") {
                Toggle("Invert pan", isOn: Binding(get: { f["pan_invert"] as? Bool ?? false }, set: { v in
                    apply("Invert Pan") { all in Self.set(&all, id) { $0["pan_invert"] = v ? true : nil } }
                }))
                Toggle("Invert tilt", isOn: Binding(get: { f["tilt_invert"] as? Bool ?? false }, set: { v in
                    apply("Invert Tilt") { all in Self.set(&all, id) { $0["tilt_invert"] = v ? true : nil } }
                }))
            }
        }
    }

    // MARK: several

    @ViewBuilder
    private func several(_ sel: [[String: Any]]) -> some View {
        let keys = Set(sel.map { string($0, "fixture") })
        let ids = Set(sel.map { string($0, "id") })
        let universes = Set(sel.map { int($0, "universe", 1) })
        SwiftUI.Section("\(sel.count) fixtures") {
            if keys.count == 1, let key = keys.first, let def = definition(key) {
                let modes = Set(sel.map { string($0, "mode") })
                Picker("DMX mode", selection: Binding(get: { modes.count == 1 ? modes.first! : "" }, set: { m in
                    apply("Change Modes") { all in for id in ids { Self.set(&all, id) { $0["mode"] = m } } }
                })) {
                    if modes.count > 1 { Text("Mixed").tag("") }
                    ForEach(def.modes.keys.sorted(), id: \.self) { m in Text("\(m) · \(def.channels(m)) ch").tag(m) }
                }
            }
            Stepper(universes.count == 1 ? "Universe \(universes.first!)" : "Universe (mixed)",
                    value: Binding(get: { universes.min() ?? 1 }, set: { nu in
                        apply("Change Universe") { all in for id in ids { Self.set(&all, id) { $0["universe"] = nu } } }
                    }), in: 1...64)
        }
        SwiftUI.Section {
            HStack {
                TextField("From address", text: $firstAddress)
                Button("Patch in a Row") { patchInRow(sel, from: Int(firstAddress) ?? 1) }
            }
        } header: {
            Text("Addresses")
        } footer: {
            Text("One after another from that address (in the order shown), in their universe, around the other fixtures; a fixture that doesn't fit goes on in the next universe.")
        }
    }

    private func patchInRow(_ sel: [[String: Any]], from start: Int) {
        let ids = Set(sel.map { string($0, "id") })
        var u = sel.map { int($0, "universe", 1) }.min() ?? 1
        var a = max(1, start)
        var placed: [String: (Int, Int)] = [:]
        var taken: [(u: Int, a: Int, n: Int)] = []
        for f in sel {
            let n = footprint(f)
            while true {
                let clash = !clashes(universe: u, from: a, count: n, except: ids).isEmpty
                    || taken.contains { $0.u == u && $0.a <= a + n - 1 && a <= $0.a + $0.n - 1 }
                if a + n - 1 > 512 { u += 1; a = 1; continue }
                if clash { a += 1; continue }
                break
            }
            placed[string(f, "id")] = (u, a)
            taken.append((u, a, n))
            a += n
        }
        apply("Patch in a Row") { all in
            for (id, p) in placed { Self.set(&all, id) { $0["universe"] = p.0; $0["address"] = p.1 } }
        }
    }

    private static func set(_ all: inout [[String: Any]], _ id: String, _ body: (inout [String: Any]) -> Void) {
        guard let i = all.firstIndex(where: { $0["id"] as? String == id }) else { return }
        body(&all[i])
    }
}
