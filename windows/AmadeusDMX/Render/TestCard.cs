// The LED wall's test card (LED Wall Output › Test Card; mac/Sources/AmadeusDMX/Render/TestCard.swift), to line the
// output up with the LED processor: the panel grid from the wall's top left with each panel's column and row, a
// one-pixel white edge with a coloured corner at each end (top left red, top right green, bottom left blue, bottom
// right yellow: a mirrored or turned map shows at once), diagonals and a circle (a stretched picture makes it an
// oval), colour bars and a grey ramp. The output's shader adds a bar that crosses every two seconds: it tears or
// stutters when frames are dropped. Drawn with SkiaSharp (Core Graphics on the Mac), y down from the top left.
using SkiaSharp;

namespace AmadeusDMX;

public static class TestCard
{
    /// The card at `pixels` (the wall's rectangle in what is drawn), labelled with `wall` (its rectangle in the
    /// monitor's own pixels, what the processor is told): BGRA, premultiplied. The caller disposes it.
    public static SKBitmap Draw((int W, int H) pixels, PixelRect wall, int panelPx)
    {
        int W = Math.Max(1, pixels.W), H = Math.Max(1, pixels.H);
        var bitmap = new SKBitmap(new SKImageInfo(W, H, SKColorType.Bgra8888, SKAlphaType.Premul));
        using var g = new SKCanvas(bitmap);
        var k = (float)W / Math.Max(1, wall.W);   // drawn pixels per monitor pixel (1 unless the window is another size)
        float w = W, h = H, px = 1 * k;
        g.Clear(SKColors.Black);
        using var fill = new SKPaint { Style = SKPaintStyle.Fill, IsAntialias = false };
        using var stroke = new SKPaint { Style = SKPaintStyle.Stroke, IsAntialias = true };
        static SKColor Rgb(float r, float gr, float b) => new((byte)MathF.Round(r * 255), (byte)MathF.Round(gr * 255), (byte)MathF.Round(b * 255));
        static SKColor Gray(float v) => Rgb(v, v, v);

        // colour bars across the middle, a grey ramp under them
        (float, float, float)[] bars = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 1), (0, 0, 0)];
        float by = h * 0.36f, bh = h * 0.2f, bw = w / bars.Length;
        for (var i = 0; i < bars.Length; i++)
        {
            fill.Color = Rgb(bars[i].Item1 * 0.85f, bars[i].Item2 * 0.85f, bars[i].Item3 * 0.85f);
            g.DrawRect(SKRect.Create(i * bw, by, bw + 1, bh), fill);
        }
        const int steps = 16;
        for (var i = 0; i < steps; i++)
        {
            fill.Color = Gray((float)i / (steps - 1));
            g.DrawRect(SKRect.Create(w * i / steps, by + bh, w / steps + 1, h * 0.08f), fill);
        }

        // the panels: a grid from the top left, each with its column and row
        var p = Math.Max(1, panelPx) * k;
        stroke.Color = Gray(0.45f);
        stroke.StrokeWidth = px;
        stroke.IsAntialias = false;
        for (var x = p; x < w - 0.5f; x += p) g.DrawLine(x + px / 2, -px, x + px / 2, h + px, stroke);
        for (var y = p; y < h - 0.5f; y += p) g.DrawLine(-px, y + px / 2, w + px, y + px / 2, stroke);
        stroke.IsAntialias = true;
        if (p >= 40)
        {
            var size = MathF.Min(p * 0.16f, 28 * k);
            for (var c = 0; c < (int)MathF.Ceiling(w / p); c++)
                for (var r = 0; r < (int)MathF.Ceiling(h / p); r++)
                    Text(g, $"{c + 1},{r + 1}", new SKPoint(c * p + 4 * k, r * p + 4 * k), size, 0.6f, centred: false);
        }

        // diagonals and a circle: lines meet in the middle, the circle stays round on the wall
        stroke.Color = Gray(0.7f);
        stroke.StrokeWidth = px;
        g.DrawLine(0, 0, w, h, stroke);
        g.DrawLine(w, 0, 0, h, stroke);
        var d = MathF.Min(w, h) * 0.8f;
        stroke.StrokeWidth = 2 * px;
        stroke.Color = SKColors.White;
        g.DrawOval(SKRect.Create((w - d) / 2, (h - d) / 2, d, d), stroke);

        // the edge, one pixel, and the corners
        stroke.StrokeWidth = px;
        stroke.IsAntialias = false;
        g.DrawRect(SKRect.Create(px / 2, px / 2, w - px, h - px), stroke);
        float arm = MathF.Min(w, h) * 0.12f, thick = MathF.Max(3 * k, MathF.Min(w, h) * 0.015f);
        (SKPoint O, float Sx, float Sy, SKColor C)[] corners =
        [
            (new(0, 0), 1, 1, Rgb(1, 0, 0)), (new(w, 0), -1, 1, Rgb(0, 1, 0)),
            (new(0, h), 1, -1, Rgb(0, 0.4f, 1)), (new(w, h), -1, -1, Rgb(1, 0.9f, 0)),
        ];
        foreach (var (o, sx, sy, c) in corners)
        {
            fill.Color = c;
            g.DrawRect(SKRect.Create(o.X, o.Y, arm * sx, thick * sy).Standardized, fill);
            g.DrawRect(SKRect.Create(o.X, o.Y, thick * sx, arm * sy).Standardized, fill);
        }

        // what the processor should be told
        var label = $"LED wall {wall.W} × {wall.H} px at {wall.X}, {wall.Y}";
        var sub = $"panels {panelPx} px · {(int)Math.Ceiling((double)wall.W / Math.Max(1, panelPx))} × {(int)Math.Ceiling((double)wall.H / Math.Max(1, panelPx))}";
        var ts = MathF.Max(10 * k, MathF.Min(h * 0.07f, w * 0.04f));
        fill.Color = new SKColor(0, 0, 0, 191);
        g.DrawRect(SKRect.Create(w * 0.15f, h * 0.12f, w * 0.7f, ts * 2.6f), fill);
        Text(g, label, new SKPoint(w / 2, h * 0.12f + ts * 0.85f), ts, 1, centred: true);
        Text(g, sub, new SKPoint(w / 2, h * 0.12f + ts * 1.95f), ts * 0.6f, 0.8f, centred: true);
        return bitmap;
    }

    static void Text(SKCanvas g, string s, SKPoint p, float size, float gray, bool centred)
    {
        using var font = new SKFont(WallRenderer.Typeface(mono: true), size);   // the Mac's Menlo-Bold
        using var paint = new SKPaint { IsAntialias = true, Color = new SKColor((byte)MathF.Round(gray * 255), (byte)MathF.Round(gray * 255), (byte)MathF.Round(gray * 255)) };
        font.MeasureText(s, out var b);
        // centred: on the point; else hanging from it (the top left of a panel)
        var at = centred ? new SKPoint(p.X - b.MidX, p.Y - b.MidY) : new SKPoint(p.X - b.Left, p.Y - b.Top);
        g.DrawText(s, at.X, at.Y, SKTextAlign.Left, font, paint);
    }
}
