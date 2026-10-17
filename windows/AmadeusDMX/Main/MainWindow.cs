// The main window: the menu in the title bar, a sidebar (Show, Sets, Rigs, Engine, Settings), the set on the rig
// and the engine controls in the toolbar above the page.
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;

namespace AmadeusDMX;

public sealed partial class MainWindow : Window
{
    readonly AppModel _model;
    readonly Dictionary<Section, FrameworkElement> _pages = [];
    readonly ContentControl _page = new()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
    };
    readonly NavigationView _nav = new();
    bool _askedOnce;

    public MainWindow(AppModel model)
    {
        _model = model;
        Title = "Amadeus DMX";
        ExtendsContentIntoTitleBar = true;
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        var icon = Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusDMX.ico");
        if (File.Exists(icon)) AppWindow.SetIcon(icon);
        SystemBackdrop = new MicaBackdrop();
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;  // Resize is in pixels
        AppWindow.Resize(new SizeInt32((int)(1440 * scale), (int)(900 * scale)));
        if (AppWindow.Presenter is OverlappedPresenter p)
        {
            p.PreferredMinimumWidth = 980;
            p.PreferredMinimumHeight = 620;
        }
        Content = Build(out var dragRegion);
        SetTitleBar(dragRegion);
        Activated += (_, _) => FirstShown();
        // a new rig, or a set placed on one: ask how the set goes on it (Swift: MainView's .sheet(item: mountPrompt))
        model.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(AppModel.MountPrompt) && model.MountPrompt is { } m)
                MountPromptSheet.Present(model, this, m.Rig, m.Set);
        };
    }

    FrameworkElement Build(out UIElement dragRegion)
    {
        // the title bar: the icon, the name, the menu; the rest of it drags the window
        var drag = new Border { Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent) };
        dragRegion = drag;
        var titleBar = UI.HStack(10,
            new Image { Source = new Microsoft.UI.Xaml.Media.Imaging.BitmapImage(new Uri(Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusDMX.ico"))), Width = 16, Height = 16 },
            UI.Text("Amadeus DMX", Font.Caption),
            AppCommands.Build(_model, this),
            drag.Grow().Fill()
        ).Padding(14, 0).Frame(height: 48);

        // the sidebar and the page
        var sidebar = new Sidebar(_model, this);
        _nav.PaneDisplayMode = NavigationViewPaneDisplayMode.Left;
        _nav.IsBackButtonVisible = NavigationViewBackButtonVisible.Collapsed;
        _nav.IsSettingsVisible = false;
        _nav.OpenPaneLength = 230;
        _nav.IsTitleBarAutoPaddingEnabled = false;
        foreach (var item in sidebar.Items()) _nav.MenuItems.Add(item);
        _nav.PaneFooter = sidebar.Footer();
        _nav.SelectionChanged += (_, e) => { if (e.SelectedItem is NavigationViewItem { Tag: Section s }) _model.Section = s; };
        _nav.Bind(_model, nameof(AppModel.Section), n =>
        {
            n.SelectedItem = n.MenuItems.OfType<NavigationViewItem>().FirstOrDefault(i => i.Tag is Section s && s == _model.Section);
            ShowPage();
        });
        _nav.Bind(_model, nameof(AppModel.NeedsSetup), _ => { _pages.Clear(); ShowPage(); });

        var detail = new Grid();
        detail.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        detail.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        detail.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var toolbar = Toolbar();
        var banner = new LimiterBanner(_model).Build();  // a row of its own above the page: it pushes the page down, never covers it
        Grid.SetRow(toolbar, 0);
        Grid.SetRow(banner, 1);
        Grid.SetRow(_page, 2);
        detail.Children.Add(toolbar);
        detail.Children.Add(banner);
        detail.Children.Add(_page);
        _nav.Content = detail;

        var root = new Grid();
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        Grid.SetRow(titleBar, 0);
        Grid.SetRow(_nav, 1);
        root.Children.Add(titleBar);
        root.Children.Add(_nav);

        // a mode change that needs the show restarted asks first; New Rig… opens its sheet
        root.Bind(_model, nameof(AppModel.PendingMode), _ => { if (_model.PendingMode is { } m) AskToSwitch(m); });
        root.Bind(_model, nameof(AppModel.ShowNewRig), _ => { if (_model.ShowNewRig) NewRigSheet.Present(_model, this); });
        return root;
    }

    /// The page's title and what it is about (the Mac's navigation title and subtitle), then the tools.
    FrameworkElement Toolbar()
    {
        var title = UI.Text("", Font.Headline);
        var subtitle = UI.Text("", Font.Caption).Secondary();
        void Titles(FrameworkElement _)
        {
            title.Text = _model.Section == Section.Show ? (_model.ShowState.IsActive ? _model.Feed.Hello?.Title ?? "Show" : "Show") : _model.Section.Title();
            subtitle.Text = Subtitle();
        }
        var showOnly = UI.HStack(8, new SetMenu(_model).Build(), new DirectorMenu(_model).Build())
            .Bind(_model, nameof(AppModel.Section), s => s.Visible(_model.Section == Section.Show));  // the combination the show runs: only on the Show page
        var inspector = UI.IconButton("sidebar.trailing", "Show what the director decided for this phrase", () => _model.ShowInspector = !_model.ShowInspector)
            .Bind(_model, nameof(AppModel.Section), b => b.Visible(_model.Section == Section.Show));
        var bar = UI.HStack(8,
            UI.VStack(0, title, subtitle).MinWidth(120),
            showOnly,
            UI.Spacer(),
            new StatusPill(_model).Build(),
            UI.Spacer(),
            new LimiterButton(_model).Build(),
            new ModeMenu(_model).Build(),
            new EngineButton(_model, this).Build(),
            inspector
        ).Padding(16, 8);
        bar.BindAll(_model, Titles);
        bar.Bind(_model.Feed, nameof(LiveFeed.Hello), Titles);
        return bar;
    }

    string Subtitle()
    {
        var m = _model;
        switch (m.Section)  // each page about its own thing
        {
            case Section.Set:
                return m.Sets.FirstOrDefault(s => s.Name == m.EditingSet) is { } set ? $"{set.FixtureCount} fixtures" : "";
            case Section.Rig:
                return m.Rigs.FirstOrDefault(r => r.Name == m.EditingRig) is { } r
                    ? r.Summary + (m.EditingRigSet.Length == 0 ? "" : $" · {m.EditingRigSet} on it") : "";
            case Section.Engine or Section.Settings:
                return "";
        }
        if (m.ShowState.IsActive)
            return m.Feed.Hello is { } h ? $"{(int)Math.Round(h.Bpm)} BPM · {m.ShowTitle}" : m.ShowTitle;
        var (placed, total) = m.Mounted;
        if (total == 0) return m.CurrentRig?.Summary ?? "";
        return placed < total ? $"{total - placed} of {total} fixtures not mounted" : $"{total} fixtures · {m.CurrentRig?.Summary ?? ""}";
    }

    void ShowPage()
    {
        var s = _model.NeedsSetup ? (Section?)null : _model.Section;
        if (s is not { } section) { _page.Content = EngineMissingView(); return; }
        if (!_pages.TryGetValue(section, out var page))
        {
            page = section switch
            {
                Section.Show => new ShowView(_model).Build(),
                Section.Rig => new RigView(_model).Build(),
                Section.Set => new SetView(_model, this).Build(),
                Section.Engine => new EngineView(_model).Build(),
                _ => new SettingsView(_model).Build(),
            };
            _pages[section] = page;  // built once: a page keeps its state (scroll, selection) when you come back
        }
        _page.Content = page;
    }

    FrameworkElement EngineMissingView() =>
        UI.Unavailable("shippingbox", "Engine Not Found", "Amadeus DMX needs its engine folder (with the Python environment).",
                       UI.Button("Set Up…", OpenWizard).Prominent());

    void FirstShown()
    {
        if (_askedOnce) return;
        _askedOnce = true;
        if (_model.NeedsSetup || _model.Sets.Count == 0 || Defaults.Standard.Bool("wizard")) OpenWizard();
    }

    // MARK: other windows and dialogs

    WizardWindow? _wizard;
    DMXWindow? _dmx;

    public void OpenWizard()
    {
        if (_wizard is null)
        {
            _wizard = new WizardWindow(_model);
            _wizard.Closed += (_, _) => _wizard = null;
        }
        _wizard.Activate();
    }

    public void OpenDMX()
    {
        if (_model.Workspace is null) return;
        if (_dmx is null)
        {
            _dmx = new DMXWindow(_model);
            _dmx.Closed += (_, _) => _dmx = null;
        }
        _dmx.Activate();
    }

    public XamlRoot? Root => Content?.XamlRoot;

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(IntPtr hwnd);

    async void AskToSwitch(ShowMode m)
    {
        if (Root is null) return;
        var dialog = new ContentDialog
        {
            XamlRoot = Root,
            Title = $"Switch to {m.Title()}?",
            Content = UI.Text(m.SendsDMX() ? "Sending to the lights needs the show to restart. It picks up where it was in a few seconds."
                              : "The show restarts without sending to the lights: the lights black out.").Wrap(),
            PrimaryButtonText = "Restart Show",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() == ContentDialogResult.Primary) _model.ConfirmPendingMode();
        else _model.PendingMode = null;
    }

    public async void ShowAbout()
    {
        if (Root is null) return;
        var version = typeof(App).Assembly.GetCustomAttributes(typeof(System.Reflection.AssemblyInformationalVersionAttribute), false)
            .OfType<System.Reflection.AssemblyInformationalVersionAttribute>().FirstOrDefault()?.InformationalVersion ?? "";
        await new ContentDialog
        {
            XamlRoot = Root,
            Title = "Amadeus DMX",
            Content = UI.Text($"Version {version}"),
            CloseButtonText = "OK",
        }.ShowAsync();
    }
}
