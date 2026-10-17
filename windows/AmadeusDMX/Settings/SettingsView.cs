// Settings: the engine folder, the director and its AI key, the DJ software integrations, updates (mac/Sources/AmadeusDMX/Settings).
// A placeholder until the page is ported: the class and its Build() are what MainWindow uses.
namespace AmadeusDMX;

public sealed class SettingsView(AppModel model)
{
    public FrameworkElement Build() =>
        UI.Unavailable("gearshape", "Settings", "This page is being ported from the Mac app.")
            .Bind(model, nameof(AppModel.ConfigVersion), _ => { });
}
