// Which version this app is, whether it's the newest, and the one click that updates it (Updates.swift).
// Amadeus DMX shows it in Settings › General › Updates, Amadeus Link in its menu bar window.
import SwiftUI

public struct UpdateStatusView: View {
    let updates: Updates
    let appName: String
    /// When a waiting update installs ("when the show stops").
    let whenIdle: String
    let compact: Bool

    public init(updates: Updates, appName: String, whenIdle: String, compact: Bool = false) {
        self.updates = updates
        self.appName = appName
        self.whenIdle = whenIdle
        self.compact = compact
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(appName) \(updates.version)").font(compact ? .callout : .body)
                    Text("Build \(updates.build)").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                action
            }
            status.font(compact ? .caption : .callout)
        }
        .onAppear { updates.refresh() }
    }

    @ViewBuilder private var action: some View {
        switch updates.state {
        case .available(let v):
            Button("Update to \(v)") { updates.installNewest() }
                .buttonStyle(.borderedProminent).disabled(!updates.canCheck)
                .help("Downloads \(appName) \(v) and installs it; \(appName) starts again")
        case .downloading:
            Button("Cancel") { updates.cancelInstall() }
        case .checking, .installing:
            EmptyView()
        default:
            Button { updates.refresh(force: true) } label: { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.borderless).disabled(!updates.canCheck).help("Check again")
        }
    }

    @ViewBuilder private var status: some View {
        switch updates.state {
        case .unknown:
            Label("Not checked yet", systemImage: "questionmark.circle").foregroundStyle(.secondary)
        case .checking:
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text("Checking for the newest version…").foregroundStyle(.secondary)
            }
        case .upToDate(let newest):
            Label(newest.map { $0 == updates.version ? "Up to date: \($0) is the newest" : "Up to date (newest: \($0))" } ?? "Up to date",
                  systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .available(let v):
            Label("\(v) is available: you have \(updates.version)", systemImage: "arrow.down.circle.fill")
                .foregroundStyle(.orange)
        case .downloading(let v, let share):
            VStack(alignment: .leading, spacing: 4) {
                Text("Downloading \(v)…").foregroundStyle(.secondary)
                if let share { ProgressView(value: share) } else { ProgressView().progressViewStyle(.linear) }
            }
        case .installing(let v):
            Label(updates.waitingForIdle ? "\(v) is ready: it installs \(whenIdle)" : "Installing \(v): \(appName) starts again",
                  systemImage: updates.waitingForIdle ? "clock" : "arrow.triangle.2.circlepath")
                .foregroundStyle(.secondary)
        case .failed(let message):
            Label("Couldn't check for updates: \(message)", systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
        }
    }
}
