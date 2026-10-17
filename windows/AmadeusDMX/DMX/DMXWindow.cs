// DMX Devices & Output: your Art-Net / sACN nodes and USB interfaces, and where each set's universes go
// (mac/Sources/AmadeusDMX/DMX/DMXWindow.swift). A placeholder until it is ported.
namespace AmadeusDMX;

public sealed partial class DMXWindow : Window
{
    public DMXWindow(AppModel model)
    {
        Title = "DMX Devices & Output";
        AppWindow.Resize(new Windows.Graphics.SizeInt32(900, 620));
        Content = UI.Unavailable("cable.connector", "DMX Devices & Output", "This window is being ported from the Mac app.");
    }
}
