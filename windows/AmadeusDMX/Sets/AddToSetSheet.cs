// Adding fixtures to the set: search a model (our library, QLC+, Open Fixture Library, DMXControl DDF), choose its mode and how
// many. No start addresses: you give each the one set on the fixture (in the inspector). Where they hang is done
// on the Rigs page (mac/Sources/AmadeusDMX/Sets/AddToSetSheet.swift). A sheet: a ContentDialog here. A fixture no
// library knows is made from its manual (a PDF, or a pasted screenshot of its DMX chart, read with AI and the user's
// own OpenAI key), imported from its maker's GDTF file, or made from a common layout with New Fixture…
// (NewFixtureSheet.cs, shown in this dialog).
namespace AmadeusDMX;

public sealed class AddToSetSheet
{
    readonly AppModel _model;
    readonly Action _onDone;
    readonly ContentDialog _dialog = new();
    readonly TextBox _query = new() { PlaceholderText = L("e.g. sharpy, fuze, katana, pixbar, atomic, laserworld"), BorderThickness = new Thickness(0) };
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
    string? _madeKey;                    // a fixture just made from a template, a GDTF file or a manual
    string _madeFrom = "";               // the manual it was made from, for the note
    bool _hasKey;                        // an OpenAI key in the app: manuals can be read
    CancellationTokenSource? _reading;   // a manual is being read with AI
    Button? _manual, _stopReading, _gdtf, _newButton;
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
        _dialog.Title = L("Add Fixtures to {0}", _model.EditingSet);
        _dialog.Resources["ContentDialogMaxWidth"] = 640.0;
        _dialog.CloseButtonText = L("Cancel");
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
        _hasKey = KeySource.Current(Keychain.OpenAIKey, _model.Workspace).Where != KeySource.Kind.None;
        _dialog.Closed += (_, _) => _reading?.Cancel();
        var menu = new MenuFlyout();
        var choose = new MenuFlyoutItem { Text = L("Choose a PDF or Picture…") };
        choose.Click += (_, _) => ChooseManual();
        var paste = new MenuFlyoutItem { Text = L("Paste from Clipboard") };
        paste.Click += (_, _) => PasteManual(true);
        menu.Items.Add(choose);
        menu.Items.Add(paste);
        _manual = new Button { Content = UI.Label("doc.text.magnifyingglass", L("From Manual")), Flyout = menu }
            .Tooltip(_hasKey ? L("Read the fixture's manual with AI and make the fixture from its DMX chart: a PDF, or a picture of the chart (copy a screenshot and paste it here with Ctrl+V). It is sent to OpenAI with your own key.")
                     : L("Reading a manual needs your own OpenAI API key (Settings › Director)"));
        _stopReading = UI.Button(L("Stop"), () => { _reading?.Cancel(); });
        _gdtf = UI.Button(L("Import GDTF…"), ImportGDTF, "square.and.arrow.down")
            .Tooltip(L("Convert a .gdtf file from the maker's site or your own GDTF Share account into your fixtures"));
        _newButton = UI.Button(L("New Fixture…"), ShowNew, "plus")
            .Tooltip(L("Make it from a common channel layout, then check it channel by channel on the real fixture"));
        var newFixture = UI.VStack(8,
            _madeNote,
            UI.HStack(8, _manual, _stopReading, UI.Spacer(), _gdtf, _newButton));
        _dialog.Content = _main = UI.VStack(14,
            UI.Text(L("Search by brand or model. Then give each its start address (the one set on the fixture) on the right; where they hang is set on the Rigs page.")).Secondary().Wrap(),
            field,
            _results,
            newFixture,
            _options,
            _note,
            _error).MinWidth(520);
        // Ctrl+V with a picture or PDF (and no text) on the clipboard reads it as the manual, in the search box too
        _query.Paste += async (_, e) =>
        {
            if (!ManualOnClipboard()) return;
            e.Handled = true;
            await Task.Yield();
            PasteManual(false);
        };
        var pasteKey = new Microsoft.UI.Xaml.Input.KeyboardAccelerator { Key = Windows.System.VirtualKey.V, Modifiers = Windows.System.VirtualKeyModifiers.Control };
        pasteKey.Invoked += (_, e) =>
        {
            if (Microsoft.UI.Xaml.Input.FocusManager.GetFocusedElement(root) is TextBox or NumberBox or PasswordBox || !ManualOnClipboard()) return;
            e.Handled = true;
            PasteManual(false);
        };
        _main!.KeyboardAccelerators.Add(pasteKey);
        _main.KeyboardAcceleratorPlacementMode = Microsoft.UI.Xaml.Input.KeyboardAcceleratorPlacementMode.Hidden;
        Refresh();
        _query.Loaded += (_, _) => _query.Focus(FocusState.Programmatic);
        await Dialogs.Show(_dialog);
    }

    void Refresh()
    {
        if (_new is { } n)
        {
            _dialog.PrimaryButtonText = L("Make Fixture");
            _dialog.IsPrimaryButtonEnabled = n.CanMake;
            return;
        }
        _busyRing.Visibility = _busy ? Visibility.Visible : Visibility.Collapsed;
        _dialog.PrimaryButtonText = _key is null ? L("Add to the Set") : L("Add {0} to the Set", _count);  // a number once a fixture is chosen
        _dialog.IsPrimaryButtonEnabled = _key is not null && _mode.Length > 0 && !_busy;
        var reading = _reading is not null;
        _madeNote.Text = reading ? L("Reading the manual with AI: this takes up to a few minutes.")
            : _madeKey is null ? L("Not in any library? Make it from its manual: a PDF, or a screenshot of its DMX chart (paste it with Ctrl+V). Or import the maker's GDTF file, or start from a common layout.")
            : _madeFrom.Length > 0 ? L("Made for you from {0}: once added, give it its start address and check its channels on the fixture once.", _madeFrom)
            : L("Made for you: once added, give it its start address and check its channels on the fixture once.");
        if (_manual is not null) _manual.IsEnabled = _hasKey && !reading && !_busy;
        if (_stopReading is not null) _stopReading.Visibility = reading ? Visibility.Visible : Visibility.Collapsed;
        if (_gdtf is not null) _gdtf.IsEnabled = !reading;
        if (_newButton is not null) _newButton.IsEnabled = !reading;
        if (reading) _dialog.IsPrimaryButtonEnabled = false;
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
                        UI.Text(string.Join(" · ", new[] { e.Type, e.Look, e.IsLocal ? L("in your library") : e.Source?.ToUpperInvariant() }.OfType<string>().Where(t => t.Length > 0)),
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
        var picker = new Microsoft.Windows.Storage.Pickers.FileOpenPicker(id) { CommitButtonText = L("Import") };
        picker.FileTypeFilter.Add(".gdtf");
        if (await picker.PickSingleFileAsync() is not { } file) return;
        _busy = true;
        Refresh();
        try
        {
            if (!await _model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var name = Path.GetFileName(file.Path);
            var r = await _model.Api.ImportGDTF(name, await File.ReadAllBytesAsync(file.Path));
            if (r.Key is not { } k || r.Mode is not { } m) throw SetupAPIException.Server(L("Couldn’t import {0}", name));
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

    // MARK: From Manual

    async void ChooseManual()
    {
        if (_main is null || Dialogs.WindowOf(_main) is not { } id) return;
        var picker = new Microsoft.Windows.Storage.Pickers.FileOpenPicker(id) { CommitButtonText = L("Read") };
        foreach (var ext in ManualFile.Extensions) picker.FileTypeFilter.Add(ext);
        if (await picker.PickSingleFileAsync() is not { } file) return;
        try { await Read(new ManualFile(Path.GetFileName(file.Path), await File.ReadAllBytesAsync(file.Path))); }
        catch (IOException x) { ShowError(x.Message); }
    }

    /// A picture or PDF on the clipboard, and no text (text pastes into the search box as usual).
    static bool ManualOnClipboard()
    {
        try
        {
            var c = Windows.ApplicationModel.DataTransfer.Clipboard.GetContent();
            return !c.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.Text)
                && (c.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.Bitmap)
                    || c.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.StorageItems));
        }
        catch (Exception x) when (x is System.Runtime.InteropServices.COMException or UnauthorizedAccessException) { return false; }
    }

    /// The picture (a screenshot of the chart), or the copied PDF or picture file, on the clipboard. `asked`: from
    /// the menu (Ctrl+V with nothing to read says nothing).
    async void PasteManual(bool asked)
    {
        if (!_hasKey || _reading is not null || _new is not null) return;
        ManualFile? file = null;
        try { file = await ManualFile.Pasted(); }
        catch (Exception x) when (x is IOException or System.Runtime.InteropServices.COMException or UnauthorizedAccessException) { }
        if (file is not null) await Read(file);
        else if (asked) ShowError(L("There is no picture or PDF on the clipboard. Copy a screenshot of the DMX chart first."));
    }

    /// The manual read with AI into a new fixture in your library (its largest mode), then chosen like a search result.
    async Task Read(ManualFile file)
    {
        ShowError(null);
        var reading = _reading = new CancellationTokenSource();
        Refresh();
        try
        {
            if (!await _model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var r = await _model.Api.FixtureFromManual(file.Name, file.Data, reading.Token);
            if (reading.IsCancellationRequested) return;
            if (r.Key is not { } k || r.Mode is not { } m)
                throw SetupAPIException.Server(r.Problems is { Count: > 0 } p ? string.Join(" ", p) : L("Couldn’t make a fixture from {0}", file.Name));
            Use(k, m, file.Name);
        }
        catch (OperationCanceledException) { }
        catch (Exception x) when (SetView.IsApiError(x)) { if (!reading.IsCancellationRequested) ShowError(x.Message); }
        finally
        {
            if (_reading == reading) _reading = null;
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
        _dialog.Title = L("Add Fixtures to {0}", _model.EditingSet);
        _dialog.Content = _main;
        Refresh();
    }

    /// A fixture just made (from a template, a GDTF file or a manual): chosen, in its mode.
    void Use(string k, string m) => Use(k, m, "");

    void Use(string k, string m, string from)
    {
        CloseNew();
        _madeFrom = from;
        _chosen = null;
        _results.SelectedItem = null;
        _key = k;
        _madeKey = k;
        _definition = _model.Workspace?.Definition(k);
        _mode = m;
        _count = 2;
        ShowError(_definition is null ? L("Couldn’t read {0}", k) : null);
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
            ShowError(_definition is null ? L("Couldn’t read {0}", k) : null);
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
            Form.Row(L("DMX mode"), UI.Picker(modes, _mode, m => L("{0} · {1} channels", m, d.ChannelCount(m)), m => { _mode = m; Refresh(); })),
            Form.Stepper(_count, 1, 96, v => L("How many: {0}", v), v => { _count = v; Refresh(); }),
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
