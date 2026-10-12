// "Start with a DJ laptop": VirtualDJ runs on another computer with Amadeus Link; pick it, type its code.
import AmadeusKit
import SwiftUI

struct DJLinkSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var chosen: String?
    @State private var code = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: "laptopcomputer.and.arrow.down").font(.largeTitle).foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Start with a DJ Laptop").font(.title2.weight(.semibold))
                    Text("The DJ software runs on the DJ’s laptop with Amadeus Link switched on. The show here follows that mix.")
                        .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            GroupBox("Nearby DJs") {
                VStack(alignment: .leading, spacing: 6) {
                    if model.djs.found.isEmpty {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text("Looking… Is Amadeus Link switched on on the DJ laptop, on the same network?")
                                .font(.callout).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 6)
                    }
                    ForEach(model.djs.found) { dj in
                        Button { chosen = dj.name } label: {
                            HStack {
                                Image(systemName: chosen == dj.name ? "largecircle.fill.circle" : "circle")
                                    .foregroundStyle(.tint)
                                Image(systemName: "laptopcomputer")
                                Text(dj.name)
                                Spacer()
                            }
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                        .padding(.vertical, 3)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
            }
            HStack {
                Text("Pairing code")
                TextField("0000", text: $code)
                    .font(.title3.monospacedDigit())
                    .frame(width: 90)
                    .onChange(of: code) { code = String(code.filter(\.isNumber).prefix(4)) }
                Text("as shown in Amadeus Link on the DJ laptop").font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Connect and Start") {
                    if let chosen { model.startLive(dj: chosen, code: code) }
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(chosen == nil || code.count != 4)
            }
        }
        .padding(22)
        .frame(width: 520)
        .onAppear {
            model.djs.start()
            if model.djs.found.count == 1 { chosen = model.djs.found[0].name }
        }
        .onChange(of: model.djs.found) { if chosen == nil, model.djs.found.count == 1 { chosen = model.djs.found[0].name } }
        .onDisappear { model.djs.stop() }
    }
}
