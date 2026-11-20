// The calibration's picture: where the software expects a head's beam to go, drawn twice, as you see it from the
// audience and from above. The real head is then turned (its calibration, a press at a time) until it does the same.
// Both are drawn as the audience sees the stage: stage left (x = 0) on the right
// (mac/Sources/AmadeusDMX/Sets/BeamPicture.swift).
using System.Numerics;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace AmadeusDMX;

/// `Pos`: metres, x from stage left, y towards the audience from the stage's front edge, z up; `Stage`: width, height.
public sealed record Beam(Vector3 Pos, Vector3 Dir, Vector2 Stage);

public static class BeamPicture
{
    const double W = 250, H = 140;

    public static FrameworkElement Build(Beam beam)
    {
        var row = UI.HStack(12, Panel(beam, L("From where you stand"), false), Panel(beam, L("From above"), true));
        row.HorizontalAlignment = HorizontalAlignment.Left;
        return row;
    }

    static FrameworkElement Panel(Beam beam, string title, bool above)
    {
        var canvas = new Canvas { Width = W, Height = H, IsHitTestVisible = false };
        canvas.Clip = new RectangleGeometry { Rect = new Rect(0, 0, W, H) };
        Draw(canvas, beam, above);
        var box = new Border { Child = canvas, CornerRadius = new CornerRadius(8), Background = ShowUI.Quaternary, Width = W, Height = H };
        var stack = UI.VStack(4, box, UI.Text(title, Font.Caption).Secondary());
        stack.Alignment = 0;
        return stack;
    }

    static void Draw(Canvas c, Beam beam, bool above)
    {
        double w = Math.Max(beam.Stage.X, 1), reach = Math.Max(1.5, beam.Stage.X * 0.4);
        Vector3 p = beam.Pos, d = beam.Dir;
        // the world box in the picture's own metres: h from the left (stage right's edge), v down
        double top, height, ax, ay, dx, dy;
        if (above)
        {
            double back = Math.Min(p.Y, -2) - 0.8, front = Math.Max(p.Y, 0) + reach + 0.3;
            top = back; height = front - back;
            ax = w - p.X; ay = p.Y - back;
            dx = -d.X; dy = d.Y;
        }
        else
        {
            var h = Math.Max(Math.Max(beam.Stage.Y, p.Z + 0.5), 2);
            top = 0; height = h;
            ax = w - p.X; ay = h - p.Z;
            dx = -d.X; dy = -d.Z;
        }
        const double pad = 16;
        var s = Math.Min((W - 2 * pad) / w, (H - 2 * pad) / height);
        double ox = (W - w * s) / 2, oy = (H - height * s) / 2;
        Point Pt(double h, double v) => new(ox + h * s, oy + v * s);

        var secondary = Theme.Brush("TextFillColorSecondaryBrush");
        void Stroke(Point a, Point b, Brush brush, double thickness) =>
            c.Children.Add(new Line { X1 = a.X, Y1 = a.Y, X2 = b.X, Y2 = b.Y, Stroke = brush, StrokeThickness = thickness });
        void Word(string text, double left, double width, TextAlignment align, double y, bool bold = false)
        {
            var t = UI.Text(text, Font.Caption2).Secondary();
            t.Width = width;
            t.TextAlignment = align;
            if (bold) t.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
            Canvas.SetLeft(t, left);
            Canvas.SetTop(t, y);
            c.Children.Add(t);
        }
        if (above)   // the stage's floor, its front edge heavy; the audience below it
        {
            var edge = -top;
            var floor = new Rectangle { Width = w * s, Height = edge * s, Fill = Tint.Brush(Tint.Gray, 0.15) };
            Canvas.SetLeft(floor, ox);
            Canvas.SetTop(floor, oy);
            c.Children.Add(floor);
            Stroke(Pt(0, edge), Pt(w, edge), secondary, 2);
            Word(L("Audience"), 0, W, TextAlignment.Center, H - 16);
            Word(L("Stage"), 0, W, TextAlignment.Center, 1);
        }
        else         // the floor heavy, the room's height light
        {
            var room = new Rectangle { Width = w * s, Height = height * s, Stroke = Tint.Brush(Tint.Gray, 0.35), StrokeThickness = 1 };
            Canvas.SetLeft(room, ox);
            Canvas.SetTop(room, oy);
            c.Children.Add(room);
            Stroke(Pt(0, height), Pt(w, height), secondary, 2);
        }
        Word("SR", 4, 40, TextAlignment.Left, H - 16, bold: true);
        Word("SL", W - 44, 40, TextAlignment.Right, H - 16, bold: true);

        // the beam: a cone from the head, widening; seen end-on it is short, and a glow says it comes at you
        var a = Pt(ax, ay);
        var flat = Math.Sqrt(dx * dx + dy * dy);
        if (flat > 0.05)
        {
            double len = reach * s * flat, ux = dx / flat, uy = dy / flat;
            var b = new Point(a.X + ux * len, a.Y + uy * len);
            var half = 3 + len * 0.12;
            var cone = new Polygon { Fill = Tint.Brush(Tint.Yellow, 0.45) };
            cone.Points.Add(a);
            cone.Points.Add(new Point(b.X - uy * half, b.Y + ux * half));
            cone.Points.Add(new Point(b.X + uy * half, b.Y - ux * half));
            c.Children.Add(cone);
            Stroke(a, b, Tint.Brush(Tint.Yellow), 1.5);
        }
        void Dot(double r, Brush fill)
        {
            var e = new Ellipse { Width = 2 * r, Height = 2 * r, Fill = fill };
            Canvas.SetLeft(e, a.X - r);
            Canvas.SetTop(e, a.Y - r);
            c.Children.Add(e);
        }
        if (!above && d.Y > 0.3) Dot(6 + 12 * d.Y, Tint.Brush(Tint.Yellow, 0.3));   // towards you
        Dot(4, Theme.Brush("TextFillColorPrimaryBrush"));
    }
}
