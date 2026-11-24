// The LED wall's picture (the native version of web/js/screen.js; mac/Sources/AmadeusDMX/Render/WallRenderer.swift).
// The director picks a mode per phrase (decision.screen): off | ambient | figure | words | equalizer | psychedelic.
// Figures are playful neon outlines on the beat: a runner, a dancer, a jumping crowd, pong. The modes also bring
// abstract scenes: geometric shapes among the figures, a scope for the equaliser, a starfield for ambient, a tunnel in
// drops (Pick()). The music's style picks the family: the harder styles (hardstyle, hardcore, metal) get dark, sharp
// scenes (a wolf's head in facets, claws, jaws of spikes) and none of the playful figures; techno and the other club
// styles get hard lines and a ridge landscape beside theirs. The wall flashes when the lights strobe (frame.Strobe)
// and when blinders and strobe lights fire: it is part of the light show. Into a drop the wall counts 3-2-1 and
// shouts DROP!. Psychedelic is drawn by a shader (WallSource); everything else here, with
// SkiaSharp (the Mac draws with Core Graphics), into a 640×360 BGRA picture (the wall's shape when the rig gives its
// pixels; finer for a real LED wall: `scale`) that WallSource puts on the GPU.
//
// Core Graphics → Skia: the CG context is flipped to y-down like a canvas; Skia is y-down already. CG's per-draw
// shadow (the neon glow) is a drop-shadow image filter with sigma = blur / 2; setAlpha multiplies every paint.
// The Mac multiplies a shadow's blur by `scale` (CG's shadows are in pixels, not units); Skia's image filters are in
// the canvas's units already and scale with it, so here the blur stays as it is.
using System.Diagnostics;
using System.Numerics;
using System.Text.RegularExpressions;
using SkiaSharp;

using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

public enum WallScene { Auto, Off, Ambient, Starfield, Runner, Dancer, Crowd, Pong, Shapes, Lines, Grid, Wolf, Claws, Spikes, Words, Equalizer, Scope, Tunnel, Psychedelic }

/// What kind of scenes a style of music gets.
public enum WallFamily { Hard, Club, Other }

public static class WallScenes
{
    public static readonly WallScene[] AllCases = Enum.GetValues<WallScene>();
    public static readonly WallScene[] Figures = [WallScene.Runner, WallScene.Dancer, WallScene.Crowd, WallScene.Pong];

    public static string RawValue(this WallScene s) => s.ToString().ToLowerInvariant();
    public static WallScene? FromRawValue(string? raw) => AllCases.Cast<WallScene?>().FirstOrDefault(s => s!.Value.RawValue() == raw);
    static readonly string[] HardStyles = ["hardstyle", "hardcore", "metal"];
    static readonly string[] ClubStyles = ["techno", "trance", "psytrance", "edm", "house", "dnb", "dubstep"];

    public static WallFamily Family(Hello h)
    {
        var g = (h.Style.Length == 0 ? h.Genre : h.Style).ToLowerInvariant();
        return HardStyles.Contains(g) ? WallFamily.Hard : ClubStyles.Contains(g) ? WallFamily.Club : WallFamily.Other;
    }

    public static string Title(this WallScene s) => s == WallScene.Auto ? "Director's Choice" : s.ToString();

    public static string Symbol(this WallScene s) => s switch
    {
        WallScene.Auto => "wand.and.stars",
        WallScene.Off => "rectangle.slash",
        WallScene.Ambient => "cloud.fog",
        WallScene.Starfield => "sparkles",
        WallScene.Shapes => "triangle",
        WallScene.Scope => "waveform",
        WallScene.Tunnel => "circle.circle",
        WallScene.Lines => "barcode",
        WallScene.Grid => "mountain.2",
        WallScene.Wolf => "pawprint",
        WallScene.Claws => "line.diagonal",
        WallScene.Spikes => "bolt",
        WallScene.Runner => "figure.run",
        WallScene.Dancer => "figure.dance",
        WallScene.Crowd => "person.3",
        WallScene.Pong => "gamecontroller",
        WallScene.Words => "textformat.size",
        WallScene.Equalizer => "chart.bar",
        _ => "circle.hexagongrid",
    };
}

/// Flash: the lights strobe or the blinders fire, how much of the wall is the flash now (0..1). Layer: the overlay
/// layer (WallSource.hlsl's layer_mask): X the mask, Y the beat's lift 0..1, Z the beat's phase, W its parity.
public readonly record struct WallState(float Level, bool Psychedelic, Vector3[] Palette, Vector4 Bands, WallScene Scene,
                                        float Flash = 0, Vector4 Layer = default);

public sealed partial class WallRenderer : IDisposable
{
    /// The 16:9 picture's units: 640×360. A wall of another shape gets a canvas of its shape, its short side 360
    /// (Cw × Ch: 1440×360 for 4:1, 360×720 for 1:2): figures keep their size against the short side, scenes spread
    /// along the long one; on a tall wall the scenes that stand on a floor stand in its middle.
    public const int W = 640, H = 360;
    /// The canvas in units, the wall's shape.
    public float Cw { get; }
    public float Ch { get; }
    public double Aspect { get; }
    /// How much finer than the units the bitmap is (a real LED wall wants more pixels than the 3D stage's wall).
    public float Scale { get; }
    /// Where scenes that stand on something have their floor: the bottom, or on a tall wall a little below its middle.
    float Ground => Ch > H ? Ch - (Ch - H) * 0.4f : Ch;
    public int PixelWidth => _bitmap.Width;
    public int PixelHeight => _bitmap.Height;
    readonly SKBitmap _bitmap;
    readonly SKCanvas _canvas;
    public WallScene Force { get; set; } = WallScene.Auto;

    (string Mode, WallScene Scene) _cur = ("off", WallScene.Off);
    float _fade;
    float _level;
    /// The equaliser's bars: 16 on a 16:9 wall, more on a wider one.
    readonly float[] _eq, _caps;
    /// How far the tunnel, the stars and the shapes have travelled, in beats (faster in a drop), and the beat last seen.
    double _travel;
    double? _lastBp;
    /// The music's bass, mids and highs, smoothed (the scope's lines, the bokeh's breath).
    Vector3 _sound;
    /// The flash with the lights' strobes (its short tail), and the blinders' and strobe lights' level as it has been
    /// lately: the wall flashes on what comes on top of it.
    float _flash, _blindHeld;
    /// One overlay mask tried out (development: -wallMask 0…7).
    public static float? ForceMask { get; set; }
    /// The lights taken to strobe (development: -wallStrobe YES).
    public static Vector2? ForceStrobe { get; set; }
    double _amb;
    float[][] _fromPose = Moves["down"];
    int _lastBeat = -1;
    /// This picture's fade (the share of the last picture darkened) and the fade at the show's 40 pictures a second.
    float _fadeNow = 0.59f, _fadeRef = 0.59f;
    /// The time between pictures, smoothed: the trail's fade follows it (one picture 25 ms after the last, the next 50,
    /// would brighten and dim every glow that builds up on the trail).
    double _fadeDt = 1.0 / 40;
    static readonly Stopwatch Clock = Stopwatch.StartNew();

    /// The canvas for a wall of this shape, in units.
    public static (float W, float H) Canvas(double aspect)
    {
        var a = (float)aspect;
        return a >= 1 ? (MathF.Round(H * a, MidpointRounding.AwayFromZero), H) : (H, MathF.Round(H / a, MidpointRounding.AwayFromZero));
    }

    public WallRenderer(float scale = 1, double aspect = ScreenShape.DefaultAspect)
    {
        Scale = scale;
        Aspect = aspect;
        (Cw, Ch) = Canvas(aspect);
        var bars = Math.Min(48, Math.Max(12, (int)MathF.Round(16 * Cw / W, MidpointRounding.AwayFromZero)));
        _eq = new float[bars]; _caps = new float[bars];
        int w = (int)MathF.Round(Cw * scale, MidpointRounding.AwayFromZero), h = (int)MathF.Round(Ch * scale, MidpointRounding.AwayFromZero);
        // premultiplied BGRA, like the Mac's premultipliedFirst + byteOrder32Little (the texture is B8G8R8A8_UNORM)
        _bitmap = new SKBitmap(new SKImageInfo(w, h, SKColorType.Bgra8888, SKAlphaType.Premul));
        _canvas = new SKCanvas(_bitmap);
        _canvas.Clear(SKColors.Black);
        _canvas.Scale(scale);   // in units
    }

    /// Carries on where `old` was (another resolution, the same shape): its scene, fades, equaliser and dancer, and its
    /// last picture (the trails fade on it), so drawing finer or coarser doesn't show.
    public void TakeOver(WallRenderer old)
    {
        _cur = old._cur; _fade = old._fade; _level = old._level; _amb = old._amb;
        if (old._eq.Length == _eq.Length) { old._eq.CopyTo(_eq, 0); old._caps.CopyTo(_caps, 0); }
        _travel = old._travel; _lastBp = old._lastBp; _sound = old._sound; _flash = old._flash; _blindHeld = old._blindHeld;
        _fromPose = old._fromPose; _lastBeat = old._lastBeat; Force = old.Force; _fadeDt = old._fadeDt;
        if (old.Aspect != Aspect) return;
        _canvas.Save();
        _canvas.ResetMatrix();   // in pixels: the old picture stretched over the new one
        using var image = SKImage.FromBitmap(old._bitmap);
        _canvas.DrawImage(image, new SKRect(0, 0, _bitmap.Width, _bitmap.Height), new SKSamplingOptions(SKFilterMode.Linear, SKMipmapMode.None));
        _canvas.Restore();
    }

    public void Dispose()
    {
        _canvas.Dispose();
        _bitmap.Dispose();
        _fill.Dispose(); _stroke.Dispose();
    }

    /// The picture: PixelWidth × PixelHeight BGRA (premultiplied), RowBytes per row.
    public ReadOnlySpan<byte> Pixels => _bitmap.GetPixelSpan();
    public int RowBytes => _bitmap.RowBytes;

    /// The picture as a PNG (diagnostics, tests).
    public byte[] Png()
    {
        using var data = _bitmap.Encode(SKEncodedImageFormat.Png, 100);
        return data.ToArray();
    }

    public static long Hash(int n, int salt = 0) =>
        (long)(unchecked((ulong)(long)(n + 1) * 2654435761UL + (ulong)salt * 40503UL) % 4294967296UL);

    static int Mod(long a, int n) => (int)(((a % n) + n) % n);

    static readonly Dictionary<string, string[]> Rules = new()
    {
        ["intro"] = ["off", "ambient"], ["groove"] = ["off", "figure", "equalizer", "off", "figure", "words"],
        ["buildup"] = ["words", "figure"], ["drop"] = ["psychedelic", "figure", "equalizer"],
        ["breakdown"] = ["ambient", "off", "figure"], ["outro"] = ["ambient", "off"],
        ["verse"] = ["off", "ambient", "words"], ["chorus"] = ["figure", "equalizer", "words"], ["bridge"] = ["ambient", "off"],
    };

    (string, WallScene) Wanted(Frame f, Decision? d, Hello h)
    {
        if (Force != WallScene.Auto)
            return (WallScenes.Figures.Contains(Force) ? "figure" : Force.RawValue(), Force);
        var mode = d?.Screen ?? "";
        if (mode.Length == 0)
        {
            var opts = Rules.GetValueOrDefault(d?.Section ?? "") ?? ["off"];
            mode = opts[Mod(Hash(f.Phrase, 2), opts.Length)];
        }
        return (mode, Pick(mode, f.Phrase, d?.Section == "drop", WallScenes.Family(h)));
    }

    /// The scene a mode shows this phrase: the director's modes are few, each brings a small family of scenes.
    public static WallScene Pick(string mode, int phrase, bool drop, WallFamily family = WallFamily.Other)
    {
        const WallScene Wolf = WallScene.Wolf, Tunnel = WallScene.Tunnel, Shapes = WallScene.Shapes, Lines = WallScene.Lines;
        WallScene[] pool;
        switch (mode, family)
        {
            case ("figure", WallFamily.Hard): pool = [Wolf, WallScene.Claws, WallScene.Spikes, Shapes, .. (drop ? new[] { Wolf, Tunnel } : [])]; break;
            case ("figure", WallFamily.Club): pool = [Lines, WallScene.Grid, Shapes, WallScene.Dancer, WallScene.Crowd, .. (drop ? new[] { Tunnel, Lines } : [])]; break;
            case ("figure", _): pool = [.. WallScenes.Figures, .. (drop ? new[] { Shapes, Tunnel } : [Shapes])]; break;
            case ("equalizer", WallFamily.Hard): pool = [WallScene.Spikes, WallScene.Scope]; break;
            case ("equalizer", WallFamily.Club): pool = [WallScene.Equalizer, WallScene.Scope, WallScene.Grid]; break;
            case ("equalizer", _): pool = [WallScene.Equalizer, WallScene.Scope]; break;
            case ("ambient", _): pool = [WallScene.Ambient, WallScene.Ambient, WallScene.Starfield]; break;
            case ("psychedelic", WallFamily.Hard): pool = [WallScene.Psychedelic, Tunnel, WallScene.Claws]; break;
            case ("psychedelic", WallFamily.Club): pool = [WallScene.Psychedelic, WallScene.Psychedelic, Tunnel, Lines]; break;
            case ("psychedelic", _): pool = [WallScene.Psychedelic, WallScene.Psychedelic, Tunnel]; break;
            default: return WallScenes.FromRawValue(mode) ?? WallScene.Off;
        }
        return pool[Mod(Hash(phrase, 9), pool.Length)];
    }

    public WallState Update(Frame f, Hello h, float dt)
    {
        var d = f.Phrase >= 0 && f.Phrase < h.Plan.Count ? h.Plan[f.Phrase] : null;
        var want = Wanted(f, d, h);
        // the show arc's LED wall knob (live mode): dimmer, below half only calm colour, at zero off
        var wall = Force == WallScene.Auto ? (float)(f.Arc is { On: true } arc && arc.Values.TryGetValue("screen", out var sv) ? sv : 1) : 1;
        if (wall < 0.03f) want = ("off", WallScene.Off);
        else if (wall < 0.5f && want.Item1 != "off") want = ("ambient", WallScene.Ambient);
        var next = f.Phrase + 1 >= 0 && f.Phrase + 1 < h.Plan.Count ? h.Plan[f.Phrase + 1] : null;
        var spb = 60 / Math.Max(h.Bpm, 60);
        var nextDrop = h.Countdown == f.Phrase + 1 && next?.Section == "drop" && d?.Section != "drop";  // the rare one
        var beatsLeft = nextDrop ? (next!.Start - f.T) / spb : 99;
        if (want.Item1 == "off" && beatsLeft <= 4.5 && Force == WallScene.Auto && wall >= 0.5f) want = ("words", WallScene.Words);  // a dark wall counts in
        var shout = wall >= 0.5f && h.Countdown == f.Phrase && d?.Section == "drop" && _cur.Mode != "off" && _cur.Scene != WallScene.Psychedelic && (f.T - d.Start) / spb < 2;
        if (shout) _fade = 1;
        else if (want.Item2 != _cur.Scene)
        {
            _fade = MathF.Max(0, _fade - dt * 5);
            if (_fade == 0) _cur = want;
        }
        else
        {
            _fade = MathF.Min(1, _fade + dt * (d?.Section == "drop" ? 6 : 1.5f));
        }

        var bp = f.Bp ?? f.T * h.Bpm / 60;
        var b = f.Bands;
        var bass = MathF.Min(1, ((b.Length > 0 ? b[0] : 0) + (b.Length > 1 ? b[1] : 0)) / 2);
        var cols = Colours(d?.Palette);
        var bandsV = new Vector4(bass, b.Length > 2 ? b[2] : 0, b.Length > 3 ? b[3] : (b.Length > 0 ? b[^1] : 0), 0);
        _sound += (new Vector3(bandsV.X, bandsV.Y, bandsV.Z) - _sound) * MathF.Min(1, dt * 9);
        float target;
        if (_cur.Scene == WallScene.Psychedelic)
        {
            var fx = f.Fx;
            var mean = fx.Length == 0 ? 0 : fx.Sum(v => MathF.Min(1, (v.Length > 0 ? v[0] : 0) + (v.Length > 4 ? v[4] : 0))) / fx.Length;
            target = mean < 0.01f ? 0.05f : MathF.Min(1, 0.3f + 1.4f * mean);
        }
        else
        {
            Draw(f, d, h, cols, bp, bass, dt);
            var calm = d?.Section != "drop" && d?.Section != "buildup";
            target = _cur.Mode == "off" ? 0 : _cur.Scene == WallScene.Ambient ? 0.4f : _cur.Scene == WallScene.Starfield && calm ? 0.55f : 0.95f;
        }
        _level += (target * MathF.Min(1, wall * 2) * _fade - _level) * MathF.Min(1, dt * 10);
        // the wall flashes with the lights: the share of the rig that strobes, on its beat grid, and the blinders and
        // strobe lights when they fire (the engine holds all of it to the set's flash limit); a short tail after it
        var flashNow = 0f;
        if (Force != WallScene.Off && wall >= 0.5f)
        {
            if ((ForceStrobe ?? f.Strobe) is { } st && st.X >= 0.15f) flashNow = st.Y * MathF.Min(1, 0.35f + 1.3f * st.X);
            float sum = 0, n = 0;
            for (var i = 0; i < h.Fixtures.Count && i < f.Fx.Length; i++)
            {
                if (h.Fixtures[i].Kind is not (FixtureKind.Blinder or FixtureKind.Strobe)) continue;
                sum += f.Fx[i].Length > 0 ? f.Fx[i][0] : 0; n++;
            }
            // (their hit, not their light: one held on is let go of in half a second, or the wall would stay white)
            var blind = n > 0 ? sum / n : 0;
            _blindHeld += (blind - _blindHeld) * MathF.Min(1, dt * (blind > _blindHeld ? 2.5f : 8));
            if (blind - _blindHeld > 0.15f) flashNow = MathF.Max(flashNow, MathF.Min(1, (blind - _blindHeld) * 1.6f));
        }
        _flash = MathF.Max(flashNow, _flash - dt * 12);
        // the overlay layer, as a VJ lays one over the picture: a mask per phrase in the style's taste; the picture
        // lifts through it on every beat of the parts with energy, and the strobe's flash shows through it
        var beatNow = (int)Math.Floor(bp);
        var phase = (float)(bp - Math.Floor(bp));
        var section = d?.Section ?? "";
        float[] masks = WallScenes.Family(h) switch { WallFamily.Hard => [5, 3, 1, 7, 6], WallFamily.Club => [2, 1, 3, 4, 7], _ => [4, 6, 1, 0] };
        var lively = Force != WallScene.Off && wall >= 0.5f && _cur.Mode != "off" && _cur.Scene != WallScene.Ambient
            && section is "drop" or "chorus" or "buildup";
        var lift = lively ? MathF.Exp(-phase * 5) * (section == "drop" ? 1 : 0.6f) * _fade : 0;
        var layer = new Vector4(ForceMask ?? masks[Mod(Hash(f.Phrase, 91), masks.Length)], lift, phase, Mod(beatNow, 2));
        return new WallState(MathF.Max(_level, _flash * 0.95f), _cur.Scene == WallScene.Psychedelic, Palettes.Colors(d?.Palette), bandsV,
                             _cur.Scene, _flash, layer);
    }

    // MARK: drawing state (Core Graphics' graphics state, the parts the scenes use)

    struct GState
    {
        public SKColor Stroke, Fill, ShadowColor;
        public float LineWidth, Alpha, ShadowBlur;
        public float[]? Dash;
        public bool Hard;   // mitred joins and butt caps (the sharp scenes); round otherwise
    }

    GState _g = new() { Stroke = SKColors.Black, Fill = SKColors.Black, LineWidth = 1, Alpha = 1 };
    readonly Stack<GState> _saved = new();
    readonly SKPaint _fill = new() { IsAntialias = true, Style = SKPaintStyle.Fill };
    readonly SKPaint _stroke = new() { IsAntialias = true, Style = SKPaintStyle.Stroke, StrokeCap = SKStrokeCap.Round, StrokeJoin = SKStrokeJoin.Round };

    void SaveGState() { _saved.Push(_g); _canvas.Save(); }
    void RestoreGState() { _g = _saved.Pop(); _canvas.Restore(); }
    void SetShadow(float blur, SKColor? color) { _g.ShadowBlur = color is null ? 0 : blur; _g.ShadowColor = color ?? SKColors.Transparent; }
    void SetAlpha(float a) => _g.Alpha = a;

    static SKColor WithAlpha(SKColor c, float k) => c.WithAlpha((byte)Math.Clamp(MathF.Round(c.Alpha * k), 0, 255));

    SKPaint Paint(bool stroke)
    {
        var p = stroke ? _stroke : _fill;
        p.Color = WithAlpha(stroke ? _g.Stroke : _g.Fill, _g.Alpha);
        p.Shader = null;
        if (stroke)
        {
            p.StrokeWidth = _g.LineWidth;
            p.StrokeJoin = _g.Hard ? SKStrokeJoin.Miter : SKStrokeJoin.Round;
            p.StrokeCap = _g.Hard ? SKStrokeCap.Butt : SKStrokeCap.Round;
            p.StrokeMiter = 12;
            p.PathEffect?.Dispose();
            p.PathEffect = _g.Dash is { Length: > 0 } dash ? SKPathEffect.CreateDash(dash, 0) : null;
        }
        p.ImageFilter?.Dispose();
        p.ImageFilter = _g.ShadowBlur > 0
            ? SKImageFilter.CreateDropShadow(0, 0, _g.ShadowBlur / 2, _g.ShadowBlur / 2, WithAlpha(_g.ShadowColor, _g.Alpha))
            : null;
        return p;
    }

    void FillRect(SKRect r) => _canvas.DrawRect(r, Paint(false));
    void StrokeRect(SKRect r) => _canvas.DrawRect(r, Paint(true));
    void FillEllipse(SKRect r) => _canvas.DrawOval(r, Paint(false));
    void StrokePath(SKPath p) => _canvas.DrawPath(p, Paint(true));

    void StrokeLineSegments(params SKPoint[] pts)
    {
        using var p = new SKPath();
        for (var i = 0; i + 1 < pts.Length; i += 2) { p.MoveTo(pts[i]); p.LineTo(pts[i + 1]); }
        StrokePath(p);
    }

    static SKRect Rect(double x, double y, double w, double h) => SKRect.Create((float)x, (float)y, (float)w, (float)h);
    static SKPoint Pt(double x, double y) => new((float)x, (float)y);

    // MARK: drawing

    static Vector3[] Colours(string? palette) =>
        Palettes.Colors(palette).Select(c =>
        {
            var m = MathF.Max(MathF.Max(MathF.Max(c.X, c.Y), c.Z), 0.01f);
            return Vector3.Min(Vector3.One, new Vector3(0.25f) + 0.75f * c / m);   // brightened: must read on a dark wall
        }).ToArray();

    static SKColor Cg(Vector3 c, float a = 1) =>
        new((byte)Math.Clamp(MathF.Round(c.X * 255), 0, 255), (byte)Math.Clamp(MathF.Round(c.Y * 255), 0, 255),
            (byte)Math.Clamp(MathF.Round(c.Z * 255), 0, 255), (byte)Math.Clamp(MathF.Round(a * 255), 0, 255));

    void Neon(Vector3 c, float width)
    {
        _g.Stroke = Cg(c); _g.Fill = Cg(c); _g.LineWidth = width; _g.Hard = false;
        SetShadow(width * 2.2f, Cg(c));
    }

    /// A colour without glow (far, small or many things: a glow per star or window costs too much and reads as mud).
    void Flat(Vector3 c, float width)
    {
        _g.Stroke = Cg(c); _g.Fill = Cg(c); _g.LineWidth = width; _g.Hard = false;
        SetShadow(0, null);
    }

    /// A colour dimmed towards black: opaque, so it looks the same at any drawing rate (alpha would build up on the trail).
    static Vector3 Dim(Vector3 c, float k) => c * Math.Clamp(k, 0, 1);

    static Vector3 Mix(Vector3 a, Vector3 b, float t) => a + (b - a) * Math.Clamp(t, 0, 1);

    /// A regular polygon (0 sides: a circle) round (x, y).
    static SKPath Polygon(double x, double y, double r, int sides, double rot)
    {
        var p = new SKPath();
        if (sides < 3) { p.AddOval(Rect(x - r, y - r, r * 2, r * 2)); return p; }
        for (var i = 0; i < sides; i++)
        {
            var a = rot + i * 2 * Math.PI / sides - Math.PI / 2;
            var pt = Pt(x + r * Math.Cos(a), y + r * Math.Sin(a));
            if (i == 0) p.MoveTo(pt); else p.LineTo(pt);
        }
        p.Close();
        return p;
    }

    static double Frac(double v) => v - Math.Floor(v);

    /// Hard edges: mitred corners, no round caps, no glow (the sharp scenes).
    void Sharp(Vector3 c, float width)
    {
        Flat(c, width);
        _g.Hard = true;
    }

    /// A glow round a wall-sized line, cheaply: a few wide translucent strokes under it (a real glow costs its whole
    /// bounding box, which for these is the wall).
    void SoftGlow(SKPath p, Vector3 c, float width)
    {
        SetShadow(0, null);
        var hard = _g.Hard;
        _g.Hard = false;
        foreach (var (wide, alpha) in new[] { (7.0f, 0.05f), (4.6f, 0.08f), (3.0f, 0.13f), (1.9f, 0.22f) })
        {
            _g.Stroke = Cg(c, alpha); _g.LineWidth = width * wide;
            StrokePath(p);
        }
        _g.Hard = hard;
    }

    static SKPath PathOf(params SKPoint[] pts)
    {
        var p = new SKPath();
        p.AddPoly(pts, close: true);
        return p;
    }

    void FillPoly(params SKPoint[] pts) { using var p = PathOf(pts); FillPath(p); }

    void StrokeEllipse(SKRect r) => _canvas.DrawOval(r, Paint(true));
    void FillPath(SKPath p) => _canvas.DrawPath(p, Paint(false));

    void Draw(Frame f, Decision? d, Hello h, Vector3[] cols, double bp, float bass, float dt)
    {
        SaveGState();
        SetShadow(0, null);
        // a short trail behind moving lines: how much of the last picture fades is set per 1/60 s, so the trail
        // is as short at any drawing rate (a fixed share per picture ghosted when the wall was drawn less often)
        // (sharp scenes leave next to no trail)
        var fadeShare = _cur.Scene == WallScene.Words ? 0.8 : _cur.Scene is WallScene.Lines or WallScene.Grid or WallScene.Wolf or WallScene.Spikes ? 0.75
            : _cur.Scene is WallScene.Tunnel or WallScene.Scope or WallScene.Claws ? 0.6 : 0.45;
        // the tunnel, the stars and the shapes travel with the beat, faster in a drop (a jump in the song is no travel)
        bool drop = d?.Section == "drop", build = d?.Section == "buildup";
        var rate = _cur.Scene == WallScene.Starfield ? (drop ? 2.5 : build ? 1.2 : 0.5) : drop ? 2.0 : 1.0;
        if (_lastBp is { } last && bp > last && bp - last < 2) _travel += (bp - last) * rate;
        _lastBp = bp;
        _fadeDt += (Math.Min(0.1, Math.Max(dt, 1.0 / 240)) - _fadeDt) * 0.15;
        _fadeNow = (float)(1 - Math.Pow(1 - fadeShare, _fadeDt * 60));
        _fadeRef = (float)(1 - Math.Pow(1 - fadeShare, 1.5));
        _g.Fill = new SKColor(0, 0, 0, (byte)Math.Clamp(Math.Round(255 * _fadeNow), 0, 255));
        FillRect(Rect(0, 0, Cw, Ch));
        var phraseFrac = d is null ? 0 : Math.Min(1, Math.Max(0, d.End > d.Start ? (f.T - d.Start) / (d.End - d.Start) : 0));
        if (!(_cur.Mode != "off" && Countdown(f, d, h, cols)))
        {
            switch (_cur.Scene)
            {
                case WallScene.Runner: Runner(d, cols, bp, bass); break;
                case WallScene.Dancer: Dancer(d, cols, bp); break;
                case WallScene.Crowd: Crowd(d, cols, bp, bass, phraseFrac); break;
                case WallScene.Pong: Pong(d, cols, bp); break;
                case WallScene.Words: Words(h, cols, bp); break;
                case WallScene.Equalizer: Equalizer(f, cols, dt); break;
                case WallScene.Ambient: Ambient(cols, dt); break;
                case WallScene.Tunnel: Tunnel(cols, bass); break;
                case WallScene.Starfield: Starfield(cols, drop); break;
                case WallScene.Scope: Scope(cols, bp); break;
                case WallScene.Shapes: Shapes(cols, bp, drop); break;
                case WallScene.Lines: Lines(cols, bp, bass, drop); break;
                case WallScene.Grid: Grid(cols); break;
                case WallScene.Wolf: Wolf(cols, bp, bass, drop); break;
                case WallScene.Claws: Claws(cols, bp, drop); break;
                case WallScene.Spikes: Spikes(f, cols, bp, bass, dt); break;
            }
        }
        RestoreGState();
    }

    /// What a translucent stroke drawn on every picture settles at (it builds up on the fading last picture), at the
    /// show's 40 pictures a second.
    float Settled(float a) => a / (_fadeRef + a - _fadeRef * a);

    /// The alpha that brings a stroke drawn on every picture to what `a` looks like at 40 pictures a second, at this
    /// picture's rate: the time between pictures varies (they are drawn on a thread of their own), and a fixed alpha
    /// would make the wall brighter and darker with it, a flicker.
    float Held(float a)
    {
        var t = Settled(a);
        return MathF.Min(1, t * _fadeNow / MathF.Max(0.001f, 1 - t * (1 - _fadeNow)));
    }

    /// A stick figure: hip at (x, y), size s. Angles: 0 = hanging down, positive = towards +x.
    (double, double, double) Figure(double x, double y, double s, double lean = 0, double head = 0, float[][]? arms = null, float[][]? legs = null)
    {
        static SKPoint Seg(double x0, double y0, double a, double len) => Pt(x0 + len * Math.Sin(a), y0 + len * Math.Cos(a));
        using var path = new SKPath();
        void Limb(double x0, double y0, float[] a, double len)
        {
            var p1 = Seg(x0, y0, a[0], len);
            var p2 = Seg(p1.X, p1.Y, a[0] + a[1], len);
            path.MoveTo(Pt(x0, y0)); path.LineTo(p1); path.LineTo(p2);
        }
        double nx = x + Math.Sin(lean) * s * 0.42, ny = y - Math.Cos(lean) * s * 0.42, r = s * 0.11;
        path.MoveTo(Pt(x, y)); path.LineTo(Pt(nx, ny));
        foreach (var a in arms ?? []) Limb(nx - Math.Sin(lean) * s * 0.04, ny + s * 0.04, a, s * 0.21);
        foreach (var l in legs ?? []) Limb(x, y, l, s * 0.26);
        double hx = nx + Math.Sin(lean + head) * r * 1.25, hy = ny - Math.Cos(lean + head) * r * 1.25;
        path.AddOval(Rect(hx - r, hy - r, r * 2, r * 2));
        StrokePath(path);
        return (hx, hy, r);
    }

    static float[][] P(float a, float b, float c, float d) => [[a, b], [c, d]];

    void Runner(Decision? d, Vector3[] cols, double bp, float bass)
    {
        double s = 150, gy = Ground - 60, rx = Math.Round(Cw * 0.36, MidpointRounding.AwayFromZero);
        var drop = d?.Section == "drop";
        var speed = drop ? 90.0 : 60.0;
        var scroll = bp * speed;
        var c1 = cols[1 % cols.Length];
        // a moon, and a far skyline that passes slowly
        Flat(Dim(c1, 0.5f), 2);
        StrokeEllipse(Rect(Cw * 0.78 - 24, gy - 222, 48, 48));
        StrokeEllipse(Rect(Cw * 0.78 - 6, gy - 212, 9, 9));
        Flat(Dim(c1, 0.3f), 1.5f);
        using (var far = new SKPath())
        {
            var offF = scroll * 0.12;
            for (var i = -1; i < (int)(Cw / 44) + 2; i++)
            {
                var b = i + (int)Math.Floor(offF / 44);
                var x = i * 44 - Frac(offF / 44) * 44;
                var hh = 70 + Hash(b, 14) % 85;
                far.MoveTo(Pt(x, gy)); far.LineTo(Pt(x, gy - hh));
                far.LineTo(Pt(x + 36, gy - hh)); far.LineTo(Pt(x + 36, gy));
            }
            StrokePath(far);
        }
        // the near skyline, its windows lit here and there
        Neon(c1, 2);
        SetAlpha(Held(0.45f));
        using (var sky = new SKPath())
        using (var lit = new SKPath())
        {
            var off = scroll * 0.3;
            for (var i = -1; i < (int)(Cw / 70) + 2; i++)
            {
                var b = i + (int)Math.Floor(off / 70);
                var x = i * 70 - Frac(off / 70) * 70;
                var hh = 40 + Hash(b) % 90;
                sky.MoveTo(Pt(x, gy)); sky.LineTo(Pt(x, gy - hh));
                sky.LineTo(Pt(x + 52, gy - hh)); sky.LineTo(Pt(x + 52, gy));
                for (var row = 0; row < (int)((hh - 12) / 16); row++)
                    for (var col = 0; col < 3; col++)
                        if (Hash(b * 31 + row * 7 + col, 6) % 3 == 0)
                            lit.AddRect(Rect(x + 8 + col * 14, gy - hh + 9 + row * 16, 8, 7));
            }
            StrokePath(sky);
            SetAlpha(1);
            Flat(Dim(Mix(c1, new Vector3(1, 0.9f, 0.6f), 0.5f), 0.55f), 1);
            FillPath(lit);
        }
        // the road: its marks pass at the runner's speed
        Flat(Dim(cols[0], 0.5f), 2);
        if (gy + 18 < Ch)
        {
            var marks = new List<SKPoint>();
            for (var i = -1; i < (int)(Cw / 80) + 2; i++)
            {
                var x = i * 80 - Frac(scroll / 80) * 80;
                marks.Add(Pt(x, gy + 18)); marks.Add(Pt(x + 34, gy + 18));
            }
            StrokeLineSegments([.. marks]);
        }
        Neon(cols[0], 3);
        StrokeLineSegments(Pt(0, gy), Pt(Cw, gy));
        // a hurdle every bar, arriving at the runner on the downbeat
        var bar = bp / 4;
        var hx = rx + (Math.Ceiling(bar) - bar) * 4 * speed;
        StrokeLineSegments(Pt(hx - 12, gy), Pt(hx - 12, gy - 38), Pt(hx + 12, gy), Pt(hx + 12, gy - 38),
                           Pt(hx - 16, gy - 38), Pt(hx + 16, gy - 38), Pt(hx - 12, gy - 26), Pt(hx + 12, gy - 26));
        var fromDown = (bp + 0.5) % 4 - 0.5;
        var jump = Math.Abs(fromDown) < 0.5 ? Math.Cos(fromDown * Math.PI) : 0;
        var w = (float)(bp * Math.PI);
        var y = gy - s * 0.5 - Math.Abs(MathF.Cos(w)) * 6 - jump * 70;
        // the runner's shadow on the road, smaller while in the air
        Flat(Dim(cols[0], 0.35f), 2);
        var sh = 34 - jump * 14;
        StrokeEllipse(Rect(rx - sh, gy + 4, sh * 2, 5));
        Neon(cols[0], 5);
        (double hx2, double hy2, double r) = jump > 0.05
            ? Figure(rx, y, s, lean: 0.35, arms: P(-2.4f, 0.3f, 2.6f, -0.2f), legs: P(1.3f, -1.9f, -0.4f, -1.2f))
            : Figure(rx, y, s, lean: drop ? 0.35 : 0.22,
                     arms: P(-0.9f * MathF.Sin(w), 1.5f, 0.9f * MathF.Sin(w), 1.5f),
                     legs: P(0.75f * MathF.Sin(w), -0.2f - 1.1f * MathF.Max(0, MathF.Sin(w + 1.2f)),
                             -0.75f * MathF.Sin(w), -0.2f - 1.1f * MathF.Max(0, -MathF.Sin(w + 1.2f))));
        if (drop || bass > 0.7f)  // speed lines and a drop of sweat
        {
            _g.LineWidth = 2;
            var pts = new List<SKPoint>();
            for (var i = 0; i < 4; i++)
            {
                var ly = y - 40 + i * 22;
                pts.Add(Pt(rx - 80 - i * 12, ly)); pts.Add(Pt(rx - 120 - i * 20, ly));
            }
            StrokeLineSegments([.. pts]);
            var t = bp % 1;
            FillEllipse(Rect(hx2 - r - 9 - t * 20, hy2 - r - 3 + t * 25, 6, 6));
        }
    }

    public static readonly Dictionary<string, float[][]> Moves = new()
    {
        ["down"] = P(-0.25f, 0.2f, 0.25f, -0.2f), ["up"] = P(-2.6f, 0, 2.6f, 0), ["hips"] = P(-0.9f, 1.9f, 0.9f, -1.9f),
        ["disco"] = P(-0.5f, 1.5f, 2.75f, 0), ["disco2"] = P(-2.75f, 0, 0.5f, -1.5f), ["robot"] = P(-1.57f, -1.57f, 1.57f, 1.57f),
        ["robot2"] = P(-1.57f, 1.57f, 1.57f, -1.57f), ["clap"] = P(-2.9f, 0.6f, 2.9f, -0.6f), ["point"] = P(-0.3f, 0.2f, 1.6f, 0),
    };

    public static readonly string[][] Routines = [["disco", "down", "disco", "down"], ["robot", "robot2", "robot", "robot2"],
                                                  ["hips", "clap", "hips", "clap"], ["point", "disco2", "point", "up"], ["up", "down", "up", "clap"]];

    void Dancer(Decision? d, Vector3[] cols, double bp)
    {
        var beat = (int)Math.Floor(bp);
        var u = (float)(bp - Math.Floor(bp));
        var drop = d?.Section == "drop";
        var routine = Routines[Mod(Hash(beat / 8, 3), Routines.Length)];
        var want = drop && beat % 4 == 0 ? Moves["up"] : Moves[routine[Mod(beat, 4)]];
        if (beat != _lastBeat) { _fromPose = Moves[routine[Mod(beat + 3, 4)]]; _lastBeat = beat; }
        var k = MathF.Min(1, u / 0.18f);
        var arms = Enumerable.Range(0, 2).Select(i => Enumerable.Range(0, 2).Select(j => _fromPose[i][j] + (want[i][j] - _fromPose[i][j]) * k).ToArray()).ToArray();
        var dip = MathF.Sin(u * MathF.PI);
        var hop = drop && beat % 4 == 0 ? Math.Sin(u * Math.PI) * 60 : 0;
        var legs = hop > 0 ? P(-0.6f, 1.4f, 0.6f, -1.4f) : P(-0.25f - 0.25f * dip, 0.5f * dip, 0.25f + 0.25f * dip, -0.5f * dip);
        double mx = Cw / 2, floorY = Ground - 15, hipY = Ground - 155;
        // two spotlights from above, swaying over the dancer
        SetShadow(0, null);
        double[] lamps = [mx - Math.Min(Cw * 0.32, 260), mx + Math.Min(Cw * 0.32, 260)];
        for (var i = 0; i < 2; i++)
        {
            double x0 = lamps[i], xf = mx + Math.Sin(bp * Math.PI / 4 + i * 2.4) * 70;
            using var cone = new SKPath();
            cone.MoveTo(Pt(x0 - 6, floorY - 330)); cone.LineTo(Pt(x0 + 6, floorY - 330));
            cone.LineTo(Pt(xf + 75, floorY)); cone.LineTo(Pt(xf - 75, floorY)); cone.Close();
            _g.Fill = Cg(cols[(i + 1) % cols.Length], Held(0.07f));
            FillPath(cone);
        }
        // a disco ball: it turns, and throws a few sparks on the beat
        double by = floorY - 318, br = 20;
        Flat(Dim(cols[1 % cols.Length], 0.7f), 1.5f);
        StrokeLineSegments(Pt(mx, by - br), Pt(mx, by - br - 22));
        StrokeEllipse(Rect(mx - br, by - br, br * 2, br * 2));
        for (var j = 0; j < 3; j++)
        {
            var wj = br * Math.Abs(Math.Cos(bp * Math.PI / 8 + j * Math.PI / 3));
            StrokeEllipse(Rect(mx - wj, by - br, wj * 2, br * 2));
        }
        StrokeLineSegments(Pt(mx - br * 0.95, by - 7), Pt(mx + br * 0.95, by - 7), Pt(mx - br * 0.95, by + 7), Pt(mx + br * 0.95, by + 7));
        Neon(cols[0], 2);
        if (u < 0.6f)
        {
            var sparks = new List<SKPoint>();
            for (var j = 0; j < 6; j++)
            {
                double a = Hash(beat * 6 + j, 17) % 628 / 100.0, r0 = br + 6 + u * 26;
                sparks.Add(Pt(mx + r0 * Math.Cos(a), by + r0 * Math.Sin(a)));
                sparks.Add(Pt(mx + (r0 + 9) * Math.Cos(a), by + (r0 + 9) * Math.Sin(a)));
            }
            StrokeLineSegments([.. sparks]);
        }
        var n = 8 + 2 * Math.Max(0, (int)((Cw - 640) / 140));
        for (var i = 0; i < n; i++)  // the dance floor lights up with the beat
        {
            var on = Hash(i + beat * 8, 1) % 3 == 0;
            Neon(cols[i % cols.Length], 2);
            double x0 = mx + (i - n / 2) * 70, x1 = x0 + 70;
            using var p = new SKPath();
            p.MoveTo(Pt(x0 + (x0 - mx) * 0.4, floorY)); p.LineTo(Pt(x1 + (x1 - mx) * 0.4, floorY));
            p.LineTo(Pt(x1, floorY - 45)); p.LineTo(Pt(x0, floorY - 45)); p.Close();
            if (on)   // a lit tile glows
            {
                _g.Fill = Cg(cols[i % cols.Length], Held(0.16f));
                FillPath(p);
            }
            SetAlpha(Held(on ? 0.55f : 0.12f));
            StrokePath(p);
            SetAlpha(1);
        }
        // two backing dancers, a move behind and mirrored
        if (Cw >= 600)
        {
            var side = Math.Min(Cw * 0.3, 250);
            for (var i = 0; i < 2; i++)
            {
                var pose = i == 0 ? arms : [arms[1].Select(v => -v).ToArray(), arms[0].Select(v => -v).ToArray()];
                Neon(Dim(cols[(i + 1) % cols.Length], 0.75f), 3.5f);
                Figure(mx + (i == 0 ? -side : side), hipY + 52 - dip * 5 - hop * 0.5, 125, head: -0.15 * Math.Sin(bp * Math.PI),
                       arms: pose, legs: P(-0.25f - 0.2f * dip, 0.4f * dip, 0.25f + 0.2f * dip, -0.4f * dip));
            }
        }
        Neon(cols[0], 6);
        Figure(mx, hipY - dip * 8 - hop, 190, lean: 0.07 * Math.Sin(bp * Math.PI), head: 0.15 * Math.Sin(bp * Math.PI), arms: arms, legs: legs);
        if (hop > 0) { Neon(cols[1 % cols.Length], 4); Text("!", Pt(mx + 90, hipY - 145 - hop * 0.3), size: 46, fill: true); }
    }

    void Crowd(Decision? d, Vector3[] cols, double bp, float bass, double phraseFrac)
    {
        var n = Math.Max(4, (int)Math.Round(11 * Cw / 640, MidpointRounding.AwayFromZero));
        var drop = d?.Section == "drop";
        var hands = drop || (d?.Intensity ?? 1) >= 2;
        // light sweeps over the heads
        SetShadow(0, null);
        for (var k = 0; k < 2; k++)
        {
            double x0 = Cw * (k == 0 ? 0.25 : 0.75), xf = x0 + Math.Sin(bp * Math.PI / 4 + k * 2) * Ground * 0.55;
            using var beam = new SKPath();
            beam.MoveTo(Pt(x0 - 5, Ground - 345)); beam.LineTo(Pt(x0 + 5, Ground - 345));
            beam.LineTo(Pt(xf + 55, Ground)); beam.LineTo(Pt(xf - 55, Ground)); beam.Close();
            _g.Fill = Cg(cols[(k + 1) % cols.Length], Held(0.06f));
            FillPath(beam);
        }
        // the back row: smaller, dimmer, half a beat behind
        for (var i = 0; i <= n; i++)
        {
            double x = 40 + (i - 0.5) * (Cw - 80.0) / (n - 1), s = 72 + Hash(i, 8) % 16;
            var u = Frac(bp - 0.5 - i * 0.09);
            var jump = Math.Max(0, Math.Sin(u * Math.PI)) * (drop ? 24 : 8 + 12 * bass);
            Flat(Dim(cols[(i + 1) % cols.Length], 0.42f), 2);
            Figure(x, Ground - 62 - s * 0.5 - jump, s,
                   arms: hands ? P(-2.8f, 0.2f, 2.8f, -0.2f) : P(-0.3f, 0.4f, 0.3f, -0.4f), legs: P(-0.2f, 0, 0.2f, 0));
        }
        for (var i = 0; i < n; i++)
        {
            double x = 40 + i * (Cw - 80.0) / (n - 1), s = 105 + Hash(i, 5) % 25;
            var u = drop ? bp % 1 : (bp - i * 0.12) % 1;
            var jump = Math.Max(0, Math.Sin(u * Math.PI)) * (drop ? 40 : 14 + 22 * bass);
            var wave = hands ? (float)(0.25 * Math.Sin(bp * Math.PI + i)) : 0;
            Neon(cols[i % cols.Length], 3);
            Figure(x, Ground - 15 - s * 0.5 - jump, s, head: 0.12 * Math.Sin(bp * Math.PI + i),
                   arms: hands ? P(-2.7f + wave, 0, 2.7f + wave, 0) : P(-0.3f, 0.4f, 0.3f, -0.4f),
                   legs: jump > 4 ? P(-0.5f, 0.6f, 0.5f, -0.6f) : P(-0.2f, 0, 0.2f, 0));
        }
        if (drop)  // confetti comes down over a drop
        {
            SetShadow(0, null);
            for (var i = 0; i < (int)(46 * Cw / 640); i++)
            {
                var fall = Frac(Hash(i, 22) % 1000 / 1000.0 + bp * (0.1 + Hash(i, 23) % 10 / 80.0));
                var x = Hash(i, 21) % (int)Cw + Math.Sin(bp * 2 + i) * 10;
                _g.Fill = Cg(cols[i % cols.Length]);
                FillRect(Rect(x, fall * Ground, i % 2 == 0 ? 6 : 3, i % 2 == 0 ? 3 : 6));
            }
        }
        if (hands)  // a crowd surfer, carried across during the phrase
        {
            Neon(cols[0], 4);
            SaveGState();
            _canvas.Translate((float)(20 + phraseFrac * (Cw - 40)), (float)(Ground - 232 + 4 * Math.Sin(bp * Math.PI)));
            _canvas.RotateRadians(-MathF.PI / 2);
            Figure(0, 0, 80, arms: P(-2.9f, 0, 2.6f, 0.3f), legs: P((float)(-0.25 + 0.3 * Math.Sin(bp * 2)), 0.3f, 0.25f, 0));
            RestoreGState();
        }
    }

    void Pong(Decision? d, Vector3[] cols, double bp)
    {
        var drop = d?.Section == "drop";
        static double Tri(double v) => 1 - Math.Abs(((v % 2) + 2) % 2 - 1);
        Neon(cols[0], 3);
        _g.Dash = [10, 14];
        StrokeLineSegments(Pt(Cw / 2, 10), Pt(Cw / 2, Ch - 10));
        _g.Dash = null;
        Text(((int)(bp / 4) % 100).ToString(), Pt(Cw / 2 - 70, 70), size: 54, fill: true, mono: true);
        Text(((int)(bp / 7) % 100).ToString(), Pt(Cw / 2 + 70, 70), size: 54, fill: true, mono: true);
        double yL = Ch / 2, yR = Ch / 2;
        double[] offsets = drop ? [0, 0.33, 0.66] : [0];
        for (var i = 0; i < offsets.Length; i++)
        {
            var o = offsets[i];
            double x = 52 + Tri(bp + o) * (Cw - 104), y = 20 + Tri(bp * 0.37 + o * 1.7 + 0.3) * (Ch - 40);
            Neon(cols[i % cols.Length], 3);
            FillRect(Rect(x - 8, y - 8, 16, 16));
            if (x < Cw / 2) yL = y; else yR = y;
        }
        Neon(cols[0], 3);
        FillRect(Rect(28, yL - 40, 12, 80));
        FillRect(Rect(Cw - 40, yR - 40, 12, 80));
    }

    [GeneratedRegex(@"^\d+\s*[-_.]\s*")] private static partial Regex TrackNumber();
    [GeneratedRegex(@"[\[(].*?[\])]")] private static partial Regex Brackets();

    void Words(Hello h, Vector3[] cols, double bp)
    {
        var title = h.Title;
        title = TrackNumber().Replace(title, "");
        title = Brackets().Replace(title, "");
        var ws = title.Replace("_", " ").Split([' ', '-']).Where(w => w.Length > 0).ToArray();
        if (ws.Length == 0) return;
        var beat = (int)Math.Floor(bp);
        var u = bp - Math.Floor(bp);
        var w = ws[Mod(beat, ws.Length)].ToUpperInvariant();
        var c = cols[Mod(beat, cols.Length)];
        // every word comes in its own way: punched in, slid in from a side, dropped from above
        var kind = (int)(Hash(beat, 31) % 4);
        var arrive = 1 - Math.Pow(1 - Math.Min(1, u * 5), 3);
        var size = Math.Min(170, 1000.0 / Math.Max(3, w.Length)) * Math.Min(1.6, Cw / 640);
        double ax = Cw / 2, ay = Ch / 2;
        switch (kind)
        {
            case 1: ax += (Mod(beat, 2) == 0 ? -1 : 1) * Cw * 0.5 * (1 - arrive); break;
            case 2: ay -= Ch * 0.45 * (1 - arrive) - Math.Sin(Math.Min(1, u * 5) * Math.PI) * 10; break;
            default: size *= 1 + 0.25 * Math.Max(0, 1 - u * 4); break;
        }
        // on the bar's first beat the word echoes outwards
        if (Mod(beat, 4) == 0)
        {
            for (var e = 1; e <= 2; e++)
            {
                Flat(Dim(c, 0.45f - 0.15f * e), 2);
                Text(w, Pt(ax, ay), size: size * (1 + e * 0.16 * (0.4 + u)), fill: false);
            }
        }
        // two bars frame it, opening with the beat
        double half = Cw * 0.36 * (0.35 + 0.65 * arrive), by = size * 0.48;
        Flat(Dim(cols[Mod(beat + 1, cols.Length)], 0.6f), 3);
        StrokeLineSegments(Pt(Cw / 2 - half, Ch / 2 - by), Pt(Cw / 2 + half, Ch / 2 - by),
                           Pt(Cw / 2 - half, Ch / 2 + by), Pt(Cw / 2 + half, Ch / 2 + by));
        Neon(c, 5);
        Text(w, Pt(ax, ay), size: size, fill: u < 0.15);
    }

    /// The spectrum's bars (and their falling caps), from the frame's bands.
    void Meter(Frame f, float dt)
    {
        var b = f.Bands;
        var n = _eq.Length;
        var now = (float)Clock.Elapsed.TotalSeconds;
        for (var i = 0; i < n; i++)
        {
            var pos = (float)i / (n - 1) * Math.Max(b.Length - 1, 1);
            var j = (int)pos;
            var k = pos - j;
            var lo = j < b.Length ? b[j] : 0;
            var hi = j + 1 < b.Length ? b[j + 1] : lo;
            var v = MathF.Min(1, MathF.Max(0, (lo + (hi - lo) * k) * (0.85f + 0.3f * MathF.Sin(i * 2.3f + now * 5.5f))));
            _eq[i] = MathF.Max(v, _eq[i] - dt * 2.2f);   // a held level holds (falling only where the music fell)
            _caps[i] = MathF.Max(_eq[i], _caps[i] - dt * 0.6f);
        }
    }

    void Equalizer(Frame f, Vector3[] cols, float dt)
    {
        Meter(f, dt);
        var n = _eq.Length;
        // the bars stand on a line with their reflection under it
        double bw = Cw / n, mirror = Math.Min(64, Ch * 0.16), base_ = Ch - 16 - mirror, top = base_ - 44;
        for (var i = 0; i < n; i++)
        {
            var t = (float)i / (n - 1) * (cols.Length - 1);
            var ci = Math.Min(cols.Length - 1, (int)t);
            var c = Mix(cols[ci], cols[Math.Min(cols.Length - 1, ci + 1)], t - ci);   // the palette runs across the wall
            double h = _eq[i] * top, x = i * bw + 6;
            var segs = (int)Math.Ceiling(h / 16);
            Flat(Dim(c, 0.22f), 2);
            for (var sg = 0; sg < Math.Min(segs, (int)(mirror / 16)); sg++) StrokeRect(Rect(x, base_ + 6 + sg * 16, bw - 12, 10));
            Neon(c, 3);
            for (var sg = 0; sg < segs; sg++)
            {
                if (sg == segs - 1 && segs > 1)   // the top of a bar burns hot
                {
                    Neon(Mix(c, Vector3.One, 0.6f), 3);
                    FillRect(Rect(x, base_ - 12 - sg * 16, bw - 12, 10));
                }
                StrokeRect(Rect(x, base_ - 12 - sg * 16, bw - 12, 10));
            }
            Neon(Mix(c, Vector3.One, 0.35f), 3);
            FillRect(Rect(x, base_ - 10 - _caps[i] * top - 8, bw - 12, 4));
        }
        Flat(Dim(cols[0], 0.5f), 1.5f);
        StrokeLineSegments(Pt(0, base_ + 2), Pt(Cw, base_ + 2));
    }

    void Ambient(Vector3[] cols, float dt)
    {
        _amb += dt * 0.15;
        SetShadow(0, null);
        // slow clouds need no trail: drawn afresh on black each picture, as bright as they settled at 40 a second
        _g.Fill = SKColors.Black;
        FillRect(Rect(0, 0, Cw, Ch));
        float[] stops = [0, 0.25f, 0.5f, 0.75f, 1];
        for (var i = 0; i < cols.Length; i++)
        {
            var c = cols[i];
            var x = Cw / 2.0 + (Cw / 2.0 - 90) * Math.Sin(_amb * (0.7 + i * 0.23) + i * 2);
            var y = Ch / 2.0 + (Ch / 2.0 - 70) * Math.Cos(_amb * (0.5 + i * 0.17) + i);
            var radius = MathF.Max(260, MathF.Max(Cw, Ch) * 0.4f);
            using var shader = SKShader.CreateRadialGradient(Pt(x, y), radius, stops.Select(s => Cg(c, Settled(0.5f * (1 - s)))).ToArray(), stops, SKShaderTileMode.Clamp);
            var p = Paint(false);
            p.Shader = shader;
            p.Color = SKColors.White.WithAlpha((byte)Math.Round(255 * _g.Alpha));
            _canvas.DrawCircle(Pt(x, y), radius, p);
            p.Shader = null;
        }
        // out-of-focus lights drift up through the clouds and breathe with the bass
        var count = Math.Max(8, (int)(14 * Cw * Ch / (W * H)));
        for (var i = 0; i < count; i++)
        {
            var rise = Frac(Hash(i, 41) % 1000 / 1000.0 + _amb * (0.05 + Hash(i, 42) % 10 / 150.0));
            var x = Hash(i, 43) % (int)Cw + Math.Sin(_amb * 0.8 + i) * 18;
            var y = Ch + 40 - rise * (Ch + 80);
            var r = (10 + Hash(i, 44) % 22) * (1 + 0.25 * _sound.X);
            var near = (float)Math.Sin(rise * Math.PI);   // in and out softly at the edges
            var c = Mix(cols[i % cols.Length], Vector3.One, 0.25f);
            _g.Fill = Cg(c, 0.07f * near);
            FillEllipse(Rect(x - r, y - r, r * 2, r * 2));
            _g.Stroke = Cg(c, 0.16f * near); _g.LineWidth = 1.5f;
            StrokeEllipse(Rect(x - r, y - r, r * 2, r * 2));
        }
    }

    // MARK: abstract scenes

    /// A neon tunnel flown through: a ring passes on every beat travelled, the far end sways.
    void Tunnel(Vector3[] cols, float bass)
    {
        const int n = 16;
        var first = (int)Math.Floor(_travel);
        var f = Frac(_travel);
        SKPoint[]? last = null;
        using var rails = new SKPath();
        var rings = new List<(SKPoint[] Pts, double S, int Idx)>();
        (double, double)[] corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)];
        for (var k = 0; k < n; k++)   // from the nearest ring into the depth
        {
            double z = k + 1 - f, s = 1 / (1 + z * 0.55);
            var far = 1 - s;
            var bend = far * far;   // only the far end leaves the middle: the tunnel bends, it doesn't slide
            var cx = Cw / 2 + Math.Sin(_travel * 0.21 + z * 0.18) * Cw * 0.13 * bend;
            var cy = Ch / 2 + Math.Cos(_travel * 0.17 + z * 0.15) * Ch * 0.11 * bend;
            double hw = Cw * 0.86 * s, hh = Ch * 0.86 * s, tilt = Math.Sin(_travel * 0.13 + z * 0.1) * 0.1 * bend;
            var pts = corners.Select(c =>
            {
                double x = c.Item1 * hw, y = c.Item2 * hh;
                return Pt(cx + x * Math.Cos(tilt) - y * Math.Sin(tilt), cy + x * Math.Sin(tilt) + y * Math.Cos(tilt));
            }).ToArray();
            if (last is not null) for (var j = 0; j < 4; j++) { rails.MoveTo(last[j]); rails.LineTo(pts[j]); }
            last = pts;
            rings.Add((pts, s, first + k));
        }
        Flat(Dim(cols[1 % cols.Length], 0.4f), 1.5f);
        StrokePath(rails);
        for (var i = rings.Count - 1; i >= 0; i--)   // far rings first
        {
            var r = rings[i];
            var c = cols[Mod(r.Idx, cols.Length)];
            var hit = Mod(r.Idx, 4) == 0 ? 1 + bass * 0.8 : 1;   // every fourth ring swells with the kick
            using var p = new SKPath();
            p.AddPoly(r.Pts, close: true);
            // the glow is a wide dim stroke under the line: a real glow round sixteen wall-sized rings costs too much
            float k = (float)(0.25 + 1.1 * r.S), width = (float)((1.2 + 5 * r.S) * hit);
            if (r.S > 0.3)
            {
                Flat(Dim(c, k), 1);
                foreach (var (wide, alpha) in new[] { (7.0f, 0.05f), (4.6f, 0.08f), (3.0f, 0.13f), (1.9f, 0.22f) })
                {
                    _g.Stroke = Cg(Dim(c, k), alpha); _g.LineWidth = width * wide;
                    StrokePath(p);
                }
            }
            Flat(Dim(c, k), width);
            StrokePath(p);
        }
    }

    /// Stars streaming out of the middle: a calm drift, streaks at warp speed in a drop.
    void Starfield(Vector3[] cols, bool warp)
    {
        var n = Math.Min(420, (int)(150 * Cw * Ch / (W * H)));
        var reach = Math.Sqrt(Cw * Cw + Ch * Ch) / 2 * 1.05;
        var tiers = Enumerable.Range(0, 3 * cols.Length).Select(_ => new List<SKPoint>()).ToArray();
        var bright = new List<(SKPoint P, double R, Vector3 C)>();
        for (var i = 0; i < n; i++)
        {
            double a = Hash(i, 11) % 6283 / 1000.0, speed = 0.3 + Hash(i, 12) % 100 / 140.0;
            var u = Frac(Hash(i, 13) % 1000 / 1000.0 + _travel * speed * 0.22);
            double r1 = 6 + u * u * reach, streak = (warp ? 0.22 : 0.035) * (0.3 + u), r0 = r1 * (1 - streak);
            var p1 = Pt(Cw / 2 + Math.Cos(a) * r1, Ch / 2 + Math.Sin(a) * r1);
            var p0 = Pt(Cw / 2 + Math.Cos(a) * r0, Ch / 2 + Math.Sin(a) * r0);
            var tier = u < 0.35 ? 0 : u < 0.7 ? 1 : 2;
            tiers[tier * cols.Length + i % cols.Length].AddRange([p0, p1]);
            if (i % 9 == 0 && u > 0.45) bright.Add((p1, 2 + 5 * u, Mix(cols[i % cols.Length], Vector3.One, 0.5f)));
        }
        float[] dims = [0.35f, 0.7f, 1], widths = [1, 1.6f, 2.4f];
        for (var tier = 0; tier < 3; tier++)
        {
            for (var ci = 0; ci < cols.Length; ci++)
            {
                var pts = tiers[tier * cols.Length + ci];
                if (pts.Count == 0) continue;
                Flat(Dim(Mix(cols[ci], Vector3.One, 0.35f), dims[tier]), widths[tier]);
                StrokeLineSegments([.. pts]);
            }
        }
        foreach (var (p, r, c) in bright)   // a few near stars flare
        {
            Neon(c, 1.5f);
            StrokeLineSegments(Pt(p.X - r, p.Y), Pt(p.X + r, p.Y), Pt(p.X, p.Y - r), Pt(p.X, p.Y + r));
        }
    }

    /// An oscilloscope: one line each for the bass, the mids and the highs, over a faint graticule.
    void Scope(Vector3[] cols, double bp)
    {
        Flat(Dim(cols[1 % cols.Length], 0.16f), 1);
        var grid = new List<SKPoint>();
        double cell = Ch / 6.0;
        for (var gx = Cw / 2 - Math.Floor(Cw / 2 / cell) * cell; gx < Cw; gx += cell) { grid.Add(Pt(gx, 0)); grid.Add(Pt(gx, Ch)); }
        for (var gy = Ch / 2 - Math.Floor(Ch / 2 / cell) * cell; gy < Ch; gy += cell) { grid.Add(Pt(0, gy)); grid.Add(Pt(Cw, gy)); }
        StrokeLineSegments([.. grid]);
        float[] levels = [_sound.X, _sound.Y, _sound.Z], widths = [5, 3.5f, 2.5f];
        double[] waves = [1.5, 4.0, 9.0], runs = [1.0, 2.0, 4.0];
        for (var r = 0; r < 3; r++)
        {
            double y0 = Ch * (0.5 + (r - 1) * 0.25), amp = Ch * 0.17 * (0.12 + Math.Min(1, levels[r] * 1.3));
            var cycles = waves[r] * Cw / W;
            using var p = new SKPath();
            for (double x = 0; x <= Cw; x += 5)
            {
                double t = x / Cw, env = Math.Sin(t * Math.PI);   // pinned at both ends
                var v = 0.7 * Math.Sin(2 * Math.PI * cycles * t - bp * Math.PI * runs[r])
                      + 0.3 * Math.Sin(2 * Math.PI * cycles * 2.7 * t + bp * Math.PI * 1.3 + r);
                var pt = Pt(x, y0 + amp * env * v);
                if (x == 0) p.MoveTo(pt); else p.LineTo(pt);
            }
            Neon(cols[r % cols.Length], widths[r]);
            StrokePath(p);
        }
    }

    /// Nested triangles, squares, hexagons and circles turning against each other; one of them kicks out every beat.
    void Shapes(Vector3[] cols, double bp, bool drop)
    {
        var beat = (int)Math.Floor(bp);
        var u = bp - Math.Floor(bp);
        var bar = beat / 4;
        var wide = Cw >= Ch;
        double longSide = Math.Max(Cw, Ch), shortSide = Math.Min(Cw, Ch);
        var groups = Math.Max(1, (int)Math.Round(longSide / shortSide / 1.6, MidpointRounding.AwayFromZero));
        int[] kinds = [3, 4, 6, 0];
        for (var gi = 0; gi < groups; gi++)
        {
            var along = longSide * (gi + 0.5) / groups;
            double x = wide ? along : Cw / 2, y = wide ? Ch / 2 : along;
            var radius = Math.Min(longSide / groups, shortSide) * 0.44;
            for (var j = 0; j < (drop ? 5 : 4); j++)
            {
                var sides = kinds[Mod(j + Hash(bar, 4) + gi, 4)];
                var kick = Mod(beat + gi, 4) == j % 4 ? Math.Exp(-u * 4) : 0;
                var r = radius * (1 - j * 0.19) * (1 + kick * 0.13);
                var turn = _travel * Math.PI / 8 * (j % 2 == 0 ? 1 : -1) * (1 + j * 0.25) + j + gi;
                Neon(cols[(j + gi) % cols.Length], (float)(4 - j * 0.5 + kick * 4));
                using var p = Polygon(x, y, r, sides, turn);
                StrokePath(p);
            }
            Neon(cols[gi % cols.Length], 3);
            var dot = 5 + Math.Exp(-u * 5) * 9;
            FillEllipse(Rect(x - dot, y - dot, dot * 2, dot * 2));
        }
    }

    // MARK: techno and club

    /// Hard vertical bars, a barcode that steps along with the beat; a scanner crosses once a bar.
    void Lines(Vector3[] cols, double bp, float bass, bool drop)
    {
        var n = Math.Max(12, (int)MathF.Round(28 * Cw / W, MidpointRounding.AwayFromZero));
        double bw = Cw / (double)n;
        var beat = (int)Math.Floor(bp);
        var u = bp - Math.Floor(bp);
        var bar = beat / 4;
        var kick = (float)Math.Exp(-u * 5);
        var shift = (int)Math.Floor(_travel * 2);   // the code moves two bars' width a beat
        SetShadow(0, null);
        for (var i = 0; i < n; i++)
        {
            var k = i + shift;
            if (Hash(k, 51 + Mod(bar, 4)) % 5 >= (drop ? 3 : 2)) continue;
            bool thin = Hash(k, 52) % 3 == 0, accent = Hash(k, 53) % 6 == 0;
            // a band that breathes across the wall; in a drop the bars stand wall-high
            var wave = 0.5 + 0.5 * Math.Sin(i * 0.45 - bp * Math.PI / 2);
            var h = drop ? Ch : Ch * (0.22 + 0.5 * wave + 0.25 * bass);
            var c = accent ? cols[0] : Mix(cols[1 % cols.Length], Vector3.One, 0.75f);
            _g.Fill = Cg(Dim(c, 0.4f + 0.6f * kick));
            var w = thin ? Math.Max(2, bw * 0.22) : bw * 0.82;
            FillRect(Rect(i * bw + (bw - w) / 2, (Ch - h) / 2, w, h));
        }
        // two cuts through the bars, and the scanner
        _g.Fill = SKColors.Black;
        foreach (var y in new[] { Ch * 0.36, Ch * 0.64 }) FillRect(Rect(0, y - 2.5, Cw, 5));
        var sx = Frac(bp / 4) * Cw;
        Neon(cols[0], 3);
        _g.Hard = true;
        StrokeLineSegments(Pt(sx, 0), Pt(sx, Ch));
    }

    /// A landscape of ridges coming on, line behind line, rising with the music.
    void Grid(Vector3[] cols)
    {
        const int rows = 16, steps = 56;
        double horizon = Ch * 0.14, f = Frac(_travel * 0.5);
        var first = (int)Math.Floor(_travel * 0.5);
        var loud = 0.22 + 0.7 * _sound.X + 0.5 * _sound.Y;
        SetShadow(0, null);
        for (var k = rows - 1; k >= 0; k--)   // the far ridges first: the near ones hide them
        {
            double z = (k + 1 - f) * 1.35, s = 1 / (0.4 + z * 0.3);   // near 1.2 .. far 0.15
            var near = Math.Min(1, s / 1.4);
            var y0 = horizon + (Ch * 1.08 - horizon) * near;
            double half = Cw * (0.42 + 0.5 * near), amp = Ch * 0.4 * Math.Pow(near, 0.55) * loud;
            var row = first + k;
            double p1 = Hash(row, 81) % 628 / 100.0, p2 = Hash(row, 82) % 628 / 100.0, p3 = Hash(row, 83) % 628 / 100.0;
            var pts = new SKPoint[steps + 1];
            for (var i = 0; i <= steps; i++)
            {
                double t = i / (double)steps, env = Math.Pow(Math.Sin(t * Math.PI), 2.4);   // the ridge stands in the middle
                var v = Math.Abs(0.5 * Math.Sin(t * 11 + p1) + 0.32 * Math.Sin(t * 27 + p2) + 0.18 * Math.Sin(t * 53 + p3));
                pts[i] = Pt(Cw / 2 + (t * 2 - 1) * half, y0 - amp * env * v);
            }
            using (var body = new SKPath())
            {
                body.AddPoly(pts, close: false);
                body.LineTo(Pt(pts[^1].X, Ch + 4)); body.LineTo(Pt(pts[0].X, Ch + 4)); body.Close();
                _g.Fill = SKColors.Black;
                var fill = Paint(false);
                fill.IsAntialias = false;   // (the line drawn over its edge is the smooth one)
                _canvas.DrawPath(body, fill);
                fill.IsAntialias = true;
            }
            var c = Mix(cols[Mod(row, cols.Length)], Vector3.One, 0.25f);
            using var line = new SKPath();
            line.AddPoly(pts, close: false);
            var shade = Dim(c, (float)(0.2 + 0.8 * near));
            var width = (float)(1 + 1.6 * near);
            if (k < 3) SoftGlow(line, shade, width);
            Sharp(shade, width);
            StrokePath(line);
        }
    }

    // MARK: the harder styles

    static readonly Dictionary<string, (double X, double Y)> WolfPoints = new()
    {
        ["E"] = (0.62, -1.18), ["Eo"] = (0.84, -0.42), ["En"] = (0.52, -0.62), ["Ei"] = (0.26, -0.66), ["T"] = (0, -0.56), ["B"] = (0, -0.2),
        ["Bo"] = (0.5, -0.3), ["Tm"] = (0.88, -0.08), ["C1"] = (1.02, 0.34), ["C2"] = (0.7, 0.36), ["J"] = (0.5, 0.74), ["Yi"] = (0.15, -0.06),
        ["Yo"] = (0.56, -0.22), ["Yb"] = (0.38, 0.02), ["Nb"] = (0.13, 0.32), ["M"] = (0.3, 0.56), ["N"] = (0.13, 0.64), ["Nt"] = (0, 0.8),
        ["Mc"] = (0.25, 0.82), ["Ch"] = (0, 1.04), ["Nc"] = (0, 0.3),
    };

    /// The right half of the head in facets (mirrored for the left); the last one is the lower jaw, which opens.
    static readonly string[][] WolfFacets =
    [
        ["E", "Eo", "En"], ["E", "En", "Ei"], ["T", "Ei", "Bo", "B"], ["Ei", "En", "Eo", "Tm", "Bo"], ["B", "Bo", "Yo", "Yi"],
        ["Yo", "Bo", "Tm"], ["Yo", "Tm", "C1", "C2"], ["Yo", "C2", "Yb"], ["B", "Yi", "Nb", "Nc"], ["Yi", "Yb", "M", "Nb"],
        ["Yb", "C2", "J", "M"], ["Nb", "M", "N"], ["Nc", "Nb", "N", "Nt"], ["N", "M", "Mc", "Nt"], ["M", "J", "Mc"],
        ["Nt", "Mc", "Ch"],
    ];

    /// A wolf's head in hard facets: its eyes burn with the bass, facets catch light on the kick, in a drop it bares
    /// its teeth. A wide wall shows a pack.
    void Wolf(Vector3[] cols, double bp, float bass, bool drop)
    {
        var beat = (int)Math.Floor(bp);
        var u = bp - Math.Floor(bp);
        var kick = (float)Math.Exp(-u * 4);
        var open = drop ? Math.Min(1, 0.25 + bass) * (0.55 + 0.45 * kick) : Math.Max(0, bass - 0.75) * 1.2;
        var c1 = cols[1 % cols.Length];

        void Head(double x0, double y0, double size, float lightK, int salt)
        {
            var s = size * (1 + 0.035 * bass);
            SKPoint P(string name, double side)
            {
                var (x, y) = WolfPoints[name];
                if (name == "Ch") y += 0.24 * open; else if (name == "Mc") y += 0.06 * open;
                return Pt(x0 + side * x * s, y0 + y * s);
            }
            // a mane of spikes behind the head, thrown out on the kick
            Sharp(Dim(c1, 0.5f * lightK), 1.5f);
            using (var mane = new SKPath())
            {
                const int spikes = 18;
                for (var i = 0; i < spikes; i++)
                {
                    var a = i / (double)spikes * 2 * Math.PI + _travel * 0.05;
                    if (Math.Sin(a) >= 0.55) continue;   // none under the chin
                    var len = 1.34 + 0.2 * (Hash(i + salt, 73) % 100) / 100.0 + 0.3 * kick;
                    var tip = Pt(x0 + Math.Cos(a) * len * s, y0 - 0.1 * s + Math.Sin(a) * len * s);
                    foreach (var da in new[] { -0.07, 0.07 })
                    {
                        mane.MoveTo(Pt(x0 + Math.Cos(a + da) * 1.02 * s, y0 - 0.1 * s + Math.Sin(a + da) * 1.02 * s));
                        mane.LineTo(tip);
                    }
                }
                StrokePath(mane);
            }
            // the facets: each its own shade, the left side in the light, some lit by the kick
            using (var edges = new SKPath())
            {
                foreach (var side in new[] { 1.0, -1.0 })
                {
                    for (var fi = 0; fi < WolfFacets.Length; fi++)
                    {
                        using var p = PathOf(WolfFacets[fi].Select(name => P(name, side)).ToArray());
                        var shade = 0.05f + 0.15f * (Hash(fi + salt, side > 0 ? 71 : 74) % 100) / 100f;
                        if (side < 0) shade *= 1.7f;
                        if (Hash(fi + beat * 17 + (side > 0 ? 0 : 50), 72) % 4 == 0) shade += 0.4f * kick;
                        SetShadow(0, null);
                        _g.Fill = Cg(Dim(Mix(c1, Vector3.One, 0.2f), shade * lightK));
                        FillPath(p);
                        edges.AddPath(p);
                    }
                }
                Sharp(Dim(cols[0], 0.85f * lightK), 1.4f);
                StrokePath(edges);
            }
            // the open mouth is dark, with fangs
            if (open > 0.12)
            {
                _g.Fill = SKColors.Black;
                FillPoly(P("Mc", 1), P("Nt", 1), P("Mc", -1), Pt(x0, y0 + (0.8 + 0.2 * open) * s));
                Sharp(Dim(Vector3.One, lightK), 1.2f);
                _g.Fill = Cg(Dim(Vector3.One, 0.85f * lightK));
                foreach (var side in new[] { 1.0, -1.0 })
                    foreach (var (fx, len) in new[] { (0.1, 0.17), (0.2, 0.09) })
                        FillPoly(Pt(x0 + side * (fx - 0.035) * s, y0 + 0.81 * s), Pt(x0 + side * (fx + 0.035) * s, y0 + 0.82 * s),
                                 Pt(x0 + side * fx * s, y0 + (0.82 + len * Math.Min(1, open * 1.6)) * s));
            }
            // the nose, and the eyes: they burn
            SetShadow(0, null);
            _g.Fill = Cg(Dim(cols[0], 0.5f * lightK));
            FillPoly(P("N", 1), P("Nt", 1), P("N", -1));
            var burn = Mix(cols[0], Vector3.One, 0.35f + 0.65f * MathF.Max(bass, kick));
            Neon(Dim(burn, lightK), 2.5f + 2.5f * kick);
            _g.Hard = true;
            foreach (var side in new[] { 1.0, -1.0 })
            {
                using var eye = PathOf(P("Yi", side), P("Yo", side), P("Yb", side));
                FillPath(eye);
                StrokePath(eye);
            }
        }

        double size0 = Math.Min(Cw, Ch) * 0.36, cy = Ch / 2 + size0 * 0.06;
        if (Cw / Ch > 2.4)   // a pack: two more behind, smaller and darker
        {
            Head(Cw / 2 - Cw * 0.3, cy + size0 * 0.12, size0 * 0.68, 0.55f, 5);
            Head(Cw / 2 + Cw * 0.3, cy + size0 * 0.12, size0 * 0.68, 0.55f, 9);
        }
        Head(Cw / 2, cy, size0, 1, 0);
    }

    /// Claws rip across the wall, one slash every other beat (every beat in a drop); the scars stay a while.
    void Claws(Vector3[] cols, double bp, bool drop)
    {
        var step = drop ? 1.0 : 2.0;
        var hit = (int)Math.Floor(bp / step);
        var u = bp - hit * step;
        double small = Math.Min(Cw, Ch), longest = Math.Min(Math.Max(Cw, Ch) * 0.8, small * 1.9);
        var c1 = cols[1 % cols.Length];
        for (var age = 2; age >= 0; age--)   // the oldest scar first
        {
            var h = hit - age;
            var since = u + age * step;
            var reveal = age == 0 ? Math.Min(1, u / 0.14) : 1;
            var heat = (float)Math.Exp(-since * (drop ? 1.5 : 0.9));
            double dir = Hash(h, 61) % 2 == 0 ? 1 : -1;
            double cx = Cw * (0.3 + 0.4 * (Hash(h, 62) % 100) / 100.0), cy = Ch * (0.4 + 0.2 * (Hash(h, 63) % 100) / 100.0);
            var a = 0.85 + 0.35 * (Hash(h, 64) % 100) / 100.0;   // from the vertical
            double dx = dir * Math.Sin(a), dy = Math.Cos(a), nx = dy, ny = -dx;
            var count = 3 + (int)(Hash(h, 65) % 2);
            for (var c = 0; c < count; c++)
            {
                var off = (c - (count - 1) / 2.0) * small * 0.13;
                double len = longest * (c == 0 || c == count - 1 ? 0.78 : 1), wide = small * 0.028;
                double sx = cx + nx * off - dx * len / 2, sy = cy + ny * off - dy * len / 2;
                double ex = sx + dx * len * reveal, ey = sy + dy * len * reveal;
                double mx = sx + (ex - sx) * 0.4, my = sy + (ey - sy) * 0.4;
                using var blade = PathOf(Pt(sx, sy), Pt(mx + nx * wide, my + ny * wide), Pt(ex, ey), Pt(mx - nx * wide, my - ny * wide));
                if (age == 0)
                {
                    var hot = Mix(cols[0], Vector3.One, heat);
                    SoftGlow(blade, hot, 2);
                    Sharp(hot, 1.5f);
                    _g.Fill = Cg(hot);
                }
                else
                {
                    Sharp(Dim(cols[0], 0.18f + 0.6f * heat), 1.2f);
                    _g.Fill = Cg(Dim(cols[0], 0.08f + 0.3f * heat));
                }
                FillPath(blade);
                StrokePath(blade);
            }
            if (age != 0) continue;
            // shards fly off the fresh slash
            Sharp(Dim(Mix(c1, Vector3.One, 0.5f), heat), 1);
            for (var i = 0; i < 16; i++)
            {
                double along = Hash(h * 16 + i, 66) % 100 / 100.0 - 0.5, sideways = i % 2 == 0 ? 1 : -1;
                var fly = u * small * (0.25 + 0.5 * (Hash(h * 16 + i, 67) % 100) / 100.0);
                double ox = cx + dx * longest * along + nx * sideways * (small * 0.1 + fly);
                double oy = cy + dy * longest * along + ny * sideways * (small * 0.1 + fly);
                using var shard = Polygon(ox, oy, 3 + Hash(i, 68) % 5, 3, u * 5 + i);
                FillPath(shard);
            }
        }
    }

    /// Jaws: rows of spikes from the top and the bottom, as long as the music is loud there; they bite on the kick.
    void Spikes(Frame f, Vector3[] cols, double bp, float bass, float dt)
    {
        Meter(f, dt);
        var n = _eq.Length;
        double tw = Cw / (double)n, u = bp - Math.Floor(bp);
        var kick = (float)Math.Exp(-u * 5);
        var bite = Ch * 0.07 * kick * (0.4 + bass);
        for (var side = 0; side < 2; side++)
        {
            double edge = side == 0 ? 0 : Ch, dir = side == 0 ? 1 : -1;
            var pts = new List<SKPoint> { Pt(-tw, edge) };
            for (var i = -1; i <= n; i++)
            {
                var j = Math.Min(n - 1, Math.Max(0, side == 0 ? i : n - 1 - i));
                var len = Ch * (0.09 + 0.33 * _eq[j]) + bite;
                var x0 = i * tw + (side == 1 ? tw / 2 : 0);   // the rows interlock
                pts.Add(Pt(x0, edge)); pts.Add(Pt(x0 + tw / 2, edge + dir * len));
            }
            pts.Add(Pt(Cw + tw * 2, edge));
            using var jaw = PathOf([.. pts]);
            var c = cols[side % cols.Length];
            SetShadow(0, null);
            _g.Fill = Cg(Dim(c, 0.14f + 0.2f * kick));
            FillPath(jaw);
            Neon(Mix(c, Vector3.One, 0.5f * kick), 2);
            _g.Hard = true;
            StrokePath(jaw);
        }
        // between the jaws a cut of light on the kick
        Sharp(Dim(Mix(cols[0], Vector3.One, 0.7f), kick), 1 + 5 * kick);
        StrokeLineSegments(Pt(0, Ch / 2), Pt(Cw, Ch / 2));
    }

    /// 3-2-1 into the drop the engine picked (hello.countdown: once or twice a night), then DROP!
    bool Countdown(Frame f, Decision? d, Hello h, Vector3[] cols)
    {
        var spb = 60 / Math.Max(h.Bpm, 60);
        string? label = null;
        var u = 0.0;
        if (h.Countdown == f.Phrase + 1 && f.Phrase + 1 >= 0 && f.Phrase + 1 < h.Plan.Count && h.Plan[f.Phrase + 1].Section == "drop" && d?.Section != "drop")
        {
            var left = (h.Plan[f.Phrase + 1].Start - f.T) / spb;
            if (left > 0 && left <= 4) { label = ((int)Math.Ceiling(left)).ToString(); u = 1 - (left % 1 == 0 ? 1 : left % 1); }
        }
        if (h.Countdown == f.Phrase && d is { Section: "drop" } && f.T - d.Start < spb * 2) { label = "DROP!"; u = (f.T - d.Start) / (spb * 2); }
        if (label is null) return false;
        SetShadow(0, null);
        _g.Fill = new SKColor(0, 0, 0, (byte)Math.Round(0.85 * 255));
        FillRect(Rect(0, 0, Cw, Ch));
        Neon(cols[0], 7);
        var fit = Math.Min(1, Cw / 520.0);   // DROP! fits a narrow wall too
        Text(label, Pt(Cw / 2, Ch / 2 + 5), size: (label.Length > 1 ? 150 : 230 * (1.3 - 0.3 * u)) * fit, fill: false);
        return true;
    }

    static SKTypeface? _display, _mono;

    /// The Mac's HelveticaNeue-CondensedBlack and Menlo-Bold, or their nearest on Windows.
    internal static SKTypeface Typeface(bool mono)
    {
        static SKTypeface? Find(string family, SKFontStyleWeight weight, SKFontStyleWidth width)
        {
            var t = SKTypeface.FromFamilyName(family, weight, width, SKFontStyleSlant.Upright);
            if (t is not null && t.FamilyName.Equals(family, StringComparison.OrdinalIgnoreCase)) return t;
            t?.Dispose();
            return null;
        }
        if (mono)
            return _mono ??= Find("Consolas", SKFontStyleWeight.Bold, SKFontStyleWidth.Normal) ?? Find("Menlo", SKFontStyleWeight.Bold, SKFontStyleWidth.Normal)
                ?? SKTypeface.FromFamilyName("Courier New", SKFontStyle.Bold) ?? SKTypeface.Default;
        return _display ??= Find("Helvetica Neue", SKFontStyleWeight.Black, SKFontStyleWidth.Condensed)
            ?? Find("Bahnschrift", SKFontStyleWeight.Bold, SKFontStyleWidth.Condensed) ?? Find("Impact", SKFontStyleWeight.Normal, SKFontStyleWidth.Normal)
            ?? SKTypeface.FromFamilyName("Arial", SKFontStyleWeight.Black, SKFontStyleWidth.Normal, SKFontStyleSlant.Upright) ?? SKTypeface.Default;
    }

    /// Centred outlined (or filled) text in the current colour.
    void Text(string s, SKPoint p, double size, bool fill, bool mono = false)
    {
        using var font = new SKFont(Typeface(mono), (float)size);
        font.MeasureText(s, out var bounds);   // the glyphs' own bounds (CTLine's useGlyphPathBounds)
        var paint = Paint(true);
        paint.PathEffect?.Dispose();
        paint.PathEffect = null;
        paint.Style = fill ? SKPaintStyle.StrokeAndFill : SKPaintStyle.Stroke;
        _canvas.DrawText(s, p.X - bounds.MidX, p.Y - bounds.MidY, SKTextAlign.Left, font, paint);
        paint.Style = SKPaintStyle.Stroke;
    }
}
