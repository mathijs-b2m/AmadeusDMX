// Amadeus Link: a notification-area app for the DJ's laptop. Switch it on, read the code to the lighting operator.
// A window as well as the icon (the Mac has a menu bar icon and a window): closing the window keeps Link running
// in the notification area; Quit Amadeus Link ends it (asking first while a lighting computer is connected).
using Microsoft.UI.Dispatching;
using Microsoft.Windows.AppLifecycle;

namespace AmadeusLink;

public sealed partial class App : Application
{
    LinkServer? _link;
    LinkWindow? _window;
    TrayIcon? _tray;
    Updater? _updater;
    bool _quitting;
    bool _asking;

    public App()
    {
        RequestedTheme = ApplicationTheme.Dark;
        UnhandledException += (_, e) => CrashLog.Write("Amadeus Link", e.Exception, "unhandled");
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try { Launch(); }
        catch (Exception e)
        {
            CrashLog.Write("Amadeus Link", e, "launch");
            throw;
        }
    }

    void Launch()
    {
        Resources.MergedDictionaries.Add(new XamlControlsResources());
        Defaults.Standard = new Defaults(Defaults.FileFor("Amadeus Link"), Environment.GetCommandLineArgs());
        // updates: a release with a feed only (appsettings.json), never while a lighting computer is connected
        _updater = Updater.ForThisBuild("Amadeus Link", () => _link?.Updates, Ask, Tell, Quit);
        _link = new LinkServer(_updater);
        _window = new LinkWindow(_link, AskToQuit);
        var icon = Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusLink.ico");
        _tray = new TrayIcon(icon, "Amadeus Link", ShowWindow, TrayMenu);
        _link.PropertyChanged += (_, _) => _tray.Tooltip = TrayTip();
        _tray.Tooltip = TrayTip();
        // a second start: show this one
        var queue = DispatcherQueue.GetForCurrentThread();
        AppInstance.GetCurrent().Activated += (_, _) => queue.TryEnqueue(ShowWindow);
        _window.Activate();
        // Sparkle's rule on the Mac: on the second launch, ask once whether to check by itself
        if (_link.Updates.ShouldAskToCheckAutomatically())
            queue.TryEnqueue(async () => _link.Updates.Answer(await Ask(
                "Check for updates automatically?",
                "Amadeus Link can look for a new version once a day (never while a lighting computer is connected). You can change this at the bottom of its window.",
                "Check Automatically")));
    }

    string TrayTip() => _link is not { } l ? "Amadeus Link"
        : !l.IsOn ? "Amadeus Link: off"
        : l.Peers.Count == 0 ? $"Amadeus Link: code {l.Code}"
        : $"Amadeus Link: {string.Join(", ", l.Peers.Select(p => p.Address))}";

    IReadOnlyList<TrayIcon.Entry> TrayMenu()
    {
        var l = _link!;
        List<TrayIcon.Entry> menu =
        [
            new("Show Amadeus Link", ShowWindow),
            new(l.IsOn ? $"Pairing code {l.Code}" : "Off: invisible on the network", null),
            new("On", () => l.SetOn(!l.IsOn), Checked: l.IsOn),
            TrayIcon.Entry.Separator,
        ];
        foreach (var s in Enum.GetValues<LinkServer.Software>())
            menu.Add(new(LinkServer.Title(s), () => l.SetSoftware(s), Checked: l.Current == s));
        menu.Add(TrayIcon.Entry.Separator);
        if (l.Updates.IsAvailable) menu.Add(new("Check for Updates…", l.Updates.CanCheck ? l.Updates.CheckForUpdates : null));
        menu.Add(new("Quit Amadeus Link", AskToQuit));
        return menu;
    }

    void ShowWindow() => _window?.Reveal();

    /// A question in Link's window (shown first: it may be in the notification area).
    async Task<bool> Ask(string title, string message, string yes)
    {
        if (_window?.Content?.XamlRoot is not { } root) return false;
        ShowWindow();
        var dialog = new ContentDialog
        {
            Title = title, Content = new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap },
            PrimaryButtonText = yes, CloseButtonText = "Not Now", DefaultButton = ContentDialogButton.Primary, XamlRoot = root,
        };
        try { return await dialog.ShowAsync() == ContentDialogResult.Primary; }
        catch (Exception e) when (e is InvalidOperationException or System.Runtime.InteropServices.COMException) { return false; }  // another dialog is open
    }

    void Tell(string title, string message)
    {
        if (_window?.Content?.XamlRoot is not { } root) return;
        ShowWindow();
        var dialog = new ContentDialog { Title = title, Content = message, CloseButtonText = "OK", XamlRoot = root };
        try { _ = dialog.ShowAsync(); }
        catch (Exception e) when (e is InvalidOperationException or System.Runtime.InteropServices.COMException) { }
    }

    /// The DJ quits (the window's button, Ctrl+Q, the notification area): while a lighting computer is connected,
    /// only after saying what stops. An update's own quit (NetSparkle) goes straight to Quit: it waits until idle.
    async void AskToQuit()
    {
        if (_quitting || _asking) return;
        if (_link is not { Peers.Count: > 0 } l || _window?.Content?.XamlRoot is not { } root)
        {
            Quit();
            return;
        }
        _asking = true;
        ShowWindow();
        var dialog = new ContentDialog
        {
            Title = "Quit Amadeus Link during the show?",
            Content = new TextBlock
            {
                Text = $"A lighting computer is connected ({string.Join(", ", l.Peers.Select(p => p.Address))}). If you quit, "
                       + "it loses the mix: the lights stop following the music until Amadeus Link is back.",
                TextWrapping = TextWrapping.Wrap,
            },
            PrimaryButtonText = "Quit Anyway", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Close, XamlRoot = root,
        };
        bool quit;
        try { quit = await dialog.ShowAsync() == ContentDialogResult.Primary; }
        catch (Exception e) when (e is InvalidOperationException or System.Runtime.InteropServices.COMException) { quit = false; }  // another dialog is open
        finally { _asking = false; }
        if (quit) Quit();
    }

    void Quit()
    {
        // an update downloaded by itself installs now: NetSparkle starts its installer, then asks us to quit again
        if (!_quitting && _updater?.InstallOnQuit() == true)
        {
            _quitting = true;
            var queue = DispatcherQueue.GetForCurrentThread();
            _ = Task.Delay(TimeSpan.FromSeconds(15)).ContinueWith(_ => queue.TryEnqueue(Quit));  // if it never does
            return;
        }
        _quitting = true;
        _updater?.Dispose();
        _link?.Dispose();
        _tray?.Dispose();
        _window?.CloseForGood();
        Exit();
    }
}
