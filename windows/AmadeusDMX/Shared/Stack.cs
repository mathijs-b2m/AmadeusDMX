// The panel behind UI.VStack / UI.HStack: SwiftUI's stacks for WinUI. Children are laid out one after the other
// with `Spacing` between them; UI.Spacer() and children marked `.Grow()` share the free room; text gives way when
// there isn't enough (it truncates or wraps). Across the stack each child keeps its own alignment, as in a
// StackPanel, except that in an HStack a child that would stretch is centred (SwiftUI's default) unless it is
// marked `.Fill()`; `Alignment` puts every child at the leading edge (0), the centre (0.5) or the trailing edge (1).
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;

namespace AmadeusDMX;

public sealed partial class Stack : Panel
{
    public Orientation Axis { get; }
    double _spacing;
    Thickness _padding;
    double? _alignment;

    public double Spacing { get => _spacing; set { _spacing = value; InvalidateMeasure(); } }
    public Thickness Padding { get => _padding; set { _padding = value; InvalidateMeasure(); } }
    /// Across the stack, for every child: 0 leading, 0.5 centre, 1 trailing (nil: each child's own alignment).
    public double? Alignment { get => _alignment; set { _alignment = value; InvalidateArrange(); } }

    public Stack(Orientation axis, double spacing)
    {
        Axis = axis;
        _spacing = spacing;
    }

    // MARK: what a child says about itself

    public static readonly DependencyProperty GrowProperty =
        DependencyProperty.RegisterAttached("Grow", typeof(bool), typeof(Stack), new PropertyMetadata(false, Relayout));

    public static readonly DependencyProperty FillProperty =
        DependencyProperty.RegisterAttached("Fill", typeof(bool), typeof(Stack), new PropertyMetadata(false, Relayout));

    /// A spacer's least length (it grows from there).
    public static readonly DependencyProperty SpacerProperty =
        DependencyProperty.RegisterAttached("Spacer", typeof(double), typeof(Stack), new PropertyMetadata(-1.0, Relayout));

    static void Relayout(DependencyObject d, DependencyPropertyChangedEventArgs e) =>
        (VisualTreeHelper.GetParent(d) as UIElement)?.InvalidateMeasure();

    public static bool GetGrow(UIElement e) => (bool)e.GetValue(GrowProperty) || IsSpacer(e);
    public static void SetGrow(UIElement e, bool v) => e.SetValue(GrowProperty, v);
    public static bool GetFill(UIElement e) => (bool)e.GetValue(FillProperty);
    public static void SetFill(UIElement e, bool v) => e.SetValue(FillProperty, v);
    static bool IsSpacer(UIElement e) => (double)e.GetValue(SpacerProperty) >= 0;
    static double SpacerMin(UIElement e) => Math.Max(0, (double)e.GetValue(SpacerProperty));
    static bool Shrinks(UIElement e) => e is TextBlock or RichTextBlock;

    // MARK: layout

    bool Horizontal => Axis == Orientation.Horizontal;
    double Main(Size s) => Horizontal ? s.Width : s.Height;
    double Cross(Size s) => Horizontal ? s.Height : s.Width;
    Size Make(double main, double cross) => Horizontal ? new Size(main, cross) : new Size(cross, main);

    List<UIElement> Visible() => Children.Where(c => c.Visibility == Visibility.Visible).ToList();

    StackLayout.Child[] _wanted = [];

    protected override Size MeasureOverride(Size available)
    {
        var p = Padding;
        var inner = new Size(Math.Max(0, available.Width - p.Left - p.Right), Math.Max(0, available.Height - p.Top - p.Bottom));
        var room = Main(inner);
        var crossRoom = Cross(inner);
        var kids = Visible();
        var wanted = new StackLayout.Child[kids.Count];
        for (var i = 0; i < kids.Count; i++)
        {
            var k = kids[i];
            if (IsSpacer(k)) { k.Measure(Make(0, 0)); wanted[i] = new(SpacerMin(k), Grows: true); continue; }
            var grows = GetGrow(k);
            if (grows && !double.IsInfinity(room)) { wanted[i] = new(0, Grows: true); continue; }  // measured with its share below
            k.Measure(Make(double.PositiveInfinity, crossRoom));
            wanted[i] = new(Main(k.DesiredSize), grows, Shrinks(k));
        }
        _wanted = wanted;
        var lengths = StackLayout.Lengths(wanted, Spacing, room);
        double main = 0, cross = 0;
        for (var i = 0; i < kids.Count; i++)
        {
            var k = kids[i];
            if (!IsSpacer(k) && (wanted[i].Grows || lengths[i] < wanted[i].Wanted)) k.Measure(Make(lengths[i], crossRoom));
            main += lengths[i];
            cross = Math.Max(cross, Cross(k.DesiredSize));
        }
        main += Spacing * Math.Max(0, kids.Count - 1);
        if (!double.IsInfinity(room) && wanted.Any(w => w.Grows)) main = Math.Max(main, room);
        var size = Make(main, cross);
        return new Size(size.Width + p.Left + p.Right, size.Height + p.Top + p.Bottom);
    }

    protected override Size ArrangeOverride(Size final)
    {
        var p = Padding;
        var inner = new Size(Math.Max(0, final.Width - p.Left - p.Right), Math.Max(0, final.Height - p.Top - p.Bottom));
        var kids = Visible();
        if (_wanted.Length != kids.Count) return final;  // changed since the measure: a new one is on its way
        var lengths = StackLayout.Lengths(_wanted, Spacing, Main(inner));
        var crossRoom = Cross(inner);
        double at = 0;
        for (var i = 0; i < kids.Count; i++)
        {
            var k = kids[i];
            var size = Cross(k.DesiredSize);
            double offset = 0, length = crossRoom;
            var own = k is FrameworkElement fe ? (Horizontal ? Align(fe.VerticalAlignment) : Align(fe.HorizontalAlignment)) : null;
            var align = Alignment ?? (GetFill(k) ? null : own ?? (Horizontal ? 0.5 : null));
            if (align is { } a && !GetFill(k))
            {
                length = Math.Min(size, crossRoom);
                offset = StackLayout.Offset(crossRoom, length, a);
            }
            var rect = Horizontal
                ? new Rect(p.Left + at, p.Top + offset, lengths[i], length)
                : new Rect(p.Left + offset, p.Top + at, length, lengths[i]);
            k.Arrange(rect);
            at += lengths[i] + Spacing;
        }
        return final;
    }

    /// A child's own alignment across the stack: nil when it stretches (it fills the slot).
    static double? Align(HorizontalAlignment a) => a switch
    {
        HorizontalAlignment.Left => 0, HorizontalAlignment.Center => 0.5, HorizontalAlignment.Right => 1, _ => null,
    };

    static double? Align(VerticalAlignment a) => a switch
    {
        VerticalAlignment.Top => 0, VerticalAlignment.Center => 0.5, VerticalAlignment.Bottom => 1, _ => null,
    };
}
