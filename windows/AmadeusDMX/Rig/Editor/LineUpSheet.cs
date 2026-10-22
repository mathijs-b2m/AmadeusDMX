// Line Up…: puts a drawing under the rig right with two clicks on its page, the stage's front edge at stage left and
// then at stage right, and the distance between them (amadeus/rig/importer/underlay.py align). What the import
// thought shows faintly. The editor posts it (RigEditorModel.LineUp); the engine moves the drawing's fixtures and
// their trusses and saves the rig.
// The port of mac/Sources/AmadeusDMX/Rig/Editor/LineUpSheet.swift (docs/import-ui.md): a ContentDialog.
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace AmadeusDMX;

public sealed class LineUpSheet(Underlay drawing, DrawingPicture picture, double stageWidth)
{
    const double MaxWidth = 700, MaxHeight = 470;

    Vec2? _sl, _sr;
    readonly Canvas _marks = new() { IsHitTestVisible = false };
    readonly TextBlock _status = UI.Text("", Font.Callout).Secondary().Wrap();
    NumberBox? _distance;
    ContentDialog? _dialog;
    double _w, _h;

    /// The two clicks (page fractions from the top left: stage left, stage right) and the distance between them, or
    /// nil when cancelled.
    public async Task<(Vec2 A, Vec2 B, double WidthM)?> Show(XamlRoot root)
    {
        var k = Math.Min(MaxWidth / Math.Max(1, picture.Width), MaxHeight / Math.Max(1, picture.Height));
        (_w, _h) = (picture.Width * k, picture.Height * k);
        var page = new Grid { Width = _w, Height = _h, Background = new SolidColorBrush(Microsoft.UI.Colors.White) };
        page.Children.Add(new Image { Source = DrawingPages.Bitmap(picture), Stretch = Stretch.Fill, Width = _w, Height = _h });
        page.Children.Add(_marks);
        page.PointerPressed += (_, e) =>
        {
            if (!e.GetCurrentPoint(page).Properties.IsLeftButtonPressed) return;
            var p = e.GetCurrentPoint(page).Position;
            Click(new Vec2(Math.Clamp(p.X / _w, 0, 1), Math.Clamp(p.Y / _h, 0, 1)));
            e.Handled = true;
        };
        // zoomable (Ctrl + wheel, pinch), the whole page fitting to begin with
        var scroll = new ScrollViewer
        {
            Content = page, ZoomMode = ZoomMode.Enabled, MinZoomFactor = 1, MaxZoomFactor = 8, Width = MaxWidth, Height = MaxHeight,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            HorizontalScrollMode = ScrollMode.Auto, VerticalScrollMode = ScrollMode.Auto,
            HorizontalContentAlignment = HorizontalAlignment.Center, VerticalContentAlignment = VerticalAlignment.Center,
        };

        var width = stageWidth > 0 ? stageWidth : drawing.WidthM > 0 ? drawing.WidthM : 8;
        _distance = new NumberBox
        {
            Value = Math.Round(width, 2), Minimum = 0.5, Maximum = 200, SmallChange = 0.5, LargeChange = 1,
            SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline, Width = 150,
        };
        _distance.ValueChanged += (_, _) => Validate();
        _distance.Tooltip("How far apart the two points are (metres): the stage's width, or the hall's when you clicked its side walls");

        _dialog = new ContentDialog
        {
            XamlRoot = root, Title = $"Line Up “{drawing.Name}”", PrimaryButtonText = "Line Up", CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            Content = UI.VStack(10,
                UI.Text("Click the stage's front edge at stage left, then at stage right.", Font.Headline).Wrap(),
                UI.Text("Stage left is the performers' left: on the usual plan, with the audience at the bottom, that is on the right of the page. On a hall plan without the stage, click where the hall meets the stage at its two side walls, and type the hall's width.",
                        Font.Callout).Secondary().Wrap(),
                scroll,
                UI.HStack(10, _status.Grow(), UI.Text("Distance"), _distance, UI.Text("m").Secondary())).Frame(width: MaxWidth),
        };
        _dialog.Resources["ContentDialogMaxWidth"] = MaxWidth + 80;
        page.Tooltip("The faint marks: where the import thought the stage's front edge is");
        Draw();
        Validate();
        if (await Dialogs.Show(_dialog) != ContentDialogResult.Primary || _sl is not { } a || _sr is not { } b || Distance is not { } d) return null;
        return (a, b, d);
    }

    double? Distance => _distance is { Value: var v } && v > 0 ? v : null;   // NaN (an empty field) is no distance

    /// The first click is stage left, the second stage right; a third starts over.
    void Click(Vec2 f)
    {
        if (_sl is null || _sr is not null) { _sl = f; _sr = null; }
        else _sr = f;
        Draw();
        Validate();
    }

    void Validate()
    {
        if (_dialog is not null) _dialog.IsPrimaryButtonEnabled = _sl is not null && _sr is not null && Distance is not null;
        _status.Text = _sl is null ? "Click stage left (SL) on the page."
            : _sr is null ? "Now click stage right (SR)."
            : "Line Up moves the drawing's fixtures there. Click again to start over.";
    }

    void Draw()
    {
        _marks.Children.Clear();
        // what the import thought: faint
        Pair(drawing.A, drawing.B, faint: true);
        if (_sl is { } a) Pair(a, _sr, faint: false);
    }

    void Pair(Vec2 a, Vec2? b, bool faint)
    {
        var color = faint ? Tint.Gray : Tint.Orange;
        if (b is { } bb)
        {
            var line = new Line
            {
                X1 = a.X * _w, Y1 = a.Y * _h, X2 = bb.X * _w, Y2 = bb.Y * _h, Stroke = new SolidColorBrush(color), StrokeThickness = faint ? 1.5 : 2.5,
                Opacity = faint ? 0.6 : 1,
            };
            if (faint) line.StrokeDashArray = [4, 3];
            _marks.Children.Add(line);
        }
        Marker(a, "SL", color, faint);
        if (b is { } b2) Marker(b2, "SR", color, faint);
    }

    void Marker(Vec2 f, string label, Windows.UI.Color color, bool faint)
    {
        double x = f.X * _w, y = f.Y * _h;
        var dot = new Ellipse
        {
            Width = 12, Height = 12, Fill = new SolidColorBrush(color), Stroke = new SolidColorBrush(Tint.White), StrokeThickness = 1.5,
            Opacity = faint ? 0.5 : 1,
        };
        Canvas.SetLeft(dot, x - 6);
        Canvas.SetTop(dot, y - 6);
        _marks.Children.Add(dot);
        var tag = new Border
        {
            Child = UI.Text(label, Font.Caption).Bold().Foreground(Tint.White), Background = new SolidColorBrush(color),
            CornerRadius = new CornerRadius(4), Padding = new Thickness(4, 1, 4, 1), Opacity = faint ? 0.5 : 1,
        };
        Canvas.SetLeft(tag, x + 8);
        Canvas.SetTop(tag, y - 22);
        _marks.Children.Add(tag);
    }
}
