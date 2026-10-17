// How UI.VStack / UI.HStack share their room (the app's Shared/StackLayout.cs), like SwiftUI's stacks.
using AmadeusDMX;
using C = AmadeusDMX.StackLayout.Child;

namespace AmadeusKit.Tests;

public class StackLayoutTests
{
    [Fact]
    public void ChildrenGetWhatTheyWantAndSpacersTheRest()
    {
        Assert.Equal([40, 100 - 40 - 30 - 16, 30], StackLayout.Lengths([new C(40), new C(0, Grows: true), new C(30)], 8, 100));
        Assert.Equal([40, 30], StackLayout.Lengths([new C(40), new C(30)], 8, 100));  // no spacer: no growing
        // two spacers share alike; a spacer keeps its least length
        Assert.Equal([10, 40, 40], StackLayout.Lengths([new C(10), new C(0, true), new C(0, true)], 0, 90));
        Assert.Equal([100, 5], StackLayout.Lengths([new C(100), new C(5, true)], 0, 90));
    }

    [Fact]
    public void TextGivesWayWhenThereIsTooLittleRoom()
    {
        // a button (fixed) and two texts in 100: the texts shrink in proportion, the button keeps its size
        var l = StackLayout.Lengths([new C(40), new C(60, Shrinks: true), new C(20, Shrinks: true)], 0, 100);
        Assert.Equal(40, l[0]);
        Assert.Equal(45, l[1], 6);
        Assert.Equal(15, l[2], 6);
        Assert.Equal(100, l.Sum(), 6);
        // nothing can give way: as wanted (it overflows, like SwiftUI's fixed views)
        Assert.Equal([80, 80], StackLayout.Lengths([new C(80), new C(80)], 0, 100));
    }

    [Fact]
    public void WithoutALimitEveryoneGetsWhatTheyWant()
    {
        Assert.Equal([40, 7, 30], StackLayout.Lengths([new C(40), new C(7, true), new C(30)], 8, double.PositiveInfinity));
        Assert.Empty(StackLayout.Lengths([], 8, 100));
        Assert.Equal(25, StackLayout.Offset(100, 50, 0.5));
        Assert.Equal(0, StackLayout.Offset(10, 50, 1));
    }
}
