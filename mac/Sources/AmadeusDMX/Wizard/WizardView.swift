// "Set Up a Rig": a step-by-step assistant for a new set (and for the first launch).
import AmadeusKit
import SwiftUI

struct WizardView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var w = WizardModel()
    @State private var savedNote: String?   // after Save and Close: what was saved, where to go on

    var body: some View {
        HStack(spacing: 0) {
            StepRail(current: w.step)
                .frame(width: 190)
                .background(.background.secondary)
            VStack(spacing: 0) {
                ScrollView {
                    content
                        .padding(.horizontal, 36)
                        .padding(.top, 40)
                        .padding(.bottom, 20)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                Divider()
                bottomBar
                    .padding(.horizontal, 20)
                    .padding(.vertical, 14)
            }
        }
        .frame(width: 820, height: 600)
        .task(id: w.step) { await enter(w.step) }
        .alert("Saved. Continue Later", isPresented: Binding(get: { savedNote != nil }, set: { if !$0 { savedNote = nil } })) {
            Button("Close") { model.section = w.planned.isEmpty ? .dmx : .set; dismiss() }
        } message: {
            Text(LocalizedStringKey(savedNote ?? ""))
        }
    }

    @ViewBuilder
    private var content: some View {
        switch w.step {
        case .welcome: WelcomeStep()
        case .engine: EngineStep()
        case .fixtures: FixturesStep(w: w)
        case .network: NetworkStep(w: w)
        case .rig: RigStep(w: w)
        case .director: DirectorStep(w: w)
        case .review: ReviewStep(w: w)
        case .done: DoneStep(w: w)
        }
    }

    private var bottomBar: some View {
        HStack {
            if w.creating {
                ProgressView().controlSize(.small)
                Text(w.progress).font(.callout).foregroundStyle(.secondary)
            } else if let e = w.error {
                Label(e, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(.red).lineLimit(2)
            }
            Spacer()
            if ![.welcome, .engine, .review, .done].contains(w.step) {
                // never trapped: what is chosen so far is saved, the pages take it from there
                Button(w.hasSomethingToSave ? "Save and Close" : "Close") {
                    guard w.hasSomethingToSave else { dismiss(); return }
                    Task { if let note = await w.saveAndClose(model) { savedNote = note } }
                }
                .disabled(w.creating)
                .help(w.hasSomethingToSave ? "Save the DMX output and the fixtures chosen so far, and go on later on the pages" : "Close the assistant")
                Spacer().frame(width: 12)
            }
            if w.step != .welcome && w.step != .done {
                Button("Back") { w.step = WizardStep(rawValue: w.step.rawValue - 1) ?? .welcome }
                    .disabled(w.creating)
            }
            switch w.step {
            case .review:
                Button(w.autoMount ? "Create and Mount" : "Create") { Task { await w.create(model) } }
                    .buttonStyle(.glassProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(!w.canContinue || w.creating)
            case .done:
                Button(w.autoMount ? "Open the Show" : "Place the Fixtures") {
                    model.section = w.autoMount ? .show : .rig
                    dismiss()
                }
                .buttonStyle(.glassProminent)
                .keyboardShortcut(.defaultAction)
            default:
                Button(w.step == .welcome ? "Get Started" : "Continue") { next() }
                    .buttonStyle(.glassProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(!w.canContinue || (w.step == .engine && model.workspace == nil))
            }
        }
    }

    private func next() {
        var s = WizardStep(rawValue: w.step.rawValue + 1) ?? .done
        if s == .engine, model.workspace?.isValid == true, w.step == .welcome, !model.sets.isEmpty { s = .network }
        w.step = s
    }

    private func enter(_ s: WizardStep) async {
        w.error = nil
        switch s {
        case .fixtures, .network, .director:
            _ = await model.ensureSetupService()
            if s == .director, w.directors.isEmpty {
                w.directors = (try? await model.api.directors()) ?? []
                if let ai = w.directors.first(where: { $0.value == "openai" && $0.available }) { w.director = ai.value }
            }
        default: break
        }
    }
}

struct StepRail: View {
    var current: WizardStep

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 20, height: 20)
                Text("Set Up").font(.headline)
            }
            .padding(.bottom, 18)
            ForEach(WizardStep.allCases.filter { $0 != .welcome }, id: \.self) { s in
                HStack(spacing: 10) {
                    ZStack {
                        Circle().fill(s.rawValue < current.rawValue ? Color.accentColor
                                      : s == current ? Color.accentColor.opacity(0.25) : Color.secondary.opacity(0.15))
                        if s.rawValue < current.rawValue {
                            Image(systemName: "checkmark").font(.caption2.weight(.bold)).foregroundStyle(.white)
                        } else {
                            Text("\(s.rawValue)").font(.caption2.weight(.semibold))
                                .foregroundStyle(s == current ? Color.accentColor : .secondary)
                        }
                    }
                    .frame(width: 20, height: 20)
                    Text(s.title)
                        .font(.callout.weight(s == current ? .semibold : .regular))
                        .foregroundStyle(s.rawValue <= current.rawValue ? .primary : .secondary)
                }
                .padding(.vertical, 5)
            }
            Spacer()
        }
        .padding(20)
        .frame(maxHeight: .infinity, alignment: .top)
    }
}

struct StepHeader: View {
    var symbol: String?   // nil: the app icon
    var title: String
    var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let symbol {
                Image(systemName: symbol)
                    .font(.system(size: 34))
                    .foregroundStyle(.tint)
                    .symbolRenderingMode(.hierarchical)
            } else {
                Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 56, height: 56)
            }
            Text(title).font(.largeTitle.weight(.bold))
            Text(text).font(.title3).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 20)
    }
}
