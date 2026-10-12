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

    private func string(_ f: [String: Any], _ k: String) -> String { f[k] as? String ?? "" }
    private func int(_ f: [String: Any], _ k: String, _ d: Int) -> Int { (f[k] as? NSNumber)?.intValue ?? d }

    private var selected: [[String: Any]] {
        fixtures.filter { ids.contains(string($0, "id")) }
            .sorted { (int($0, "universe", 1), int($0, "address", 1)) < (int($1, "universe", 1), int($1, "address", 1)) }
    }

    /// How many DMX channels a fixture takes.
    private func footprint(_ f: [String: Any]) -> Int {
        max(1, definition(string(f, "fixture"))?.channels(string(f, "mode")) ?? 1)
    }

    /// The fixtures (by id) whose channels overlap these, in a universe.
    private func clashes(universe u: Int, from a: Int, count n: Int, except: Set<String>) -> [String] {
        fixtures.filter { f in
            let id = string(f, "id")
            guard !except.contains(id), int(f, "universe", 1) == u else { return false }
            let b = int(f, "address", 1)
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
        .onChange(of: ids) { sync() }
    }

    private func sync() {
        if let f = selected.first, selected.count == 1 {
            name = string(f, "id")
            address = String(int(f, "address", 1))
        }
    }

    // MARK: one fixture

    @ViewBuilder
    private func single(_ f: [String: Any]) -> some View {
        let id = string(f, "id"), key = string(f, "fixture"), def = definition(key)
        let u = int(f, "universe", 1), a = int(f, "address", 1), n = footprint(f)
        SwiftUI.Section(def?.name ?? key) {
            TextField("Name", text: $name)
                .onSubmit { if name != id { rename(id, name) } }
                .help("The fixture's name in the set (renaming keeps where it hangs on your rigs). Press Return to rename.")
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
            HStack {
                TextField("Start address", text: $address)
                    .onSubmit {
                        if let v = Int(address), (1...512).contains(v) {
                            apply("Change Address") { all in Self.set(&all, id) { $0["address"] = v } }
                        } else { address = String(a) }
                    }
                Button("Next Free") {
                    if let v = free(universe: u, count: n, except: [id]) {
                        address = String(v)
                        apply("Change Address") { all in Self.set(&all, id) { $0["address"] = v } }
                    }
                }
                .help("The first address in this universe where its \(n) channels fit")
            }
            LabeledContent("Channels", value: "\(u).\(String(format: "%03d", a)) – \(u).\(String(format: "%03d", a + n - 1))")
            if a + n - 1 > 512 {
                Label("It doesn't fit in the universe: \(a + n - 1 - 512) channels past 512.", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
            }
            let c = clashes(universe: u, from: a, count: n, except: [id])
            if !c.isEmpty {
                Label("Overlaps \(c.joined(separator: ", "))", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
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
