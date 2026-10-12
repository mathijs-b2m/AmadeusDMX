// Decisive Link: a menu bar app for the DJ's laptop. Switch it on, read the code to the lighting operator.
import SwiftUI

@main
struct DecisiveLinkApp: App {
    @State private var link = LinkServer()

    var body: some Scene {
        // a window as well as the menu bar icon: a full menu bar (or the notch) can hide the icon
        Window("Decisive Link", id: "link") {
            LinkMenu()
                .environment(link)
        }
        .windowResizability(.contentSize)
        .defaultPosition(.topTrailing)

        MenuBarExtra {
            LinkMenu()
                .environment(link)
        } label: {
            Image(systemName: !link.isOn ? "dot.radiowaves.left.and.right.slash"
                  : link.peers.isEmpty ? "dot.radiowaves.left.and.right" : "link.circle.fill")
        }
        .menuBarExtraStyle(.window)
    }
}

struct LinkMenu: View {
    @Environment(LinkServer.self) private var link

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Image(systemName: "bolt.fill").foregroundStyle(.yellow)
                Text("Decisive Link").font(.headline)
                Spacer()
                Toggle("", isOn: Binding(get: { link.isOn }, set: { link.setOn($0) }))
                    .toggleStyle(.switch)
                    .labelsHidden()
            }

            TimelineView(.periodic(from: .now, by: 1)) { _ in
                Label(link.djConnected ? "\(link.djApp) connected"
                      : "Waiting for the DJ software (VirtualDJ: DecisiveLink plugin as master effect)",
                      systemImage: link.djConnected ? "checkmark.circle.fill" : "hourglass")
                    .foregroundStyle(link.djConnected ? .green : .secondary)
                    .font(.callout)
            }
            if link.djConnected && !link.deckSummary.isEmpty {
                Text(link.deckSummary).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(4)
            }

            if link.isOn {
                VStack(spacing: 4) {
                    Text("Pairing code").font(.caption).foregroundStyle(.secondary)
                    Text(link.code)
                        .font(.system(size: 40, weight: .bold, design: .rounded).monospacedDigit())
                        .tracking(8)
                        .textSelection(.enabled)
                    Button("New Code") { link.renewCode() }.buttonStyle(.link).font(.caption)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .background(.quaternary.opacity(0.5), in: .rect(cornerRadius: 12))

                if link.peers.isEmpty {
                    Text("The lighting computer finds this laptop under “Nearby DJs” and asks for the code.")
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                } else {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Connected").font(.caption).foregroundStyle(.secondary)
                        ForEach(link.peers) { p in
                            HStack {
                                Image(systemName: "light.overhead.right").foregroundStyle(.tint)
                                Text(p.address).font(.callout)
                                Spacer()
                                Button { link.disconnect(p.id) } label: { Image(systemName: "xmark.circle.fill") }
                                    .buttonStyle(.borderless).foregroundStyle(.secondary).help("Disconnect")
                            }
                        }
                        if link.tracksServed > 0 {
                            Text("\(link.tracksServed) track\(link.tracksServed == 1 ? "" : "s") sent").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            } else {
                Text("Off: this laptop is invisible on the network.").font(.callout).foregroundStyle(.secondary)
            }

            if let e = link.error {
                Label(e, systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Divider()
            Button("Quit Decisive Link") { NSApp.terminate(nil) }
                .keyboardShortcut("q")
        }
        .padding(16)
        .frame(width: 300)
    }
}
