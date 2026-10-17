// Development: GPU time, frame rates and exposure, logged to %TEMP%\gpu-stats.txt with -gpuStats YES
// (mac/Sources/AmadeusDMX/Render/StageRenderer+Diagnostics.swift). The GPU time comes from Direct3D timestamp
// queries (GpuTimer); the invalid-pixel count from a read-back of the light buffer (StageRenderer.cs).
using System.Globalization;
using System.Numerics;

namespace AmadeusDMX;

public sealed partial class StageRenderer
{
    public static readonly bool GpuStats = Defaults.Standard.Bool("gpuStats");
    static readonly List<double> GpuSamples = [];
    internal static DateTime NanCheckAt = DateTime.MinValue;
    public static float LastLum { get; private set; }
    public static float LastExposure { get; private set; } = 1;
    static double LastFrameT = -1.0;
    static int NewFrames;
    static DateTime GpuSince = DateTime.UtcNow;

    public static string StatsFile => Path.Combine(Path.GetTempPath(), "gpu-stats.txt");

    internal static void AppendStats(string line)
    {
        try { File.AppendAllText(StatsFile, line); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    public static void RecordGPU(double ms, int beams, Vector2 size)
    {
        GpuSamples.Add(ms);
        if ((DateTime.UtcNow - GpuSince).TotalSeconds <= 3) return;
        var avg = GpuSamples.Average();
        var line = string.Format(CultureInfo.InvariantCulture,
            "{0:F1} ms GPU/frame (max {1:F1}), {2:F0} drawn/s, {3:F0} new show frames/s, {4} beams, {5:F0}×{6:F0} px, light {7:F2} → exposure {8:F2}\n",
            avg, GpuSamples.Max(), GpuSamples.Count / 3.0, NewFrames / 3.0, beams, size.X, size.Y, LastLum, LastExposure);
        NewFrames = 0;
        AppendStats(line);
        GpuSamples.Clear();
        GpuSince = DateTime.UtcNow;
    }

    /// Invalid (NaN/inf) and clearly negative values among half floats (the light buffer's RGBA16F pixels).
    public static (int Bad, int Negative) CountInvalid(ReadOnlySpan<ushort> halfs)
    {
        int bad = 0, neg = 0;
        foreach (var h in halfs)
        {
            if ((h & 0x7C00) == 0x7C00) bad++;
            else if ((h & 0x8000) != 0 && (h & 0x7FFF) > 0x0400) neg++;
        }
        return (bad, neg);
    }
}
