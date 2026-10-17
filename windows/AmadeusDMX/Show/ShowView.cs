// The show page: the stage, now playing, the decks, the timeline, the Perform board, the director (mac/Sources/AmadeusDMX/Show).
// A placeholder until the page is ported: the class and its Build() are what MainWindow uses.
namespace AmadeusDMX;

public sealed class ShowView(AppModel model)
{
    public FrameworkElement Build() =>
        UI.Unavailable("sparkles.tv", "Show", "This page is being ported from the Mac app.")
            .Bind(model, nameof(AppModel.ConfigVersion), _ => { });
}
