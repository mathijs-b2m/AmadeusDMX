// Amadeus Link: a notification-area app for the DJ's laptop. Switch it on, read the code to the lighting operator.
// A window as well as the icon (the Mac has a menu bar icon and a window): closing the window keeps Link running
// in the notification area; Quit Amadeus Link ends it.
using Microsoft.UI.Dispatching;
using Microsoft.Windows.AppLifecycle;

namespace AmadeusLink;

public sealed partial class App : Application
{
    LinkServer? _link;
    LinkWindow? _window;
    TrayIcon? _tray;

    public App()
    {
        RequestedTheme = ApplicationTheme.Dark;
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Resources.MergedDictionaries.Add(new XamlControlsResources());
        Defaults.Standard = new Defaults(Defaults.FileFor("Amadeus Link"), Environment.GetCommandLineArgs());
        _link = new LinkServer(updater: null);  // contract: the NetSparkle updater, for a release with a feed (Updates.cs)
        _window = new LinkWindow(_link, Quit);
        var icon = Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusLink.ico");
        _tray = new TrayIcon(icon, "Amadeus Link", ShowWindow, TrayMenu);
        _link.PropertyChanged += (_, _) => _tray.Tooltip = TrayTip();
        _tray.Tooltip = TrayTip();
        // a second start: show this one
        var queue = DispatcherQueue.GetForCurrentThread();
        AppInstance.GetCurrent().Activated += (_, _) => queue.TryEnqueue(ShowWindow);
        _window.Activate();
    }

    string TrayTip() => _link is not { } l ? "Amadeus Link"
        : !l.IsOn ? "Amadeus Link: off"
        : l.Peers.Count == 0 ? $"Amadeus Link: code {l.Code}"
        : $"Amadeus Link: {string.Join(", ", l.Peers.Select(p => p.Address))}";

    IReadOnlyList<TrayIcon.Entry> TrayMenu()
    {
        var l = _link!;
        return
        [
            new("Show Amadeus Link", ShowWindow),
            new(l.IsOn ? $"Pairing code {l.Code}" : "Off: invisible on the network", null),
            new("On", () => l.SetOn(!l.IsOn), Checked: l.IsOn),
            TrayIcon.Entry.Separator,
            new("Quit Amadeus Link", Quit),
        ];
    }

    void ShowWindow() => _window?.Reveal();

    void Quit()
    {
        _link?.Dispose();
        _tray?.Dispose();
        _window?.CloseForGood();
        Exit();
    }
}
