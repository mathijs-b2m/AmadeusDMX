// Updates with Sparkle: the app checks the release feed (SUFeedURL in Info.plist, set by build-app.sh for a
// release) and installs updates signed with the release key (SUPublicEDKey). Off in a development build.
//
// Opt-in: Sparkle asks on the second launch whether to check automatically (Settings › General changes it). Never
// during a show: no background check while the lights run, and an update you start installing then waits until
// the show stops. One downloaded in the background is installed when you quit.
import AppKit
import Observation
import Sparkle

@MainActor
@Observable
final class Updates: NSObject, SPUUpdaterDelegate {
    /// nil in a development build (no feed or key in Info.plist).
    @ObservationIgnored private var controller: SPUStandardUpdaterController?
    @ObservationIgnored private var observation: NSKeyValueObservation?
    /// Whether a show is running (the lights must not be interrupted).
    @ObservationIgnored var showRunning: () -> Bool = { false }
    @ObservationIgnored private var pendingInstall: (() -> Void)?

    private(set) var canCheck = false
    /// An update waits for the show to stop.
    private(set) var waitingForShow = false

    var isAvailable: Bool { controller != nil }

    override init() {
        super.init()
        let info = Bundle.main.infoDictionary ?? [:]
        guard info["SUFeedURL"] != nil, info["SUPublicEDKey"] != nil else { return }
        let c = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)
        controller = c
        observation = c.updater.observe(\.canCheckForUpdates, options: [.initial, .new]) { [weak self] u, _ in
            let can = u.canCheckForUpdates
            Task { @MainActor in self?.canCheck = can }
        }
    }

    func checkForUpdates() { controller?.checkForUpdates(nil) }

    var checksAutomatically: Bool {
        get { controller?.updater.automaticallyChecksForUpdates ?? false }
        set { controller?.updater.automaticallyChecksForUpdates = newValue }
    }

    var installsAutomatically: Bool {
        get { controller?.updater.automaticallyDownloadsUpdates ?? false }
        set { controller?.updater.automaticallyDownloadsUpdates = newValue }
    }

    var lastChecked: Date? { controller?.updater.lastUpdateCheckDate }

    /// The show stopped: an update that waited for it installs now (and the app relaunches).
    func showStopped() {
        guard let install = pendingInstall else { return }
        pendingInstall = nil
        waitingForShow = false
        install()
    }

    // MARK: SPUUpdaterDelegate

    nonisolated func updater(_ updater: SPUUpdater, mayPerform updateCheck: SPUUpdateCheck) throws {
        let busy = MainActor.assumeIsolated { updateCheck == .updatesInBackground && showRunning() }
        if busy {
            throw NSError(domain: "AmadeusDMX", code: 1, userInfo: [NSLocalizedDescriptionKey: "A show is running"])
        }
    }

    nonisolated func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                             untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        MainActor.assumeIsolated {
            guard showRunning() else { return false }
            pendingInstall = installHandler
            waitingForShow = true
            return true
        }
    }
}
