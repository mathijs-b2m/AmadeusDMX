// Which version this app is, whether it's the newest, and the one click that updates it (the Mac's
// AmadeusKit/UpdateStatusView.swift). Amadeus DMX shows it in Settings › Updates, Amadeus Link in its window.
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
            UpdateState.Available => UI.Button($"Update to {u.Newest}", () => u.InstallNewest()).Prominent().Disabled(!u.CanCheck),
            UpdateState.Downloading => UI.Button("Cancel", u.CancelInstall),
            UpdateState.Checking or UpdateState.Installing => null,
            _ => UI.Button("Check Again", () => u.Refresh(force: true)).Disabled(!u.CanCheck).Font(small),
        };
        UIElement status = u.State switch
        {
            UpdateState.Checking => UI.HStack(6, UI.Spinner(14), UI.Text("Checking for the newest version…", small).Secondary()),
            UpdateState.UpToDate => Note("checkmark.circle.fill",
                u.Newest is { } n ? (n == u.Version ? $"Up to date: {n} is the newest" : $"Up to date (newest: {n})") : "Up to date",
                small, Tint.Green),
            UpdateState.Available => Note("arrow.down.circle", $"{u.Newest} is available: you have {u.Version}", small, Tint.Orange),
            UpdateState.Downloading => UI.VStack(4, UI.Text($"Downloading {u.Newest}…", small).Secondary(), UI.Progress(u.Progress)),
            UpdateState.Installing => u.WaitingForIdle
                ? Note("clock", $"{u.Newest} is ready: it installs {whenIdle}", small, null)
                : Note("arrow.triangle.2.circlepath", $"Installing {u.Newest}: {appName} starts again", small, null),
            UpdateState.Failed => Note("exclamationmark.triangle.fill", $"Couldn’t check for updates: {u.Problem}", small, Tint.Orange),
            _ => Note("info.circle", "Not checked yet", small, null),
        };
        var name = UI.VStack(2, UI.Text($"{appName} {u.Version}", compact ? Font.Callout : Font.Body),
                             UI.Text($"Build {u.Build}", Font.Caption).Secondary());
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
