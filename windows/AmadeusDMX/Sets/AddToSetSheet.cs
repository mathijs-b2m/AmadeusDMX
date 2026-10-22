// Adding fixtures to the set: search a model (our library, QLC+, Open Fixture Library, DMXControl DDF), choose its mode and how
// many. No start addresses: you give each the one set on the fixture (in the inspector). Where they hang is done
// on the Rigs page (mac/Sources/AmadeusDMX/Sets/AddToSetSheet.swift). A sheet: a ContentDialog here. A fixture no
// library knows is imported from its maker's GDTF file, or made from a common layout with New Fixture…
// (NewFixtureSheet.cs, shown in this dialog).
namespace AmadeusDMX;

public sealed class AddToSetSheet
{
    readonly AppModel _model;
    readonly Action _onDone;
    readonly ContentDialog _dialog = new();
    readonly TextBox _query = new() { PlaceholderText = "e.g. sharpy, fuze, katana, pixbar, atomic, laserworld", BorderThickness = new Thickness(0) };
    readonly ProgressRing _busyRing = UI.Spinner();
    readonly ListView _results = new() { SelectionMode = ListViewSelectionMode.Single, MinHeight = 200, Height = 220 };
    readonly ContentControl _options = Host(), _note = Host(), _error = Host();
    IReadOnlyList<CatalogEntry> _found = [];
    CatalogEntry? _chosen;
    string? _key;
    FixtureDefinition? _definition;
    string _mode = "";
    int _count = 4;
    bool _busy;
    CancellationTokenSource? _search;
    string? _madeKey;                    // a fixture just made from a template
    NewFixtureSheet? _new;               // New Fixture… is showing (in this dialog: one ContentDialog at a time)
    UIElement? _main;
    readonly TextBlock _madeNote = UI.Text("", Font.Callout).Secondary().Wrap();

    static ContentControl Host() => new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    AddToSetSheet(AppModel model, Action onDone)
    {
        _model = model;
        _onDone = onDone;
    }

    public static async void Present(AppModel model, XamlRoot? root, Action onDone)
    {
        if (root is null) return;
        await new AddToSetSheet(model, onDone).Show(root);
    }

    async Task Show(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        _dialog.Title = $"Add Fixtures to {_model.EditingSet}";
        _dialog.Resources["ContentDialogMaxWidth"] = 640.0;
        _dialog.CloseButtonText = "Cancel";
        _dialog.DefaultButton = ContentDialogButton.Primary;
        _dialog.PrimaryButtonClick += async (_, e) =>
        {
            e.Cancel = true;  // stays open until added (or with what went wrong)
            var deferral = e.GetDeferral();
            try
            {
                if (_new is { } n) { await n.Make(); }
                else if (await Add()) _dialog.Hide();
            }
            finally { deferral.Complete(); }
        };
        _dialog.Closing += (_, e) =>
        {
            if (_new is null || e.Result == ContentDialogResult.Primary) return;
            e.Cancel = true;  // Cancel (or Esc) on New Fixture: back to the search
            CloseNew();
        };
        _query.TextChanged += (_, _) => Search();
        _results.SelectionChanged += (_, _) =>
        {
            if (_results.SelectedItem is ListViewItem { Tag: CatalogEntry e } && e != _chosen) { _chosen = e; _ = Prepare(); }
        };
        _busyRing.Visibility = Visibility.Collapsed;
        var search = UI.HStack(8, UI.Icon("magnifyingglass").Secondary(), _query.Grow(), _busyRing).Padding(9, 4);
        var field = new Border
        {
            Child = search, CornerRadius = new CornerRadius(9), Background = Theme.Brush("ControlFillColorSecondaryBrush"),
        };
        var newFixture = UI.HStack(8,
            _madeNote.Grow(),
            UI.Button("Import GDTF…", ImportGDTF, "square.and.arrow.down")
                .Tooltip("Convert a .gdtf file from the maker's site or your own GDTF Share account into your fixtures"),
            UI.Button("New Fixture…", ShowNew, "plus")
                .Tooltip("Make it from a common channel layout, then check it channel by channel on the real fixture"));
        _dialog.Content = _main = UI.VStack(14,
            UI.Text("Search by brand or model. Then give each its start address (the one set on the fixture) on the right; where they hang is set on the Rigs page.").Secondary().Wrap(),
            field,
            _results,
            newFixture,
            _options,
            _note,
            _error).MinWidth(520);
        Refresh();
        _query.Loaded += (_, _) => _query.Focus(FocusState.Programmatic);
        await Dialogs.Show(_dialog);
    }

    void Refresh()
    {
        if (_new is { } n)
        {
            _dialog.PrimaryButtonText = "Make Fixture";
            _dialog.IsPrimaryButtonEnabled = n.CanMake;
            return;
        }
        _busyRing.Visibility = _busy ? Visibility.Visible : Visibility.Collapsed;
        _dialog.PrimaryButtonText = $"Add {_count} to the Set";
        _dialog.IsPrimaryButtonEnabled = _key is not null && _mode.Length > 0 && !_busy;
        _madeNote.Text = _madeKey is null ? "Not in any library? Import the maker's GDTF file, or make it from a common layout."
            : "Made for you: once added, give it its start address and check its channels on the fixture once.";
        _note.Content = _definition?.AddingNote is { } note
            ? UI.Text(note, Font.Callout).Foreground(_definition.Warning is null ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Red)).Wrap()
            : null;
    }

    void ShowError(string? e) =>
        _error.Content = e is null ? null : Form.Note("exclamationmark.triangle.fill", e, Tint.Red);

    async void Search()
    {
        _search?.Cancel();
        var cts = _search = new CancellationTokenSource();
        var q = _query.Text;
        try { await Task.Delay(300, cts.Token); }
        catch (TaskCanceledException) { return; }
        if (q.Length < 2 || !await _model.EnsureSetupService() || cts.IsCancellationRequested) return;
        try { _found = await _model.Api.Catalog(q, 20, cts.Token); }
        catch (Exception e) when (SetView.IsApiError(e)) { if (cts.IsCancellationRequested) return; _found = []; }
        _results.Items.Clear();
        foreach (var e in _found)
            _results.Items.Add(new ListViewItem
            {
                Tag = e,
                Content = UI.HStack(8,
                    UI.Icon(Icon(e)).Secondary().Frame(width: 22),
                    UI.VStack(1,
                        UI.Text($"{e.Manufacturer} {e.Model}"),
                        UI.Text(string.Join(" · ", new[] { e.Type, e.Look, e.IsLocal ? "in your library" : e.Source?.ToUpperInvariant() }.OfType<string>()),
                                Font.Caption).Secondary())),
            });
    }

    public static string Icon(CatalogEntry e) => (e.Type ?? "") switch
    {
        "moving head" => "light.overhead.right",
        "laser" => "rays",
        "par" => "light.recessed",
        "blinder" => "light.panel",
        "smoke" => "cloud.fog",
        _ => "lightbulb",
    };

    // MARK: Import GDTF…

    /// A .gdtf file you have, converted on this computer into your fixtures, then chosen like a search result.
    async void ImportGDTF()
    {
        if (_main is null || Dialogs.WindowOf(_main) is not { } id) return;
        var picker = new Microsoft.Windows.Storage.Pickers.FileOpenPicker(id) { CommitButtonText = "Import" };
        picker.FileTypeFilter.Add(".gdtf");
        if (await picker.PickSingleFileAsync() is not { } file) return;
        _busy = true;
        Refresh();
        try
        {
            if (!await _model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var name = Path.GetFileName(file.Path);
            var r = await _model.Api.ImportGDTF(name, await File.ReadAllBytesAsync(file.Path));
            if (r.Key is not { } k || r.Mode is not { } m) throw SetupAPIException.Server($"Couldn’t import {name}");
            _busy = false;
            Use(k, m);
        }
        catch (Exception x) when (SetView.IsApiError(x) || x is IOException) { ShowError(x.Message); }
        finally
        {
            _busy = false;
            Refresh();
        }
    }

    // MARK: New Fixture…

    void ShowNew()
    {
        var q = _query.Text;
        _new = new NewFixtureSheet(_model, q.Length >= 2 && _found.Count == 0 ? q : "", Use, Refresh);
        _dialog.Title = NewFixtureSheet.Title;
        _dialog.Content = _new.Build();
        Refresh();
    }

    void CloseNew()
    {
        _new = null;
        _dialog.Title = $"Add Fixtures to {_model.EditingSet}";
        _dialog.Content = _main;
        Refresh();
    }

    /// A fixture just made from a template: chosen, in its only mode.
    void Use(string k, string m)
    {
        CloseNew();
        _chosen = null;
        _results.SelectedItem = null;
        _key = k;
        _madeKey = k;
        _definition = _model.Workspace?.Definition(k);
        _mode = m;
        _count = 2;
        ShowError(_definition is null ? $"Couldn’t read {k}" : null);
        ShowOptions();
        Refresh();
    }

    async Task Prepare()
    {
        if (_chosen is not { } e) return;
        _madeKey = null;
        _busy = true;
        Refresh();
        try
        {
            var k = e.IsLocal ? e.Key : await _model.Api.AddToLibrary(e.Key);  // QLC+/OFL/DDF → our library
            _key = k;
            _definition = _model.Workspace?.Definition(k);
            _mode = _definition?.DefaultMode ?? "";
            _count = _definition?.IsMoving == true ? 4 : 2;
            ShowError(_definition is null ? $"Couldn’t read {k}" : null);
        }
        catch (Exception x) when (SetView.IsApiError(x)) { ShowError(x.Message); }
        finally
        {
            _busy = false;
            ShowOptions();
            Refresh();
        }
    }

    void ShowOptions()
    {
        if (_definition is not { } d) { _options.Content = null; return; }
        var modes = d.Modes.Keys.OrderByDescending(d.ChannelCount).ToList();
        _options.Content = Form.Section(null,
        [
            Form.Row("DMX mode", UI.Picker(modes, _mode, m => $"{m} · {d.ChannelCount(m)} channels", m => { _mode = m; Refresh(); })),
            Form.Stepper(_count, 1, 96, v => $"How many: {v}", v => { _count = v; Refresh(); }),
        ]);
    }

    async Task<bool> Add()
    {
        if (_key is not { } key || _definition is null || _model.Workspace is not { } ws) return false;
        _busy = true;
        Refresh();
        var set = _model.EditingSet;
        try
        {
            if (!await _model.EnsureSetupService() || SetLayout.Parse(ws.Composed("", set)) is not { } layout)
                throw SetupAPIException.NotRunningError();
            var fixtures = SetLayout.Fixtures(layout);
            // no start address: a guess is usually wrong, and then they overlap
            fixtures.AddRange(new Patch(fixtures, Patch.ChannelsFrom(ws.Definition)).NewFixtures(key, _mode, _count));
            await _model.Api.SaveSet(SetLayout.WithFixtures(layout, fixtures), set);
            _onDone();
            return true;
        }
        catch (Exception e) when (SetView.IsApiError(e))
        {
            ShowError(e.Message);
            return false;
        }
        finally
        {
            _busy = false;
            Refresh();
        }
    }
}
