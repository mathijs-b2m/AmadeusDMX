// Rigs: the venues. A list of your rigs; the one picked is edited in 3D (trusses, towers, stage, zones). Sets are
// placed on a rig here, and only here: a set on a rig is a combination the show can run, and its fixtures are
// arranged on the rig in the same editor. With no set picked you edit the rig alone.
// The port of mac/Sources/AmadeusDMX/Rig/RigView.swift.
namespace AmadeusDMX;

public sealed class RigView(AppModel model)
{
    public FrameworkElement Build()
    {
        var list = new RigList(model).Build();
        var detail = new Grid { MinWidth = 600 };
        detail.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        detail.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var bar = UI.Live(model, () => model.EditingRig.Length == 0 ? null : UI.VStack(0, new PlacementBar(model).Build(), UI.Divider()),
                          nameof(AppModel.EditingRig));
        // the editor for the rig (and the set on it) being edited: a new one when either changes (Swift's .id)
        var editor = UI.Live(model, Editor, nameof(AppModel.EditingRig), nameof(AppModel.EditingRigSet), nameof(AppModel.Workspace));
        Grid.SetRow(bar, 0);
        Grid.SetRow(editor, 1);
        detail.Children.Add(bar);
        detail.Children.Add(editor);

        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(230), MinWidth = 180, MaxWidth = 300 });
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        Grid.SetColumn(list, 0);
        Grid.SetColumn(detail, 1);
        root.Children.Add(list);
        root.Children.Add(detail);
        return root;
    }

    UIElement Editor()
    {
        if (model.Workspace is { } ws && model.EditingRig.Length > 0
            && RigEditorModel.Create(ws, model.EditingRig, model.EditingRigSet) is { } editor)
            return new RigEditorView(model, editor).Build();
        return UI.Unavailable("square.split.bottomrightquarter", "No Rig Yet", "A rig is the venue: the stage and the trusses your fixtures hang on.",
                              UI.Button("New Rig…", () => model.ShowNewRig = true).Prominent());
    }
}

/// Your rigs.
sealed class RigList(AppModel model)
{
    bool _quiet;

    public FrameworkElement Build()
    {
        var list = new ListView { SelectionMode = ListViewSelectionMode.Single };
        list.SelectionChanged += (_, _) =>
        {
            if (_quiet || list.SelectedItem is not ListViewItem { Tag: (string name, string _) }) return;
            model.EditingRig = name;
            model.EditingRigSet = "";
        };
        list.Bind(model, [nameof(AppModel.Rigs), nameof(AppModel.Sets), nameof(AppModel.EditingRig)], l =>
        {
            _quiet = true;
            try
            {
                var rows = model.Rigs.Select(r => (r.Name, Line: Line(r.Name))).ToList();
                var shown = l.Items.OfType<ListViewItem>().Select(i => i.Tag is (string n, string s) ? (n, s) : ("", "")).ToList();
                if (!rows.SequenceEqual(shown))
                {
                    l.Items.Clear();
                    foreach (var (name, line) in rows)
                    {
                        var text = UI.VStack(2, UI.Text(name, Font.Headline), UI.Text(line, Font.Caption).Secondary().Wrap(2));
                        text.Padding = new Thickness(0, 4, 0, 4);
                        l.Items.Add(new ListViewItem { Content = text, Tag = (name, line) });
                    }
                }
                l.SelectedItem = l.Items.OfType<ListViewItem>().FirstOrDefault(i => i.Tag is (string n, string _) && n == model.EditingRig);
            }
            finally { _quiet = false; }
        });

        var header = UI.HStack(8, UI.Text("Rigs", Font.Subheadline).Secondary().Bold(), UI.Spacer(),
                               UI.IconButton("plus", "Make a new rig (Ctrl+Alt+N)", () => model.ShowNewRig = true)).Padding(14, 10);
        // a real button, full width under the list: the first place you look for a new rig
        var add = UI.Button("New Rig…", () => model.ShowNewRig = true, "plus").Prominent().Tooltip("Make a new rig: start from an empty room or a template (Ctrl+Alt+N)");
        add.HorizontalAlignment = HorizontalAlignment.Stretch;
        add.Padding = new Thickness(10);
        add.Margin = new Thickness(10);

        var root = new Grid
        {
            Background = Theme.Brush("LayerFillColorDefaultBrush"), BorderBrush = Theme.Brush("DividerStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(0, 0, 1, 0),
        };
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Grid.SetRow(header, 0);
        Grid.SetRow(list, 1);
        Grid.SetRow(add, 2);
        root.Children.Add(header);
        root.Children.Add(list);
        root.Children.Add(add);
        return root;
    }

    string Line(string rig)
    {
        if (model.Rigs.FirstOrDefault(r => r.Name == rig) is not { } r) return "";
        var on = model.SetsOn(r.Name);
        return r.Summary + (on.Count == 0 ? "" : " · " + string.Join(", ", on));
    }
}

/// The sets on this rig: which one's placement you edit, putting another set on it, taking one off.
sealed class PlacementBar(AppModel model)
{
    bool _busy;
    ContentControl? _host;

    public FrameworkElement Build()
    {
        _host = UI.Live(model, Bar, nameof(AppModel.EditingRig), nameof(AppModel.EditingRigSet), nameof(AppModel.Sets), nameof(AppModel.Rigs),
                        nameof(AppModel.EngineRunning));
        return _host;
    }

    void Rebuild()
    {
        if (_host is not null) _host.Content = Bar();
    }

    UIElement Bar()
    {
        var rig = model.EditingRig;
        var on = model.SetsOn(rig);
        var off = model.Sets.Select(s => s.Name).Where(s => !on.Contains(s)).ToList();
        List<string> choices = ["", .. on];
        var picker = UI.Picker(choices, model.EditingRigSet, s => s.Length == 0 ? "The rig alone" : s, s => model.EditingRigSet = s)
            .Tooltip("Edit the rig alone, or where a set's fixtures hang on it");
        var place = UI.MenuButton(UI.Label("plus", "Place a Set"), () => UI.Menu([.. off.Select(s => UI.Item(s, () => Place(s)))]))
            .Tooltip("Put one of your sets on this rig: a combination the show can run");
        place.IsEnabled = !(off.Count == 0 || model.EngineRunning || _busy);
        var row = UI.HStack(10, UI.Text("On this rig").Secondary(), picker, place);
        if (model.EditingRigSet.Length > 0)
            row.Children.Add(UI.Button("Take Off…", TakeOff, "minus.circle").Disabled(model.EngineRunning || _busy)
                .Tooltip("Take this set off the rig: where its fixtures hang here is forgotten"));
        if (_busy) row.Children.Add(UI.Spinner());
        row.Children.Add(UI.Spacer());
        if (on.Count > 0) row.Children.Add(UI.Text($"{on.Count} combination{(on.Count == 1 ? "" : "s")} for the show", Font.Caption).Secondary());
        return row.Padding(14, 8);
    }

    async void Place(string set)
    {
        if (_host?.XamlRoot is not { } xr) return;
        var rig = model.EditingRig;
        var d = new ContentDialog
        {
            XamlRoot = xr, Title = $"Place “{set}” on {rig}",
            Content = UI.Text("Auto-mount hangs them the way a lighting tech would start; by hand they wait in front of the stage until you drag them onto the trusses.").Wrap(),
            PrimaryButtonText = "Auto-Mount the Fixtures", SecondaryButtonText = "Place Them by Hand", CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        var r = await d.ShowAsync();
        if (r == ContentDialogResult.None) return;
        Run(() => model.PlaceSet(set, rig, r == ContentDialogResult.Primary));
    }

    async void TakeOff()
    {
        var (s, rig) = (model.EditingRigSet, model.EditingRig);
        if (await EditorUI.Confirm(_host?.XamlRoot, $"Take “{s}” off {rig}?",
                "Where its fixtures hang on this rig is forgotten, and the show can no longer run this combination. The set and the rig stay.", "Take Off"))
            Run(() => model.UnplaceSet(s, rig));
    }

    async void Run(Func<Task> op)
    {
        _busy = true;
        Rebuild();
        try { await op(); }
        catch (Exception e) when (e is not OutOfMemoryException) { await EditorUI.Alert(_host?.XamlRoot, "Couldn’t Change the Rig", e.Message); }
        _busy = false;
        Rebuild();
    }
}
