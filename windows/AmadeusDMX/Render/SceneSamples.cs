// A known scene for the stage: a small club rig (heads on a truss, one with a gobo wheel, a pixel bar, pars, a strobe,
// a laser, a smoke machine, an LED wall and a zone) and a show frame that lights all of it. The render self-test draws it
// (`AmadeusDMX.exe -renderSelfTest`, RenderSelfTest.cs) and the tests build it on a Mac (RenderTests).
using System.Numerics;
using SkiaSharp;

using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

public static class SceneSamples
{
    public static StageInput Club(bool screen = true)
    {
        var fixtures = new List<FixtureInfo>();
        for (var k = 0; k < 4; k++)
            fixtures.Add(new FixtureInfo($"head{k + 1}", FixtureKind.Head, $"Head {k + 1}", new Vec3(1 + k * 1.33, -0.5, 3.2), "hang", 4, k == 3 ? 16 : 4)
            {
                Fixture = $"head{k + 1}", Body = "moving_head", Up = new Vec3(0, 0, -1), Truss = "t1",
            });
        for (var c = 0; c < 8; c++)
            fixtures.Add(new FixtureInfo($"bar.{c + 1}", FixtureKind.Par, $"Bar {c + 1}", new Vec3(1.5 + c * 0.4, -0.3, 0.1), "floor", 25)
            {
                Fixture = "bar", Body = "par_bar", Cells = 8, Length = 3.2, Dir = new Vec3(0, 0.3, 1),
            });
        foreach (var (id, x) in new[] { ("parL", 0.3), ("parR", 5.7) })
            fixtures.Add(new FixtureInfo(id, FixtureKind.Par, id, new Vec3(x, -0.8, 0.2), "floor", 30) { Dir = new Vec3(0, 0.2, 1) });
        fixtures.Add(new FixtureInfo("strobe", FixtureKind.Strobe, "Strobe", new Vec3(3, -0.5, 3.4), "hang", 90) { Dir = new Vec3(0, 1, -0.2), Truss = "t1" });
        fixtures.Add(new FixtureInfo("laser", FixtureKind.Laser, "Laser", new Vec3(3, -1.2, 2.6), "stand", 1) { Body = "laser" });
        fixtures.Add(new FixtureInfo("smoke", FixtureKind.Smoke, "Smoke", new Vec3(0.5, -1.5, 0.15), "floor", 1) { Body = "smoke", Dir = new Vec3(0, 1, 0.1) });
        var trusses = new List<Truss> { new("t1", 6, 3, -0.5, 3.5), new("tower", 3.5, 6.4, -1, 1.75, vertical: true) };
        var stage = new Stage(6, 4.5, 8);
        var plan = new List<Decision>
        {
            new() { Phrase = 0, Start = 0, End = 16, Section = "buildup", Palette = "neon", Screen = "words" },
            new() { Phrase = 1, Start = 16, End = 48, Section = "drop", Palette = "neon", Screen = "figure", Intensity = 2 },
        };
        var hello = new Hello
        {
            Track = "01 - Sample Track (Club Mix).wav", Bpm = 128, Fixtures = fixtures, Stage = stage, Plan = plan, Screen = screen, Countdown = 1,
            Trusses = trusses, Gobos = [DotsGobo()],
        };
        var zones = new List<Zone> { new("z1", "Audience", "laser_out", "box", new Vec3(3, 4, 1), [6, 4, 2]) };
        return new StageInput
        {
            Key = "sample:club", Fixtures = fixtures, Stage = stage, Screen = screen, Hello = hello, Trusses = trusses, Zones = zones,
        };
    }

    /// A metal gobo as the hello sends it (a grey PNG in base64, light where light passes): a ring of six holes round
    /// one in the middle.
    public static GoboPicture DotsGobo()
    {
        const int size = 128;
        using var bmp = new SKBitmap(new SKImageInfo(size, size, SKColorType.Gray8, SKAlphaType.Opaque));
        using (var canvas = new SKCanvas(bmp))
        using (var paint = new SKPaint { Color = SKColors.White, IsAntialias = true })
        {
            canvas.Clear(SKColors.Black);
            canvas.DrawCircle(size / 2f, size / 2f, 12, paint);
            for (var k = 0; k < 6; k++)
            {
                var a = k * MathF.PI / 3;
                canvas.DrawCircle(size / 2f + 40 * MathF.Cos(a), size / 2f + 40 * MathF.Sin(a), 14, paint);
            }
        }
        using var data = bmp.Encode(SKEncodedImageFormat.Png, 100);
        return new GoboPicture { Key = "sample/dots", Img = Convert.ToBase64String(data.ToArray()), Style = "dots" };
    }

    /// A show frame at `t` seconds: every fixture lit, heads fanned out (one through a prism, one with a turning gobo,
    /// zoomed a little wider), the laser drawing a fan.
    public static Frame Frame(StageInput inp, double t = 20)
    {
        var n = inp.Fixtures.Count;
        var fx = new float[n][];
        var dirs = new Vector3?[n];
        var beam = new string?[n];
        var lz = new LaserBeam[]?[n];
        var gobo = new GoboState?[n];
        var zoom = new float?[n];
        for (var i = 0; i < n; i++)
        {
            var f = inp.Fixtures[i];
            var hue = i / (float)Math.Max(1, n);
            fx[i] = [1, 1 - hue, 0.2f + hue * 0.8f, hue, 0];
            if (f.Kind == FixtureKind.Head)
            {
                var a = (i - 1.5f) * 0.35f;
                dirs[i] = Vector3.Normalize(new Vector3(MathF.Sin(a), 0.8f, -0.6f));
                beam[i] = i == 1 ? "prism" : i == 3 ? "gobo" : "open";
                if (i == 3) { gobo[i] = new GoboState(0, Turn: 0.5f); zoom[i] = 0.3f; }
            }
            if (f.Kind == FixtureKind.Laser)
                lz[i] = Enumerable.Range(0, 7).Select(k => new LaserBeam(
                    Vector3.Normalize(new Vector3((k - 3) * 0.15f, 1, 0.05f)), new Vector3(0, 1, 0.2f), 0.9f)).ToArray();
        }
        return new Frame
        {
            T = t, Phrase = t >= 16 ? 1 : 0, Bp = t * 128 / 60, Fx = fx, Dirs = dirs, Beam = beam, Lz = lz, Gobo = gobo, Zoom = zoom,
            Bands = [0.8f, 0.6f, 0.4f, 0.3f, 0.2f, 0.1f],
            Fog = new Dictionary<string, float> { ["smoke"] = 0.8f },
        };
    }
}
