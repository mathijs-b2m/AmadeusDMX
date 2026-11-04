// A scaffold (a wall of tube) as amadeus/rig/trusses.py has it (mac/Tests/AmadeusKitTests/ScaffoldTests.swift;
// tests/test_scaffold.py asks the engine the same), and what the Windows editor and stage do with one.
using System.Numerics;
using System.Text;
using AmadeusDMX;

namespace AmadeusKit.Tests;

public class ScaffoldTests
{
    static readonly Vector3 Down = new(0, 0, -1);
    static readonly Vector3 Upstage = new(0, -1, 0);
    static Vector3 Above(double x, double y) => new((float)x, (float)y, 30);
    /// A ray from the audience, level, at this height.
    static Vector3 FromTheFront(double x, double z) => new((float)x, 30, (float)z);
    static PlacedFixture Fx(RigEditorModel e, string id) => e.Doc.Fixtures.First(f => f.Id == id);

    [Fact]
    public void ItsHeadsPlayToTheAudience()
    {
        var t = Truss.Scaffold("w", 16, 9, 8, -7);
        Assert.Equal("audience", t.LightAim);
    }

    [Fact]
    public void SharesItsSizeIntoBaysAndLifts()
    {
        var t = Truss.Scaffold("w", width: 16, height: 9, xM: 8, yM: -7);
        Assert.True(t.IsScaffold && !t.IsStand && !t.IsLoop);
        Assert.Equal(6, t.ScaffoldBays);
        Assert.Equal(9, t.ScaffoldLifts);
        Assert.Equal(3, t.LiftHeight(3));
        Assert.Equal(4, t.NearestLift(4.2));
        Assert.Equal(1, t.NearestLift(0));
        Assert.Equal(9, t.NearestLift(30));
    }

    [Fact]
    public void LedgersAreOnItsFrontFrame()
    {
        var t = Truss.Scaffold("w", width: 16, height: 9, xM: 8, yM: -7);
        var l = t.Ledger(4);
        Assert.Equal(-6.5, l.YM);
        Assert.Equal(4, l.ZM);
        Assert.True(l.IsTube && !l.IsScaffold);
        Assert.Equal("w", l.Id);
        Assert.Equal(9, t.Ledger(40).ZM);
        Assert.Equal(9, t.Pieces().Count);
    }

    [Fact]
    public void TheWidestFacingTheAudienceCarriesTheScreen()
    {
        var side = Truss.Scaffold("s", width: 30, height: 9, xM: 0, yM: -3);
        side.RotDeg = 90;
        var back = Truss.Scaffold("b", width: 16, height: 9, xM: 8, yM: -7);
        Assert.Equal("b", Truss.ScreenWall([side, back])?.Id);
        Assert.Null(Truss.ScreenWall([side]));
    }

    [Fact]
    public void ItsSizesSurviveASaveAndTheStageItsTube()
    {
        var json = """{"id": "w", "type": "scaffold", "length_m": 12, "x_m": 6, "y_m": -7, "z_m": 6, "depth_m": 1.5, "bay_m": 2, "lift_m": 1.5}""";
        var t = Truss.From(J.ParseElement(Encoding.UTF8.GetBytes(json)));
        Assert.Equal((6, 4), (t.ScaffoldBays, t.ScaffoldLifts));
        Assert.Equal(1.5, t.ScaffoldDepth);
        var o = t.ToJSON().Object!;
        Assert.Equal(2, o["bay_m"].Number);
        Assert.Equal(1.5, o["lift_m"].Number);
        Assert.Equal(t, Truss.From(t.ToJSON()));

        var stage = J.DecodeOrThrow(new Stage { DeckM = 1, DeckScaffold = true }.ToJSON().ToJson(), Stage.From);
        Assert.True(stage.DeckScaffold);
        Assert.False(J.DecodeOrThrow(new Stage().ToJSON().ToJson(), Stage.From).DeckScaffold);
    }

    [Fact]
    public void AFixtureClampsToItsLedgerLikeToATube()
    {
        var t = Truss.Scaffold("w", width: 16, height: 9, xM: 8, yM: -7);
        var f = new PlacedFixture("a", "k", "m", 1, 1, "hang", 0.5, 0, 3, 0, null, null, null);
        RigEditorModel.Place(f, t, 2, 16);  // new here: the top one
        Assert.Equal(("w", 9), (f.Truss, f.TrussLift));
        Assert.Equal(9 - RigEditorModel.TubeDrop, f.ZM, 9);
        Assert.Equal(-6.5, f.YM, 9);
        Assert.Equal(10.0 / 16, f.X, 9);
        f.TrussLift = 3;
        f.Side = "front";
        RigEditorModel.Place(f, t, 2, 16);
        Assert.Equal(3, f.TrussLift);
        Assert.Equal(3, f.ZM, 9);
        Assert.Equal(-6.5 + RigEditorModel.TubeOut, f.YM, 9);
        RigEditorModel.Place(f, new Truss("bar", 4, 8, -1, 5), 0, 16);  // off it: no ledger any more
        Assert.Null(f.TrussLift);
    }

    [Fact]
    public void ItsLiftIsPartOfThePlacement()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(8, 5);
        var t = e.Doc.Trusses.Single(x => x.IsScaffold);
        e.Select(["sharpy2"]);
        e.Attach("sharpy2", t.Id);
        e.SetLift(e.SelectedFixtures, 2);
        Assert.Equal(2, Fx(e, "sharpy2").TrussLift);
        Assert.Equal(2 - RigEditorModel.TubeDrop, Fx(e, "sharpy2").ZM, 6);

        var saved = new RigDocument("r", "s", e.Doc.Json());  // written and read back
        Assert.Equal(2, saved.Fixtures.First(f => f.Id == "sharpy2").TrussLift);
        Assert.Contains("truss_lift", RigDocument.PlacementKeys);

        saved.SwapPlacements("sharpy2", "sharpy3");  // it trades places with the rest
        Assert.Equal(2, saved.Fixtures.First(f => f.Id == "sharpy3").TrussLift);
        Assert.Null(saved.Fixtures.First(f => f.Id == "sharpy2").TrussLift);

        e.Unmount(new HashSet<string> { "sharpy2" });  // off the rig: not written
        var o = e.Doc.JsonObject()["fixtures"].Array!.Select(v => v.Object!).First(f => f["id"].String == "sharpy2");
        Assert.False(o.ContainsKey("truss_lift"));
    }

    [Fact]
    public void AddedAtTheBackOfTheStageEachOneFurtherBackUnderTheCeiling()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(16, 9);
        e.AddScaffold(8, 5);
        var walls = e.Doc.Trusses.Where(x => x.IsScaffold).ToList();
        Assert.Equal(-7, walls[0].YM);  // the stage is 12 m wide
        Assert.Equal(-9, walls[1].YM);
        Assert.Equal(7.7, walls[0].ZM, 6);  // an 8 m ceiling
        Assert.Equal(5, walls[1].ZM);
        Assert.Equal(EditorSelection.Truss(walls[1].Id), e.Selection);
    }

    [Fact]
    public void AFixtureDraggedOverItsFrontGoesUpAndDownItsLedgers()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(8, 5);
        var t = e.Doc.Trusses.Single(x => x.IsScaffold);
        e.Unmount(new HashSet<string> { "sharpy2" });
        var p = Fx(e, "sharpy2").Position(e.Doc.Width);
        Assert.True(e.Pick(Above(p.X, p.Y), Down, false));
        e.Drag(FromTheFront(t.XM + 1.1, 3.2), Upstage, false);
        var f = Fx(e, "sharpy2");
        Assert.Equal((t.Id, 3), (f.Truss, f.TrussLift));
        Assert.Equal(1.0, f.TrussPos!.Value, 6);  // on the grid
        Assert.Equal("hang", f.Mount);
        Assert.False(f.Waiting);
        e.Drag(FromTheFront(t.XM + 1.1, 1.2), Upstage, false);  // and on down it
        Assert.Equal(1, Fx(e, "sharpy2").TrussLift);
        e.EndDrag();
    }

    [Fact]
    public void WalkingAcrossTheStageAFixtureStaysOffTheWallAndOffItsLedgers()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(8, 5);
        var t = e.Doc.Trusses.Single(x => x.IsScaffold);
        e.Unmount(new HashSet<string> { "sharpy2" });
        var p = Fx(e, "sharpy2").Position(e.Doc.Width);
        Assert.True(e.Pick(Above(p.X, p.Y), Down, false));
        // straight above its front ledgers: it doesn't snap on as onto a truss
        e.Drag(Above(t.XM, t.YM + t.ScaffoldDepth / 2 + 0.2), Down, false);
        Assert.NotEqual(t.Id, Fx(e, "sharpy2").Truss);
        // a slanted ray that goes through the wall far behind the fixture's own height: still in the stage
        var eye = new Vector3((float)t.XM, 12, 6);
        var floor = new Vector3((float)t.XM, -2, (float)p.Z);
        e.Drag(eye, Vector3.Normalize(floor - eye), false);
        Assert.NotEqual(t.Id, Fx(e, "sharpy2").Truss);
        e.EndDrag();
    }

    [Fact]
    public void DroppedOnALedgerAGroupHangsInARowOnIt()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(8, 5);
        var t = e.Doc.Trusses.Single(x => x.IsScaffold);
        e.Unmount(new HashSet<string> { "sharpy2", "sharpy3" });
        Assert.True(e.Drop(RigEditorModel.Payload(["sharpy2", "sharpy3"]), FromTheFront(t.XM, 3), Upstage));
        PlacedFixture a = Fx(e, "sharpy2"), b = Fx(e, "sharpy3");
        Assert.Equal((t.Id, 3, t.Id, 3), (a.Truss, a.TrussLift, b.Truss, b.TrussLift));
        Assert.Equal(a.ZM, b.ZM);
        Assert.True(Math.Abs(a.TrussPos!.Value - b.TrussPos!.Value) >= RigEditorModel.Spacing - 1e-6);
    }

    [Fact]
    public void ARowOnALedgerOnlyMakesRoomForThatLedger()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(8, 5);
        var t = e.Doc.Trusses.Single(x => x.IsScaffold);
        e.Unmount(new HashSet<string> { "sharpy2", "sharpy3" });
        Assert.True(e.Drop(RigEditorModel.Payload(["sharpy2"]), FromTheFront(t.XM, 3), Upstage));
        Assert.True(e.Drop(RigEditorModel.Payload(["sharpy3"]), FromTheFront(t.XM, 4), Upstage));
        Assert.Equal(Fx(e, "sharpy2").TrussPos!.Value, Fx(e, "sharpy3").TrussPos!.Value, 6);  // one above the other
    }

    [Fact]
    public async Task AutoMountSaysWhichLedger()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddScaffold(8, 5);
        var t = e.Doc.Trusses.Single(x => x.IsScaffold);
        e.Unmount(new HashSet<string> { "sharpy2" });
        var host = new FakeHost
        {
            Placements = _ => new()
            {
                ["sharpy2"] = new()
                {
                    ["mount"] = "hang", ["x"] = 0.5, ["y_m"] = -6.5, ["z_m"] = 2.72, ["truss"] = t.Id, ["truss_pos_m"] = 0.0, ["truss_lift"] = 3,
                },
            },
        };
        await e.AutoMount(host);
        Assert.Equal(3, Fx(e, "sharpy2").TrussLift);
    }

    /// The app's own self test on a scaffold (mac/Sources/AmadeusDMX/Rig/Editor/EditorSelfTest.swift).
    [Fact]
    public async Task TheEditorSelfTestsChecksOnAScaffold()
    {
        using var w = new EditorWorkspace();
        var sets = Path.Combine(w.Data, "config", "sets");
        File.WriteAllText(Path.Combine(sets, "wall-test.json"), File.ReadAllText(Path.Combine(sets, "showcase.json")).Replace("\"sharpy2\"", "\"h1\""));
        var e = w.Editor(set: "wall-test");
        e.AddScaffold(16, 7);
        var report = await EditorSelfTest.Run(new FakeHost(), w.Ws, e, "wall-test");
        Assert.Equal(9, report.Count);
        Assert.All(report, line => Assert.StartsWith("PASS", line));
    }

    [Fact]
    public void TheLedWallHangsOnItsFrontAndTheStageStopsAtIt()
    {
        var wall = Truss.Scaffold("w", width: 16, height: 9, xM: 8, yM: -8);
        var s = new Scenery([], new Stage(16, 9, 30) { DeckM = 1.5 }, true, [wall]);
        Assert.Equal(-7.5f, s.Deck!.Value.Y0);
        Assert.Equal(-7.13f, s.Wall!.Value.Center.Y, 4);
        Assert.True(s.DjHead.Y > s.Wall.Value.Center.Y);  // the DJ stands in front of the LED wall
        Assert.All(s.Vertices, v => Assert.True(float.IsFinite(v.Pos.X + v.Pos.Y + v.Pos.Z) && MathF.Abs(v.Normal.Length() - 1) < 1e-3f));
        Assert.Equal(0, s.Vertices.Count % 3);
        // without one it stands where it did
        var free = new Scenery([], new Stage(16, 9, 30) { DeckM = 1.5 }, true);
        Assert.True(free.Wall!.Value.Center.Y < free.Deck!.Value.Y0 + 3);
        // a scaffold that is turned away carries nothing
        var turned = wall with { RotDeg = 90 };
        Assert.NotEqual(-7.13f, new Scenery([], new Stage(16, 9, 30), true, [turned]).Wall!.Value.Center.Y, 2);
    }

    [Fact]
    public void ARaisedStageOnScaffoldIsAPlateOnOpenTube()
    {
        var solid = new Scenery([], new Stage(12) { DeckM = 1.5 }, false);
        var open = new Scenery([], new Stage(12) { DeckM = 1.5, DeckScaffold = true }, false);
        Assert.Equal(solid.Deck, open.Deck);
        // the solid one's front face goes down to the floor across its whole width; the plate's stops 10 cm down
        static bool Face(Scenery s) => s.Vertices.Any(v => v.Normal == new Vector3(0, 1, 0) && v.Pos.Y == 0 && v.Pos.Z == 0 && v.Pos.X == -0.5f);
        Assert.True(Face(solid));
        Assert.Contains(open.Vertices, v => v.Normal == new Vector3(0, 1, 0) && v.Pos.Y == 0 && MathF.Abs(v.Pos.Z - 1.4f) < 1e-4f);
        Assert.True(open.Vertices.Count > solid.Vertices.Count);
        Assert.All(open.Vertices, v => Assert.True(float.IsFinite(v.Pos.X + v.Pos.Y + v.Pos.Z) && MathF.Abs(v.Normal.Length() - 1) < 1e-3f));
        // on the floor there is nothing to stand on: as it was
        Assert.Equal(new Scenery([], new Stage(12), false).Vertices.Count, new Scenery([], new Stage(12) { DeckScaffold = true }, false).Vertices.Count);
    }
}
