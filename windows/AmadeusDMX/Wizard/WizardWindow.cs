// The set-up assistant (set → rig → mount), a window of its own (mac/Sources/AmadeusDMX/Wizard).
// A placeholder until it is ported.
namespace AmadeusDMX;

public sealed partial class WizardWindow : Window
{
    public WizardWindow(AppModel model)
    {
        Title = "Set Up a Rig";
        AppWindow.Resize(new Windows.Graphics.SizeInt32(900, 640));
        Content = UI.Unavailable("wand.and.stars", "Set Up a Rig", "The set-up assistant is being ported from the Mac app.");
    }
}
