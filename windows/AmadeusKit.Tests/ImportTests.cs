// Import from Documents…: the import job's status and the drawings under a rig as the engine sends them
// (amadeus/web/importer.py), the rig editor's drawings (shown or hidden per rig, their opacity, lining one up again,
// taking one away) and where the stage draws them on the floor.
using System.Numerics;
using AmadeusDMX;

namespace AmadeusKit.Tests;

public class ImportTests
{
    const string UnderlayJson = """
        {"id": "u1", "title": "THE MAX stage roof", "source": "plots.pdf page 1 (THE MAX stage roof)",
         "file": "09a7c2f4d86c548ef16d.pdf", "w": 595.32, "h": 841.92, "set": "showcase",
         "a": [0.90741, 0.405], "b": [0.09259, 0.405], "a_m": [0.0, 0.0], "b_m": [14.0, 0.0],
         "fixtures": {"sharpy1": [0.266, 0.305], "gone": [0.345, 0.305]},
         "corners": [[15.591, -9.841], [-1.591, -9.841], [-1.591, 14.458], [15.591, 14.458]]}
        """;

    [Fact]
    public void AnUnderlayDecodes()
    {
        var u = J.DecodeOrThrow(J.Utf8(UnderlayJson), Underlay.From);
        Assert.Equal("u1", u.Id);
        Assert.Equal("THE MAX stage roof", u.Name);
        Assert.Equal("09a7c2f4d86c548ef16d.pdf", u.File);
        Assert.Equal("showcase", u.Set);
        Assert.Equal(new Vec2(0.90741, 0.405), u.A);
        Assert.Equal(new Vec2(0.09259, 0.405), u.B);
        Assert.Equal(14.0, u.WidthM, 6);
        Assert.Equal(new Vec2(0.266, 0.305), u.Fixtures["sharpy1"]);
        Assert.Equal(4, u.Corners.Count);
        Assert.Equal(new Vec2(15.591, -9.841), u.Corners[0]);   // the page's top left: upstage, at stage right
        Assert.Equal(new Vec2(15.591, 14.458), u.Corners[3]);
        // what may be left out
        var bare = J.DecodeOrThrow(J.Utf8("""{"id": "u2", "file": "x.pdf"}"""), Underlay.From);
        Assert.Equal("u2", bare.Name);
        Assert.Empty(bare.Corners);
        Assert.Empty(bare.Fixtures);
        Assert.Throws<System.Text.Json.JsonException>(() => J.DecodeOrThrow(J.Utf8("""{"id": "u3"}"""), Underlay.From));
        // the list the engine answers with
        var list = J.DecodeOrThrow(J.Utf8($$"""{"underlays": [{{UnderlayJson}}]}"""), c => J.Req(c, "underlays", J.ArrayOf(Underlay.From)));
        Assert.Single(list);
    }

    [Fact]
    public void AnImportsStatusDecodesAndItsReportReadsMissingFirst()
    {
        var running = J.DecodeOrThrow(J.Utf8("""{"state": "running", "step": "Reading page 2 of 5…", "notes": [], "name": "max"}"""),
                                      ImportStatus.From);
        Assert.True(running.Running);
        Assert.Equal("Reading page 2 of 5…", running.Step);
        Assert.Null(running.Fixtures);
        var done = J.DecodeOrThrow(J.Utf8("""
            {"state": "done", "step": "Done", "name": "max", "fixtures": 179, "trusses": 12, "underlays": 3,
             "notes": [{"level": "ok", "text": "179 fixtures patched"},
                       {"level": "check", "text": "A near match: Diablo-S", "ids": ["spot1", "spot2"]},
                       {"level": "missing", "text": "No patch for the hazers", "ids": ["haze1"]},
                       {"level": "ok", "text": "12 trusses from the plot"},
                       {"level": "check", "text": "The hall plot's scale is rough"}]}
            """), ImportStatus.From);
        Assert.True(done.Done);
        Assert.Equal((179, 12, 3), (done.Fixtures, done.Trusses, done.Underlays));
        Assert.Equal(["missing", "check", "check", "ok", "ok"], done.Report.Select(n => n.Level));
        Assert.Equal(["No patch for the hazers", "A near match: Diablo-S", "The hall plot's scale is rough", "179 fixtures patched",
                      "12 trusses from the plot"], done.Report.Select(n => n.Text));
        Assert.Equal(["spot1", "spot2"], done.Report[1].Ids);
        Assert.Empty(done.Report[2].Ids);
        var failed = J.DecodeOrThrow(J.Utf8("""{"state": "failed", "step": "…", "notes": [], "name": "max", "error": "No fixtures found in these files"}"""),
                                     ImportStatus.From);
        Assert.True(failed.Failed);
        Assert.Equal("No fixtures found in these files", failed.Error);
    }

    static Underlay U(string id, string set, string file) =>
        J.DecodeOrThrow(J.Utf8(UnderlayJson), Underlay.From) with { Id = id, Set = set, File = file };

    [Fact]
    public async Task TheEditorShowsTheSetsDrawingsAndRemembersWhichAndHowOpaque()
    {
        using var w = new EditorWorkspace();
        var host = new FakeHost { UnderlayList = [U("u1", "showcase", "a.pdf"), U("u2", "other", "b.pdf")] };
        var e = w.Editor();
        await e.LoadDrawings(host);
        Assert.DoesNotContain("underlays showcase", host.Calls);   // the rig file has none: the engine isn't asked
        Assert.Empty(e.StageInput().Drawings);

        var path = w.Ws.RigURL("showcase");
        var rig = JSONValue.ParseObject(File.ReadAllBytes(path))!.ToDictionary(p => p.Key, p => p.Value);
        rig["underlays"] = JSONValue.Of(new[] { JSONValue.Of(new Dictionary<string, JSONValue> { ["id"] = "u1" }) });
        File.WriteAllBytes(path, JSONValue.Of(rig).ToJson());
        await e.LoadDrawings(host);
        Assert.Equal(["u1"], e.Drawings.Select(u => u.Id));        // the set's, not the other set's
        Assert.Equal(["underlays showcase", "page a.pdf"], host.Calls);
        var d = Assert.Single(e.StageInput().Drawings);
        Assert.Equal("a.pdf", d.Key);
        Assert.Equal(0.5f, d.Opacity);
        Assert.Equal(new Vec2(-1.591, 14.458), d.Corners[2]);

        try
        {
            e.DrawingOpacity = 0.25;
            Assert.Equal(0.25f, Assert.Single(e.StageInput().Drawings).Opacity);
            e.SetShown(e.Drawings[0], false);
            Assert.Empty(e.StageInput().Drawings);
            var again = w.Editor();   // remembered for the rig
            await again.LoadDrawings(host);
            Assert.False(again.IsShown(again.Drawings[0]));
            Assert.Equal(0.25, again.DrawingOpacity);
            again.SetShown(again.Drawings[0], true);
            Assert.True(e.IsShown(e.Drawings[0]));
            Assert.False(e.IsDirty);   // none of it is the rig's
        }
        finally
        {
            Defaults.Standard.Remove("rigDrawingsHidden");
            Defaults.Standard.Remove("rigDrawingsOpacity");
        }

        // the rig alone shows every set's drawings
        var alone = w.Editor(set: "");
        await alone.LoadDrawings(host);
        Assert.Equal(["u1", "u2"], alone.Drawings.Select(u => u.Id));

        // taking one away
        await e.RemoveDrawing(host, e.Drawings[0]);
        Assert.Contains("remove u1", host.Calls);
        Assert.Empty(e.Drawings);
    }

    [Fact]
    public async Task LiningUpPostsTheClicksAndReadsTheSavedRig()
    {
        using var w = new EditorWorkspace();
        var host = new FakeHost { UnderlayList = [U("u1", "showcase", "a.pdf")] };
        var e = w.Editor();
        await e.LineUp(host, host.UnderlayList[0], new Vec2(0.8, 0.4), new Vec2(0.2, 0.4), 12);
        Assert.Contains("align u1 0.8,0.4 0.2,0.4 12", host.Calls);
        Assert.Equal("Lined up: 1 fixture moved", e.Message);   // sharpy1 is in the set, "gone" isn't
        Assert.Equal(1, host.Reloads);
        Assert.Equal(new Vec2(0.8, 0.4), Assert.Single(e.Underlays).A);
        // the editor reads the rig the engine saved (here: unchanged), throwing away what wasn't saved
        var x = e.Doc.Trusses[0].XM;
        e.UpdateTruss(e.Doc.Trusses[0].Id, t => t.XM += 1);
        Assert.True(e.IsDirty);
        e.Reload();
        Assert.False(e.IsDirty);
        Assert.Equal(x, e.Doc.Trusses[0].XM);
    }

    // MARK: on the stage floor

    static StageDrawing Drawing(params (double X, double Y)[] corners) =>
        new("a.pdf", new DrawingPicture(2, 2, new byte[16]), [.. corners.Select(c => new Vec2(c.X, c.Y))], 0.5f);

    [Fact]
    public void ADrawingLiesOnTheFloorAtItsCornersAndOnABigStagesDeck()
    {
        // the page's corners on the rig: x from stage left, y towards the audience, as the trusses (world x/y)
        var d = Drawing((10, -6), (0, -6), (0, 4), (10, 4));
        var floor = StageRenderer.DrawingVertices(d, null);
        Assert.Equal(6, floor.Length);   // two triangles
        Assert.All(floor, v => Assert.Equal(StageRenderer.DrawingLift, v.Pos.Z));
        Assert.All(floor, v => Assert.Equal(0.5f, v.Alpha));
        Assert.Contains(floor, v => v.Pos == new Vector3(10, -6, StageRenderer.DrawingLift) && v.Uv == new Vector2(0, 0));
        Assert.Contains(floor, v => v.Pos == new Vector3(0, 4, StageRenderer.DrawingLift) && v.Uv == new Vector2(1, 1));

        // a deck from y -3 to -0.2 (across the whole drawing): the part over it again, on top of it
        var both = StageRenderer.DrawingVertices(d, (-0.5f, 10.5f, -3f, -0.2f, 0.15f));
        var deck = both.Skip(6).ToList();
        Assert.Equal(6, deck.Count);
        Assert.All(deck, v => Assert.Equal(0.15f + StageRenderer.DrawingLift, v.Pos.Z));
        Assert.All(deck, v => Assert.InRange(v.Pos.Y, -3.0001f, -0.1999f));
        // the texture follows the clip: y -3 is 3/10 down the page, -0.2 is 5.8/10
        Assert.Contains(deck, v => MathF.Abs(v.Pos.Y + 3) < 1e-4f && MathF.Abs(v.Uv.Y - 0.3f) < 1e-4f);
        Assert.Contains(deck, v => MathF.Abs(v.Pos.Y + 0.2f) < 1e-4f && MathF.Abs(v.Uv.Y - 0.58f) < 1e-4f);

        // a drawing in front of the stage only: nothing on the deck; too few corners: nothing at all
        Assert.Equal(6, StageRenderer.DrawingVertices(Drawing((10, 1), (0, 1), (0, 4), (10, 4)), (-0.5f, 10.5f, -3f, -0.2f, 0.15f)).Length);
        Assert.Empty(StageRenderer.DrawingVertices(Drawing((0, 0), (1, 0)), null));
    }
}
