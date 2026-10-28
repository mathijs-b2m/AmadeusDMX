// The editor's inspector: with nothing selected, the set on this rig (what hangs where, and what still waits,
// in groups to drag onto the stage) and the venue; else the selected truss, fixture(s) or zone.
// The port of mac/Sources/AmadeusDMX/Rig/Editor/Inspectors.swift. Each panel is built once per shape (EditorUI.Keyed)
// and its controls follow the values.
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;

namespace AmadeusDMX;

public sealed class EditorInspector(AppModel model, RigEditorModel editor)
{
    readonly AppEditorHost _host = new(model);
    readonly HashSet<string> _open = [];   // the model groups shown open

    public FrameworkElement Build()
    {
        var body = EditorUI.Keyed(editor, Key, Panel);
        var scroll = UI.Scroll(new Border { Child = body, Padding = new Thickness(14) });
        return new Border
        {
            Child = scroll, Background = Theme.Brush("LayerFillColorDefaultBrush"), BorderBrush = Theme.Brush("DividerStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(1, 0, 0, 0), MinWidth = 300,
        };
    }

    Truss? TrussOf(PlacedFixture f) => f.Truss is { } t ? editor.Doc.Trusses.FirstOrDefault(x => x.Id == t) : null;

    /// What the panel is made of: rebuilt when it changes, else its controls follow on their own.
    string Key()
    {
        var d = editor.Doc;
        var ids = editor.SelectedFixtures;
        if (ids.Count > 1)
        {
            var fs = d.Fixtures.Where(f => ids.Contains(f.Id)).ToList();
            return string.Join("|", "multi", string.Join(",", ids.Order(StringComparer.Ordinal)),
                               fs.All(f => TrussOf(f) is { Vertical: false }), fs.All(f => TrussOf(f) is { Vertical: true }),
                               fs.All(f => TrussOf(f)?.IsRing == true));
        }
        switch (editor.Selection)
        {
            case { Kind: EditorSelectionKind.Truss, Id: var id }:
                return d.Trusses.FirstOrDefault(t => t.Id == id) is { } t
                    ? string.Join("|", "truss", id, t.Vertical, t.IsRing, t.Arc, t.DiameterM, d.Fixtures.Count(f => f.Truss == id)) : "none";
            case { Kind: EditorSelectionKind.Fixture, Id: var id }:
                return d.Fixtures.FirstOrDefault(f => f.Id == id) is { } f
                    ? string.Join("|", "fixture", id, f.Truss, TrussOf(f)?.Vertical, TrussOf(f)?.IsRing, f.Waiting, f.Universe, f.Address, f.Mode) : "none";
            case { Kind: EditorSelectionKind.Zone, Id: var id }:
                return d.Zones.FirstOrDefault(z => z.Id == id) is { } z ? string.Join("|", "zone", id, z.Shape, z.Kind) : "none";
        }
        return string.Join("|", "overview", d.Set, editor.IsDirty, editor.Busy, d.Stage.Outdoor, d.HasScreen,
            string.Join(";", d.Fixtures.Select(f => $"{f.Id},{f.Key},{f.Waiting},{f.Truss},{f.Side},{f.Mount}")),
            string.Join(";", d.Trusses.Select(t => $"{t.Id},{t.LengthM},{t.Vertical},{t.IsRing},{t.DiameterM},{t.Arc}")),
            string.Join(";", d.Zones.Select(z => $"{z.Id},{z.Name},{z.Kind},{z.Shape},{z.Enabled}")));
    }

    UIElement Panel()
    {
        var ids = editor.SelectedFixtures;
        if (ids.Count > 1) return new MultiFixtureInspector(editor, _host, ids).Build();
        var d = editor.Doc;
        switch (editor.Selection)
        {
            case { Kind: EditorSelectionKind.Truss, Id: var id }:
                return d.Trusses.FirstOrDefault(t => t.Id == id) is { } t ? new TrussInspector(editor, t.Id).Build() : Overview();
            case { Kind: EditorSelectionKind.Fixture, Id: var id }:
                return d.Fixtures.FirstOrDefault(f => f.Id == id) is { } f ? new FixtureInspector(model, editor, _host, f.Id).Build() : Overview();
            case { Kind: EditorSelectionKind.Zone, Id: var id }:
                return d.Zones.FirstOrDefault(z => z.Id == id) is { } z ? new ZoneInspector(editor, z.Id).Build() : Overview();
        }
        return Overview();
    }

    UIElement Overview()
    {
        var d = editor.Doc;
        var fixtures = d.Fixtures;
        var waiting = d.WaitingCount;
        var sections = UI.VStack(18);
        UIElement? Unsaved() => editor.IsDirty ? UI.Label("circle.fill", "Unsaved changes", Font.Callout).Foreground(Tint.Orange) : null;
        if (editor.SetName.Length == 0)  // the rig alone
        {
            sections.Children.Add(EditorUI.Section(null,
                UI.HStack(8, UI.Icon("building.2").Secondary(),
                          UI.Text("The rig alone: its structure. Choose a set under “Showing” to arrange its fixtures here.", Font.Callout).Secondary().Wrap()),
                Unsaved()));
        }
        else
        {
            var head = UI.HStack(8, UI.Icon("light.overhead.right").Foreground(Tint.Accent), UI.Text($"Set “{editor.SetName}”", Font.Headline), UI.Spacer(),
                                 UI.Link("Fixtures…", () => { model.EditingSet = editor.SetName; model.Section = Section.Set; }).Font(Font.Caption));
            var rows = new List<UIElement?> { head };
            if (fixtures.Count > 0)
            {
                var bar = UI.Progress((double)(fixtures.Count - waiting) / fixtures.Count);
                bar.Foreground = new SolidColorBrush(waiting == 0 ? Tint.Green : Tint.Orange);
                rows.Add(bar);
                rows.Add(UI.Text(waiting == 0 ? $"All {fixtures.Count} fixtures hang on this rig."
                                 : $"{fixtures.Count - waiting} of {fixtures.Count} mounted. {waiting} wait in front of the stage.", Font.Callout).Secondary().Wrap());
            }
            if (waiting > 0)
                rows.Add(UI.Button($"Auto-Mount the {waiting} Waiting", () => _ = editor.AutoMount(_host), "wand.and.stars").Prominent()
                    .Disabled(editor.Busy).Align(HorizontalAlignment.Stretch));
            rows.Add(Unsaved());
            sections.Children.Add(EditorUI.Section(null, rows,
                fixtures.Count > 0 ? "Drag a group or a fixture onto a truss in the stage: a group hangs in a row. Click a group to select it all." : null));

            var groups = new List<UIElement?>();
            if (fixtures.Count == 0)
            {
                groups.Add(UI.Text("The set has no fixtures yet.").Secondary());
                groups.Add(UI.Button("Add Fixtures to the Set…", () => { model.EditingSet = editor.SetName; model.Section = Section.Set; }));
            }
            foreach (var g in fixtures.GroupBy(f => f.Key))  // in the set's order (GroupBy keeps the first appearance's)
                groups.Add(ModelGroupRow(g.Key, g.ToList()));
            sections.Children.Add(EditorUI.Section("Fixtures by Model", groups));
        }

        sections.Children.Add(EditorUI.Section("Venue",
            EditorUI.ValueSlider(editor, "Stage width", () => editor.Doc.Stage.WidthM, v => editor.UpdateStage(s => s.WidthM = v), 2, 30, 0.5),
            EditorUI.Toggle(editor, "Outdoor", () => editor.Doc.Stage.Outdoor, v => editor.UpdateStage(s => s.Outdoor = v),
                "An open-air stage: no ceiling, so the director uses the sky far more (beams up into the night). Indoors the ceiling is kept clear."),
            d.Stage.Outdoor ? null
                : EditorUI.ValueSlider(editor, "Ceiling", () => editor.Doc.Stage.CeilingM, v => editor.UpdateStage(s => s.CeilingM = v), 2.5, 20, 0.5),
            EditorUI.ValueSlider(editor, "Room depth", () => editor.Doc.Stage.RoomDepthM, v => editor.UpdateStage(s => s.RoomDepthM = v), 3, 60, 1),
            EditorUI.ValueSlider(editor, "Room width", () => editor.Doc.Stage.RoomWidth, v => editor.UpdateStage("Change Room Width", s => s.RoomWidthM = v),
                () => editor.Doc.Width, () => Math.Max(80, editor.Doc.Width), 1)
                .Tooltip("The hall's width, wall to wall: beams end on its side walls and the haze fills it. The stage stands in its middle"),
            EditorUI.NumberField(editor, "Stage height", () => editor.Doc.Stage.DeckM, editor.SetDeck, 0, 3, 0.1,
                help: "How high the stage stands above the hall floor: heights count from the hall floor, so the stage's grid is its height plus the height above the stage"),
            EditorUI.Toggle(editor, "LED wall behind the DJ", () => editor.Doc.HasScreen, editor.SetScreen),
            d.Stage.Outdoor ? null
                : EditorUI.Toggle(editor, "Beams stay off the ceiling", () => editor.Doc.Stage.CeilingGuard, v => editor.UpdateStage(s => s.CeilingGuard = v),
                    "Moving heads only go up so far that their beam reaches the ceiling at least the room's depth away"),
            EditorUI.Toggle(editor, "Beams never shine back at the DJ", () => editor.Doc.Stage.BackGuard, v => editor.UpdateStage(s => s.BackGuard = v),
                "Moving heads never swing back past the rig towards the stage (pointing steeply down is fine)")));

        var trusses = new List<UIElement?>();
        if (d.Trusses.Count == 0)
            trusses.Add(UI.Text("No trusses: fixtures stand on the floor. Add one with Truss; fixtures snap onto it.").Secondary().Wrap());
        foreach (var t in d.Trusses)
        {
            var id = t.Id;
            trusses.Add(ListRow(t.Vertical ? "building.columns" : t.IsRing ? EditorUI.Symbol("circle") : "square.split.bottomrightquarter", null, t.Id,
                $"{(t.IsRing ? TrussInspector.RingName(t) : $"{Format.Number(t.LengthM)} m")} · {fixtures.Count(f => f.Truss == t.Id)} fixtures",
                () => editor.Selection = EditorSelection.Truss(id)));
        }
        sections.Children.Add(EditorUI.Section("Trusses", trusses));

        var zones = new List<UIElement?>();
        if (d.Zones.Count == 0)
            zones.Add(UI.Text("No zones. Use Zone to keep beams off walls and the set, or lasers out of the audience.").Secondary().Wrap());
        foreach (var z in d.Zones)
        {
            var id = z.Id;
            zones.Add(ListRow(ZoneInspector.SymbolOf(z), ZoneInspector.ColorOf(z), z.Name, ZoneInspector.KindName(z.Kind),
                              () => editor.Selection = EditorSelection.Zone(id)).Opacity(z.Enabled ? 1 : 0.5));
        }
        sections.Children.Add(EditorUI.Section("Zones", zones));
        return sections;
    }

    static FrameworkElement ListRow(string symbol, Windows.UI.Color? color, string title, string detail, Action tap)
    {
        var icon = UI.Icon(EditorUI.Symbol(symbol));
        if (color is { } c) icon.Foreground(c);
        var row = UI.HStack(8, icon, UI.Text(title), UI.Spacer(), UI.Text(detail, Font.Caption).Secondary());
        var b = new Button
        {
            Content = row, HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent), BorderThickness = new Thickness(0), Padding = new Thickness(4, 3, 4, 3),
        };
        b.Click += (_, _) => tap();
        return b;
    }

    /// One model of the set: how many, mounted or waiting; drag it (the waiting ones, else all) onto the stage.
    FrameworkElement ModelGroupRow(string key, List<PlacedFixture> fixtures)
    {
        var def = editor.Definition(key);
        var waiting = fixtures.Where(f => f.Waiting).ToList();
        var dragIDs = (waiting.Count == 0 ? fixtures : waiting).Select(f => f.Id).ToList();
        var ids = fixtures.Select(f => f.Id).ToList();

        var header = UI.HStack(8,
            UI.Icon(EditorUI.FixtureSymbol(def?.Kind)).Foreground(Tint.Accent).Frame(width: 20),
            UI.VStack(1,
                UI.Text($"{fixtures.Count}× {def?.Name ?? key}").Lines(1),
                UI.Text(waiting.Count == 0 ? "all mounted" : $"{waiting.Count} waiting", Font.Caption)
                    .Foreground(waiting.Count == 0 ? Theme.Brush("TextFillColorSecondaryBrush") : new SolidColorBrush(Tint.Orange))),
            UI.Spacer(),
            UI.Icon("hand.draw").Secondary().Tooltip("Drag onto a truss: they hang in a row"));
        header.Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent);  // the whole row takes the pointer
        Draggable(header, RigEditorModel.Payload(dragIDs));
        header.Tapped += (_, e) => { editor.Select(ids); e.Handled = true; };

        var list = UI.VStack(4);
        foreach (var f in fixtures)
        {
            var id = f.Id;
            var status = f.Waiting ? "waiting" : f.Truss is { } t ? $"{t} · {f.Side ?? ""}" : f.Mount;
            var row = UI.HStack(8, UI.Icon("line.3.horizontal", 12).Secondary(), UI.Text(f.Id, Font.Mono), UI.Spacer(),
                UI.Text(status, Font.Caption).Foreground(f.Waiting ? new SolidColorBrush(Tint.Orange) : Theme.Brush("TextFillColorSecondaryBrush")));
            row.Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent);
            row.Tapped += (_, _) => editor.Select([id]);
            Draggable(row, RigEditorModel.Payload([id]));
            list.Children.Add(row);
        }
        var expander = new Expander
        {
            Header = header, Content = list, IsExpanded = _open.Contains(key),
            HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
        };
        expander.Expanding += (_, _) => _open.Add(key);
        expander.Collapsed += (_, _) => _open.Remove(key);
        return expander;
    }

    /// The element can be dragged onto the stage, carrying the fixtures' ids as text.
    static void Draggable(UIElement e, string payload)
    {
        e.CanDrag = true;
        e.DragStarting += (_, args) =>
        {
            args.Data.SetText(payload);
            args.Data.RequestedOperation = DataPackageOperation.Move;
        };
    }
}

/// Several fixtures selected: what they have in common, and what can be done to all of them.
public sealed class MultiFixtureInspector(RigEditorModel editor, IRigEditorHost host, IReadOnlySet<string> ids)
{
    public FrameworkElement Build()
    {
        var d = editor.Doc;
        var fixtures = d.Fixtures.Where(f => ids.Contains(f.Id)).ToList();
        var models = fixtures.Select(f => f.Key).Distinct().ToList();
        Truss? Of(PlacedFixture f) => f.Truss is { } t ? d.Trusses.FirstOrDefault(x => x.Id == t) : null;
        var onBoxTruss = fixtures.All(f => Of(f) is { Vertical: false });
        var onTower = fixtures.All(f => Of(f) is { Vertical: true });
        var s = UI.VStack(18);
        s.Children.Add(EditorUI.Section(null, [
            UI.HStack(10, UI.Icon("square.stack.3d.up", 22).Foreground(Tint.Accent),
                      UI.VStack(2, UI.Text($"{fixtures.Count} Fixtures", Font.Headline),
                                UI.Text(models.Count == 1 ? editor.Definition(models[0])?.Name ?? models[0] : $"{models.Count} models", Font.Caption).Secondary())),
            UI.Text(string.Join(", ", fixtures.Select(f => f.Id).Order(StringComparer.Ordinal)), Font.MonoCaption).Secondary().Wrap(),
        ], "Drag one of them in the stage and the others come along: onto a truss they hang in a row."));

        // the side they share ("" when they differ: none lit)
        string Shared(string fallback)
        {
            var now = editor.Doc.Fixtures.Where(f => ids.Contains(f.Id)).ToList();
            var sides = now.Select(f => f.Side).OfType<string>().Distinct().ToList();
            return sides.Count == 1 ? now.FirstOrDefault()?.Side ?? fallback : "";
        }
        if (onBoxTruss)
        {
            var onRing = fixtures.All(f => Of(f)?.IsRing == true);
            s.Children.Add(EditorUI.Section("Position on the Truss",
                EditorUI.Segmented(editor, ["under", "front", "top", "back"], () => Shared("under"),
                    v => v switch { "under" => "Under", "front" => onRing ? "Outside" : "Front", "top" => "Top", _ => onRing ? "Inside" : "Back" },
                    v => editor.SetSide(ids, v))));
        }
        else if (onTower)
        {
            s.Children.Add(EditorUI.Section("Position on the Tower",
                EditorUI.Segmented(editor, ["front", "left", "right", "back", "top"], () => Shared("front"),
                    v => char.ToUpperInvariant(v[0]) + v[1..], v => editor.SetSide(ids, v))));
        }
        var heads = fixtures.Where(f => !f.Waiting && editor.Definition(f.Key)?.IsMoving == true).Select(f => f.Id).ToList();
        if (heads.Count > 0) s.Children.Add(HeadGroupSection.Build(editor, heads));
        s.Children.Add(EditorUI.Section(null,
            UI.Button("Auto-Mount These", () => _ = editor.AutoMount(host, ids.ToList()), "wand.and.stars"),
            UI.Button("Rotate 90°", () => editor.RotateSelection(90), "rotate.right"),
            UI.Button("Unmount (Back to Waiting)", () => editor.Unmount(ids), "arrow.down.to.line")));
        return s;
    }
}

/// The head group of the selected moving heads (amadeus/rig/groups.py): Automatic groups them by where they
/// stand (one row per depth and height, a tower, a ring); a name puts them in a group of their own.
public static class HeadGroupSection
{
    const string Automatic = "Automatic";

    public static FrameworkElement Build(RigEditorModel editor, IReadOnlyCollection<string> ids)
    {
        string? Current()  // the group they share (blank: automatic); null when they differ
        {
            var names = ids.Select(i => editor.Doc.Group(i) ?? "").Distinct().ToList();
            return names.Count == 1 ? names[0] : null;
        }
        var box = new ComboBox { IsEditable = true, MinWidth = 160 };
        box.Tooltip("Type a name for a group of its own, or pick one already on this rig, or Automatic");
        var following = false;
        void Follow()
        {
            following = true;
            try
            {
                box.Items.Clear();
                box.Items.Add(Automatic);
                foreach (var g in editor.Doc.GroupNames) box.Items.Add(g);
                var now = Current();
                box.PlaceholderText = now is null ? "Mixed" : Automatic;
                box.SelectedItem = now is { Length: > 0 } ? now : now is null ? null : Automatic;
                box.Text = now is { Length: > 0 } ? now : now is null ? "" : Automatic;
            }
            finally { following = false; }
        }
        void Set(string? name) => editor.SetGroup(ids, name is null || name.Trim() == Automatic ? null : name);
        box.SelectionChanged += (_, _) => { if (!following && box.SelectedItem is string s) Set(s); };
        box.TextSubmitted += (_, e) => { e.Handled = true; if (!following) Set(e.Text); };
        var count = UI.Text("", Font.Caption).Secondary();
        var rows = UI.VStack(10, UI.Row("Group", box), count).Bind(editor, [nameof(RigEditorModel.Version)], _ =>
        {
            if (box.FocusState == FocusState.Unfocused) Follow();
            var now = Current();
            var n = now is { Length: > 0 } ? editor.Doc.Fixtures.Count(f => !f.Waiting && editor.Doc.Group(f.Id) == now) : 0;
            count.Text = n > 0 ? $"{n} heads in “{now}”" : "";
            count.Visibility = n > 0 ? Visibility.Visible : Visibility.Collapsed;
        });
        Follow();
        return EditorUI.Section("Head Group", [rows],
            "The show plays a group as one line: fans, waves and chases run through it, and the groups answer each other. "
            + "Automatic groups heads by where they stand: a row at one depth and height, a tower, a ring. "
            + "Type a name to group heads that don't stand in a line, such as a scattered floor.");
    }
}

public sealed class TrussInspector(RigEditorModel editor, string id)
{
    static string Metres(double v) => v.ToString("0.00", System.Globalization.CultureInfo.InvariantCulture) + " m";

    /// "Ø 4 m circle" / "Ø 6 m half circle".
    public static string RingName(Truss t)
    {
        var d = Format.Number(t.DiameterM ?? 4);
        return t.IsFullRing ? $"Ø {d} m circle" : t.Arc == 180 ? $"Ø {d} m half circle" : $"Ø {d} m, {(int)t.Arc}° arc";
    }

    Truss T => editor.Doc.Trusses.FirstOrDefault(t => t.Id == id) ?? new Truss(id, 1, 0, 0, 0);

    public FrameworkElement Build()
    {
        var truss = T;
        var s = UI.VStack(18);
        s.Children.Add(EditorUI.Section(null,
            UI.HStack(10, UI.Icon(truss.Vertical ? "building.columns" : truss.IsRing ? EditorUI.Symbol("circle") : "square.split.bottomrightquarter", 22)
                              .Foreground(Tint.Accent),
                      UI.VStack(2, UI.Text(truss.Id, Font.Headline),
                                UI.Text(truss.Vertical ? "Tower, box truss 30 cm" : truss.IsRing ? $"Round truss, {RingName(truss)}" : "Box truss (quatro), 30 cm",
                                        Font.Caption).Secondary())),
            truss.IsRing ? UI.Text("Heads on a ring play it as a circle: crowns of beams out of it, cones, twisters, waves running round.", Font.Caption)
                .Secondary().Wrap() : null));

        var size = new List<UIElement?>();
        if (truss.IsRing)
        {
            var diameters = Truss.RingDiameters.Append(truss.DiameterM ?? 4).Distinct().Order().ToList();
            size.Add(EditorUI.Picker(editor, "Diameter", diameters, () => T.DiameterM ?? 4, dm => $"Ø {Format.Number(dm)} m",
                dm => editor.UpdateTruss(id, "Change Diameter", t => t.DiameterM = dm)));
            size.Add(EditorUI.Stepper(editor, () => $"Round the arc {Metres(T.LengthM)}",
                () => editor.UpdateTruss(id, "Change Diameter", t => t.DiameterM = Math.Max(1, (t.DiameterM ?? 4) - 0.5)),
                () => editor.UpdateTruss(id, "Change Diameter", t => t.DiameterM = Math.Min(20, (t.DiameterM ?? 4) + 0.5))));
            var arcs = new List<double> { 360, 180 };
            if (!Truss.RingArcs.Contains(truss.Arc)) arcs.Add(truss.Arc);
            size.Add(EditorUI.Segmented(editor, arcs, () => T.Arc, a => a == 360 ? "Full circle" : a == 180 ? "Half circle" : $"{(int)a}°",
                a => editor.UpdateTruss(id, a >= 359.5 ? "Make Full Circle" : "Make Half Circle", t => t.ArcDeg = a)));
        }
        else
        {
            size.Add(EditorUI.Stepper(editor, () => $"Length {Metres(T.LengthM)}",
                () => editor.UpdateTruss(id, t => t.LengthM = Math.Max(0.5, t.LengthM - 0.5)),
                () => editor.UpdateTruss(id, t => t.LengthM = Math.Min(20, t.LengthM + 0.5))));
        }
        size.Add(EditorUI.ValueSlider(editor, "Across (x)", () => T.XM, v => editor.UpdateTruss(id, t => t.XM = v), () => -6, () => editor.Doc.Width + 6, 0.25));
        size.Add(EditorUI.ValueSlider(editor, "Depth (y)", () => T.YM, v => editor.UpdateTruss(id, t => t.YM = v), -14, 4, 0.25));
        if (!truss.Vertical)
        {
            size.Add(EditorUI.ValueSlider(editor, "Height", () => T.ZM, v => editor.UpdateTruss(id, t => t.ZM = v),
                                          () => 0.5, () => Math.Max(2, editor.Doc.Stage.CeilingM), 0.1));
            size.Add(EditorUI.ValueSlider(editor, "Rotation", () => T.RotDeg, v => editor.UpdateTruss(id, t => t.RotDeg = v), -180, 180, 15, "°"));
        }
        s.Children.Add(EditorUI.Section("Size and Place", size));

        if (!truss.Vertical)
        {
            var aims = new[] { "", "audience", "down" };
            var picker = (ComboBox)UI.Picker(aims, T.Aim ?? "", a => a switch
            {
                "" => T.YM >= Truss.OverCrowdM ? "Automatic (down)" : "Automatic",
                "audience" => "Towards the audience",
                _ => "Down",
            }, a => editor.UpdateTruss(id, "Change Aim", t => t.Aim = a.Length == 0 ? null : a))
                .Tooltip("Where the heads on this truss play. Automatic: down when it hangs over the crowd, else wherever the show aims");
            var note = UI.Text(AimNote(T), Font.Caption).Secondary().Wrap();
            var lights = UI.VStack(10, UI.Row("Aim", picker), note).Bind(editor, [nameof(RigEditorModel.Version)], _ =>
            {
                picker.Select(T.Aim ?? "");
                if (picker.Items.FirstOrDefault() is ComboBoxItem first) first.Content = T.YM >= Truss.OverCrowdM ? "Automatic (down)" : "Automatic";
                note.Text = AimNote(T);
            });
            s.Children.Add(EditorUI.Section("Lights", lights));
        }
        s.Children.Add(EditorUI.Section(null,
            EditorUI.Labeled("Fixtures on it", $"{editor.Doc.Fixtures.Count(f => f.Truss == id)}"),
            UI.Button("Duplicate", editor.DuplicateSelection, "plus.square.on.square"),
            UI.Button("Delete Truss", editor.DeleteSelection, "trash").Foreground(Tint.Red)));
        return s;
    }

    static string AimNote(Truss t) => t.LightAim switch
    {
        "down" => "The heads play down onto the crowd under it (they still go up for a build).",
        "audience" => "The heads play out towards the audience, never back at the stage.",
        _ => "The heads play wherever the show aims: the crowd, the stage or the sky.",
    };
}

public sealed class FixtureInspector(AppModel model, RigEditorModel editor, IRigEditorHost host, string id)
{
    PlacedFixture F => editor.Doc.Fixtures.FirstOrDefault(f => f.Id == id) ?? new PlacedFixture(id, "", "", 1, 1, "floor", 0, 0, 0, 0, null, null, null);

    static Vec2 DefaultAim(FixtureKind? k) => k switch
    {
        FixtureKind.Laser => new(0, 13),
        FixtureKind.Blinder => new(0, 7),
        FixtureKind.Strobe => new(0, 8),
        FixtureKind.Smoke => new(0, 10),
        _ => new(0, 80),
    };

    public FrameworkElement Build()
    {
        var fixture = F;
        var def = editor.Definition(fixture.Key);
        var truss = editor.Doc.Trusses.FirstOrDefault(t => t.Id == fixture.Truss);
        void Move(Action<PlacedFixture> body) => editor.UpdateFixture(id, "Move Fixture", body);
        var s = UI.VStack(18);
        s.Children.Add(EditorUI.Section(null,
            UI.HStack(10, UI.Icon(EditorUI.FixtureSymbol(def?.Kind), 22).Foreground(Tint.Accent),
                      UI.VStack(2, UI.Text(fixture.Id, Font.Headline), UI.Text(def?.Name ?? fixture.Key, Font.Caption).Secondary())),
            EditorUI.Labeled("Patch", $"{fixture.PatchText} · {fixture.Mode}"),
            LightTest(def)));

        var mounting = new List<UIElement?>
        {
            EditorUI.Picker(editor, "Truss", [.. new[] { "" }.Concat(editor.Doc.Trusses.Select(t => t.Id))], () => F.Truss ?? "",
                t => t.Length == 0 ? "None (floor / stand)" : t, t => editor.Attach(id, t.Length == 0 ? null : t)),
        };
        if (truss is { Vertical: false } box)
        {
            mounting.Add(EditorUI.Segmented(editor, ["under", "front", "top", "back"], () => F.Side ?? (F.Mount == "stand" ? "top" : "under"),
                v => v switch
                {
                    "under" => "Under 0°", "front" => box.IsRing ? "Outside 90°" : "Front 90°", "top" => "Top 180°", _ => box.IsRing ? "Inside 270°" : "Back 270°",
                }, v => editor.SetSide(id, v)));
        }
        else if (truss is { Vertical: true })
        {
            mounting.Add(EditorUI.Segmented(editor, ["front", "left", "right", "back", "top"], () => F.Side ?? "front",
                v => char.ToUpperInvariant(v[0]) + v[1..], v => editor.SetSide(id, v)));
            mounting.Add(UI.Text("", Font.Caption).Secondary().Wrap().Bind(editor, nameof(RigEditorModel.Version), t =>
                t.Text = F.Side == "top" ? "Standing on top of the tower." : "Hanging off the tower's face, the head pointing out."));
        }
        else
        {
            string[] mounts = truss is null ? ["hang", "stand", "floor"] : ["hang", "stand"];
            mounting.Add(EditorUI.Segmented(editor, mounts, () => F.Mount,
                m => m switch { "hang" => truss is null ? "Hanging" : "Under", "stand" => truss is null ? "Stand" : "On top", _ => "Floor" },
                m => editor.UpdateFixture(id, "Change Mount", f =>
                {
                    f.Mount = m;
                    if (m == "floor" && f.Truss is null) f.ZM = RigEditorModel.FloorHeight(editor.Doc.Stage, f);
                })));
        }
        if (truss is { } tr)
        {
            var tid = tr.Id;
            Truss Now() => editor.Doc.Trusses.FirstOrDefault(t => t.Id == tid) ?? tr;
            mounting.Add(EditorUI.ValueSlider(editor, tr.Vertical ? "Height on tower" : "Along the truss", () => F.TrussPos ?? 0, v => Move(f => f.TrussPos = v),
                () => Now().Vertical ? 0.2 : -Now().LengthM / 2, () => Now().Vertical ? Now().LengthM : Now().LengthM / 2, 0.05));
        }
        else
        {
            mounting.Add(EditorUI.ValueSlider(editor, "Across (x)", () => F.X * editor.Doc.Width, v => Move(f => f.X = v / editor.Doc.Width),
                () => -6, () => editor.Doc.Width + 6, 0.05));
            mounting.Add(EditorUI.ValueSlider(editor, "Depth (y)", () => F.YM, v => Move(f => f.YM = v), -14, 4, 0.05));
            mounting.Add(EditorUI.ValueSlider(editor, "Height", () => F.ZM, v => Move(f => f.ZM = v), () => 0, () => Math.Max(2, editor.Doc.Stage.CeilingM), 0.05));
        }
        s.Children.Add(EditorUI.Section("Mounting", mounting));

        var orientation = new List<UIElement?>
        {
            EditorUI.ValueSlider(editor, "Rotation", () => F.RotDeg, v => Move(f => f.RotDeg = v), -180, 180, 5, "°"),
        };
        if (!(def?.IsMoving ?? true))
        {
            Vec2 Aim() => F.Aim ?? DefaultAim(def?.ElementKind);
            orientation.Add(EditorUI.ValueSlider(editor, "Aim up/down", () => Aim().Y,
                v => { var a = Aim(); editor.UpdateFixture(id, "Aim", f => f.Aim = new Vec2(a.X, v)); }, -90, 90, 5, "°"));
            orientation.Add(EditorUI.ValueSlider(editor, "Aim left/right", () => Aim().X,
                v => { var a = Aim(); editor.UpdateFixture(id, "Aim", f => f.Aim = new Vec2(v, a.Y)); }, -180, 180, 5, "°"));
            if (def?.ElementKind == FixtureKind.Laser)
                orientation.Add(UI.Text("Where the laser points when its pattern is centred: measure it on the real laser. The laser "
                                        + "guard uses it to keep beams out of the laser safety zones.", Font.Caption).Foreground(Tint.Orange).Wrap());
        }
        else
        {
            orientation.Add(UI.Text("Moving fixtures aim themselves; the rotation tells the engine where their front is.", Font.Caption).Secondary().Wrap());
        }
        s.Children.Add(EditorUI.Section("Orientation", orientation));
        if (def?.IsMoving == true && !fixture.Waiting) s.Children.Add(HeadGroupSection.Build(editor, [id]));

        s.Children.Add(EditorUI.Section(null, [
            fixture.Waiting
                ? UI.Label("hourglass", "Waiting in front of the stage: drag it onto a truss, or Auto-Mount.", Font.Callout).Foreground(Tint.Orange)
                : UI.Button("Unmount (Back to Waiting)", () => editor.Unmount(new HashSet<string> { id }), "arrow.down.to.line"),
        ], "The fixture stays in the set; to remove it from your gear, use the Set page."));
        return s;
    }

    /// The light test on the real rig: on until switched off, a head pointed at the audience; while a head is lit,
    /// where its real beam went instead (its calibration put right). Rebuilt when it is switched or refused.
    UIElement LightTest(FixtureDefinition? def) => EditorUI.Keyed([editor, model],
        () => $"{editor.Lit.Contains(id)}|{editor.TestRefusal(host, F)}", () =>
    {
        var refusal = editor.TestRefusal(host, F);
        var on = editor.Lit.Contains(id);
        var test = UI.Button(on ? "On: Click to Switch Off" : "Test on the Lights", () => _ = editor.ToggleTest(host, id), on ? "lightbulb.fill" : "lightbulb")
            .Disabled(refusal is not null && !on)
            .Tooltip(refusal ?? (on ? "Switch it off again"
                                 : "Light it on the real rig until you switch it off (a minute at most), a head aimed as here: is it patched, connected and hung the way it is placed?"));
        if (on) test.Foreground(Tint.Yellow);
        var rows = UI.VStack(8, test);
        if (refusal is not null) rows.Children.Add(UI.Text(refusal, Font.Caption).Secondary().Wrap());
        if (on && def?.IsMoving == true)
        {
            Button Fix(string title, string symbol, string seen) => UI.Button(title, () => _ = editor.FixFront(host, id, seen), symbol)
                .Tooltip("Left and right as seen from the audience, facing the stage. The head's calibration is put right in the set and it is aimed again: pressed the wrong one, it ends up the other way; press that one");
            rows.Children.Add(UI.VStack(6,
                UI.Text("Its beam should point at the audience, as on the stage here. Where does the real one point?", Font.Caption).Secondary().Wrap(),
                UI.HStack(8, Fix("Left", "arrow.left", "left"), Fix("Right", "arrow.right", "right"), Fix("Back", "arrow.uturn.down", "back"))));
        }
        return rows;
    });
}
