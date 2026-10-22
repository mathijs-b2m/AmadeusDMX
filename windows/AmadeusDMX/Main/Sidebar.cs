// The sidebar: the pages, and at the bottom the engine's state and this version with its updates.
using System.Globalization;

namespace AmadeusDMX;

public sealed class Sidebar(AppModel model, MainWindow window)
{
    /// The pages, for the NavigationView (Tag: the Section).
    public IEnumerable<NavigationViewItem> Items() => SectionExtensions.All.Select(s =>
        new NavigationViewItem { Content = s.Title(), Icon = new FontIcon { Glyph = Symbols.Glyph(s.Symbol()), FontFamily = Theme.SymbolFont }, Tag = s }
            .Tooltip(s.Help())
            .Bind(model, nameof(AppModel.ShowState), i =>
            {
                // the engine page says when the engine stopped by itself
                if (s == Section.Engine) i.InfoBadge = model.ShowState.Kind == ShowStateKind.Failed ? new InfoBadge { Value = -1 } : null;
            }));

    public FrameworkElement Footer() => UI.VStack(6, new EngineFooter(model, window).Build(), new VersionFooter(model).Build()).Padding(10);
}

/// The engine at a glance, at the bottom of the sidebar.
public sealed class EngineFooter(AppModel model, MainWindow window)
{
    public FrameworkElement Build()
    {
        // rebuilt when the app's state or the power meter changes, and when the feed's link or kind changes (not
        // with every frame's time: a button rebuilt 5 times a second can't be clicked). The link comes with every
        // feed update: its jitter moves in place, only another DJ laptop or the link going up or down rebuilds.
        var live = UI.Live([model, model.Power], Content)
            .Bind(model.Feed, [nameof(LiveFeed.Link), nameof(LiveFeed.Lite), nameof(LiveFeed.State)], c =>
            {
                var feed = model.Feed;
                var shape = $"{feed.Link?.Name}|{feed.Link?.Up}|{feed.Lite}|{feed.State}";
                if (shape != _shape) c.Rebuild(Content);
                else if (_linkLine is not null && feed.Link is { } link) _linkLine.Text = LinkLine(link);
            });
        var card = UI.Card(live, padding: 12, corner: 14);
        // the power meter runs while the show does
        return card.Bind(model, nameof(AppModel.EngineRunning), _ => Meter(model.EngineRunning));
    }

    void Meter(bool running)
    {
        // the 3D stage adds its frames' GPU time (Direct3D timestamp queries) to the meter
        StageRenderer.OnGPUTime ??= s => model.Power.GpuSeconds += s;
        if (running) model.Power.Start(() => model.Engine.Pid); else model.Power.Stop();
    }

    string? _shape;
    TextBlock? _linkLine;

    static string LinkLine(LinkStatus link) => link.Up ? $"{link.Name} · {link.JitterMs:F0} ms jitter" : $"{link.Name}: link down";

    UIElement Content()
    {
        _shape = $"{model.Feed.Link?.Name}|{model.Feed.Link?.Up}|{model.Feed.Lite}|{model.Feed.State}";
        _linkLine = null;
        var state = model.ShowState;
        var fps = model.Feed.State == FeedState.Connected && state.IsActive && !model.Feed.Lite
            ? UI.Text("", Font.Caption).Secondary().Bind(model.Feed, nameof(LiveFeed.Fps),
                  t => t.Text = $"{Math.Round(model.Feed.Fps).ToString(CultureInfo.CurrentCulture)} fps")
            : null;
        var rows = new List<UIElement?>
        {
            UI.HStack(8, UI.Icon(state.Symbol).Foreground(state.Color), UI.Text(model.ShowTitle, Font.Callout).Bold(), UI.Spacer(), fps),
        };
        if (model.EngineRunning && model.Power.Measured)
        {
            rows.Add(PowerLine.Build(model.Power, model.Mode.Renders3D()));
            if (model.Mode.SendsDMX() && model.Mode.Renders3D() && model.Power.StageIsHeavy)
                rows.Add(PowerWarning.Build(model.Power, () => model.SetMode(ShowMode.Perform)));
        }
        if (state.Kind == ShowStateKind.Failed)
            rows.Add(UI.Text(state.Reason, Font.Caption).Secondary().Wrap(3));
        else if (model.Feed.Link is { } link && model.EngineRunning)
        {
            var line = UI.Label(link.Up ? "laptopcomputer" : "exclamationmark.triangle.fill", LinkLine(link), Font.Caption)
                .Foreground(link.Up ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Orange));
            _linkLine = line.Children.OfType<TextBlock>().FirstOrDefault();
            rows.Add(line);
            if (model.EngineFirewall is { BlockedOn: { } profile } fw) rows.Add(FirewallRows(fw, profile, link.Name));
        }
        else if (state.Kind == ShowStateKind.WaitingForDJ)
            rows.Add(UI.Text(model.DjWaiting, Font.Caption).Secondary().Wrap());
        else if (state.Kind == ShowStateKind.Attached)
            rows.Add(UI.Text("An engine started outside the app is running; the app shows its lights.", Font.Caption).Secondary().Wrap());
        else if (model.CurrentSet is { } set)
        {
            var output = new HyperlinkButton
            {
                Content = UI.Label("cable.connector", set.IsVirtual || !model.SendArtNet ? "Visualiser only" : set.OutputText, Font.Caption).Secondary(),
                Padding = new Thickness(0),
            }.Tooltip("DMX Output (Ctrl+Shift+D)");
            output.Click += (_, _) => window.OpenDMX();
            rows.Add(output);
        }
        return UI.VStack(6, [.. rows]);
    }

    /// Windows Firewall keeps the DJ laptop's decks from the engine: say so, and let them in.
    static UIElement FirewallRows(FirewallWatch fw, NetProfile profile, string dj) =>
        UI.VStack(4,
            UI.Text($"Windows Firewall keeps {dj}'s decks out on this network (a {Firewall.Name(profile)} network to Windows).",
                    Font.Caption).Foreground(Tint.Orange).Wrap(3),
            UI.Button(fw.Allowing ? "Allowing…" : "Allow the Engine…", () => _ = fw.Allow()).Disabled(fw.Allowing).Font(Font.Caption)
                .Tooltip("Windows asks for an administrator."),
            fw.Note is { } note ? UI.Text(note, Font.Caption).Secondary().Wrap() : null);
}

/// This version and its updates, under the engine's card: not everybody looks in Settings. A newer one gets its
/// one click here; the line opens the update settings. It checks by itself only when checking automatically is on,
/// and never while a show runs.
public sealed class VersionFooter(AppModel model)
{
    public FrameworkElement Build()
    {
        var view = UI.Live(model.Updates, Content).Padding(6, 0);
        view.Loaded += (_, _) => Refresh();
        return view.Bind(model, nameof(AppModel.EngineRunning), _ => { if (!model.EngineRunning) Refresh(); });
    }

    /// The sidebar's own check: only with checking automatically on (opt-in), never during a show.
    void Refresh()
    {
        var u = model.Updates;
        if (u.IsAvailable && u.ChecksAutomatically && !model.EngineRunning) u.Refresh();
    }

    UIElement Content()
    {
        var u = model.Updates;
        var (symbol, color) = !u.IsAvailable ? ("info.circle", (Windows.UI.Color?)null) : u.State switch
        {
            UpdateState.Available => ("arrow.down.circle", Tint.Orange),
            UpdateState.UpToDate => ("checkmark.circle.fill", Tint.Green),
            UpdateState.Failed => ("exclamationmark.triangle.fill", Tint.Orange),
            UpdateState.Installing => (u.WaitingForIdle ? "clock" : "arrow.triangle.2.circlepath", null),
            _ => ("info.circle", null),
        };
        var icon = UI.Icon(symbol, 12);
        if (color is { } c) icon.Foreground(c); else icon.Secondary();
        var line = new HyperlinkButton
        {
            Content = UI.HStack(5, icon, UI.Text(Line(u), Font.Caption).Secondary()),
            Padding = new Thickness(0),
        }.Tooltip(!u.IsAvailable ? "A development build: it updates with the code, not by itself"
            : u.State == UpdateState.Available ? $"{u.Newest} is available: you have {u.Version}. Click for the update settings."
            : "Updates: this version, the newest, and whether to check by itself");
        line.Click += (_, _) => new Flyout { Content = Options(u), Placement = Microsoft.UI.Xaml.Controls.Primitives.FlyoutPlacementMode.RightEdgeAlignedBottom }.ShowAt(line);
        UIElement? action = u.State switch
        {
            UpdateState.Available when u.IsAvailable => UI.Button($"Update to {u.Newest}", () => u.InstallNewest()).Prominent()
                .Disabled(!u.CanCheck).Font(Font.Caption).Tooltip($"Downloads Amadeus DMX {u.Newest} and installs it; Amadeus DMX starts again"),
            UpdateState.Downloading => UI.HStack(4, UI.Progress(u.Progress).Frame(width: 50),
                UI.IconButton("xmark.circle.fill", "Stop the download", u.CancelInstall)),
            _ => null,
        };
        var row = UI.HStack(6, line.Grow(), action);
        row.Alignment = 0.5;
        return row;
    }

    static string Line(Updates u)
    {
        if (!u.IsAvailable) return $"Amadeus DMX {u.Version} · development build";
        return u.State switch
        {
            UpdateState.Available => u.Version,  // the button names the newer one
            UpdateState.Downloading => $"Downloading {u.Newest}…",
            UpdateState.Installing => u.WaitingForIdle ? $"{u.Newest} installs when the show stops" : $"Installing {u.Newest}…",
            UpdateState.Checking => $"Amadeus DMX {u.Version} · checking…",
            UpdateState.UpToDate => $"Amadeus DMX {u.Version} · up to date",
            UpdateState.Failed => $"Amadeus DMX {u.Version} · couldn’t check",
            _ => $"Amadeus DMX {u.Version}",
        };
    }

    /// The flyout: the status with its one click, and whether to check and install by itself.
    static FrameworkElement Options(Updates u)
    {
        if (!u.IsAvailable)
            return UI.VStack(6, UI.Text($"Amadeus DMX {u.Version}", Font.Headline),
                UI.Text("A development build: it updates with the code, not by itself.").Secondary().Wrap()).Frame(width: 340);
        var toggles = UI.Live(u, () => UI.VStack(4,
            UI.Row("Check for updates automatically", UI.Toggle("", u.ChecksAutomatically, v => u.ChecksAutomatically = v)),
            UI.Row("Download and install updates by themselves",
                UI.Toggle("", u.InstallsAutomatically, v => u.InstallsAutomatically = v).Disabled(!u.ChecksAutomatically))));
        return UI.VStack(10,
            UpdateStatusView.Build(u, "Amadeus DMX", "when the show stops"),
            toggles,
            UI.Text(UpdatesSection.Rules, Font.Caption).Secondary().Wrap()).Frame(width: 360);
    }
}

/// What the show costs the computer: the lights against the 3D stage.
public static class PowerLine
{
    public static FrameworkElement Build(PowerMeter power, bool stageOn) =>
        UI.VStack(2,
            Row("Lights", power.Engine.Cpu, null),
            stageOn ? Row("3D stage", power.Stage.Cpu, power.Gpu) : null)
        .Tooltip("CPU use (100% = one core) of the light engine and of the app's 3D stage, and the GPU time the "
                 + $"stage takes. Measured every {(int)PowerMeter.Interval.TotalSeconds} s.");

    // one line each, however narrow the sidebar: a taller footer would push the show's timeline out of the window
    static FrameworkElement Row(string name, double cpu, double? gpu) =>
        UI.HStack(6,
            UI.Text(name, Font.Caption).Secondary().Frame(width: 58),
            UI.Text($"{cpu * 100:F0}% CPU" + (gpu is { } g ? $" · GPU {g * 100:F0}%" : ""), Font.Caption).Secondary().Lines(1));
}

/// The 3D stage costs more than the show can spare: say so, and offer Perform Only.
public static class PowerWarning
{
    // short, on one line with its button (the whole story in the tooltip): the footer must stay low
    public static FrameworkElement Build(PowerMeter power, Action performOnly)
    {
        var ratio = (power.Stage.Cpu + power.Gpu) / Math.Max(power.Engine.Cpu, 0.05);
        string? why = power.Hot ? "The computer is getting hot" : power.LowPower ? "Battery saver is on" : power.OnBattery ? "On battery" : null;
        var cost = ratio >= 1.5 ? $"3D {Math.Round(ratio)}× the lights" : "3D stage is heavy";
        var shortText = power.Hot ? $"Hot · {cost}" : power.LowPower ? $"Battery Saver · {cost}" : power.OnBattery ? $"Battery · {cost}" : cost;
        var longCost = ratio >= 1.5 ? $"the 3D stage takes {Math.Round(ratio)}× what the lights do" : "the 3D stage adds to the load";
        var reason = (why is null ? "" : $"{why}: ") + longCost + ". During a gig, Perform Only keeps the lights on time.";
        var button = UI.Button("Perform Only", performOnly).Font(Font.Caption).Padding(6, 2);
        return UI.HStack(6,
            UI.Label("exclamationmark.triangle.fill", shortText, Font.Caption).Foreground(Tint.Orange),
            UI.Spacer(4),
            button)
        .Tooltip(reason + " Perform Only: the lights only, no 3D stage, so the computer's power goes to the show.");
    }
}
