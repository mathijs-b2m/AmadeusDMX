// VirtualDJ's decks: what each one plays and how far its show is prepared.
namespace AmadeusDMX;

public sealed class DecksCard(AppModel model)
{
    string? _shape;
    readonly List<(int Deck, ProgressBar Bar)> _volumes = [];
    TextBlock? _linkLine;

    public FrameworkElement Build()
    {
        var host = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };
        // rebuilt when what it shows changes; the volumes and the link's numbers move in place (5 times a second)
        host.Bind(model.Feed, [nameof(LiveFeed.Decks), nameof(LiveFeed.Link)], c =>
        {
            var shape = Decks.Shape(model.Feed.Decks, model.Feed.Link);
            if (shape != _shape || c.Content is null)
            {
                _shape = shape;
                c.Rebuild(Content);
            }
            Update();
        });
        return ShowUI.Glass(host).Frame(width: 330);
    }

    void Update()
    {
        foreach (var (deck, bar) in _volumes)
            if (model.Feed.Decks.FirstOrDefault(d => d.Deck == deck) is { } d) bar.Value = Math.Min(1, d.Vol);
        if (_linkLine is not null && model.Feed.Link is { } link) _linkLine.Text = Decks.LinkLine(link);
    }

    UIElement Content()
    {
        _volumes.Clear();
        _linkLine = null;
        var rows = new List<UIElement?>();
        if (model.Feed.Link is { } link)  // VirtualDJ on a DJ laptop: how the link is doing
        {
            _linkLine = UI.Text(Decks.LinkLine(link), Font.Caption2).Secondary();
            rows.Add(UI.HStack(6,
                UI.Icon("laptopcomputer").Foreground(link.Up ? Tint.Green : Tint.Orange),
                UI.Text(link.Name, Font.Caption).Bold().Lines(1),
                UI.Spacer(),
                _linkLine));
            if (link.Fetching.Count > 0)
                rows.Add(UI.Label("arrow.down.circle", $"Fetching {string.Join(", ", link.Fetching)}", Font.Caption2).Secondary().Leading());
        }
        foreach (var d in model.Feed.Decks) rows.Add(DeckRow(d));
        return UI.VStack(10, [.. rows]);
    }

    UIElement DeckRow(DeckInfo deck)
    {
        var number = new Border
        {
            Width = 20, Height = 20, CornerRadius = new CornerRadius(10),
            Background = deck.Play ? Tint.Brush(Tint.Accent) : ShowUI.Brush(Tone.Secondary, 0.3),
            Child = UI.Text($"{deck.Deck}", Font.Caption).Bold().Foreground(Tint.White).Center(),
        };
        var volume = UI.Progress(Math.Min(1, deck.Vol));
        volume.Foreground = Tint.Brush(deck.Play ? Tint.Green : Tint.Gray);
        _volumes.Add((deck.Deck, volume));
        var rows = new List<UIElement?>
        {
            UI.HStack(8,
                number,
                UI.Text(deck.Track, Font.Callout).Lines(1),
                deck.Genre == "cinematic" ? UI.Icon("film.stack").Foreground(Tint.Orange).Tooltip("Cinematic program") : null,  // a program of its own: say so
                GenreChip.Build(deck.Genre ?? "", style: deck.Style ?? ""),
                UI.Spacer(),
                UI.Icon(deck.Play ? "play.fill" : "pause.fill", Theme.Size(Font.Caption)).Secondary()),
            volume,
        };
        if (deck.Status is { } s)
        {
            // the steps go on in a second line where they don't fit (Segoe UI is wider than the Mac's font)
            var steps = UI.Flow(6, [.. Decks.Steps(s).Select(StepChip)]);
            if (s.Lights is { } l) steps.Children.Add(UI.Text(Decks.Lights(l), Font.Caption2).Secondary());
            rows.Add(steps);
        }
        return UI.VStack(5, [.. rows]);
    }

    /// A preparation step: static symbols (a spinning icon would redraw the window every frame).
    static UIElement StepChip(Decks.Step step) =>
        ShowUI.Capsule(UI.HStack(3, UI.Icon(step.Symbol, Theme.Size(Font.Caption2)), UI.Text(step.Text, Font.Caption2)).Foreground(ShowUI.Brush(step.Tone)),
                       ShowUI.Brush(step.Tone, 0.18), 6, 2);
}
