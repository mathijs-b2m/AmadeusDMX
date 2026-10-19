// Updates for Amadeus DMX and Amadeus Link: the app checks its release feed (an appcast, the same format and the
// same Ed25519 release key as the Mac's Sparkle) and installs updates signed with that key. Off in a development
// build. The checking and installing is an IUpdater the apps provide (NetSparkle); this class holds the rules.
//
// Opt-in: the app asks on the second launch whether to check automatically. Never while the app is busy (Amadeus
// DMX: a show runs; Amadeus Link: a lighting computer is connected): no background check then, and an update you
// start installing waits until it's idle again. One downloaded in the background is installed when you quit.
//
// What the apps show: this version, the newest in the feed, whether this one is up to date, and one button that
// downloads and installs the newer one (State, Refresh, InstallNewest; the IUpdater reports what it finds).
using System.Reflection;

namespace AmadeusKit;

/// Where this app stands with its updates.
public enum UpdateState
{
    /// Not checked yet.
    Unknown,
    Checking,
    /// This is the newest (Newest: the feed's newest version, when it said).
    UpToDate,
    /// Newest is newer than this one.
    Available,
    /// Downloading Newest (Progress: the share done, nil while its size isn't known).
    Downloading,
    /// Downloaded, now installing: the app starts again (with WaitingForIdle: once it's idle).
    Installing,
    /// Problem says why.
    Failed,
}

/// What checks and installs (NetSparkle in the apps). It asks `Updates` before a check and before installing.
public interface IUpdater
{
    bool CanCheck { get; }
    bool ChecksAutomatically { get; set; }
    bool InstallsAutomatically { get; set; }
    DateTimeOffset? LastChecked { get; }
    /// A check the person asked for (it shows what it finds).
    void CheckForUpdates();
    /// A quiet check (nothing shown): reports what's newest with Updates.Report.
    void Refresh();
    /// Downloads and installs the newest the last check found, reporting its progress.
    void InstallNewest();
    /// Stops that download.
    void CancelInstall();
    /// CanCheck changed.
    event Action? CanCheckChanged;
}

public sealed class Updates : Observable
{
    /// nil in a development build (no feed or key).
    readonly IUpdater? _updater;
    readonly Defaults _defaults;
    Action? _pendingInstall;
    bool _canCheck, _waitingForIdle;
    UpdateState _state;
    string? _newest, _problem;
    double? _progress;
    DateTimeOffset? _lastRefresh;
    readonly Func<DateTimeOffset> _now;

    /// Whether the app must not be interrupted now (a show runs, a lighting computer is connected).
    public Func<bool> IsBusy { get; set; } = () => false;

    public bool CanCheck { get => _canCheck; private set => Set(ref _canCheck, value); }
    /// An update waits until the app is idle.
    public bool WaitingForIdle { get => _waitingForIdle; private set => Set(ref _waitingForIdle, value); }

    public bool IsAvailable => _updater is not null;

    /// The version people see (1.0.5) and the build number updates compare (the fourth part of the assembly version).
    public string Version { get; }
    public int Build { get; }

    public UpdateState State { get => _state; private set => Set(ref _state, value); }
    /// The newest version the feed has (Available, Downloading, Installing: the one that's newer than this).
    public string? Newest { get => _newest; private set => Set(ref _newest, value); }
    public double? Progress { get => _progress; private set => Set(ref _progress, value); }
    public string? Problem { get => _problem; private set => Set(ref _problem, value); }

    public Updates(IUpdater? updater = null, Defaults? defaults = null, Func<DateTimeOffset>? now = null)
    {
        _updater = updater;
        _defaults = defaults ?? Defaults.Standard;
        _now = now ?? (() => DateTimeOffset.UtcNow);
        var entry = Assembly.GetEntryAssembly();
        Version = entry?.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0.0.0";
        Build = entry?.GetName().Version?.Revision is int r and > 0 ? r : 0;
        if (updater is null) return;
        CanCheck = updater.CanCheck;
        updater.CanCheckChanged += () => CanCheck = updater.CanCheck;
    }

    public void CheckForUpdates() => _updater?.CheckForUpdates();

    /// A quiet check for what's newest: at most every five minutes unless forced, never while an update is on its way.
    public void Refresh(bool force = false)
    {
        if (_updater is null || !CanCheck || State is UpdateState.Checking or UpdateState.Downloading or UpdateState.Installing) return;
        if (!force && _lastRefresh is { } last && _now() - last < TimeSpan.FromMinutes(5)) return;
        _lastRefresh = _now();
        Report(UpdateState.Checking, Newest);
        _updater.Refresh();
    }

    /// The one click: download and install the newest (after the show, if one runs). The app starts again.
    public void InstallNewest()
    {
        if (_updater is null || !CanCheck || State != UpdateState.Available) return;
        Report(UpdateState.Downloading, Newest);
        _updater.InstallNewest();
    }

    public void CancelInstall()
    {
        if (State == UpdateState.Downloading) _updater?.CancelInstall();
    }

    /// What the IUpdater found or is doing (on the UI thread).
    public void Report(UpdateState state, string? newest = null, double? progress = null, string? problem = null)
    {
        // the same state with under a percent more done: nothing to redraw
        if (state == State && newest == Newest && problem == Problem && progress is { } p && Progress is { } q && Math.Abs(p - q) < 0.01) return;
        State = state;
        Newest = newest;
        Progress = progress;
        Problem = problem;
    }

    public bool ChecksAutomatically
    {
        get => _updater?.ChecksAutomatically ?? false;
        set
        {
            if (_updater is null) return;
            _updater.ChecksAutomatically = value;
            _defaults.Set(AskedKey, true);  // a choice made: never ask again
            Changed();
        }
    }

    public bool InstallsAutomatically
    {
        get => _updater?.InstallsAutomatically ?? false;
        set { if (_updater is not null) { _updater.InstallsAutomatically = value; Changed(); } }
    }

    public DateTimeOffset? LastChecked => _updater?.LastChecked;

    // MARK: opt-in (Sparkle's own rule on the Mac: ask on the second launch, once)

    const string LaunchesKey = "updatesLaunches", AskedKey = "updatesAsked";

    /// Call once per launch: whether to ask now if the app may check for updates by itself.
    public bool ShouldAskToCheckAutomatically()
    {
        if (_updater is null || _defaults.Bool(AskedKey)) return false;
        var launches = _defaults.Integer(LaunchesKey) + 1;
        _defaults.Set(LaunchesKey, launches);
        return launches >= 2;
    }

    /// The answer to that question.
    public void Answer(bool checkAutomatically)
    {
        _defaults.Set(AskedKey, true);
        ChecksAutomatically = checkAutomatically;
    }

    // MARK: never during a show (the IUpdater asks these)

    /// May a check start now? A check in the background never does while the app is busy.
    public bool MayCheck(bool inBackground) => !(inBackground && IsBusy());

    /// Installing an update relaunches the app: while it is busy, keep `install` for later and say so (true).
    public bool ShouldPostponeInstall(Action install)
    {
        if (!IsBusy()) return false;
        _pendingInstall = install;
        WaitingForIdle = true;
        Report(UpdateState.Installing, Newest);
        return true;
    }

    /// The app is idle again: an update that waited installs now (and the app relaunches).
    public void BecameIdle()
    {
        if (_pendingInstall is not { } install) return;
        _pendingInstall = null;
        WaitingForIdle = false;
        install();
    }
}
