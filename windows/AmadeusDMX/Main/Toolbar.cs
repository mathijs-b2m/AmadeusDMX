// The toolbar: the set, the show's status, the mode and the start/stop button.
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using static AmadeusDMX.Formatting;

namespace AmadeusDMX;

/// The rig and the set the show runs with: "showcase on club". Most people have one set, and a rig per venue.
public sealed class SetMenu(AppModel model)
{
    public FrameworkElement Build()
    {
        var button = UI.MenuButton(new Border(), () =>
        {
            var combos = model.Combinations;
            var current = new AppModel.Combination(model.SelectedRig, model.SelectedSet);
            var items = new List<MenuFlyoutItemBase>();
            if (combos.Count == 0) items.Add(UI.Note("No set is placed on a rig yet"));
            else items.AddRange(combos.Select(c => UI.Choice(c.Label, "show", c == current, () => model.ChooseShow(c))));
            items.Add(UI.Separator());
            items.Add(UI.Item("Place Sets on Rigs…", () =>
            {
                model.EditingRig = model.SelectedRig;
                model.EditingRigSet = model.SelectedSet;
                model.Section = Section.Rig;
            }, "square.split.bottomrightquarter"));
            return UI.Menu([.. items]);
        });
        return button.Bind(model, [nameof(AppModel.Combinations), nameof(AppModel.ShowLabel), nameof(AppModel.EngineRunning)], b =>
        {
            b.Content = UI.Label("square.split.bottomrightquarter", model.Combinations.Count == 0 ? "No Combination" : model.ShowLabel);
            b.IsEnabled = !model.EngineRunning;
            b.Tooltip(model.EngineRunning ? "A show runs with this set on this rig; stop it to switch"
                : "The set on the rig the show runs with: the combinations made on the Rigs page");
        });
    }
}

public sealed class StatusPill(AppModel model)
{
    public FrameworkElement Build()
    {
        var time = UI.Text("", Font.Callout).Secondary().Bind(model.Feed, nameof(LiveFeed.Time), t => t.Text = TimeString(model.Feed.Time));
        UIElement Content()
        {
            var state = model.ShowState;
            var dot = new Ellipse { Width = 8, Height = 8, Fill = Tint.Brush(state.Color), VerticalAlignment = VerticalAlignment.Center };
            if (model.Feed.Hello is { } h && state.IsActive)
            {
                var phrase = model.Feed.Phrase;
                var d = phrase >= 0 && phrase < h.Plan.Count ? h.Plan[phrase] : null;
                var section = d is null ? null : new Border
                {
                    Background = Tint.Brush(Tint.From(AmadeusKit.Sections.Color(d.Section)), 0.85),
                    CornerRadius = new CornerRadius(999),
                    Padding = new Thickness(7, 2, 7, 2),
                    Child = UI.Text(Capitalized(d.Section), Font.Caption).Bold().Foreground(Tint.White),
                };
                return UI.HStack(8, dot, UI.Text(h.Title, Font.Callout).MaxWidth(260), section);
            }
            return UI.HStack(8, dot, UI.Text(model.ShowTitle, Font.Callout).Secondary());
        }
        // rebuilt when the state, the track or the phrase changes; the time alone follows the feed 5 times a second,
        // beside it (one element can't move into each new rebuild: WinUI refuses an element with a parent still)
        var live = UI.Live(model, Content, nameof(AppModel.ShowState), nameof(AppModel.ShowTitle))
            .Bind(model.Feed, [nameof(LiveFeed.Hello), nameof(LiveFeed.Phrase)], c => c.Content = Content());
        time.Bind(model, [nameof(AppModel.ShowState)], t => t.Visible(model.Feed.Hello is not null && model.ShowState.IsActive))
            .Bind(model.Feed, [nameof(LiveFeed.Hello)], t => t.Visible(model.Feed.Hello is not null && model.ShowState.IsActive));
        return UI.HStack(8, live, time).Padding(12, 0);
    }
}

/// Who decides the show: the rules (instant, offline) or an AI model. It belongs to the set; a running live
/// show follows a change (the rules' plan plays until the AI's plan is ready).
public sealed class DirectorMenu(AppModel model)
{
    IReadOnlyList<DirectorOption> _options = [];
    string _current = "";
    string? _problem;
    DropDownButton? _button;

    string Short => _current switch
    {
        "" or "rules" => "Rules",
        var d when d.StartsWith("ollama:", StringComparison.Ordinal) => "AI · " + d[7..],
        _ => "AI",
    };

    public FrameworkElement Build()
    {
        _button = UI.MenuButton(new Border(), () =>
        {
            var items = _options.Select(d =>
            {
                var i = UI.Choice(d.Available ? d.Label : $"{d.Label} ({d.Note ?? "not available"})", "director", d.Value == _current,
                                  () => Choose(d.Value));
                i.IsEnabled = d.Available;
                return (MenuFlyoutItemBase)i;
            }).ToList();
            if (_problem is not null) items.Add(UI.Note(_problem));
            return UI.Menu([.. items]);
        });
        Show();
        // the set's director: read again whenever the show's set or rig changes (SwiftUI's .task(id:))
        return _button.Bind(model, [nameof(AppModel.SelectedRig), nameof(AppModel.SelectedSet)], b => { _ = Load(); });
    }

    void Show()
    {
        if (_button is null) return;
        _button.Content = UI.Label(_current is "rules" or "" ? "list.bullet.rectangle" : "sparkles", Short);
        _button.IsEnabled = model.SelectedSet.Length > 0;
        _button.Tooltip($"Decision model of this set: {_options.FirstOrDefault(o => o.Value == _current)?.Label ?? _current}");
    }

    async Task Load()
    {
        var (rig, set) = (model.SelectedRig, model.SelectedSet);
        Show();
        if (set.Length == 0 || !await model.EnsureSetupService()) return;
        try
        {
            _options = await model.Api.Directors();
            var raw = await model.Api.Rig(rig, set);
            if ((rig, set) != (model.SelectedRig, model.SelectedSet)) return;  // changed meanwhile: that load wins
            _current = raw.GetValueOrDefault("director")?.String ?? "rules";
        }
        catch (Exception e) when (e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException) { }
        Show();
    }

    async void Choose(string value)
    {
        var before = _current;
        _current = value;
        Show();
        try
        {
            await model.Api.SetDirector(value, model.SelectedRig, model.SelectedSet);
            _problem = null;
        }
        catch (Exception e) when (e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException)
        {
            _current = before;
            _problem = $"Couldn't switch: {e.Message}";
        }
        Show();
    }
}

public sealed class ModeMenu(AppModel model)
{
    public FrameworkElement Build()
    {
        var button = UI.MenuButton(new Border(), () => UI.Menu([.. ShowModes.All.Select(m =>
            (MenuFlyoutItemBase)UI.Choice(m.Title(), "mode", model.Mode == m, () => model.SetMode(m), m.Symbol()).Tooltip(m.Detail()))]));
        return button.Bind(model, nameof(AppModel.Mode), b =>
        {
            b.Content = UI.Label(model.Mode.Symbol(), model.Mode.Title());
            b.Tooltip($"{model.Mode.Title()}: {model.Mode.Detail()}");
        });
    }
}

public sealed class EngineButton(AppModel model, MainWindow window)
{
    public FrameworkElement Build() => UI.Live(model, Content, nameof(AppModel.EngineRunning));

    UIElement Content()
    {
        if (model.EngineRunning)
            return UI.Button("Stop", model.StopShow, "stop.fill").Tooltip("Stop the show (the lights black out) Ctrl+R");
        var start = new SplitButton { Content = UI.Label("play.fill", "Start") };
        start.Click += (_, _) => model.StartLive();
        var flyout = new MenuFlyout();
        flyout.Opening += (_, _) =>
        {
            flyout.Items.Clear();
            foreach (var dj in model.Workspace?.DJSources() ?? [])
            {
                var untested = dj.Verified.StartsWith("not yet", StringComparison.Ordinal) ? ", untested" : "";
                flyout.Items.Add(UI.Item($"Start Live Show ({dj.App}{untested})", () => model.StartLive(source: dj.Name), "dot.radiowaves.left.and.right"));
            }
            flyout.Items.Add(UI.Item("Start with a DJ Laptop…", () => DJLinkSheet.Present(model, window), "laptopcomputer.and.arrow.down"));
            flyout.Items.Add(UI.Item("Play a Track…", () => PlayPanel.Choose(model, window), "music.note"));
        };
        start.Flyout = flyout;
        return start.Bind(model, [nameof(AppModel.Workspace), nameof(AppModel.SelectedSet), nameof(AppModel.ShowState)], b =>
        {
            b.IsEnabled = model.Workspace is not null && model.SelectedSet.Length > 0 && model.ShowState.Kind != ShowStateKind.Attached;
            b.Tooltip(model.ShowState.Kind == ShowStateKind.Attached ? "An engine is already running outside the app"
                : $"Start the live show: the lights follow {model.NextSourceName} Ctrl+R");
        });
    }
}
