// A set on a rig: the check after hanging's fixes (two fixtures trading places, a head calibrated; ported from
// mac/Tests/AmadeusKitTests/HangCheckTests.swift), composing a set onto a rig, trusses, zones and definitions.
using System.Text;
using AmadeusKit;

namespace AmadeusKit.Tests;

public class RigModelTests
{
    static RigDocument Document()
    {
        var json = """
            {"stage": {"width_m": 8}, "trusses": [{"id": "front", "type": "quatro", "length_m": 6, "x_m": 4, "y_m": -1, "z_m": 4}],
             "fixtures": [
              {"id": "a", "fixture": "claypaky/sharpy", "mode": "Standard", "universe": 1, "address": 1, "pan_home_deg": 270,
               "truss": "front", "truss_pos_m": -2, "truss_side": "under", "mount": "hang", "x": 0.25, "y_m": -1, "z_m": 3.58},
              {"id": "b", "fixture": "beamz/fuze75b-beam", "mode": "12ch", "universe": 2, "address": 21, "group": "left",
               "truss": "front", "truss_pos_m": 1.5, "truss_side": "top", "mount": "stand", "x": 0.69, "y_m": -1, "z_m": 4.42,
               "rot_deg": 30}]}
            """;
        return new RigDocument("r", "s", Encoding.UTF8.GetBytes(json));
    }

    static IReadOnlyDictionary<string, JSONValue> Fixture(byte[] json, string id) =>
        JSONValue.ParseObject(json)!["fixtures"].Array!.Select(v => v.Object!).First(o => o["id"].String == id);

    [Fact]
    public void SwappedFixturesTradePlacesButKeepTheirPatch()
    {
        var d = Document();
        d.SwapPlacements("a", "b");
        var a = d.Fixtures.First(f => f.Id == "a");
        var b = d.Fixtures.First(f => f.Id == "b");
        Assert.True(a.TrussPos == 1.5 && a.Side == "top" && a.Mount == "stand" && a.RotDeg == 30 && a.X == 0.69);
        Assert.True(b.TrussPos == -2 && b.Side == "under" && b.Mount == "hang" && b.RotDeg == 0);
        Assert.True(a.Universe == 1 && a.Address == 1 && a.Key == "claypaky/sharpy" && b.Address == 21);
        var json = d.Json();
        var ra = Fixture(json, "a");
        var rb = Fixture(json, "b");
        Assert.True(ra.GetValueOrDefault("group")?.String == "left" && !rb.ContainsKey("group"));  // placement fields the editor doesn't model too
        Assert.True(ra["pan_home_deg"].Number == 270 && !rb.ContainsKey("pan_home_deg"));  // calibration stays with the fixture
    }

    [Fact]
    public void ACalibratedHeadIsSavedWithItsFix()
    {
        var d = Document();
        d.Calibrate("a", new Dictionary<string, JSONValue> { ["pan_invert"] = true, ["pan_home_deg"] = 90 });
        var a = Fixture(d.Json(), "a");
        Assert.True(a["pan_invert"].Bool == true && a["pan_home_deg"].Number == 90);
    }

    [Fact]
    public void ACloneIsItsOwn()
    {
        var d = Document();
        var c = d.Clone();
        c.Fixtures[0].X = 0.9;
        c.Trusses[0].XM = 1;
        c.Calibrate("a", new Dictionary<string, JSONValue> { ["pan_invert"] = true });
        Assert.Equal(0.25, d.Fixtures[0].X);
        Assert.Equal(4, d.Trusses[0].XM);
        Assert.False(d.RawFixture("a").ContainsKey("pan_invert"));
    }

    [Fact]
    public void JsonRoundsAndDropsWhatIsNotThere()
    {
        var d = Document();
        d.Fixtures[1].RotDeg = 0;
        d.Fixtures[1].Truss = null;
        d.Fixtures[0].X = 0.123456;
        d.Fixtures[0].Aim = new Vec2(12.34, 45.66);
        var json = d.Json();
        var b = Fixture(json, "b");
        Assert.False(b.ContainsKey("rot_deg"));
        Assert.False(b.ContainsKey("truss_side"));  // no side without a truss
        var a = Fixture(json, "a");
        Assert.Equal(0.1235, a["x"].Number);
        Assert.Equal([12.3, 45.7], a["aim"].Array!.Select(v => v.Number!.Value));
        var text = Encoding.UTF8.GetString(json);
        Assert.Contains("claypaky/sharpy", text);  // slashes unescaped, like .withoutEscapingSlashes
        Assert.True(text.IndexOf("\"fixtures\"", StringComparison.Ordinal) < text.IndexOf("\"stage\"", StringComparison.Ordinal));  // sorted keys
    }

    [Fact]
    public void ComposePutsTheSetOnTheRig()
    {
        var set = JSONValue.ParseObject("""
            {"description": "mine", "stage": {"width_m": 99}, "fixtures": [
              {"id": "p1", "fixture": "x/par", "x": 0.1, "mount": "stand"}, {"id": "p2", "fixture": "x/par"}, {"id": "p3", "fixture": "x/par"}]}
            """u8)!;
        var rig = JSONValue.ParseObject("""
            {"stage": {"width_m": 10}, "trusses": [], "placements": {"s": {"p1": {"x": 0.5, "y_m": -1, "z_m": 3, "mount": "hang"}}}}
            """u8)!;
        var out_ = RigDocument.Compose(set, rig, "s");
        Assert.Equal(10, out_["stage"]["width_m"]!.Number);
        Assert.Equal("mine", out_["description"].String);
        var fx = out_["fixtures"].Array!.Select(v => v.Object!).ToList();
        Assert.Equal("hang", fx[0]["mount"].String);
        Assert.Equal(0.5, fx[0]["x"].Number);
        Assert.False(fx[0].ContainsKey(RigDocument.UnplacedKey));
        // the two without a place wait in a row on the floor at the front
        Assert.Equal(0.3333, fx[1]["x"].Number);
        Assert.Equal(0.6667, fx[2]["x"].Number);
        Assert.Equal("floor", fx[2]["mount"].String);
        Assert.True(fx[1].ContainsKey(RigDocument.UnplacedKey));
        var doc = new RigDocument("r", "s", JSONValue.ToJson(out_));
        Assert.Equal(2, doc.WaitingCount);
        Assert.Equal(new Vec3(5, -1, 3), doc.Fixtures[0].Position(doc.Width));
        Assert.Equal(new Vec3(0, 0, -1), doc.Fixtures[0].Up);
    }

    [Fact]
    public void RingsFollowTheirDiameterAndArc()
    {
        var t = Truss.Ring("ring", diameter: 4, arc: 180, xM: 5, yM: 2, zM: 4);
        Assert.Equal(Math.Round(Math.PI * 2, 3), t.LengthM);
        Assert.True(t.IsRing && !t.IsFullRing);
        var mid = t.Point(0);  // the middle of the arc faces the audience
        Assert.Equal(5, mid.X, 6);
        Assert.Equal(4, mid.Y, 6);
        var (u, dist) = t.Project(new Vec2(5, 4.5));
        Assert.Equal(0, u, 6);
        Assert.Equal(0.5, dist, 6);
        Assert.True(t.Pieces().Count >= 8);
        Assert.Equal("down", t.LightAim);  // over the crowd
        var straight = new Truss("front", 6, 4, -1, 4);
        Assert.Null(straight.LightAim);
        Assert.Equal((2.0, 1.0), straight.Project(new Vec2(6, 0)));
        var back = Truss.From(J.ParseElement(t.ToJSON().ToJson()));
        Assert.Equal(t, back);
    }

    [Fact]
    public void ZonesAreHitByRays()
    {
        var wall = new Zone("w", "Wall", "avoid", "rect", new Vec3(0, 5, 2), [4, 2]);
        Assert.Equal(5, wall.Hit(new Vec3(0, 0, 2), new Vec3(0, 1, 0)));
        Assert.Null(wall.Hit(new Vec3(0, 0, 2), new Vec3(0, -1, 0)));
        Assert.Null(wall.Hit(new Vec3(3, 0, 2), new Vec3(0, 1, 0)));
        var box = new Zone("b", "Crowd", "laser_out", "box", new Vec3(0, 10, 1.5), [10, 10, 3]);
        Assert.Equal(5, box.MarginDeg);
        Assert.Equal(5, box.Hit(new Vec3(0, 0, 1.5), new Vec3(0, 1, 0)));
        Assert.Equal(0, box.Hit(new Vec3(0, 10, 1), new Vec3(0, 0, 1)));  // starting inside
        Assert.Equal(8, box.Corners.Count);
        Assert.Equal(4, wall.Corners.Count);
        Assert.Equal(box, Zone.From(J.ParseElement(box.ToJSON().ToJson())));
    }

    [Fact]
    public void DefinitionsSayWhatTheShowDrives()
    {
        FixtureDefinition Def(string json) => FixtureDefinition.From(J.ParseElement(Encoding.UTF8.GetBytes(json)));
        var smoke = Def("""{"kind": "smoke", "modes": {"2ch": [{"attr": "dimmer"}, {"attr": "other"}]}}""");
        Assert.Contains("smoke machine", smoke.Inert);
        Assert.StartsWith("Not driven by the show", smoke.AddingNote);
        var laser = Def("""{"kind": "laser", "warning": "use a key switch", "modes": {}}""");
        Assert.Contains("laser", laser.Inert);
        Assert.Contains("⚠ use a key switch.", laser.AddingNote);
        Assert.Equal("", Def("""{"kind": "laser", "laser": {}}""").Inert);
        var bar = Def("""
            {"manufacturer": "Ayra", "model": "Bar", "kind": "par_bar", "physical": {"beam_deg": 25, "size_mm": [1200, 300, 140]},
             "modes": {"4ch": [{"attr": "dimmer"}], "16ch": [{"attr": "red", "head": 1}, {"attr": "red", "head": 2}, {"attr": "red", "head": 3},
                       {"attr": "red", "head": 4}], "fx": [{"attr": "macro"}, {"attr": "dimmer", "default": 255}]}}
            """);
        Assert.Equal(4, bar.Cells("16ch"));
        Assert.Equal(1, bar.Cells("4ch"));
        Assert.Equal("16ch", bar.DefaultMode);
        Assert.True(bar.Plays("16ch"));
        Assert.False(bar.Plays("fx"));  // only a macro and a dimmer held at its default
        Assert.Equal(new Vec3(1.2, 0.3, 0.14), bar.Size);
        Assert.Equal(FixtureKind.Par, bar.ElementKind);
        Assert.Equal("Ayra Bar", bar.Name);
        var blacklight = Def("""{"kind": "par", "modes": {"1": [{"attr": "uv", "default": 0}]}}""");
        Assert.True(blacklight.Plays("1"));
    }

    [Fact]
    public void ElementsAreExpandedLikeTheEngine()
    {
        var doc = new RigDocument("r", "s", """
            {"stage": {"width_m": 10}, "fixtures": [{"id": "bar", "fixture": "x/bar", "mode": "16ch", "x": 0.5, "y_m": -1, "z_m": 2},
                                                    {"id": "head", "fixture": "x/head", "mode": "m", "mount": "hang", "x": 0.2}]}
            """u8);
        var defs = new Dictionary<string, FixtureDefinition>
        {
            ["x/bar"] = FixtureDefinition.From(J.ParseElement("""
                {"kind": "par_bar", "physical": {"size_mm": [1000, 100, 100]}, "modes": {"16ch": [{"attr": "red", "head": 1}, {"attr": "red", "head": 2}]}}
                """u8)),
            ["x/head"] = FixtureDefinition.From(J.ParseElement("""{"kind": "moving_head", "physical": {"beam_deg": 3}, "modes": {"m": []}}"""u8)),
        };
        var els = RigElements.Elements(doc, k => defs.GetValueOrDefault(k));
        Assert.Equal(["bar.1", "bar.2", "head"], els.Select(e => e.Id));
        Assert.Equal(4.75, els[0].Pos.X, 6);
        Assert.Equal(5.25, els[1].Pos.X, 6);
        Assert.Equal(2, els[0].Cells);
        Assert.NotNull(els[0].Dir);  // a par shines where it's aimed (up, by default)
        Assert.Equal(FixtureKind.Head, els[2].Kind);
        Assert.Equal(new Vec3(0, 0, -1), els[2].Up);
        Assert.Equal(-1.0, els[2].Pos.Y);  // hang: 1 m behind the stage edge by default
        Assert.Equal(3, els[2].BeamDeg);
    }
}
