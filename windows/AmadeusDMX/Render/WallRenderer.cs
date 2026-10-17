// The LED wall's picture (the native version of web/js/screen.js; mac/Sources/AmadeusDMX/Render/WallRenderer.swift).
// The director picks a mode per phrase (decision.screen): off | ambient | figure | words | equalizer | psychedelic.
// Figures are playful neon outlines on the beat: a runner, a dancer, a jumping crowd, pong. Into a drop the wall
// counts 3-2-1 and shouts DROP!. Psychedelic is drawn by a shader on the wall itself; everything else here, with
// SkiaSharp (the Mac draws with Core Graphics), into a 640×360 BGRA picture that the renderer puts on the wall.
//
// Core Graphics → Skia: the CG context is flipped to y-down like a canvas; Skia is y-down already. CG's per-draw
// shadow (the neon glow) is a drop-shadow image filter with sigma = blur / 2; setAlpha multiplies every paint.
using System.Diagnostics;
using System.Numerics;
using System.Text.RegularExpressions;
using SkiaSharp;

namespace AmadeusDMX;

public enum WallScene { Auto, Off, Ambient, Runner, Dancer, Crowd, Pong, Words, Equalizer, Psychedelic }

public static class WallScenes
{
    public static readonly WallScene[] AllCases = Enum.GetValues<WallScene>();
    public static readonly WallScene[] Figures = [WallScene.Runner, WallScene.Dancer, WallScene.Crowd, WallScene.Pong];

    public static string RawValue(this WallScene s) => s.ToString().ToLowerInvariant();
    public static WallScene? FromRawValue(string? raw) => AllCases.Cast<WallScene?>().FirstOrDefault(s => s!.Value.RawValue() == raw);
    public static string Title(this WallScene s) => s == WallScene.Auto ? "Director's Choice" : s.ToString();

    public static string Symbol(this WallScene s) => s switch
    {
        WallScene.Auto => "wand.and.stars",
        WallScene.Off => "rectangle.slash",
        WallScene.Ambient => "cloud.fog",
        WallScene.Runner => "figure.run",
        WallScene.Dancer => "figure.dance",
        WallScene.Crowd => "person.3",
        WallScene.Pong => "gamecontroller",
        WallScene.Words => "textformat.size",
        WallScene.Equalizer => "chart.bar",
        _ => "circle.hexagongrid",
    };
}

public readonly record struct WallOutput(float Level, bool Psychedelic, Vector3[] Palette, Vector4 Bands, WallScene Scene);

public sealed partial class WallRenderer : IDisposable
{
    public const int W = 640, H = 360;
    readonly SKBitmap _bitmap;
    readonly SKCanvas _canvas;
    public WallScene Force { get; set; } = WallScene.Auto;

    (string Mode, WallScene Scene) _cur = ("off", WallScene.Off);
    float _fade;
    float _level;
    readonly float[] _eq = new float[16], _caps = new float[16];
    double _amb;
    float[][] _fromPose = Moves["down"];
    int _lastBeat = -1;
    static readonly Stopwatch Clock = Stopwatch.StartNew();

    public WallRenderer()
    {
        // premultiplied BGRA, like the Mac's premultipliedFirst + byteOrder32Little (the texture is B8G8R8A8_UNORM)
        _bitmap = new SKBitmap(new SKImageInfo(W, H, SKColorType.Bgra8888, SKAlphaType.Premul));
        _canvas = new SKCanvas(_bitmap);
        _canvas.Clear(SKColors.Black);
    }

    public void Dispose()
    {
        _canvas.Dispose();
        _bitmap.Dispose();
        _fill.Dispose(); _stroke.Dispose();
    }

    /// The picture: W×H BGRA (premultiplied), RowBytes per row.
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

    (string, WallScene) Wanted(Frame f, Decision? d)
    {
        if (Force != WallScene.Auto)
            return (WallScenes.Figures.Contains(Force) ? "figure" : Force.RawValue(), Force);
        var mode = d?.Screen ?? "";
        if (mode.Length == 0)
        {
            var opts = Rules.GetValueOrDefault(d?.Section ?? "") ?? ["off"];
            mode = opts[Mod(Hash(f.Phrase, 2), opts.Length)];
        }
        var scene = mode == "figure" ? WallScenes.Figures[Mod(Hash(f.Phrase, 9), WallScenes.Figures.Length)]
            : WallScenes.FromRawValue(mode) ?? WallScene.Off;
        return (mode, scene);
    }

    public WallOutput Update(Frame f, Hello h, float dt)
    {
        var d = f.Phrase >= 0 && f.Phrase < h.Plan.Count ? h.Plan[f.Phrase] : null;
        var want = Wanted(f, d);
        // the show arc's LED wall knob (live mode): dimmer, below half only calm colour, at zero off
        var wall = Force == WallScene.Auto ? (float)(f.Arc is { On: true } arc && arc.Values.TryGetValue("screen", out var sv) ? sv : 1) : 1;
        if (wall < 0.03f) want = ("off", WallScene.Off);
        else if (wall < 0.5f && want.Item1 != "off") want = ("ambient", WallScene.Ambient);
        var next = f.Phrase + 1 >= 0 && f.Phrase + 1 < h.Plan.Count ? h.Plan[f.Phrase + 1] : null;
        var spb = 60 / Math.Max(h.Bpm, 60);
        var nextDrop = next?.Section == "drop" && d?.Section != "drop";
        var beatsLeft = nextDrop ? (next!.Start - f.T) / spb : 99;
        if (want.Item1 == "off" && beatsLeft <= 4.5 && Force == WallScene.Auto && wall >= 0.5f) want = ("words", WallScene.Words);  // a dark wall counts in
        var shout = wall >= 0.5f && d?.Section == "drop" && _cur.Mode != "off" && _cur.Mode != "psychedelic" && (f.T - d.Start) / spb < 2;
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
        float target;
        if (_cur.Mode == "psychedelic")
        {
            var fx = f.Fx;
            var mean = fx.Length == 0 ? 0 : fx.Sum(v => MathF.Min(1, (v.Length > 0 ? v[0] : 0) + (v.Length > 4 ? v[4] : 0))) / fx.Length;
            target = mean < 0.01f ? 0.05f : MathF.Min(1, 0.3f + 1.4f * mean);
        }
        else
        {
            Draw(f, d, h, cols, bp, bass, dt);
            target = _cur.Mode == "off" ? 0 : _cur.Mode == "ambient" ? 0.4f : 0.95f;
        }
        _level += (target * MathF.Min(1, wall * 2) * _fade - _level) * MathF.Min(1, dt * 10);
        return new WallOutput(_level, _cur.Mode == "psychedelic", Palettes.Colors(d?.Palette), bandsV, _cur.Scene);
    }

    // MARK: drawing state (Core Graphics' graphics state, the parts the scenes use)

    struct GState
    {
        public SKColor Stroke, Fill, ShadowColor;
        public float LineWidth, Alpha, ShadowBlur;
        public float[]? Dash;
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
        _g.Stroke = Cg(c); _g.Fill = Cg(c); _g.LineWidth = width;
        SetShadow(width * 2.2f, Cg(c));
    }

    void Draw(Frame f, Decision? d, Hello h, Vector3[] cols, double bp, float bass, float dt)
    {
        SaveGState();
        SetShadow(0, null);
        // a short trail behind moving lines: how much of the last picture fades is set per 1/60 s, so the trail
        // is as short at any drawing rate (a fixed share per picture ghosted when the wall was drawn less often)
        var fadeShare = _cur.Scene == WallScene.Words ? 0.8 : 0.45;
        _g.Fill = new SKColor(0, 0, 0, (byte)Math.Clamp(Math.Round(255 * (1 - Math.Pow(1 - fadeShare, Math.Max(dt, 1.0 / 240) * 60))), 0, 255));
        FillRect(Rect(0, 0, W, H));
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
            }
        }
        RestoreGState();
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
        double s = 150, gy = 300;
        var drop = d?.Section == "drop";
        var speed = drop ? 90.0 : 60.0;
        var scroll = bp * speed;
        Neon(cols[1 % cols.Length], 2);
        SetAlpha(0.45f);
        using (var sky = new SKPath())
        {
            var off = scroll * 0.3;
            for (var i = -1; i < 12; i++)
            {
                var x = i * 70 - off % 70;
                var hh = 40 + Hash(i + (int)(off / 70)) % 90;
                sky.MoveTo(Pt(x, gy)); sky.LineTo(Pt(x, gy - hh));
                sky.LineTo(Pt(x + 52, gy - hh)); sky.LineTo(Pt(x + 52, gy));
            }
            StrokePath(sky);
        }
        SetAlpha(1);
        Neon(cols[0], 3);
        StrokeLineSegments(Pt(0, gy), Pt(640, gy));
        // a hurdle every bar, arriving at the runner on the downbeat
        var bar = bp / 4;
        var hx = 230 + (Math.Ceiling(bar) - bar) * 4 * speed;
        StrokeLineSegments(Pt(hx, gy), Pt(hx, gy - 38), Pt(hx - 14, gy - 38), Pt(hx + 14, gy - 38));
        var fromDown = (bp + 0.5) % 4 - 0.5;
        var jump = Math.Abs(fromDown) < 0.5 ? Math.Cos(fromDown * Math.PI) : 0;
        var w = (float)(bp * Math.PI);
        var y = gy - s * 0.5 - Math.Abs(MathF.Cos(w)) * 6 - jump * 70;
        Neon(cols[0], 5);
        (double hx2, double hy2, double r) = jump > 0.05
            ? Figure(230, y, s, lean: 0.35, arms: P(-2.4f, 0.3f, 2.6f, -0.2f), legs: P(1.3f, -1.9f, -0.4f, -1.2f))
            : Figure(230, y, s, lean: drop ? 0.35 : 0.22,
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
                pts.Add(Pt(150 - i * 12, ly)); pts.Add(Pt(110 - i * 20, ly));
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
        for (var i = 0; i < 8; i++)  // the dance floor lights up with the beat
        {
            var on = Hash(i + beat * 8, 1) % 3 == 0;
            Neon(cols[i % cols.Length], 2);
            SetAlpha(on ? 0.55f : 0.12f);
            double x0 = 320 + (i - 4) * 70, x1 = x0 + 70;
            using var p = new SKPath();
            p.MoveTo(Pt(x0 + (x0 - 320) * 0.4, 345)); p.LineTo(Pt(x1 + (x1 - 320) * 0.4, 345));
            p.LineTo(Pt(x1, 300)); p.LineTo(Pt(x0, 300)); p.Close();
            StrokePath(p);
        }
        SetAlpha(1);
        Neon(cols[0], 6);
        Figure(320, 205 - dip * 8 - hop, 190, head: 0.15 * Math.Sin(bp * Math.PI), arms: arms, legs: legs);
        if (hop > 0) { Neon(cols[1 % cols.Length], 4); Text("!", Pt(410, 60 - hop * 0.3), size: 46, fill: true); }
    }

    void Crowd(Decision? d, Vector3[] cols, double bp, float bass, double phraseFrac)
    {
        const int n = 11;
        var drop = d?.Section == "drop";
        var hands = drop || (d?.Intensity ?? 1) >= 2;
        for (var i = 0; i < n; i++)
        {
            double x = 40 + i * 560.0 / (n - 1), s = 105 + Hash(i, 5) % 25;
            var u = drop ? bp % 1 : (bp - i * 0.12) % 1;
            var jump = Math.Max(0, Math.Sin(u * Math.PI)) * (drop ? 40 : 14 + 22 * bass);
            var wave = hands ? (float)(0.25 * Math.Sin(bp * Math.PI + i)) : 0;
            Neon(cols[i % cols.Length], 3);
            Figure(x, 345 - s * 0.5 - jump, s,
                   arms: hands ? P(-2.7f + wave, 0, 2.7f + wave, 0) : P(-0.3f, 0.4f, 0.3f, -0.4f),
                   legs: jump > 4 ? P(-0.5f, 0.6f, 0.5f, -0.6f) : P(-0.2f, 0, 0.2f, 0));
        }
        if (hands)  // a crowd surfer, carried across during the phrase
        {
            Neon(cols[0], 4);
            SaveGState();
            _canvas.Translate((float)(20 + phraseFrac * 600), (float)(128 + 4 * Math.Sin(bp * Math.PI)));
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
        StrokeLineSegments(Pt(320, 10), Pt(320, 350));
        _g.Dash = null;
        Text(((int)(bp / 4) % 100).ToString(), Pt(250, 70), size: 54, fill: true, mono: true);
        Text(((int)(bp / 7) % 100).ToString(), Pt(390, 70), size: 54, fill: true, mono: true);
        double yL = 180, yR = 180;
        double[] offsets = drop ? [0, 0.33, 0.66] : [0];
        for (var i = 0; i < offsets.Length; i++)
        {
            var o = offsets[i];
            double x = 52 + Tri(bp + o) * 536, y = 20 + Tri(bp * 0.37 + o * 1.7 + 0.3) * 320;
            Neon(cols[i % cols.Length], 3);
            FillRect(Rect(x - 8, y - 8, 16, 16));
            if (x < 320) yL = y; else yR = y;
        }
        Neon(cols[0], 3);
        FillRect(Rect(28, yL - 40, 12, 80));
        FillRect(Rect(600, yR - 40, 12, 80));
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
        var size = Math.Min(170, 1000.0 / Math.Max(3, w.Length)) * (1 + 0.25 * Math.Max(0, 1 - u * 4));
        Neon(cols[Mod(beat, cols.Length)], 5);
        Text(w, Pt(320, 180), size: size, fill: u < 0.15);
    }

    void Equalizer(Frame f, Vector3[] cols, float dt)
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
            _eq[i] = v > _eq[i] ? v : _eq[i] - dt * 2.2f;
            _caps[i] = MathF.Max(_eq[i], _caps[i] - dt * 0.6f);
        }
        var bw = 640.0 / n;
        for (var i = 0; i < n; i++)
        {
            Neon(cols[Math.Min(cols.Length - 1, i * cols.Length / n)], 3);
            double h = _eq[i] * 300, x = i * bw + 6, y = 340;
            while (y > 340 - h) { StrokeRect(Rect(x, y - 12, bw - 12, 10)); y -= 16; }
            FillRect(Rect(x, 330 - _caps[i] * 300 - 8, bw - 12, 4));
        }
    }

    void Ambient(Vector3[] cols, float dt)
    {
        _amb += dt * 0.15;
        SetShadow(0, null);
        for (var i = 0; i < cols.Length; i++)
        {
            var c = cols[i];
            var x = 320 + 230 * Math.Sin(_amb * (0.7 + i * 0.23) + i * 2);
            var y = 180 + 110 * Math.Cos(_amb * (0.5 + i * 0.17) + i);
            using var shader = SKShader.CreateRadialGradient(Pt(x, y), 260, [Cg(c, 0.5f), Cg(c, 0)], [0, 1], SKShaderTileMode.Clamp);
            var p = Paint(false);
            p.Shader = shader;
            p.Color = SKColors.White.WithAlpha((byte)Math.Round(255 * _g.Alpha));
            _canvas.DrawCircle(Pt(x, y), 260, p);
            p.Shader = null;
        }
    }

    /// 3-2-1 into a drop, then DROP!
    bool Countdown(Frame f, Decision? d, Hello h, Vector3[] cols)
    {
        var spb = 60 / Math.Max(h.Bpm, 60);
        string? label = null;
        var u = 0.0;
        if (f.Phrase + 1 >= 0 && f.Phrase + 1 < h.Plan.Count && h.Plan[f.Phrase + 1].Section == "drop" && d?.Section != "drop")
        {
            var left = (h.Plan[f.Phrase + 1].Start - f.T) / spb;
            if (left > 0 && left <= 4) { label = ((int)Math.Ceiling(left)).ToString(); u = 1 - (left % 1 == 0 ? 1 : left % 1); }
        }
        if (d is { Section: "drop" } && f.T - d.Start < spb * 2) { label = "DROP!"; u = (f.T - d.Start) / (spb * 2); }
        if (label is null) return false;
        SetShadow(0, null);
        _g.Fill = new SKColor(0, 0, 0, (byte)Math.Round(0.85 * 255));
        FillRect(Rect(0, 0, 640, 360));
        Neon(cols[0], 7);
        Text(label, Pt(320, 185), size: label.Length > 1 ? 150 : 230 * (1.3 - 0.3 * u), fill: false);
        return true;
    }

    static SKTypeface? _display, _mono;

    /// The Mac's HelveticaNeue-CondensedBlack and Menlo-Bold, or their nearest on Windows.
    static SKTypeface Typeface(bool mono)
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
