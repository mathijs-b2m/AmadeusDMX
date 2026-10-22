// Import from Documents…: a set and a rig built from what a venue sends (MVR files, patch sheets, PDFs of patch lists,
// riders and light plots), read by the engine (amadeus/rig/importer, POST /api/import), followed once a second, then
// its report: what is missing, what to check, what went right. The drawings it placed the fixtures from lie under
// the rig in the editor (RigEditorModel's drawings).
// The port of mac/Sources/AmadeusDMX/Rig/ImportSheet.swift (docs/import-ui.md): the sheet is a ContentDialog whose
// content goes from the form to the progress to the report (WinUI shows one dialog at a time).
using System.Text.RegularExpressions;
using Microsoft.UI.Xaml.Media;

namespace AmadeusDMX;

public sealed class ImportSheet(AppModel model)
{
    static readonly string[] Types = [".pdf", ".mvr", ".csv", ".tsv", ".txt", ".xlsx", ".xlsm"];

    enum Phase { Form, Replace, Running, Done, Failed }

    Phase _phase = Phase.Form;
    readonly List<string> _files = [];
    string _name = "";
    bool _nameEdited, _busy;
    string _step = "";
    string? _job;   // the running import, to cancel it
    string? _error;
    ImportStatus? _status;
    ContentDialog? _dialog;
    readonly ContentControl _body = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    /// What the window calls when AppModel.ShowImport turns on.
    public static async void Present(AppModel model, MainWindow window)
    {
        if (window.Root is not { } root) { model.ShowImport = false; return; }
        try { await new ImportSheet(model).Show(root); }
        finally { model.ShowImport = false; }
    }

    async Task Show(XamlRoot root)
    {
        _dialog = new ContentDialog { XamlRoot = root, Title = "Import from Documents", Content = _body.Frame(width: 600) };
        _dialog.Resources["ContentDialogMaxWidth"] = 680.0;
        _dialog.PrimaryButtonClick += (_, args) =>
        {
            switch (_phase)
            {
                case Phase.Form: args.Cancel = true; Start(replace: false); break;
                case Phase.Replace: args.Cancel = true; Start(replace: true); break;
                case Phase.Done: OpenInEditor(null, hide: false); break;   // and the sheet closes
                default: args.Cancel = true; break;
            }
        };
        _dialog.SecondaryButtonClick += (_, args) =>  // Change Name, Back: to the form again; Cancel Import
        {
            args.Cancel = true;
            if (_phase == Phase.Running)
            {
                if (_job is { } job) { _step = "Cancelling…"; Render(); CancelJob(job); }
                return;
            }
            _phase = Phase.Form;
            Render();
        };
        Render();
        await Dialogs.Show(_dialog);
    }

    // MARK: what the sheet shows

    void Render()
    {
        if (_dialog is null) return;
        _body.Content = _phase switch
        {
            Phase.Form => Form(),
            Phase.Replace => UI.Text($"A set or rig called “{SafeName}” exists already. Importing replaces both with what these files say.").Wrap(),
            Phase.Running => Progress(),
            _ => Report(),
        };
        _dialog.Title = _phase switch
        {
            Phase.Replace => $"Replace the set and rig “{SafeName}”?",
            Phase.Running => $"Importing “{SafeName}”",
            Phase.Done => $"Imported “{DoneName}”",
            Phase.Failed => $"Couldn’t Import “{SafeName}”",
            _ => "Import from Documents",
        };
        (_dialog.PrimaryButtonText, _dialog.SecondaryButtonText, _dialog.CloseButtonText) = _phase switch
        {
            Phase.Form => ("Import", "", "Cancel"),
            Phase.Replace => ("Replace", "Change Name", "Cancel"),
            Phase.Running => ("", "Cancel Import", "Close"),
            Phase.Done => ("Open in Rig Editor", "", "Close"),
            _ => ("", "Back", "Close"),
        };
        _dialog.DefaultButton = _phase is Phase.Form or Phase.Done ? ContentDialogButton.Primary : ContentDialogButton.None;
        _dialog.IsSecondaryButtonEnabled = _phase != Phase.Running || (_job is not null && _step != "Cancelling…");
        _dialog.IsPrimaryButtonEnabled = _phase switch
        {
            Phase.Form => !_busy && _files.Count > 0 && SafeName.Length > 0 && !NeedsKey,
            Phase.Replace => !_busy,
            _ => true,
        };
    }

    /// The set's and rig's name as the engine makes it (amadeus/rig/store.py safe_name).
    string SafeName => Safe(_name);

    /// The name the import gave the set and rig.
    string DoneName => _status?.Name is { Length: > 0 } n ? n : SafeName;

    static string Safe(string s) => Regex.Replace(s.Trim().ToLowerInvariant(), "[^a-z0-9_-]+", "-").Trim('-');

    bool HasPDF => _files.Any(f => Path.GetExtension(f).Equals(".pdf", StringComparison.OrdinalIgnoreCase));

    /// PDFs are read with AI: without an OpenAI key (the app's, or the engine folder's .env) they can't be.
    bool NeedsKey => HasPDF && KeySource.Current(Keychain.OpenAIKey, model.Workspace).Where == KeySource.Kind.None;

    UIElement Form()
    {
        var files = UI.VStack(6);
        foreach (var f in _files)
        {
            var path = f;
            files.Children.Add(UI.HStack(8,
                UI.Icon(Path.GetExtension(path).Equals(".pdf", StringComparison.OrdinalIgnoreCase) ? "doc.richtext" : "doc.text", 14).Secondary(),
                UI.Text(Path.GetFileName(path)).Lines(1).Tooltip(path).Grow(),
                UI.IconButton("xmark.circle.fill", "Leave this file out", () => { _files.Remove(path); FilesChanged(); })));
        }
        if (_files.Count == 0) files.Children.Add(UI.Text("No files yet: an MVR file, patch sheets (CSV, Excel), or PDFs", Font.Callout).Secondary());
        var choose = UI.Button("Add Files…", Choose, "plus").Tooltip("Pick the documents: several at once (.pdf .mvr .csv .tsv .txt .xlsx .xlsm)");
        choose.IsEnabled = !_busy;

        var name = new TextBox { Text = _name, PlaceholderText = "Name", MinWidth = 260 }.Tooltip("The set and the rig get this name");
        name.TextChanged += (_, _) =>
        {
            _name = name.Text;
            _nameEdited = true;
            Validate();
        };

        var rows = new List<UIElement?>
        {
            UI.Text("A venue's documents become a set (the fixtures and their patch) and a rig (the trusses they hang on) of the same name; light plots lie under the rig as drawings.")
                .Secondary().Wrap(),
            UI.Card(UI.VStack(10, UI.HStack(8, UI.Text("Files", Font.Headline), UI.Spacer(), choose), files)),
            UI.Card(UI.Row("Name", name)),
            AmadeusDMX.Form.Note("info.circle", "MVR files and patch sheets are read here. PDFs (patch lists, riders, light plots) are read with AI using your own OpenAI API key; every page is sent to OpenAI."),
        };
        if (NeedsKey)
            rows.Add(UI.HStack(10,
                AmadeusDMX.Form.Note("key", "There is no OpenAI API key in the app: PDFs can't be read without one.", Tint.Orange).Grow(),
                UI.Button("Open Settings…", OpenSettings).Tooltip("Settings › Director: enter your OpenAI API key (the same key the AI director uses)")));
        if (_busy) rows.Add(UI.HStack(8, UI.Spinner(), UI.Text("Sending the files…", Font.Callout).Secondary()));
        if (_error is { } e) rows.Add(UI.Text("⚠ " + e, Font.Callout).Foreground(Tint.Red).Wrap());
        return UI.VStack(14, [.. rows]);
    }

    /// Typing the name: only the buttons follow (the form isn't rebuilt under the cursor).
    void Validate()
    {
        if (_dialog is not null && _phase == Phase.Form) _dialog.IsPrimaryButtonEnabled = !_busy && _files.Count > 0 && SafeName.Length > 0 && !NeedsKey;
    }

    void FilesChanged()
    {
        if (!_nameEdited || _name.Trim().Length == 0)
        {
            _name = _files.Count > 0 ? Safe(Path.GetFileNameWithoutExtension(_files[0])) : "";
            _nameEdited = false;
        }
        Render();
    }

    async void Choose()
    {
        if (Dialogs.WindowOf(_body) is not { } id) return;
        var picker = new Microsoft.Windows.Storage.Pickers.FileOpenPicker(id) { CommitButtonText = "Choose" };
        foreach (var t in Types) picker.FileTypeFilter.Add(t);
        var picked = await picker.PickMultipleFilesAsync();
        foreach (var f in picked)
            if (!_files.Contains(f.Path, StringComparer.OrdinalIgnoreCase)) _files.Add(f.Path);
        FilesChanged();
    }

    /// To the OpenAI key in Settings (the sheet closes; the files are chosen again afterwards).
    void OpenSettings()
    {
        _dialog?.Hide();
        model.SettingsTab = "director";
        model.Section = Section.Settings;
    }

    UIElement Progress() =>
        UI.VStack(14,
            UI.HStack(10, UI.Spinner(20), UI.Text(_step.Length > 0 ? _step : "Reading the files…").Wrap().Grow()),
            UI.Text(HasPDF ? "Reading PDFs with AI takes up to a few minutes. You can close this and carry on: the import goes on, and the rig shows up in the list when it's done."
                           : "You can close this and carry on: the import goes on, and the rig shows up in the list when it's done.", Font.Callout).Secondary().Wrap());

    UIElement Report()
    {
        var s = _status;
        var rows = new List<UIElement?>();
        if (_phase == Phase.Done && s is not null)
        {
            var counts = new List<string> { $"{s.Fixtures ?? 0} fixtures", $"{s.Trusses ?? 0} trusses" };
            if (s.Underlays is > 0 and var u) counts.Add($"{u} drawing{(u == 1 ? "" : "s")}");
            rows.Add(UI.Text(string.Join(" · ", counts) + ". Look over what is marked before the show: a line with fixtures selects them in the rig editor.")
                .Secondary().Wrap());
        }
        else
        {
            rows.Add(AmadeusDMX.Form.Note("exclamationmark.triangle.fill", _error ?? s?.Error ?? "The import failed.", Tint.Red, Font.Body));
        }
        if (s is { Notes.Count: > 0 })
        {
            var lines = UI.VStack(8);
            foreach (var n in s.Report) lines.Children.Add(NoteRow(n));
            var scroll = UI.Scroll(lines.Padding(new Thickness(0, 0, 12, 0)));
            scroll.MaxHeight = 380;
            rows.Add(scroll);
        }
        return UI.VStack(14, [.. rows]);
    }

    /// A line of the report: ✗ missing (red), ? to check (orange), ✓ fine (green); its fixtures can be selected.
    UIElement NoteRow(ImportStatus.Note n)
    {
        var (symbol, color) = n.Level switch
        {
            "missing" => ("xmark.circle.fill", Tint.Red),
            "check" => ("questionmark.circle.fill", Tint.Orange),
            _ => ("checkmark.circle.fill", Tint.Green),
        };
        var row = UI.HStack(8, UI.Icon(symbol, 16).Foreground(color), UI.Text(n.Text).Wrap().Selectable().Grow());
        row.Alignment = 0;
        if (n.Ids.Count > 0 && _phase == Phase.Done)
            row.Children.Add(UI.Link("Select", () => OpenInEditor(n.Ids))
                .Tooltip($"Open the rig with {(n.Ids.Count == 1 ? n.Ids[0] : $"these {n.Ids.Count} fixtures")} selected"));
        return row;
    }

    // MARK: importing

    async void Start(bool replace)
    {
        _error = null;
        _busy = true;
        if (_phase == Phase.Replace) _phase = Phase.Form;
        Render();
        try
        {
            if (!await model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var files = new List<(string, byte[])>();
            foreach (var f in _files) files.Add((Path.GetFileName(f), await File.ReadAllBytesAsync(f)));
            var job = await model.Api.StartImport(SafeName, files, replace);
            _busy = false;
            if (job is null)  // the name is taken: replace them?
            {
                _phase = Phase.Replace;
                Render();
                return;
            }
            _phase = Phase.Running;
            _job = job;
            _step = "Reading the files…";
            Render();
            Follow(job);
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            _busy = false;
            _error = e.Message;
            Render();
        }
    }

    /// Stops the import at its next step; Follow sees it cancelled.
    async void CancelJob(string job)
    {
        try { await model.Api.CancelImport(job); }
        catch (Exception e) when (e is not OutOfMemoryException) { _error = e.Message; Render(); }
    }

    /// Asks how the import goes once a second until it is done (also after the sheet was closed: the set and rig
    /// appear in the lists when it is).
    async void Follow(string job)
    {
        var misses = 0;
        while (true)
        {
            try
            {
                var s = await model.Api.ImportStatus(job);
                misses = 0;
                _status = s;
                if (s.State == "cancelled")
                {
                    _phase = Phase.Form;
                    _job = null;
                    _error = "The import was cancelled: nothing was saved.";
                    Render();
                    return;
                }
                if (!s.Running)
                {
                    _phase = s.Done ? Phase.Done : Phase.Failed;
                    _error = s.Error;
                    if (s.Done) model.ReloadSets();
                    Render();
                    return;
                }
                if (s.Step != _step) { _step = s.Step; Render(); }
            }
            catch (Exception e) when (e is not OutOfMemoryException)
            {
                if (++misses >= 5)  // the setup service went away
                {
                    _phase = Phase.Failed;
                    _error = e.Message;
                    Render();
                    return;
                }
            }
            await Task.Delay(1000);
        }
    }

    /// The new rig on the Rigs page, with the new set showing (and the fixtures of a report line selected).
    void OpenInEditor(IReadOnlyList<string>? select, bool hide = true)
    {
        var name = DoneName;
        if (hide) _dialog?.Hide();
        model.ReloadSets();
        model.Section = Section.Rig;
        model.PendingSelection = select;
        if (model.EditingRig == name) model.EditingRig = "";  // replaced: a new editor for it
        model.EditingRig = name;
        model.EditingRigSet = name;
    }
}
