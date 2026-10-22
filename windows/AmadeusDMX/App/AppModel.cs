// The app's state: where the engine is, the show engine and the setup service, the live feed, the sets.
// SwiftUI follows every property the views read; here a property raises PropertyChanged (Observable), and the
// properties computed from others (ShowState from the engine and the feed, ShowLabel from the selection) are
// raised whenever what they come from changes.
namespace AmadeusDMX;

public sealed class AppModel : Observable
{
    Workspace? _workspace;
    public Workspace? Workspace
    {
        get => _workspace;
        set { if (Set(ref _workspace, value)) Changed(nameof(NeedsSetup)); }
    }

    public EngineProcess Engine { get; } = new("show");
    /// What the show costs the computer: the light engine against the 3D stage.
    public PowerMeter Power { get; } = new();
    public EngineProcess Setup { get; } = new("setup");
    /// Installs an optional pack (Settings › General).
    public EngineProcess PackInstall { get; } = new("packs");
    /// Updates (NetSparkle; a release build only: App.cs gives it its updater).
    public Updates Updates { get; }
    public LiveFeed Feed { get; } = new();
    public SetupAPI Api { get; } = new(8181);
    public LinkBrowser Djs { get; } = new();

    Section _section = Section.Show;
    public Section Section { get => _section; set => Set(ref _section, value); }

    /// Your gear (fixtures and patch) and the venues (trusses, stage) it can hang on. A show runs with one of each.
    IReadOnlyList<SetSummary> _sets = [];
    IReadOnlyList<RigSummary> _rigs = [];
    public IReadOnlyList<SetSummary> Sets { get => _sets; private set { if (Set(ref _sets, value)) Derived(); } }
    public IReadOnlyList<RigSummary> Rigs { get => _rigs; private set { if (Set(ref _rigs, value)) Derived(); } }

    string _selectedSet = "", _selectedRig = "";
    public string SelectedSet
    {
        get => _selectedSet;
        set { if (Set(ref _selectedSet, value)) { SelectionChanged(); Derived(); } }
    }
    public string SelectedRig
    {
        get => _selectedRig;
        set { if (Set(ref _selectedRig, value)) { SelectionChanged(); Derived(); } }
    }

    /// Everything computed from the sets, rigs and the selection.
    void Derived() => Changed(nameof(ShowLabel), nameof(Combinations), nameof(CurrentSet), nameof(CurrentRig), nameof(Mounted));

    /// The set on the rig, in words: "showcase on club".
    public string ShowLabel => SelectedSet.Length == 0 ? "No Set" : $"{SelectedSet} on {SelectedRig}";

    /// Sheets: a new rig (from a template), and "mount the set on this rig?" when it isn't yet.
    bool _showNewRig;
    public bool ShowNewRig { get => _showNewRig; set => Set(ref _showNewRig, value); }
    /// Goes up whenever sets or rigs were (re)read: views showing a file reload it.
    int _configVersion;
    public int ConfigVersion { get => _configVersion; private set => Set(ref _configVersion, value); }
    (string Rig, string Set)? _mountPrompt;
    public (string Rig, string Set)? MountPrompt { get => _mountPrompt; set => Set(ref _mountPrompt, value); }
    /// The Sets page edits this set (it has nothing to do with the show's choice).
    string _editingSet = "";
    public string EditingSet { get => _editingSet; set => Set(ref _editingSet, value); }
    /// The Rigs page edits this rig, and the set placed on it whose placement is shown ("": the rig alone).
    /// Opening a rig shows a set on it (RigSetDefault), not the bare rig: that is what you came to see.
    string _editingRig = "", _editingRigSet = "";
    public string EditingRig
    {
        get => _editingRig;
        set
        {
            if (_editingRig == value) return;
            _editingRig = value;
            RememberRigSet(RigSetDefault(value));  // the set with it, before either is announced (no editor for the old pair)
            Changed(nameof(EditingRig), nameof(EditingRigSet));
        }
    }
    public string EditingRigSet
    {
        get => _editingRigSet;
        set { if (RememberRigSet(value)) Changed(); }
    }

    /// Swift's editingRigSet didSet: the choice remembered per rig (settings' "rigEditorSet").
    bool RememberRigSet(string set)
    {
        if (_editingRigSet == set) return false;
        _editingRigSet = set;
        if (_editingRig.Length == 0) return true;
        var chosen = Defaults.Standard.Object("rigEditorSet")?.Object is { } o ? new Dictionary<string, JSONValue>(o) : [];
        chosen[_editingRig] = set;
        Defaults.Standard.Set("rigEditorSet", JSONValue.Of(chosen));
        return true;
    }

    /// The set a rig opens with: the one last shown on it ("" too, when you chose the rig alone), else the show's
    /// set when it is on this rig, else the first one placed on it.
    public string RigSetDefault(string rig)
    {
        var on = SetsOn(rig);
        if (Defaults.Standard.Object("rigEditorSet")?[rig]?.String is { } last && (last.Length == 0 || on.Contains(last))) return last;
        if (on.Contains(SelectedSet)) return SelectedSet;
        return on.FirstOrDefault() ?? "";
    }

    /// A set placed on a rig: what a show runs. Made on the Rigs page; the show picks one of these.
    public readonly record struct Combination(string Rig, string Set)
    {
        public string Id => $"{Set}@{Rig}";
        public string Label => $"{Set} on {Rig}";
    }

    /// Every set placed on a rig (with or without fixtures mounted yet).
    public IReadOnlyList<Combination> Combinations
    {
        get
        {
            var names = Sets.Select(s => s.Name).ToHashSet();
            return Rigs.SelectMany(r => r.Mounted.Keys.Order(StringComparer.Ordinal).Where(names.Contains).Select(s => new Combination(r.Name, s)))
                .ToList();
        }
    }

    /// The sets placed on a rig.
    public IReadOnlyList<string> SetsOn(string rig) => Combinations.Where(c => c.Rig == rig).Select(c => c.Set).ToList();

    /// The show runs this combination.
    public void ChooseShow(Combination c)
    {
        if (EngineRunning) return;
        SelectedRig = c.Rig;
        SelectedSet = c.Set;
    }

    /// Puts a set on a rig (a new combination), auto-mounting its fixtures or leaving them to place by hand.
    public async Task PlaceSet(string set, string on, bool auto)
    {
        if (!await EnsureSetupService()) throw SetupAPIException.NotRunningError();
        await Api.PlaceSet(set, on, auto);
        ReloadSets();
        EditingRigSet = set;
    }

    /// Takes a set off a rig (its placements there are forgotten).
    public async Task UnplaceSet(string set, string from)
    {
        if (!await EnsureSetupService()) throw SetupAPIException.NotRunningError();
        await Api.UnplaceSet(set, from);
        if (EditingRigSet == set) EditingRigSet = "";
        ReloadSets();
    }

    /// Visualise / Perform / both (-showMode perform). Perform ↔ both switches live; DMX on/off restarts the show.
    ShowMode _mode = ShowMode.Both;
    public ShowMode Mode
    {
        get => _mode;
        set
        {
            if (!Set(ref _mode, value)) return;
            Defaults.Standard.Set("showMode", value.RawValue());
            Feed.Lite = !value.Renders3D();
            Changed(nameof(SendArtNet));
        }
    }
    public bool SendArtNet => Mode.SendsDMX();
    /// A mode change that needs the running show restarted, waiting for the operator's OK.
    ShowMode? _pendingMode;
    public ShowMode? PendingMode { get => _pendingMode; set => Set(ref _pendingMode, value); }
    bool _runningWithDMX;
    string? _remoteCode;
    bool _showInspector = true;
    public bool ShowInspector { get => _showInspector; set => Set(ref _showInspector, value); }

    /// The brightness limiter (Workspace.LimiterLevel): a ceiling on every light while testing and setting up.
    /// 1 is off. The app starts at 100 %: a limiter left on from the afternoon's setup never dims the night's show.
    double _limiter = 1;
    public double Limiter { get => _limiter; private set { if (Set(ref _limiter, value)) Changed(nameof(LimiterOn)); } }
    public bool LimiterOn => Limiter < 0.995;

    public void SetLimiter(double level)
    {
        var v = Math.Min(Math.Max(level, Workspace.LimiterMinimum), 1);
        Limiter = v;
        Workspace?.SetLimiterLevel(v);
    }

    /// Follows a change made elsewhere (the web setup page) while the app runs.
    async void WatchLimiter()
    {
        while (true)
        {
            await Task.Delay(TimeSpan.FromSeconds(2));
            if (Workspace is { } ws)
            {
                var v = ws.LimiterLevel();
                if (Math.Abs(v - Limiter) > 0.001) Limiter = v;
            }
        }
    }

    /// Follows changes to the sets and rigs made outside the app (the web setup page, the command line, your AI
    /// assistant through `amadeus mcp`): they are read again, and an open rig editor reloads (RigEditorModel).
    async void WatchConfig()
    {
        _configStamp = Workspace?.ConfigStamp() ?? "";
        while (true)
        {
            await Task.Delay(TimeSpan.FromSeconds(1));
            if (Workspace?.ConfigStamp() is not { } stamp || stamp == _configStamp) continue;
            _configStamp = stamp;
            ReloadSets();
        }
    }
    string _configStamp = "";

    /// Claude Desktop and the assistant server (Settings › Integrations): null until read.
    ClaudeDesktopStatus? _claudeDesktop;
    public ClaudeDesktopStatus? ClaudeDesktop { get => _claudeDesktop; private set => Set(ref _claudeDesktop, value); }

    /// Reads whether Claude Desktop starts the assistant server; when it does with an engine somewhere else (the
    /// app moved, an update, another engine folder chosen), it is pointed at this one again.
    public async Task RefreshClaudeDesktop()
    {
        if (Workspace is not { } ws) { ClaudeDesktop = null; return; }
        var s = await ws.ClaudeDesktop();
        if (s is { On: true, Current: false, Problem: "" }) s = await ws.ClaudeDesktop("on") ?? s;
        ClaudeDesktop = s;
    }

    public async Task SetClaudeDesktop(bool on)
    {
        if (Workspace is not { } ws) return;
        ClaudeDesktop = await ws.ClaudeDesktop(on ? "on" : "off") ?? ClaudeDesktop;
    }

    /// Open the rig editor.
    public void EditLayout() => Section = Section.Rig;

    bool _showZones = Defaults.Standard.Bool("showZones");  // -showZones YES
    public bool ShowZones { get => _showZones; set => Set(ref _showZones, value); }
    string? _playingFile;
    public string? PlayingFile { get => _playingFile; private set { if (Set(ref _playingFile, value)) ShowChanged(); } }
    bool _setupReady;
    public bool SetupReady { get => _setupReady; private set => Set(ref _setupReady, value); }

    (string Key, StageInput Input)? _previewCache;
    readonly SynchronizationContext? _ui = SynchronizationContext.Current;

    /// After the current turn of the UI thread (DispatchQueue.main.async).
    void Later(Action a)
    {
        if (_ui is null) a(); else _ui.Post(_ => a(), null);
    }

    public AppModel(IUpdater? updater = null)
    {
        Updates = new Updates(updater) { IsBusy = () => EngineRunning };
        var d = Defaults.Standard;
        // the show's state follows the engine and the feed
        Engine.PropertyChanged += (_, e) => { if (e.PropertyName is nameof(EngineProcess.State) or nameof(EngineProcess.IsRunning)) ShowChanged(); };
        Feed.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is nameof(LiveFeed.State) or nameof(LiveFeed.Hello) or nameof(LiveFeed.Decks)) ShowChanged();
        };
        EngineProcess.StopLeftover("show");
        EngineProcess.StopLeftover("setup");
        Workspace = Workspace.Locate(d.String("engineRoot"));
        Mode = ShowModes.Parse(d.String("showMode")) ?? (d.BoolIfSet("sendArtNet") == false ? ShowMode.Visualise : ShowMode.Both);
        Feed.Lite = !Mode.Renders3D();
        ReloadSets();
        if (SectionExtensions.Parse(d.String("section")) is { } s) Section = s;  // -section rig
        if (d.String("editSet") is { } editSet && SetsOn(EditingRig).Contains(editSet))
            EditingRigSet = editSet;  // -editSet SET: the rig editor shows where that set hangs (screenshots)
        if (d.Bool("startLive"))  // -startLive YES: start the live show at launch
            Later(() => StartLive());
        else if (d.String("startDJ") is { } dj && d.String("djCode") is { } code)  // -startDJ NAME -djCode 1234
            Later(() => StartLive(dj, code));
        if (d.String("play") is { } file)  // -play FILE [-playFrom SECONDS]: start with a track
        {
            var from = d.Double("playFrom");
            Later(() => Play(file, from));
        }
        Feed.Start();
        Later(() => EditorSelfTest.RunIfRequested(this));  // -editorSelfTest SET (development; it saves into the set and rig SET)
        if (Workspace is { } ws && ws.LimiterLevel() < 1) ws.SetLimiterLevel(1);
        WatchLimiter();
        WatchConfig();
        _ = RefreshClaudeDesktop();
    }

    public bool NeedsSetup => Workspace is null;

    public bool UseWorkspace(string path)
    {
        var ws = new Workspace(path);
        if (!ws.IsValid) return false;
        Workspace = ws;
        Defaults.Standard.Set("engineRoot", path);
        ReloadSets();
        _ = RefreshClaudeDesktop();
        return true;
    }

    /// Installs an optional pack; afterwards the engine runs with it (a release: the packs' environment).
    public async Task<bool> InstallPack(string name)
    {
        if (Workspace is not { } ws || PackInstall.IsRunning) return false;
        // the setup service first: it may run the packs' own python.exe, which Windows won't let the install
        // replace while it runs (started again when needed, with the new packages)
        if (Setup.IsRunning) { Setup.StopAndWait(); SetupReady = false; }
        PackInstall.ClearLog();
        PackInstall.Start(ws, ["packs", "install", name], EngineEnvironment);
        while (PackInstall.IsRunning) await Task.Delay(250);
        // kept: an install that went wrong can be looked into after the window is gone
        CrashLog.Save("Amadeus DMX", "packs.log", PackInstall.Log.Select(l => $"{l.Date:HH:mm:ss} {l.Text}"));
        if (ws.IsBuiltIn && Workspace.BuiltIn is { } fresh) Workspace = fresh;
        return PackInstall.State == EngineState.Stopped;
    }

    /// Back to the engine that comes with the app (after a development folder was chosen).
    public void UseBuiltInWorkspace()
    {
        if (Workspace.BuiltIn is not { } ws) return;
        Workspace = ws;
        Defaults.Standard.Remove("engineRoot");
        ReloadSets();
        _ = RefreshClaudeDesktop();
    }

    /// Reads the sets and rigs again (after any change to them), and keeps a valid selection.
    public void ReloadSets()
    {
        if (Workspace is not { } ws) { Sets = []; Rigs = []; return; }
        ws.Prepare();
        Sets = ws.Sets();
        Rigs = ws.Rigs();
        var d = Defaults.Standard;
        if (SelectedSet.Length == 0 || Sets.All(s => s.Name != SelectedSet))
            SelectedSet = (d.String("lastSet") is { } n && Sets.Any(s => s.Name == n) ? n : null) ?? ws.ActiveSet ?? Sets.FirstOrDefault()?.Name ?? "";
        if (SelectedRig.Length == 0 || Rigs.All(r => r.Name != SelectedRig))
            SelectedRig = (d.String("lastRig") is { } n && Rigs.Any(r => r.Name == n) ? n : null) ?? ws.ActiveRig ?? Rigs.FirstOrDefault()?.Name ?? "";
        // the show runs a combination made on the Rigs page (never a set and a rig that were never put together)
        if (!Combinations.Contains(new Combination(SelectedRig, SelectedSet)) && Combinations.Count > 0)
        {
            var c = Combinations[0];
            SelectedRig = c.Rig;
            SelectedSet = c.Set;
        }
        if (EditingSet.Length == 0 || Sets.All(s => s.Name != EditingSet)) EditingSet = SelectedSet;
        if (EditingRig.Length == 0 || Rigs.All(r => r.Name != EditingRig)) EditingRig = SelectedRig;
        if (EditingRigSet.Length > 0 && !SetsOn(EditingRig).Contains(EditingRigSet) || EditingRigSet.Length == 0)
            EditingRigSet = RigSetDefault(EditingRig);  // also once the rigs are read: a rig opens with a set on it
        _previewCache = null;
        ConfigVersion++;
        Derived();
    }

    void SelectionChanged()
    {
        _previewCache = null;
        if (SelectedSet.Length > 0) Defaults.Standard.Set("lastSet", SelectedSet);
        if (SelectedRig.Length > 0) Defaults.Standard.Set("lastRig", SelectedRig);
    }

    public SetSummary? CurrentSet => Sets.FirstOrDefault(s => s.Name == SelectedSet);
    public RigSummary? CurrentRig => Rigs.FirstOrDefault(r => r.Name == SelectedRig);

    /// How much of the set hangs on the rig: (mounted, all).
    public (int Placed, int Total) Mounted => Workspace?.Mounted(SelectedRig, SelectedSet) ?? (0, 0);

    /// Picks the rig (and the set) for the show.
    public void Choose(string? rig = null, string? set = null)
    {
        if (EngineRunning) return;
        if (rig is not null) SelectedRig = rig;
        if (set is not null) SelectedSet = set;
    }

    /// Auto-mount the set's fixtures that aren't mounted on the rig yet (or all of them).
    public async Task AutoMount(string rig, string set, bool all = false)
    {
        if (!await EnsureSetupService()) throw SetupAPIException.NotRunningError();
        await Api.Automount(rig, set, all: all);
        ReloadSets();
    }

    // MARK: show state

    /// The engine or the feed changed: so did what follows from them.
    void ShowChanged() => Changed(nameof(ShowState), nameof(ShowTitle), nameof(EngineRunning), nameof(DjWaiting));

    public ShowState ShowState => Engine.State.Kind switch
    {
        EngineStateKind.Failed => ShowState.Failed(Engine.State.Reason),
        EngineStateKind.Starting => ShowState.Starting,
        EngineStateKind.Running when PlayingFile is not null =>
            Feed.State == FeedState.Connected && Feed.Hello is not null ? ShowState.Playing : ShowState.Starting,
        EngineStateKind.Running => Feed.Decks.Any(d => d.Play) && Feed.Hello is not null ? ShowState.Live : ShowState.WaitingForDJ,
        _ => Feed.State == FeedState.Connected && Feed.Hello is not null ? ShowState.Attached : ShowState.Stopped,
    };

    public bool EngineRunning => Engine.IsRunning;

    /// The DJ laptop the show follows (Amadeus Link), when it isn't this computer.
    string? _remoteDJ;
    public string? RemoteDJ { get => _remoteDJ; private set { if (Set(ref _remoteDJ, value)) ShowChanged(); } }
    /// The DJ software a live show on this computer follows (from the engine's list; VirtualDJ unless chosen).
    DJSource? _liveSource;
    public DJSource? LiveSource { get => _liveSource; private set { if (Set(ref _liveSource, value)) ShowChanged(); } }

    /// Who the show waits for or follows, for people: the DJ laptop, else the DJ software.
    public string DjName => RemoteDJ ?? LiveSource?.App ?? "VirtualDJ";

    /// What to do while the show waits for the DJ software.
    public string DjWaiting => RemoteDJ is { } r ? $"Waiting for {r}…"
        : LiveSource?.Waiting ?? "Load a track in VirtualDJ with AmadeusLink as master effect.";

    /// The show's state for people: "Waiting for djay Pro" rather than a fixed name.
    public string ShowTitle => ShowState.Kind == ShowStateKind.WaitingForDJ ? $"Waiting for {DjName}" : ShowState.Title;

    /// The DJ software Start (Ctrl+R) follows: the last one chosen in the Start menu.
    public string NextSourceName => Workspace?.DJSource(Defaults.Standard.String("djSource") ?? "vdj")?.App ?? "VirtualDJ";

    /// With a DJ laptop: whether Windows Firewall keeps its decks (UDP) away from the engine.
    FirewallWatch? _engineFirewall;
    public FirewallWatch? EngineFirewall { get => _engineFirewall; private set => Set(ref _engineFirewall, value); }

    void WatchFirewall(Workspace? ws)
    {
        EngineFirewall?.Dispose();
        EngineFirewall = null;
        if (ws is null || !OperatingSystem.IsWindows()) return;
        var watch = new FirewallWatch("Amadeus DMX engine", ws.ListeningPythons(), [(NetProtocol.Udp, null)]);
        watch.PropertyChanged += (_, _) => Changed(nameof(EngineFirewall));  // the footer rebuilds with the model
        EngineFirewall = watch;
        watch.Start(TimeSpan.FromSeconds(30));
    }

    /// Start live mode: the lights follow the DJ software on this computer (VirtualDJ, Mixxx, …) or on a DJ laptop.
    public void StartLive(string? dj = null, string? code = null, string? source = null)
    {
        if (Workspace is not { } ws || SelectedSet.Length == 0) return;
        Section = Section.Show;  // starting a show: watch it
        PlayingFile = null;
        RemoteDJ = dj;
        _remoteCode = code;
        var d = Defaults.Standard;
        if (source is not null) d.Set("djSource", source);
        LiveSource = dj is null ? ws.DJSource(source ?? d.String("djSource") ?? "vdj") : null;
        _runningWithDMX = SendArtNet;
        var args = new List<string> { "live", "--set", SelectedSet, "--rig", SelectedRig, "--health", "30" };
        WatchFirewall(dj is not null ? ws : null);
        if (dj is not null && code is not null) args.AddRange(["--remote", "dj:" + dj, "--code", code]);
        else if ((source ?? d.String("djSource")) is { } src && src != "vdj")
            args.AddRange(["--source", src]);  // another DJ software on this computer (the last one chosen in the Start menu)
        if (SendArtNet) args.Insert(1, "--artnet");
        Engine.Start(ws, args, EngineEnvironment, readyWhen: "Live mode", keepAwake: true);
    }

    /// Play a track with the engine itself (no VirtualDJ): to try a set or a look.
    public void Play(string file, double from = 0)
    {
        if (Workspace is not { } ws || SelectedSet.Length == 0) return;
        Section = Section.Show;  // starting a show: watch it
        PlayingFile = file;
        WatchFirewall(null);
        _runningWithDMX = SendArtNet;
        var args = new List<string> { "play", file, "--set", SelectedSet, "--rig", SelectedRig };
        if (SendArtNet) args.Add("--artnet");
        if (from > 0) args.AddRange(["--start", ((int)from).ToString(System.Globalization.CultureInfo.InvariantCulture)]);
        if (Defaults.Standard.Bool("muted")) args.Add("--mute");  // -muted YES (testing)
        Engine.Start(ws, args, EngineEnvironment, readyWhen: "Visualiser", keepAwake: true);
    }

    public void StopShow() => Engine.Stop();

    /// Switch the mode. Turning the lights on or off needs a new engine: a running show asks first.
    public void SetMode(ShowMode m)
    {
        if (EngineRunning && m.SendsDMX() != _runningWithDMX) PendingMode = m;
        else Mode = m;
    }

    /// The operator said yes: switch and restart the show where it was.
    public async void ConfirmPendingMode()
    {
        if (PendingMode is not { } m) return;
        PendingMode = null;
        Mode = m;
        var (file, at, dj, code) = (PlayingFile, Feed.Time, RemoteDJ, _remoteCode);
        Engine.Stop();
        for (var i = 0; i < 80 && Engine.IsRunning; i++) await Task.Delay(100);
        if (file is not null) Play(file, at); else StartLive(dj, code);
    }

    public IReadOnlyDictionary<string, string> EngineEnvironment
    {
        get
        {
            var env = new Dictionary<string, string>();
            if (Workspace is { } ws) foreach (var (k, v) in ws.Environment) env[k] = v;  // where the engine and your data are
            if (Keychain.OpenAIKey is { Length: > 0 } key) env["OPENAI_API_KEY"] = key;
            if (Defaults.Standard.String("ollamaHost") is { Length: > 0 } host) env["OLLAMA_HOST"] = host;
            return env;
        }
    }

    // MARK: setup service (the engine's setup API, for the wizard and the rig tools)

    public async Task<bool> EnsureSetupService()
    {
        if (await Api.IsUp()) { SetupReady = true; return true; }
        if (Workspace is not { } ws) return false;
        if (!Setup.IsRunning) Setup.Start(ws, ["setup", "--port", "8181"], EngineEnvironment, readyWhen: "Fixture setup");
        for (var i = 0; i < 60; i++)
        {
            if (await Api.IsUp()) { SetupReady = true; return true; }
            await Task.Delay(250);
        }
        return false;
    }

    /// Start the setup service again (e.g. with a new OpenAI key or Ollama address), when it runs.
    public async Task RestartSetupService()
    {
        if (!Setup.IsRunning) return;
        await Task.Run(() => Setup.StopAndWait(2));
        SetupReady = false;
        await EnsureSetupService();
    }

    /// Before the app quits: stop the engine cleanly, so it blacks out the lights before it exits.
    public void Shutdown()
    {
        Engine.StopAndWait();
        Setup.StopAndWait(2);
    }

    // MARK: what the stage shows

    /// The running show's rig, or a preview of the selected set.
    public StageInput? StageInput()
    {
        if (Feed.Hello is { } h && Feed.State == FeedState.Connected)
            return new StageInput
            {
                Key = $"show:{h.Stage.WidthM}:{h.Screen}:{AmadeusDMX.StageInput.Layout(h.Fixtures, h.Trusses)}", Fixtures = h.Fixtures,
                Stage = h.Stage, Screen = h.Screen, Hello = h, Trusses = h.Trusses, Zones = ShowZones ? h.Zones : [],
            };
        return Preview(SelectedRig, SelectedSet);
    }

    /// The set on the rig, before a show runs. Cached until the selection changes or a save (`ReloadSets`).
    public StageInput? Preview(string rig, string set)
    {
        var key = $"{rig}/{set}";
        if (_previewCache is { } c && c.Key == key) return c.Input;
        if (Workspace?.Preview(rig, set) is not { } p) return null;
        var input = new StageInput
        {
            Key = $"preview:{key}:{AmadeusDMX.StageInput.Layout(p.Fixtures, p.Trusses)}", Fixtures = p.Fixtures, Stage = p.Stage,
            Screen = p.Screen, Trusses = p.Trusses,
        };
        _previewCache = (key, input);
        return input;
    }
}
