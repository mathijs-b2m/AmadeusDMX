// The rig page: your rigs and the rig editor (mac/Sources/AmadeusDMX/Rig).
// A placeholder until the page is ported: the class and its Build() are what MainWindow uses.
namespace AmadeusDMX;

public sealed class RigView(AppModel model)
{
    public FrameworkElement Build() =>
        UI.Unavailable("square.split.bottomrightquarter", "Rigs", "This page is being ported from the Mac app.")
            .Bind(model, nameof(AppModel.ConfigVersion), _ => { });
}
