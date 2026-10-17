// The Show page's own little pieces on top of Shared/UI.cs: the glass panels that float over the stage, capsules,
// the colours a Tone stands for, borderless buttons, and the grouped form of the director's inspector.
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AmadeusDMX;

public static class ShowUI
{
    /// A panel floating over the stage (SwiftUI's `.glassEffect(.regular, in: .rect(cornerRadius:))`): the stage
    /// shows through, blurred.
    public static Border Glass(UIElement content, double padding = 14, double corner = 18) => new()
    {
        Child = content,
        Padding = new Thickness(padding),
        CornerRadius = new CornerRadius(corner),
        Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"),
        BorderBrush = Theme.Brush("CardStrokeColorDefaultBrush"),
        BorderThickness = new Thickness(1),
    };

    /// A pill around a small text or label.
    public static Border Capsule(UIElement content, Brush background, double horizontal = 7, double vertical = 3) => new()
    {
        Child = content,
        Background = background,
        CornerRadius = new CornerRadius(999),
        Padding = new Thickness(horizontal, vertical, horizontal, vertical),
        VerticalAlignment = VerticalAlignment.Center,
    };

    /// SwiftUI's `.quaternary` fill: a faint tint of the text colour.
    public static Brush Quaternary => Theme.Brush("ControlFillColorSecondaryBrush");

    public static Brush Tertiary => Theme.Brush("TextFillColorTertiaryBrush");

    /// The text colour itself at an opacity (SwiftUI's `.white.opacity(…)` over the dark stage, theme-aware).
    public static SolidColorBrush Ink(double opacity) =>
        new(Theme.Brush("TextFillColorPrimaryBrush") is SolidColorBrush b ? b.Color : Tint.White) { Opacity = opacity };

    public static Color Color(Tone t) => t switch
    {
        Tone.Green => Tint.Green,
        Tone.Orange => Tint.Orange,
        Tone.Red => Tint.Red,
        Tone.Yellow => Tint.Yellow,
        Tone.Secondary => Theme.Brush("TextFillColorSecondaryBrush") is SolidColorBrush s ? s.Color : Tint.Gray,
        _ => Theme.Brush("TextFillColorPrimaryBrush") is SolidColorBrush p ? p.Color : Tint.White,
    };

    public static Brush Brush(Tone t, double opacity = 1) => t switch
    {
        Tone.Primary when opacity >= 1 => Theme.Brush("TextFillColorPrimaryBrush"),
        Tone.Secondary when opacity >= 1 => Theme.Brush("TextFillColorSecondaryBrush"),
        _ => Tint.Brush(Color(t), opacity),
    };

    /// A colour from the engine's sections and palettes.
    public static SolidColorBrush Section(string section, double opacity = 1) => Tint.Brush(Tint.From(Sections.Color(section)), opacity);

    /// A button without its frame (SwiftUI's `.buttonStyle(.borderless)` / `.plain`).
    public static T Borderless<T>(this T b) where T : ButtonBase
    {
        b.Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent);
        b.BorderThickness = new Thickness(0);
        b.Padding = new Thickness(4, 2, 4, 2);
        b.MinWidth = 0;
        b.MinHeight = 0;
        return b;
    }

    /// SwiftUI's `.controlSize(.small)`.
    public static T Small<T>(this T c) where T : Control
    {
        c.FontSize = Theme.Size(Font.Caption);
        c.Padding = new Thickness(8, 3, 8, 4);
        c.MinHeight = 0;
        return c;
    }

    /// A leading-aligned element in a VStack (SwiftUI's `VStack(alignment: .leading)`).
    public static T Leading<T>(this T e) where T : FrameworkElement { e.HorizontalAlignment = HorizontalAlignment.Left; return e; }

    public static TextBlock AlignRight(this TextBlock t) { t.TextAlignment = TextAlignment.Right; return t; }

    /// A Form section, grouped: an optional title, then its rows in a rounded box with lines between them.
    public static FrameworkElement FormSection(string? title, params UIElement?[] rows)
    {
        var box = UI.VStack(0);
        var first = true;
        foreach (var r in rows)
        {
            if (r is null) continue;
            if (!first) box.Children.Add(UI.Divider().Margin(10, 0, 10, 0));
            first = false;
            box.Children.Add(r is FrameworkElement fe ? fe.Padding(new Thickness(10, 7, 10, 7)) : r);
        }
        var card = UI.Card(box, padding: 0, corner: 8);
        return title is null ? card : UI.VStack(6, UI.Text(title, Font.Subheadline).Bold().Secondary().Margin(4, 0, 0, 0), card);
    }

    /// A row of a Form: its label at the left, its value at the right (SwiftUI's LabeledContent).
    public static Stack Labeled(string label, UIElement value) => UI.HStack(8, UI.Text(label), UI.Spacer(8), value);

    public static Stack Labeled(string label, string value) => Labeled(label, UI.Text(value).Secondary());
}
