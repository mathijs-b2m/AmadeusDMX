// Perform Only: what the operator needs at a glance, big, instead of the 3D stage.
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Media;

namespace AmadeusDMX;

/// Perform Only: what the operator needs at a glance, big, instead of the 3D stage.
public sealed class PerformBoard(AppModel model)
{
    static readonly FontFamily Rounded = new("Segoe UI Variable Display, Segoe UI");

    public FrameworkElement Build()
    {
        var live = UI.Live(model, Content, nameof(AppModel.ShowState), nameof(AppModel.CurrentSet))
            .Bind(model.Feed, [nameof(LiveFeed.Hello), nameof(LiveFeed.Phrase)], c => c.Content = Content());
        live.HorizontalAlignment = HorizontalAlignment.Center;
        live.VerticalAlignment = VerticalAlignment.Center;
        var board = new Grid { Background = Theme.Brush("SolidBackgroundFillColorTertiaryBrush") };  // the Mac's under-page colour
        board.Children.Add(live);
        return board;
    }

    UIElement Content()
    {
        var feed = model.Feed;
        var rows = new List<UIElement?>();
        if (feed.Hello is { } h && model.ShowState.IsActive && NowPlaying.At(h, feed.Phrase) is { } d)
        {
            var section = UI.Text(d.Section.ToUpperInvariant()).Foreground(ShowUI.Section(d.Section)).Center();
            section.FontSize = 72;
            section.FontWeight = FontWeights.Black;
            section.FontFamily = Rounded;
            rows.Add(section);
            var pips = IntensityPips.Build(d.Intensity);
            pips.RenderTransformOrigin = new Windows.Foundation.Point(0.5, 0.5);
            pips.RenderTransform = new ScaleTransform { ScaleX = 1.6, ScaleY = 1.6 };  // drawn bigger, laid out as it is
            pips.Margin = new Thickness(0, 0, 0, 6);
            rows.Add(pips);
            if (NowPlaying.At(h, feed.Phrase + 1) is { } next)
                rows.Add(UI.Text("", Font.Title2).Secondary().Center()
                    .Bind(feed, nameof(LiveFeed.Time), t => t.Text = NowPlaying.NextLine(next, feed.Time)));
        }
        else
        {
            rows.Add(UI.Icon(ShowMode.Perform.Symbol(), 44).Secondary());
            rows.Add(UI.Text(ShowMode.Perform.Title(), Font.Title).Bold().Center());
            rows.Add(UI.Text("The 3D stage is off: the computer's power goes to the lights.").Secondary().Center().Wrap());
        }
        rows.Add(UI.HStack(8, UI.Icon("cable.connector"), UI.Text(NowPlaying.Output(model.CurrentSet), Font.Callout))
            .Secondary().Font(Font.Callout).Margin(0, 10, 0, 0));
        rows.Add(UI.Button("Show the Stage", () => model.SetMode(ShowMode.Both)).Tooltip("Perform + Visualise: the 3D stage alongside the lights"));
        var stack = UI.VStack(14, [.. rows]).Padding(40);
        stack.Alignment = 0.5;
        return stack;
    }
}
