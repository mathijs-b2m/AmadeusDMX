// `AmadeusDMX.exe -renderSelfTest [-d3dFeatureLevel 10.0]`: draws the sample club rig (SceneSamples) offscreen with the real renderer, from
// three cameras, into PNGs in %TEMP% (amadeus-stage-*.png) with a report (amadeus-stage-selftest.txt), then quits
// without starting the app. Exit code 0 when every picture was drawn and isn't empty. For checking the Direct3D half
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
            var inp = SceneSamples.Club();
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
