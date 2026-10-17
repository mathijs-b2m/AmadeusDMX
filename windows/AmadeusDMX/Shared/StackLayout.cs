// How a stack shares its room among its children, like SwiftUI's HStack / VStack: children take what they need
// along the stack, spacers (and children marked to grow) share what is left, and when there isn't enough, the
// ones that can give way (text: it truncates or wraps) give it back first. Pure arithmetic, so it is tested on any
// computer (AmadeusKit.Tests compiles this file).
namespace AmadeusDMX;

public static class StackLayout
{
    /// One child along the stack: the length it wants, whether it grows into free room, whether it can give way.
    public readonly record struct Child(double Wanted, bool Grows = false, bool Shrinks = false);

    /// The length each child gets. `room`: the stack's length (infinity: as long as its children want).
    public static double[] Lengths(IReadOnlyList<Child> children, double spacing, double room)
    {
        var n = children.Count;
        var out_ = new double[n];
        if (n == 0) return out_;
        var gaps = spacing * (n - 1);
        double fixedTotal = 0;
        var growers = 0;
        for (var i = 0; i < n; i++)
        {
            if (children[i].Grows) growers++;
            else fixedTotal += children[i].Wanted;
        }
        if (double.IsInfinity(room))
        {
            for (var i = 0; i < n; i++) out_[i] = children[i].Wanted;
            return out_;
        }
        var over = fixedTotal + gaps - room;
        if (over > 0)  // too little room: those that can give way do, in proportion to their length
        {
            double shrinkable = 0;
            for (var i = 0; i < n; i++) if (!children[i].Grows && children[i].Shrinks) shrinkable += children[i].Wanted;
            var k = shrinkable > 0 ? Math.Max(0, 1 - over / shrinkable) : 1;
            fixedTotal = 0;
            for (var i = 0; i < n; i++)
            {
                if (children[i].Grows) continue;
                out_[i] = children[i].Shrinks ? children[i].Wanted * k : children[i].Wanted;
                fixedTotal += out_[i];
            }
        }
        else
            for (var i = 0; i < n; i++) if (!children[i].Grows) out_[i] = children[i].Wanted;
        if (growers > 0)
        {
            var share = Math.Max(0, room - fixedTotal - gaps) / growers;
            for (var i = 0; i < n; i++) if (children[i].Grows) out_[i] = Math.Max(share, children[i].Wanted);
        }
        return out_;
    }

    /// Where a child of length `size` starts across the stack: leading (0), centre (0.5) or trailing (1).
    public static double Offset(double room, double size, double alignment) => Math.Max(0, room - size) * alignment;
}
