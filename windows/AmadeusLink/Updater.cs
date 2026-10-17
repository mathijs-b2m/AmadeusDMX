// Updates for a release with a feed (appsettings.json: UpdateFeedUrl, UpdatePublicEdKey): NetSparkle reading the
// same appcast format as the Mac's Sparkle, every feed and installer checked against the same Ed25519 release key
// (strict: unsigned is refused). The kit's Updates holds the rules (opt-in, never while a lighting computer is
// connected); this is the IUpdater it asks. Nothing in it is Link-specific: Amadeus DMX can use it as it is.
//
// - Newer means a higher build number (sparkle:version, the commit count build.ps1 stamps into the app's version
//   as its fourth number), never the version text: 0.3.0-beta.2 and 0.3.0 can't confuse it.
// - An update is the new installer, run silently (/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART) once the app has quit;
//   the app starts again after it. Installing waits while the app is busy (Updates.ShouldPostponeInstall).
// - No window of NetSparkle's own (it has none for WinUI): the app's `ask`/`tell` show what there is to say.
using System.Reflection;
using NetSparkleUpdater;
using NetSparkleUpdater.Configurations;
using NetSparkleUpdater.Enums;
using NetSparkleUpdater.Interfaces;
using NetSparkleUpdater.SignatureVerifiers;

namespace AmadeusLink;

public sealed class Updater : IUpdater, IDisposable
{
    public const string InstallerArguments = "/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART";
    static readonly TimeSpan Every = TimeSpan.FromHours(24);

    /// The updater for this build: nil without a feed or a key (a development build).
    public static Updater? ForThisBuild(string appName, Func<Updates?> rules, Func<string, string, string, Task<bool>> ask,
                                        Action<string, string> tell, Action quit) =>
        AppSettings.UpdateFeedUrl is { } feed && AppSettings.UpdatePublicEdKey is { } key
            ? new Updater(appName, feed, key, rules, ask, tell, quit) : null;

    /// This build's number (build.ps1's BuildNumber: the fourth part of the assembly version) and version text.
    public static int Build => Assembly.GetEntryAssembly()?.GetName().Version?.Revision is int r and > 0 ? r : 0;
    public static string Version =>
        Assembly.GetEntryAssembly()?.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0.0.0";

    readonly string _appName;
    readonly SparkleUpdater _sparkle;
    readonly Func<Updates?> _rules;
    readonly Func<string, string, string, Task<bool>> _ask;
    readonly Action<string, string> _tell;
    readonly Action _quit;
    readonly Defaults _defaults = Defaults.Standard;
    readonly CancellationTokenSource _life = new();
    readonly SynchronizationContext? _ui = SynchronizationContext.Current;
    bool _busy;
    string? _downloaded;  // an installer downloaded in the background, installed when the app quits
    AppCastItem? _downloadedItem;

    Updater(string appName, string feed, string publicKey, Func<Updates?> rules, Func<string, string, string, Task<bool>> ask,
            Action<string, string> tell, Action quit)
    {
        _appName = appName;
        _rules = rules;
        _ask = ask;
        _tell = tell;
        _quit = quit;
        _sparkle = new SparkleUpdater(feed, new Ed25519Checker(SecurityMode.Strict, publicKey))
        {
            UIFactory = null,
            UserInteractionMode = UserInteractionMode.NotSilent,  // nothing happens without us: we ask, then install
            CustomInstallerArguments = InstallerArguments,
            RelaunchAfterUpdate = true,
            ClearOldInstallers = null,
        };
        _sparkle.Configuration = new BuildConfiguration(new BuildAccessor(appName));
        _sparkle.AppCastHelper = new ByBuildNumber();
        // NetSparkle quits the app to run the installer: the app's own quit (the window, the icon, the ports)
        _sparkle.CloseApplication += () => Post(_quit);
        _ = Loop();
    }

    // MARK: IUpdater

    public bool CanCheck => !_busy;
    public event Action? CanCheckChanged;

    public bool ChecksAutomatically
    {
        get => _defaults.BoolIfSet("SUEnableAutomaticChecks") ?? false;
        set => _defaults.Set("SUEnableAutomaticChecks", value);
    }

    public bool InstallsAutomatically
    {
        get => _defaults.BoolIfSet("SUAutomaticallyUpdate") ?? false;
        set => _defaults.Set("SUAutomaticallyUpdate", value);
    }

    public DateTimeOffset? LastChecked
    {
        get
        {
            var t = _defaults.Double("SULastCheckTime");
            return t > 0 ? DateTimeOffset.FromUnixTimeSeconds((long)t) : null;
        }
    }

    public void CheckForUpdates() => _ = Check(inBackground: false);

    // MARK: checking

    void Post(Action a)
    {
        if (_ui is null) a();
        else _ui.Post(_ => a(), null);
    }

    void SetBusy(bool busy) => Post(() =>
    {
        _busy = busy;
        CanCheckChanged?.Invoke();
    });

    /// A check by itself once a day, when the person said it may.
    async Task Loop()
    {
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(30), _life.Token);  // not while the app is starting
            while (!_life.IsCancellationRequested)
            {
                var due = LastChecked is not { } last || DateTimeOffset.UtcNow - last >= Every;
                if (ChecksAutomatically && due) await Check(inBackground: true);
                await Task.Delay(TimeSpan.FromHours(1), _life.Token);
            }
        }
        catch (OperationCanceledException) { }
    }

    async Task Check(bool inBackground)
    {
        var rules = _rules();
        if (_busy || rules is null || !rules.MayCheck(inBackground)) return;
        SetBusy(true);
        try
        {
            var info = await _sparkle.CheckForUpdatesQuietly(ignoreSkippedVersions: !inBackground);
            _defaults.Set("SULastCheckTime", (double)DateTimeOffset.UtcNow.ToUnixTimeSeconds());
            var item = info.Updates?.OrderByDescending(i => BuildOf(i)).FirstOrDefault();
            if (info.Status != UpdateStatus.UpdateAvailable || item is null)
            {
                if (!inBackground)
                    Post(() => _tell(info.Status == UpdateStatus.CouldNotDetermine ? "Can’t check for updates" : "You’re up to date",
                                     info.Status == UpdateStatus.CouldNotDetermine
                                         ? "The update feed can't be reached or isn't signed with the release key. Try again later."
                                         : $"{_appName} {Version} is the newest version."));
                return;
            }
            if (inBackground && InstallsAutomatically)
            {
                await Download(item, installNow: false);  // installed when the app quits
                return;
            }
            var go = await Ask(item);
            if (go) await Download(item, installNow: true);
        }
        catch (Exception e) when (e is HttpRequestException or IOException or TaskCanceledException or InvalidOperationException)
        {
            if (!inBackground) Post(() => _tell("Can’t check for updates", e.Message));
        }
        finally { SetBusy(false); }
    }

    Task<bool> Ask(AppCastItem item)
    {
        var done = new TaskCompletionSource<bool>();
        Post(async () =>
        {
            try { done.TrySetResult(await _ask($"{_appName} {item.ShortVersion ?? item.Version} is available",
                                               $"You have {Version}. The update installs in a moment and {_appName} starts again; your settings stay.",
                                               "Install Update")); }
            catch (Exception) { done.TrySetResult(false); }
        });
        return done.Task;
    }

    async Task Download(AppCastItem item, bool installNow)
    {
        var finished = new TaskCompletionSource<string?>();
        void Done(AppCastItem i, string path) => finished.TrySetResult(path);
        void Bad(AppCastItem i, string path) => finished.TrySetResult(null);
        void Error(AppCastItem i, string? path, Exception e) => finished.TrySetResult(null);
        _sparkle.DownloadFinished += Done;
        _sparkle.DownloadedFileIsCorrupt += Bad;
        _sparkle.DownloadedFileThrewWhileCheckingSignature += Bad;
        _sparkle.DownloadHadError += Error;
        try
        {
            await _sparkle.InitAndBeginDownload(item);
            var path = await finished.Task.WaitAsync(TimeSpan.FromMinutes(30));
            if (path is null)
            {
                if (installNow) Post(() => _tell("The update can't be installed", "Its download failed, or it isn't signed with the release key."));
                return;
            }
            if (!installNow)
            {
                (_downloaded, _downloadedItem) = (path, item);
                return;
            }
            Post(() => Install(item, path));
        }
        finally
        {
            _sparkle.DownloadFinished -= Done;
            _sparkle.DownloadedFileIsCorrupt -= Bad;
            _sparkle.DownloadedFileThrewWhileCheckingSignature -= Bad;
            _sparkle.DownloadHadError -= Error;
        }
    }

    /// Runs the installer once the app has quit; while the app is busy, when it is idle again.
    void Install(AppCastItem item, string path)
    {
        void Now() => _ = _sparkle.InstallUpdate(item, path);
        if (_rules() is { } rules && rules.ShouldPostponeInstall(Now)) return;
        Now();
    }

    /// The app quits: an update downloaded in the background installs now (and the app starts again).
    public bool InstallOnQuit()
    {
        if (_downloaded is not { } path || _downloadedItem is not { } item || !File.Exists(path)) return false;
        _downloaded = null;
        _ = _sparkle.InstallUpdate(item, path);
        return true;
    }

    static long BuildOf(AppCastItem i) => long.TryParse(i.Version, out var b) ? b : -1;

    public void Dispose()
    {
        _life.Cancel();
        _sparkle.Dispose();
    }

    // MARK: what NetSparkle compares

    /// The installed "version" NetSparkle compares with: this build's number.
    sealed class BuildAccessor(string appName) : IAssemblyAccessor
    {
        public string AssemblyCompany => "Amadeus DMX";
        public string AssemblyCopyright => "Amadeus DMX contributors";
        public string AssemblyDescription => appName;
        public string AssemblyTitle => appName;
        public string AssemblyProduct => appName;
        public string AssemblyVersion => Build.ToString(System.Globalization.CultureInfo.InvariantCulture);
    }

    /// NetSparkle's settings, kept in memory: what it needs to remember is in the app's own settings.
    sealed class BuildConfiguration : Configuration
    {
        public BuildConfiguration(IAssemblyAccessor accessor) : base(accessor)
        {
            ApplicationName = accessor.AssemblyProduct;
            InstalledVersion = accessor.AssemblyVersion;
            CheckForUpdate = true;
            LastCheckTime = DateTime.MinValue;
        }

        public override void Reload() { }
        public override void TouchProfileTime() { }
        public override void TouchCheckTime() => LastCheckTime = DateTime.Now;
        public override void SetVersionToSkip(string version) => LastVersionSkipped = version;
    }

    /// Only Windows updates with a higher build number than this one, newest first (the feed's signature is
    /// checked by NetSparkle before this, each installer's after its download).
    sealed class ByBuildNumber : NetSparkleUpdater.AppCastHandlers.AppCastHelper
    {
        public override List<AppCastItem> FilterUpdates(List<AppCastItem> items) =>
            [.. items.Where(i => i.IsWindowsUpdate && BuildOf(i) > Build && !string.IsNullOrEmpty(i.DownloadLink)
                                         && !string.IsNullOrEmpty(i.DownloadSignature)).OrderByDescending(BuildOf)];
    }
}
