// The LED wall output's geometry (mac/Tests/AmadeusKitTests/WallOutputLayoutTests.swift): the wall's rectangle on
// the monitor, the picture fitted into it, how fine it is drawn, and the settings read back with defaults.
using System.Text;

public sealed class WallOutputLayoutTests
{
    static WallOutputSettings Decode(string json) => J.Decode(Encoding.UTF8.GetBytes(json), WallOutputSettings.From)!;

    [Fact]
    public void TheWallIsTheWholeDisplayUnlessSet()
    {
        Assert.Equal(new PixelRect(0, 0, 1920, 1080), WallOutputLayout.WallRect(null, 1920, 1080));
        // a 6×3 wall of 128 px panels at the processor's start position
        Assert.Equal(new PixelRect(0, 0, 768, 384), WallOutputLayout.WallRect(new PixelRect(0, 0, 768, 384), 1920, 1080));
    }

    [Fact]
    public void AWallOffTheDisplayIsKeptOnIt()
    {
        Assert.Equal(new PixelRect(1800, 1000, 120, 80), WallOutputLayout.WallRect(new PixelRect(1800, 1000, 768, 384), 1920, 1080));
        Assert.Equal(new PixelRect(0, 1079, 1, 1), WallOutputLayout.WallRect(new PixelRect(-50, 5000, 0, 10), 1920, 1080));
    }

    [Fact]
    public void ThePictureIsFittedAndCentred()
    {
        // 16:9 fills; a 2:1 wall gets bars left and right, a tall one above and below
        Assert.Equal(new PixelRect(0, 0, 1920, 1080), WallOutputLayout.Fit(new PixelRect(0, 0, 1920, 1080)));
        Assert.Equal(new PixelRect(42, 0, 683, 384), WallOutputLayout.Fit(new PixelRect(0, 0, 768, 384)));
        Assert.Equal(new PixelRect(100, 240, 512, 288), WallOutputLayout.Fit(new PixelRect(100, 0, 512, 768)));
        // a pixel off 16:9 is filled, no hairline bars
        Assert.Equal(new PixelRect(0, 0, 1366, 768), WallOutputLayout.Fit(new PixelRect(0, 0, 1366, 768)));
    }

    [Fact]
    public void ThePictureIsDrawnAsFineAsTheWallNeeds()
    {
        Assert.Equal(1, WallOutputLayout.PictureScale(null));
        Assert.Equal(1, WallOutputLayout.PictureScale(288));
        Assert.Equal(1.5, WallOutputLayout.PictureScale(384));
        Assert.Equal(1.5, WallOutputLayout.PictureScale(540));
        Assert.Equal(2, WallOutputLayout.PictureScale(2160));
    }

    [Fact]
    public void AHiDPIModeDrawsTheRectangleInItsOwnPixels()
    {
        var r = new PixelRect(10, 20, 768, 384);
        Assert.Equal(r, WallOutputLayout.Scaled(r, (1920, 1080), (1920, 1080)));
        Assert.Equal(new PixelRect(20, 40, 1536, 768), WallOutputLayout.Scaled(r, (1920, 1080), (3840, 2160)));
    }

    [Fact]
    public void PanelsMakeTheWall()
    {
        Assert.Equal(new PixelRect(0, 0, 768, 384), WallOutputLayout.Panels(6, 3, 128));
    }

    [Fact]
    public void SettingsReadBackWithTheirDefaults()
    {
        var s = Decode("""{"on": true, "leadMs": 900, "brightness": 2}""");
        Assert.True(s.On && s.Target == WallOutputSettings.TargetKind.Display && s.Rect is null && s.PanelPx == 128 && !s.TestPattern);
        Assert.True(s.LeadMs == 200 && s.Brightness == 1);  // kept in range
        var odd = Decode("""{"target": "projector"}""");
        Assert.Equal(WallOutputSettings.TargetKind.Display, odd.Target);

        var t = new WallOutputSettings
        {
            On = true, Target = WallOutputSettings.TargetKind.Window, Display = "UUID", Rect = new PixelRect(0, 0, 768, 384), LeadMs = -40,
        };
        var d = new Defaults(null, []);
        t.Save(d);
        Assert.Equal(t, WallOutputSettings.Load(d));
        // and from the command line, as JSON text (-ledWallOutput '{"on": true}')
        Assert.True(WallOutputSettings.Load(new Defaults(null, ["-ledWallOutput", """{"on": true}"""])).On);
        Assert.Equal(new WallOutputSettings(), WallOutputSettings.Load(new Defaults(null, [])));
    }

    [Fact]
    public void TheWallsShapeComesFromItsPixels()
    {
        Assert.Null(ScreenShape.Pixels(null));
        Assert.Null(ScreenShape.Pixels(JSONValue.Of(true)));
        var px = ScreenShape.Pixels(JSONValue.Parse("""{"pixels": [768, 384]}"""));
        Assert.Equal((768, 384), px);
        Assert.Equal(2, ScreenShape.Aspect(px));
        Assert.Equal(16.0 / 9.0, ScreenShape.Aspect(null));
        Assert.Equal(6, ScreenShape.Aspect((10000, 10)));   // kept in range
        // a tall wall stays under the ceiling, its shape kept; 16:9 and wider as always
        var tall = ScreenShape.Size(5, 0.5, 1.4, 6);
        Assert.True(Math.Abs(tall.H - 4.3) < 1e-9 && Math.Abs(tall.W - 2.15) < 1e-9);
        var wide = ScreenShape.Size(8, 16.0 / 9.0, 1.4, 3);
        Assert.Equal((8.0, 4.5), wide);
    }

    [Fact]
    public void TheHelloCarriesTheWallsPixels()
    {
        var h = Assert.IsType<HelloMessage>(FeedMessage.Decode("""{"type": "hello", "screen": true, "screen_px": [1536, 384]}""")).Hello;
        Assert.Equal([1536, 384], h.ScreenPx!);
        Assert.Equal(4, h.ScreenAspect);
        var old = Assert.IsType<HelloMessage>(FeedMessage.Decode("""{"type": "hello", "screen": true}""")).Hello;
        Assert.Null(old.ScreenPx);
        Assert.Equal(16.0 / 9.0, old.ScreenAspect);
    }

    [Fact]
    public void ThePictureIsDrawnAsFineAsTheOutputUpTo4K()
    {
        Assert.Equal(1, WallOutputLayout.PictureScale(null, (640, 360)));
        Assert.Equal(3, WallOutputLayout.PictureScale(new PixelRect(0, 0, 1920, 1080), (640, 360)));
        Assert.Equal(6, WallOutputLayout.PictureScale(new PixelRect(0, 0, 3840, 2160), (640, 360)));
        Assert.Equal(1.5, WallOutputLayout.PictureScale(new PixelRect(0, 0, 768, 384), (720, 360)));
        Assert.Equal(2, WallOutputLayout.PictureScale(new PixelRect(0, 0, 2560, 640), (1440, 360)));
        // never more than 4096 pixels on the long side: an 8K output gets a 4K-ish picture
        Assert.Equal(6, WallOutputLayout.PictureScale(new PixelRect(0, 0, 7680, 4320), (640, 360)));
    }
}
