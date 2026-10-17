// Small formatting helpers shared by the views.
namespace AmadeusDMX;

public static class Formatting
{
    /// 83.4 s → "1:23"
    public static string TimeString(double t)
    {
        var s = Math.Max(0, (int)t);
        return $"{s / 60}:{s % 60:00}";
    }

    /// 0.7 → "70%"
    public static string Percent(double v) => $"{(int)Math.Round(v * 100, MidpointRounding.AwayFromZero)}%";

    /// "drop" → "Drop" (Swift's `.capitalized` for one word).
    public static string Capitalized(string s) =>
        string.Join(' ', s.Split(' ').Select(w => w.Length == 0 ? w : char.ToUpperInvariant(w[0]) + w[1..].ToLowerInvariant()));
}
