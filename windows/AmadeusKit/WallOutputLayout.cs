// The LED wall output (the app's LED Wall Output window): where the wall's picture goes on this computer, and the
// geometry of putting it there (mac/Sources/AmadeusKit/WallOutputLayout.swift). An LED processor (NovaStar and the
// like) takes one video signal, say 1920×1080 over HDMI, and reads the wall's own pixels from a rectangle of it, one
// to one. So the output draws the picture into exactly that rectangle of the monitor, black around it, and never
// scales the monitor itself.
//
// These settings belong to the computer (which monitor is the HDMI out), not to a set or a rig: they live in the
// app's defaults (settings.json, key "ledWallOutput"). The picture is 16:9 (WallRenderer); a wall of another shape
// shows it fitted, black bars aside.
using System.Text;
using System.Text.Json;

namespace AmadeusKit;

/// A rectangle in pixels, from the top left.
public readonly record struct PixelRect(int X, int Y, int W, int H);

public sealed record WallOutputSettings
{
    public enum TargetKind
    {
        Display,   // full screen on a monitor (the HDMI into the LED processor)
        Window,    // in a window on this screen: try it without a second monitor, or for a capture (OBS)
    }

    public bool On { get; init; }
    public TargetKind Target { get; init; } = TargetKind.Display;
    /// The monitor, by its device path (stays the same across restarts and plugging in again on the same port).
    public string? Display { get; init; }
    /// Its name, for the window while it is not connected.
    public string? DisplayName { get; init; }
    /// The wall in the monitor's pixels; nil: the whole monitor.
    public PixelRect? Rect { get; init; }
    /// A ceiling on the wall's brightness, 0..1 (LED walls are bright: a dark club wants far less than daylight).
    public double Brightness { get; init; } = 1;
    /// Milliseconds the picture runs ahead of the lights: an LED processor holds a frame or two (positive values
    /// win that back), a slow DMX node the other way.
    public double LeadMs { get; init; }
    /// A test card instead of the show: the rectangle's edges, the panel grid, colour bars, a moving bar.
    public bool TestPattern { get; init; }
    /// One LED panel's size in pixels (the test card's grid).
    public int PanelPx { get; init; } = 128;

    public const string DefaultsKey = "ledWallOutput";
    public static readonly (double Lower, double Upper) LeadRange = (-200, 200);
    public static readonly (int Lower, int Upper) PanelRange = (16, 1024);

    static string Raw(TargetKind t) => t == TargetKind.Window ? "window" : "display";

    // missing keys keep their defaults (older or hand-written settings); values out of range are kept in it
    public static WallOutputSettings From(JsonElement c) => new()
    {
        On = J.Val(c, "on", J.Bool) ?? false,
        Target = J.Try(() => J.Ref(c, "target", J.String)) == "window" ? TargetKind.Window : TargetKind.Display,
        Display = J.Ref(c, "display", J.String),
        DisplayName = J.Ref(c, "displayName", J.String),
        Rect = J.Val(c, "rect", r => new PixelRect(J.Req(r, "x", J.Int), J.Req(r, "y", J.Int), J.Req(r, "w", J.Int), J.Req(r, "h", J.Int))),
        Brightness = Math.Min(1, Math.Max(0, J.Val(c, "brightness", J.Double) ?? 1)),
        LeadMs = Math.Min(LeadRange.Upper, Math.Max(LeadRange.Lower, J.Val(c, "leadMs", J.Double) ?? 0)),
        TestPattern = J.Val(c, "testPattern", J.Bool) ?? false,
        PanelPx = Math.Min(PanelRange.Upper, Math.Max(PanelRange.Lower, J.Val(c, "panelPx", J.Int) ?? 128)),
    };

    public JSONValue ToJSONValue()
    {
        var o = new Dictionary<string, JSONValue>
        {
            ["on"] = On, ["target"] = Raw(Target), ["brightness"] = Brightness, ["leadMs"] = LeadMs,
            ["testPattern"] = TestPattern, ["panelPx"] = PanelPx,
        };
        if (Display is { } d) o["display"] = d;
        if (DisplayName is { } n) o["displayName"] = n;
        if (Rect is { } r) o["rect"] = JSONValue.Of(new Dictionary<string, JSONValue> { ["x"] = r.X, ["y"] = r.Y, ["w"] = r.W, ["h"] = r.H });
        return JSONValue.Of(o);
    }

    public static WallOutputSettings Load(Defaults? defaults = null)
    {
        var v = (defaults ?? Defaults.Standard).Object(DefaultsKey);
        // an object in settings.json, or (the command line) its JSON as text
        var bytes = v?.String is { } text ? Encoding.UTF8.GetBytes(text) : v?.Object is not null ? v.ToJson() : null;
        return bytes is null ? new WallOutputSettings() : J.Decode(bytes, From) ?? new WallOutputSettings();
    }

    public void Save(Defaults? defaults = null) => (defaults ?? Defaults.Standard).Set(DefaultsKey, ToJSONValue());
}

public static class WallOutputLayout
{
    /// The wall's picture: 16:9.
    public const double Aspect = 16.0 / 9.0;

    /// The wall on a monitor of `width`×`height` pixels: the setting, kept on the monitor (at least 1×1), or the
    /// whole monitor.
    public static PixelRect WallRect(PixelRect? r, int width, int height)
    {
        int w = Math.Max(1, width), h = Math.Max(1, height);
        if (r is not { } p) return new PixelRect(0, 0, w, h);
        int x = Math.Min(Math.Max(0, p.X), w - 1), y = Math.Min(Math.Max(0, p.Y), h - 1);
        return new PixelRect(x, y, Math.Min(Math.Max(1, p.W), w - x), Math.Min(Math.Max(1, p.H), h - y));
    }

    /// Where a picture of `aspect` goes inside the wall: as big as fits, centred, in whole pixels. A wall a pixel
    /// off 16:9 is filled (no hairline bars).
    public static PixelRect Fit(PixelRect wall, double aspect = Aspect)
    {
        var wa = (double)wall.W / Math.Max(1, wall.H);
        int w = wall.W, h = wall.H;
        if (wa > aspect) w = (int)Math.Round(wall.H * aspect, MidpointRounding.AwayFromZero);
        else h = (int)Math.Round(wall.W / aspect, MidpointRounding.AwayFromZero);
        if (wall.W - w <= 2) w = wall.W;
        if (wall.H - h <= 2) h = wall.H;
        return new PixelRect(wall.X + (wall.W - w) / 2, wall.Y + (wall.H - h) / 2, Math.Max(1, w), Math.Max(1, h));
    }

    /// How much finer than 640×360 the picture is drawn: 1 for the 3D stage alone, up to 2 (1280×720) for a big
    /// wall. The figures are lines, sharp at any size; the CPU draws them, so not finer than the wall needs.
    public static double PictureScale(int? wallHeight)
    {
        if (wallHeight is not > 0) return 1;
        return Math.Min(2, Math.Max(1, Math.Ceiling(wallHeight.Value / 360.0 * 2) / 2));
    }

    /// How much finer than its canvas (WallRenderer's units: 640×360 for 16:9) the picture is drawn to fill a wall
    /// `picture` big: 1, 1.5 or 2, and never more than about 1.6 million pixels for the CPU to draw.
    public static double PictureScale(PixelRect? picture, (double W, double H) canvas)
    {
        if (picture is not { W: > 0, H: > 0 } p || canvas.W <= 0 || canvas.H <= 0) return 1;
        var s = Math.Min(2, Math.Max(1, Math.Ceiling(Math.Max(p.W / canvas.W, p.H / canvas.H) * 2) / 2));
        while (s > 1 && canvas.W * canvas.H * s * s > 1.6e6) s -= 0.5;
        return s;
    }

    /// A rectangle in the monitor's own pixels, in the pixels of what is drawn (on the Mac a HiDPI mode draws more
    /// pixels than it sends; on Windows the output's swap chain is in the monitor's pixels, so this is one to one
    /// unless the window is not the monitor's size).
    public static PixelRect Scaled(PixelRect r, (int W, int H) mode, (int W, int H) drawable)
    {
        double kx = (double)drawable.W / Math.Max(1, mode.W), ky = (double)drawable.H / Math.Max(1, mode.H);
        int x = (int)Math.Round(r.X * kx, MidpointRounding.AwayFromZero), y = (int)Math.Round(r.Y * ky, MidpointRounding.AwayFromZero);
        int x1 = (int)Math.Round((r.X + r.W) * kx, MidpointRounding.AwayFromZero), y1 = (int)Math.Round((r.Y + r.H) * ky, MidpointRounding.AwayFromZero);
        return new PixelRect(x, y, Math.Max(1, x1 - x), Math.Max(1, y1 - y));
    }

    /// A wall of `cols`×`rows` panels of `panelPx`, from the top left of the monitor.
    public static PixelRect Panels(int cols, int rows, int panelPx) =>
        new(0, 0, Math.Max(1, cols) * Math.Max(1, panelPx), Math.Max(1, rows) * Math.Max(1, panelPx));
}

/// The LED wall's shape (the same rules as amadeus/rig/trusses.py): its pixels (`screen.pixels`, as its processor
/// maps it) give its aspect, 16:9 without them; a wall taller than 16:9 stays under the ceiling.
public static class ScreenShape
{
    public const double DefaultAspect = 16.0 / 9.0;
    public static readonly (double Lower, double Upper) AspectRange = (0.25, 6);

    /// The pixels in a rig's `screen` value ({"pixels": [w, h]}), nil when not given.
    public static (int W, int H)? Pixels(JSONValue? screen)
    {
        if (screen?.Object?.GetValueOrDefault("pixels")?.Array is not { Count: 2 } px
            || px[0].Number is not { } w || px[1].Number is not { } h || w < 1 || h < 1) return null;
        return ((int)w, (int)h);
    }

    public static double Aspect((int W, int H)? pixels) =>
        pixels is { } p ? Math.Min(AspectRange.Upper, Math.Max(AspectRange.Lower, (double)p.W / p.H)) : DefaultAspect;

    /// The wall's width and height (m): `width` from the app's rule, the height from the aspect; a wall taller than
    /// 16:9 kept under the ceiling (narrower then).
    public static (double W, double H) Size(double width, double aspect, double bottom, double? ceiling)
    {
        double w = width, h = width / aspect;
        if (aspect < DefaultAspect && ceiling is { } c && c > 0)
        {
            var room = Math.Max(1, c - bottom - 0.3);
            if (h > room) { h = room; w = room * aspect; }
        }
        return (w, h);
    }
}
