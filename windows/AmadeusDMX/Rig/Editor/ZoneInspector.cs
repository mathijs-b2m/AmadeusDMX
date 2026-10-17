// The selected zone: kind, shape, size, angles and margin.
namespace AmadeusDMX;

public sealed class ZoneInspector(RigEditorModel editor, string id)
{
    public static string KindName(string k) => k switch
    {
        "keep_in" => "Keep beams in",
        "laser_out" => "Laser safety",
        _ => "Keep beams out",
    };

    public static Windows.UI.Color ColorOf(Zone z) => z.Kind == "laser_out" ? Tint.Red : z.Kind == "keep_in" ? Tint.Green : Tint.Blue;

    public static string SymbolOf(Zone z) =>
        z.Kind == "laser_out" ? "exclamationmark.triangle.fill" : z.Shape == "box" ? "cube.transparent" : "rectangle.dashed";

    Zone Z => editor.Doc.Zones.FirstOrDefault(z => z.Id == id) ?? new Zone(id, id, "avoid", "rect", new Vec3(0, 0, 2), [2, 2]);

    static string Explanation(string kind) => kind switch
    {
        "keep_in" => "Moving-head beams land only inside this area; outside it they slide back to its edge.",
        "laser_out" => "No laser beam may come into this zone (with the margin). The show lifts or shrinks the "
                       + "pattern; if that isn’t enough, the laser goes dark.",
        _ => "Moving-head beams stay off this surface: they slide to its edge, and go dark while crossing it.",
    };

    public FrameworkElement Build()
    {
        var zone = Z;
        var s = UI.VStack(18);
        var name = EditorUI.Field(editor, "Name", () => Z.Name, v => editor.UpdateZone(id, "Rename Zone", z => z.Name = v)).Font(Font.Headline);
        s.Children.Add(EditorUI.Section(null,
            UI.HStack(10, UI.Icon(SymbolOf(zone), 22).Foreground(ColorOf(zone)), name.Grow()),
            EditorUI.Toggle(editor, "Active", () => Z.Enabled, v => editor.UpdateZone(id, z => z.Enabled = v))));

        var what = new List<UIElement?>
        {
            EditorUI.Picker(editor, "Kind", ["avoid", "keep_in", "laser_out"], () => Z.Kind, KindName,
                v => editor.UpdateZone(id, "Change Zone Kind", z =>
                {
                    z.Kind = v;
                    z.MarginDeg = v == "laser_out" ? Math.Max(z.MarginDeg, 5) : z.MarginDeg;
                })),
            UI.Text(Explanation(zone.Kind), Font.Caption).Secondary().Wrap(),
            EditorUI.ValueSlider(editor, "Margin", () => Z.MarginDeg, v => editor.UpdateZone(id, z => z.MarginDeg = v),
                                 zone.Kind == "laser_out" ? 3 : 0, zone.Kind == "laser_out" ? 20 : 15, 1, "°"),
        };
        if (zone.Kind != "laser_out")
            what.Add(EditorUI.Picker(editor, "Applies to", ["auto", "all"], () => Z.Applies,
                a => a == "auto" ? "Moving heads" : "All motorised fixtures", v => editor.UpdateZone(id, z => z.Applies = v)));
        s.Children.Add(EditorUI.Section("What It Does", what));

        double Size(int k) => k < Z.Size.Length ? Z.Size[k] : 1;
        void Resize(int k, double v) => editor.UpdateZone(id, "Resize Zone", z =>
        {
            var size = z.Size.ToList();
            while (size.Count <= k) size.Add(1);
            size[k] = v;
            z.Size = [.. size];
        });
        void Centre(int k, double v) => editor.UpdateZone(id, "Move Zone", z =>
        {
            var c = (double[])z.Center.Clone();
            if (k < c.Length) c[k] = v;
            z.Center = c;
        });
        double CentreAt(int k) => k < Z.Center.Length ? Z.Center[k] : 0;
        var box = zone.Shape == "box";
        var place = new List<UIElement?>
        {
            EditorUI.Segmented(editor, ["rect", "box"], () => Z.Shape, v => v == "box" ? "Box" : "Rectangle",
                v => editor.UpdateZone(id, "Change Zone Shape", z =>
                {
                    z.Shape = v;
                    if (v == "box" && z.Size.Length < 3) z.Size = [z.Size[0], 2, z.Size.Length > 1 ? z.Size[1] : 2];
                })),
            EditorUI.ValueSlider(editor, "Width", () => Size(0), v => Resize(0, v), 0.25, 40, 0.25),
            EditorUI.ValueSlider(editor, box ? "Depth" : "Height", () => Size(1), v => Resize(1, v), 0.25, 40, 0.25),
            box ? EditorUI.ValueSlider(editor, "Height", () => Size(2), v => Resize(2, v), 0.25, 15, 0.25) : null,
            EditorUI.ValueSlider(editor, "Across (x)", () => CentreAt(0), v => Centre(0, v), () => -10, () => editor.Doc.Width + 10, 0.25),
            EditorUI.ValueSlider(editor, "Depth (y)", () => CentreAt(1), v => Centre(1, v), () => -16, () => Math.Max(4, editor.Doc.Stage.RoomDepthM + 2), 0.25),
            EditorUI.ValueSlider(editor, "Height (z)", () => CentreAt(2), v => Centre(2, v), () => 0, () => Math.Max(3, editor.Doc.Stage.CeilingM), 0.1),
            EditorUI.ValueSlider(editor, "Rotation", () => Z.RotDeg, v => editor.UpdateZone(id, z => z.RotDeg = v), -180, 180, 5, "°"),
            zone.Shape == "rect" ? EditorUI.ValueSlider(editor, "Tilt", () => Z.TiltDeg, v => editor.UpdateZone(id, z => z.TiltDeg = v), 0, 90, 5, "°") : null,
        };
        s.Children.Add(EditorUI.Section("Shape and Place", place));
        if (zone.Kind == "laser_out")
            s.Children.Add(EditorUI.Section(null,
                UI.HStack(8, UI.Icon("exclamationmark.shield").Foreground(Tint.Orange),
                          UI.Text("A software guard, not a safety system. Set the laser’s masking plate, mounting height and scan "
                                  + "safety first; keep an E-stop at hand.", Font.Caption).Foreground(Tint.Orange).Wrap())));
        s.Children.Add(EditorUI.Section(null,
            UI.Button("Duplicate", editor.DuplicateSelection, "plus.square.on.square"),
            UI.Button("Delete Zone", editor.DeleteSelection, "trash").Foreground(Tint.Red)));
        return s;
    }
}
