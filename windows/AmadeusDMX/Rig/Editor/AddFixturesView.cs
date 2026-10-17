// Adding fixtures in the editor: pick a model and how many (from your library, or a QLC+/OFL one converted into it).
// On the Mac this view exists but nothing opens it at the moment (fixtures are added on the Set page); here it is a
// dialog with the same parts: AddFixturesView.Present(model, editor, root).
namespace AmadeusDMX;

public sealed class AddFixturesView(AppModel model, RigEditorModel editor)
{
    CatalogEntry[] _results = [];
    string? _key;
    CancellationTokenSource? _search;

    bool IsOnTruss => editor.Selection?.TrussId is not null;

    public static async Task Present(AppModel model, RigEditorModel editor, XamlRoot root) =>
        await new AddFixturesView(model, editor).Show(root);

    async Task Show(XamlRoot root)
    {
        var query = new TextBox { PlaceholderText = "Search: sharpy, katana, pixbar, atomic…" };
        var list = new ListView { Height = 200, SelectionMode = ListViewSelectionMode.Single };
        var modes = new ComboBox { MinWidth = 160, Visibility = Visibility.Collapsed };
        var count = new NumberBox { Value = 4, Minimum = 1, Maximum = 48, SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline,
                                    Header = "Count", Visibility = Visibility.Collapsed };
        var note = UI.Text("", Font.Caption).Wrap();
        var error = UI.Text("", Font.Caption).Foreground(Tint.Red).Wrap();
        var spinner = UI.Spinner().Visible(false);
        var dialog = new ContentDialog
        {
            XamlRoot = root, Title = "Add Fixtures", PrimaryButtonText = "Add", CloseButtonText = "Cancel", IsPrimaryButtonEnabled = false,
            DefaultButton = ContentDialogButton.Primary,
            Content = UI.VStack(12,
                UI.Text(IsOnTruss ? "They’re spread along the selected truss." : "They’re placed on the stage floor; drag them onto a truss.", Font.Caption)
                    .Secondary().Wrap(),
                query, list, UI.HStack(12, modes, count), note, error, spinner).Frame(width: 380),
        };
        query.TextChanged += async (_, _) =>
        {
            _search?.Cancel();
            var cts = _search = new CancellationTokenSource();
            try { await Task.Delay(300, cts.Token); }
            catch (TaskCanceledException) { return; }
            var q = query.Text;
            if (q.Length < 2 || !await model.EnsureSetupService() || cts.IsCancellationRequested) return;
            try { _results = await model.Api.Catalog(q, 12); }
            catch (Exception e) when (e is not OutOfMemoryException) { _results = []; }
            if (cts.IsCancellationRequested) return;
            list.Items.Clear();
            foreach (var r in _results)
            {
                var detail = string.Join(" · ", new[] { r.Type, r.IsLocal ? "in your library" : r.Source?.ToUpperInvariant() }.OfType<string>());
                list.Items.Add(new ListViewItem { Content = UI.VStack(0, UI.Text($"{r.Manufacturer} {r.Model}"), UI.Text(detail, Font.Caption).Secondary()), Tag = r });
            }
        };
        list.SelectionChanged += async (_, _) =>
        {
            if (list.SelectedItem is not ListViewItem { Tag: CatalogEntry e }) return;
            spinner.Visible(true);
            try
            {
                var k = e.IsLocal ? e.Key : await model.Api.AddToLibrary(e.Key);  // QLC+/OFL → our library
                _key = k;
                if (editor.Definition(k) is not { } def) { error.Text = $"Couldn’t read {k}"; return; }
                note.Text = def.AddingNote ?? "";
                note.Foreground(def.Warning is not null ? new Microsoft.UI.Xaml.Media.SolidColorBrush(Tint.Red) : Theme.Brush("TextFillColorSecondaryBrush"));
                modes.Items.Clear();
                foreach (var m in def.Modes.Keys.OrderByDescending(def.ChannelCount)) modes.Items.Add(m);
                modes.SelectedItem = def.DefaultMode;
                modes.Visibility = count.Visibility = Visibility.Visible;
                error.Text = "";
                dialog.IsPrimaryButtonEnabled = modes.SelectedItem is string;
            }
            catch (Exception ex) when (ex is not OutOfMemoryException) { error.Text = ex.Message; }
            finally { spinner.Visible(false); }
        };
        modes.SelectionChanged += (_, _) => dialog.IsPrimaryButtonEnabled = _key is not null && modes.SelectedItem is string;
        if (await dialog.ShowAsync() == ContentDialogResult.Primary && _key is { } key && modes.SelectedItem is string mode)
            editor.AddFixtures(key, mode, (int)Math.Clamp(double.IsNaN(count.Value) ? 4 : count.Value, 1, 48));
    }
}
