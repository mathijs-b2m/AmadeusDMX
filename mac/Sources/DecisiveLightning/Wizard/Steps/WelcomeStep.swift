// Wizard: what the app does.
import DecisiveKit
import SwiftUI

struct WelcomeStep: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            StepHeader(symbol: "bolt.circle.fill", title: "Decisive Lightning",
                       text: "An AI lighting director for DJ sets. It listens to the music, plans every phrase and drop, and runs your lights live with VirtualDJ.")
            Feature(symbol: "light.overhead.right", title: "Your rig",
                    text: "Moving heads, pars, lasers, blinders and an LED wall, from the QLC+ and Open Fixture libraries.")
            Feature(symbol: "wand.and.stars", title: "A director, not a sound-to-light",
                    text: "Builds-ups, drops and breakdowns get their own looks, with restraint early in a track.")
            Feature(symbol: "dot.radiowaves.left.and.right", title: "Live with VirtualDJ",
                    text: "The DecisiveLink plugin tells the engine what plays; the lights follow the mix.")
        }
    }
}

struct Feature: View {
    var symbol: String
    var title: String
    var text: String
    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol).font(.title2).foregroundStyle(.tint).frame(width: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(text).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
