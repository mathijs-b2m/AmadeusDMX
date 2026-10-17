// The look: dark by default like the Mac app (the system's accent colour), SwiftUI's text styles on Windows's
// type ramp, and the Mac's system colours (dark-mode values) under their SwiftUI names.
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AmadeusDMX;

public static class Theme
{
    /// A brush of the WinUI theme ("TextFillColorSecondaryBrush", "CardBackgroundFillColorDefaultBrush", …).
    public static Brush Brush(string key) =>
        Application.Current.Resources.TryGetValue(key, out var v) && v is Brush b ? b : new SolidColorBrush(Microsoft.UI.Colors.Gray);

    public static FontFamily SymbolFont =>
        Application.Current.Resources.TryGetValue("SymbolThemeFontFamily", out var f) && f is FontFamily ff ? ff : new FontFamily("Segoe Fluent Icons");

    static readonly FontFamily MonoFamily = new("Cascadia Mono, Consolas");

    /// Size, weight and (for code-like text) the family of a text style. Segoe UI's digits are tabular already:
    /// SwiftUI's `.monospacedDigit()` needs nothing here.
    public static (double Size, Windows.UI.Text.FontWeight Weight, FontFamily? Family) Style(Font font) => font switch
    {
        Font.LargeTitle => (28, FontWeights.SemiBold, null),
        Font.Title => (24, FontWeights.SemiBold, null),
        Font.Title2 => (20, FontWeights.SemiBold, null),
        Font.Title3 => (17, FontWeights.Normal, null),
        Font.Headline => (14, FontWeights.SemiBold, null),
        Font.Callout => (13, FontWeights.Normal, null),
        Font.Subheadline => (12, FontWeights.Normal, null),
        Font.Footnote => (12, FontWeights.Normal, null),
        Font.Caption => (12, FontWeights.Normal, null),
        Font.Caption2 => (11, FontWeights.Normal, null),
        Font.Mono => (13, FontWeights.Normal, MonoFamily),
        Font.MonoCaption => (11, FontWeights.Normal, MonoFamily),
        _ => (14, FontWeights.Normal, null),
    };

    public static double Size(Font font) => Style(font).Size;
}

/// The Mac's system colours (dark mode), by their SwiftUI names.
public static class Tint
{
    static Color C(byte r, byte g, byte b) => Color.FromArgb(255, r, g, b);

    public static readonly Color Green = C(0x30, 0xD1, 0x58);
    public static readonly Color Orange = C(0xFF, 0x9F, 0x0A);
    public static readonly Color Red = C(0xFF, 0x45, 0x3A);
    public static readonly Color Blue = C(0x0A, 0x84, 0xFF);
    public static readonly Color Yellow = C(0xFF, 0xD6, 0x0A);
    public static readonly Color Purple = C(0xBF, 0x5A, 0xF2);
    public static readonly Color Gray = C(0x8E, 0x8E, 0x93);
    public static readonly Color Black = C(0, 0, 0);
    public static readonly Color White = C(255, 255, 255);

    /// The system's accent colour (SwiftUI's Color.accentColor).
    public static Color Accent =>
        Application.Current.Resources.TryGetValue("SystemAccentColor", out var v) && v is Color c ? c : Blue;

    public static SolidColorBrush Brush(Color c, double opacity = 1) => new(c) { Opacity = opacity };

    /// A colour from the engine's 0..1 RGB (palettes, sections).
    public static Color From(System.Numerics.Vector3 v) =>
        C((byte)Math.Clamp(v.X * 255, 0, 255), (byte)Math.Clamp(v.Y * 255, 0, 255), (byte)Math.Clamp(v.Z * 255, 0, 255));

    public static Color WithAlpha(this Color c, double a) => Color.FromArgb((byte)Math.Clamp(a * 255, 0, 255), c.R, c.G, c.B);
}
