// Wizard: the decision model (rules, OpenAI, or a local model).
import AmadeusKit
import SwiftUI

struct DirectorStep: View {
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "wand.and.stars", title: "Who Directs?",
                       text: "Every phrase of every track gets a lighting decision. The engine always starts with a quick rules plan; an AI director then takes over.")
            if w.directors.isEmpty {
                ProgressView("Asking the engine…")
            }
            ForEach(w.directors) { d in
                Button { if d.available { w.director = d.value } } label: {
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: w.director == d.value ? "largecircle.fill.circle" : "circle")
                            .foregroundStyle(d.available ? Color.accentColor : .secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(d.label).font(.headline)
                            if let n = d.note { Text(n).font(.callout).foregroundStyle(.secondary) }
                        }
                        Spacer()
                    }
                    .padding(12)
                    .background(.background.secondary, in: .rect(cornerRadius: 12))
                    .opacity(d.available ? 1 : 0.5)
                }
                .buttonStyle(.plain)
                .disabled(!d.available)
            }
        }
    }
}
