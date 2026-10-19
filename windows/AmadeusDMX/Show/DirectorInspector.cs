// What the director decided for the phrase that is playing (or the one you pick).
using static AmadeusDMX.Formatting;

namespace AmadeusDMX;

public sealed class DirectorInspector(AppModel model)
{
    int? _pinned;
    string? _shown;
    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        // built again when what it shows changes (another track, phrase or pin, the AI's progress), not with
        // every feed update: the scroll position and an open disclosure stay put
        var scroll = UI.Scroll(_host);
        _host.BindAll(model.Feed, _ => Refresh());
        return scroll;
    }

    void Refresh(bool force = false)
    {
        var feed = model.Feed;
        var h = feed.Hello;
        var running = h is not null && feed.State == FeedState.Connected && h.Plan.Count > 0;
        var i = running ? Director.Shown(_pinned, feed.Phrase, h!.Plan.Count) : -1;
        var note = running && h!.Plan[i].Source == "rules" ? Director.RulesNote(feed.Decks) : "";
        var key = running ? $"{System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(h)}|{i}|{_pinned is not null}|{note}" : "none";
        if (key == _shown && !force) return;
        _shown = key;
        _host.Rebuild(() => running ? Content(h!, i, note) : NoShow());
    }

    static FrameworkElement NoShow() =>
        UI.Unavailable("wand.and.stars", "No Show Running", "The director's decisions appear here, phrase by phrase.").Margin(0, 80, 0, 0);

    void Pin(int? i)
    {
        _pinned = i;
        Refresh(force: true);
    }

    FrameworkElement Content(Hello h, int i, string rulesNote)
    {
        var d = h.Plan[i];
        var hasLasers = h.Fixtures.Any(f => f.Kind == FixtureKind.Laser);
        var hasGroups = d.Fields.ContainsKey("grouping") && h.Fixtures.Count(f => f.Kind == FixtureKind.Head) > 4;

        var back = UI.IconButton("chevron.left", "", () => Pin(Math.Max(0, i - 1))).Borderless().Disabled(i == 0);
        var forward = UI.IconButton("chevron.right", "", () => Pin(Math.Min(h.Plan.Count - 1, i + 1))).Borderless().Disabled(i == h.Plan.Count - 1);
        var title = UI.VStack(2,
            UI.Text($"Phrase {i + 1} of {h.Plan.Count}", Font.Headline).Center(),
            UI.Text($"{TimeString(d.Start)} – {TimeString(d.End)}", Font.Caption).Secondary().Center());
        title.Alignment = 0.5;
        var sections = new List<UIElement?>
        {
            ShowUI.FormSection(null,
                UI.HStack(back, title.Grow(), forward),
                _pinned is null ? null : UI.Button("Follow the Show", () => Pin(null)).Align(HorizontalAlignment.Stretch)),
            ShowUI.FormSection("Moment",
                ShowUI.Labeled("Section", UI.HStack(6,
                    new Border { Width = 9, Height = 9, CornerRadius = new CornerRadius(4.5), Background = ShowUI.Section(d.Section) },
                    UI.Text(Capitalized(d.Section)).Secondary(),
                    d.DropScore >= Timeline.DropScore ? UI.Icon("bolt.fill").Foreground(Tint.Yellow) : null,
                    Confidence(d, "section"))),
                ShowUI.Labeled("Intensity", IntensityPips.Build(d.Intensity)),
                ShowUI.Labeled("Palette", UI.HStack(4, [
                    UI.Text(Capitalized(d.Palette)).Secondary(),
                    .. Palettes.Colors(d.Palette).Select(c => (UIElement)new Border
                    {
                        Width = 12, Height = 12, CornerRadius = new CornerRadius(3), Background = Tint.Brush(Tint.From(c)),
                    })])),
                ShowUI.Labeled("Decided by", Director.Source(d.Source))),
            ShowUI.FormSection("Pars",
                Row("Between hits", d, "par_base"),
                Row("On a hit", d, "par_accent"),
                Row("A hit is", d, "trigger")),
            ShowUI.FormSection("Moving Heads",
                Row("Light", d, "head_light"),
                Row("Path", d, "movement"),
                Row("Formation", d, "formation"),
                Row("Aim", d, "aim"),
                Row("Colour", d, "head_color"),
                Row("Beam", d, "beam_fx"),
                Row("Gobos", d, "gobo_style"),
                Row("Dynamics", d, "dynamics")),
        };
        if (hasGroups)
            sections.Add(ShowUI.FormSection("Groups",
                Row("Together", d, "grouping"),
                Director.ShowsFeatured(d) ? Row("Featured", d, "featured") : null,
                Row("Layering", d, "layer_split"),
                Row("Base glow", d, "base_glow")));
        if (hasLasers)
            sections.Add(ShowUI.FormSection("Lasers",
                Row("Look", d, "laser_look"),
                d["laser_look"] != "off" ? Row("Movement", d, "laser_move") : null,
                d["laser_look"] != "off" ? Row("Colour", d, "laser_color") : null));
        if (h.Screen)
            sections.Add(ShowUI.FormSection("LED Wall", Row("Shows", d, "screen")));
        if (Director.BestProbabilities(d) is { } probs)
            sections.Add(ShowUI.FormSection($"How Sure: {probs.Title}", [.. probs.Values.Select(v => (UIElement)UI.HStack(8,
                UI.Text(v.Key.Replace('_', ' '), Font.Callout).Frame(width: 110),
                UI.Progress(v.P).Grow(),
                UI.Text(Num.Pct(v.P), Font.Callout).Secondary().Frame(width: 38).AlignRight()))]));
        else if (d.Source == "rules")
            sections.Add(ShowUI.FormSection(null, UI.Text(rulesNote, Font.Callout).Secondary().Wrap()));
        if (d.Prompt.Length > 0)
            sections.Add(ShowUI.FormSection(null, new Expander
            {
                Header = "What the AI was told",
                Content = UI.Text(d.Prompt, Font.MonoCaption).Wrap().Selectable(),
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
            }));
        return UI.VStack(16, [.. sections]).Padding(16, 14);
    }

    /// A decision's value, and how sure the director was of it.
    static Stack Row(string title, Decision d, string key) =>
        ShowUI.Labeled(title, UI.HStack(6, UI.Text(Director.Value(d, key)).Secondary(), Confidence(d, key)));

    static FrameworkElement? Confidence(Decision d, string key)
    {
        if (!d.Confidence.TryGetValue(key, out var v)) return null;
        var tone = Director.Confidence(v);
        return ShowUI.Capsule(UI.Text(Num.Pct(v), Font.Caption2).Foreground(ShowUI.Brush(tone)), ShowUI.Brush(tone, 0.18), 5, 1);
    }
}
