// A new rig (a venue): start from the structure that's there (an empty room, two stands, a truss over the
// booth, a club, a concert stage, a round truss), size it, and then mount your set on it: automatically or by hand.
import AmadeusKit
import SwiftUI

enum RigTemplate: String, CaseIterable, Identifiable {
    case floor, stands, booth, club, stage, ring   // amadeus/rig/templates.py
    var id: String { rawValue }
    var title: String {
        switch self {
        case .floor: "Empty Room"
        case .stands: "Two Stands"
        case .booth: "Truss over the Booth"
        case .club: "Club"
        case .stage: "Concert Stage"
        case .ring: "Round Truss"
        }
    }
    var detail: String {
        switch self {
        case .floor: "Fixtures on the floor and on tripods."
        case .stands: "A mobile DJ: a lighting stand left and right of the booth."
        case .booth: "One truss over the DJ."
        case .club: "Two trusses over the booth, front and back."
        case .stage: "Two overhead trusses, a low one at the back, a tower each side."
        case .ring: "A circle over the booth, a half circle behind it: heads play crowns, cones and twisters."
        }
    }
    /// width, truss height, room depth (m)
    var size: (Double, Double, Double) {
        switch self {
        case .floor: (4, 2.5, 8)
        case .stands: (5, 2.5, 10)
        case .booth: (6, 3.5, 12)
        case .club: (10, 4.5, 15)
        case .stage: (16, 7, 25)
        case .ring: (10, 4.5, 15)
        }
    }
}

/// The rig seen from the audience: the floor, the booth, trusses, towers.
struct RigSketch: View {
    let template: RigTemplate
    var body: some View {
        Canvas { ctx, size in
            let w = size.width, h = size.height, floor = h - 6
            let line = GraphicsContext.Shading.color(.secondary)
            let truss = GraphicsContext.Shading.color(.accentColor)
            ctx.fill(Path(CGRect(x: 4, y: floor, width: w - 8, height: 2)), with: line)
            ctx.fill(Path(roundedRect: CGRect(x: w / 2 - 12, y: floor - 12, width: 24, height: 12), cornerRadius: 2), with: line)
            func bar(_ x: CGFloat, _ y: CGFloat, _ len: CGFloat) {
                ctx.fill(Path(roundedRect: CGRect(x: x, y: y, width: len, height: 4), cornerRadius: 1), with: truss)
            }
            func tower(_ x: CGFloat, _ top: CGFloat) {
                ctx.fill(Path(roundedRect: CGRect(x: x, y: top, width: 4, height: floor - top), cornerRadius: 1), with: truss)
            }
            switch template {
            case .floor:
                for x in [w * 0.25, w * 0.75] {
                    var p = Path(); p.move(to: CGPoint(x: x, y: floor)); p.addLine(to: CGPoint(x: x, y: floor - 18))
                    ctx.stroke(p, with: line, lineWidth: 1.5)
                }
            case .stands:
                tower(w * 0.2, h * 0.35); tower(w * 0.8 - 4, h * 0.35)
            case .booth:
                bar(w * 0.2, h * 0.25, w * 0.6)
            case .club:
                bar(w * 0.12, h * 0.22, w * 0.76); bar(w * 0.18, h * 0.12, w * 0.64)
            case .stage:
                bar(w * 0.1, h * 0.2, w * 0.8); bar(w * 0.14, h * 0.1, w * 0.72); bar(w * 0.22, floor - 22, w * 0.56)
                tower(6, h * 0.18); tower(w - 10, h * 0.18)
            case .ring:  // seen a little from below: a flat ellipse, the half circle a wider arc behind it
                var back = Path()
                back.addArc(center: CGPoint(x: w / 2, y: h * 0.2), radius: w * 0.36, startAngle: .degrees(195),
                            endAngle: .degrees(345), clockwise: false)
                ctx.stroke(back, with: truss, lineWidth: 3)
                ctx.stroke(Path(ellipseIn: CGRect(x: w * 0.27, y: h * 0.2, width: w * 0.46, height: h * 0.16)), with: truss, lineWidth: 3.5)
            }
        }
        .frame(height: 64)
    }
}

struct NewRigSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var template: RigTemplate = .club
    @State private var name = "club"
    @State private var width = 10.0
    @State private var height = 4.5
    @State private var depth = 15.0
    @State private var screen = false
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("New Rig").font(.title2.weight(.semibold))
                Text("A rig is the venue: the stage and what your fixtures hang on. Start from what's there; you can move and add trusses afterwards.")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 10)], spacing: 10) {
                ForEach(RigTemplate.allCases) { t in
                    Button { pick(t) } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            RigSketch(template: t)
                            Text(t.title).font(.headline)
                            Text(t.detail).font(.caption).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading)
                        .background(.background.secondary, in: .rect(cornerRadius: 12))
                        .overlay { RoundedRectangle(cornerRadius: 12).strokeBorder(template == t ? Color.accentColor : .clear, lineWidth: 2) }
                        .contentShape(.rect(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                }
            }
            Form {
                TextField("Name", text: $name)
                SizeRow(title: "Stage width", value: $width, range: 2...30, step: 0.5)
                if template != .floor { SizeRow(title: template == .stands ? "Stand height" : "Truss height", value: $height, range: 2...12, step: 0.5) }
                SizeRow(title: "Room depth", value: $depth, range: 4...40, step: 1)
                Toggle("LED wall behind the DJ", isOn: $screen)
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            .frame(height: template == .floor ? 190 : 230)
            HStack {
                if let error { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout) }
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Create Rig") { Task { await create() } }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || busy)
            }
        }
        .padding(22)
        .frame(width: 700)
        .onAppear { pick(.club) }
    }

    private func pick(_ t: RigTemplate) {
        let wasDefault = RigTemplate.allCases.contains { $0.rawValue == name } || name.isEmpty
        template = t
        (width, height, depth) = t.size
        screen = t == .club || t == .stage
        if wasDefault { name = unique(t.rawValue) }
    }

    private func unique(_ base: String) -> String {
        var n = base, i = 2
        while model.rigs.contains(where: { $0.name == n }) { n = "\(base)\(i)"; i += 1 }
        return n
    }

    private func create() async {
        busy = true
        defer { busy = false }
        let rigName = name.lowercased().replacingOccurrences(of: #"[^a-z0-9_-]+"#, with: "-", options: .regularExpression)
        do {
            guard await model.ensureSetupService() else { throw SetupAPIError.notRunning }
            try await model.api.createRig(name: rigName, template: template.rawValue, width: width, height: height,
                                          depth: depth, screen: screen)
            model.reloadSets()
            dismiss()
            model.section = .rig
            model.editingRig = rigName   // open it on the Rigs page; sets are placed on it there
            model.editingRigSet = ""
            model.section = .rig
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// "Mount your set on this rig?": automatically (a sensible start), or by hand in the rig editor.
struct MountPromptSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let rig: String
    let set: String
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        let m = model.workspace?.mounted(rig: rig, set: set) ?? (placed: 0, total: 0)
        let waiting = m.total - m.placed
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 14) {
                Image(systemName: "square.split.bottomrightquarter").font(.system(size: 34)).foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Mount “\(set)” on “\(rig)”?").font(.title2.weight(.semibold))
                    Text(m.placed == 0 ? "None of the set's \(m.total) fixtures hang on this rig yet."
                         : "\(waiting) of the set's \(m.total) fixtures don't hang on this rig yet.")
                        .foregroundStyle(.secondary)
                }
            }
            choice(symbol: "wand.and.stars", title: "Auto-Mount",
                   text: "Moving heads under the trusses, lasers high at the back, strobes and blinders on the front, bars and pars on the floor. Mirrored, model by model. Move anything afterwards.",
                   prominent: true) { Task { await auto() } }
            choice(symbol: "hand.draw", title: "I’ll Place Them Myself",
                   text: "They wait on the floor in front of the stage: drag them onto the trusses one by one, or a whole group at once.",
                   prominent: false) {
                dismiss(); model.section = .rig
            }
            HStack {
                if let error { Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.callout) }
                Spacer()
                if busy { ProgressView().controlSize(.small) }
                Button("Later") { dismiss() }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(22)
        .frame(width: 520)
    }

    private func choice(symbol: String, title: String, text: String, prominent: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: symbol).font(.title2).frame(width: 30)
                    .foregroundStyle(prominent ? Color.accentColor : Color.secondary)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.headline)
                    Text(text).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(prominent ? AnyShapeStyle(.tint.opacity(0.12)) : AnyShapeStyle(.background.secondary), in: .rect(cornerRadius: 12))
            .contentShape(.rect(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .disabled(busy)
    }

    private func auto() async {
        busy = true
        defer { busy = false }
        do {
            try await model.autoMount(rig: rig, set: set)
            dismiss()
            model.section = .rig
        } catch {
            self.error = error.localizedDescription
        }
    }
}
