// The brightness limiter, shared with every engine: config/limiter.json ({"level": 0.7}). A ceiling on every
// light, for testing and setting up without eye strain; 1 is off (amadeus/dmx/limiter.py).
namespace AmadeusKit;

public sealed partial record Workspace
{
    public const double LimiterMinimum = 0.05;

    public string LimiterFile => Path.Combine(Data, "config", "limiter.json");

    /// The saved level, 0.05...1 (1: off, also when there is no file).
    public double LimiterLevel()
    {
        if (Files.ReadBytes(LimiterFile) is not { } data || JSONValue.ParseObject(data)?.GetValueOrDefault("level")?.Number is not { } v
            || !double.IsFinite(v)) return 1;
        return Math.Min(Math.Max(v, LimiterMinimum), 1);
    }

    /// Saves the level; a running engine follows within a quarter of a second.
    public void SetLimiterLevel(double level)
    {
        var v = Math.Min(Math.Max(level, LimiterMinimum), 1);
        try { Files.WriteAtomic(LimiterFile, JSONValue.ToJson(new Dictionary<string, JSONValue> { ["level"] = RigDocument.Round(v, 1000) })); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
    }
}
