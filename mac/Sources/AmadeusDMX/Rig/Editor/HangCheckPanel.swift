// The check after hanging, over the stage: the fixture lit now (in the hang sheet's order), where it should be and
// what its beam should do, and what to do when it isn't so: the head mirrored or turned round, or the light at
// another fixture's place (the two swapped). The editor puts it right; Save keeps it.
import AmadeusKit
import SwiftUI

struct HangCheckPanel: View {
    @Environment(AppModel.self) private var model
    let editor: RigEditorModel

    var body: some View {
        if let c = editor.check, let step = c.step {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label("Check the Hang", systemImage: "checklist").font(.headline)
                    Text("\(c.index + 1) of \(c.steps.count)").foregroundStyle(.secondary).monospacedDigit()
                    Spacer()
                    Button("Done") { Task { await editor.stopCheck(model) } }
                }
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(step.label).font(.system(size: 26, weight: .bold))
                    Text("\(step.id) · \(step.model) · \(step.dmx)").foregroundStyle(.secondary).lineLimit(1)
                }
                Text(step.where).font(.callout)
                Text(step.facing.prefix(1).uppercased() + step.facing.dropFirst()).font(.callout).foregroundStyle(.secondary)
                if !step.dark.isEmpty {
                    Label("Not lit by the check (\(step.dark.trimmingCharacters(in: .punctuationCharacters))): check it by eye.",
                          systemImage: "eye").font(.callout).foregroundStyle(.orange)
                } else if !step.expect.isEmpty {
                    Label(step.expect, systemImage: "light.beacon.max").font(.callout.weight(.medium))
                } else {
                    Label("It lights up white.", systemImage: "lightbulb.max").font(.callout.weight(.medium))
                }
                if let done = c.fixed[step.id] {
                    Label("Put right: \(done). Save to keep it.", systemImage: "checkmark.circle.fill")
                        .font(.callout).foregroundStyle(.green)
                }
                HStack(spacing: 8) {
                    Button { go(c.index - 1) } label: { Label("Back", systemImage: "chevron.left") }
                        .disabled(c.index == 0)
                        .keyboardShortcut(.leftArrow, modifiers: .command)
                    Button { go(c.index + 1) } label: { Label(c.index + 1 < c.steps.count ? "Right, Next" : "Right", systemImage: "checkmark") }
                        .buttonStyle(.borderedProminent)
                        .disabled(c.index + 1 >= c.steps.count)
                        .keyboardShortcut(.rightArrow, modifiers: .command)
                        .help("It lit at its place, the right way round: the next one (⌘→)")
                    if !step.faults.isEmpty {
                        Menu("Beam Goes Elsewhere") {
                            ForEach(step.faults, id: \.self) { f in
                                Button("\(f.seen.prefix(1).uppercased() + f.seen.dropFirst()): \(Self.cause[f.fix] ?? f.fix)") {
                                    Task { await editor.fixCheck(model, f) }
                                }
                            }
                        }
                        .fixedSize()
                        .help("The head is hung turned round, or pans the other way: say where its beam goes and the app is put right")
                    }
                    Menu("Lit Somewhere Else") {
                        ForEach(c.steps.filter { $0.id != step.id }) { other in
                            Button("At \(other.label) (\(other.id))") { Task { await editor.swapCheck(model, with: other) } }
                        }
                    }
                    .fixedSize()
                    .help("The light came on at another fixture's place: the two swap places here, so you needn't swap them on the truss")
                }
                if !c.output.isEmpty {
                    Text(c.output).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .padding(14)
            .frame(maxWidth: 560, alignment: .leading)
            .glassEffect(.regular, in: .rect(cornerRadius: 16))
        }
    }

    static let cause = ["mirrored": "it pans the other way", "turned": "it is turned round",
                        "both": "turned round, and pans the other way"]

    private func go(_ i: Int) { Task { await editor.moveCheck(model, to: i) } }
}
