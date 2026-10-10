// Wizard: the kind of venue and the size of the stage.
import DecisiveKit
import SwiftUI

struct VenueStep: View {
    @Bindable var w: WizardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(symbol: "building.2.fill", title: "Where Do You Play?",
                       text: "This sets the size of the stage and how the lights are hung. You can fine-tune everything later.")
            HStack(spacing: 12) {
                ForEach(Venue.allCases) { v in
                    Button { w.venue = v } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Image(systemName: v.symbol).font(.title)
                            Text(v.title).font(.headline)
                            Text(v.detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                        .padding(14)
                        .frame(maxWidth: .infinity, minHeight: 140, alignment: .topLeading)
                        .background(.background.secondary, in: .rect(cornerRadius: 14))
                        .overlay { RoundedRectangle(cornerRadius: 14).strokeBorder(w.venue == v ? Color.accentColor : .clear, lineWidth: 2) }
                        .contentShape(.rect(cornerRadius: 14))
                    }
                    .buttonStyle(.plain)
                }
            }
            Form {
                SizeRow(title: "Stage width", value: $w.width, range: 2...24, step: 0.5)
                SizeRow(title: "Truss height", value: $w.height, range: 2...12, step: 0.5)
                SizeRow(title: "Room depth", value: $w.depth, range: 4...40, step: 1)
                Toggle("LED wall behind the DJ", isOn: $w.ledWall)
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            .frame(height: 220)
        }
    }
}

struct SizeRow: View {
    var title: String
    @Binding var value: Double
    var range: ClosedRange<Double>
    var step: Double

    var body: some View {
        LabeledContent(title) {
            HStack {
                Slider(value: $value, in: range, step: step)
                Text(step < 1 ? String(format: "%.1f m", value) : "\(Int(value)) m")
                    .monospacedDigit().frame(width: 56, alignment: .trailing)
            }
        }
    }
}
