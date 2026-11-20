// The calibration's picture: a moving head as the software expects it, and where its beam goes, drawn twice, as you
// see it from the audience and from above. The real head is then turned (its calibration, a press at a time) until
// it does the same. Both are drawn as the audience sees the stage: stage left (x = 0) on the right
// (mac/Sources/AmadeusDMX/Sets/BeamPicture.swift).
using System.Numerics;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace AmadeusDMX;

/// `Pos`: metres, x from stage left, y towards the audience from the stage's front edge, z up; `Stage`: width, height;
/// `Hanging`: its base above it (under a truss), or below (standing).
public sealed record Beam(Vector3 Pos, Vector3 Dir, Vector2 Stage, bool Hanging = true);

public static class BeamPicture
{
    const double W = 270, H = 170;

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
        const double pad = 22;
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

        Head(c, Pt(ax, ay), above ? null : (0, beam.Hanging ? -1 : 1), dx, dy, above ? 0 : d.Y, reach * s);
    }

    /// The moving head hanging under a truss or standing on the floor: the calibration's first question.
    public static FrameworkElement Icon(bool hanging)
    {
        const double w = 120, h = 84;
        var c = new Canvas { Width = w, Height = h, IsHitTestVisible = false };
        var rail = hanging ? 12.0 : h - 8;
        c.Children.Add(new Line
        {
            X1 = 6, Y1 = rail, X2 = w - 6, Y2 = rail, Stroke = Theme.Brush("TextFillColorSecondaryBrush"), StrokeThickness = hanging ? 5 : 2,
            StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round,
        });
        Head(c, new Point(w / 2, hanging ? rail + 8 : rail - 6), (0, hanging ? -1 : 1), 0.62, hanging ? 0.62 : -0.62, 0, 34);
        return c;
    }

    /// A moving head: its base (at `mount`, the yoke hanging from it or standing on it along -`up`; null: seen from
    /// above, the base under the head), the head turned to the aim (the beam's direction as this view sees it: shorter
    /// the more it points at or away from you, `towards` > 0 at you), and `beam` points of beam from its lens.
    static void Head(Canvas c, Point mount, (double X, double Y)? up, double aimX, double aimY, double towards, double beam)
    {
        var body = Tint.Brush(Windows.UI.Color.FromArgb(255, 209, 209, 209));
        var dark = Tint.Brush(Windows.UI.Color.FromArgb(255, 64, 64, 64));
        // a rounded box in its own coordinates, turned and moved by (a, b, c, d, tx, ty) as CGAffineTransform's
        void Box(double x, double y, double w, double h, double radius, Brush fill, double a, double b, double cc, double d, double tx, double ty) =>
            c.Children.Add(new Rectangle
            {
                Width = w, Height = h, RadiusX = radius, RadiusY = radius, Fill = fill,
                RenderTransform = new MatrixTransform { Matrix = new Matrix(a, b, cc, d, a * x + cc * y + tx, b * x + d * y + ty) },
            });
        void Disc(Point at, double r, Brush? fill, Brush? stroke = null, double thickness = 0)
        {
            var e = new Ellipse { Width = 2 * r, Height = 2 * r, Fill = fill, Stroke = stroke, StrokeThickness = thickness };
            Canvas.SetLeft(e, at.X - r);
            Canvas.SetTop(e, at.Y - r);
            c.Children.Add(e);
        }
        var pivot = mount;
        if (up is { } u)
        {
            // the base, and the yoke's two arms from it to the head's pivot
            double bx = -u.Y, by = u.X;   // across the base
            pivot = new Point(mount.X - u.X * 24, mount.Y - u.Y * 24);
            Box(-17, -5, 34, 10, 3, body, bx, by, u.X, u.Y, mount.X, mount.Y);
            foreach (var o in new[] { -14.0, 14.0 })
                c.Children.Add(new Line
                {
                    X1 = mount.X + bx * o, Y1 = mount.Y + by * o, X2 = pivot.X + bx * o, Y2 = pivot.Y + by * o, Stroke = body, StrokeThickness = 4,
                    StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round,
                });
        }
        else
        {
            var plate = new Rectangle { Width = 30, Height = 30, RadiusX = 5, RadiusY = 5, Stroke = body, StrokeThickness = 2 };
            Canvas.SetLeft(plate, mount.X - 15);
            Canvas.SetTop(plate, mount.Y - 15);
            c.Children.Add(plate);
        }
        var flat = Math.Sqrt(aimX * aimX + aimY * aimY);
        if (flat > 0.35)   // the head from its side: a barrel, its lens at the front
        {
            double ux = aimX / flat, uy = aimY / flat, length = 16 + 12 * flat;   // shorter when it points partly at you
            var lens = new Point(pivot.X + ux * (length - 10), pivot.Y + uy * (length - 10));
            if (beam > 0)
            {
                double len = beam * flat, half = 4 + len * 0.12;
                var end = new Point(lens.X + ux * len, lens.Y + uy * len);
                var cone = new Polygon { Fill = Tint.Brush(Tint.Yellow, 0.45) };
                cone.Points.Add(new Point(lens.X - uy * 5, lens.Y + ux * 5));
                cone.Points.Add(new Point(end.X - uy * half, end.Y + ux * half));
                cone.Points.Add(new Point(end.X + uy * half, end.Y - ux * half));
                cone.Points.Add(new Point(lens.X + uy * 5, lens.Y - ux * 5));
                c.Children.Add(cone);
            }
            Box(-10, -9, length, 18, 5, body, ux, uy, -uy, ux, pivot.X, pivot.Y);
            Box(length - 13, -7, 3, 14, 0, Tint.Brush(Tint.Yellow), ux, uy, -uy, ux, pivot.X, pivot.Y);
            Disc(pivot, 2.5, dark);
        }
        else               // end-on: its round front (the lens lit, at you) or its back
        {
            if (towards > 0 && beam > 0) Disc(pivot, 24, Tint.Brush(Tint.Yellow, 0.3));
            Disc(pivot, 11, body);
            if (towards > 0) Disc(pivot, 7, Tint.Brush(Tint.Yellow)); else Disc(pivot, 5, null, dark, 1.5);
        }
    }
}
