// The track, the section and what comes next; the laser guard's actions.
using static AmadeusDMX.Formatting;

namespace AmadeusDMX;

public sealed class NowPlayingCard(AppModel model)
{
    public FrameworkElement Build()
    {
        // rebuilt when the state, the track, the phrase or the guard changes; the times follow the feed by themselves
        var live = UI.Live(model, Content, nameof(AppModel.ShowState), nameof(AppModel.ShowTitle), nameof(AppModel.DjWaiting), nameof(AppModel.CurrentSet))
            .Bind(model.Feed, [nameof(LiveFeed.Hello), nameof(LiveFeed.Phrase), nameof(LiveFeed.LaserGuard)], c => c.Rebuild(Content));
        return ShowUI.Glass(live).MaxWidth(420).Leading();
    }

    UIElement Content()
    {
        var state = model.ShowState;
        var feed = model.Feed;
        if (feed.Hello is not { } h || !state.IsActive)
            return UI.VStack(6,
                UI.Text(model.CurrentSet?.Name ?? "No set", Font.Headline).Leading(),
                UI.Text(Idle(state), Font.Callout).Secondary().Wrap().Leading());

        var i = feed.Phrase;
        var d = NowPlaying.At(h, i);
        var next = NowPlaying.At(h, i + 1);
        var metrics = UI.HStack(14,
            Metric.Build($"{Num.Round(h.Bpm)}", "BPM"),
            Metric.Build("", $"of {TimeString(h.Duration)}", bind: t => t.Text = TimeString(feed.Time), feed: feed),
            d is null ? null : Metric.Build(Capitalized(d.Section), "now", ShowUI.Section(d.Section)),
            next is null ? null : Metric.Build("", $"→ {next.Section}", bind: t => t.Text = NowPlaying.NextValue(next, feed.Time), feed: feed));
        var rows = new List<UIElement?>
        {
            ProgramBanner.Build(h.Program),
            UI.HStack(8,
                UI.Icon(state.Kind == ShowStateKind.Playing ? "music.note" : "dot.radiowaves.left.and.right").Secondary(),
                UI.Text(h.Title, Font.Headline).Lines(1),
                GenreChip.Build(h.Genre, h.GenreSource, h.Style)),
            metrics.Leading(),
            d is null ? null : IntensityPips.Build(d.Intensity).Leading(),
        };
        if (feed.LaserGuard.Count > 0)
            rows.Add(UI.VStack(2, [.. NowPlaying.Guard(feed.LaserGuard).Select(g =>
                    (UIElement)UI.Label(NowPlaying.GuardIsSevere(g.Note) ? "exclamationmark.octagon.fill" : "arrow.up.circle", $"{g.Id}: {g.Note}", Font.Caption)
                        .Foreground(NowPlaying.GuardIsSevere(g.Note) ? Tint.Red : Tint.Orange).Leading())])
                .Tooltip("The laser guard keeps laser beams out of the laser safety zones (rig editor)").Leading());
        return UI.VStack(8, [.. rows]);
    }

    string Idle(ShowState s) => s.Kind switch
    {
        ShowStateKind.Stopped => "Rig preview. Press Start (Ctrl+R) for a live show, or play a track (Ctrl+O).",
        ShowStateKind.Starting => "The engine is starting…",
        ShowStateKind.WaitingForDJ => $"{model.ShowTitle}. {model.DjWaiting}",
        ShowStateKind.Failed => s.Reason,
        _ => "",
    };
}

/// A number and what it is: "128" over "BPM".
public static class Metric
{
    /// `bind`: the value follows the feed's time (set again whenever it moves).
    public static FrameworkElement Build(string value, string label, Microsoft.UI.Xaml.Media.Brush? color = null,
                                         Action<TextBlock>? bind = null, LiveFeed? feed = null)
    {
        var v = UI.Text(value, Font.Title3).Bold().Leading();
        if (color is not null) v.Foreground = color;
        if (bind is not null && feed is not null) v.Bind(feed, nameof(LiveFeed.Time), bind);
        return UI.VStack(1, v, UI.Text(label, Font.Caption).Secondary().Leading());
    }
}

/// The phrase's intensity, 0..3: four short bars, lit up to it.
public static class IntensityPips
{
    public static Stack Build(int level, bool labelHidden = false)
    {
        var row = UI.HStack(3);
        for (var k = 0; k < 4; k++)
            row.Children.Add(new Border
            {
                Width = 18, Height = 4, CornerRadius = new CornerRadius(2),
                Background = k <= level ? Tint.Brush(Tint.Orange) : ShowUI.Brush(Tone.Secondary, 0.25),
            });
        if (!labelHidden) row.Children.Add(UI.Text("intensity", Font.Caption2).Secondary().Margin(4, 0, 0, 0));
        return row;
    }
}
