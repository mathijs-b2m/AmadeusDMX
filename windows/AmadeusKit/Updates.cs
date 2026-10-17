// Updates for Amadeus DMX and Amadeus Link: the app checks its release feed (an appcast, the same format and the
// same Ed25519 release key as the Mac's Sparkle) and installs updates signed with that key. Off in a development
// build. The checking and installing is an IUpdater the apps provide (NetSparkle); this class holds the rules.
//
// Opt-in: the app asks on the second launch whether to check automatically. Never while the app is busy (Amadeus
// DMX: a show runs; Amadeus Link: a lighting computer is connected): no background check then, and an update you
// start installing waits until it's idle again. One downloaded in the background is installed when you quit.
namespace AmadeusKit;

/// What checks and installs (NetSparkle in the apps). It asks `Updates` before a check and before installing.
public interface IUpdater
{
    bool CanCheck { get; }
    bool ChecksAutomatically { get; set; }
    bool InstallsAutomatically { get; set; }
    DateTimeOffset? LastChecked { get; }
    /// A check the person asked for (it shows what it finds).
    void CheckForUpdates();
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

    /// Whether the app must not be interrupted now (a show runs, a lighting computer is connected).
    public Func<bool> IsBusy { get; set; } = () => false;

    public bool CanCheck { get => _canCheck; private set => Set(ref _canCheck, value); }
    /// An update waits until the app is idle.
    public bool WaitingForIdle { get => _waitingForIdle; private set => Set(ref _waitingForIdle, value); }

    public bool IsAvailable => _updater is not null;

    public Updates(IUpdater? updater = null, Defaults? defaults = null)
    {
        _updater = updater;
        _defaults = defaults ?? Defaults.Standard;
        if (updater is null) return;
        CanCheck = updater.CanCheck;
        updater.CanCheckChanged += () => CanCheck = updater.CanCheck;
    }

    public void CheckForUpdates() => _updater?.CheckForUpdates();

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
