// The brightness limiter: its toolbar button (on every page) and the banner that can't be missed while it is on.
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;
using static AmadeusDMX.Formatting;

namespace AmadeusDMX;

static class LimiterText
{
    public const string Explanation = "A ceiling on every light, to test and set up without eye strain. At 70 %, a light the show plays at 50 % stays at 50 %; one at 100 % plays at 70 %. The show, the light test and Identify all keep to it. Smoke isn't limited. For a show: 100 %.";
}

public sealed class LimiterButton(AppModel model)
{
    public FrameworkElement Build()
    {
        var button = new Button { Flyout = new Flyout { Content = new LimiterPanel(model).Build(), Placement = Microsoft.UI.Xaml.Controls.Primitives.FlyoutPlacementMode.Bottom } };
        return button.Bind(model, [nameof(AppModel.Limiter), nameof(AppModel.Workspace)], b =>
        {
            if (model.LimiterOn)
                b.Content = UI.Label("sun.max.trianglebadge.exclamationmark.fill", $"Limited to {Percent(model.Limiter)}").Foreground(Tint.Orange).Bold();
            else
                b.Content = UI.Icon("sun.max");
            b.Tooltip(model.LimiterOn ? $"Every light is limited to {Percent(model.Limiter)}. Click to change" : "Brightness limiter: off (100 %)");
            b.IsEnabled = model.Workspace is not null;
        });
    }
}

public sealed class LimiterPanel(AppModel model)
{
    public FrameworkElement Build()
    {
        var level = UI.Text("", Font.Title3).Bold().Bind(model, nameof(AppModel.Limiter), t =>
        {
            t.Text = model.LimiterOn ? Percent(model.Limiter) : "Off";
            t.Foreground = model.LimiterOn ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorSecondaryBrush");
        });
        var slider = UI.Slider(model.Limiter, Workspace.LimiterMinimum, 1, v => model.SetLimiter(Math.Round(v * 20) / 20), step: 0.05)
            .Bind(model, nameof(AppModel.Limiter), s => s.SetValueQuietly(model.Limiter));
        slider.Header = "Ceiling";
        var off = UI.Button("100% (Off)", () => model.SetLimiter(1)).Prominent()
            .Bind(model, nameof(AppModel.Limiter), b => b.IsEnabled = model.LimiterOn);
        return UI.VStack(12,
            UI.HStack(UI.Text("Brightness Limiter", Font.Headline), UI.Spacer(), level),
            UI.HStack(6, UI.Text("5%", Font.Caption).Secondary(), slider.Grow(), UI.Text("100%", Font.Caption).Secondary()),
            UI.HStack(
                UI.Button(Percent(0.25), () => model.SetLimiter(0.25)),
                UI.Button(Percent(0.5), () => model.SetLimiter(0.5)),
                UI.Button(Percent(0.7), () => model.SetLimiter(0.7)),
                UI.Spacer(),
                off),
            UI.Text(LimiterText.Explanation, Font.Callout).Secondary().Wrap(),
            UI.Text("The app starts at 100 % every time it opens.", Font.Caption).Secondary().Wrap()
        ).Frame(width: 360);
    }
}

/// Across the top of every page while the limiter is on: hazard stripes, the level, one click back to 100 %.
public sealed class LimiterBanner(AppModel model)
{
    public FrameworkElement Build()
    {
        var black = Tint.Brush(Tint.Black);
        var title = UI.Text("", Font.Headline).Foreground(black);
        var line = UI.Text("", Font.Callout).Foreground(black).Lines(1);
        var back = UI.Button("Back to 100%", () => model.SetLimiter(1));
        back.Background = black;
        back.Foreground = Tint.Brush(Tint.White);
        var banner = new Border
        {
            Background = HazardStripes(),
            Padding = new Thickness(14, 7, 14, 7),
            Child = UI.HStack(12, UI.Icon("sun.max.trianglebadge.exclamationmark.fill", 18).Foreground(black), title, line, UI.Spacer(8), back),
        }.Tooltip(LimiterText.Explanation);
        return banner.Bind(model, nameof(AppModel.Limiter), b =>
        {
            b.Visible(model.LimiterOn);
            title.Text = $"Brightness limited to {Percent(model.Limiter)}";
            line.Text = $"lights above it play at {Percent(model.Limiter)}, the rest as the show plays them · set it to 100 % for a show";
        });
    }

    /// Diagonal stripes, 14 px wide, orange on lighter orange (a repeating gradient with hard stops).
    static Brush HazardStripes()
    {
        var dark = Windows.UI.Color.FromArgb(255, 255, 158, 26);
        var light = Windows.UI.Color.FromArgb(255, 255, 184, 77);
        var b = new LinearGradientBrush
        {
            MappingMode = BrushMappingMode.Absolute,
            StartPoint = new Point(0, 0),
            EndPoint = new Point(14, 14),  // one dark and one light stripe along the diagonal: 28 px across
            SpreadMethod = GradientSpreadMethod.Repeat,
        };
        b.GradientStops.Add(new GradientStop { Color = dark, Offset = 0 });
        b.GradientStops.Add(new GradientStop { Color = dark, Offset = 0.5 });
        b.GradientStops.Add(new GradientStop { Color = light, Offset = 0.5 });
        b.GradientStops.Add(new GradientStop { Color = light, Offset = 1 });
        return b;
    }
}
