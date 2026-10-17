// What the build tells the app (the Mac's Info.plist keys): appsettings.json beside the exe, written by build.ps1 and
// never by the app. AmadeusEngineRoot (a development build: the checkout it runs the engine from), UpdateFeedUrl and
// UpdatePublicEdKey (a release with an update feed).
namespace AmadeusKit;

public static class AppSettings
{
    static IReadOnlyDictionary<string, JSONValue>? _values;

    /// appsettings.json in `dir` (the app's folder by default); empty when there is none.
    public static IReadOnlyDictionary<string, JSONValue> Read(string? dir = null) =>
        Files.ReadBytes(Path.Combine(dir ?? AppContext.BaseDirectory, "appsettings.json")) is { } data
            ? JSONValue.ParseObject(data) ?? [] : new Dictionary<string, JSONValue>();

    static IReadOnlyDictionary<string, JSONValue> Values => _values ??= Read();

    public static string? String(string key) => Values.GetValueOrDefault(key)?.String is { Length: > 0 } s ? s : null;

    public static string? EngineRoot => String("AmadeusEngineRoot");
    public static string? UpdateFeedUrl => String("UpdateFeedUrl");
    public static string? UpdatePublicEdKey => String("UpdatePublicEdKey");
}
