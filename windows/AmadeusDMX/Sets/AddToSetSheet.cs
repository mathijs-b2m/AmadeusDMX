// Adding fixtures to the set: search a model (our library, QLC+, Open Fixture Library), choose its mode and how
// many. They get free DMX addresses (the kit's Patch). Where they hang is done on the Rigs page
// (mac/Sources/AmadeusDMX/Sets/AddToSetSheet.swift). A sheet: a ContentDialog here.
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
            try { if (await Add()) _dialog.Hide(); }
            finally { deferral.Complete(); }
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
        _dialog.Content = UI.VStack(14,
            UI.Text("Search by brand or model. They get free DMX addresses; where they hang is set on the Rigs page.").Secondary().Wrap(),
            field,
            _results,
            _options,
            _note,
            _error).MinWidth(520);
        Refresh();
        _query.Loaded += (_, _) => _query.Focus(FocusState.Programmatic);
        await Dialogs.Show(_dialog);
    }

    void Refresh()
    {
        _busyRing.Visibility = _busy ? Visibility.Visible : Visibility.Collapsed;
        _dialog.PrimaryButtonText = $"Add {_count} to the Set";
        _dialog.IsPrimaryButtonEnabled = _key is not null && _mode.Length > 0 && !_busy;
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

    async Task Prepare()
    {
        if (_chosen is not { } e) return;
        _busy = true;
        Refresh();
        try
        {
            var k = e.IsLocal ? e.Key : await _model.Api.AddToLibrary(e.Key);  // QLC+/OFL → our library
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
            // free addresses after what is patched, universe by universe
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
