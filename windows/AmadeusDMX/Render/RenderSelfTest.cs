// `AmadeusDMX.exe -renderSelfTest`: draws the sample club rig (SceneSamples) offscreen with the real renderer, from
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
                var lit = 0;
                for (var k = 0; k < px.Length; k += 4) if (px[k] + px[k + 1] + px[k + 2] > 90) lit++;
                var name = $"amadeus-stage-{preset.RawValue().ToLowerInvariant().Replace(' ', '-')}.png";
                File.WriteAllBytes(Path.Combine(dir, name), Png(px, W, H));
                var share = lit / (double)(W * H);
                var good = share > 0.01 && share < 0.95;
                ok &= good;
                report.Add($"{preset.RawValue()}: {name}, {share:P1} of the pixels lit{(good ? "" : " — EMPTY OR WHITE")}, " +
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

    static byte[] Png(byte[] bgra, int w, int h)
    {
        using var bmp = new SKBitmap(new SKImageInfo(w, h, SKColorType.Bgra8888, SKAlphaType.Opaque));
        for (var y = 0; y < h; y++) System.Runtime.InteropServices.Marshal.Copy(bgra, y * w * 4, bmp.GetPixels() + y * bmp.RowBytes, w * 4);
        using var data = bmp.Encode(SKEncodedImageFormat.Png, 100);
        return data.ToArray();
    }
}
