// Updates with NetSparkle (the Mac's Sparkle, mac/Sources/AmadeusKit/Updates.swift): the app checks its release
// feed (UpdateFeedUrl in appsettings.json, which build.ps1 writes for a release with a feed) and installs updates
// signed with the release key (UpdatePublicEdKey, Ed25519, strict: the feed is signed too). No feed: no updater
// (a development build). The rules (opt-in on the second launch, never during a show) are AmadeusKit's Updates;
// this is its IUpdater. NetSparkle has no WinUI interface, so the questions are ContentDialogs here.
//
// Versions compare by build number: sparkle:version is the commit count, and so is the last part of the assembly
// version (Directory.Build.props: BuildNumber). An update runs the new installer silently once the app has quit,
// then starts the app again.
using NetSparkleUpdater;
using NetSparkleUpdater.Enums;
using NetSparkleUpdater.Interfaces;
using NetSparkleUpdater.SignatureVerifiers;

namespace AmadeusDMX;

public sealed class Updater : IUpdater
{
    /// The installer's switches (Inno Setup): no questions, no restart; /RELAUNCH: it starts the app it installed
    /// afterwards (not NetSparkle, which would start this exe again, wherever it ran from).
    public const string InstallerArguments = "/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART";
    const string Relaunch = " /RELAUNCH";
    const string ChecksKey = "updatesCheckAutomatically", InstallsKey = "updatesInstallAutomatically", LastKey = "updatesLastChecked";
    static readonly TimeSpan Interval = TimeSpan.FromHours(24);

    readonly SparkleUpdater _sparkle;
    readonly int _build;
    readonly string _version;
    readonly SynchronizationContext? _ui = SynchronizationContext.Current;
    Updates? _rules;
    Func<XamlRoot?> _root = () => null;
    Action _quit = () => { };
    bool _busy, _quitting;
    (AppCastItem Item, string Path)? _downloaded;   // downloaded in the background: installed when you quit
    TaskCompletionSource<string?>? _download;
    AppCastItem? _newest;  // what the last check found newer than this build
    Action<double>? _progress;

    /// The updater for a release with a feed; nil in a development build.
    public static Updater? Create() =>
        AppSettings.UpdateFeedUrl is { } feed && AppSettings.UpdatePublicEdKey is { } key ? new Updater(feed, key) : null;

    Updater(string feed, string publicKey)
    {
        var asm = typeof(Updater).Assembly;
        _build = UpdateVersions.BuildNumber(asm.GetName().Version);
        _version = AppVersion;
        _sparkle = new SparkleUpdater(feed, new Ed25519Checker(SecurityMode.Strict, publicKey))
        {
            UIFactory = null,
            UserInteractionMode = UserInteractionMode.NotSilent,  // no UI factory: nothing is shown or downloaded by itself
            CustomInstallerArguments = InstallerArguments + Relaunch,
            RelaunchAfterUpdate = false,  // the installer starts the app (Relaunch)
            // NetSparkle asks the app to quit (CloseApplicationAsync: it stops the engine and blacks out first) and the
            // installer waits until it has; off, it neither asks nor waits and installs beside the running app
            ShouldKillParentProcessWhenStartingInstaller = true,
            // name the download after the feed's link (AmadeusDMX-Setup-1.3.1.exe): asking the server names it after
            // where GitHub redirects, a bare id without .exe, and Windows can't run that, so nothing installs
            CheckServerFileName = false,
        };
        _sparkle.Configuration = new NetSparkleUpdater.Configurations.JSONConfiguration(
            new BuildAccessor(_build, _version), Path.Combine(Workspace.DefaultDataFolder, "updates.json"));
        _sparkle.LogWriter = new LogWriter(LogWriterOutputMode.Debug);
        // NetSparkle reports every chunk (thousands a second on a fast network): only each whole percent reaches the UI
        var lastPercent = -1;
        _sparkle.DownloadMadeProgress += (_, _, e) =>
        {
            var share = e.TotalBytesToReceive > 0 ? (double)e.BytesReceived / e.TotalBytesToReceive : 0;
            var percent = (int)(share * 100);
            if (Interlocked.Exchange(ref lastPercent, percent) == percent) return;
            Post(() => _progress?.Invoke(share));
        };
        _sparkle.DownloadFinished += (_, path) => Post(() => _download?.TrySetResult(path));
        _sparkle.DownloadHadError += (_, _, ex) => Post(() => _download?.TrySetException(ex));
        _sparkle.DownloadedFileIsCorrupt += (_, _) => Post(() => _download?.TrySetException(new InvalidDataException(
            "The update isn’t signed with the release key: it was not installed.")));
        _sparkle.DownloadCanceled += (_, _) => Post(() => _download?.TrySetResult(null));
        // the installer is about to run (it waits for this app to quit): quit
        _sparkle.CloseApplicationAsync += () =>
        {
            if (_quitting) return Task.CompletedTask;  // installing at quit: the app is closing already (and its UI thread waits)
            var done = new TaskCompletionSource();
            Post(() => { if (!_quitting) { _quitting = true; _quit(); } done.TrySetResult(); });
            return done.Task;
        };
    }

    /// The version people see (0.3.0), from the build.
    public static string AppVersion =>
        typeof(Updater).Assembly.GetCustomAttributes(typeof(System.Reflection.AssemblyInformationalVersionAttribute), false)
            .OfType<System.Reflection.AssemblyInformationalVersionAttribute>().FirstOrDefault()?.InformationalVersion ?? "";

    void Post(Action a)
    {
        if (_ui is null || SynchronizationContext.Current == _ui) a(); else _ui.Post(_ => a(), null);
    }

    /// Wires it to the app: the rules, the window for its questions, and quitting. Asks on the second launch whether
    /// to check automatically, checks in the background when that's on, installs a background download at quit.
    public void Attach(AppModel model, MainWindow window)
    {
        _rules = model.Updates;
        _root = () => window.Root;
        _quit = () => { window.Close(); Application.Current.Exit(); };
        var asked = false;
        window.Activated += async (_, _) =>
        {
            if (asked) return;
            asked = true;
            await Task.Delay(1500);  // the window is up and drawn first
            await AskToCheckAutomatically();
        };
        window.Closed += (_, _) => InstallOnQuit();
        _ = Loop();
    }

    // MARK: IUpdater

    public bool CanCheck => !_busy;
    public event Action? CanCheckChanged;

    void Busy(bool on)
    {
        _busy = on;
        CanCheckChanged?.Invoke();
    }

    public bool ChecksAutomatically
    {
        get => Defaults.Standard.Bool(ChecksKey);
        set => Defaults.Standard.Set(ChecksKey, value);
    }

    public bool InstallsAutomatically
    {
        get => Defaults.Standard.Bool(InstallsKey);
        set => Defaults.Standard.Set(InstallsKey, value);
    }

    public DateTimeOffset? LastChecked =>
        Defaults.Standard.Contains(LastKey) ? DateTimeOffset.FromUnixTimeSeconds((long)Defaults.Standard.Double(LastKey)) : null;

    public void CheckForUpdates() => _ = Check(inBackground: false);
    public void Refresh() => _ = Check(inBackground: false, quiet: true);
    public void InstallNewest() => _ = InstallNewestQuietly();
    public void CancelInstall() => _sparkle.CancelFileDownload();

    void Report(UpdateState state, string? newest = null, double? progress = null, string? problem = null) =>
        Post(() => _rules?.Report(state, newest, progress, problem));

    static string Name(AppCastItem item) => item.ShortVersion ?? item.Version ?? "";

    // MARK: checking

    /// Sparkle's question on the second launch, once.
    async Task AskToCheckAutomatically()
    {
        if (_rules is null || !_rules.ShouldAskToCheckAutomatically()) return;
        var yes = await Dialogs.Confirm(_root(), "Check for updates automatically?",
            "Should Amadeus DMX automatically check for updates? You can always check for updates manually from the Help menu.",
            "Check Automatically");
        _rules.Answer(yes);
    }

    /// Checks once a day while checking automatically is on (never during a show: the rules say no then).
    async Task Loop()
    {
        await Task.Delay(TimeSpan.FromSeconds(20));
        while (!_quitting)
        {
            if (ChecksAutomatically && (LastChecked is not { } last || DateTimeOffset.Now - last >= Interval))
                await Check(inBackground: true);
            await Task.Delay(TimeSpan.FromMinutes(30));
        }
    }

    /// quiet: nothing shown but what Updates reports (the status in Settings).
    async Task Check(bool inBackground, bool quiet = false)
    {
        if (_busy || _rules?.MayCheck(inBackground) == false) { if (quiet) Report(_rules?.State ?? UpdateState.Unknown, _rules?.Newest); return; }
        Busy(true);
        try
        {
            UpdateInfo info;
            try { info = await _sparkle.CheckForUpdatesQuietly(ignoreSkippedVersions: !inBackground); }
            catch (Exception e)  // whatever the network or the feed did: the app goes on
            {
                Report(UpdateState.Failed, problem: e.Message);
                if (!inBackground && !quiet) await Dialogs.Alert(_root(), "Update Error!", $"Amadeus DMX couldn’t check for updates: {e.Message}");
                return;
            }
            Defaults.Standard.Set(LastKey, (double)DateTimeOffset.Now.ToUnixTimeSeconds());
            var item = Newest(info.Updates);
            _newest = info.Status == UpdateStatus.UpdateAvailable ? item : null;
            if (_newest is { } n) Report(UpdateState.Available, Name(n));
            else if (info.Status == UpdateStatus.CouldNotDetermine) Report(UpdateState.Failed, problem: "The update feed can't be read, or isn't signed with the release key.");
            else Report(UpdateState.UpToDate, _version);
            if (quiet) return;
            if (info.Status == UpdateStatus.UpdateAvailable && item is not null)
            {
                if (inBackground && InstallsAutomatically) { await DownloadInBackground(item); return; }
                await Offer(item);
            }
            else if (!inBackground)
            {
                if (info.Status == UpdateStatus.CouldNotDetermine)
                    await Dialogs.Alert(_root(), "Update Error!", "Amadeus DMX couldn’t read the update feed (or its signature). Try again later.");
                else
                    await Dialogs.Alert(_root(), "You’re up to date!", $"Amadeus DMX {_version} is currently the newest version available.");
            }
        }
        finally { Busy(false); }
    }

    /// The newest release in the feed that is newer than this build (prereleases never reach people).
    AppCastItem? Newest(IEnumerable<AppCastItem>? items) =>
        (items ?? []).Where(i => i.IsWindowsUpdate && UpdateVersions.IsNewer(i.Version, _build) && !UpdateVersions.IsPrerelease(i.ShortVersion))
            .OrderByDescending(i => int.TryParse(i.Version, out var n) ? n : 0).FirstOrDefault();

    /// "A new version is available": install, later, or skip it.
    async Task Offer(AppCastItem item)
    {
        if (_root() is not { } root) return;
        var d = new ContentDialog
        {
            XamlRoot = root,
            Title = "A new version of Amadeus DMX is available!",
            Content = UI.VStack(10,
                UI.Text($"Amadeus DMX {item.ShortVersion ?? item.Version} is now available—you have {_version}. Would you like to download it now?").Wrap(),
                item.ReleaseNotesLink is { Length: > 0 } notes ? UI.Link("Release Notes", () => Dialogs.OpenURL(notes)) : null),
            PrimaryButtonText = "Install Update",
            SecondaryButtonText = "Skip This Version",
            CloseButtonText = "Remind Me Later",
            DefaultButton = ContentDialogButton.Primary,
        };
        switch (await Dialogs.Show(d))
        {
            case ContentDialogResult.Primary: await DownloadAndInstall(item); break;
            case ContentDialogResult.Secondary: _sparkle.Configuration.SetVersionToSkip(item.Version ?? ""); break;
        }
    }

    // MARK: downloading and installing

    async Task<string?> Download(AppCastItem item)
    {
        _download = new TaskCompletionSource<string?>();
        await _sparkle.InitAndBeginDownload(item);
        try { return await _download.Task; }
        finally { _download = null; _progress = null; }
    }

    /// Downloads with a progress dialog, then installs (after the show, if one runs).
    async Task DownloadAndInstall(AppCastItem item)
    {
        if (_root() is not { } root) return;
        var bar = UI.Progress(null).MinWidth(320);
        var dialog = new ContentDialog
        {
            XamlRoot = root, Title = "Downloading Update…",
            Content = UI.VStack(10, UI.Text($"Amadeus DMX {item.ShortVersion ?? item.Version}"), bar),
            CloseButtonText = "Cancel",
        };
        _progress = share => { bar.IsIndeterminate = share <= 0; bar.Value = share; };
        dialog.CloseButtonClick += (_, _) => _sparkle.CancelFileDownload();
        var shown = Dialogs.Show(dialog);
        string? path;
        try { path = await Download(item); }
        catch (Exception e)
        {
            dialog.Hide();
            await shown;
            await Dialogs.Alert(_root(), "Update Error!", $"The update couldn’t be downloaded: {e.Message}");
            return;
        }
        dialog.Hide();
        await shown;
        if (path is null) return;  // cancelled
        Install(item, path);
    }

    /// The one click in Settings: downloads with the progress in the status, then installs (after the show, if one runs).
    async Task InstallNewestQuietly()
    {
        if (_newest is not { } item || _busy) return;
        Busy(true);
        try
        {
            Report(UpdateState.Downloading, Name(item));
            string? path;
            try
            {
                _progress = share => _rules?.Report(UpdateState.Downloading, Name(item), share > 0 ? share : null);
                path = await Download(item);
            }
            catch (Exception e)
            {
                Report(UpdateState.Failed, Name(item), problem: $"The update couldn’t be downloaded: {e.Message}");
                return;
            }
            if (path is null) { Report(UpdateState.Available, Name(item)); return; }  // cancelled
            Report(UpdateState.Installing, Name(item));
            Install(item, path, quiet: true);
        }
        finally { Busy(false); }
    }

    /// One downloaded by itself waits until you quit.
    async Task DownloadInBackground(AppCastItem item)
    {
        try
        {
            if (await Download(item) is { } path) _downloaded = (item, path);
        }
        catch (Exception) { }  // tried again at the next check
    }

    /// Installing quits the app: while a show runs it waits until the show stops (the rules keep it).
    void Install(AppCastItem item, string path, bool quiet = false)
    {
        void Now() => _ = _sparkle.InstallUpdate(item, path);
        if (_rules?.ShouldPostponeInstall(Now) == true)
        {
            if (quiet) return;  // the status says it waits for the show
            _ = Dialogs.Alert(_root(), "The update installs when the show stops",
                "Amadeus DMX never restarts during a show: the update is ready and installs as soon as you stop the show.");
            return;
        }
        Now();
    }

    /// The app quits: an update downloaded in the background installs now (the app isn't started again).
    void InstallOnQuit()
    {
        _quitting = true;
        if (_downloaded is not { } d) return;
        _downloaded = null;
        _sparkle.CustomInstallerArguments = InstallerArguments;  // not started again
        // the installer waits for this process to end; launch it before the app is gone
        try { Task.Run(() => _sparkle.InstallUpdate(d.Item, d.Path)).Wait(TimeSpan.FromSeconds(10)); }
        catch (AggregateException) { }
    }

    /// What NetSparkle compares and saves under: the build number is the version (the feed's sparkle:version).
    sealed class BuildAccessor(int build, string version) : IAssemblyAccessor
    {
        public string AssemblyCompany => "Amadeus DMX";
        public string AssemblyCopyright => "Amadeus DMX contributors";
        public string AssemblyDescription => $"Amadeus DMX {version}";
        public string AssemblyTitle => "Amadeus DMX";
        public string AssemblyProduct => "Amadeus DMX";
        public string AssemblyVersion => build.ToString(System.Globalization.CultureInfo.InvariantCulture);
    }
}
