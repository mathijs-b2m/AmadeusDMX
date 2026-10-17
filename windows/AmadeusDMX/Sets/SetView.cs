// The set page: your fixtures, their patch, adding fixtures (mac/Sources/AmadeusDMX/Sets).
// A placeholder until the page is ported: the class and its Build() are what MainWindow uses.
namespace AmadeusDMX;

public sealed class SetView(AppModel model)
{
    public FrameworkElement Build() =>
        UI.Unavailable("light.overhead.right", "Sets", "This page is being ported from the Mac app.")
            .Bind(model, nameof(AppModel.ConfigVersion), _ => { });
}
