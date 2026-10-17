// The rules behind Settings (mac/Sources/AmadeusDMX/Settings): which kind of director a value is, where the OpenAI
// key comes from and how it is shown, the Mixxx MIDI port's name, and how updates compare versions.
namespace AmadeusKit;

/// Which director decides the show: the rules, OpenAI, or a local decision model in Ollama.
public enum DirectorKind { Rules, OpenAI, Local }

public static class DirectorKinds
{
    public static readonly DirectorKind[] All = Enum.GetValues<DirectorKind>();

    public static DirectorKind Of(string value) =>
        value.StartsWith("ollama", StringComparison.Ordinal) ? DirectorKind.Local : value == "openai" ? DirectorKind.OpenAI : DirectorKind.Rules;

    public static string Title(this DirectorKind k) => k switch
    {
        DirectorKind.Rules => "Rules",
        DirectorKind.OpenAI => "OpenAI",
        _ => "Local model",
    };
}

/// Where the engine's OpenAI key comes from: the app's (Credential Manager) wins over the engine folder's .env.
public readonly record struct KeySource(KeySource.Kind Where, string Key = "")
{
    public enum Kind { Stored, EnvFile, None }

    public static KeySource Current(string? stored, Workspace? ws) =>
        stored is { Length: > 0 } k ? new(Kind.Stored, k) : ws?.HasEnvKey == true ? new(Kind.EnvFile) : new(Kind.None);

    /// "sk-proj-…a1B2": enough to recognise a key, not enough to use it.
    public static string Masked(string k) =>
        k.Length > 12 ? $"{k[..(k.StartsWith("sk-proj-", StringComparison.Ordinal) ? 8 : 3)]}…{k[^4..]}" : "…";
}

/// The Mixxx integration's MIDI port (amadeus/show/sources/mixxx.py, winmidi.py).
public static class MixxxPort
{
    public const string Name = "Amadeus DMX";

    /// The port called `wanted`: exactly; else one the system names with something added at the end ("Amadeus DMX
    /// 1", "Amadeus DMX group 1") or at the front (winmidi.matching).
    public static int? Matching(IReadOnlyList<string> names, string wanted = Name)
    {
        Func<string, bool>[] tests = [n => n == wanted, n => n.EndsWith(" " + wanted, StringComparison.Ordinal),
                                      n => n.StartsWith(wanted + " ", StringComparison.Ordinal)];
        foreach (var t in tests)
            for (var i = 0; i < names.Count; i++)
                if (t(names[i])) return i;
        return null;
    }
}

/// Versions for updates: the feed's sparkle:version is the build number (the commit count), and so is the last
/// part of the app's assembly version (Directory.Build.props: major.minor.patch.BuildNumber).
public static class UpdateVersions
{
    /// The build number of an assembly version (0: a development build).
    public static int BuildNumber(Version? v) => v is null || v.Revision < 0 ? 0 : v.Revision;

    /// Is the feed's version (a build number) newer than this build?
    public static bool IsNewer(string? feedVersion, int build) =>
        int.TryParse(feedVersion?.Trim(), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var n)
        && n > build;

    /// A prerelease version people don't get ("0.4.0-beta.1").
    public static bool IsPrerelease(string? shortVersion) => shortVersion?.Contains('-') == true;
}
