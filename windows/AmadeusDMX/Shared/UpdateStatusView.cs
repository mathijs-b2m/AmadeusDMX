// Which version this app is, whether it's the newest, and the one click that updates it (the Mac's
// AmadeusKit/UpdateStatusView.swift). Amadeus DMX shows it in Settings › Updates, Amadeus Link in its window.
using static AmadeusKit.Strings;  // also compiled into Amadeus Link

namespace AmadeusDMX;

public static class UpdateStatusView
{
    /// whenIdle: when a waiting update installs ("when the show stops"). Checks quietly for the newest when shown.
    public static FrameworkElement Build(Updates updates, string appName, string whenIdle, bool compact = false)
    {
        var view = UI.Live(updates, () => Content(updates, appName, whenIdle, compact));
        view.Loaded += (_, _) => updates.Refresh();
        return view;
    }

    static UIElement Content(Updates u, string appName, string whenIdle, bool compact)
    {
        var small = compact ? Font.Caption : Font.Callout;
        UIElement? action = u.State switch
        {
            UpdateState.Available => UI.Button(L("Update to {0}", u.Newest), () => u.InstallNewest()).Prominent().Disabled(!u.CanCheck),
            UpdateState.Downloading => UI.Button(L("Cancel"), u.CancelInstall),
            UpdateState.Checking or UpdateState.Installing => null,
            _ => UI.Button(L("Check Again"), () => u.Refresh(force: true)).Disabled(!u.CanCheck).Font(small),
        };
        UIElement status = u.State switch
        {
            UpdateState.Checking => UI.HStack(6, UI.Spinner(14), UI.Text(L("Checking for the newest version…"), small).Secondary()),
            UpdateState.UpToDate => Note("checkmark.circle.fill",
                u.Newest is { } n ? (n == u.Version ? L("Up to date: {0} is the newest", n) : L("Up to date (newest: {0})", n)) : L("Up to date"),
                small, Tint.Green),
            UpdateState.Available => Note("arrow.down.circle", L("{0} is available: you have {1}", u.Newest, u.Version), small, Tint.Orange),
            UpdateState.Downloading => UI.VStack(4, UI.Text(L("Downloading {0}…", u.Newest), small).Secondary(), UI.Progress(u.Progress)),
            UpdateState.Installing => u.WaitingForIdle
                ? Note("clock", L("{0} is ready: it installs {1}", u.Newest, whenIdle), small, null)
                : Note("arrow.triangle.2.circlepath", L("Installing {0}: {1} starts again", u.Newest, appName), small, null),
            UpdateState.Failed => Note("exclamationmark.triangle.fill", L("Couldn’t check for updates: {0}", u.Problem), small, Tint.Orange),
            _ => Note("info.circle", L("Not checked yet|updates"), small, null),
        };
        var name = UI.VStack(2, UI.Text($"{appName} {u.Version}", compact ? Font.Callout : Font.Body),
                             UI.Text(L("Build {0}", u.Build), Font.Caption).Secondary());
        var top = UI.HStack(8, name.Grow(), action);
        top.Alignment = 0.5;
        return UI.VStack(6, top, status);
    }

    static Stack Note(string symbol, string text, Font font, Windows.UI.Color? color)
    {
        var s = UI.HStack(6, UI.Icon(symbol, Theme.Size(font)), UI.Text(text, font).Wrap().Grow());
        if (color is { } c) s.Foreground(c); else s.Secondary();
        return s;
    }
}
