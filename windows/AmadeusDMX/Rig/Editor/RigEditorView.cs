// The rig editor: the stage in 3D (or from above), the rig's trusses and zones, the set's fixtures to mount on
// it (one by one, as a group, or automatically), and an inspector for the selection.
// The port of mac/Sources/AmadeusDMX/Rig/Editor/RigEditorView.swift; the stage comes through EditorViewport.
using System.Diagnostics;
using System.Globalization;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.System;

namespace AmadeusDMX;

public sealed class RigEditorView(AppModel model, RigEditorModel editor)
{
    readonly UndoManager _undo = new();
    readonly AppEditorHost _host = new(model);
    EditorViewport? _viewport;
    FrameworkElement? _root;

    public RigEditorModel Editor => editor;

    public FrameworkElement Build()
    {
        editor.UndoManager = _undo;
        _viewport = new EditorViewport(editor);

        var stage = new Grid { MinWidth = 520 };
        stage.Children.Add(_viewport.Build());
        stage.Children.Add(UI.VStack(8, Toolbar(),
            EditorUI.Keyed(editor, () => (editor.ChangedOnDisk is null).ToString(), () => editor.ChangedOnDisk is null ? null : ChangedOnDisk()))
            .Align(VerticalAlignment.Top).Margin(12, 12, 12, 0));
        // the hint (or the check) on the left, wrapping in a narrow window; the camera buttons always in view
        var bottom = new Grid { ColumnSpacing = 8, VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(12, 0, 12, 12) };
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        bottom.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var info = EditorUI.Keyed(editor, () => editor.Check is null ? "hint" : "check",
                                  () => editor.Check is null ? Hint() : new HangCheckPanel(editor, _host).Build());
        info.VerticalAlignment = VerticalAlignment.Bottom;
        info.HorizontalAlignment = HorizontalAlignment.Left;
        var cameras = CameraButtons();
        Grid.SetColumn(cameras, 1);
        bottom.Children.Add(info);
        bottom.Children.Add(cameras);
        stage.Children.Add(bottom);

        var inspector = new EditorInspector(model, editor).Build();
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(340) });
        Grid.SetColumn(stage, 0);
        Grid.SetColumn(inspector, 1);
        root.Children.Add(stage);
        root.Children.Add(inspector);

        // Ctrl+S saves the rig; Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) undo and redo the editor's changes
        Accelerator(root, VirtualKey.S, VirtualKeyModifiers.Control, Save);
        Accelerator(root, VirtualKey.Z, VirtualKeyModifiers.Control, _undo.Undo, inText: false);
        Accelerator(root, VirtualKey.Z, VirtualKeyModifiers.Control | VirtualKeyModifiers.Shift, _undo.Redo, inText: false);
        Accelerator(root, VirtualKey.Y, VirtualKeyModifiers.Control, _undo.Redo, inText: false);

        root.Bind(model, nameof(AppModel.ConfigVersion), _ => editor.ReloadIfClean());
        _ = editor.LoadDrawings(_host);  // the plans an import placed the fixtures from, under the rig
        if (model.PendingSelection is { } ids)  // a line of the import's report: its fixtures selected once the rig is open
        {
            model.PendingSelection = null;
            editor.Select(ids.Where(id => editor.Doc.Fixtures.Any(f => f.Id == id)).ToList());
        }
        root.Bind(editor, nameof(RigEditorModel.Message), _ => ClearLater(editor.Message));
        root.Unloaded += async (_, _) =>  // the lights go off
        {
            if (root.IsLoaded) return;
            if (editor.Check is not null) await editor.StopCheck(_host);
            if (editor.Lit.Count > 0) await editor.SwitchOffTests(_host);
        };
        _root = root;
        return root;
    }

    /// A shortcut over the whole editor; `inText: false`: not while typing in a field (it has its own undo).
    void Accelerator(UIElement on, VirtualKey key, VirtualKeyModifiers mods, Action action, bool inText = true)
    {
        var a = new KeyboardAccelerator { Key = key, Modifiers = mods };
        a.Invoked += (_, e) =>
        {
            if (!inText && _root?.XamlRoot is { } xr && FocusManager.GetFocusedElement(xr) is TextBox) return;
            e.Handled = true;
            action();
        };
        on.KeyboardAccelerators.Add(a);
    }

    /// A message stays for 2.5 s.
    async void ClearLater(string? m)
    {
        if (m is null) return;
        await Task.Delay(2500);
        if (editor.Message == m) editor.Message = null;
    }

    async void Save()
    {
        try { await editor.Save(_host); }
        catch (Exception e) when (e is not OutOfMemoryException) { await EditorUI.Alert(_root?.XamlRoot, "Couldn’t Save", e.Message); }
    }

    static void Run(Func<Task> op) => _ = op();

    // MARK: the toolbar

    static readonly double[] TrussLengths = [1, 2, 3, 4, 6, 8, 10];
    static readonly double[] TowerLengths = [2, 3, 4];

    static string N(double v) => Format.Number(v);

    FrameworkElement Toolbar()
    {
        string Key()
        {
            var d = editor.Doc;
            return string.Join("|", editor.Tool, editor.Busy, editor.IsDirty, d.WaitingCount, d.Fixtures.Count, editor.SelectedFixtures.Count,
                               d.Set, editor.Check is null, editor.ShowZones, editor.Snap, model.EditingRig, model.EngineRunning, model.Rigs.Count,
                               editor.Drawings.Count);
        }
        var bar = EditorUI.Keyed([editor, model], Key, BuildToolbar);
        return new Border
        {
            Child = bar, Padding = new Thickness(8), CornerRadius = new CornerRadius(12),
            Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"), BorderBrush = Theme.Brush("CardStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(1), HorizontalAlignment = HorizontalAlignment.Stretch,
        };
    }

    /// Saved elsewhere (your AI assistant, the web setup page) while there are unsaved changes here: which to keep.
    FrameworkElement ChangedOnDisk()
    {
        var row = UI.HStack(10,
            UI.Label("exclamationmark.triangle", "Saved elsewhere while you were editing", Font.Callout)
                .Tooltip("Your AI assistant, the setup page or the command line saved this rig while you have unsaved changes here. Load theirs (Undo brings yours back), or keep yours."),
            UI.Button("Load Their Changes", editor.TakeChangesOnDisk).Prominent()
                .Tooltip("Show the rig as it was saved elsewhere. Undo brings your changes back"),
            UI.Button("Keep Mine", editor.KeepChangesHere).Tooltip("Keep your changes: saving puts them over the other ones"));
        return new Border
        {
            Child = row, Padding = new Thickness(12, 8, 12, 8), CornerRadius = new CornerRadius(12),
            Background = Theme.Brush("SystemFillColorCautionBackgroundBrush"), BorderBrush = Theme.Brush("CardStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(1), HorizontalAlignment = HorizontalAlignment.Center,
        };
    }

    UIElement BuildToolbar()
    {
        var d = editor.Doc;
        var row = new FlowPanel { Spacing = 8, LineSpacing = 8 };  // the tools wrap in a narrow window; Save stays in view
        row.Children.Add(new RigMenu(model, editor).Build());
        row.Children.Add(ToolPicker());
        if (editor.Tool == EditorTool.Truss)
            row.Children.Add(EditorUI.Stepper(editor, () => string.Format(CultureInfo.InvariantCulture, "at {0:0.0} m", editor.BuildHeight),
                () => editor.BuildHeight = Math.Max(1, editor.BuildHeight - 0.25), () => editor.BuildHeight = Math.Min(15, editor.BuildHeight + 0.25),
                "The height a new truss goes up to"));
        else if (editor.Tool == EditorTool.Tower)
            row.Children.Add(EditorUI.Stepper(editor, () => string.Format(CultureInfo.InvariantCulture, "{0:0.0} m tall", editor.TowerHeight),
                () => editor.TowerHeight = Math.Max(1, editor.TowerHeight - 0.5), () => editor.TowerHeight = Math.Min(12, editor.TowerHeight + 0.5),
                "How tall a new tower is"));

        row.Children.Add(UI.MenuButton(UI.Label("square.split.bottomrightquarter", "Truss"), () => UI.Menu([
            UI.Note("Box truss (quatro, 30 cm)"),
            .. TrussLengths.Select(l => UI.Item($"{(int)l} m", () => editor.AddTruss(l))),
            UI.Separator(),
            UI.Note("Round truss (circle)"),
            .. Truss.RingDiameters.Select(dm => UI.Item($"Ø {(int)dm} m circle", () => editor.AddRing(dm))),
            UI.Separator(),
            UI.Note("Half circle"),
            .. Truss.RingDiameters.Select(dm => UI.Item($"Ø {(int)dm} m half circle", () => editor.AddRing(dm, 180))),
            UI.Separator(),
            UI.Note("Tower"),
            .. TowerLengths.Select(l => UI.Item($"{(int)l} m tower", () => editor.AddTruss(l, vertical: true))),
            UI.Separator(),
            UI.Note("Light stands (bar on tripods)"),
            .. Truss.StandPresets.Select(p => UI.Item(p.Title, () => editor.AddStand(p))),
        ])).Tooltip("Add a truss or a tower"));

        row.Children.Add(UI.MenuButton(UI.Label("square.dashed", "Zone"), () => UI.Menu([
            UI.Note("Artistic (moving heads)"),
            .. new[] { RigEditorModel.ZonePreset.Wall, RigEditorModel.ZonePreset.FloorArea, RigEditorModel.ZonePreset.KeepIn }
                .Select(p => UI.Item(RigEditorModel.Title(p), () => editor.AddZone(p), RigEditorModel.Symbol(p))),
            UI.Separator(),
            UI.Note("Safety (lasers)"),
            .. new[] { RigEditorModel.ZonePreset.LaserAudience, RigEditorModel.ZonePreset.LaserPlane }
                .Select(p => UI.Item(RigEditorModel.Title(p), () => editor.AddZone(p), RigEditorModel.Symbol(p))),
        ])).Tooltip("Draw a zone: where beams may not go (or may only go)"));

        row.Children.Add(AutoMountButton());

        if (d.Set.Length > 0)
        {
            var check = UI.IconButton("checklist", "The check after hanging: light the fixtures one by one in the hang sheet's order, and put right what was hung the wrong way in the app",
                () => Run(() => editor.Check is null ? editor.StartCheck(_host) : editor.StopCheck(_host)))
                .Disabled(editor.Busy || d.Fixtures.Count == 0);
            if (editor.Check is not null) check.Prominent();
            row.Children.Add(check);
            row.Children.Add(UI.IconButton("printer", "The hang sheet for the crew: where every fixture goes on which truss, which way round, its DMX address, and labels to stick on them. Opens in your browser to print or save as PDF",
                () => Run(() => editor.HangSheet(_host))).Disabled(editor.Busy || d.Fixtures.Count == 0));
        }

        if (editor.Drawings.Count > 0) row.Children.Add(DrawingsMenu());

        row.Children.Add(IconToggle(editor.ShowZones ? "eye" : "eye.slash", editor.ShowZones, v => editor.ShowZones = v,
                                    "Show or hide the zones (a selected zone always shows)"));
        row.Children.Add(IconToggle("squareshape.split.3x3", editor.Snap, v => editor.Snap = v,
                                    "Snap to the 25 cm grid and onto trusses (hold Alt while dragging to place freely)"));
        var end = UI.HStack(8);
        if (editor.Busy) end.Children.Add(UI.Spinner());
        var message = UI.Text("", Font.Callout).Secondary().Bind(editor, nameof(RigEditorModel.Message), t => t.Text = editor.Message ?? "");
        message.MaxWidth = 240;
        end.Children.Add(message);
        end.Children.Add(UI.Button("Revert", editor.Revert).Disabled(!editor.IsDirty));
        end.Children.Add(UI.Button("Save", Save).Prominent().Disabled(!editor.IsDirty).Tooltip("Save the rig, and where the set hangs on it (Ctrl+S)"));
        end.VerticalAlignment = VerticalAlignment.Top;
        var bar = new Grid { ColumnSpacing = 8 };
        bar.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        bar.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Grid.SetColumn(end, 1);
        bar.Children.Add(row);
        bar.Children.Add(end);
        return bar;
    }

    /// Select · Draw Truss · Place Tower (a segmented picker of symbols).
    FrameworkElement ToolPicker()
    {
        (EditorTool Tool, string Symbol, string Title)[] tools =
            [(EditorTool.Select, "cursorarrow", "Select"), (EditorTool.Truss, "line.diagonal", "Draw Truss"), (EditorTool.Tower, "arrow.up.to.line", "Place Tower")];
        var row = UI.HStack(2);
        foreach (var (tool, symbol, title) in tools)
        {
            var b = new ToggleButton { Content = UI.Icon(symbol, 14), IsChecked = editor.Tool == tool, Padding = new Thickness(10, 6, 10, 6) }
                .Tooltip(title);
            b.Click += (_, _) => editor.Tool = tool;
            row.Children.Add(b);
        }
        return row.Tooltip("Select and move · Draw a truss on the floor (T) · Click to set a tower · Esc: back to select");
    }

    static ToggleButton IconToggle(string symbol, bool on, Action<bool> changed, string help)
    {
        var b = new ToggleButton { Content = UI.Icon(symbol, 14), IsChecked = on, Padding = new Thickness(8, 6, 8, 6) }.Tooltip(help);
        b.Click += (_, _) => changed(b.IsChecked == true);
        return b;
    }

    /// Auto-Mount: the button mounts what waits (or re-mounts everything when nothing does); its menu has the rest.
    FrameworkElement AutoMountButton()
    {
        var d = editor.Doc;
        var waiting = d.WaitingCount;
        var selected = editor.SelectedFixtures.ToList();
        var menu = UI.Menu(
            UI.Item($"Mount the {waiting} Waiting", () => Run(() => editor.AutoMount(_host)), "wand.and.stars").Disabled(waiting == 0),
            selected.Count > 0 ? UI.Item($"Re-Mount the Selected {selected.Count}", () => Run(() => editor.AutoMount(_host, selected)), "arrow.triangle.2.circlepath") : null,
            UI.Item("Put in Name Order", () => Run(() => editor.PutInOrder(_host)), "list.number").Disabled(d.Fixtures.Count == d.WaitingCount)
                .Tooltip("The fixtures stay on their spots, but in name order along the rig: top1 at the first place, top2 at the next"),
            UI.Separator(),
            UI.Item("Re-Mount Everything", () => Run(() => editor.AutoMount(_host, all: true)), "arrow.counterclockwise"));
        var b = new SplitButton { Content = UI.Label("wand.and.stars", "Auto-Mount"), Flyout = menu }
            .Tooltip("Hang the fixtures that wait in front of the stage: heads on the trusses, lasers high at the back, bars on the floor…");
        b.Click += (_, _) => Run(() => editor.AutoMount(_host, all: editor.Doc.WaitingCount == 0));
        b.IsEnabled = !(editor.Busy || d.Fixtures.Count == 0);
        return b;
    }

    // MARK: the drawings under the rig

    /// Drawings: show or hide each one, how opaque, line one up again, take one away. With one drawing those are
    /// direct items.
    FrameworkElement DrawingsMenu()
    {
        MenuFlyout Menu()
        {
            var drawings = editor.Drawings;
            var items = new List<MenuFlyoutItemBase?>();
            if (drawings.Count > 1) items.Add(UI.Note("Show"));
            foreach (var u in drawings)
            {
                var shown = new ToggleMenuFlyoutItem { Text = drawings.Count == 1 ? $"Show “{u.Name}”" : u.Name, IsChecked = editor.IsShown(u) };
                shown.Click += (_, _) => editor.SetShown(u, shown.IsChecked);
                items.Add(shown.Tooltip(u.Source));
            }
            items.Add(UI.Separator());
            items.Add(UI.Note("Opacity"));
            foreach (var o in RigEditorModel.Opacities)
                items.Add(UI.Choice($"{o * 100:0} %", "drawingOpacity", Math.Abs(editor.DrawingOpacity - o) < 0.01, () => editor.DrawingOpacity = o));
            items.Add(UI.Separator());
            if (drawings.Count == 1)
            {
                var u = drawings[0];
                items.Add(UI.Item("Line Up…", () => LineUp(u), "ruler"));
                items.Add(UI.Item("Remove…", () => RemoveDrawing(u), "trash"));
            }
            else
            {
                items.Add(UI.SubMenu("Line Up", [.. drawings.Select(u => UI.Item($"{u.Name}…", () => LineUp(u)))]));
                items.Add(UI.SubMenu("Remove", [.. drawings.Select(u => UI.Item($"{u.Name}…", () => RemoveDrawing(u)))]));
            }
            return UI.Menu([.. items]);
        }
        var b = UI.MenuButton(UI.Label("doc.richtext", "Drawings"), Menu)
            .Tooltip("The venue's drawings under the rig (from the import): show or hide them, line one up with the stage, remove one. Best seen from Plan view");
        b.IsEnabled = !editor.Busy;
        return b;
    }

    /// Line Up…: two clicks on the page; unsaved changes are saved or discarded first (the engine saves the rig).
    async void LineUp(Underlay u)
    {
        var root = _root?.XamlRoot;
        if (root is null) return;
        if (editor.Picture(u) is not { } picture)
        {
            await EditorUI.Alert(root, "Couldn’t Show the Drawing", "Its page isn’t there yet: the engine's setup service may still be starting. Try again in a moment.");
            return;
        }
        if (editor.IsDirty)
        {
            var ask = new ContentDialog
            {
                XamlRoot = root, Title = "Save your changes first?",
                Content = UI.Text("Lining up a drawing moves its fixtures and trusses in the saved rig, and the editor reads it again: changes not saved are lost.").Wrap(),
                PrimaryButtonText = "Save", SecondaryButtonText = "Discard", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Primary,
            };
            switch (await Dialogs.Show(ask))
            {
                case ContentDialogResult.Primary:
                    try { await editor.Save(_host); }
                    catch (Exception e) when (e is not OutOfMemoryException) { await EditorUI.Alert(root, "Couldn’t Save", e.Message); return; }
                    break;
                case ContentDialogResult.Secondary:
                    editor.Revert();
                    break;
                default:
                    return;
            }
        }
        if (await new LineUpSheet(u, picture, editor.Doc.Width).Show(root) is { } r)
            await editor.LineUp(_host, u, r.A, r.B, r.WidthM);
    }

    async void RemoveDrawing(Underlay u)
    {
        if (await EditorUI.Confirm(_root?.XamlRoot, $"Remove the drawing “{u.Name}”?", "It is taken away from under the rig; the fixtures stay where they are.", "Remove"))
            await editor.RemoveDrawing(_host, u);
    }

    // MARK: under the stage

    FrameworkElement Hint()
    {
        var text = UI.Text("", Font.Caption);
        text.TextWrapping = TextWrapping.Wrap;
        var pill = new Border
        {
            Child = text, Padding = new Thickness(10, 6, 10, 6), CornerRadius = new CornerRadius(14),
            Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"), VerticalAlignment = VerticalAlignment.Bottom,
        };
        return pill.Bind(editor, [nameof(RigEditorModel.Selection), nameof(RigEditorModel.Group), nameof(RigEditorModel.Version)], _ =>
        {
            var n = editor.SelectedFixtures.Count;
            text.Text = editor.Doc.WaitingCount > 0 && editor.Selection is null
                ? $"{editor.Doc.WaitingCount} fixtures wait in front of the stage: drag them onto a truss, drag a group from the list, or Auto-Mount"
                : editor.Selection is null ? "Click to select · Shift-click for more · Ctrl+A all fixtures · drag empty space to turn the view"
                    + (_viewport!.Stage.CanFly ? " · WASD walks · F flies" : "")
                : n > 1 ? $"{n} selected: drag one and the rest come along · Delete unmounts them · R rotates"
                : "Drag to move · R rotates 15° (Shift+R 90°) · arrows nudge · Delete unmounts or deletes · Alt-drag places freely";
        });
    }

    FrameworkElement CameraButtons()
    {
        var stage = _viewport!.Stage;
        var hint = new Border
        {
            Child = UI.Text("WASD move · Q/E down/up · drag to look · Shift faster · Esc lands", Font.Caption).Secondary(),
            Padding = new Thickness(12, 8, 12, 8), CornerRadius = new CornerRadius(14),
            Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"), VerticalAlignment = VerticalAlignment.Bottom,
        };
        hint.Bind(stage, nameof(IEditorStage.Fly), h => h.Visible(stage.Fly));
        var row = UI.HStack(6, hint);
        var buttons = new List<ToggleButton>();
        foreach (var (preset, symbol) in EditorViewport.CameraPresets)
        {
            var b = new ToggleButton
            {
                Content = UI.Icon(EditorUI.Symbol(symbol), 14), IsChecked = _viewport!.Preset == preset, Padding = new Thickness(8, 6, 8, 6),
                Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"),
            }.Tooltip(preset);
            b.Click += (_, _) =>
            {
                _viewport!.Preset = preset;
                foreach (var o in buttons) o.IsChecked = ReferenceEquals(o, b);
            };
            buttons.Add(b);
            row.Children.Add(b);
        }
        if (stage.CanFly)
        {
            var fly = new ToggleButton
            {
                Content = UI.Icon("figure.walk.motion", 14), Padding = new Thickness(8, 6, 8, 6),
                Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"),
            }.Tooltip("Fly through the room (F): WASD or arrows move, Q/E down/up, drag to look around, scroll or pinch to move, Shift faster. Without flying: WASD still walks, +/− zoom.");
            fly.Click += (_, _) => stage.Fly = !stage.Fly;
            row.Children.Add(fly.Bind(stage, nameof(IEditorStage.Fly), f => f.IsChecked = stage.Fly));
        }
        row.VerticalAlignment = VerticalAlignment.Bottom;
        return row;
    }
}

/// The rig's name: make a new one, duplicate, rename, delete (switching rigs is the list on the Rigs page).
public sealed class RigMenu(AppModel model, RigEditorModel editor)
{
    FrameworkElement? _button;

    public FrameworkElement Build()
    {
        var label = UI.Label("building.2", editor.IsDirty ? $"{model.EditingRig} •" : model.EditingRig);
        var b = UI.MenuButton(label, () => UI.Menu(
            UI.Item("New Rig…", () => model.ShowNewRig = true, "plus"),
            UI.Item("Duplicate", () =>
            {
                var r = model.EditingRig;
                Run(() => model.Api.CreateRig(Unique(r + "-copy"), copyOf: r));
            }, "plus.square.on.square"),
            UI.Item("Import from Documents…", () => model.ShowImport = true, "doc.badge.arrow.up"),
            UI.Item("Rename…", Rename, "pencil"),
            UI.Item("Show in File Explorer", () =>
            {
                if (model.Workspace?.RigURL(model.EditingRig) is { } path)
                    try { Process.Start(new ProcessStartInfo("explorer.exe") { ArgumentList = { $"/select,{path}" } })?.Dispose(); }
                    catch (System.ComponentModel.Win32Exception) { }
            }, "folder"),
            UI.Separator(),
            UI.Item("Delete…", ConfirmDelete, "trash").Disabled(model.Rigs.Count <= 1)));
        b.IsEnabled = !model.EngineRunning;
        _button = b.Tooltip("The rig: a new one, duplicate, rename, delete");
        return _button;
    }

    string Unique(string prefix)
    {
        var n = prefix;
        for (var i = 2; model.Rigs.Any(r => r.Name == n); i++) n = $"{prefix}{i}";
        return n;
    }

    async void Rename()
    {
        if (_button?.XamlRoot is not { } root) return;
        var field = new TextBox { Text = model.EditingRig, PlaceholderText = "Name" };
        var d = new ContentDialog
        {
            XamlRoot = root, Title = "Rename the Rig", Content = field, PrimaryButtonText = "Rename", CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await d.ShowAsync() != ContentDialogResult.Primary) return;
        var (old, to) = (model.EditingRig, field.Text);
        Run(async () =>
        {
            await model.Api.RenameRig(old, to);
            model.EditingRig = to.ToLowerInvariant();
        });
    }

    async void ConfirmDelete()
    {
        var r = model.EditingRig;
        if (await EditorUI.Confirm(_button?.XamlRoot, $"Delete the rig “{r}”?",
                "Its trusses, zones and where every set hung on it are removed. Your sets (the fixtures) stay.", "Delete"))
            Run(() => model.Api.DeleteRig(r));
    }

    async void Run(Func<Task> op)
    {
        if (!await model.EnsureSetupService())
        {
            await EditorUI.Alert(_button?.XamlRoot, "Couldn’t Change the Rigs", "The engine's setup service did not start.");
            return;
        }
        try { await op(); }
        catch (Exception e) when (e is not OutOfMemoryException) { await EditorUI.Alert(_button?.XamlRoot, "Couldn’t Change the Rigs", e.Message); }
        model.ReloadSets();
    }
}
