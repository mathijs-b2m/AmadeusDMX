// Where the engine lives and the files the app shares with it: config/sets (your gear), config/rigs (venues),
// config/active-set and active-rig, fixtures/, .env. The file format is the engine's (amadeus/rig/store.py,
// docs/rig-format.md).
//
// Two kinds: a checkout (the Amadeus DMX project folder with its .venv; your data in the same folder) and the
// engine that comes with the app (engine\ with its own Python in runtime\, next to the exe; your data in
// %LOCALAPPDATA%\Amadeus DMX, so an update of the app never touches it).
using System.Diagnostics;
using System.Reflection;

namespace AmadeusKit;

public sealed partial record Workspace
{
    /// The engine: the package, the web UI, the shipped fixture library and examples.
    public string Root { get; init; }
    /// Your data: sets, rigs, settings, fixtures you added or calibrated, the cache.
    public string Data { get; init; }
    public string Python { get; init; }

    /// A checkout: everything in one folder.
    public Workspace(string root) : this(root, root, VenvPython(root)) { }

    internal Workspace(string root, string data, string python)
    {
        Root = root; Data = data; Python = python;
    }

    /// A Python environment's interpreter: Scripts\python.exe on Windows, bin/python elsewhere.
    public static string VenvPython(string env) =>
        OperatingSystem.IsWindows() ? Path.Combine(env, ".venv", "Scripts", "python.exe") : Path.Combine(env, ".venv", "bin", "python");

    /// The interpreters that may be the one listening when the engine runs: `Python`, and, when that is a
    /// virtual environment's (a checkout's .venv, the packs), the Python it was made from: on Windows a venv's
    /// python.exe only starts that one (Windows Firewall's rules name the program that listens).
    public IReadOnlyList<string> ListeningPythons()
    {
        var list = new List<string> { Python };
        var cfg = Files.ReadText(Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(Python) ?? "") ?? "", "pyvenv.cfg"));
        var home = cfg?.Split('\n').Select(l => l.Split('=', 2)).FirstOrDefault(kv => kv.Length == 2 && kv[0].Trim() == "home")?[1].Trim();
        if (home is { Length: > 0 })
            list.Add(Path.Combine(home, OperatingSystem.IsWindows() ? "python.exe" : "python3"));
        return list;
    }

    static string EnvPython(string env) =>
        OperatingSystem.IsWindows() ? Path.Combine(env, "Scripts", "python.exe") : Path.Combine(env, "bin", "python3");

    /// %LOCALAPPDATA%\Amadeus DMX (AMADEUS_DATA, when set, wins: a second data folder for testing).
    public static string DefaultDataFolder =>
        System.Environment.GetEnvironmentVariable("AMADEUS_DATA") is { Length: > 0 } d ? d
            : Path.Combine(System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData), "Amadeus DMX");

    /// The engine that comes with the app (a release build), nil in a development build.
    public static Workspace? BuiltIn => FromApp(AppContext.BaseDirectory, DefaultDataFolder);

    /// The engine next to an app in `appDir` (engine\ and runtime\python.exe), with the data in `dataDir`.
    public static Workspace? FromApp(string appDir, string dataDir)
    {
        var runtime = OperatingSystem.IsWindows() ? Path.Combine(appDir, "runtime", "python.exe")
            : Path.Combine(appDir, "runtime", "bin", "python3");
        var ws = new Workspace(Path.Combine(appDir, "engine"), dataDir, runtime);
        if (!ws.IsValid) return null;
        try { Directory.CreateDirectory(ws.Data); }
        catch (IOException) { }
        // optional packs (amadeus/cli/packs.py) live in an environment on top of the app's Python: use it once there
        var packs = Path.Combine(ws.Data, "python");
        if (File.Exists(Path.Combine(packs, "pyvenv.cfg")))
        {
            RepairPacks(packs, runtime);
            var py = EnvPython(packs);
            if (IsExecutable(py)) ws = ws with { Python = py };
        }
        return ws;
    }

    /// The packs' environment points at the app's Python by path: after the app moved, point it there again.
    static void RepairPacks(string env, string runtime)
    {
        var cfg = Files.ReadText(Path.Combine(env, "pyvenv.cfg")) ?? "";
        var home = Path.GetDirectoryName(runtime)!;
        if (cfg.Split('\n').Any(l => l.Trim() == $"home = {home}")) return;
        try
        {
            using var p = Process.Start(new ProcessStartInfo(runtime)
            {
                // -B: nothing written into the program folder
                ArgumentList = { "-B", "-m", "venv", "--upgrade", "--system-site-packages", "--without-pip", env },
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            });
            p?.WaitForExit();
        }
        catch (System.ComponentModel.Win32Exception) { }
    }

    /// The optional packs and whether they're installed (`amadeus packs --json`).
    public async Task<IReadOnlyList<PackInfo>> Packs(CancellationToken ct = default)
    {
        var psi = PythonStart(["-m", "amadeus", "packs", "--json"]);
        try
        {
            using var p = Process.Start(psi);
            if (p is null) return [];
            var data = await p.StandardOutput.ReadToEndAsync(ct);
            await p.WaitForExitAsync(ct);
            return J.Decode(J.Utf8(data), J.ArrayOf(PackInfo.From)) ?? [];
        }
        catch (System.ComponentModel.Win32Exception) { return []; }
    }

    /// Whether Claude Desktop starts this engine's assistant server (`amadeus mcp --claude-desktop`): "status",
    /// or "on"/"off" to change it. Null when the engine couldn't say.
    public async Task<ClaudeDesktopStatus?> ClaudeDesktop(string action = "status", CancellationToken ct = default)
    {
        var psi = PythonStart(["-m", "amadeus", "mcp", "--claude-desktop", action]);
        try
        {
            using var p = Process.Start(psi);
            if (p is null) return null;
            var data = await p.StandardOutput.ReadToEndAsync(ct);
            await p.WaitForExitAsync(ct);
            return J.Decode(J.Utf8(data), ClaudeDesktopStatus.From);
        }
        catch (System.ComponentModel.Win32Exception) { return null; }
    }

    /// The sets and rigs on disk, in one line: it changes when any of them is written, added or removed (by the
    /// web setup page, the command line, your AI assistant), so the app can read them again.
    public string ConfigStamp()
    {
        var parts = new List<string>();
        foreach (var dir in new[] { SetsDir, RigsDir })
        {
            if (!Directory.Exists(dir)) continue;
            foreach (var f in Directory.GetFiles(dir, "*.json").Order(StringComparer.Ordinal))
            {
                var i = new FileInfo(f);
                parts.Add(i.Exists ? $"{f}|{i.LastWriteTimeUtc.Ticks}|{i.Length}" : f);
            }
        }
        parts.Add(ActiveSet ?? "");
        parts.Add(ActiveRig ?? "");
        return string.Join("\n", parts);
    }

    ProcessStartInfo PythonStart(IEnumerable<string> args)
    {
        var psi = new ProcessStartInfo(Python)
        {
            WorkingDirectory = Root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        foreach (var (k, v) in Environment) psi.Environment[k] = v;
        return psi;
    }

    public bool IsBuiltIn => Data != Root;

    /// What the engine needs to know where it is (amadeus/paths.py).
    public IReadOnlyDictionary<string, string> Environment
    {
        get
        {
            var env = new Dictionary<string, string> { ["AMADEUS_ROOT"] = Root };
            if (IsBuiltIn)
            {
                env["AMADEUS_DATA"] = Data;
                env["PYTHONDONTWRITEBYTECODE"] = "1";  // nothing may be written into the program folder (compiled at build)
                env["PYTHONNOUSERSITE"] = "1";  // only the app's own packages, never the user's site-packages
            }
            return env;
        }
    }

    public string SetsDir => Path.Combine(Data, "config", "sets");
    public string RigsDir => Path.Combine(Data, "config", "rigs");
    public string ActiveSetFile => Path.Combine(Data, "config", "active-set");
    public string ActiveRigFile => Path.Combine(Data, "config", "active-rig");
    public string EnvFile => Path.Combine(Data, ".env");
    /// The VirtualDJ plugin built from vdj/ (vdj/build.sh on the Mac; the Windows build makes the DLL).
    public string PluginBundle => Path.Combine(Root, "vdj", "build", OperatingSystem.IsWindows() ? "AmadeusLink.dll" : "AmadeusLink.bundle");

    static bool IsExecutable(string path)
    {
        if (!File.Exists(path)) return false;
        if (OperatingSystem.IsWindows()) return true;
        return (File.GetUnixFileMode(path) & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute)) != 0;
    }

    /// Looks like an engine folder: the package and a Python environment.
    public bool IsValid => HasPackage && IsExecutable(Python);

    public bool HasPackage => File.Exists(Path.Combine(Root, "amadeus", "__main__.py"));

    public bool HasEnvKey => Files.ReadText(EnvFile)?.Contains("OPENAI_API_KEY") ?? false;

    // MARK: first run and old files

    /// A fresh checkout (no sets yet) or old combined set files: let the engine set things up, so the
    /// migration lives in one place (amadeus/rig/store.py). Fast; runs only when needed.
    public void Prepare()
    {
        var sets = Names(SetsDir);
        var combined = sets.Any(name =>
            Files.ReadBytes(SetURL(name)) is { } bytes && JSONValue.ParseObject(bytes) is { } o
            && RigDocument.RigKeys.Any(o.ContainsKey));
        if (!(sets.Count == 0 || combined || !Directory.Exists(RigsDir)) || !IsValid) return;
        try
        {
            using var p = Process.Start(PythonStart(["-c", "from amadeus.rig import store; store.sets.names(); store.rigs.names()"]));
            p?.WaitForExit();
        }
        catch (System.ComponentModel.Win32Exception) { }
    }

    static List<string> Names(string dir)
    {
        try
        {
            return Directory.EnumerateFiles(dir, "*.json").Select(f => Path.GetFileNameWithoutExtension(f))
                .Order(StringComparer.Ordinal).ToList();
        }
        catch (IOException) { return []; }
    }

    // MARK: sets (your gear)

    public IReadOnlyList<string> SetNames() => Names(SetsDir);

    public string? ActiveSet => Files.ReadText(ActiveSetFile)?.Trim();

    public string SetURL(string name) => Path.Combine(SetsDir, $"{name}.json");

    public RigFile? LoadSet(string name) =>
        Files.ReadBytes(SetURL(name)) is { } data ? J.Decode(data, RigFile.From) : null;

    public IReadOnlyList<SetSummary> Sets()
    {
        var active = ActiveSet;
        return SetNames().Select(name => LoadSet(name) is { } rig ? new SetSummary(name, rig, name == active, IsExampleSet(name)) : null)
            .OfType<SetSummary>().ToList();
    }

    /// One of the sets a first run starts from (examples/sets): there to look around in, not for your own gear.
    /// Renamed or duplicated, it is yours.
    public bool IsExampleSet(string name) => File.Exists(Path.Combine(Root, "examples", "sets", $"{name}.json"));

    // MARK: rigs (venues)

    public IReadOnlyList<string> RigNames() => Names(RigsDir);

    public string? ActiveRig => Files.ReadText(ActiveRigFile)?.Trim();

    public string RigURL(string name) => Path.Combine(RigsDir, $"{name}.json");

    Dictionary<string, JSONValue>? ReadObject(string path) => Files.ReadBytes(path) is { } b ? JSONValue.ParseObject(b) : null;

    public IReadOnlyList<RigSummary> Rigs()
    {
        var active = ActiveRig;
        return RigNames().Select(name => ReadObject(RigURL(name)) is { } o ? new RigSummary(name, o, name == active, IsExampleRig(name)) : null)
            .OfType<RigSummary>().ToList();
    }

    /// One of the rigs a first run starts from (examples/rigs): venues to look around in, not your own.
    /// Renamed or duplicated, it is yours.
    public bool IsExampleRig(string name) => File.Exists(Path.Combine(Root, "examples", "rigs", $"{name}.json"));

    // MARK: a set on a rig

    /// The set placed on the rig, in the shape the engine reads (amadeus/rig/store.py compose): fixtures with
    /// their places on this rig; fixtures without one wait in a row on the floor at the front ("_unplaced").
    public byte[]? Composed(string rig, string set)
    {
        Dictionary<string, JSONValue> setDoc;
        if (set.Length == 0)  // the rig alone: its structure, no set on it
            setDoc = new() { ["fixtures"] = JSONValue.Of(Array.Empty<JSONValue>()) };
        else if (ReadObject(SetURL(set)) is { } d)
            setDoc = d;
        else
            return null;
        var rigDoc = ReadObject(RigURL(rig)) ?? [];
        return JSONValue.ToJson(RigDocument.Compose(setDoc, rigDoc, set));
    }

    /// Which of the set's fixtures have a place on the rig: (mounted, all).
    public (int Placed, int Total) Mounted(string rig, string set)
    {
        var ids = LoadSet(set)?.Fixtures.Select(f => f.Id).ToList() ?? [];
        var places = ReadObject(RigURL(rig))?.GetValueOrDefault("placements")?[set]?.Object;
        return (ids.Count(id => places?.ContainsKey(id) == true), ids.Count);
    }

    // MARK: finding the engine

    /// The engine root a development build was made with, like the Mac's Info.plist key: build.ps1's
    /// appsettings.json, else the one `dotnet build` bakes in (MSBuild AmadeusEngineRoot).
    public static string? BakedRoot => AppSettings.EngineRoot
        ?? (Assembly.GetEntryAssembly()?.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == "AmadeusEngineRoot")?.Value is { Length: > 0 } r ? r : null);

    /// The engine: a folder chosen before, the one baked in at build time (a development build), the one that
    /// comes with the app (a release), or a checkout around the app.
    public static Workspace? Locate(string? saved) => Locate(saved, BakedRoot, AppContext.BaseDirectory, BuiltIn);

    public static Workspace? Locate(string? saved, string? baked, string appDir, Workspace? builtIn)
    {
        var candidates = new List<string>();
        if (saved is not null) candidates.Add(saved);
        if (baked is not null) candidates.Add(baked);
        if (candidates.Select(c => new Workspace(c)).FirstOrDefault(w => w.IsValid) is { } ws) return ws;
        if (builtIn is not null) return builtIn;
        var dir = Path.TrimEndingDirectorySeparator(appDir);
        for (var i = 0; i < 5 && Path.GetDirectoryName(dir) is { } up; i++) { dir = up; candidates.Add(dir); }
        return candidates.Select(c => new Workspace(c)).FirstOrDefault(w => w.IsValid);
    }
}

/// An optional pack (amadeus/cli/packs.py).
public sealed record PackInfo(string Name, string Title, string About, string Size, string Note, bool Installed)
{
    public string Id => Name;

    public static PackInfo From(System.Text.Json.JsonElement c) => new(
        J.Req(c, "name", J.String), J.Req(c, "title", J.String), J.Req(c, "about", J.String), J.Req(c, "size", J.String),
        J.Req(c, "note", J.String), J.Req(c, "installed", J.Bool));
}

/// Claude Desktop and the assistant server (amadeus/mcp/claude_desktop.py status). Installed: it has a config
/// folder; On: its config starts this engine's server; Current: as this engine would write it now (else the app
/// moved: write it again).
public sealed record ClaudeDesktopStatus(bool Installed, bool On, bool Current, string Config, string Problem)
{
    public static ClaudeDesktopStatus From(System.Text.Json.JsonElement c) => new(
        J.Req(c, "installed", J.Bool), J.Req(c, "on", J.Bool), J.Req(c, "current", J.Bool), J.Req(c, "config", J.String),
        J.Req(c, "problem", J.String));
}

/// A set file (config/sets/NAME.json), the parts the app shows.
public sealed record RigFile
{
    public sealed record ArtNet(string? Ip, int? Port, int? Fps)
    {
        public static ArtNet From(System.Text.Json.JsonElement c) =>
            new(J.Ref(c, "ip", J.String), J.Val(c, "port", J.Int), J.Val(c, "fps", J.Int));
    }

    public sealed record Fixture
    {
        public required string Id { get; init; }
        public required string FixtureKey { get; init; }  // "fixture" in the file
        public string? Mode { get; init; }
        public int? Universe { get; init; }
        public int? Address { get; init; }
        public string? Mount { get; init; }
        public double? X { get; init; }
        public double? YM { get; init; }
        public double? ZM { get; init; }

        public static Fixture From(System.Text.Json.JsonElement c) => new()
        {
            Id = J.Req(c, "id", J.String), FixtureKey = J.Req(c, "fixture", J.String), Mode = J.Ref(c, "mode", J.String),
            Universe = J.Val(c, "universe", J.Int), Address = J.Val(c, "address", J.Int), Mount = J.Ref(c, "mount", J.String),
            X = J.Val(c, "x", J.Double), YM = J.Val(c, "y_m", J.Double), ZM = J.Val(c, "z_m", J.Double),
        };

        /// "beamz/fuze75b-beam" → "fuze75b-beam"
        public string Model => FixtureKey.Split('/', StringSplitOptions.RemoveEmptyEntries).LastOrDefault() ?? FixtureKey;
        public string Brand => FixtureKey.Split('/', StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "";
    }

    public string? Description { get; init; }
    public ArtNet? Artnet { get; init; }
    public IReadOnlyList<Fixture> Fixtures { get; init; } = [];
    public Stage? Stage { get; init; }
    public string? Director { get; init; }
    public JSONValue? Screen { get; init; }
    /// Where the DMX goes (amadeus/outputs.py): absent = Art-Net to `artnet.ip`.
    public JSONValue? Output { get; init; }
    /// The set's universes mapped onto your DMX devices (amadeus/dmx/devices.py): set universe → device + output.
    /// When present it decides the output (the blocks above are the old way).
    public IReadOnlyDictionary<string, JSONValue>? Dmx { get; init; }

    public static RigFile From(System.Text.Json.JsonElement c) => new()
    {
        Description = J.Ref(c, "description", J.String),
        Artnet = J.Ref(c, "artnet", ArtNet.From),
        Fixtures = J.Req(c, "fixtures", J.ArrayOf(Fixture.From)),
        Stage = J.Ref(c, "stage", AmadeusKit.Stage.From),
        Director = J.Ref(c, "director", J.String),
        Screen = J.Ref(c, "screen", JSONValue.From),
        Output = J.Ref(c, "output", JSONValue.From),
        Dmx = J.Ref(c, "dmx", J.DictOf(JSONValue.From)),
    };

    /// The devices the set's universes go to (ids), in universe order.
    public IReadOnlyList<string> MappedDevices
    {
        get
        {
            if (Dmx is null) return [];
            var out_ = new List<string>();
            foreach (var key in Dmx.Keys.OrderBy(k => int.TryParse(k, out var n) ? n : 0))
                if (Dmx[key]["device"]?.String is { } d && !out_.Contains(d)) out_.Add(d);
            return out_;
        }
    }

    /// The output in words, like the engine says it.
    public string OutputText
    {
        get
        {
            if (Dmx is null) return LegacyOutputText;
            var devs = MappedDevices;
            return devs.Count == 0 ? "Visualiser only" : "→ " + string.Join(", ", devs);
        }
    }

    /// The set's own output blocks in words (sets without a device mapping).
    public string LegacyOutputText
    {
        get
        {
            IEnumerable<IReadOnlyDictionary<string, JSONValue>> specs = Output switch
            {
                { Object: { } o } => [o],
                { Array: { } a } => a.Select(v => v.Object).OfType<IReadOnlyDictionary<string, JSONValue>>(),
                _ => [new Dictionary<string, JSONValue> { ["type"] = "artnet" }],
            };
            return string.Join(" + ", specs.Select(s => (s.GetValueOrDefault("type")?.String ?? "artnet") switch
            {
                "sacn" => $"sACN → {s.GetValueOrDefault("ip")?.String ?? "multicast"}",
                "enttec_pro" => $"USB ENTTEC Pro → {(s.GetValueOrDefault("port")?.String is { } p ? (p == "auto" ? "auto" : LastPathComponent(p)) : "auto")}",
                _ => $"Art-Net → {s.GetValueOrDefault("ip")?.String ?? Artnet?.Ip ?? "127.0.0.1"}",
            }));
        }
    }

    internal static string LastPathComponent(string p) =>
        p.TrimEnd('/', '\\').Split('/', '\\').LastOrDefault() is { Length: > 0 } last ? last : p;

    /// Only the visualiser: Art-Net to this computer, no other output.
    public bool IsVirtual =>
        Dmx is not null ? MappedDevices.Count == 0 : Output is null && (Artnet?.Ip is null || Artnet.Ip == "127.0.0.1");

    public bool HasScreen => Screen is not null && !Screen.IsNull && Screen.Bool != false;
}

public sealed record SetSummary
{
    public string Name { get; init; }
    public string Description { get; init; }
    public int FixtureCount { get; init; }
    public IReadOnlyList<(string Model, int Count)> Models { get; init; }
    public string? ArtnetIP { get; init; }
    public string OutputText { get; init; }
    public bool IsVirtual { get; init; }
    public string Director { get; init; }
    public bool HasScreen { get; init; }
    public bool IsDefault { get; init; }
    /// One of the shipped example sets (Workspace.IsExampleSet).
    public bool IsExample { get; init; }

    public string Id => Name;

    internal SetSummary(string name, RigFile rig, bool isDefault, bool isExample = false)
    {
        Name = name;
        Description = rig.Description ?? "";
        FixtureCount = rig.Fixtures.Count;
        var counts = new Dictionary<string, int>();
        var order = new List<string>();
        foreach (var f in rig.Fixtures)
        {
            if (!counts.ContainsKey(f.Model)) order.Add(f.Model);
            counts[f.Model] = counts.GetValueOrDefault(f.Model) + 1;
        }
        Models = order.Select(m => (m, counts[m])).ToList();
        ArtnetIP = rig.Artnet?.Ip;
        OutputText = rig.OutputText;
        IsVirtual = rig.IsVirtual;
        Director = rig.Director ?? "rules";
        HasScreen = rig.HasScreen;
        IsDefault = isDefault;
        IsExample = isExample;
    }

    public bool Equals(SetSummary? b) =>
        b is not null && Name == b.Name && FixtureCount == b.FixtureCount && IsDefault == b.IsDefault && Description == b.Description
        && IsExample == b.IsExample;

    public override int GetHashCode() => Name.GetHashCode();
}

/// A rig (config/rigs/NAME.json): a venue's structure, the parts the app lists.
public sealed record RigSummary
{
    public string Name { get; init; }
    public string Description { get; init; }
    public double WidthM { get; init; }
    public int Trusses { get; init; }
    public int Towers { get; init; }
    public bool HasScreen { get; init; }
    public int Zones { get; init; }
    /// Sets with fixtures mounted on this rig, and how many.
    public IReadOnlyDictionary<string, int> Mounted { get; init; }
    public bool IsDefault { get; init; }
    /// One of the shipped example rigs (Workspace.IsExampleRig).
    public bool IsExample { get; init; }

    public string Id => Name;

    internal RigSummary(string name, IReadOnlyDictionary<string, JSONValue> o, bool isDefault, bool isExample = false)
    {
        Name = name;
        Description = o.GetValueOrDefault("description")?.String ?? "";
        WidthM = o.GetValueOrDefault("stage")?["width_m"]?.Number ?? 6;
        var ts = o.GetValueOrDefault("trusses")?.Array ?? [];
        Towers = ts.Count(t => t["vertical"] == JSONValue.True);
        Trusses = ts.Count - Towers;
        HasScreen = o.GetValueOrDefault("screen") is { } s && !s.IsNull && s.Bool != false;
        Zones = o.GetValueOrDefault("zones")?.Array?.Count ?? 0;
        Mounted = (o.GetValueOrDefault("placements")?.Object ?? new Dictionary<string, JSONValue>())
            .ToDictionary(p => p.Key, p => p.Value.Object?.Count ?? 0);
        IsDefault = isDefault;
        IsExample = isExample;
    }

    /// "12 m wide · 2 trusses · 2 towers · LED wall"
    public string Summary
    {
        get
        {
            var parts = new List<string> { $"{Format.Number(WidthM)} m wide" };
            if (Trusses > 0) parts.Add($"{Trusses} truss{(Trusses == 1 ? "" : "es")}");
            if (Towers > 0) parts.Add($"{Towers} tower{(Towers == 1 ? "" : "s")}");
            if (Trusses + Towers == 0) parts.Add("floor and stands");
            if (HasScreen) parts.Add("LED wall");
            return string.Join(" · ", parts);
        }
    }

    public bool Equals(RigSummary? b) =>
        b is not null && Name == b.Name && Description == b.Description && WidthM == b.WidthM && Trusses == b.Trusses
        && Towers == b.Towers && HasScreen == b.HasScreen && Zones == b.Zones && IsDefault == b.IsDefault
        && IsExample == b.IsExample && Mounted.Count == b.Mounted.Count && Mounted.All(p => b.Mounted.TryGetValue(p.Key, out var n) && n == p.Value);

    public override int GetHashCode() => Name.GetHashCode();
}

/// Numbers for people, like Swift's `.formatted()`: no trailing zeros, at most 3 decimals.
public static class Format
{
    public static string Number(double v) =>
        Math.Round(v, 3).ToString("0.###", System.Globalization.CultureInfo.CurrentCulture);
}

// MARK: rig preview (before a show runs)

public sealed partial record Workspace
{
    public FixtureDefinition? Definition(string key)
    {
        var mine = Path.Combine(Data, "fixtures", key + ".json");  // yours win (amadeus/library/fixtures.py)
        var path = File.Exists(mine) ? mine : Path.Combine(Root, "fixtures", key + ".json");
        return Files.ReadBytes(path) is { } data ? J.Decode(data, FixtureDefinition.From) : null;
    }

    public RigDocument? Document(string rig, string set)
    {
        if (Composed(rig, set) is not { } data) return null;
        try { return new RigDocument(rig, set, data); }
        catch (System.Text.Json.JsonException) { return null; }
    }

    /// The set on the rig as the visualiser would place it (the same rules as amadeus/fixtures.py + geometry.py).
    public (IReadOnlyList<FixtureInfo> Fixtures, Stage Stage, bool Screen, IReadOnlyList<Truss> Trusses)? Preview(string rig, string set)
    {
        if (Document(rig, set) is not { } doc) return null;
        var defs = new Dictionary<string, FixtureDefinition?>();
        var els = RigElements.Elements(doc, key =>
        {
            if (!defs.TryGetValue(key, out var d)) defs[key] = d = Definition(key);
            return d;
        });
        return (els, doc.Stage, doc.HasScreen, doc.Trusses);
    }
}
