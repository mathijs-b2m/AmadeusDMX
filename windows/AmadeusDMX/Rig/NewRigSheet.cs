using AmadeusKit;
// A new rig (a venue): start from the structure that's there (an empty room, two stands, a truss over the
// booth, a club, a concert stage, a round truss), size it, and then mount your set on it: automatically or by hand.
// The port of mac/Sources/AmadeusDMX/Rig/NewRigSheet.swift: the sheets are ContentDialogs.
using System.Globalization;
using System.Text.RegularExpressions;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace AmadeusDMX;

/// The rig seen from the audience: the floor, the booth, trusses, towers.
public static class RigSketch
{
    public static FrameworkElement Build(RigTemplate template)
    {
        var canvas = new Canvas { Height = 64, HorizontalAlignment = HorizontalAlignment.Stretch, IsHitTestVisible = false };
        canvas.SizeChanged += (_, _) => Draw(canvas, template);
        return canvas;
    }

    static void Draw(Canvas c, RigTemplate template)
    {
        c.Children.Clear();
        double w = c.ActualWidth, h = c.ActualHeight, floor = h - 6;
        if (w <= 0) return;
        var line = Theme.Brush("TextFillColorSecondaryBrush");
        var truss = new SolidColorBrush(Tint.Accent);
        void Rect(double x, double y, double width, double height, Brush fill, double corner = 0)
        {
            var r = new Rectangle { Width = Math.Max(0, width), Height = Math.Max(0, height), Fill = fill, RadiusX = corner, RadiusY = corner };
            Canvas.SetLeft(r, x);
            Canvas.SetTop(r, y);
            c.Children.Add(r);
        }
        void Bar(double x, double y, double len) => Rect(x, y, len, 4, truss, 1);
        void Tower(double x, double top) => Rect(x, top, 4, floor - top, truss, 1);
        Rect(4, floor, w - 8, 2, line);
        Rect(w / 2 - 12, floor - 12, 24, 12, line, 2);
        switch (template)
        {
            case RigTemplate.Floor:
                foreach (var x in new[] { w * 0.25, w * 0.75 })
                    c.Children.Add(new Line { X1 = x, Y1 = floor, X2 = x, Y2 = floor - 18, Stroke = line, StrokeThickness = 1.5 });
                break;
            case RigTemplate.Stands:
                Tower(w * 0.2, h * 0.35); Tower(w * 0.8 - 4, h * 0.35);
                break;
            case RigTemplate.Booth:
                Bar(w * 0.2, h * 0.25, w * 0.6);
                break;
            case RigTemplate.Club:
                Bar(w * 0.12, h * 0.22, w * 0.76); Bar(w * 0.18, h * 0.12, w * 0.64);
                break;
            case RigTemplate.Stage:
                Bar(w * 0.1, h * 0.2, w * 0.8); Bar(w * 0.14, h * 0.1, w * 0.72); Bar(w * 0.22, floor - 22, w * 0.56);
                Tower(6, h * 0.18); Tower(w - 10, h * 0.18);
                break;
            case RigTemplate.Ring:  // seen a little from below: a flat ellipse, the half circle a wider arc behind it
            {
                double cx = w / 2, cy = h * 0.2, r = w * 0.36;
                Point At(double deg) => new(cx + r * Math.Cos(deg * Math.PI / 180), cy + r * Math.Sin(deg * Math.PI / 180));
                var fig = new PathFigure { StartPoint = At(195), IsClosed = false };
                fig.Segments.Add(new ArcSegment { Point = At(345), Size = new Size(r, r), SweepDirection = SweepDirection.Clockwise });
                var geo = new PathGeometry();
                geo.Figures.Add(fig);
                c.Children.Add(new Microsoft.UI.Xaml.Shapes.Path { Data = geo, Stroke = truss, StrokeThickness = 3 });
                var e = new Ellipse { Width = w * 0.46, Height = h * 0.16, Stroke = truss, StrokeThickness = 3.5 };
                Canvas.SetLeft(e, w * 0.27);
                Canvas.SetTop(e, h * 0.2);
                c.Children.Add(e);
                break;
            }
        }
    }
}

public sealed class NewRigSheet(AppModel model)
{
    RigTemplate _template = RigTemplate.Club;
    string _name = "club";
    double _width = 10, _height = 4.5, _depth = 15;
    bool _screen;
    readonly ContentControl _form = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };
    readonly List<(RigTemplate T, Border Card)> _cards = [];
    readonly TextBlock _error = UI.Text("", Font.Callout).Foreground(Tint.Red).Wrap();
    ContentDialog? _dialog;

    /// What the window calls when AppModel.ShowNewRig turns on.
    public static async void Present(AppModel model, MainWindow window)
    {
        if (window.Root is not { } root) { model.ShowNewRig = false; return; }
        try { await new NewRigSheet(model).Show(root); }
        finally { model.ShowNewRig = false; }
    }

    async Task Show(XamlRoot root)
    {
        var grid = new Grid { ColumnSpacing = 10, RowSpacing = 10 };
        for (var i = 0; i < 3; i++) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        for (var i = 0; i < 2; i++) grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var k = 0;
        foreach (var t in RigTemplates.All)
        {
            var card = TemplateCard(t);
            Grid.SetColumn(card, k % 3);
            Grid.SetRow(card, k / 3);
            grid.Children.Add(card);
            k++;
        }
        _dialog = new ContentDialog
        {
            XamlRoot = root, Title = "New Rig", PrimaryButtonText = "Create Rig", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Primary,
            Content = UI.Scroll(UI.VStack(16,
                UI.Text("A rig is the venue: the stage and what your fixtures hang on. Start from what's there; you can move and add trusses afterwards.")
                    .Secondary().Wrap(),
                grid, _form, _error).Frame(width: 680)),
        };
        _dialog.Resources["ContentDialogMaxWidth"] = 760.0;
        _dialog.PrimaryButtonClick += async (d, args) =>
        {
            var deferral = args.GetDeferral();
            try { args.Cancel = !await Create(); }
            finally { deferral.Complete(); }
        };
        Pick(RigTemplate.Club);
        await _dialog.ShowAsync();
    }

    Border TemplateCard(RigTemplate t)
    {
        var body = UI.VStack(6, RigSketch.Build(t), UI.Text(t.Title(), Font.Headline), UI.Text(t.Detail(), Font.Caption).Secondary().Wrap());
        body.Alignment = 0;
        var b = new Border
        {
            Child = body, Padding = new Thickness(12), CornerRadius = new CornerRadius(12), MinHeight = 150,
            Background = Theme.Brush("CardBackgroundFillColorSecondaryBrush"), BorderThickness = new Thickness(2),
            BorderBrush = new SolidColorBrush(Microsoft.UI.Colors.Transparent),
        };
        b.Tapped += (_, _) => Pick(t);
        _cards.Add((t, b));
        return b;
    }

    void Pick(RigTemplate t)
    {
        var wasDefault = RigTemplates.All.Any(x => x.RawValue() == _name) || _name.Length == 0;
        _template = t;
        (_width, _height, _depth) = t.Size();
        _screen = t is RigTemplate.Club or RigTemplate.Stage;
        if (wasDefault) _name = Unique(t.RawValue());
        foreach (var (ct, card) in _cards)
            card.BorderBrush = ct == t ? new SolidColorBrush(Tint.Accent) : new SolidColorBrush(Microsoft.UI.Colors.Transparent);
        _form.Content = Form();
        Validate();
    }

    void Validate()
    {
        if (_dialog is not null) _dialog.IsPrimaryButtonEnabled = _name.Trim().Length > 0;
    }

    string Unique(string prefix)
    {
        var n = prefix;
        for (var i = 2; model.Rigs.Any(r => r.Name == n); i++) n = $"{prefix}{i}";
        return n;
    }

    UIElement Form()
    {
        var name = new TextBox { Text = _name, PlaceholderText = "Name" };
        name.TextChanged += (_, _) => { _name = name.Text; Validate(); };
        return UI.Card(UI.VStack(12,
            UI.Row("Name", name.MinWidth(260)),
            SizeRow("Stage width", _width, 2, 30, 0.5, v => _width = v),
            _template == RigTemplate.Floor ? null
                : SizeRow(_template == RigTemplate.Stands ? "Stand height" : "Truss height", _height, 2, 12, 0.5, v => _height = v),
            SizeRow("Room depth", _depth, 4, 40, 1, v => _depth = v),
            UI.Row("LED wall behind the DJ", UI.Toggle("", _screen, v => _screen = v))));
    }

    /// A size with its slider (the wizard's SizeRow).
    static FrameworkElement SizeRow(string title, double value, double min, double max, double step, Action<double> set)
    {
        string Text(double v) => step < 1 ? v.ToString("0.0", CultureInfo.InvariantCulture) + " m" : $"{(int)v} m";
        var text = UI.Text(Text(value)).Secondary();
        text.Width = 56;
        text.TextAlignment = TextAlignment.Right;
        var slider = UI.Slider(value, min, max, v =>
        {
            var s = Math.Round(v / step, MidpointRounding.AwayFromZero) * step;
            set(s);
            text.Text = Text(s);
        }, step);
        return UI.HStack(8, UI.Text(title), UI.Spacer(), slider.MinWidth(240).Grow(), text);
    }

    async Task<bool> Create()
    {
        var rigName = Regex.Replace(_name.ToLowerInvariant(), "[^a-z0-9_-]+", "-");
        _error.Text = "";
        try
        {
            if (!await model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            await model.Api.CreateRig(rigName, _template.RawValue(), _width, _height, _depth, _screen);
            model.ReloadSets();
            model.Section = Section.Rig;
            model.EditingRig = rigName;   // open it on the Rigs page; sets are placed on it there
            model.EditingRigSet = "";
            return true;
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            _error.Text = "⚠ " + e.Message;
            return false;
        }
    }
}

/// "Mount your set on this rig?": automatically (a sensible start), or by hand in the rig editor.
/// MountPromptSheet.Present(model, window, rig, set) when AppModel.MountPrompt is set (the window's to call).
public sealed class MountPromptSheet(AppModel model, string rig, string set)
{
    ContentDialog? _dialog;
    readonly TextBlock _error = UI.Text("", Font.Callout).Foreground(Tint.Red).Wrap();
    readonly ProgressRing _spinner = UI.Spinner();
    readonly List<Button> _choices = [];

    public static async void Present(AppModel model, MainWindow window, string rig, string set)
    {
        if (window.Root is not { } root) { model.MountPrompt = null; return; }
        try { await new MountPromptSheet(model, rig, set).Show(root); }
        finally { model.MountPrompt = null; }
    }

    async Task Show(XamlRoot root)
    {
        var (placed, total) = model.Workspace?.Mounted(rig, set) ?? (0, 0);
        var waiting = total - placed;
        _spinner.Visible(false);
        _dialog = new ContentDialog
        {
            XamlRoot = root, CloseButtonText = "Later",
            Content = UI.VStack(18,
                UI.HStack(14, UI.Icon("square.split.bottomrightquarter", 34).Foreground(Tint.Accent),
                          UI.VStack(4, UI.Text($"Mount “{set}” on “{rig}”?", Font.Title2),
                                    UI.Text(placed == 0 ? $"None of the set's {total} fixtures hang on this rig yet."
                                            : $"{waiting} of the set's {total} fixtures don't hang on this rig yet.").Secondary().Wrap())),
                Choice("wand.and.stars", "Auto-Mount",
                       "Moving heads under the trusses, lasers high at the back, strobes and blinders on the front, bars and pars on the floor. Mirrored, model by model. Move anything afterwards.",
                       true, Auto),
                Choice("hand.draw", "I’ll Place Them Myself",
                       "They wait on the floor in front of the stage: drag them onto the trusses one by one, or a whole group at once.",
                       false, () => { _dialog?.Hide(); model.Section = Section.Rig; }),
                UI.HStack(8, _error.Grow(), _spinner)).Frame(width: 480),
        };
        await _dialog.ShowAsync();
    }

    Button Choice(string symbol, string title, string text, bool prominent, Action action)
    {
        var row = UI.HStack(12,
            UI.Icon(symbol, 22).Foreground(prominent ? new SolidColorBrush(Tint.Accent) : Theme.Brush("TextFillColorSecondaryBrush")).Frame(width: 30),
            UI.VStack(3, UI.Text(title, Font.Headline), UI.Text(text, Font.Callout).Secondary().Wrap()).Grow());
        var b = new Button
        {
            Content = row, HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(14), CornerRadius = new CornerRadius(12),
            Background = prominent ? Tint.Brush(Tint.Accent, 0.12) : Theme.Brush("CardBackgroundFillColorSecondaryBrush"),
        };
        b.Click += (_, _) => action();
        _choices.Add(b);
        return b;
    }

    async void Auto()
    {
        _spinner.Visible(true);
        foreach (var c in _choices) c.IsEnabled = false;
        try
        {
            await model.AutoMount(rig, set);
            _dialog?.Hide();
            model.Section = Section.Rig;
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            _error.Text = "⚠ " + e.Message;
        }
        finally
        {
            _spinner.Visible(false);
            foreach (var c in _choices) c.IsEnabled = true;
        }
    }
}
