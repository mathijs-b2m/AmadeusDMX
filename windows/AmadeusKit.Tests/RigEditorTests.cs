// The rig editor's model (windows/AmadeusDMX/Rig/Editor/RigEditorModel.cs, compiled in here): picking and dragging
// with rays from above, snapping onto trusses and the grid, the truss's sides and a tower's faces, groups in a row,
// drawing trusses and towers, zones, keys, undo/redo, auto-mount and saving through a fake setup API, rereading.
// The last test runs the app's own `-editorSelfTest` against the engine's setup service on a copy of the examples.
using System.Diagnostics;
using System.Numerics;
using Xunit.Abstractions;

namespace AmadeusKit.Tests;

using AmadeusDMX;

/// A data folder with the showcase set and rig from examples/; the fixture library is the checkout's.
public sealed class EditorWorkspace : IDisposable
{
    public static string RepoRoot => Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));

    public string Data { get; } = Directory.CreateTempSubdirectory("amadeus-editor-").FullName;
    public Workspace Ws { get; }

    public EditorWorkspace()
    {
        foreach (var kind in new[] { "sets", "rigs" })
        {
            Directory.CreateDirectory(Path.Combine(Data, "config", kind));
            foreach (var f in Directory.EnumerateFiles(Path.Combine(RepoRoot, "examples", kind)))
                File.Copy(f, Path.Combine(Data, "config", kind, Path.GetFileName(f)));
        }
        Ws = new Workspace(RepoRoot, Data, Workspace.VenvPython(RepoRoot));
    }

    public RigEditorModel Editor(string rig = "showcase", string set = "showcase")
    {
        var e = RigEditorModel.Create(Ws, rig, set) ?? throw new InvalidOperationException("no document");
        e.UndoManager = new UndoManager();
        return e;
    }

    public void Dispose()
    {
        try { Directory.Delete(Data, true); } catch (IOException) { }
    }
}

/// The setup API, faked: answers what the test says, and remembers the calls.
public sealed class FakeHost : IRigEditorHost, IRigEditorAPI
{
    public bool Up = true;
    public int Reloads;
    public readonly List<string> Calls = [];
    public IReadOnlyDictionary<string, JSONValue>? LastLayout;
    public Func<IReadOnlyDictionary<string, JSONValue>, Dictionary<string, Dictionary<string, JSONValue>>> Placements = _ => [];
    public Truss[]? Trusses;

    public Task<bool> EnsureSetupService() => Task.FromResult(Up);
    public IRigEditorAPI Api => this;
    public void ReloadSets() => Reloads++;
    public void Open(string path) => Calls.Add($"open {Path.GetFileName(path)}");

    public Task<(Dictionary<string, Dictionary<string, JSONValue>> Placements, Truss[]? Trusses)> AutomountPlacements(
        IReadOnlyDictionary<string, JSONValue> layout, IReadOnlyList<string>? ids, bool all)
    {
        Calls.Add($"automount {(ids is null ? "-" : string.Join(",", ids))} all={all}");
        LastLayout = layout;
        return Task.FromResult((Placements(layout), Trusses));
    }

    public Task<byte[]> HangSheet(IReadOnlyDictionary<string, JSONValue> layout, string set, string rig) =>
        Task.FromResult("<html></html>"u8.ToArray());
    public Task<HangCheckStep[]> HangCheck(IReadOnlyDictionary<string, JSONValue> layout) => Task.FromResult(Array.Empty<HangCheckStep>());
    public Task<LightTest> TestLight(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout, bool point) =>
        Task.FromResult(new LightTest { On = on, Output = "Art-Net", Universe = 1, Channels = [1, 8] });
    public Task<Dictionary<string, JSONValue>> HangCheckFix(IReadOnlyDictionary<string, JSONValue> layout, string fixture, string fix) =>
        Task.FromResult(new Dictionary<string, JSONValue> { ["pan_invert"] = true });
    public Task<Dictionary<string, Dictionary<string, JSONValue>>> InOrderPlacements(IReadOnlyDictionary<string, JSONValue> layout) =>
        Task.FromResult(new Dictionary<string, Dictionary<string, JSONValue>>());

    public Task SaveRigStructure(IReadOnlyDictionary<string, JSONValue> layout, string rig)
    {
        Calls.Add($"save structure {rig}");
        LastLayout = layout;
        return Task.CompletedTask;
    }

    public Task SaveRig(IReadOnlyDictionary<string, JSONValue> layout, string rigName, string setName)
    {
        Calls.Add($"save {setName} on {rigName}");
        LastLayout = layout;
        return Task.CompletedTask;
    }
}

public class RigEditorTests(ITestOutputHelper output)
{
    static readonly Vector3 Down = new(0, 0, -1);
    static Vector3 Above(double x, double y) => new((float)x, (float)y, 30);
    static PlacedFixture Fx(RigEditorModel e, string id) => e.Doc.Fixtures.First(f => f.Id == id);
    static Truss Tr(RigEditorModel e, string id) => e.Doc.Trusses.First(t => t.Id == id);

    [Fact]
    public void ATrussDraggedSnapsTo25cmAndItsFixturesFollow()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var front = Tr(e, "front") with { };
        Assert.True(e.Pick(Above(front.XM, front.YM), Down, false));
        Assert.Equal(EditorSelection.Truss("front"), e.Selection);
        e.Drag(Above(front.XM + 0.33, front.YM - 0.8), Down, false);
        e.EndDrag();
        Assert.Equal(-2.0, Tr(e, "front").YM, 6);           // -1.2 - 0.8, on the 25 cm grid
        Assert.Equal(6.25, Tr(e, "front").XM, 6);           // 6.33 → 6.25
        Assert.Equal(Tr(e, "front").YM, Fx(e, "sharpy1").YM, 6);
        Assert.True(e.IsDirty);
        // Alt: free
        Assert.True(e.Pick(Above(Tr(e, "front").XM, Tr(e, "front").YM), Down, false));
        e.Drag(Above(Tr(e, "front").XM + 0.13, Tr(e, "front").YM), Down, true);
        e.EndDrag();
        Assert.Equal(6.38, Tr(e, "front").XM, 3);
    }

    [Fact]
    public void AFixtureSlidesAlongItsTrussAndGoesRoundItsSides()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var s1 = Fx(e, "sharpy1").Position(e.Doc.Width);
        var fr = Tr(e, "front") with { };
        Assert.True(e.Pick(Above(s1.X, s1.Y), Down, false));
        Assert.Equal(EditorSelection.Fixture("sharpy1"), e.Selection);  // the fixture wins from its truss
        e.Drag(Above(s1.X + 1.37, s1.Y + 0.1), Down, false);
        Assert.Equal(-3.25, Fx(e, "sharpy1").TrussPos!.Value, 6);
        e.Drag(Above(s1.X + 1.37, fr.YM + 0.5), Down, false);
        Assert.Equal("front", Fx(e, "sharpy1").Side);
        Assert.Equal(90, Fx(e, "sharpy1").MountRoll);
        Assert.Equal(fr.YM + RigEditorModel.SideOut, Fx(e, "sharpy1").YM, 6);
        e.Drag(Above(s1.X + 1.37, fr.YM - 0.5), Down, false);
        Assert.Equal("back", Fx(e, "sharpy1").Side);
        Assert.Equal(270, Fx(e, "sharpy1").MountRoll);
        e.Drag(Above(s1.X + 1.37, fr.YM + 0.05), Down, false);
        Assert.Equal("under", Fx(e, "sharpy1").Side);
        Assert.Null(Fx(e, "sharpy1").MountRoll);
        Assert.Equal(fr.ZM - RigEditorModel.HangDrop, Fx(e, "sharpy1").ZM, 6);
        // far from every truss: onto the floor
        e.Drag(Above(s1.X + 4.5, s1.Y + 4), Down, false);
        Assert.Null(Fx(e, "sharpy1").Truss);
        Assert.Equal("floor", Fx(e, "sharpy1").Mount);
        e.EndDrag();
        // one drag, one undo step
        e.UndoManager!.Undo();
        Assert.Equal("front", Fx(e, "sharpy1").Truss);
        Assert.Equal(-4.5, Fx(e, "sharpy1").TrussPos!.Value, 6);
        Assert.False(e.IsDirty);
        e.UndoManager.Redo();
        Assert.Null(Fx(e, "sharpy1").Truss);
    }

    [Fact]
    public void ArrowsGoRoundTheTrussAndATowersFaces()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.Select(["sharpy1"]);
        e.SetSide("sharpy1", "under");
        Assert.True(e.Key(new EditorKey(EditorKeyCode.Up)));
        Assert.Equal("front", Fx(e, "sharpy1").Side);
        e.Key(new EditorKey(EditorKeyCode.Up));
        Assert.Equal("top", Fx(e, "sharpy1").Side);
        Assert.Equal("stand", Fx(e, "sharpy1").Mount);
        e.Key(new EditorKey(EditorKeyCode.Down));
        e.Key(new EditorKey(EditorKeyCode.Down));
        e.Key(new EditorKey(EditorKeyCode.Down));
        Assert.Equal("back", Fx(e, "sharpy1").Side);
        // a fixture on a tower: its faces, front → right → back → left (the back face it had stays)
        e.Attach("sharpy1", "towerL");
        Assert.Equal("back", Fx(e, "sharpy1").Side);
        Assert.Equal(90, Fx(e, "sharpy1").MountRoll);
        e.Key(new EditorKey(EditorKeyCode.Up));
        Assert.Equal("left", Fx(e, "sharpy1").Side);
        var t = Tr(e, "towerL");
        Assert.Equal(t.XM - RigEditorModel.TowerOut, Fx(e, "sharpy1").Position(e.Doc.Width).X, 6);
        e.Key(new EditorKey(EditorKeyCode.Up));
        Assert.Equal("front", Fx(e, "sharpy1").Side);
        Assert.Equal(t.YM + RigEditorModel.TowerOut, Fx(e, "sharpy1").YM, 6);
        e.SetSide(new HashSet<string> { "sharpy1" }, "top");
        Assert.Equal(t.ZM + t.LengthM / 2 + RigEditorModel.TowerTop, Fx(e, "sharpy1").ZM, 6);
        // not on a truss: the arrows nudge (↑: towards the back)
        e.Attach("sharpy1", null);
        var y = Fx(e, "sharpy1").YM;
        e.Key(new EditorKey(EditorKeyCode.Up, Shift: true));
        Assert.Equal(y - 0.5, Fx(e, "sharpy1").YM, 6);
    }

    [Fact]
    public void AGroupDroppedOnATrussHangsInARow60cmApart()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.Unmount(new HashSet<string> { "sharpy2", "sharpy3" });
        Assert.True(Fx(e, "sharpy2").Waiting);
        Assert.Equal(-0.3, Fx(e, "sharpy2").YM, 6);
        var bt = Tr(e, "back");
        e.DropHover(Above(bt.XM, bt.YM), Down);
        Assert.Equal("back", e.DropTarget);
        Assert.Contains("truss:back", e.StageInput().Selected);
        Assert.True(e.Drop(RigEditorModel.Payload(["sharpy2", "sharpy3"]), Above(bt.XM, bt.YM), Down));
        Assert.Null(e.DropTarget);
        PlacedFixture a = Fx(e, "sharpy2"), b = Fx(e, "sharpy3");
        Assert.Equal("back", a.Truss);
        Assert.Equal("back", b.Truss);
        Assert.False(a.Waiting);
        Assert.Equal(RigEditorModel.Spacing, Math.Abs(a.TrussPos!.Value - b.TrussPos!.Value), 3);
        // clear of the fixtures already there (housings at least 15 cm apart)
        foreach (var other in e.Doc.Fixtures.Where(f => f.Truss == "back" && f.Id is not ("sharpy2" or "sharpy3") && (f.Side ?? "under") == "under"))
            Assert.True(Math.Abs(other.TrussPos!.Value - a.TrussPos.Value) >= 0.3 && Math.Abs(other.TrussPos.Value - b.TrussPos.Value) >= 0.3,
                        $"{other.Id} at {other.TrussPos}");
        Assert.Equal(new HashSet<string> { "sharpy2", "sharpy3" }, e.SelectedFixtures);
        // dropped on the floor: a row there
        Assert.True(e.Drop(RigEditorModel.Payload(["sharpy2", "sharpy3"]), Above(3, 4), Down));
        Assert.Null(Fx(e, "sharpy2").Truss);
        Assert.Equal(RigEditorModel.Spacing, (Fx(e, "sharpy3").X - Fx(e, "sharpy2").X) * e.Doc.Width, 6);
        Assert.False(e.Drop("not ours", Above(3, 4), Down));
    }

    [Fact]
    public void ShiftClickSelectsMoreAndTheGroupComesAlongOntoATruss()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.Unmount(new HashSet<string> { "sharpy2", "sharpy3" });
        Vec3 pa = Fx(e, "sharpy2").Position(e.Doc.Width), pb = Fx(e, "sharpy3").Position(e.Doc.Width);
        e.Pick(Above(pa.X, pa.Y), Down, false);
        e.EndDrag();
        e.Pick(Above(pb.X, pb.Y), Down, true);
        Assert.Equal(new HashSet<string> { "sharpy2", "sharpy3" }, e.SelectedFixtures);
        var ft = Tr(e, "front");
        e.Drag(Above(ft.XM + 2.0, ft.YM), Down, false);
        e.EndDrag();
        Assert.Equal("front", Fx(e, "sharpy2").Truss);
        Assert.Equal("front", Fx(e, "sharpy3").Truss);
        Assert.Equal("Move Fixtures", e.UndoManager!.UndoActionName);
        // Shift-click one again: out of the selection
        var p3 = Fx(e, "sharpy3").Position(e.Doc.Width);
        e.Pick(Above(p3.X, p3.Y), Down, true);
        Assert.Equal(new HashSet<string> { "sharpy2" }, e.SelectedFixtures);
        // Ctrl+A: every fixture
        Assert.True(e.Key(EditorKey.Char("a", control: true)));
        Assert.Equal(e.Doc.Fixtures.Count, e.SelectedFixtures.Count);
        // Backspace unmounts them all; Esc clears
        Assert.True(e.Key(new EditorKey(EditorKeyCode.Backspace)));
        Assert.Equal(e.Doc.Fixtures.Count, e.Doc.WaitingCount);
        Assert.Null(e.Selection);
    }

    [Fact]
    public void DrawTrussStretchAndTowers()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var n = e.Doc.Trusses.Count;
        e.Key(EditorKey.Char("t"));
        Assert.Equal(EditorTool.Truss, e.Tool);
        Assert.Contains("Alt: free", e.Message);
        e.Pick(Above(1.1, -6.1), Down, false);
        e.Drag(Above(4.1, -6.7), Down, false);   // 3.06 m at -11°: ½ m and 15° steps
        e.EndDrag();
        var drawn = e.Doc.Trusses[^1];
        Assert.Equal(n + 1, e.Doc.Trusses.Count);
        Assert.Equal(3.0, drawn.LengthM, 6);
        Assert.Equal(-15, drawn.RotDeg, 6);
        Assert.Equal(e.BuildHeight, drawn.ZM, 6);
        Assert.Equal("Draw Truss", e.UndoManager!.UndoActionName);
        // a click without a drag draws nothing
        e.Pick(Above(1.1, -8.1), Down, false);
        e.EndDrag();
        Assert.Equal(n + 1, e.Doc.Trusses.Count);
        // Esc: back to selecting
        e.Key(new EditorKey(EditorKeyCode.Escape));
        Assert.Equal(EditorTool.Select, e.Tool);
        // stretch it by an end handle: the other end stays put
        e.Selection = EditorSelection.Truss(drawn.Id);
        var (a, b) = (drawn.Point(-drawn.LengthM / 2), drawn.Point(drawn.LengthM / 2));
        Assert.True(e.Pick(new Vector3((float)b.X, (float)b.Y, 30), Down, false));
        e.Drag(Above(a.X + 4.0, a.Y), Down, false);
        e.EndDrag();
        var t = Tr(e, drawn.Id);
        Assert.Equal(4.0, t.LengthM, 6);
        Assert.Equal(0, t.RotDeg, 6);
        Assert.Equal(a.X, t.Point(-t.LengthM / 2).X, 6);
        Assert.Equal("Stretch Truss", e.UndoManager.UndoActionName);
        // a tower, raised by its top
        e.Tool = EditorTool.Tower;
        e.Pick(Above(7.2, -2.9), Down, false);
        e.EndDrag();
        var tower = e.Doc.Trusses[^1];
        Assert.True(tower.Vertical);
        Assert.Equal((7.0, -3.0, e.TowerHeight), (tower.XM, tower.YM, tower.LengthM));
        e.Tool = EditorTool.Select;
        e.Selection = EditorSelection.Truss(tower.Id);
        var eye = new Vector3(7, 10, 6);
        Assert.True(e.Pick(eye, Vector3.Normalize(new Vector3(7, -3, (float)tower.LengthM + 0.2f) - eye), false));
        e.Drag(eye, Vector3.Normalize(new Vector3(7, -3, 5.6f) - eye), false);
        e.EndDrag();
        Assert.Equal(5.5, Tr(e, tower.Id).LengthM, 6);
        Assert.Equal(2.75, Tr(e, tower.Id).ZM, 6);
        // Alt+↑ raises it by 25 cm; Alt+↓ lowers a truss
        e.Key(new EditorKey(EditorKeyCode.Up, Alt: true));
        Assert.Equal(5.75, Tr(e, tower.Id).LengthM, 6);
        e.Selection = EditorSelection.Truss("front");
        var z = Tr(e, "front").ZM;
        e.Key(new EditorKey(EditorKeyCode.Down, Alt: true));
        Assert.Equal(z - 0.25, Tr(e, "front").ZM, 6);
        Assert.Equal(z - 0.25 - RigEditorModel.HangDrop, Fx(e, "sharpy1").ZM, 6);
    }

    [Fact]
    public void RotatingATrussTurnsItsFixturesWithIt()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        e.AddTruss(3);
        var id = e.Selection!.Value.TrussId!;
        e.AddFixtures("dts/katana", "Extended", 2);
        var ks = e.Doc.Fixtures.Where(f => f.Truss == id).ToList();
        Assert.Equal(2, ks.Count);
        Assert.Equal(["katana3", "katana4"], ks.Select(k => k.Id).ToArray());  // the set has katana1 and 2
        var used = e.Doc.Fixtures.Select(f => (f.Universe, f.Address)).ToList();
        Assert.Equal(used.Count, used.Distinct().Count());
        e.Key(EditorKey.Char("r", shift: true));  // Shift+R: 90°
        Assert.All(e.Doc.Fixtures.Where(f => f.Truss == id), f => Assert.Equal(90, f.RotDeg, 6));
        var after = e.Doc.Fixtures.Where(f => f.Truss == id).Select(f => f.Position(e.Doc.Width)).ToList();
        Assert.Equal(after[0].X, after[1].X, 6);
        e.Key(EditorKey.Char("r"));
        Assert.Equal(105, Tr(e, id).RotDeg, 6);
        // duplicate and delete: the copy is selected; deleting a truss puts its fixtures on the floor
        e.DuplicateSelection();
        Assert.NotEqual(id, e.Selection!.Value.TrussId);
        e.Selection = EditorSelection.Truss(id);
        e.DeleteSelection();
        Assert.DoesNotContain(e.Doc.Trusses, t => t.Id == id);
        Assert.All(e.Doc.Fixtures.Where(f => f.Key == "dts/katana" && f.Id is "katana3" or "katana4"), f => Assert.Equal("floor", f.Mount));
    }

    [Fact]
    public void ZonesArePickedSmallestFirstAndDraggedOnTheGrid()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        foreach (var p in RigEditorModel.ZonePresets) e.AddZone(p);
        Assert.Equal(RigEditorModel.ZonePresets.Length, e.Doc.Zones.Count);
        Assert.Equal(["zone1", "zone2", "zone3", "zone4", "zone5"], e.Doc.Zones.Select(z => z.Id).ToArray());
        var vip = e.Doc.Zones.First(z => z.Name == "VIP corner");
        e.Selection = null;
        var c = vip.CenterV;
        Assert.True(e.Pick(Above(c.X, c.Y), Down, false));
        Assert.Equal(EditorSelection.Zone(vip.Id), e.Selection);   // inside the keep-in box too: the smaller wins
        e.Drag(Above(c.X - 1.3, c.Y + 0.6), Down, false);
        e.EndDrag();
        var moved = e.Doc.Zones.First(z => z.Id == vip.Id).CenterV;
        Assert.Equal(Math.Round((c.X - 1.3) / 0.25, MidpointRounding.AwayFromZero) * 0.25, moved.X, 6);
        Assert.Equal(c.Z, moved.Z, 9);
        Assert.Equal("Move Zone", e.UndoManager!.UndoActionName);
        // hidden zones aren't drawn, except the selected one
        e.ShowZones = false;
        Assert.Equal([vip.Id], e.StageInput().Zones.Select(z => z.Id).ToArray());
        e.DuplicateSelection();
        Assert.Equal("VIP corner copy", e.Doc.Zones[^1].Name);
        e.Key(new EditorKey(EditorKeyCode.Delete));
        Assert.Equal(RigEditorModel.ZonePresets.Length, e.Doc.Zones.Count);
    }

    [Fact]
    public void HoverLightsWhatAClickWouldPick()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var p = Fx(e, "sharpy1").Position(e.Doc.Width);
        var v = e.Version;
        e.Hover(Above(p.X, p.Y), Down);
        Assert.Contains("hover:fixture:sharpy1", e.StageInput().Selected);
        Assert.True(e.Version > v);
        e.Hover(Above(-20, 40), Down);
        Assert.DoesNotContain(e.StageInput().Selected, s => s.StartsWith("hover:", StringComparison.Ordinal));
        Assert.False(e.IsDirty);  // hovering changes nothing
        Assert.StartsWith("edit:showcase on showcase:", e.StageInput().Key);
    }

    [Fact]
    public void UndoRedoAndRevert()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var u = e.UndoManager!;
        e.UpdateStage(s => s.WidthM = 14);
        Assert.Equal(14, e.Doc.Width);
        Assert.Equal(14, e.Doc.Raw["stage"]["width_m"]?.Number);
        Assert.Equal(JSONValue.False, e.Doc.Raw["stage"]["eye_safety"]);  // kept: the editor doesn't show it
        e.SetScreen(false);
        Assert.False(e.Doc.HasScreen);
        Assert.Equal("Remove LED Wall", u.UndoActionName);
        u.Undo();
        Assert.True(e.Doc.HasScreen);
        Assert.Equal("Remove LED Wall", u.RedoActionName);
        u.Undo();
        Assert.Equal(12, e.Doc.Width);
        Assert.False(e.IsDirty);
        u.Redo();
        Assert.Equal(14, e.Doc.Width);
        // a change that changes nothing isn't a step
        e.UpdateStage(s => s.WidthM = 14);
        Assert.Equal("Change Stage", u.UndoActionName);
        Assert.True(u.CanRedo);
        e.Revert();
        Assert.False(e.IsDirty);
        Assert.False(u.CanRedo);  // a new step forgets the redo
        u.Undo();
        Assert.Equal(14, e.Doc.Width);
    }

    [Fact]
    public async Task AutoMountAppliesTheEnginesPlacementsAsOneStep()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var host = new FakeHost
        {
            Placements = layout =>
            {
                var waiting = (layout["fixtures"].Array ?? []).Select(v => v.Object!).Where(o => o.ContainsKey("_unplaced"))
                    .Select(o => o["id"].String!).ToList();
                return waiting.Select((id, k) => (id, k)).ToDictionary(p => p.id, p => new Dictionary<string, JSONValue>
                {
                    ["mount"] = "hang", ["x"] = 0.4 + p.k * 0.1, ["y_m"] = -5.0, ["z_m"] = 5.38, ["truss"] = "back",
                    ["truss_pos_m"] = -1.2 + p.k * 1.2, ["truss_side"] = "under",
                });
            },
        };
        e.Unmount(new HashSet<string> { "sharpy2", "sharpy3" });
        Assert.Equal(2, e.Doc.WaitingCount);
        await e.AutoMount(host);
        Assert.Equal(["automount - all=False"], host.Calls);
        Assert.Equal(0, e.Doc.WaitingCount);
        Assert.Equal("back", Fx(e, "sharpy2").Truss);
        Assert.Equal("Mounted 2 fixtures", e.Message);
        Assert.Equal("Auto-Mount 2 Fixtures", e.UndoManager!.UndoActionName);
        Assert.False(e.Busy);
        e.UndoManager.Undo();
        Assert.Equal(2, e.Doc.WaitingCount);
        // the engine down: said, nothing changed
        host.Up = false;
        await e.AutoMount(host, all: true);
        Assert.Equal("The engine's setup service is not running.", e.Message);
        Assert.Equal(2, e.Doc.WaitingCount);
    }

    [Fact]
    public async Task ARigWithoutTrussesGetsTheEnginesStructure()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        foreach (var t in e.Doc.Trusses.ToList()) { e.Selection = EditorSelection.Truss(t.Id); e.DeleteSelection(); }
        Assert.Empty(e.Doc.Trusses);
        var host = new FakeHost
        {
            Trusses = [new Truss("front", 5, 3, -1, 5.5), new Truss("back", 5, 3, -3, 5.8)],
            Placements = _ => new() { ["sharpy1"] = new() { ["truss"] = "front", ["truss_pos_m"] = 0, ["mount"] = "hang" } },
        };
        await e.AutoMount(host, all: true);
        Assert.Equal(2, e.Doc.Trusses.Count);
        Assert.Equal("The rig had no trusses: it has 2 now (where its fixtures hung, or a standard set-up)", e.Message);
        Assert.Equal("Auto-Mount Fixture", e.UndoManager!.UndoActionName);
    }

    [Fact]
    public async Task SavingGoesThroughTheSetupAPIAndRereadsWhenClean()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var host = new FakeHost();
        e.Nudge(0, 0);  // nothing selected: nothing
        Assert.False(e.IsDirty);
        e.Selection = EditorSelection.Truss("front");
        e.Nudge(0.5, 0);
        Assert.True(e.IsDirty);
        await e.Save(host);
        Assert.Equal(["save showcase on showcase"], host.Calls);
        Assert.Equal(6.5, host.LastLayout!["trusses"].Array!.First(t => t["id"]?.String == "front")["x_m"]?.Number);
        Assert.False(e.IsDirty);
        Assert.Equal("Saved showcase", e.Message);
        Assert.Equal(1, host.Reloads);

        // the files changed elsewhere: reread (the fake didn't write them: the editor goes back to the file)
        e.ReloadIfClean();
        Assert.Equal(6.0, Tr(e, "front").XM, 6);
        // not while there are unsaved changes
        e.Selection = EditorSelection.Truss("front");
        e.Nudge(1, 0);
        e.ReloadIfClean();
        Assert.Equal(7.0, Tr(e, "front").XM, 6);

        // the rig alone: its structure
        var rig = w.Editor(set: "");
        Assert.Empty(rig.Doc.Fixtures);
        rig.Selection = EditorSelection.Truss("back");
        rig.Nudge(0, -0.5);
        await rig.Save(host);
        Assert.Equal("save structure showcase", host.Calls[^1]);
    }

    [Fact]
    public async Task TheHangCheckFixAndSwapAreEditorChanges()
    {
        using var w = new EditorWorkspace();
        var e = w.Editor();
        var host = new FakeHost();
        var s1 = Fx(e, "sharpy1").Clone();
        var s2 = Fx(e, "sharpy2").Clone();
        e.Check = new RigEditorModel.HangCheck([
            new HangCheckStep { Id = "sharpy1", Label = "A1", Moving = true },
            new HangCheckStep { Id = "sharpy2", Label = "A2", Moving = true },
        ]);
        await e.SwapCheck(host, e.Check.Steps[1]);
        Assert.Equal(s2.TrussPos, Fx(e, "sharpy1").TrussPos);
        Assert.Equal(s1.TrussPos, Fx(e, "sharpy2").TrussPos);
        Assert.Equal("swapped with sharpy2", e.Check!.Fixed["sharpy1"]);
        Assert.Equal("Swap A1 and A2", e.UndoManager!.UndoActionName);
        Assert.Equal(EditorSelection.Fixture("sharpy1"), e.Selection);
        Assert.Equal("universe 1, channels 1–8 · Art-Net", e.Check.Output);
        await e.FixCheck(host, new HangCheckStep.Fault("mirrored", "left"));
        Assert.Equal(JSONValue.True, e.Doc.RawFixture("sharpy1")["pan_invert"]);
        Assert.Equal("pans the other way now", e.Check!.Fixed["sharpy1"]);
        await e.StopCheck(host);
        Assert.Null(e.Check);
    }

    [Fact]
    public void TheUndoManagerGroupsAndForgetsTheRedo()
    {
        var u = new UndoManager();
        var log = new List<string>();
        void Do(string what)
        {
            log.Add(what);
            u.RegisterUndo(() => { log.Add("undo " + what); u.RegisterUndo(() => Do(what)); });
            u.SetActionName(what);
        }
        Do("a");
        u.BeginUndoGrouping();
        Do("b");
        Do("c");
        u.EndUndoGrouping();
        Assert.Equal("c", u.UndoActionName);
        u.Undo();
        Assert.Equal(["a", "b", "c", "undo c", "undo b"], log);
        Assert.True(u.CanRedo);
        u.Redo();
        Assert.Equal(["b", "c"], log[^2..]);
        u.Undo();
        Do("d");
        Assert.False(u.CanRedo);
        u.Undo();
        u.Undo();
        Assert.False(u.CanUndo);
        Assert.Equal("undo a", log[^1]);
    }

    static int FreePort()
    {
        var l = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        l.Start();
        var port = ((System.Net.IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return port;
    }

    /// The app's `-editorSelfTest showcase`, step for step, against the engine's setup service (on a free port) on a
    /// copy of the examples: picking, dragging, groups, auto-mount and save through the real API.
    [Fact]
    public async Task TheEditorSelfTestPassesAgainstTheEngine()
    {
        if (LinkTests.EnginePython() is not { } python) { output.WriteLine("no engine Python: skipped"); return; }
        using var w = new EditorWorkspace();
        var port = FreePort();
        var psi = new ProcessStartInfo(python)
        {
            WorkingDirectory = EditorWorkspace.RepoRoot, RedirectStandardOutput = true, RedirectStandardError = true,
            ArgumentList = { "-m", "amadeus", "setup", "--port", port.ToString(System.Globalization.CultureInfo.InvariantCulture) },
        };
        psi.Environment["AMADEUS_ROOT"] = EditorWorkspace.RepoRoot;
        psi.Environment["AMADEUS_DATA"] = w.Data;
        using var p = Process.Start(psi)!;
        p.OutputDataReceived += (_, _) => { };
        p.ErrorDataReceived += (_, _) => { };
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        try
        {
            var api = new SetupAPI(port);
            var up = false;
            for (var i = 0; i < 120 && !up && !p.HasExited; i++)
            {
                up = await api.IsUp();
                if (!up) await Task.Delay(250);
            }
            if (!up) { output.WriteLine("the setup service didn't start: skipped"); return; }
            var host = new EngineHost(api);
            var e = RigEditorModel.Create(w.Ws, "showcase", "showcase")!;
            var report = await EditorSelfTest.Run(host, w.Ws, e, "showcase");
            foreach (var line in report) output.WriteLine(line);
            Assert.True(report.Count >= 30, $"{report.Count} checks");
            Assert.DoesNotContain(report, l => l.StartsWith("FAIL", StringComparison.Ordinal));
        }
        finally
        {
            try { p.Kill(true); } catch (InvalidOperationException) { }
        }
    }

    sealed class EngineHost(SetupAPI api) : IRigEditorHost
    {
        public Task<bool> EnsureSetupService() => api.IsUp();
        public IRigEditorAPI Api { get; } = new SetupEditorAPI(api);
        public void ReloadSets() { }
        public void Open(string path) { }
    }
}
