// The DJ software live mode can follow: the engine's own list (amadeus/show/sources/sources.json), so a new
// integration shows up in the app without a change here.
using System.Text.Json;

namespace AmadeusKit;

public sealed record DJSource
{
    public required string Name { get; init; }
    public required string App { get; init; }
    public required string Position { get; init; }   // exact | beat | metadata: only "exact" can light a show
    public required string Verified { get; init; }
    public bool? Menu { get; init; }
    public string? Waiting { get; init; }            // what to do while the show waits for it
    public string Id => Name;

    public static DJSource From(JsonElement c) => new()
    {
        Name = J.Req(c, "name", J.String), App = J.Req(c, "app", J.String), Position = J.Req(c, "position", J.String),
        Verified = J.Req(c, "verified", J.String), Menu = J.Val(c, "menu", J.Bool), Waiting = J.Ref(c, "waiting", J.String),
    };
}

public sealed partial record Workspace
{
    public string DJSourcesFile => Path.Combine(Root, "amadeus", "show", "sources", "sources.json");

    DJSource[]? AllDJSources() => Files.ReadBytes(DJSourcesFile) is { } data ? J.Decode(data, J.ArrayOf(AmadeusKit.DJSource.From)) : null;

    /// The DJ software to offer in the Start menu (VirtualDJ first), from the engine's list.
    public IReadOnlyList<DJSource> DJSources() => AllDJSources()?.Where(s => s.Menu ?? true).ToList() ?? [];

    /// One DJ software from the engine's list by its name (vdj, mixxx, djay, …).
    public DJSource? DJSource(string name) => AllDJSources()?.FirstOrDefault(s => s.Name == name);
}

// Settings per integration, shared with the engine: config/integrations.json ({"djay": {"streamed": true}}).
// Live mode passes them to the integration (amadeus/show/sources/__init__.py); `--opt` overrides them.
public sealed partial record Workspace
{
    public string IntegrationsFile => Path.Combine(Data, "config", "integrations.json");

    Dictionary<string, JSONValue> Integrations() =>
        Files.ReadBytes(IntegrationsFile) is { } data ? JSONValue.ParseObject(data) ?? [] : [];

    public bool IntegrationSetting(string source, string key) =>
        Integrations().GetValueOrDefault(source)?[key]?.Bool ?? false;

    /// Saves one setting, keeping every other one in the file.
    public void SetIntegrationSetting(string source, string key, bool value)
    {
        var all = Integrations();
        var one = all.GetValueOrDefault(source)?.Object is { } o ? new Dictionary<string, JSONValue>(o) : [];
        one[key] = value;
        all[source] = JSONValue.Of(one);
        try { Files.WriteAtomic(IntegrationsFile, JSONValue.ToJson(all, pretty: true, sortKeys: true)); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
    }

    /// A Python package installed in the engine's environment (e.g. yt_dlp).
    public bool HasPythonPackage(string name)
    {
        // Windows: <env>\Scripts\python.exe (a venv) or <runtime>\python.exe, with Lib\site-packages;
        // elsewhere: <env>/bin/python, with lib/pythonX.Y/site-packages
        var bin = Path.GetDirectoryName(Python)!;
        if (OperatingSystem.IsWindows())
        {
            var env = Path.GetFileName(bin).Equals("Scripts", StringComparison.OrdinalIgnoreCase) ? Path.GetDirectoryName(bin)! : bin;
            return Directory.Exists(Path.Combine(env, "Lib", "site-packages", name));
        }
        var lib = Path.Combine(Path.GetDirectoryName(bin)!, "lib");
        try { return Directory.EnumerateDirectories(lib).Any(v => Directory.Exists(Path.Combine(v, "site-packages", name))); }
        catch (IOException) { return false; }
    }
}
