// Children in a row that continues on the next line when the row is full (SwiftUI has no such stack; on the Mac
// the rows that use it fit in one line, but Windows' Segoe UI is wider than the Mac's font at the same size).
using Windows.Foundation;

namespace AmadeusDMX;

public sealed partial class FlowPanel : Panel
{
    public double Spacing { get; set; } = 6;
    public double LineSpacing { get; set; } = 4;

    protected override Size MeasureOverride(Size available)
    {
        double x = 0, y = 0, line = 0, widest = 0;
        foreach (var c in Children)
        {
            c.Measure(new Size(available.Width, double.PositiveInfinity));
            var s = c.DesiredSize;
            if (s.Width == 0 && s.Height == 0) continue;  // collapsed
            if (x > 0 && x + s.Width > available.Width) { y += line + LineSpacing; x = 0; line = 0; }
            x += s.Width + Spacing;
            line = Math.Max(line, s.Height);
            widest = Math.Max(widest, x - Spacing);
        }
        return new Size(double.IsInfinity(available.Width) ? widest : Math.Min(widest, available.Width), y + line);
    }

    protected override Size ArrangeOverride(Size final)
    {
        double x = 0, y = 0, line = 0;
        foreach (var c in Children)
        {
            var s = c.DesiredSize;
            if (s.Width == 0 && s.Height == 0) { c.Arrange(new Rect(0, 0, 0, 0)); continue; }
            if (x > 0 && x + s.Width > final.Width) { y += line + LineSpacing; x = 0; line = 0; }
            c.Arrange(new Rect(x, y, s.Width, s.Height));
            x += s.Width + Spacing;
            line = Math.Max(line, s.Height);
        }
        return final;
    }
}

public static partial class UI
{
    /// A row that wraps onto more lines when it doesn't fit (chips, tags).
    public static FlowPanel Flow(double spacing, params UIElement?[] children)
    {
        var p = new FlowPanel { Spacing = spacing };
        foreach (var c in children) if (c is not null) p.Children.Add(c);
        return p;
    }
}
