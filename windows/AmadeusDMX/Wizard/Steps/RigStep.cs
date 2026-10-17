// Wizard step 2 and 3: the rig your fixtures go on (a new one from a template, or one you have), and how they
// go on it (auto-mounted, or by hand afterwards) (mac/Sources/AmadeusDMX/Wizard/Steps/RigStep.swift).
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace AmadeusDMX;

public sealed class RigStep(AppModel model, WizardModel w)
{
    public UIElement Build() =>
        UI.VStack(14,
            StepHeader.Build("square.split.bottomrightquarter", "Where Do They Hang?",
                "A rig is the venue: the stage and what your fixtures hang on. You can have one per venue and mount the same set on each."),
            UI.Live(w, Body, nameof(WizardModel.UseExistingRig), nameof(WizardModel.Template), nameof(WizardModel.AutoMount)));

    UIElement Body()
    {
        var s = UI.VStack(14);
        if (model.Rigs.Count > 0)
            s.Children.Add(UI.Segmented([false, true], w.UseExistingRig, v => v ? "A rig I have" : "A new rig", v => w.UseExistingRig = v));
        if (w.UseExistingRig)
        {
            if (w.ExistingRig.Length == 0) w.ExistingRig = model.SelectedRig;
            s.Children.Add(Form.Row("Rig", UI.Picker(model.Rigs.Select(r => r.Name).ToList(), w.ExistingRig,
                n => model.Rigs.FirstOrDefault(r => r.Name == n) is { } r ? $"{r.Name} — {r.Summary}" : n, n => w.ExistingRig = n)));
        }
        else
        {
            var cards = UI.HStack(8);
            foreach (var t in RigTemplates.All)
            {
                var card = ChoiceCard.Build(UI.VStack(4, Sketch.Build(t).Frame(height: 44), UI.Text(t.Title(), Font.Caption).Bold().Wrap(2)),
                                            () => w.Template = t, selected: w.Template == t).Tooltip(t.Detail());
                card.MinHeight = 90;
                card.VerticalContentAlignment = VerticalAlignment.Top;
                cards.Children.Add(card.Grow());
            }
            s.Children.Add(cards);
            var rows = new List<UIElement?>
            {
                Form.Row("Rig name", UI.Field("Rig name", w.RigName, v => w.RigName = v).MinWidth(200)),
                SizeRow.Build("Stage width", w.Width, 2, 30, 0.5, v => w.Width = v),
                w.Template != RigTemplate.Floor ? SizeRow.Build("Truss height", w.Height, 2, 12, 0.5, v => w.Height = v) : null,
                Form.Row("LED wall behind the DJ", UI.Toggle("", w.LedWall, v => w.LedWall = v)),
            };
            s.Children.Add(Form.Section(null, rows));
        }
        s.Children.Add(Form.Row(UI.Text("Your fixtures on it"),
            Form.Radio([true, false], w.AutoMount, v => v ? "Auto-mount them" : "I’ll place them myself", v => w.AutoMount = v)));
        s.Children.Add(UI.Text(w.AutoMount
                ? "Heads under the trusses, lasers high at the back, bars on the floor: a sensible start you can change in the rig editor."
                : "They wait on the floor in front of the stage; drag them onto the trusses in the rig editor.", Font.Caption).Secondary().Wrap());
        return s;
    }

    /// The rig seen from the audience: the floor, the booth, trusses, towers (NewRigSheet.swift's RigSketch).
    public static class Sketch
    {
        public static FrameworkElement Build(RigTemplate template)
        {
            var canvas = new Canvas { Height = 44, HorizontalAlignment = HorizontalAlignment.Stretch };
            canvas.SizeChanged += (_, e) => Draw(canvas, template, e.NewSize.Width, e.NewSize.Height);
            return canvas;
        }

        static void Draw(Canvas c, RigTemplate template, double w, double h)
        {
            c.Children.Clear();
            if (w <= 0 || h <= 0) return;
            var line = Theme.Brush("TextFillColorSecondaryBrush");
            var truss = Tint.Brush(Tint.Accent);
            var floor = h - 6;
            void Rect(double x, double y, double width, double height, Brush fill, double corner = 1)
            {
                var r = new Rectangle { Width = Math.Max(0, width), Height = Math.Max(0, height), Fill = fill, RadiusX = corner, RadiusY = corner };
                Canvas.SetLeft(r, x);
                Canvas.SetTop(r, y);
                c.Children.Add(r);
            }
            void Bar(double x, double y, double len) => Rect(x, y, len, 4, truss);
            void Tower(double x, double top) => Rect(x, top, 4, floor - top, truss);
            Rect(4, floor, w - 8, 2, line, 0);
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
                default:  // seen a little from below: a flat ellipse, the half circle a wider arc behind it
                {
                    double cx = w / 2, cy = h * 0.2, r = w * 0.36;
                    var a0 = 195 * Math.PI / 180;
                    var a1 = 345 * Math.PI / 180;
                    var figure = new PathFigure { StartPoint = new Windows.Foundation.Point(cx + r * Math.Cos(a0), cy - r * Math.Sin(a0)) };
                    figure.Segments.Add(new ArcSegment
                    {
                        Point = new Windows.Foundation.Point(cx + r * Math.Cos(a1), cy - r * Math.Sin(a1)), Size = new Windows.Foundation.Size(r, r),
                        SweepDirection = SweepDirection.Counterclockwise,
                    });
                    var geometry = new PathGeometry();
                    geometry.Figures.Add(figure);
                    c.Children.Add(new Microsoft.UI.Xaml.Shapes.Path { Data = geometry, Stroke = truss, StrokeThickness = 3 });
                    var ring = new Ellipse { Width = w * 0.46, Height = h * 0.16, Stroke = truss, StrokeThickness = 3.5 };
                    Canvas.SetLeft(ring, w * 0.27);
                    Canvas.SetTop(ring, h * 0.2);
                    c.Children.Add(ring);
                    break;
                }
            }
        }
    }
}

/// A labelled slider with its value in metres.
public static class SizeRow
{
    public static FrameworkElement Build(string title, double value, double min, double max, double step, Action<double> changed)
    {
        static string Text(double v, double step) =>
            step < 1 ? $"{v.ToString("0.0", System.Globalization.CultureInfo.CurrentCulture)} m" : $"{(int)v} m";
        var label = UI.Text(Text(value, step)).Frame(width: 56);
        label.TextAlignment = TextAlignment.Right;
        var slider = UI.Slider(value, min, max, v => { label.Text = Text(v, step); changed(v); }, step).MinWidth(160);
        return Form.Row(title, UI.HStack(8, slider.Grow(), label).MinWidth(260));
    }
}
