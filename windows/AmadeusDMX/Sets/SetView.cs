// Sets: your gear, nothing else. A list of your sets; the one picked shows every fixture, grouped by model, with
// its DMX patch, and lets you add and remove fixtures. Rigs (and where a set hangs on one) are on the Rigs page
// (mac/Sources/AmadeusDMX/Sets/SetView.swift).
using Microsoft.UI.Xaml.Input;

namespace AmadeusDMX;

public sealed class SetView(AppModel model, MainWindow window)
{
    RigDocument? _doc;
    Dictionary<string, JSONValue> _layout = [];   // the set as in its file (what the inspector edits)
    readonly Dictionary<string, FixtureDefinition?> _names = [];
    HashSet<string> _selection = [];
    readonly HashSet<string> _lit = [];          // fixtures the light test keeps on
    readonly Dictionary<string, CancellationTokenSource> _testOff = [];  // their switch-off when the engine's time runs out
    string? _message;
    string _loaded = "";
    readonly PatchInspector.Typing _typing = new();   // what is typed in the inspector, kept while it is made again
    PatchInspector? _patchInspector;

    readonly ListView _sets = new() { SelectionMode = ListViewSelectionMode.Single };
    readonly ListView _fixtures = new() { SelectionMode = ListViewSelectionMode.Extended };
    readonly ContentControl _header = Host(), _middle = Host(), _inspector = Host(), _flash = Host();
    FrameworkElement? _root;
    bool _quiet;

    static ContentControl Host() => new()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
    };

    XamlRoot? Root => _root?.XamlRoot;

    public FrameworkElement Build()
    {
        // the sets
        _sets.SelectionChanged += (_, _) =>
        {
            if (_quiet) return;
            if (_sets.SelectedItem is ListViewItem { Tag: string name }) { if (name != model.EditingSet) model.EditingSet = name; }
            else ListSets();  // a section header isn't a set
        };
        var newSet = UI.Button("New Set…", window.OpenWizard, "plus").Prominent();
        newSet.HorizontalAlignment = HorizontalAlignment.Stretch;
        var setsPane = new Grid { MinWidth = 180, Width = 220 };
        setsPane.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        setsPane.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        setsPane.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var setsTitle = UI.Text("Sets", Font.Subheadline).Secondary().Bold().Margin(16, 12, 0, 4);
        setsTitle.Visibility = Visibility.Collapsed;  // the list has its own sections
        Grid.SetRow(setsTitle, 0);
        Grid.SetRow(_sets, 1);
        Grid.SetRow(newSet.Margin(6, 6, 6, 10), 2);
        setsPane.Children.Add(setsTitle);
        setsPane.Children.Add(_sets);
        setsPane.Children.Add(newSet);

        // the fixtures
        _fixtures.SelectionChanged += (_, _) =>
        {
            if (_quiet) return;
            // group headers aren't fixtures
            foreach (var h in _fixtures.SelectedItems.OfType<ListViewItem>().Where(i => i.Tag is not string).ToList()) _fixtures.SelectedItems.Remove(h);
            _selection = _fixtures.SelectedItems.OfType<ListViewItem>().Select(i => i.Tag).OfType<string>().ToHashSet();
            _patchInspector?.Commit();  // another fixture picked: keep what was typed
            ShowInspector();
            Header();
        };
        var middle = new Grid { MinWidth = 480 };
        middle.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        middle.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        middle.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var line = UI.Divider();
        Grid.SetRow(_header, 0);
        Grid.SetRow(line, 1);
        Grid.SetRow(_middle, 2);
        middle.Children.Add(_header);
        middle.Children.Add(line);
        middle.Children.Add(_middle);

        // the inspector
        var right = new Grid { MinWidth = 320, Width = 380 };
        right.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        right.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Grid.SetRow(_inspector, 0);
        Grid.SetRow(_flash, 1);
        right.Children.Add(_inspector);
        right.Children.Add(_flash);

        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var d1 = UI.Divider(vertical: true);
        var d2 = UI.Divider(vertical: true);
        Grid.SetColumn(setsPane, 0);
        Grid.SetColumn(d1, 1);
        Grid.SetColumn(middle, 2);
        Grid.SetColumn(d2, 3);
        Grid.SetColumn(right, 4);
        foreach (var e in new UIElement[] { setsPane, d1, middle, d2, right }) grid.Children.Add(e);
        _root = grid;

        // what it follows: the sets as read (every save reads them again), the set edited, the show
        grid.Bind(model, [nameof(AppModel.ConfigVersion), nameof(AppModel.Sets)], _ => { ListSets(); Load(); });
        grid.Bind(model, nameof(AppModel.EditingSet), _ =>
        {
            if (_loaded == model.EditingSet) return;
            SwitchOffTests(_loaded);
            _typing.Forget();
            _selection = [];
            ListSets();
            Load();
        });
        grid.Bind(model, nameof(AppModel.EngineRunning), _ =>
        {
            if (model.EngineRunning) SwitchOffTests();
            ListSets();
            Header();
            ListFixtures();
        });
        grid.Unloaded += (_, _) => SwitchOffTests();
        return grid;
    }

    // MARK: the lists

    void ListSets()
    {
        _quiet = true;
        try
        {
            _sets.Items.Clear();
            void Title(UIElement content) =>
                _sets.Items.Add(new ListViewItem
                {
                    Content = content, IsTabStop = false, Padding = new Thickness(12, 10, 12, 2), HorizontalContentAlignment = HorizontalAlignment.Stretch,
                });
            void Row(SetSummary s) =>
                _sets.Items.Add(new ListViewItem
                {
                    Tag = s.Name,
                    Content = UI.VStack(2,
                        UI.Text(s.Name, Font.Headline),
                        UI.Text($"{s.FixtureCount} fixtures · {(s.IsVirtual ? "visualiser only" : s.OutputText)}", Font.Caption).Secondary().Lines(1)
                    ).Padding(0, 4),
                });
            // as on the Rigs page: a + by the title, the big button under the list
            Title(UI.HStack(8, UI.Text("Your Sets", Font.Subheadline).Secondary().Bold(), UI.Spacer(),
                            UI.IconButton("plus", "Make a new set with the set-up assistant", window.OpenWizard).Disabled(model.EngineRunning)));
            foreach (var s in model.Sets.Where(s => !s.IsExample)) Row(s);
            if (!model.Sets.Any(s => !s.IsExample))
                Title(UI.Text("None yet. Your fixtures go in a set of your own: make one with New Set…", Font.Callout).Secondary().Wrap());
            if (model.Sets.Any(s => s.IsExample))
            {
                Title(UI.VStack(1, UI.Text("Examples", Font.Subheadline).Secondary().Bold(),
                                UI.Text("To look around in and try the show.", Font.Caption).Secondary().Wrap()));
                foreach (var s in model.Sets.Where(s => s.IsExample)) Row(s);
            }
            _sets.SelectedItem = _sets.Items.OfType<ListViewItem>().FirstOrDefault(i => i.Tag as string == model.EditingSet);
        }
        finally { _quiet = false; }
    }

    public sealed record Group(string Key, FixtureDefinition? Definition, IReadOnlyList<PlacedFixture> Fixtures);

    IReadOnlyList<Group> Groups(RigDocument doc)
    {
        var order = new List<string>();
        var by = new Dictionary<string, List<PlacedFixture>>();
        foreach (var f in doc.Fixtures.OrderBy(f => f.Universe).ThenBy(f => f.Address ?? Patch.UniverseSize + 1))
        {
            if (!by.TryGetValue(f.Key, out var l)) { order.Add(f.Key); by[f.Key] = l = []; }
            l.Add(f);
        }
        return order.Select(k => new Group(k, _names.GetValueOrDefault(k), by[k])).ToList();
    }

    void ListFixtures()
    {
        if (_doc is not { Fixtures.Count: > 0 } doc)
        {
            _middle.Content = UI.Unavailable("light.overhead.right", "No Fixtures Yet",
                "Add the fixtures you own: search by brand or model across our library, QLC+ and the Open Fixture Library.",
                UI.Button("Add Fixtures…", ShowAdd).Prominent());
            return;
        }
        _quiet = true;
        try
        {
            _fixtures.Items.Clear();
            foreach (var g in Groups(doc))
            {
                _fixtures.Items.Add(new ListViewItem
                {
                    Content = GroupHeader(g), IsTabStop = false, Padding = new Thickness(12, 10, 12, 4),
                    HorizontalContentAlignment = HorizontalAlignment.Stretch,
                });
                foreach (var f in g.Fixtures)
                {
                    var item = new ListViewItem
                    {
                        Tag = f.Id,
                        Content = FixtureRow(f, _lit.Contains(f.Id), f.Address is null ? "No start address yet: give it one first" : TestRefusal(g.Definition)),
                        HorizontalContentAlignment = HorizontalAlignment.Stretch,
                    };
                    item.ContextFlyout = ContextMenu(f.Id);
                    _fixtures.Items.Add(item);
                    if (_selection.Contains(f.Id)) _fixtures.SelectedItems.Add(item);
                }
            }
        }
        finally { _quiet = false; }
        _middle.Content = _fixtures;
    }

    /// Right-click: the selection when the row is in it, else that row.
    MenuFlyout ContextMenu(string id)
    {
        var menu = new MenuFlyout();
        menu.Opening += (_, _) =>
        {
            var ids = _selection.Contains(id) ? _selection.ToHashSet() : [id];
            menu.Items.Clear();
            var identify = UI.Item("Identify on the Lights", () => Identify(ids), "lightbulb.max");
            identify.IsEnabled = !((EditingSummary?.IsVirtual ?? true) || model.EngineRunning);
            var map = UI.Item("Map DMX Channels…", () => MapChannels(_doc?.Fixtures.FirstOrDefault(f => ids.Contains(f.Id))), "slider.vertical.3");
            map.IsEnabled = ids.Count > 0 && !model.EngineRunning;
            var remove = UI.Item("Remove from the Set", () => Remove(ids), "trash");
            remove.IsEnabled = !model.EngineRunning;
            menu.Items.Add(identify);
            menu.Items.Add(map);
            menu.Items.Add(UI.Separator());
            menu.Items.Add(remove);
        };
        return menu;
    }

    UIElement GroupHeader(Group g)
    {
        var d = g.Definition;
        var f = g.Fixtures.FirstOrDefault();
        var tried = g.Fixtures.FirstOrDefault(x => x.Address is not null) ?? f;  // the mapper tries its values on a patched one
        var row = UI.HStack(8,
            UI.Icon(FixtureIcon.Symbol(d?.Kind)).Foreground(Tint.Accent),
            UI.Text($"{g.Fixtures.Count}× {d?.Name ?? g.Key}", Font.Headline),
            f is null ? null : UI.Text($"{f.Mode} · {d?.ChannelCount(f.Mode) ?? 0} ch", Font.Caption).Secondary(),
            UI.Spacer());
        if (d is not null && f is not null && d.Inert.Length == 0 && d.Kind != "smoke")
        {
            var dark = !d.Plays(f.Mode);
            if (dark)
                row.Children.Add(UI.Label("exclamationmark.triangle.fill", "Plays nothing", Font.Caption).Foreground(Tint.Orange)
                    .Tooltip("The show finds no dimmer or colour channel in this mode: map its channels by hand"));
            var b = UI.Button(dark ? "Map Channels…" : "Channels…", () => MapChannels(tried), "slider.vertical.3").Font(Font.Caption).Padding(8, 3)
                .Disabled(model.EngineRunning)
                .Tooltip("The DMX mapper: what each channel does, by hand, with the values tried on the real fixture");
            if (dark) b.Foreground(Tint.Orange);
            row.Children.Add(b);
        }
        return row;
    }

    UIElement FixtureRow(PlacedFixture f, bool lit, string? test)
    {
        var button = UI.Button(lit ? "On" : "Test", () => ToggleTest(f.Id), lit ? "lightbulb.fill" : "lightbulb").Font(Font.Caption).Padding(8, 3)
            .Disabled(test is not null && !lit)
            .Tooltip(test ?? (lit ? "Switch it off again"
                : "Light it on the real rig until you switch it off (a minute at most): is it patched and connected?"));
        if (lit) button.Foreground(Tint.Yellow);
        return UI.HStack(8,
            UI.Text(f.Id, Font.Mono).Frame(width: 110),
            (f.Address is null ? UI.Text("no address").Foreground(Tint.Orange) : UI.Text(f.PatchText).Secondary()).Frame(width: 80)
                .Tooltip(f.Address is null ? "No start address yet: select it and give it one (the visualiser only until then)"
                    : "Universe.address: set this start address on the fixture's display"),
            UI.Text(f.Mode, Font.Callout).Secondary(),
            UI.Spacer(),
            button);
    }

    // MARK: header and inspector

    void Header() => _header.Content = new SetHeader(model, window, _doc, ShowAdd, () => Identify(_selection), _selection.Count > 0,
                                                     (t, m) => _ = Dialogs.Alert(Root, t, m)).Build();

    void ShowInspector()
    {
        if (_selection.Count == 0)
        {
            _patchInspector = null;
            _inspector.Content = UI.Unavailable("slider.horizontal.3", "Select a Fixture",
                "Its DMX mode, universe and address, and its name, are edited here. Select several to patch them in a row.");
            return;
        }
        _patchInspector = new PatchInspector(_selection, SetLayout.Fixtures(_layout), Definition, Change, RenameFixture, _typing);
        _inspector.Content = _patchInspector.Build();
    }

    void ShowFlash()
    {
        _flash.Content = _message is { } m
            ? new Border
            {
                Child = UI.Text(m, Font.Callout).Wrap(), Padding = new Thickness(14, 8, 14, 8), Margin = new Thickness(12),
                CornerRadius = new CornerRadius(999), Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"),
                BorderBrush = Theme.Brush("CardStrokeColorDefaultBrush"), BorderThickness = new Thickness(1),
                HorizontalAlignment = HorizontalAlignment.Center,
            }
            : null;
    }

    FixtureDefinition? Definition(string key)
    {
        if (!_names.TryGetValue(key, out var d)) _names[key] = d = model.Workspace?.Definition(key);
        return d;
    }

    SetSummary? EditingSummary => model.Sets.FirstOrDefault(s => s.Name == model.EditingSet);

    void Load()
    {
        if (model.Workspace is not { } ws) return;
        _loaded = model.EditingSet;
        _doc = ws.Document("", model.EditingSet);  // the set alone: no rig
        _layout = SetLayout.Parse(ws.Composed("", model.EditingSet)) ?? [];
        foreach (var key in _doc?.Fixtures.Select(f => f.Key).Distinct() ?? []) Definition(key);
        _selection = _selection.Where(id => _doc?.Fixtures.Any(f => f.Id == id) == true).ToHashSet();
        Header();
        ListFixtures();
        ShowInspector();
    }

    // MARK: changes, saved at once

    /// A change to the set's fixtures, saved at once (the set alone).
    async void Change(string name, Action<List<Dictionary<string, JSONValue>>> body)
    {
        var fixtures = SetLayout.Fixtures(_layout);
        body(fixtures);
        var l = SetLayout.WithFixtures(_layout, fixtures);
        _layout = l;
        var set = model.EditingSet;
        try
        {
            if (!await model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            await model.Api.SaveSet(l, set);
            model.ReloadSets();  // and so Load()
        }
        catch (Exception e) when (IsApiError(e))
        {
            await Dialogs.Alert(Root, "Couldn’t Change the Set", e.Message);
            Load();
        }
    }

    async void RenameFixture(string old, string to)
    {
        var set = model.EditingSet;
        try
        {
            if (!await model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            await model.Api.RenameFixture(old, to, set);
            _selection = [to];
            model.ReloadSets();
            Flash($"Renamed {old} → {to}");
        }
        catch (Exception e) when (IsApiError(e)) { await Dialogs.Alert(Root, "Couldn’t Change the Set", e.Message); }
    }

    async void Flash(string text, double seconds = 3)
    {
        _message = text;
        ShowFlash();
        await Task.Delay(TimeSpan.FromSeconds(seconds));
        if (_message == text) { _message = null; ShowFlash(); }
    }

    async void Identify(IReadOnlySet<string> ids)
    {
        var (rig, set) = (model.SelectedRig, model.EditingSet);  // (identify only needs the set's patch and output)
        if (!await model.EnsureSetupService()) { await Dialogs.Alert(Root, "Couldn’t Change the Set", "The engine's setup service did not start."); return; }
        foreach (var id in ids)
        {
            try { await model.Api.Identify(id, rig, set); }
            catch (Exception e) when (IsApiError(e)) { }
        }
        Flash($"Lit {(ids.Count == 1 ? ids.First() : $"{ids.Count} fixtures")} for 2 s");
    }

    void ShowAdd() => AddToSetSheet.Present(model, Root, () => model.ReloadSets());

    /// The DMX mapper for this fixture's model and mode (tried on this fixture).
    void MapChannels(PlacedFixture? f)
    {
        if (f is null) return;
        SwitchOffTests();
        var target = new MapTarget(f.Key, f.Mode, f.Id, f.Address, f.Universe);
        MapperSheet.Present(model, Root, target, target.Address is null ? $"Give {target.Fixture} a start address to try values on it" : TryRefusal, () =>
        {
            _names[target.Key] = model.Workspace?.Definition(target.Key);
            model.ReloadSets();
            Flash($"Mapped {_names[target.Key]?.Name ?? target.Key} ({target.Mode}): every one in your sets plays by it");
        });
    }

    /// Why nothing can be lit on the real rig now (nil: it can).
    string? TryRefusal
    {
        get
        {
            if (EditingSummary?.IsVirtual ?? true) return "This set only feeds the visualiser: give it a DMX output to test the real lights";
            if (model.EngineRunning) return "Stop the show to test the lights";
            return null;
        }
    }

    /// Why the light test can't light this model here (nil: it can).
    string? TestRefusal(FixtureDefinition? d)
    {
        if (TryRefusal is { } r) return r;
        if (d is { Inert.Length: > 0 }) return $"Not tested: {d.Inert}";
        if (d?.Kind == "smoke") return "Smoke machines fire only in the show or the hardware test";
        return null;
    }

    /// The light test: the fixture on (the rest of the set dark) until switched off again, to see that it is
    /// patched and connected. The engine switches it off by itself after a minute.
    async void ToggleTest(string id)
    {
        var on = !_lit.Contains(id);
        var (rig, set) = (model.SelectedRig, model.EditingSet);
        if (on) _lit.Add(id); else _lit.Remove(id);
        if (_testOff.Remove(id, out var old)) old.Cancel();
        ListFixtures();
        try
        {
            if (!await model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var r = await model.Api.TestLight(id, on, rig: rig, set: set);
            if (on)
            {
                Flash($"{id} on: {r.Summary}", 8);
                var cts = new CancellationTokenSource();
                _testOff[id] = cts;
                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(r.Seconds), cts.Token);
                    _lit.Remove(id);
                    _testOff.Remove(id);
                    ListFixtures();
                }
                catch (TaskCanceledException) { }
            }
        }
        catch (Exception e) when (IsApiError(e))
        {
            _lit.Remove(id);
            ListFixtures();
            await Dialogs.Alert(Root, "Couldn’t Change the Set", e.Message);
        }
    }

    void SwitchOffTests(string? set = null)
    {
        if (_lit.Count == 0) return;
        var ids = _lit.ToList();
        var (rig, s) = (model.SelectedRig, set ?? model.EditingSet);
        _lit.Clear();
        foreach (var c in _testOff.Values) c.Cancel();
        _testOff.Clear();
        _ = Task.Run(async () =>
        {
            foreach (var id in ids)
            {
                try { await model.Api.TestLight(id, false, rig: rig, set: s); }
                catch (Exception e) when (IsApiError(e)) { }
            }
        });
        if (_root?.IsLoaded == true) ListFixtures();
    }

    async void Remove(IReadOnlySet<string> ids)
    {
        var set = model.EditingSet;
        try
        {
            if (!await model.EnsureSetupService() || model.Workspace is not { } ws || SetLayout.Parse(ws.Composed("", set)) is not { } layout)
                throw SetupAPIException.NotRunningError();
            var kept = SetLayout.Fixtures(layout).Where(f => !ids.Contains(Patch.Id(f)));
            await model.Api.SaveSet(SetLayout.WithFixtures(layout, kept), set);
            _selection = [];
            model.ReloadSets();
            Flash($"Removed {(ids.Count == 1 ? ids.First() : $"{ids.Count} fixtures")}");
        }
        catch (Exception e) when (IsApiError(e)) { await Dialogs.Alert(Root, "Couldn’t Change the Set", e.Message); }
    }

    internal static bool IsApiError(Exception e) =>
        e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException or IOException;
}

/// The set's name (a menu for the rare second set), what it holds, and where the DMX goes.
public sealed class SetHeader(AppModel model, MainWindow window, RigDocument? doc, Action showAdd, Action identify, bool hasSelection,
                              Action<string, string> error)
{
    public FrameworkElement Build()
    {
        var set = model.Sets.FirstOrDefault(s => s.Name == model.EditingSet);
        var example = set?.IsExample ?? false;
        var name = UI.MenuButton(UI.Text(model.EditingSet, Font.Title2), () =>
        {
            var delete = UI.Item("Delete…", Delete, "trash");
            delete.IsEnabled = model.Sets.Count > 1;
            return UI.Menu(
                UI.Item("New Set…", window.OpenWizard, "plus"),
                UI.Item("Duplicate", () => Run(() => model.Api.CreateSet(Unique(model.EditingSet + "-copy"), copyOf: model.EditingSet)),
                        "plus.square.on.square"),
                UI.Item("Rename…", Rename, "pencil"),
                UI.Separator(),
                UI.Item("Show in File Explorer", () => { if (model.Workspace is { } ws) Dialogs.ShowInExplorer(ws.SetURL(model.EditingSet)); }, "folder"),
                delete);
        }).Disabled(model.EngineRunning);
        name.Background = Tint.Brush(Tint.Black, 0);
        name.BorderThickness = new Thickness(0);
        var identifyButton = UI.Button("Identify", identify, "lightbulb.max")
            .Disabled(!hasSelection || (set?.IsVirtual ?? true) || model.EngineRunning)
            .Tooltip("Light the selected fixtures on the real rig for 2 seconds");
        var add = example
            ? UI.Button("Add Fixtures…", AddToExample, "plus").Disabled(model.EngineRunning)
            : UI.Button("Add Fixtures…", showAdd, "plus").Prominent().Disabled(model.EngineRunning);
        var output = new Button
        {
            Content = Metric(set?.IsVirtual ?? true ? "Visualiser" : set?.OutputText ?? "–", "DMX output ›"),
            Background = Tint.Brush(Tint.Black, 0), BorderThickness = new Thickness(0), Padding = new Thickness(0),
        }.Tooltip("Where the set's universes go: the DMX Output page (Ctrl+Shift+D)");
        output.Click += (_, _) => window.OpenDMX();
        var fixtures = doc?.Fixtures ?? [];
        return UI.VStack(12,
            UI.HStack(8, name, UI.Text(example ? "example" : "your fixtures").Secondary(), UI.Spacer(), identifyButton, add),
            UI.HStack(18,
                Metric($"{fixtures.Count}", "fixtures"),
                Metric($"{fixtures.Select(f => f.Key).Distinct().Count()}", "models"),
                Metric($"{fixtures.Select(f => f.Universe).Distinct().Count()}", "universes"),
                fixtures.Count(f => f.Address is null) is > 0 and var unpatched
                    ? Metric($"{unpatched}", "without address", Tint.Orange)
                        .Tooltip("Fixtures without a start address play in the visualiser only: select one and give it the address set on the fixture")
                    : null,
                output,
                UI.Spacer()),
            example ? ExampleNotice() : null
        ).Padding(16);
    }

    /// Over an example set: it is not yours, and where yours go.
    FrameworkElement ExampleNotice() => new Border
    {
        Background = Tint.Brush(Tint.Accent, 0.12), CornerRadius = new CornerRadius(8), Padding = new Thickness(12),
        Child = UI.HStack(12,
            UI.Icon("info.circle", 22).Foreground(Tint.Accent),
            UI.VStack(2,
                UI.Text("This is an example set", Font.Headline),
                UI.Text("Look around and try the show with it. For the fixtures you own, make a set of your own.", Font.Callout).Secondary().Wrap()
            ).Grow(),
            UI.Button("New Set…", window.OpenWizard, "plus").Prominent().Disabled(model.EngineRunning)),
    };

    /// Adding to an example asks first: most who do meant to start their own set.
    async void AddToExample()
    {
        if (window.Root is null) return;
        var d = new ContentDialog
        {
            XamlRoot = window.Root, Title = $"Add fixtures to the example “{model.EditingSet}”?",
            Content = UI.Text("The examples are there to look around in. Your own fixtures belong in a set of your own.").Wrap(),
            PrimaryButtonText = "New Set…", SecondaryButtonText = "Add to the Example", CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        switch (await Dialogs.Show(d))
        {
            case ContentDialogResult.Primary: window.OpenWizard(); break;
            case ContentDialogResult.Secondary: showAdd(); break;
        }
    }

    static FrameworkElement Metric(string value, string label, Windows.UI.Color? color = null) =>
        color is { } c
            ? UI.VStack(1, UI.Text(value, Font.Title3).Bold().Foreground(c), UI.Text(label, Font.Caption).Foreground(c))
            : UI.VStack(1, UI.Text(value, Font.Title3).Bold(), UI.Text(label, Font.Caption).Secondary());

    string Unique(string baseName)
    {
        var n = baseName;
        for (var i = 2; model.Sets.Any(s => s.Name == n); i++) n = $"{baseName}{i}";
        return n;
    }

    async void Rename()
    {
        var old = model.EditingSet;
        if (await Dialogs.AskText(window.Root, "Rename the Set", "Name", old, "Rename") is not { } to || to == old) return;
        Run(async () =>
        {
            await model.Api.RenameSet(old, to);
            model.EditingSet = to.ToLowerInvariant();
        });
    }

    async void Delete()
    {
        var s = model.EditingSet;
        if (await Dialogs.Confirm(window.Root, $"Delete the set “{s}”?",
                "Its fixture list and patch are removed, and where it hung on every rig. The rigs themselves stay.", "Delete", destructive: true))
            Run(() => model.Api.DeleteSet(s));
    }

    async void Run(Func<Task> op)
    {
        if (!await model.EnsureSetupService()) { error("Couldn’t Change the Sets", "The engine's setup service did not start."); return; }
        try { await op(); }
        catch (Exception e) when (SetView.IsApiError(e)) { error("Couldn’t Change the Sets", e.Message); }
        model.ReloadSets();
    }
}

/// Segoe Fluent symbols for fixture kinds (library `kind`), by their SF Symbols names.
public static class FixtureIcon
{
    public static string Symbol(string? kind) => kind switch
    {
        "moving_head" => "light.overhead.right",
        "moving_bar" or "par_bar" => "light.strip.2",
        "laser" => "rays",
        "strobe" => "bolt",
        "blinder" => "light.panel",
        "smoke" => "cloud.fog",
        _ => "light.recessed",
    };
}
