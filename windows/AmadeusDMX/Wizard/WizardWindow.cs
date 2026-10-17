// "Set Up a Rig": a step-by-step assistant for a new set (and for the first launch), a window of its own
// (mac/Sources/AmadeusDMX/Wizard/WizardView.swift). The state and its rules are the kit's WizardModel.
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Shapes;

namespace AmadeusDMX;

public sealed partial class WizardWindow : Window
{
    readonly AppModel _model;
    readonly WizardModel _w = new();

    public WizardWindow(AppModel model)
    {
        _model = model;
        Title = "Set Up a Rig";
        var icon = System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusDMX.ico");
        if (File.Exists(icon)) AppWindow.SetIcon(icon);
        SystemBackdrop = new MicaBackdrop();
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;  // Resize is in pixels
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(820 * scale), (int)(600 * scale)));
        if (AppWindow.Presenter is OverlappedPresenter p)
        {
            p.IsResizable = false;
            p.IsMaximizable = false;
        }
        Content = new WizardView(model, _w, Close).Build();
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(IntPtr hwnd);
}

/// What the app gives the wizard (the kit's IWizardHost).
public sealed class AppWizardHost(AppModel model) : IWizardHost
{
    public SetupAPI Api => model.Api;
    public Task<bool> EnsureSetupService() => model.EnsureSetupService();
    public IReadOnlyList<SetSummary> Sets => model.Sets;
    public IReadOnlyList<RigSummary> Rigs => model.Rigs;
    public void ReloadSets() => model.ReloadSets();

    public void Select(string rig, string set)
    {
        model.SelectedSet = set;
        model.SelectedRig = rig;
    }
}

public sealed class WizardView(AppModel model, WizardModel w, Action dismiss)
{
    readonly ContentControl _content = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        var rail = new Border
        {
            Width = 190, Background = Theme.Brush("LayerFillColorDefaultBrush"),
            Child = UI.Live(w, () => StepRail.Build(w.Step), nameof(WizardModel.Step)),
        };
        var scroll = UI.Scroll(_content.Padding(new Thickness(36, 40, 36, 20)));
        var bottom = UI.Live(w, BottomBar, nameof(WizardModel.Step), nameof(WizardModel.Creating), nameof(WizardModel.Error),
                             nameof(WizardModel.Progress), nameof(WizardModel.CanContinue), nameof(WizardModel.AutoMount))
            .Bind(model, nameof(AppModel.Workspace), c => c.Content = BottomBar());
        var right = new Grid();
        right.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        right.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        right.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var line = UI.Divider();
        var bar = bottom.Padding(20, 14);
        Grid.SetRow(scroll, 0);
        Grid.SetRow(line, 1);
        Grid.SetRow(bar, 2);
        right.Children.Add(scroll);
        right.Children.Add(line);
        right.Children.Add(bar);
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        Grid.SetColumn(rail, 0);
        Grid.SetColumn(right, 1);
        root.Children.Add(rail);
        root.Children.Add(right);
        // a step's page, and what entering it needs (SwiftUI's .task(id: w.step))
        root.Bind(w, nameof(WizardModel.Step), g =>
        {
            _content.Content = Content();
            scroll.ChangeView(null, 0, null, true);
            _ = Enter(w.Step);
        });
        return root;
    }

    UIElement Content() => w.Step switch
    {
        WizardStep.Welcome => WelcomeStep.Build(),
        WizardStep.Engine => new EngineStep(model).Build(),
        WizardStep.Fixtures => new FixturesStep(model, w).Build(),
        WizardStep.Network => new NetworkStep(model, w).Build(),
        WizardStep.Rig => new RigStep(model, w).Build(),
        WizardStep.Director => DirectorStep.Build(w),
        WizardStep.Review => ReviewStep.Build(w),
        _ => DoneStep.Build(w),
    };

    UIElement BottomBar()
    {
        var row = UI.HStack(8);
        if (w.Creating)
        {
            row.Children.Add(UI.Spinner());
            row.Children.Add(UI.Text(w.Progress, Font.Callout).Secondary());
        }
        else if (w.Error is { } e)
            row.Children.Add(Form.Note("exclamationmark.triangle.fill", e, Tint.Red).Grow());
        row.Children.Add(UI.Spacer());
        if (w.Step is not WizardStep.Welcome and not WizardStep.Done)
            row.Children.Add(UI.Button("Back", () => w.Step = w.PreviousStep).Disabled(w.Creating));
        Button main;
        switch (w.Step)
        {
            case WizardStep.Review:
                main = UI.Button(w.AutoMount ? "Create and Mount" : "Create", () => _ = w.Create(new AppWizardHost(model)))
                    .Disabled(!w.CanContinue || w.Creating);
                break;
            case WizardStep.Done:
                main = UI.Button(w.AutoMount ? "Open the Show" : "Place the Fixtures", () =>
                {
                    model.Section = w.AutoMount ? Section.Show : Section.Rig;
                    dismiss();
                });
                break;
            default:
                main = UI.Button(w.Step == WizardStep.Welcome ? "Get Started" : "Continue", Next)
                    .Disabled(!w.CanContinue || (w.Step == WizardStep.Engine && model.Workspace is null));
                break;
        }
        main.Prominent();
        row.Children.Add(main);
        return row;
    }

    void Next() => w.Step = w.NextStep(model.Workspace?.IsValid == true, model.Sets.Count > 0);

    async Task Enter(WizardStep s)
    {
        w.Error = null;
        if (s is not (WizardStep.Fixtures or WizardStep.Network or WizardStep.Director)) return;
        await model.EnsureSetupService();
        if (s == WizardStep.Director && w.Directors.Count == 0)
        {
            try { w.Directors = await model.Api.Directors(); }
            catch (Exception e) when (SetView.IsApiError(e)) { }
            if (w.Directors.FirstOrDefault(d => d.Value == "openai" && d.Available) is { } ai) w.Director = ai.Value;
        }
    }
}

/// The steps down the left: done ones ticked, the current one in the accent colour.
public static class StepRail
{
    public static UIElement Build(WizardStep current)
    {
        var s = UI.VStack(4, UI.HStack(8, AppIcon(20), UI.Text("Set Up", Font.Headline)).Margin(0, 0, 0, 18));
        foreach (var step in WizardSteps.All.Where(x => x != WizardStep.Welcome))
        {
            var done = step < current;
            var here = step == current;
            var accent = Tint.Accent;
            var circle = new Ellipse
            {
                Width = 20, Height = 20,
                Fill = done ? Tint.Brush(accent) : here ? Tint.Brush(accent, 0.25) : Tint.Brush(Tint.Gray, 0.15),
            };
            UIElement mark = done
                ? UI.Icon("checkmark", 10).Foreground(Tint.White).Align(HorizontalAlignment.Center)
                : UI.Text($"{(int)step}", Font.Caption2).Bold().Foreground(here ? Tint.Brush(accent) : Theme.Brush("TextFillColorSecondaryBrush"))
                    .Center();
            var dot = UI.ZStack(circle, mark).Frame(20, 20);
            var title = UI.Text(step.Title(), Font.Callout);
            if (here) title.Bold();
            if (step > current) title.Secondary();
            s.Children.Add(UI.HStack(10, dot, title).Padding(0, 5));
        }
        return s.Padding(20);
    }

    public static Image AppIcon(double size) => new()
    {
        Source = new BitmapImage(new Uri(System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusDMX.ico"))),
        Width = size, Height = size,
    };
}

/// A step's symbol (nil: the app icon), title and what it is about.
public static class StepHeader
{
    public static FrameworkElement Build(string? symbol, string title, string text) =>
        UI.VStack(8,
            symbol is null ? StepRail.AppIcon(56) : UI.Icon(symbol, 34).Foreground(Tint.Accent),
            UI.Text(title, Font.LargeTitle).Bold().Wrap(),
            UI.Text(text, Font.Title3).Secondary().Wrap()
        ).Margin(0, 0, 0, 20);
}

/// A symbol, a title and a line (the welcome and done steps).
public static class Feature
{
    public static FrameworkElement Build(string symbol, string title, string text)
    {
        var row = UI.HStack(14,
            UI.Icon(symbol, 22).Foreground(Tint.Accent).Frame(width: 34),
            UI.VStack(2, UI.Text(title, Font.Headline), UI.Text(text).Secondary().Wrap()).Grow());
        row.Alignment = 0;
        return row;
    }
}

/// A card that is a button (the wizard's choices: a node, a director, a template).
public static class ChoiceCard
{
    public static Button Build(UIElement content, Action action, bool selected = false, bool enabled = true)
    {
        var b = new Button
        {
            Content = content, HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(10), CornerRadius = new CornerRadius(10), IsEnabled = enabled,
            Background = Theme.Brush("CardBackgroundFillColorDefaultBrush"),
            BorderBrush = selected ? Tint.Brush(Tint.Accent) : Theme.Brush("CardStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(selected ? 2 : 1),
        };
        b.Click += (_, _) => action();
        return b;
    }

    /// A radio dot (SwiftUI's largecircle.fill.circle / circle).
    public static FontIcon Radio(bool on, bool enabled = true) =>
        UI.Icon(on ? "largecircle.fill.circle" : "circle").Foreground(enabled ? Tint.Brush(Tint.Accent) : Theme.Brush("TextFillColorSecondaryBrush"));
}
