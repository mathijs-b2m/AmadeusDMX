// The Set page's patch, the DMX devices window, the wizard's steps and the DMX mapper: their rules, and (with the
// engine's Python) the wizard and the DMX window against the engine's real setup service in a data folder of
// their own.
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using AmadeusKit;
using Xunit.Abstractions;

namespace AmadeusKit.Tests;

public class PatchTests
{
    static Dictionary<string, JSONValue> F(string id, int u, int a, string key = "beamz/fuze75b-beam", string mode = "12ch") =>
        new() { ["id"] = id, ["fixture"] = key, ["mode"] = mode, ["universe"] = u, ["address"] = a };

    static int Channels(string key, string mode) => key switch
    {
        "beamz/fuze75b-beam" => mode == "12ch" ? 12 : 10,
        "bar/pixel" => 100,
        "huge/one" => 600,
        _ => 0,
    };

    static Patch P(params Dictionary<string, JSONValue>[] f) => new(f, Channels);

    [Fact]
    public void FootprintsAndClashes()
    {
        var p = P(F("a", 1, 1), F("b", 1, 13), F("c", 2, 1, "unknown/x", "1ch"));
        Assert.Equal(12, p.Footprint(F("a", 1, 1)));
        Assert.Equal(1, p.Footprint(F("c", 2, 1, "unknown/x", "1ch")));  // unknown counts as one channel
        Assert.Equal(["a"], p.Clashes(1, 12, 1, new HashSet<string>()));
        Assert.Equal(["a", "b"], p.Clashes(1, 10, 5, new HashSet<string>()));
        Assert.Empty(p.Clashes(1, 25, 12, new HashSet<string>()));
        Assert.Empty(p.Clashes(1, 1, 12, new HashSet<string> { "a" }));
        Assert.Equal(["c"], p.Clashes(2, 1, 1, new HashSet<string>()));
    }

    [Fact]
    public void NextFreeFindsTheFirstGapThatFits()
    {
        var p = P(F("a", 1, 1), F("b", 1, 20), F("c", 1, 40));
        Assert.Equal(52, p.Free(1, 12, new HashSet<string>()));      // 13..19 is too short for 12, 32..39 too
        Assert.Equal(13, p.Free(1, 7, new HashSet<string>()));
        Assert.Equal(1, p.Free(1, 12, new HashSet<string> { "a" }));  // its own channels are free for itself
        Assert.Equal(501, P().Free(1, 12, new HashSet<string>(), from: 501));
        Assert.Null(P().Free(1, 12, new HashSet<string>(), from: 502));  // 502 + 11 > 512
        Assert.Equal(0, Patch.Overflow(501, 12));
        Assert.Equal(3, Patch.Overflow(504, 12));
        Assert.Equal("1.007", Patch.Where(1, 7));
    }

    [Fact]
    public void PatchInARowGoesAroundOthersAndOnToTheNextUniverse()
    {
        var fixtures = new[] { F("x", 1, 30), F("h1", 1, 1), F("h2", 1, 1), F("h3", 1, 1), F("full", 2, 1, "bar/pixel") };
        var p = P(fixtures);
        var sel = p.Selected(new HashSet<string> { "h3", "h1", "h2" });
        var row = p.InRow(sel, 20);
        // 20..31 clashes with x (30..41): from 42 on
        Assert.Equal((1, 42), row[sel[0].GetValueOrDefault("id")!.String!]);
        Assert.Equal(new[] { (1, 42), (1, 54), (1, 66) }, sel.Select(f => row[Patch.Id(f)]).ToArray());
        var late = p.InRow(sel, 495);
        Assert.Equal((1, 495), late[Patch.Id(sel[0])]);
        Assert.Equal((2, 101), late[Patch.Id(sel[1])]);  // 507 + 11 > 512: universe 2, after the 100-channel bar
        Assert.Equal((2, 113), late[Patch.Id(sel[2])]);
        // a fixture larger than a universe never hangs the loop
        var huge = P(F("big", 1, 1, "huge/one"));
        Assert.Equal((1, 1), huge.InRow(huge.Selected(new HashSet<string> { "big" }), 1)["big"]);
    }

    [Fact]
    public void NewFixturesGetFreeAddressesAndNamesOfTheirOwn()
    {
        Assert.Equal("fuze", Patch.BaseName("beamz/fuze75b-beam"));
        Assert.Equal("fx", Patch.BaseName("acme/75x"));
        var p = P(F("fuze1", 1, 1), F("fuze3", 1, 25));
        var added = p.NewFixtures("beamz/fuze75b-beam", "12ch", 3);
        Assert.Equal(["fuze2", "fuze4", "fuze5"], added.Select(Patch.Id));
        Assert.Equal([13, 37, 49], added.Select(Patch.Address));
        var full = P(Enumerable.Range(0, 42).Select(i => F($"fuze{i + 1}", 1, 1 + 12 * i)).ToArray());
        var next = full.NewFixtures("beamz/fuze75b-beam", "12ch", 1).Single();
        Assert.Equal(2, Patch.Universe(next));  // 42 × 12 = 504: no 12 channels left in universe 1
        Assert.Equal(1, Patch.Address(next));
    }

    [Fact]
    public void LayoutsKeepWhatTheyDontTouch()
    {
        var layout = new Dictionary<string, JSONValue>
        {
            ["fixtures"] = JSONValue.Of([JSONValue.Of(F("a", 1, 1))]), ["artnet"] = JSONValue.Of(new Dictionary<string, JSONValue> { ["ip"] = "2.0.0.10" }),
        };
        var all = SetLayout.Fixtures(layout);
        SetLayout.Change(all, "a", f => { f["address"] = 100; f["pan_invert"] = true; });
        SetLayout.Change(all, "nobody", f => f["address"] = 1);
        var changed = SetLayout.WithFixtures(layout, all);
        Assert.Equal(100, changed["fixtures"].Array![0]["address"]!.Number);
        Assert.Equal(true, changed["fixtures"].Array![0]["pan_invert"]!.Bool);
        Assert.Equal("2.0.0.10", changed["artnet"]["ip"]!.String);
        Assert.Equal(1, layout["fixtures"].Array![0]["address"]!.Number);  // the original stays as it was
    }
}

public class DMXModelTests
{
    static Dictionary<string, JSONValue> Layout(string? dmx = null)
    {
        var json = $$"""
            {"fixtures": [{"id": "a", "universe": 1}, {"id": "b", "universe": 1}, {"id": "c", "universe": 3}, {"id": "d"}]
             {{(dmx is null ? "" : ", \"dmx\": " + dmx)}}}
            """;
        return JSONValue.ParseObject(J.Utf8(json))!;
    }

    [Fact]
    public void UniversesAndRoutesComeFromTheSet()
    {
        var m = new DMXModel();
        m.ReadLayout(Layout(), "Art-Net → 127.0.0.1");
        Assert.Equal([(1, 3), (3, 1)], m.Universes);
        Assert.Equal("Art-Net → 127.0.0.1", m.Legacy);
        Assert.Equal(new DMXModel.Route(null, 3), m.RouteOf(3));  // not mapped: nowhere, its own number as output

        m.ReadLayout(Layout("""{"1": {"device": "node", "output": 2}, "x": {}}"""), "ignored");
        Assert.Null(m.Legacy);
        Assert.Equal(new DMXModel.Route("node", 2), m.RouteOf(1));
    }

    [Fact]
    public void DevicesAreAddedWithIdsOfTheirOwnAndTargetsInTheirNumbering()
    {
        var m = new DMXModel();
        m.ReadLayout(Layout(), null);
        m.Add(DMXModel.NewArtNet());
        m.Add(DMXModel.NewArtNet());
        m.Add(DMXModel.NewSACN());
        m.AddUSB(new USBInterface("COM3", "", null, true, "EN123", null));
        Assert.Equal(["node", "node-2", "sacn", "usb"], m.Devices.Select(d => d.Id));
        Assert.Equal("usb", m.Selection);
        Assert.Equal("USB DMX interface", m.Devices[^1].Name);
        Assert.Equal("EN123", m.Devices[^1].Serial);
        Assert.True(m.HasChanges);

        m.SetRoute(1, new DMXModel.Route("node-2", 2));
        m.SetRoute(3, new DMXModel.Route("sacn", 3));
        Assert.Equal("Art-Net universe 1", m.Target(1));  // first output universe 0
        Assert.Equal("sACN universe 3", m.Target(3));
        m.SetRoute(5, new DMXModel.Route("usb", 1));
        Assert.Equal("USB output", m.Target(5));
        m.SetRoute(6, new DMXModel.Route("gone", 1));
        Assert.Null(m.Target(6));

        var block = m.DmxBlock();
        Assert.Equal(["1", "3", "5"], block.Keys);  // a route to a device you don't have isn't saved
        Assert.Equal("node-2", block["1"]["device"]!.String);
        Assert.Equal(2, block["1"]["output"]!.Number);

        m.Remove("node-2");
        Assert.Equal(new DMXModel.Route(null, 2), m.RouteOf(1));  // its output number stays
        Assert.Equal("node", m.Selection);
    }

    [Fact]
    public void FoundDevicesAreThoseYouDontHaveYet()
    {
        var m = new DMXModel();
        m.AddNode(new ArtNetNode("2.0.0.10", "NET-2/3 Pocket", "", 2));
        Assert.Equal("net-2-3-pocket", m.Devices[0].Id);
        Assert.Equal("NET-2/3 Pocket", m.Devices[0].Name);
        Assert.Equal("device", DMXModel.Slug("!!"));
    }
}

public class WizardModelTests
{
    static CatalogEntry Entry(string key, string type = "moving head", Dictionary<string, int>? modes = null) =>
        new() { Key = key, Manufacturer = "beamZ", Model = "Fuze75B Beam", Type = type, Source = "local", Modes = modes };

    [Fact]
    public void StepsMoveOnOnlyWhenTheirPartIsDone()
    {
        var w = new WizardModel(new Defaults(null, []));
        Assert.Equal(WizardStep.Welcome, w.Step);
        Assert.Equal(WizardStep.Network, w.NextStep(engineValid: true, hasSets: true));  // a new set: the engine is there
        Assert.Equal(WizardStep.Engine, w.NextStep(engineValid: true, hasSets: false));    // the first launch
        w.Step = WizardStep.Fixtures;
        Assert.False(w.CanContinue);
        w.Results = [Entry("beamz/fuze75b-beam")];
        Assert.False(w.CanContinue);
        w.Step = WizardStep.Network;
        Assert.True(w.CanContinue);  // the visualiser only
        w.OutputKind = WizardModel.Output.Node;
        Assert.False(w.CanContinue);  // no node chosen
        w.ChosenNodes = [new ArtNetNode("2.0.0.10", "node", null, 2)];
        Assert.True(w.CanContinue);
        w.Step = WizardStep.Rig;
        w.RigName = "  ";
        Assert.False(w.CanContinue);
        w.UseExistingRig = true;
        Assert.False(w.CanContinue);
        w.ExistingRig = "club";
        Assert.True(w.CanContinue);
        w.Step = WizardStep.Review;
        w.Name = "";
        Assert.False(w.CanContinue);
        Assert.Equal(WizardStep.Director, w.PreviousStep);
        w.Step = WizardStep.Done;
        Assert.Equal(WizardStep.Done, w.NextStep(true, true));
        Assert.Equal(WizardStep.Network, new WizardModel(new Defaults(null, ["x", "-wizardStep", "dmx output"])).Step);
        Assert.Equal(WizardModel.Output.Usb, new WizardModel(new Defaults(null, ["x", "-wizardStep", "network"])).OutputKind);
    }

    [Fact]
    public async Task TheFixturesAreCountedInUniversesAgainstTheOutput()
    {
        var w = new WizardModel(new Defaults(null, []));
        Assert.Equal(0, w.UniversesNeeded);
        Assert.False(w.HasSomethingToSave);
        // 40 × 14 channels: 36 fit in 512 (a fixture never straddles two universes), 4 more in the second
        await w.Add(Entry("k", modes: new() { ["14ch"] = 14, ["8ch"] = 8 }), new SetupAPI(1));  // modes known: no request
        var p = w.Planned.Single();
        Assert.Equal("14ch", p.Mode);
        p.Count = 40;
        Assert.Equal(14, p.Footprint);
        Assert.Equal(2, w.UniversesNeeded);
        Assert.True(w.HasSomethingToSave);
        p.Mode = "8ch";
        Assert.Equal(1, w.UniversesNeeded);
        Assert.Null(w.UniversesAvailable);  // the visualiser
        w.OutputKind = WizardModel.Output.Usb;
        Assert.Equal(1, w.UniversesAvailable);
        w.OutputKind = WizardModel.Output.Node;
        Assert.Null(w.UniversesAvailable);  // no node yet
        w.ChosenNodes = [new ArtNetNode("2.0.0.10", "a", null, 2), new ArtNetNode("2.0.0.11", "b", null, 4)];
        Assert.Equal(6, w.UniversesAvailable);
        Assert.Equal("2.0.0.10", w.Node!.Ip);
        Assert.Equal("Art-Net → 2 nodes (2.0.0.10, 2.0.0.11)", w.OutputText);
        w.ChosenNodes = [new ArtNetNode("2.0.0.10", "a", null, null)];
        Assert.Null(w.UniversesAvailable);  // outputs not known
        w.Sacn = true;
        Assert.Null(w.UniversesAvailable);  // multicast: no limit
    }

    [Fact]
    public void TheTemplateSizesTheRigAndNamesItUntilYouDo()
    {
        var w = new WizardModel(new Defaults(null, []));
        Assert.Equal((10.0, 4.5, 15.0), (w.Width, w.Height, w.Depth));
        Assert.True(w.LedWall);
        w.Template = RigTemplate.Floor;
        Assert.Equal("floor", w.RigName);
        Assert.Equal(4, w.Width);
        Assert.False(w.LedWall);
        w.RigName = "paradiso";
        w.Template = RigTemplate.Stage;
        Assert.Equal("paradiso", w.RigName);
        Assert.True(w.LedWall);
        Assert.Equal("my-club", WizardModel.Safe("  My Club!! "));
        Assert.Equal("a_b-c", WizardModel.Safe("A_B c"));
    }

    [Fact]
    public void TheOutputGoesIntoTheSet()
    {
        var w = new WizardModel(new Defaults(null, []));
        Assert.Null(w.OutputSpec);
        Assert.Equal("Visualiser only", w.OutputText);
        Assert.Equal("127.0.0.1", w.ArtnetIP);
        w.OutputKind = WizardModel.Output.Manual;
        Assert.Equal("Art-Net → 2.0.0.10", w.OutputText);
        Assert.Null(w.OutputSpec);  // Art-Net: the artnet block's ip, as sets always did
        w.Sacn = true;
        Assert.Equal("sacn", w.OutputSpec!["type"].String);
        Assert.False(w.OutputSpec.ContainsKey("ip"));
        Assert.Equal("sACN → multicast", w.OutputText);
        w.Multicast = false;
        Assert.Equal("2.0.0.10", w.OutputSpec!["ip"].String);
        w.OutputKind = WizardModel.Output.Usb;
        Assert.Equal("USB ENTTEC Pro → first one found", w.OutputText);
        w.UsbPort = "COM4";
        Assert.Equal("COM4", w.OutputSpec!["port"].String);
        Assert.Equal("USB ENTTEC Pro → COM4", w.OutputText);

        var layout = new Dictionary<string, JSONValue> { ["output"] = "old", ["stage"] = JSONValue.Of(new Dictionary<string, JSONValue>()) };
        w.OutputKind = WizardModel.Output.Node;
        w.Sacn = false;
        w.ChosenNodes = [new ArtNetNode("2.0.0.20", "n", null, 2)];
        w.Director = "openai";
        w.Compose(layout, [JSONValue.Of(new Dictionary<string, JSONValue> { ["id"] = "fuze1", ["fixture"] = "k", ["address"] = 1, ["x"] = 0.2, ["mount"] = "stand" })]);
        Assert.False(layout.ContainsKey("output"));
        Assert.Equal("2.0.0.20", layout["artnet"]["ip"]!.String);
        Assert.Equal(6454, layout["artnet"]["port"]!.Number);
        Assert.Equal("openai", layout["director"].String);
        var f = layout["fixtures"].Array!.Single().Object!;
        Assert.Equal(["id", "fixture", "address"], f.Keys);  // where it hangs is the rig's
        Assert.True(layout.ContainsKey("stage"));
    }
}

public class MapperAndSettingsTests
{
    static FixtureMapping Mapping() => J.DecodeOrThrow(J.Utf8("""
        {"key": "acme/fx", "name": "Acme FX", "mode": "4ch", "kind": "effect", "kinds": {"par": "Par", "moving_head": "Moving head"},
         "roles": [{"role": "dimmer", "label": "Dimmer", "group": "Light", "cell": false},
                   {"role": "red", "label": "Red", "group": "Colour", "cell": true},
                   {"role": "pan", "label": "Pan", "group": "Position", "cell": false}],
         "channels": [{"n": 1, "attr": "", "role": "dimmer", "cell": 0, "value": 0, "name": "Dim", "ranges": [[0, 255, "dim"]]},
                      {"n": 2, "attr": "", "role": "pan", "cell": 0, "value": 128, "name": "Pan", "ranges": []},
                      {"n": 3, "attr": "macro", "role": "keep", "cell": 0, "value": 10, "name": "Macro", "ranges": []},
                      {"n": 4, "attr": "", "role": "red", "cell": 1, "value": 0, "name": "R1", "ranges": []}],
         "plays": false, "mapped": false, "refusal": ""}
        """), FixtureMapping.From);

    [Fact]
    public void TheMapperEditsACopy()
    {
        var m = new MapperModel { Mapping = Mapping() };
        Assert.True(m.Editable);
        Assert.Equal([("effect", "Effect"), ("moving_head", "Moving head"), ("par", "Par")], MapperModel.KindChoices(m.Mapping!));
        Assert.Equal(["Colour", "Light", "Position"], MapperModel.Groups(m.Mapping!).Select(g => g.Group));
        Assert.Equal([0, 3], m.Light);  // dimmer and red, not pan, not the kept macro
        m.SetValue(0, 300);
        m.SetCell(3, 70);
        m.SetRole(2, "hold");
        m.SetKind("par");
        Assert.Equal([255, 128, 10, 0], m.Raw);
        Assert.Equal(64, m.Mapping!.Channels[3].Cell);
        Assert.Equal("hold", m.Mapping.Channels[2].Role);
        Assert.Equal("par", m.Mapping.Kind);
        Assert.Equal(new[] { 255, 128, 10, 0 }, m.Raw);
        m.Mapping = m.Mapping with { Refusal = "a laser" };
        Assert.False(m.Editable);
    }

    [Fact]
    public void DirectorsKeysPortsAndVersions()
    {
        Assert.Equal(DirectorKind.Local, DirectorKinds.Of("ollama:nimble"));
        Assert.Equal(DirectorKind.OpenAI, DirectorKinds.Of("openai"));
        Assert.Equal(DirectorKind.Rules, DirectorKinds.Of("whatever"));
        Assert.Equal("sk-proj-…WXYZ", KeySource.Masked("sk-proj-abcdefghijklmnopWXYZ"));
        Assert.Equal("sk-…WXYZ", KeySource.Masked("sk-abcdefghijWXYZ"));
        Assert.Equal("…", KeySource.Masked("sk-short"));
        Assert.Equal(KeySource.Kind.Stored, KeySource.Current("sk-x", null).Where);
        Assert.Equal(KeySource.Kind.None, KeySource.Current("", null).Where);
        using var t = new TempWorkspace();
        t.Write(".env", "OPENAI_API_KEY=sk-env\n");
        Assert.Equal(KeySource.Kind.EnvFile, KeySource.Current(null, t.Ws).Where);

        Assert.Equal(1, MixxxPort.Matching(["Microsoft GS", "Amadeus DMX"]));
        Assert.Equal(0, MixxxPort.Matching(["Amadeus DMX 1"]));
        Assert.Equal(1, MixxxPort.Matching(["loopMIDI", "IAC Amadeus DMX"]));
        Assert.Null(MixxxPort.Matching(["Amadeus"]));

        Assert.Equal(412, UpdateVersions.BuildNumber(new Version(0, 3, 0, 412)));
        Assert.Equal(0, UpdateVersions.BuildNumber(new Version(1, 2)));
        Assert.True(UpdateVersions.IsNewer("413", 412));
        Assert.False(UpdateVersions.IsNewer("412", 412));
        Assert.False(UpdateVersions.IsNewer("0.3.1", 412));  // only build numbers compare
        Assert.True(UpdateVersions.IsPrerelease("0.4.0-beta.1"));
        Assert.False(UpdateVersions.IsPrerelease("0.4.0"));
        Assert.Equal("Concert Stage", RigTemplate.Stage.Title());
        Assert.True(RigTemplates.IsDefaultName("club2"));
        Assert.False(RigTemplates.IsDefaultName("paradiso"));
    }
}

/// The wizard and the DMX window against the engine's setup service (skipped without the engine's Python).
public sealed class SetupServiceTests(ITestOutputHelper output)
{
    sealed class Host(SetupAPI api, Workspace ws) : IWizardHost
    {
        public SetupAPI Api => api;
        public Task<bool> EnsureSetupService() => api.IsUp();
        public IReadOnlyList<SetSummary> Sets { get; private set; } = ws.Sets();
        public IReadOnlyList<RigSummary> Rigs { get; private set; } = ws.Rigs();
        public void ReloadSets() { Sets = ws.Sets(); Rigs = ws.Rigs(); }
        public Workspace? Workspace => ws;
        public string? Editing;
        public void Edit(string set) => Editing = set;
        public (string Rig, string Set)? Selected;
        public void Select(string rig, string set) => Selected = (rig, set);
    }

    static int FreePort()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        var port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return port;
    }

    [Fact]
    public async Task TheWizardMakesASetOnARigAndTheDMXWindowRoutesIt()
    {
        if (LinkTests.EnginePython() is not { } python) { output.WriteLine("no engine Python: skipped"); return; }
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));
        using var data = new TempWorkspace();
        var port = FreePort();
        var psi = new ProcessStartInfo(python)
        {
            WorkingDirectory = root, RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = true,
        };
        foreach (var a in new[] { "-m", "amadeus", "setup", "--port", port.ToString() }) psi.ArgumentList.Add(a);
        psi.Environment["AMADEUS_DATA"] = data.Root;
        psi.Environment["AMADEUS_ROOT"] = root;
        using var p = Process.Start(psi)!;
        try
        {
            var api = new SetupAPI(port);
            var up = false;
            for (var i = 0; i < 120 && !up && !p.HasExited; i++) { up = await api.IsUp(); if (!up) await Task.Delay(250); }
            if (!up) { output.WriteLine("the setup service didn't start: skipped"); return; }
            var ws = new Workspace(root, data.Root, python);
            var host = new Host(api, ws);

            var w = new WizardModel(new Defaults(null, []));
            await w.Search(api);
            Assert.Empty(w.Results);  // fewer than 2 letters: no search
            w.Query = "fuze75b";
            await w.Search(api);
            var fuze = w.Results.First(e => e.Key == "beamz/fuze75b-beam");
            await w.Add(fuze, api);
            Assert.Equal(4, w.Planned.Single().Count);  // a moving head: four
            Assert.Equal("12ch", w.Planned.Single().Mode);  // the most channels first
            w.Name = "Wizard Test";
            w.Template = RigTemplate.Booth;
            w.OutputKind = WizardModel.Output.Manual;
            w.ManualIP = "2.0.0.30";
            await w.Create(host);
            Assert.Null(w.Error);
            Assert.Equal(WizardStep.Done, w.Step);
            Assert.Equal(("booth", "wizard-test"), host.Selected);
            var set = ws.LoadSet("wizard-test")!;
            Assert.Equal(4, set.Fixtures.Count);
            Assert.Equal([1, 13, 25, 37], set.Fixtures.Select(f => f.Address ?? 0));
            Assert.Equal("2.0.0.30", set.Artnet?.Ip);
            Assert.Equal((4, 4), ws.Mounted("booth", "wizard-test"));

            await w.Create(host);
            Assert.Contains("already exists", w.Error);

            // Add Fixtures…: two more, after what is patched; saved as the set alone
            var layout = SetLayout.Parse(ws.Composed("", "wizard-test"))!;
            var fixtures = SetLayout.Fixtures(layout);
            var patch = new Patch(fixtures, Patch.ChannelsFrom(ws.Definition));
            fixtures.AddRange(patch.NewFixtures("beamz/fuze75b-beam", "12ch", 2));
            await api.SaveSet(SetLayout.WithFixtures(layout, fixtures), "wizard-test");
            Assert.Equal(["fuze5", "fuze6"], ws.LoadSet("wizard-test")!.Fixtures.Skip(4).Select(f => f.Id));
            Assert.Equal([49, 61], ws.LoadSet("wizard-test")!.Fixtures.Skip(4).Select(f => f.Address ?? 0));

            // the address became a DMX device, universe 1 on its first output
            Assert.Equal("→ node", ws.LoadSet("wizard-test")!.OutputText);

            // the DMX Output page: another node, universe 1 on its second output
            var dmx = new DMXModel();
            await dmx.Load(api, "wizard-test", "booth", ws.LoadSet("wizard-test")!.OutputText);
            Assert.Null(dmx.Legacy);  // mapped to a device already
            Assert.Equal(new DMXModel.Route("node", 1), dmx.RouteOf(1));
            Assert.Equal("Node 2.0.0.30", dmx.Device("node")!.Name);
            Assert.Equal([(1, 6)], dmx.Universes);
            dmx.Add(DMXModel.NewArtNet());
            dmx.SetRoute(1, new DMXModel.Route("node-2", 2));
            Assert.True(await dmx.Save(api, showRunning: false));
            Assert.Equal("Saved.", dmx.Message);
            Assert.Equal("→ node-2", ws.LoadSet("wizard-test")!.OutputText);
            var again = new DMXModel();
            await again.Load(api, "wizard-test", "booth", null);
            Assert.Equal(new DMXModel.Route("node-2", 2), again.RouteOf(1));
            Assert.Equal("Art-Net universe 1", again.Target(1));

            // Save and Close: the planned fixtures as a set of their own (a free name), the output as devices
            var later = new WizardModel(new Defaults(null, [])) { Name = "Wizard Test" };
            await later.Add(fuze, api);
            later.OutputKind = WizardModel.Output.Manual;
            later.ManualIP = "2.0.0.30";
            Assert.True(later.HasSomethingToSave);
            var note = await later.SaveAndClose(host);
            Assert.Null(later.Error);
            Assert.Contains("**wizard-test-2**", note);
            Assert.Equal("wizard-test-2", host.Editing);
            Assert.Equal(4, ws.LoadSet("wizard-test-2")!.Fixtures.Count);
            Assert.Equal("→ node", ws.LoadSet("wizard-test-2")!.OutputText);  // the device there already
        }
        finally
        {
            try { p.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
        }
    }
}

public class DJSourceWindowsTests
{
    [Fact]
    public void WindowsBlockOverridesOnWindowsOnly()
    {
        using var doc = System.Text.Json.JsonDocument.Parse(
            """{"name":"vdj","app":"VirtualDJ","position":"exact","verified":"macOS","waiting":"Load a track.","windows":{"verified":"not yet on Windows"}}""");
        Assert.Equal("not yet on Windows", DJSource.From(doc.RootElement, windows: true).Verified);
        Assert.Equal("macOS", DJSource.From(doc.RootElement, windows: false).Verified);
        Assert.Equal("Load a track.", DJSource.From(doc.RootElement, windows: true).Waiting);
    }
}
