// The sidebar: the pages, and the engine's state at the bottom.
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

    public FrameworkElement Footer() => new EngineFooter(model, window).Build().Padding(10);
}

/// The engine at a glance, at the bottom of the sidebar.
public sealed class EngineFooter(AppModel model, MainWindow window)
{
    public FrameworkElement Build()
    {
        // rebuilt when the app's state or the power meter changes, and when the feed's link or kind changes (not
        // with every frame's time: a button rebuilt 5 times a second can't be clicked)
        var live = UI.Live([model, model.Power], Content)
            .Bind(model.Feed, [nameof(LiveFeed.Link), nameof(LiveFeed.Lite), nameof(LiveFeed.State)], c => c.Content = Content());
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

    UIElement Content()
    {
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
            rows.Add(UI.Label(link.Up ? "laptopcomputer" : "exclamationmark.triangle.fill",
                              link.Up ? $"{link.Name} · {link.JitterMs:F0} ms jitter" : $"{link.Name}: link down", Font.Caption)
                .Foreground(link.Up ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Orange)));
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
            }.Tooltip("DMX Devices & Output… (Ctrl+Shift+D)");
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
