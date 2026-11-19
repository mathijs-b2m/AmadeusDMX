// Settings (Ctrl+,): the engine folder, updates, the optional packs, the director and its AI key, the DJ software
// integrations (mac/Sources/AmadeusDMX/Settings/SettingsView.swift). On Windows it is the main window's Settings
// page only (the Mac also has a Settings window with the same tabs).
namespace AmadeusDMX;

public sealed class SettingsView(AppModel model)
{
    public FrameworkElement Build()
    {
        var bar = new SelectorBar();
        var tabs = new (string Title, string Symbol, Func<FrameworkElement> Page)[]
        {
            (L("General"), "gearshape", () => new GeneralSettings(model).Build()),
            (L("Director"), "wand.and.stars", () => new DirectorSettings(model).Build()),
            (L("Integrations"), "dot.radiowaves.left.and.right", () => new IntegrationSettings(model).Build()),
        };
        var pages = new FrameworkElement?[tabs.Length];
        var host = new ContentControl
        {
            HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
        };
        foreach (var t in tabs)
            bar.Items.Add(new SelectorBarItem { Text = t.Title, Icon = new FontIcon { Glyph = Symbols.Glyph(t.Symbol), FontFamily = Theme.SymbolFont } });
        bar.SelectionChanged += (_, _) =>
        {
            var i = bar.Items.IndexOf(bar.SelectedItem);
            if (i < 0) return;
            host.Content = pages[i] ??= tabs[i].Page();  // built once: a tab keeps its state
        };
        bar.SelectedItem = bar.Items[0];
        // opened for one tab (Import from Documents… → the OpenAI key): that one
        string[] keys = ["general", "director", "integrations"];
        bar.Bind(model, nameof(AppModel.SettingsTab), b =>
        {
            if (model.SettingsTab is not { } tab) return;
            model.SettingsTab = null;
            if (Array.IndexOf(keys, tab) is var i and >= 0) b.SelectedItem = b.Items[i];
        });
        var root = new Grid();
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var top = UI.HStack(bar).Padding(16, 4);
        top.Alignment = 0.5;
        Grid.SetRow(top, 0);
        Grid.SetRow(host, 1);
        root.Children.Add(top);
        root.Children.Add(host);
        return root;
    }
}

public sealed class GeneralSettings(AppModel model)
{
    string? _error;
    readonly ContentControl _engine = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        _engine.Bind(model, nameof(AppModel.Workspace), c => c.Content = EngineSection());
        var mode = UI.Live(model, ModeSection, nameof(AppModel.Mode));
        return Form.Page(680, _engine, new UpdatesSection(model).Build(), new PacksSection(model).Build(), mode, LanguageSection());
    }

    /// The app's language (AmadeusKit/Strings.cs): Windows's own, or one picked here; each named in its own words.
    static UIElement LanguageSection()
    {
        string[] codes = ["", .. Strings.Languages.Select(l => l.Code)];
        var saved = Defaults.Standard.String(Strings.SettingKey) ?? "";
        var picker = UI.Picker(codes, codes.Contains(saved) ? saved : "",
            c => c.Length == 0 ? L("Same as Windows") : Strings.Languages.First(l => l.Code == c).Name,
            c => { if (c.Length == 0) Defaults.Standard.Remove(Strings.SettingKey); else Defaults.Standard.Set(Strings.SettingKey, c); });
        return Form.Section(null, [Form.Row(L("Language"), picker)], L("Takes effect the next time Amadeus DMX starts."));
    }

    UIElement EngineSection()
    {
        var ws = model.Workspace;
        var path = UI.Text(ws is null ? L("Not set") : ws.IsBuiltIn ? L("Built into the app") : ws.Root, Font.Callout).Secondary();
        path.HorizontalAlignment = HorizontalAlignment.Right;
        var buttons = UI.HStack(8,
            Workspace.BuiltIn is not null && ws?.IsBuiltIn != true ? UI.Button(L("Use Built-in"), () => { _error = null; model.UseBuiltInWorkspace(); }) : null,
            UI.Button(L("Choose Folder…"), Choose));
        var value = UI.VStack(4, path, buttons);
        value.Alignment = 1;
        var rows = new List<UIElement?> { Form.Row(L("Engine"), value.MaxWidth(440)) };
        if (ws is { IsBuiltIn: true })
            rows.Add(Form.Row(L("Your data"), UI.Button(L("Show in File Explorer"), () => Dialogs.ShowInExplorer(ws.Data))));
        if (_error is { } e) rows.Add(UI.Text(e, Font.Callout).Foreground(Tint.Red).Wrap());
        return Form.Section(null, rows, ws?.IsBuiltIn == true
            ? L("Your sets, rigs and fixtures are kept apart from the app, so an update never touches them. A development checkout (with its .venv) can be chosen instead.")
            : L("The Amadeus DMX folder with its Python environment (.venv). The web UI uses the same folder, sets and fixtures."));
    }

    async void Choose()
    {
        if (await Dialogs.ChooseFolder(_engine, L("Choose")) is not { } folder) return;
        _error = model.UseWorkspace(folder) ? null : @"That folder has no engine (amadeus\ and .venv\Scripts\python.exe).";
        _engine.Content = EngineSection();
    }

    UIElement ModeSection()
    {
        var picker = UI.Picker(ShowModes.All, model.Mode, m => m.Title(), model.SetMode);
        return Form.Section(null, [Form.Row(L("Mode"), picker)], L("{0} Perform Only keeps the computer free for the lights at a gig.", model.Mode.Detail()));
    }
}

/// Updates (NetSparkle, Settings/Updater.cs): whether to check and install by itself, and checking now.
public sealed class UpdatesSection(AppModel model)
{
    public FrameworkElement Build() => UI.Live(model.Updates, Content);

    UIElement Content()
    {
        var updates = model.Updates;
        if (!updates.IsAvailable)
            return Form.Section(L("Updates"), [Form.Row(L("Amadeus DMX {0}", updates.Version),
                UI.Text(L("A development build: it updates with the code, not by itself.")).Secondary().Wrap())]);
        var checks = UI.Toggle("", updates.ChecksAutomatically, v => updates.ChecksAutomatically = v);
        var installs = UI.Toggle("", updates.InstallsAutomatically, v => updates.InstallsAutomatically = v).Disabled(!updates.ChecksAutomatically);
        var rows = new List<UIElement?>
        {
            Form.Row(L("Check for updates automatically"), checks),
            Form.Row(L("Download and install updates by themselves"), installs),
            UpdateStatusView.Build(updates, "Amadeus DMX", L("when the show stops")),
        };
        return Form.Section(L("Updates"), rows, Rules);
    }

    public static string Rules => L("Never during a show: no check while the lights run, and an update you install then waits until the show stops. One downloaded by itself is installed when you quit. Your sets, rigs and packs stay as they are.");
}

/// The optional packs (amadeus/cli/packs.py): what each adds, and installing it.
public sealed class PacksSection(AppModel model)
{
    IReadOnlyList<PackInfo> _packs = [];
    string? _installing, _failed;
    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        Show();
        return _host.Bind(model, nameof(AppModel.Workspace), c => { _ = Load(); });
    }

    async Task Load()
    {
        _packs = model.Workspace is { } ws ? await ws.Packs() : [];
        Show();
    }

    void Show()
    {
        var rows = _packs.Select(pack =>
        {
            UIElement action;
            if (pack.Installed) action = UI.Label("checkmark.circle.fill", L("Installed")).Foreground(Tint.Green);
            else if (_installing == pack.Name) action = UI.Spinner();
            else action = UI.Button(L("Install ({0})", pack.Size), () => Confirm(pack)).Disabled(_installing is not null);
            return (UIElement)UI.VStack(6,
                Form.Row(pack.Title, action),
                UI.Text(pack.About, Font.Callout).Secondary().Wrap(),
                _installing == pack.Name
                    ? UI.Text("", Font.MonoCaption).Secondary().Bind(model.PackInstall, nameof(EngineProcess.LastLine), t => t.Text = model.PackInstall.LastLine)
                    : null,
                _failed == pack.Name
                    ? UI.Text(L("Not installed: {0}", model.PackInstall.Log.LastOrDefault(l => l.IsError)?.Text ?? model.PackInstall.LastLine), Font.Callout)
                        .Foreground(Tint.Red).Wrap()
                    : null);
        }).ToList();
        _host.Content = Form.Section(L("Optional packs"), rows,
            L("Downloaded from the internet when you install them, then they work offline. They take effect at the next show."));
    }

    async void Confirm(PackInfo pack)
    {
        if (await Dialogs.Confirm(_host.XamlRoot, L("Install {0}?", pack.Title), pack.Note.Length == 0 ? pack.About : pack.Note,
                                  L("Install ({0})", pack.Size)))
            Install(pack.Name);
    }

    async void Install(string name)
    {
        _installing = name;
        _failed = null;
        Show();
        var ok = await model.InstallPack(name);  // `amadeus packs install NAME`: its stdin stays open while it runs
        _packs = model.Workspace is { } ws ? await ws.Packs() : [];
        _installing = null;
        if (!ok) _failed = name;
        Show();
    }
}

public sealed class DirectorSettings(AppModel model)
{
    public FrameworkElement Build() =>
        Form.Page(680,
            new DirectorChoiceSection(model).Build(),
            Form.Section(L("AI Director: OpenAI API key"), [new OpenAIKeyView(model).Build()],
                L("With a key, the AI director (OpenAI) decides the show; without one, the rule-based director does. Your key is kept in Windows Credential Manager and handed to the engine when it starts, never written to a file, and only sent to OpenAI.")));
}

/// What each DJ software integration needs or may do: one section per DJ software.
public sealed class IntegrationSettings(AppModel model)
{
    public FrameworkElement Build() =>
        Form.Page(680, new VirtualDJSection(model).Build(), new MixxxSection().Build(), new StreamedSection(model).Build(),
                  new AssistantSection(model).Build());
}

/// Your own AI assistant (amadeus mcp, docs/ai-assistants.md): Claude Desktop starts the engine's assistant server and
/// can then make and change your sets and rigs. Off until switched on; the engine writes Claude's config.
public sealed class AssistantSection(AppModel model)
{
    bool _busy;
    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        _host.Loaded += async (_, _) =>  // while it shows: Claude's config can change elsewhere (Claude, another app)
        {
            Show();
            while (_host.IsLoaded)
            {
                if (!_busy) await model.RefreshClaudeDesktop();
                await Task.Delay(TimeSpan.FromSeconds(5));
            }
        };
        _host.Bind(model, nameof(AppModel.ClaudeDesktop), _ => Show());
        Show();
        return _host;
    }

    void Show()
    {
        var status = model.ClaudeDesktop;
        var toggle = UI.Toggle("", status?.On ?? false, v => _ = Switch(v))
            .Disabled(_busy || status is null || status is { Installed: false, On: false });
        var rows = new List<UIElement?>
        {
            Form.Row(UI.VStack(2, UI.Text(L("Claude Desktop can work on your sets and rigs")),
                    UI.Text(L("Ask Claude to make a rig for a venue from its PDFs, add fixtures, mount them or check what is unfinished. It uses your own Claude subscription."), Font.Caption).Secondary().Wrap()),
                toggle),
        };
        if (status is { Problem.Length: > 0 })
            rows.Add(Form.Note("exclamationmark.triangle", status.Problem, Tint.Orange));
        else if (status is { Installed: false })
            rows.Add(Form.Note("info.circle", L("Claude Desktop isn't installed (or hasn't been opened yet).")));
        else if (status is { On: true })
            rows.Add(Form.Note("checkmark.circle", L("Restart Claude Desktop to pick this up (quit it from the notification area). In a new chat, amadeus-dmx is under the tools button.")));
        rows.Add(UI.HStack(0, UI.Spacer(), UI.Link(L("Other assistants (Claude Code, Codex)…"), () => Dialogs.OpenURL(HelpLinks.Assistants)).Font(Font.Callout)));
        _host.Content = Form.Section(L("Your AI assistant"), rows,
            L("Everything it saves is checked as in the app, and before each change your sets and rigs are copied aside: ask it to undo. It can't delete sets or rigs, switch lights on or change a show that is running. An open rig editor shows its changes, or asks first when you have unsaved changes there."));
    }

    async Task Switch(bool on)
    {
        _busy = true;
        Show();
        await model.SetClaudeDesktop(on);
        _busy = false;
        Show();
    }
}

/// Streamed tracks (Spotify in djay Pro and VirtualDJ, here or on a DJ laptop through Amadeus Link): a copy of the
/// same recording, downloaded to analyse it (amadeus/show/sources/streamed.py). One switch for all, off by default.
public sealed class StreamedSection(AppModel model)
{
    bool _on;
    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        _host.Loaded += (_, _) => { Read(); Show(); };
        Read();
        Show();
        return _host;
    }

    void Read() =>
        _on = (model.Workspace?.IntegrationSetting("streamed", "on") ?? false)
              || (model.Workspace?.IntegrationSetting("djay", "streamed") ?? false);  // the switch as djay's own, from before

    void Show()
    {
        var toggle = UI.Toggle("", _on, v => { if (v) _ = Confirm(); else Save(false); }).Disabled(model.Workspace is null);
        var rows = new List<UIElement?>
        {
            Form.Row(UI.VStack(2, UI.Text(L("Light streamed tracks")),
                    UI.Text(L("Spotify tracks in djay Pro and VirtualDJ have no file to analyse. When one is loaded on a deck (on this computer, or on a DJ laptop through Amadeus Link), a copy of the same recording is downloaded from YouTube (yt-dlp, once per track) and analysed. The audience still hears the DJ software's own stream. Needs an internet connection during the show."), Font.Caption).Secondary().Wrap()),
                toggle),
        };
        if (_on && model.Workspace?.HasPythonPackage("yt_dlp") == false)
            rows.Add(Form.Note("exclamationmark.triangle", L("yt-dlp isn't installed: install Streamed tracks under General › Optional packs"), Tint.Orange));
        _host.Content = Form.Section(L("Streamed tracks"), rows,
            L("Off by default. Downloading from YouTube goes against YouTube's terms of service and may not be allowed by copyright law where you are. Only switch this on for music you may copy; you are responsible for that choice. Needs an internet connection: a track is fetched when it is loaded on a deck (a few seconds); offline, streamed tracks stay dark, while tracks fetched before still light. Copies stay on this computer (the engine's .cache\\streamed) and are used only to analyse the track. Takes effect at the next live show."));
    }

    async Task Confirm()
    {
        var yes = await Dialogs.Confirm(_host.XamlRoot, L("Download copies of streamed tracks?"),
            L("Each Spotify track you load in djay Pro or VirtualDJ is downloaded from YouTube to analyse it. That goes against YouTube's terms of service and may not be allowed where you are. Only use it for music you may copy."),
            L("Switch On"));
        Save(yes);
    }

    void Save(bool value)
    {
        model.Workspace?.SetIntegrationSetting("streamed", "on", value);
        if (!value) model.Workspace?.SetIntegrationSetting("djay", "streamed", false);  // off means off, also the old one
        _on = value;
        Show();
    }
}

public sealed class VirtualDJSection(AppModel model)
{
    string _message = "";
    VirtualDJPlugin.Status _installed = VirtualDJPlugin.Status.NotInstalled;
    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    /// The plugin this app installs: the engine's build of it (engine\vdj\build\AmadeusLink.dll), else one beside the app.
    string? Bundled
    {
        get
        {
            if (model.Workspace?.PluginBundle is { } p && File.Exists(p)) return p;
            var beside = Path.Combine(AppContext.BaseDirectory, "vdj", "AmadeusLink.dll");
            return File.Exists(beside) ? beside : model.Workspace?.PluginBundle;
        }
    }

    public FrameworkElement Build()
    {
        _host.Loaded += (_, _) => { _installed = VirtualDJPlugin.StatusComparedTo(Bundled); Show(); };
        _installed = VirtualDJPlugin.StatusComparedTo(Bundled);
        Show();
        return _host;
    }

    string InstalledText => _installed switch
    {
        VirtualDJPlugin.Status.NotInstalled => L("Not installed"),
        VirtualDJPlugin.Status.UpToDate => L("Installed"),
        _ => L("An update is ready"),
    };

    void Show()
    {
        var bundled = Bundled;
        var status = UI.Text(InstalledText);
        if (_installed == VirtualDJPlugin.Status.Outdated) status.Foreground(Tint.Orange); else status.Secondary();
        var button = UI.Button(_installed == VirtualDJPlugin.Status.Outdated ? L("Update Plugin") : L("Install Plugin"), () => Install(bundled))
            .Disabled(bundled is null || !File.Exists(bundled) || _installed == VirtualDJPlugin.Status.UpToDate);
        _host.Content = Form.Section(L("VirtualDJ"),
            [
                Form.Row(L("AmadeusLink plugin"), status),
                UI.HStack(8, UI.Spacer(), _message.Length > 0 ? UI.Text(_message).Secondary().Wrap() : null, button),
            ],
            L("In VirtualDJ, add AmadeusLink as master effect. It sends every deck's position, tempo and volume to the engine (UDP 9123). Restart VirtualDJ after installing. On a separate DJ laptop, Amadeus Link installs it."));
    }

    void Install(string? bundled)
    {
        if (bundled is null) return;
        try
        {
            VirtualDJPlugin.Install(bundled);
            _message = L("Installed. Restart VirtualDJ.");
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            _message = e.Message;
        }
        _installed = VirtualDJPlugin.StatusComparedTo(bundled);
        Show();
    }
}

/// Mixxx (Windows only: the Mac makes its virtual MIDI device itself): the engine talks to Mixxx's controller script
/// over a MIDI port called "Amadeus DMX", which has to exist before Mixxx starts (amadeus/show/sources/winmidi.py).
public sealed class MixxxSection
{
    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        _host.Loaded += (_, _) => Show();
        Show();
        return _host;
    }

    void Show()
    {
        var ports = MidiPorts.Inputs();
        var found = MixxxPort.Matching(ports) is { } i ? ports[i] : null;
        var status = found is not null
            ? Form.Note("checkmark.circle.fill", L("MIDI port “{0}”: ready", found), Tint.Green)
            : Form.Note("exclamationmark.triangle", L("No MIDI port “{0}” on this computer", MixxxPort.Name), Tint.Orange);
        var rows = new List<UIElement?> { Form.Row(status, UI.Button(L("Look Again"), Show)) };
        if (found is null)
            rows.Add(UI.Text(
                L("Windows can't make one for a program the way macOS does. On Windows 11 24H2 and later, Windows MIDI Services has loopback ports: make one called “{0}” in the MIDI Settings app. Or install loopMIDI (tobias-erichsen.de) and add a port called “{0}”. Then start Mixxx, and the show again.", MixxxPort.Name),
                Font.Callout).Secondary().Wrap());
        _host.Content = Form.Section(L("Mixxx"), rows,
            L("In Mixxx, Preferences › Controllers: enable the “Amadeus DMX” controller with the Amadeus DMX mapping, once. Start the show first, then Mixxx; the port must be there before Mixxx starts."));
    }
}
