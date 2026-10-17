// Amadeus Link's window (the Mac's LinkMenu): on/off, the DJ software, the pairing code, the lighting computers
// connected, updates. Closing it keeps Link running in the notification area.
using Microsoft.UI.Windowing;
using Windows.System;

namespace AmadeusLink;

public sealed partial class LinkWindow : Window
{
    readonly LinkServer _link;
    readonly Action _quit;
    bool _closing;

    public LinkWindow(LinkServer link, Action quit)
    {
        _link = link;
        _quit = quit;
        Title = "Amadeus Link";
        var icon = Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusLink.ico");
        if (File.Exists(icon)) AppWindow.SetIcon(icon);
        SystemBackdrop = new Microsoft.UI.Xaml.Media.MicaBackdrop();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(380, 640));
        if (AppWindow.Presenter is OverlappedPresenter p) { p.IsMaximizable = false; p.IsResizable = false; }
        AppWindow.Closing += (_, e) =>
        {
            if (_closing) return;
            e.Cancel = true;  // the window goes, Link stays (in the notification area)
            AppWindow.Hide();
        };
        Content = UI.Scroll(new LinkMenu(link, quit).Build());
    }

    /// Back from the notification area.
    public void Reveal()
    {
        AppWindow.Show();
        Activate();
    }

    /// Quitting: the window really closes.
    public void CloseForGood()
    {
        _closing = true;
        Close();
    }
}

public sealed class LinkMenu(LinkServer link, Action quit)
{
    Updates Updates => link.Updates;

    string Waiting => link.Current switch
    {
        LinkServer.Software.VirtualDJ => "Waiting for VirtualDJ (the AmadeusLink plugin as master effect)",
        LinkServer.Software.Djay => "Waiting for djay Pro to play a track",
        _ => "Waiting for Mixxx to play a track",
    };

    public FrameworkElement Build()
    {
        var logo = new Image
        {
            Source = new Microsoft.UI.Xaml.Media.Imaging.BitmapImage(new Uri(Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusLink.ico"))),
            Width = 20, Height = 20,
        };
        var power = UI.Toggle("", link.IsOn, link.SetOn).Bind(link, nameof(LinkServer.IsOn), t => t.SetOn(link.IsOn));
        var software = UI.Segmented(Enum.GetValues<LinkServer.Software>(), link.Current, LinkServer.Title, link.SetSoftware);
        var quitButton = UI.Button("Quit Amadeus Link", quit).Shortcut(VirtualKey.Q);
        return UI.VStack(14,
            UI.HStack(logo, UI.Text("Amadeus Link", Font.Headline), UI.Spacer(), power),
            software,
            UI.Live(link, Status, nameof(LinkServer.DjConnected), nameof(LinkServer.Current), nameof(LinkServer.DjApp),
                    nameof(LinkServer.ReaderNote), nameof(LinkServer.DeckSummary)),
            UI.Live(link, Pairing, nameof(LinkServer.IsOn), nameof(LinkServer.Code), nameof(LinkServer.Peers), nameof(LinkServer.TracksServed)),
            UI.Live(link, Problems, nameof(LinkServer.PluginError), nameof(LinkServer.Error)),
            UI.Divider(),
            Updates.IsAvailable ? UI.Live(Updates, UpdateRows) : null,
            quitButton
        ).Padding(16);
    }

    UIElement Status()
    {
        var connected = link.DjConnected;
        var rows = new List<UIElement?>
        {
            UI.Label(connected ? "checkmark.circle.fill" : "hourglass", connected ? $"{link.DjApp} connected" : Waiting, Font.Callout)
                .Foreground(connected ? Tint.Brush(Tint.Green) : Theme.Brush("TextFillColorSecondaryBrush")),
        };
        if (!connected && link.Current == LinkServer.Software.VirtualDJ) rows.Add(new PluginRow().Build());
        if (link.ReaderNote.Length > 0)
        {
            rows.Add(UI.Text(link.ReaderNote, Font.Caption).Foreground(Tint.Orange).Wrap());
            // Mixxx without a MIDI port Link could make: loopMIDI makes one (the Mac's "Open Accessibility Settings")
            if (link.Current == LinkServer.Software.Mixxx && link.ReaderNote.Contains("loopMIDI", StringComparison.Ordinal))
                rows.Add(UI.Link("Get loopMIDI", () => _ = Launcher.LaunchUriAsync(new Uri(Readers.LoopMidiUrl))).Font(Font.Callout));
        }
        if (connected && link.DeckSummary.Length > 0) rows.Add(UI.Text(link.DeckSummary, Font.MonoCaption).Secondary().Wrap(4));
        return UI.VStack(8, [.. rows]);
    }

    UIElement Pairing()
    {
        if (!link.IsOn) return UI.Text("Off: this laptop is invisible on the network.", Font.Callout).Secondary().Wrap();
        var code = UI.Text(link.Code, Font.LargeTitle).Selectable().Center();
        code.FontSize = 40;
        code.FontWeight = Microsoft.UI.Text.FontWeights.Bold;
        code.CharacterSpacing = 400;
        var box = UI.VStack(4, UI.Text("Pairing code", Font.Caption).Secondary().Center(), code,
                            UI.Link("New Code", link.RenewCode).Align(HorizontalAlignment.Center));
        box.Alignment = 0.5;
        var rows = new List<UIElement?> { UI.Card(box, padding: 8, corner: 12) };
        if (link.Peers.Count == 0)
            rows.Add(UI.Text("The lighting computer finds this laptop under “Nearby DJs” and asks for the code.", Font.Caption).Secondary().Wrap());
        else
        {
            var peers = new List<UIElement?> { UI.Text("Connected", Font.Caption).Secondary() };
            peers.AddRange(link.Peers.Select(p => (UIElement)UI.HStack(
                UI.Icon("light.overhead.right").Foreground(Tint.Accent), UI.Text(p.Address, Font.Callout), UI.Spacer(),
                UI.IconButton("xmark.circle.fill", "Disconnect", () => link.Disconnect(p.Id)))));
            if (link.TracksServed > 0)
                peers.Add(UI.Text($"{link.TracksServed} track{(link.TracksServed == 1 ? "" : "s")} sent", Font.Caption).Secondary());
            rows.Add(UI.VStack(6, [.. peers]));
        }
        return UI.VStack(10, [.. rows]);
    }

    UIElement Problems()
    {
        UIElement? Problem(string? e) => e is null ? null
            : UI.HStack(6, UI.Icon("exclamationmark.triangle.fill", 12).Foreground(Tint.Orange),
                        UI.Text(e, Font.Caption).Foreground(Tint.Orange).Wrap().Grow());
        return UI.VStack(6, Problem(link.PluginError), Problem(link.Error));
    }

    UIElement UpdateRows()
    {
        var check = UI.Check("Check for updates", Updates.ChecksAutomatically, v => Updates.ChecksAutomatically = v).Font(Font.Callout);
        var now = UI.Button("Check Now", Updates.CheckForUpdates).Disabled(!Updates.CanCheck).Font(Font.Callout);
        return UI.VStack(6,
            UI.HStack(check, UI.Spacer(), now),
            Updates.WaitingForIdle ? UI.Text("An update installs when the lighting computer disconnects.", Font.Caption).Secondary().Wrap() : null);
    }
}

/// The AmadeusLink plugin for VirtualDJ: Link carries it (vdj\AmadeusLink.dll beside the app, build.ps1 puts it
/// there: the AmadeusLink.dll next to the exe is the app itself), so a DJ laptop needs nothing else.
public sealed class PluginRow
{
    static readonly string BundledPath = Path.Combine(AppContext.BaseDirectory, "vdj", "AmadeusLink.dll");
    string? Bundled => File.Exists(BundledPath) ? BundledPath : null;
    VirtualDJPlugin.Status _status = VirtualDJPlugin.Status.NotInstalled;
    string _message = "";
    ContentControl? _host;

    string Title => _status switch
    {
        VirtualDJPlugin.Status.NotInstalled => "VirtualDJ plugin not installed",
        VirtualDJPlugin.Status.UpToDate => "VirtualDJ plugin installed",
        _ => "VirtualDJ plugin: an update is ready",
    };

    public FrameworkElement Build()
    {
        _status = VirtualDJPlugin.StatusComparedTo(Bundled);
        _host = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };
        Show();
        return _host;
    }

    void Show()
    {
        if (_host is null) return;
        var ok = _status == VirtualDJPlugin.Status.UpToDate;
        var title = UI.Label(ok ? "puzzlepiece.extension.fill" : "puzzlepiece.extension", Title, Font.Callout)
            .Foreground(ok ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Orange));
        var install = !ok && Bundled is not null
            ? UI.Button(_status == VirtualDJPlugin.Status.Outdated ? "Update" : "Install", Install).Font(Font.Callout) : null;
        _host.Content = UI.VStack(6,
            UI.HStack(title, UI.Spacer(), install),
            UI.Text(_message.Length == 0 ? "In VirtualDJ: Master effect › AmadeusLink. Restart VirtualDJ after installing." : _message,
                    Font.Caption).Secondary().Wrap());
    }

    void Install()
    {
        if (Bundled is not { } bundled) return;
        try
        {
            VirtualDJPlugin.Install(bundled);
            _message = "Installed. Restart VirtualDJ, then switch on AmadeusLink as master effect.";
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            _message = e.Message;
        }
        _status = VirtualDJPlugin.StatusComparedTo(bundled);
        Show();
    }
}
