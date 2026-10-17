// The track's genre (one word), and the program it gets: a chip for every track, and a banner that stands
// out for a genre with a program of its own (cinematic: every hit played by its own fixtures).
// (Genre's symbols and words are in ShowLogic.cs.)
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;

namespace AmadeusDMX;

/// "TECHNO", small; "POP → HOUSE" when the set plays it in another genre's style.
public static class GenreChip
{
    public static FrameworkElement? Build(string genre, string source = "", string style = "")
    {
        if (genre.Length == 0) return null;
        return ShowUI.Capsule(UI.Label(Genre.Symbol(genre), Genre.Chip(genre, style), Font.Caption2).Bold(), ShowUI.Quaternary)
            .Tooltip(Genre.ChipHelp(genre, source, style));
    }
}

/// A genre with a program of its own: said loudly.
public static class ProgramBanner
{
    public static FrameworkElement? Build(string program)
    {
        if (program != "cinematic") return null;
        var white = Tint.Brush(Tint.White);
        var title = UI.Text("CINEMATIC PROGRAM", Font.Callout).Foreground(white);
        title.FontWeight = FontWeights.Black;
        title.CharacterSpacing = 115;  // tracking 1.5 pt at 13 pt
        var gradient = new LinearGradientBrush { StartPoint = new Point(0, 0.5), EndPoint = new Point(1, 0.5) };
        gradient.GradientStops.Add(new GradientStop { Color = Windows.UI.Color.FromArgb(255, 242, 115, 26), Offset = 0 });
        gradient.GradientStops.Add(new GradientStop { Color = Windows.UI.Color.FromArgb(255, 140, 26, 153), Offset = 1 });
        return new Border
        {
            Background = gradient,
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(12, 9, 12, 9),
            Child = UI.HStack(10,
                UI.Icon("film.stack", Theme.Size(Font.Title2)).Foreground(white),
                UI.VStack(1,
                    title.Leading(),
                    UI.Text("Every hit played by its own fixtures, exactly on time", Font.Caption).Foreground(white).Opacity(0.85).Leading()),
                UI.Spacer()),
        }.Tooltip("A film-score track: no beat grid. The hits are found where they are, sorted into voices, and every voice plays its own fixtures; the biggest hits play the whole rig.");
    }
}
