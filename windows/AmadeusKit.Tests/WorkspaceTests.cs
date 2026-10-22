// The files the app shares with the engine, in a workspace of its own (a temporary folder): sets, rigs, the
// limiter, integration settings, the DJ software list, finding the engine.
using System.Text;
using AmadeusKit;

namespace AmadeusKit.Tests;

public sealed class TempWorkspace : IDisposable
{
    public string Root { get; } = Directory.CreateTempSubdirectory("amadeus-ws-").FullName;
    public Workspace Ws => new(Root);

    public void Write(string path, string text)
    {
        var full = Path.Combine(Root, path);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        File.WriteAllText(full, text);
    }

    /// A folder that looks like an engine: the package and an (executable) Python.
    public TempWorkspace Engine()
    {
        Write("amadeus/__main__.py", "");
        var py = Workspace.VenvPython(Root);
        Write(Path.GetRelativePath(Root, py), "#!/bin/sh\n");
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(py, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        return this;
    }

    public void Dispose()
    {
        try { Directory.Delete(Root, true); } catch (IOException) { }
    }
}

public class WorkspaceTests
{
    [Fact]
    public void TheConfigStampChangesWhenASetOrRigIsWrittenElsewhere()
    {
        using var t = new TempWorkspace();
        t.Write("config/sets/gear.json", """{"fixtures": []}""");
        t.Write("config/rigs/club.json", """{"stage": {"width_m": 8}}""");
        var ws = t.Ws;
        var before = ws.ConfigStamp();
        Assert.Equal(before, ws.ConfigStamp());
        t.Write("config/rigs/club.json", """{"stage": {"width_m": 10}}""");  // another program (amadeus mcp) saves
        var after = ws.ConfigStamp();
        Assert.NotEqual(before, after);
        t.Write("config/rigs/venue.json", "{}");  // a new rig
        Assert.NotEqual(after, ws.ConfigStamp());
        after = ws.ConfigStamp();
        t.Write("config/active-rig", "venue\n");  // switched
        Assert.NotEqual(after, ws.ConfigStamp());
    }

    [Fact]
    public void TheClaudeDesktopStatusReadsAsTheEngineWritesIt()
    {
        var s = J.Decode(J.Utf8("""{"installed": true, "on": true, "current": false, "config": "C:\\x.json", "problem": ""}"""),
                         ClaudeDesktopStatus.From);
        Assert.Equal(new ClaudeDesktopStatus(true, true, false, "C:\\x.json", ""), s);
    }

    [Fact]
    public void SetsAndRigsAreListed()
    {
        using var t = new TempWorkspace();
        t.Write("config/sets/showcase.json", """
            {"description": "the demo", "director": "openai", "screen": {"w": 4},
             "fixtures": [{"id": "a", "fixture": "beamz/fuze75b-beam"}, {"id": "b", "fixture": "beamz/fuze75b-beam"},
                          {"id": "c", "fixture": "ayra/compar"}],
             "dmx": {"2": {"device": "node2"}, "1": {"device": "node1"}, "10": {"device": "node1"}}}
            """);
        t.Write("config/sets/broken.json", "{not json");
        t.Write("config/sets/old.json", """{"fixtures": [], "artnet": {"ip": "127.0.0.1"}}""");
        t.Write("config/active-set", "showcase\n");
        t.Write("config/rigs/club.json", """
            {"description": "a club", "stage": {"width_m": 12.5}, "screen": false,
             "trusses": [{"id": "t1"}, {"id": "t2"}, {"id": "tower", "vertical": true}], "zones": [{"id": "z"}],
             "placements": {"showcase": {"a": {"x": 0.1}, "b": {"x": 0.2}}}}
            """);
        var ws = t.Ws;
        Assert.Equal(["broken", "old", "showcase"], ws.SetNames());
        Assert.Equal("showcase", ws.ActiveSet);
        var sets = ws.Sets();
        Assert.Equal(["old", "showcase"], sets.Select(s => s.Name));  // a broken file is left out
        var show = sets[1];
        Assert.True(show.IsDefault);
        Assert.Equal(3, show.FixtureCount);
        Assert.Equal([("fuze75b-beam", 2), ("compar", 1)], show.Models);
        Assert.Equal("→ node1, node2", show.OutputText);
        Assert.False(show.IsVirtual);
        Assert.True(show.HasScreen);
        Assert.Equal("openai", show.Director);
        Assert.True(sets[0].IsVirtual);
        Assert.Equal("Art-Net → 127.0.0.1", sets[0].OutputText);

        var rig = Assert.Single(ws.Rigs());
        Assert.Equal(2, rig.Trusses);
        Assert.Equal(1, rig.Towers);
        Assert.False(rig.HasScreen);
        Assert.Equal(2, rig.Mounted["showcase"]);
        Assert.Equal($"{Format.Number(12.5)} m wide · 2 trusses · 1 tower", rig.Summary);
        Assert.Equal((2, 3), ws.Mounted("club", "showcase"));

        var doc = ws.Document("club", "showcase")!;
        Assert.Equal(12.5, doc.Width);
        Assert.Equal(1, doc.WaitingCount);  // c has no place on the club yet
        Assert.Equal("showcase on club", doc.Label);
        Assert.Equal(3, doc.Trusses.Count);
        Assert.Null(ws.Document("club", "missing"));
        Assert.Empty(ws.Document("club", "")!.Fixtures);  // the rig alone
    }

    [Fact]
    public void LegacyOutputsInWords()
    {
        RigFile Set(string json) => RigFile.From(J.ParseElement(Encoding.UTF8.GetBytes(json)));
        Assert.Equal("sACN → multicast + USB ENTTEC Pro → ttyUSB0", Set("""
            {"fixtures": [], "output": [{"type": "sacn"}, {"type": "enttec_pro", "port": "/dev/ttyUSB0"}]}
            """).OutputText);
        Assert.Equal("USB ENTTEC Pro → COM3", Set("""{"fixtures": [], "output": {"type": "enttec_pro", "port": "COM3"}}""").OutputText);
        Assert.Equal("Art-Net → 10.0.0.5", Set("""{"fixtures": [], "artnet": {"ip": "10.0.0.5"}}""").OutputText);
        Assert.Equal("Visualiser only", Set("""{"fixtures": [], "dmx": {}}""").OutputText);
        Assert.False(Set("""{"fixtures": [], "screen": null}""").HasScreen);
        Assert.Throws<System.Text.Json.JsonException>(() => Set("""{"no": "fixtures"}"""));
    }

    [Fact]
    public void TheLimiterIsKeptBetweenFiveAndAHundredPercent()
    {
        using var t = new TempWorkspace();
        var ws = t.Ws;
        Assert.Equal(1, ws.LimiterLevel());
        ws.SetLimiterLevel(0.7);
        Assert.Equal(0.7, ws.LimiterLevel());
        Assert.Equal("""{"level":0.7}""", File.ReadAllText(ws.LimiterFile));
        ws.SetLimiterLevel(0.01);
        Assert.Equal(Workspace.LimiterMinimum, ws.LimiterLevel());
        t.Write("config/limiter.json", """{"level": 7}""");
        Assert.Equal(1, ws.LimiterLevel());
        t.Write("config/limiter.json", "broken");
        Assert.Equal(1, ws.LimiterLevel());
    }

    [Fact]
    public void IntegrationSettingsKeepTheRest()
    {
        using var t = new TempWorkspace();
        t.Write("config/integrations.json", """{"mixxx": {"port": "x"}}""");
        var ws = t.Ws;
        Assert.False(ws.IntegrationSetting("djay", "streamed"));
        ws.SetIntegrationSetting("djay", "streamed", true);
        Assert.True(ws.IntegrationSetting("djay", "streamed"));
        Assert.Contains("\"port\": \"x\"", File.ReadAllText(ws.IntegrationsFile));
    }

    [Fact]
    public void TheDJSoftwareComesFromTheEngine()
    {
        using var t = new TempWorkspace();
        t.Write("amadeus/show/sources/sources.json", """
            [{"name": "vdj", "app": "VirtualDJ", "position": "exact", "verified": "yes", "waiting": "Load a track"},
             {"name": "replay", "app": "Replay", "position": "exact", "verified": "tests", "menu": false}]
            """);
        var ws = t.Ws;
        Assert.Equal(["vdj"], ws.DJSources().Select(s => s.Name));
        Assert.Equal("Replay", ws.DJSource("replay")?.App);
        Assert.Null(ws.DJSource("nope"));
    }

    [Fact]
    public void TheRealSourcesListDecodes()
    {
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));
        var ws = new Workspace(root);
        if (!File.Exists(ws.DJSourcesFile)) return;  // not in a checkout
        Assert.Equal("vdj", ws.DJSources()[0].Name);
    }

    [Fact]
    public void TheEngineIsFound()
    {
        using var engine = new TempWorkspace().Engine();
        using var other = new TempWorkspace();
        Assert.True(engine.Ws.IsValid);
        Assert.False(other.Ws.IsValid);
        Assert.Equal(engine.Root, Workspace.Locate(other.Root, engine.Root, other.Root, null)?.Root);  // a saved folder that isn't one: the baked one
        Assert.Null(Workspace.Locate(null, null, other.Root, null));
        // a checkout around the app (the app built inside it)
        var app = Path.Combine(engine.Root, "windows", "AmadeusDMX", "bin");
        Directory.CreateDirectory(app);
        Assert.Equal(engine.Root, Workspace.Locate(null, null, app, null)?.Root);
        Assert.False(engine.Ws.IsBuiltIn);
        Assert.Equal(new Dictionary<string, string> { ["AMADEUS_ROOT"] = engine.Root }, engine.Ws.Environment);
    }

    [Fact]
    public void TheBuildSaysWhereTheEngineIs()
    {
        using var t = new TempWorkspace();
        Assert.Empty(AppSettings.Read(t.Root));
        t.Write("appsettings.json", """{"AmadeusEngineRoot": "C:\\src\\amadeus", "UpdateFeedUrl": ""}""");
        var s = AppSettings.Read(t.Root);
        Assert.Equal(@"C:\src\amadeus", s["AmadeusEngineRoot"].String);
    }

    [Fact]
    public void TheEngineThatComesWithTheApp()
    {
        using var app = new TempWorkspace();
        using var data = new TempWorkspace();
        app.Write("engine/amadeus/__main__.py", "");
        var runtime = OperatingSystem.IsWindows() ? "runtime/python.exe" : "runtime/bin/python3";
        app.Write(runtime, "#!/bin/sh\n");
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(Path.Combine(app.Root, runtime), UnixFileMode.UserRead | UnixFileMode.UserExecute);
        var ws = Workspace.FromApp(app.Root, Path.Combine(data.Root, "Amadeus DMX"))!;
        Assert.True(ws.IsBuiltIn);
        Assert.True(Directory.Exists(ws.Data));
        Assert.Equal(ws.Data, ws.Environment["AMADEUS_DATA"]);
        Assert.Equal("1", ws.Environment["PYTHONNOUSERSITE"]);
        Assert.Equal(Path.Combine(ws.Data, "config", "sets"), ws.SetsDir);
        Assert.Null(Workspace.FromApp(data.Root, data.Root));
    }

    [Fact]
    public void ThePluginIsInstalledByItsBytes()
    {
        using var t = new TempWorkspace();
        t.Write("ours.dll", "v2");
        var ours = Path.Combine(t.Root, "ours.dll");
        var there = Path.Combine(t.Root, "VirtualDJ", "Plugins64", "SoundEffect", "AmadeusLink.dll");
        Assert.Equal(VirtualDJPlugin.Status.NotInstalled, VirtualDJPlugin.StatusComparedTo(ours, there));
        VirtualDJPlugin.Install(ours, there);
        Assert.Equal(VirtualDJPlugin.Status.UpToDate, VirtualDJPlugin.StatusComparedTo(ours, there));
        File.WriteAllText(ours, "v3");
        Assert.Equal(VirtualDJPlugin.Status.Outdated, VirtualDJPlugin.StatusComparedTo(ours, there));
        Assert.Equal(VirtualDJPlugin.Status.UpToDate, VirtualDJPlugin.StatusComparedTo(null, there));
        Assert.EndsWith(Path.Combine("VirtualDJ", "Plugins64", "SoundEffect", "AmadeusLink.dll"), VirtualDJPlugin.Installed);
    }
}
