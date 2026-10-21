// `-editorSelfTest NAME`: runs the rig editor's picking, dragging, snapping, grouping, dropping, auto-mount, undo
// and save on the set NAME placed on the rig NAME (use copies: it saves!) and writes a report to
// %TEMP%\editor-selftest.txt, then quits. For development.
//
// The checks are the Mac's (mac/Sources/AmadeusDMX/Rig/Editor/EditorSelfTest.swift), step for step. This part has
// no WinUI: the kit's tests run it too, against the engine's setup service on a copy of the examples.
// EditorSelfTest.App.cs starts it from the command line in the app.
using System.Globalization;
using System.Numerics;
using AmadeusKit;

namespace AmadeusDMX;

public static partial class EditorSelfTest
{
    public static string ReportPath => Path.Combine(Path.GetTempPath(), "editor-selftest.txt");

    static string F(double v, string format = "0.##") => v.ToString(format, CultureInfo.InvariantCulture);

    /// Every check, as "PASS  name" / "FAIL  name  (detail)" lines.
    public static async Task<List<string>> Run(IRigEditorHost host, Workspace ws, RigEditorModel e, string name)
    {
        var out_ = new List<string>();
        var undo = new UndoManager { GroupsByEvent = false };
        undo.BeginUndoGrouping();          // one open group for everything after the undo test
        e.UndoManager = undo;
        void Log(string s) => out_.Add(s);
        void Check(string what, bool ok, string detail = "") => Log($"{(ok ? "PASS" : "FAIL")}  {what}{(detail.Length == 0 ? "" : $"  ({detail})")}");
        var down = new Vector3(0, 0, -1);
        static Vector3 Above(double x, double y) => new((float)x, (float)y, 30);
        PlacedFixture Fx(string id) => e.Doc.Fixtures.First(f => f.Id == id);
        Truss Tr(string id) => e.Doc.Trusses.First(t => t.Id == id);
        var W = e.Doc.Width;
        static double Rounded(double v) => Math.Round(v, MidpointRounding.AwayFromZero);

        // 1. pick a truss between its fixtures
        var front = Tr("front") with { };
        undo.EndUndoGrouping();
        undo.BeginUndoGrouping();
        Check("pick truss", e.Pick(Above(front.XM, front.YM), down, false) && e.Selection == EditorSelection.Truss("front"));
        // 2. drag it 0.8 m back: its fixtures follow
        e.Drag(Above(front.XM, front.YM - 0.8), down, false);
        e.EndDrag();
        undo.EndUndoGrouping();
        Check("truss moved (snapped to 25 cm)", Math.Abs(Tr("front").YM - Rounded((front.YM - 0.8) / 0.25) * 0.25) < 0.01, $"y {F(Tr("front").YM)}");
        Check("fixtures follow", Math.Abs(Fx("sharpy1").YM - Tr("front").YM) < 0.01, $"sharpy1 y {F(Fx("sharpy1").YM)}");
        // 3. undo
        undo.Undo();
        undo.BeginUndoGrouping();
        Check("undo", Math.Abs(Tr("front").YM - front.YM) < 0.01 && Math.Abs(Fx("sharpy1").YM - front.YM) < 0.01);
        // 4. pick a fixture under the truss (fixtures win)
        var s1 = Fx("sharpy1").Position(W);
        Check("pick fixture under truss", e.Pick(Above(s1.X, s1.Y), down, false) && e.Selection == EditorSelection.Fixture("sharpy1"));
        // 5. slide along the truss, snapping to 25 cm
        e.Drag(Above(s1.X + 1.37, s1.Y + 0.1), down, false);
        Check("slide along truss", Fx("sharpy1").Truss == "front" && Math.Abs((Fx("sharpy1").TrussPos ?? 0) - (-4.5 + 1.25)) < 0.01,
              $"pos {F(Fx("sharpy1").TrussPos ?? double.NaN)}");
        // 5b. drag across the truss: onto its front face, then its back face, then back under it
        var fr = Tr("front") with { };
        e.Drag(Above(s1.X + 1.37, fr.YM + 0.5), down, false);
        Check("front face (90°)", Fx("sharpy1").Side == "front" && Fx("sharpy1").MountRoll == 90 && Math.Abs(Fx("sharpy1").YM - (fr.YM + 0.4)) < 0.01
              && Math.Abs(Fx("sharpy1").ZM - fr.ZM) < 0.01 && (Fx("sharpy1").Up - new Vec3(0, 1, 0)).Length < 0.01,
              $"side {Fx("sharpy1").Side ?? "-"} y {F(Fx("sharpy1").YM)}");
        e.Drag(Above(s1.X + 1.37, fr.YM - 0.5), down, false);
        Check("back face (270°)", Fx("sharpy1").Side == "back" && Fx("sharpy1").MountRoll == 270 && Math.Abs(Fx("sharpy1").YM - (fr.YM - 0.4)) < 0.01
              && (Fx("sharpy1").Up - new Vec3(0, -1, 0)).Length < 0.01);
        e.Drag(Above(s1.X + 1.37, fr.YM + 0.05), down, false);
        Check("centre: under again (0°)", Fx("sharpy1").Side == "under" && Fx("sharpy1").MountRoll is null
              && Math.Abs(Fx("sharpy1").ZM - (fr.ZM - 0.42)) < 0.01);
        // 6. drag far from any truss: drops to the floor
        e.Drag(Above(s1.X + 4.5, s1.Y + 4), down, false);
        Check("detach to floor", Fx("sharpy1").Truss is null && Fx("sharpy1").Mount == "floor" && Fx("sharpy1").ZM < 0.5);
        e.EndDrag();
        // 7. drag onto the back truss: hangs there
        var back = Tr("back") with { };
        var p = Fx("sharpy1").Position(W);
        e.Pick(Above(p.X, p.Y), down, false);
        e.Drag(Above(back.XM + 0.6, back.YM + 0.2), down, false);
        e.EndDrag();
        var f = Fx("sharpy1");
        Check("attach to back truss", f.Truss == "back" && f.Mount == "hang" && Math.Abs(f.ZM - (back.ZM - 0.42)) < 0.01,
              $"truss {f.Truss ?? "-"} z {F(f.ZM)}");
        // 8. a new truss with two Katanas on it
        e.AddTruss(3);
        if (e.Selection?.TrussId is not { } newID) { Check("add truss", false); return out_; }
        Check("add truss", e.Doc.Trusses.Any(t => t.Id == newID));
        e.AddFixtures("dts/katana", "Extended", 2);
        var ks = e.Doc.Fixtures.Where(x => x.Truss == newID).ToList();
        Check("add fixtures on truss", ks.Count == 2 && ks.All(x => x.Mount == "hang"),
              string.Join(" ", ks.Select(x => $"{x.Id}@{x.PatchText}")));
        Check("added without addresses (given on the Sets page)", ks.All(x => x.Address is null));
        // 9. rotate the new truss 90°: the Katanas turn with it (they now run front to back)
        var before = ks.Select(x => x.Position(W)).ToList();
        e.Selection = EditorSelection.Truss(newID);
        e.RotateSelection(90);
        var after = e.Doc.Fixtures.Where(x => x.Truss == newID).Select(x => x.Position(W)).ToList();
        Check("bars turn with the truss", e.Doc.Fixtures.Where(x => x.Truss == newID).All(x => Math.Abs(x.RotDeg - 90) < 0.01));
        Check("fixtures follow rotation", after.Count == 2 && Math.Abs(after[0].X - after[1].X) < 0.01 && Math.Abs(after[0].Y - after[1].Y) > 0.5,
              before.Count == 2 && after.Count == 2 ? $"before dx {F(before[1].X - before[0].X, "0.00")} after dy {F(after[1].Y - after[0].Y, "0.00")}" : "");
        // 9b. zones: one of each preset; pick one where nothing else is; drag it; trusses still win
        var zonesBefore = e.Doc.Zones.Count;
        foreach (var preset in RigEditorModel.ZonePresets) e.AddZone(preset);
        Check("add zones", e.Doc.Zones.Count == zonesBefore + RigEditorModel.ZonePresets.Length,
              string.Join(" ", e.Doc.Zones.Select(z => $"{z.Kind}/{z.Shape}")));
        var floorZone = e.Doc.Zones.First(z => z.Name == "VIP corner");
        e.Selection = null;
        var zc = floorZone.CenterV;
        Check("pick zone", e.Pick(Above(zc.X, zc.Y), down, false) && e.Selection == EditorSelection.Zone(floorZone.Id));
        e.Drag(Above(zc.X - 1.3, zc.Y + 0.6), down, false);
        e.EndDrag();
        var moved = e.Doc.Zones.First(z => z.Id == floorZone.Id).CenterV;
        Check("drag zone (snapped)", Math.Abs(moved.X - Rounded((zc.X - 1.3) / 0.25) * 0.25) < 0.01 && Math.Abs(moved.Z - zc.Z) < 1e-6,
              $"x {F(moved.X, "0.00")} y {F(moved.Y, "0.00")}");
        var fb = Tr("back");
        // a spot on the back truss with no fixture within reach
        double free = 0;
        for (var i = 0; ; i++)
        {
            var u = -fb.LengthM / 2 + 0.3 + i * 0.1;
            if (u >= fb.LengthM / 2 - 0.3) break;
            var q = fb.Point(u);
            if (e.Doc.Fixtures.All(x => (x.Position(W).XY - q.XY).Length > 1.0)) { free = u; break; }
        }
        Check("trusses win over zones", e.Pick(Above(fb.Point(free).X, fb.YM), down, false) && e.Selection == EditorSelection.Truss("back"),
              $"at u {F(free, "0.0")}");
        e.Selection = EditorSelection.Zone(floorZone.Id);
        e.RotateSelection(15);
        e.Nudge(0.1, 0);
        var z2 = e.Doc.Zones.First(z => z.Id == floorZone.Id);
        Check("rotate + nudge zone", Math.Abs(z2.RotDeg - 15) < 1e-6 && Math.Abs(z2.CenterV.X - moved.X - 0.1) < 1e-6);
        var plane = e.Doc.Zones.First(z => z.Name == "No lasers below");
        var pc = plane.CenterV;
        Check("plane hit maths", plane.Hit(new Vec3(pc.X, pc.Y, 6), new Vec3(0, 0, -1)) is { } th && Math.Abs(th - (6 - pc.Z)) < 1e-6
              && plane.Hit(new Vec3(pc.X, pc.Y, 6), new Vec3(0, 0, 1)) is null);
        // 10. unmount: back to waiting in front of the stage
        e.Selection = EditorSelection.Fixture("sharpy2");
        e.DeleteSelection();
        Check("unmount", Fx("sharpy2").Waiting && Fx("sharpy2").Truss is null && Math.Abs(Fx("sharpy2").YM + 0.3) < 0.01,
              $"y {F(Fx("sharpy2").YM)}");
        // 11. drop two fixtures from the inspector onto the back truss: a row, 60 cm apart
        var bt = Tr("back");
        string[] two = ["sharpy2", "sharpy3"];
        Check("drop a group on a truss", e.Drop(RigEditorModel.Payload(two), Above(bt.XM, bt.YM), down));
        PlacedFixture a = Fx("sharpy2"), b = Fx("sharpy3");
        Check("a row on that truss", a.Truss == "back" && b.Truss == "back" && !a.Waiting
              && Math.Abs(Math.Abs((a.TrussPos ?? 0) - (b.TrussPos ?? 0)) - RigEditorModel.Spacing) < 0.01,
              $"{F(a.TrussPos ?? double.NaN, "0.00")} / {F(b.TrussPos ?? double.NaN, "0.00")}");
        // 12. Shift-click two fixtures, drag one onto the front truss: the other comes along
        e.Selection = null;
        Vec3 pa = Fx("sharpy2").Position(W), pb = Fx("sharpy3").Position(W);
        e.Pick(Above(pa.X, pa.Y), down, false);
        e.EndDrag();
        e.Pick(Above(pb.X, pb.Y), down, true);
        Check("⇧-click selects more", e.SelectedFixtures.SetEquals(two), string.Join(",", e.SelectedFixtures.Order(StringComparer.Ordinal)));
        var ft = Tr("front");
        e.Drag(Above(ft.XM + 2.0, ft.YM), down, false);
        e.EndDrag();
        Check("group drag onto a truss", Fx("sharpy2").Truss == "front" && Fx("sharpy3").Truss == "front",
              $"{Fx("sharpy2").Truss ?? "-"} {Fx("sharpy3").Truss ?? "-"}");
        // 13. auto-mount what waits (through the engine)
        e.Unmount(new HashSet<string> { "sharpy2", "sharpy3", "sharpy4" });
        await e.AutoMount(host);
        Check("auto-mount", e.Doc.WaitingCount == 0 && Fx("sharpy4").Truss is not null,
              $"waiting {e.Doc.WaitingCount}, sharpy4 on {Fx("sharpy4").Truss ?? "-"}{(e.Message is { } m ? $", {m}" : "")}");
        // 13a. ↑ / ↓ round a fixture about its truss: under → front → top → back
        e.Select(["sharpy1"]);
        e.SetSide("sharpy1", "under");
        e.RollAround(1);
        var side1 = Fx("sharpy1").Side;
        e.RollAround(1);
        var side2 = Fx("sharpy1").Side;
        e.RollAround(-1); e.RollAround(-1); e.RollAround(-1);
        Check("↑/↓ round the truss", side1 == "front" && side2 == "top" && Fx("sharpy1").Side == "back" && Fx("sharpy1").MountRoll == 270,
              $"{side1 ?? "-"} {side2 ?? "-"} {Fx("sharpy1").Side ?? "-"}");
        // 13b. building: draw a truss on the floor, stretch it by an end handle, set a tower and raise it by its top
        var trussesBefore = e.Doc.Trusses.Count;
        e.Tool = EditorTool.Truss;
        e.Pick(Above(1.1, -6.1), down, false);
        e.Drag(Above(4.1, -6.1), down, false);
        e.EndDrag();
        var drawn = e.Doc.Trusses[^1] with { };
        Check("draw a truss (½ m grid, 15° steps)", e.Doc.Trusses.Count == trussesBefore + 1 && Math.Abs(drawn.LengthM - 3) < 0.01
              && Math.Abs(drawn.RotDeg) < 0.01 && Math.Abs(drawn.XM - 2.5) < 0.01 && Math.Abs(drawn.YM + 6) < 0.01 && Math.Abs(drawn.ZM - e.BuildHeight) < 0.01,
              $"{F(drawn.LengthM)} m at {F(drawn.RotDeg)}° ({F(drawn.XM)}, {F(drawn.YM)}, {F(drawn.ZM)})");
        e.Tool = EditorTool.Select;
        e.Selection = EditorSelection.Truss(drawn.Id);
        var grabbed = e.Pick(new Vector3(4.0f, -6.0f, 30), down, false);
        e.Drag(Above(5.1, -6.0), down, false);
        e.EndDrag();
        var stretched = Tr(drawn.Id);
        Check("stretch it by an end", grabbed && Math.Abs(stretched.LengthM - 4) < 0.01 && Math.Abs(stretched.XM - 3) < 0.01,
              $"{F(stretched.LengthM)} m, x {F(stretched.XM)}");
        e.Tool = EditorTool.Tower;
        e.Pick(Above(7.2, -2.9), down, false);
        e.EndDrag();
        var tower = e.Doc.Trusses[^1] with { };
        Check("place a tower", tower.Vertical && Math.Abs(tower.XM - 7) < 0.01 && Math.Abs(tower.YM + 3) < 0.01 && Math.Abs(tower.LengthM - e.TowerHeight) < 0.01,
              $"({F(tower.XM)}, {F(tower.YM)}) {F(tower.LengthM)} m");
        e.Tool = EditorTool.Select;
        e.Selection = EditorSelection.Truss(tower.Id);
        var eye = new Vector3(7, 10, 6);
        var toTop = Vector3.Normalize(new Vector3(7, -3, (float)tower.LengthM + 0.2f) - eye);
        var raised = e.Pick(eye, toTop, false);
        e.Drag(eye, Vector3.Normalize(new Vector3(7, -3, 5.5f) - eye), false);
        e.EndDrag();
        Check("raise the tower by its top", raised && Math.Abs(Tr(tower.Id).LengthM - 5.5) < 0.01 && Math.Abs(Tr(tower.Id).ZM - 2.75) < 0.01,
              $"{F(Tr(tower.Id).LengthM)} m");
        // 14. save (through the engine: the rig and the set files) and read back; a waiting fixture stays unmounted
        e.Unmount(new HashSet<string> { "sharpy4" });
        try
        {
            await e.Save(host);
            var reread = ws.Document(name, name)!;
            Check("save + reload", reread.Trusses.Count == e.Doc.Trusses.Count && reread.Fixtures.Count == e.Doc.Fixtures.Count
                  && reread.Zones.SequenceEqual(e.Doc.Zones) && reread.Fixtures.FirstOrDefault(x => x.Id == "sharpy1")?.Truss == "back");
            Check("waiting stays unmounted", reread.Fixtures.FirstOrDefault(x => x.Id == "sharpy4")?.Waiting == true
                  && ws.Mounted(name, name).Placed == reread.Fixtures.Count - 1);
        }
        catch (Exception ex) when (ex is not OutOfMemoryException)
        {
            Check("save", false, ex.Message);
        }
        return out_;
    }
}
