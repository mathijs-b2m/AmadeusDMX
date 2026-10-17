// Amadeus DMX for Windows: a native front end for the Python light engine.
using Microsoft.UI.Xaml.Input;
using Microsoft.Windows.AppLifecycle;
using Microsoft.Windows.Storage.Pickers;
using Windows.System;

namespace AmadeusDMX;

public sealed partial class App : Application
{
    AppModel? _model;
    MainWindow? _window;

    public App()
    {
        RequestedTheme = ApplicationTheme.Dark;  // like the Mac app on a dark Mac; the stage is dark either way
        UnhandledException += (_, e) =>
        {
            // whatever went wrong, never leave the lights on: stop the engine cleanly first
            _model?.Shutdown();
            e.Handled = false;
        };
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Resources.MergedDictionaries.Add(new XamlControlsResources());
        Defaults.Standard = new Defaults(Defaults.FileFor("Amadeus DMX"), Environment.GetCommandLineArgs());
        var updater = Updater.Create();  // NetSparkle, for a release with a feed (Settings/Updater.cs); nil in a development build
        _model = new AppModel(updater);
        _window = new MainWindow(_model);
        _window.Closed += (_, _) => _model.Shutdown();  // the last window: the app quits, the lights black out
        updater?.Attach(_model, _window);  // after Shutdown: a background download installs once the engine is stopped
        // ended from outside (logoff, a terminal's Ctrl+C): stop the engine first, like a normal quit
        AppDomain.CurrentDomain.ProcessExit += (_, _) => _model.Shutdown();
        _model.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(AppModel.EngineRunning) && !_model.EngineRunning) _model.Updates.BecameIdle();
        };
        // a second start (Program.Main): show this one
        var queue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
        AppInstance.GetCurrent().Activated += (_, _) => queue.TryEnqueue(() => _window.Activate());
        _window.Activate();
    }
}

/// The app's menu (the Mac's app menu and commands): in the title bar, with the shortcuts (⌘ → Ctrl, ⌥ → Alt).
public static class AppCommands
{
    const VirtualKeyModifiers Ctrl = VirtualKeyModifiers.Control, Shift = VirtualKeyModifiers.Shift, Alt = VirtualKeyModifiers.Menu;

    static MenuFlyoutItem Command(string title, Action action, VirtualKey key = VirtualKey.None, VirtualKeyModifiers mods = Ctrl)
    {
        var i = new MenuFlyoutItem { Text = title };
        i.Click += (_, _) => action();
        if (key != VirtualKey.None) i.KeyboardAccelerators.Add(new KeyboardAccelerator { Key = key, Modifiers = mods });
        return i;
    }

    public static MenuBar Build(AppModel model, MainWindow window)
    {
        var bar = new MenuBar();

        var file = new MenuBarItem { Title = "File" };
        file.Items.Add(Command("New Set…", window.OpenWizard, VirtualKey.N, Ctrl | Shift));
        file.Items.Add(Command("New Rig…", () => { model.Section = Section.Rig; model.ShowNewRig = true; }, VirtualKey.N, Ctrl | Alt)
            .Follow(model, [nameof(AppModel.Workspace)], i => i.IsEnabled = model.Workspace is not null));
        file.Items.Add(new MenuFlyoutSeparator());
        file.Items.Add(Command("Settings", () => model.Section = Section.Settings, (VirtualKey)0xBC /* the comma key */));
        file.Items.Add(new MenuFlyoutSeparator());
        file.Items.Add(Command("Exit", window.Close));
        bar.Items.Add(file);

        var show = new MenuBarItem { Title = "Show" };
        show.Items.Add(Command("Start Live Show", () => { if (model.EngineRunning) model.StopShow(); else model.StartLive(); }, VirtualKey.R)
            .Follow(model, [nameof(AppModel.EngineRunning), nameof(AppModel.Workspace)], i =>
            {
                i.Text = model.EngineRunning ? "Stop Show" : "Start Live Show";
                i.IsEnabled = model.Workspace is not null;
            }));
        show.Items.Add(Command("Play a Track…", () => PlayPanel.Choose(model, window), VirtualKey.O)
            .Follow(model, [nameof(AppModel.EngineRunning), nameof(AppModel.Workspace)],
                    i => i.IsEnabled = model.Workspace is not null && !model.EngineRunning));
        show.Items.Add(new MenuFlyoutSeparator());
        show.Items.Add(Command("DMX Devices & Output…", window.OpenDMX, VirtualKey.D, Ctrl | Shift)
            .Follow(model, [nameof(AppModel.Workspace)], i => i.IsEnabled = model.Workspace is not null));
        show.Items.Add(new MenuFlyoutSeparator());
        foreach (var m in ShowModes.All)
            show.Items.Add(UI.Choice(m.Title(), "mode", model.Mode == m, () => model.SetMode(m), m.Symbol())
                .Follow(model, [nameof(AppModel.Mode)], i => i.IsChecked = model.Mode == m));
        bar.Items.Add(show);

        var view = new MenuBarItem { Title = "View" };
        var n = 1;
        foreach (var s in SectionExtensions.All)
            view.Items.Add(Command(s.Title(), () => model.Section = s, VirtualKey.Number0 + n++));
        view.Items.Add(Command("Edit Rig Layout", model.EditLayout, VirtualKey.E));
        view.Items.Add(new MenuFlyoutSeparator());
        view.Items.Add(Command("Hide Director", () => model.ShowInspector = !model.ShowInspector, VirtualKey.I, Ctrl | Alt)
            .Follow(model, [nameof(AppModel.ShowInspector)], i => i.Text = model.ShowInspector ? "Hide Director" : "Show Director"));
        bar.Items.Add(view);

        var help = new MenuBarItem { Title = "Help" };
        if (model.Updates.IsAvailable)
            help.Items.Add(Command("Check for Updates…", model.Updates.CheckForUpdates)
                .Follow(model.Updates, [nameof(Updates.CanCheck)], i => i.IsEnabled = model.Updates.CanCheck));
        help.Items.Add(Command("About Amadeus DMX", window.ShowAbout));
        bar.Items.Add(help);
        return bar;
    }

    /// A menu item following the model (menu items aren't FrameworkElements: no UI.Bind; the menu lives as long as
    /// the window, so it simply stays subscribed).
    static T Follow<T>(this T item, System.ComponentModel.INotifyPropertyChanged model, string[] properties, Action<T> apply)
        where T : MenuFlyoutItemBase
    {
        apply(item);
        model.PropertyChanged += (_, e) => { if (e.PropertyName is null || properties.Contains(e.PropertyName)) apply(item); };
        return item;
    }
}

/// The file picker for "Play a Track…".
public static class PlayPanel
{
    static readonly string[] Audio = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aiff", ".aif", ".opus"];

    public static async void Choose(AppModel model, Window window)
    {
        var picker = new FileOpenPicker(window.AppWindow.Id)
        {
            CommitButtonText = "Play",  // choose a track to play with the lights
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var t in Audio) picker.FileTypeFilter.Add(t);
        if (await picker.PickSingleFileAsync() is { } file) model.Play(file.Path);
    }
}
