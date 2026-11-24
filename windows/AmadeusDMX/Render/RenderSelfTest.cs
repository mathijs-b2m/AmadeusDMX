// `AmadeusDMX.exe -renderSelfTest [-d3dFeatureLevel 10.0]`: draws the sample club rig (SceneSamples) offscreen with the real renderer, from
// three cameras, into PNGs in %TEMP% (amadeus-stage-*.png) with a report (amadeus-stage-selftest.txt), then quits
// without starting the app. It also draws what the LED Wall Output sends (the Mac's stage snapshot does too):
// amadeus-wall.png (the show's picture) and amadeus-wall-card.png (the test card) on a monitor of 1920×1080, the wall
// at -wallRect X,Y,W,H (missing: the whole monitor), panels of -panelPx 128, one scene with -wallScene runner, the
// rig's LED wall of -screenPx 1536x384 (its shape; missing: 16:9). -wallBench YES adds how long the CPU takes to
// draw one wall picture per scene at 720p, 1080p and 4K (scale 2, 3, 6) to the report. Exit code 0 when every picture was drawn and isn't empty. For checking the Direct3D half
// on a Windows machine (the Mac checks the rest: RenderTests).
using System.Diagnostics;
using System.Globalization;
using System.Numerics;
using SkiaSharp;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Format = Vortice.DXGI.Format;

namespace AmadeusDMX;

public static class RenderSelfTest
{
    public static bool Requested(IEnumerable<string> args) => args.Any(a => a.Equals("-renderSelfTest", StringComparison.OrdinalIgnoreCase));

    public static int Run()
    {
        // -d3dFeatureLevel 10.0: as older graphics draw it (the flag itself out: `-key value` would take the next word)
        Defaults.Standard = new Defaults(null, Environment.GetCommandLineArgs().Where(a => !Requested([a])).ToArray());
        var dir = Path.GetTempPath();
        var report = new List<string> { $"Amadeus DMX render self-test, {DateTime.Now.ToString("u", CultureInfo.InvariantCulture)}" };
        var ok = true;
        try
        {
            var clock = Stopwatch.StartNew();
            using var r = StageRenderer.Make() ?? throw new InvalidOperationException("no Direct3D 11 device");
            report.Add($"device: feature level {r.FeatureLevel}, shaders ready in {clock.ElapsedMilliseconds} ms (cache: {ShaderLibrary.CacheFolder})");
            using (var dxgi = r.Device.QueryInterface<IDXGIDevice>())
            using (var adapter = dxgi.GetAdapter())
                report.Add($"adapter: {adapter.Description.Description}");
            var screenPx = Defaults.Standard.String("screenPx")?.Split('x') is [var sw, var sh]
                && int.TryParse(sw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var pw) && int.TryParse(sh, NumberStyles.Integer, CultureInfo.InvariantCulture, out var ph)
                && pw > 0 && ph > 0 ? (pw, ph) : ((int, int)?)null;
            var inp = SceneSamples.Club(screenPx: screenPx);
            if (WallScenes.FromRawValue(Defaults.Standard.String("wallScene")) is { } scene)
                WallSource.Shared.Force = scene;   // -wallScene runner: one scene on the wall
            var frame = SceneSamples.Frame(inp);
            r.Input = () => (inp, frame);
            r.Haze = 0.6f;
            const int W = 1280, H = 720;
            using var tex = r.Device.CreateTexture2D(new Texture2DDescription(Format.B8G8R8A8_UNorm_SRgb, W, H, 1, 1,
                BindFlags.RenderTarget | BindFlags.ShaderResource));
            using var rtv = r.Device.CreateRenderTargetView(tex);
            var now = 100.0;
            foreach (var preset in new[] { CameraPreset.FrontOfHouse, CameraPreset.Drone, CameraPreset.Plan })
            {
                r.SetPreset(preset, animated: false);
                // a second of show at 40 fps: the exposure settles, the wall draws, the GPU timer reports
                for (var i = 0; i < 40; i++)
                {
                    now += 1.0 / 40;
                    WallSource.Shared.Flush();   // the wall's picture drawn on the painter's thread: in step with the frames here
                    r.Draw(rtv, new Vector2(W, H), now);
                }
                r.Context.Flush();
                var px = r.ReadPixels(tex, W, H);
                var (varied, white) = Picture(px);
                var name = $"amadeus-stage-{preset.RawValue().ToLowerInvariant().Replace(' ', '-')}.png";
                File.WriteAllBytes(Path.Combine(dir, name), Png(px, W, H));
                // a broken stage is one flat colour (nothing drew) or white all over; a lit room is neither
                var empty = varied < 0.01;
                var blown = white > 0.9;
                ok &= !empty && !blown;
                report.Add($"{preset.RawValue()}: {name}, {varied:P1} of the pixels off the background, {white:P1} white" +
                           $"{(empty ? " — EMPTY" : blown ? " — WHITE" : "")}, " +
                           $"render scale {r.RenderScale:F2}, exposure {r.AutoExposure:F2}, wall {r.WallNow}");
            }
            report.Add($"GPU time (smoothed): {r.GpuMs:F2} ms per frame");
            ok &= WallOutput(r, inp, frame, now, dir, report);
            if (Defaults.Standard.Bool("wallBench")) WallBench(inp, report);
        }
        catch (Exception e)
        {
            ok = false;
            report.Add($"FAILED: {e}");
        }
        report.Add(ok ? "OK" : "NOT OK");
        File.WriteAllLines(Path.Combine(dir, "amadeus-stage-selftest.txt"), report);
        foreach (var line in report) Console.WriteLine(line);
        return ok ? 0 : 1;
    }

    /// What the LED Wall Output sends, for this show, into two PNGs: true when the picture isn't empty.
    static bool WallOutput(StageRenderer r, StageInput inp, AmadeusKit.Frame frame, double now, string dir, List<string> report)
    {
        const int W = 1920, H = 1080;
        var ints = Defaults.Standard.String("wallRect")?.Split(',').Select(v => int.TryParse(v.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var n) ? n : 0).ToArray();
        var wall = WallOutputLayout.WallRect(ints is { Length: 4 } a ? new PixelRect(a[0], a[1], a[2], a[3]) : null, W, H);
        var aspect = inp.Hello?.ScreenAspect ?? ScreenShape.DefaultAspect;
        var pic = WallOutputLayout.Fit(wall, aspect);
        var panelPx = Defaults.Standard.Integer("panelPx") > 0 ? Defaults.Standard.Integer("panelPx") : 128;
        var canvas = WallRenderer.Canvas(aspect);
        WallSource.Shared.Scale = WallOutputLayout.PictureScale(pic, (canvas.W, canvas.H));
        WallSource.Shared.OutputPicture = (pic.W, pic.H);
        var gpu = SharedGpu.Get();
        using var drawer = new WallOutputDrawer();
        using var tex = r.Device.CreateTexture2D(new Texture2DDescription(Format.B8G8R8A8_UNorm, W, H, 1, 1, BindFlags.RenderTarget | BindFlags.ShaderResource));
        using var rtv = r.Device.CreateRenderTargetView(tex);
        var ok = true;
        foreach (var testCard in new[] { false, true })
        {
            WallState? lit = null;
            for (var i = 0; i < 10; i++)
            {
                lit = WallSource.Shared.Update(frame, inp.Hello, now + i / 40.0) ?? lit;
                WallSource.Shared.Flush();   // the picture being drawn on the painter's thread
            }
            lit = WallSource.Shared.Update(frame, inp.Hello, now + 0.25) ?? lit;   // and taken
            (ID3D11Texture2D Texture, ID3D11ShaderResourceView View)? card = null;
            using (gpu.Lock())
            {
                var picture = WallSource.Shared.Compose(gpu, now + 0.25);
                if (testCard) card = WallOutputDrawer.CardTexture(gpu, (wall.W, wall.H), wall, panelPx);
                drawer.Encode(gpu, rtv, wall, pic, testCard ? 1 : lit?.Level ?? 0, card?.View, picture, 0.7f);
                gpu.Context.Flush();
            }
            card?.View.Dispose();
            card?.Texture.Dispose();
            var px = r.ReadPixels(tex, W, H);
            var (varied, _) = Picture(px);
            var name = testCard ? "amadeus-wall-card.png" : "amadeus-wall.png";
            File.WriteAllBytes(Path.Combine(dir, name), Png(px, W, H));
            var empty = varied < 0.01;
            ok &= !empty || !testCard;   // the show's picture may be dark at this moment; the card never is
            report.Add($"LED wall output: {name}, wall {wall.W}×{wall.H} at {wall.X},{wall.Y}, picture {pic.W}×{pic.H} ({aspect:F2}:1), drawn at {WallSource.Shared.DrawScale:0.#}× in {WallSource.Shared.DrawMs:F1} ms, {varied:P1} of the pixels lit{(empty && testCard ? " — EMPTY" : "")}");
        }
        WallSource.Shared.Scale = 1;
        WallSource.Shared.OutputPicture = null;
        return ok;
    }

    /// -wallBench YES: how long the CPU takes to draw one wall picture per scene, at 720p, 1080p and 4K.
    static void WallBench(StageInput inp, List<string> report)
    {
        var h = inp.Hello!;
        foreach (var s in new[] { 2.0, 3.0, 6.0 })
            foreach (var scene in WallScenes.AllCases.Where(s => s is not (WallScene.Auto or WallScene.Off or WallScene.Psychedelic)))
            {
                using var w = new WallRenderer((float)s, h.ScreenAspect) { Force = scene };
                for (var k = 0; k < 10; k++) w.Update(SceneSamples.Frame(inp, 30 + k / 40.0), h, 1 / 40f);
                var t0 = Stopwatch.GetTimestamp();
                for (var k = 10; k < 50; k++) w.Update(SceneSamples.Frame(inp, 30 + k / 40.0), h, 1 / 40f);
                report.Add($"wall bench: {scene.RawValue()} at {w.PixelWidth}×{w.PixelHeight}: {Stopwatch.GetElapsedTime(t0).TotalMilliseconds / 40:F1} ms");
            }
    }

    /// <summary>How much of a frame differs from its most common brightness (the background: clear colour, room
    /// or sky) by more than a quarter of the way to white, and how much of it is near white.</summary>
    internal static (double Varied, double White) Picture(byte[] bgra)
    {
        var n = bgra.Length / 4;
        if (n == 0) return (0, 0);
        var counts = new int[766];
        for (var k = 0; k < bgra.Length; k += 4) counts[bgra[k] + bgra[k + 1] + bgra[k + 2]]++;
        int median = 0, seen = 0;
        while (seen + counts[median] <= n / 2) seen += counts[median++];
        int varied = 0, white = 0;
        for (var v = 0; v < counts.Length; v++)
        {
            if (Math.Abs(v - median) > 60) varied += counts[v];
            if (v > 720) white += counts[v];
        }
        return (varied / (double)n, white / (double)n);
    }

    static byte[] Png(byte[] bgra, int w, int h)
    {
        using var bmp = new SKBitmap(new SKImageInfo(w, h, SKColorType.Bgra8888, SKAlphaType.Opaque));
        for (var y = 0; y < h; y++) System.Runtime.InteropServices.Marshal.Copy(bgra, y * w * 4, bmp.GetPixels() + y * bmp.RowBytes, w * 4);
        using var data = bmp.Encode(SKEncodedImageFormat.Png, 100);
        return data.ToArray();
    }
}
