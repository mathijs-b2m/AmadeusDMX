// Updates with Sparkle, for Amadeus DMX and Amadeus Link: the app checks its release feed (SUFeedURL in
// Info.plist, set by build-app.sh for a release) and installs updates signed with the release key (SUPublicEDKey).
// Off in a development build.
//
// Opt-in: Sparkle asks on the second launch whether to check automatically. Never while the app is busy (Amadeus
// DMX: a show runs; Amadeus Link: a lighting computer is connected): no background check then, and an update you
// start installing waits until it's idle again. One downloaded in the background is installed when you quit.
import AppKit
import Observation
import Sparkle

@MainActor
@Observable
public final class Updates: NSObject, SPUUpdaterDelegate {
    /// nil in a development build (no feed or key in Info.plist).
    @ObservationIgnored private var controller: SPUStandardUpdaterController?
    @ObservationIgnored private var observation: NSKeyValueObservation?
    /// Whether the app must not be interrupted now (a show runs, a lighting computer is connected).
    @ObservationIgnored public var isBusy: () -> Bool = { false }
    @ObservationIgnored private var pendingInstall: (() -> Void)?

    public private(set) var canCheck = false
    /// An update waits until the app is idle.
    public private(set) var waitingForIdle = false

    public var isAvailable: Bool { controller != nil }

    override public init() {
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

    public func checkForUpdates() { controller?.checkForUpdates(nil) }

    public var checksAutomatically: Bool {
        get { controller?.updater.automaticallyChecksForUpdates ?? false }
        set { controller?.updater.automaticallyChecksForUpdates = newValue }
    }

    public var installsAutomatically: Bool {
        get { controller?.updater.automaticallyDownloadsUpdates ?? false }
        set { controller?.updater.automaticallyDownloadsUpdates = newValue }
    }

    public var lastChecked: Date? { controller?.updater.lastUpdateCheckDate }

    /// The app is idle again: an update that waited installs now (and the app relaunches).
    public func becameIdle() {
        guard let install = pendingInstall else { return }
        pendingInstall = nil
        waitingForIdle = false
        install()
    }

    // MARK: SPUUpdaterDelegate

    nonisolated public func updater(_ updater: SPUUpdater, mayPerform updateCheck: SPUUpdateCheck) throws {
        let busy = MainActor.assumeIsolated { updateCheck == .updatesInBackground && isBusy() }
        if busy {
            throw NSError(domain: "AmadeusDMX", code: 1, userInfo: [NSLocalizedDescriptionKey: "Busy: checked later"])
        }
    }

    nonisolated public func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                             untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        MainActor.assumeIsolated {
            guard isBusy() else { return false }
            pendingInstall = installHandler
            waitingForIdle = true
            return true
        }
    }
}
