// The track as a timeline: the director's sections over the energy curve, with the playhead.
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace AmadeusDMX;

public sealed class TimelineCard(AppModel model, Hello hello)
{
    int? _hover;
    readonly Canvas _canvas = new() { Height = 54, Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent) };  // a background: it takes the pointer
    readonly Rectangle _playhead = new() { Width = 2, Height = 54, IsHitTestVisible = false };
    readonly TranslateTransform _playheadAt = new();
    readonly Stack _header = UI.HStack();

    public FrameworkElement Build()
    {
        _playhead.Fill = ShowUI.Ink(1);
        _playhead.RenderTransform = _playheadAt;
        _canvas.SizeChanged += (_, _) => { Draw(); MovePlayhead(); };
        _canvas.PointerMoved += (_, e) =>
        {
            var t = Timeline.Time(e.GetCurrentPoint(_canvas).Position.X, _canvas.ActualWidth, hello.Duration);
            var i = hello.PhraseIndex(t);
            if (i != _hover) { _hover = i; Header(); }
        };
        _canvas.PointerExited += (_, _) => { _hover = null; Header(); };
        _canvas.Tapped += (_, e) =>
        {
            if (model.PlayingFile is not { } file) return;
            var t = Timeline.Time(e.GetPosition(_canvas).X, _canvas.ActualWidth, hello.Duration);
            model.Engine.StopAndWait();
            model.Play(file, t);
        };
        // the phrase playing is drawn brighter; only the playhead moves with the time (the drawing stays put)
        _canvas.Bind(model.Feed, nameof(LiveFeed.Phrase), _ => Draw());
        _playhead.Bind(model.Feed, nameof(LiveFeed.Time), _ => MovePlayhead());
        _header.Bind(model, nameof(AppModel.PlayingFile), _ => Header());
        var card = UI.VStack(6, _header, _canvas);
        return ShowUI.Glass(card, padding: 12).Grow();
    }

    void Header()
    {
        _header.Children.Clear();
        if (_hover is { } i && i >= 0 && i < hello.Plan.Count)
            _header.Children.Add(UI.Text(Timeline.Describe(hello.Plan[i]), Font.Caption).Secondary().Lines(1));
        else
        {
            _header.Children.Add(UI.Text("Timeline", Font.Caption).Bold().Secondary());
            if (model.PlayingFile is not null) _header.Children.Add(UI.Text("· click to jump", Font.Caption).Foreground(ShowUI.Tertiary));
        }
        _header.Children.Add(UI.Spacer());
    }

    void MovePlayhead() => _playheadAt.X = Timeline.PlayheadX(model.Feed.Time, hello.Duration, _canvas.ActualWidth);

    void Draw()
    {
        double w = _canvas.ActualWidth, h = _canvas.Height;
        _canvas.Children.Clear();
        if (w <= 0) return;
        const double bar = Timeline.BarHeight;
        // phrases, coloured by section
        for (var i = 0; i < hello.Plan.Count; i++)
        {
            var d = hello.Plan[i];
            var (x, width) = Timeline.Bar(d, hello, w);
            var r = new Rectangle
            {
                Width = width, Height = bar, RadiusX = 3, RadiusY = 3,
                Fill = ShowUI.Section(d.Section, i == model.Feed.Phrase ? 1 : 0.7), IsHitTestVisible = false,
            };
            Canvas.SetLeft(r, x);
            Canvas.SetTop(r, h - bar);
            _canvas.Children.Add(r);
        }
        // loudness
        var pts = Timeline.Energy(hello.Energy, w, h);
        if (pts.Count > 0)
        {
            var points = new PointCollection();
            foreach (var (x, y) in pts) points.Add(new Point(x, y));
            _canvas.Children.Add(new Polygon { Points = points, Fill = ShowUI.Ink(0.13), IsHitTestVisible = false });
            var outline = new PointCollection();
            foreach (var (x, y) in pts) outline.Add(new Point(x, y));
            _canvas.Children.Add(new Polyline { Points = outline, Stroke = ShowUI.Ink(0.45), StrokeThickness = 1, IsHitTestVisible = false });
        }
        // drops
        foreach (var d in Timeline.Drops(hello))
        {
            var r = new Rectangle { Width = 1.5, Height = h - bar, Fill = Tint.Brush(Tint.Yellow, 0.8), IsHitTestVisible = false };
            Canvas.SetLeft(r, Timeline.X(d.Start, hello.Duration, w) - 0.75);
            _canvas.Children.Add(r);
        }
        _canvas.Children.Add(_playhead);
    }
}
