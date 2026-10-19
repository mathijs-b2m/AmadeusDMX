// Updates with Sparkle, for Amadeus DMX and Amadeus Link: the app checks its release feed (SUFeedURL in
// Info.plist, set by build-app.sh for a release) and installs updates signed with the release key (SUPublicEDKey).
// Off in a development build.
//
// Opt-in: Sparkle asks on the second launch whether to check automatically. Never while the app is busy (Amadeus
// DMX: a show runs; Amadeus Link: a lighting computer is connected): no background check then, and an update you
// start installing waits until it's idle again. One downloaded in the background is installed when you quit.
//
// What the apps show (UpdateStatusView): this version, the newest in the feed, whether this one is up to date, and
// one button that downloads and installs the newer one. A quiet check (Sparkle's update information) finds the
// newest when the view appears; the button runs Sparkle's own update with every question answered yes, its
// progress in the view instead of Sparkle's windows. Check Now and a background check still show Sparkle's windows.
import AppKit
import Observation
import Sparkle

/// Where this app stands with its updates.
public enum UpdateState: Equatable, Sendable {
    /// Not checked yet.
    case unknown
    case checking
    /// This is the newest (the feed's newest version, when it said).
    case upToDate(newest: String?)
    case available(version: String)
    /// Downloading the update: the share done, nil while its size isn't known.
    case downloading(version: String, share: Double?)
    /// Downloaded, now installing: the app starts again (with waitingForIdle: once it's idle).
    case installing(version: String)
    case failed(String)
}

@MainActor
@Observable
public final class Updates: NSObject, SPUUpdaterDelegate {
    /// nil in a development build (no feed or key in Info.plist).
    @ObservationIgnored private var updater: SPUUpdater?
    @ObservationIgnored private var driver: OneClickDriver?
    @ObservationIgnored private var observation: NSKeyValueObservation?
    /// Whether the app must not be interrupted now (a show runs, a lighting computer is connected).
    @ObservationIgnored public var isBusy: () -> Bool = { false }
    @ObservationIgnored private var pendingInstall: (() -> Void)?
    @ObservationIgnored private var lastRefresh: Date?

    public private(set) var canCheck = false
    /// An update waits until the app is idle.
    public private(set) var waitingForIdle = false
    public private(set) var state = UpdateState.unknown

    /// The version people see (1.0.5) and the build number Sparkle compares (the commit count).
    public let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    public let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"

    public var isAvailable: Bool { updater != nil }

    override public init() {
        super.init()
        let info = Bundle.main.infoDictionary ?? [:]
        guard info["SUFeedURL"] != nil, info["SUPublicEDKey"] != nil else { return }
        let d = OneClickDriver(standard: SPUStandardUserDriver(hostBundle: .main, delegate: nil))
        d.updates = self
        let u = SPUUpdater(hostBundle: .main, applicationBundle: .main, userDriver: d, delegate: self)
        do { try u.start() } catch { return }  // a broken feed setting: no updates, the app goes on
        updater = u
        driver = d
        observation = u.observe(\.canCheckForUpdates, options: [.initial, .new]) { [weak self] u, _ in
            let can = u.canCheckForUpdates
            Task { @MainActor in self?.canCheck = can }
        }
    }

    /// Check Now: Sparkle's own windows say what it finds.
    public func checkForUpdates() { updater?.checkForUpdates() }

    /// A quiet check for what's newest (nothing shown but `state`): at most every five minutes unless forced,
    /// never while an update is on its way.
    public func refresh(force: Bool = false) {
        guard let updater, updater.canCheckForUpdates, !updater.sessionInProgress else { return }
        switch state {
        case .checking, .downloading, .installing: return
        default: break
        }
        if !force, let last = lastRefresh, Date().timeIntervalSince(last) < 300 { return }
        lastRefresh = Date()
        state = .checking
        updater.checkForUpdateInformation()
    }

    /// The one click: download and install the newest (after the show, if one runs). The app starts again.
    public func installNewest() {
        guard let updater, let driver, updater.canCheckForUpdates, case .available(let v) = state else { return }
        driver.oneClick = true
        state = .downloading(version: v, share: nil)
        updater.checkForUpdates()
    }

    /// Stops a download the one click started.
    public func cancelInstall() { driver?.cancel() }

    public var checksAutomatically: Bool {
        get { updater?.automaticallyChecksForUpdates ?? false }
        set { updater?.automaticallyChecksForUpdates = newValue }
    }

    public var installsAutomatically: Bool {
        get { updater?.automaticallyDownloadsUpdates ?? false }
        set { updater?.automaticallyDownloadsUpdates = newValue }
    }

    public var lastChecked: Date? { updater?.lastUpdateCheckDate }

    /// The app is idle again: an update that waited installs now (and the app relaunches).
    public func becameIdle() {
        guard let install = pendingInstall else { return }
        pendingInstall = nil
        waitingForIdle = false
        install()
    }

    fileprivate func set(_ s: UpdateState) { state = s }

    // MARK: SPUUpdaterDelegate

    nonisolated public func updater(_ updater: SPUUpdater, mayPerform updateCheck: SPUUpdateCheck) throws {
        let busy = MainActor.assumeIsolated { updateCheck == .updatesInBackground && isBusy() }
        if busy {
            throw NSError(domain: "AmadeusDMX", code: 1, userInfo: [NSLocalizedDescriptionKey: "Busy: checked later"])
        }
    }

    nonisolated public func updater(_ updater: SPUUpdater, didFindValidUpdate item: SUAppcastItem) {
        let v = item.displayVersionString
        MainActor.assumeIsolated {
            if driver?.oneClick != true { state = .available(version: v) }
        }
    }

    nonisolated public func updaterDidNotFindUpdate(_ updater: SPUUpdater, error: any Error) {
        let newest = ((error as NSError).userInfo[SPULatestAppcastItemFoundKey] as? SUAppcastItem)?.displayVersionString
        MainActor.assumeIsolated { state = .upToDate(newest: newest) }
    }

    nonisolated public func updater(_ updater: SPUUpdater, didFinishUpdateCycleFor updateCheck: SPUUpdateCheck,
                                    error: (any Error)?) {
        let e = error as NSError?
        let message = e?.localizedDescription
        let quiet = e?.code == Int(SUError.noUpdateError.rawValue) || e?.code == Int(SUError.installationCanceledError.rawValue)
        MainActor.assumeIsolated {
            driver?.oneClick = false
            if let message, !quiet, updateCheck == .updateInformation { state = .failed(message) }
            if state == .checking { state = .unknown }
            // a one click that stopped before installing (cancelled, failed to download): offer it again
            if case .downloading(let v, _) = state { state = .available(version: v) }
        }
    }

    nonisolated public func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                             untilInvokingBlock installHandler: @escaping () -> Void) -> Bool {
        let v = item.displayVersionString
        return MainActor.assumeIsolated {
            guard isBusy() else { return false }
            pendingInstall = installHandler
            waitingForIdle = true
            state = .installing(version: v)
            return true
        }
    }
}

/// Sparkle's standard windows, except during the one click: then every question is answered yes and the
/// progress goes to `Updates.state`.
@MainActor
final class OneClickDriver: NSObject, SPUUserDriver {
    let standard: SPUStandardUserDriver
    weak var updates: Updates?
    var oneClick = false
    private var cancellation: (() -> Void)?
    private var version = ""
    private var expected: UInt64 = 0
    private var received: UInt64 = 0

    init(standard: SPUStandardUserDriver) { self.standard = standard }

    func cancel() {
        guard oneClick, let c = cancellation else { return }
        cancellation = nil
        c()
    }

    func show(_ request: SPUUpdatePermissionRequest, reply: @escaping (SUUpdatePermissionResponse) -> Void) {
        standard.show(request, reply: reply)
    }

    func showUserInitiatedUpdateCheck(cancellation: @escaping () -> Void) {
        if oneClick { self.cancellation = cancellation } else { standard.showUserInitiatedUpdateCheck(cancellation: cancellation) }
    }

    func showUpdateFound(with appcastItem: SUAppcastItem, state: SPUUserUpdateState, reply: @escaping (SPUUserUpdateChoice) -> Void) {
        guard oneClick else { return standard.showUpdateFound(with: appcastItem, state: state, reply: reply) }
        version = appcastItem.displayVersionString
        updates?.set(.downloading(version: version, share: nil))
        reply(.install)
    }

    func showUpdateReleaseNotes(with downloadData: SPUDownloadData) {
        if !oneClick { standard.showUpdateReleaseNotes(with: downloadData) }
    }

    func showUpdateReleaseNotesFailedToDownloadWithError(_ error: any Error) {
        if !oneClick { standard.showUpdateReleaseNotesFailedToDownloadWithError(error) }
    }

    func showUpdateNotFoundWithError(_ error: any Error, acknowledgement: @escaping () -> Void) {
        if oneClick { acknowledgement() } else { standard.showUpdateNotFoundWithError(error, acknowledgement: acknowledgement) }
    }

    func showUpdaterError(_ error: any Error, acknowledgement: @escaping () -> Void) {
        guard oneClick else { return standard.showUpdaterError(error, acknowledgement: acknowledgement) }
        updates?.set(.failed(error.localizedDescription))
        acknowledgement()
    }

    func showDownloadInitiated(cancellation: @escaping () -> Void) {
        guard oneClick else { return standard.showDownloadInitiated(cancellation: cancellation) }
        self.cancellation = cancellation
        expected = 0
        received = 0
    }

    func showDownloadDidReceiveExpectedContentLength(_ expectedContentLength: UInt64) {
        guard oneClick else { return standard.showDownloadDidReceiveExpectedContentLength(expectedContentLength) }
        expected = expectedContentLength
    }

    func showDownloadDidReceiveData(ofLength length: UInt64) {
        guard oneClick else { return standard.showDownloadDidReceiveData(ofLength: length) }
        received += length
        updates?.set(.downloading(version: version, share: expected > 0 ? min(1, Double(received) / Double(expected)) : nil))
    }

    func showDownloadDidStartExtractingUpdate() {
        guard oneClick else { return standard.showDownloadDidStartExtractingUpdate() }
        cancellation = nil
        updates?.set(.installing(version: version))
    }

    func showExtractionReceivedProgress(_ progress: Double) {
        if !oneClick { standard.showExtractionReceivedProgress(progress) }
    }

    func showReady(toInstallAndRelaunch reply: @escaping (SPUUserUpdateChoice) -> Void) {
        guard oneClick else { return standard.showReady(toInstallAndRelaunch: reply) }
        updates?.set(.installing(version: version))
        reply(.install)  // while busy, Updates postpones the relaunch until idle
    }

    func showInstallingUpdate(withApplicationTerminated applicationTerminated: Bool, retryTerminatingApplication: @escaping () -> Void) {
        if !oneClick {
            standard.showInstallingUpdate(withApplicationTerminated: applicationTerminated,
                                          retryTerminatingApplication: retryTerminatingApplication)
        }
    }

    func showUpdateInstalledAndRelaunched(_ relaunched: Bool, acknowledgement: @escaping () -> Void) {
        if oneClick { acknowledgement() } else { standard.showUpdateInstalledAndRelaunched(relaunched, acknowledgement: acknowledgement) }
    }

    func showUpdateInFocus() {
        if !oneClick { standard.showUpdateInFocus() }
    }

    func dismissUpdateInstallation() {
        cancellation = nil
        if !oneClick { standard.dismissUpdateInstallation() }
    }
}
