// A fixture without a brand (or not in any library): made from a common channel layout. Cheap moving heads and
// pars are mostly the same few designs under many names, so their manuals look alike; you pick the layout closest
// to yours and say how many channels it has, and it is made in your library (amadeus/library/generic.py). Its
// channels are then checked one by one on the real fixture in the DMX mapper (Check Channels)
// (mac/Sources/AmadeusDMX/Sets/NewFixtureSheet.swift).
//
// On the Mac a sheet on top of Add Fixtures; WinUI shows one ContentDialog at a time, so here it is a page that
// Add Fixtures shows in its own dialog (its buttons become Cancel and Make Fixture) and leaves again.
namespace AmadeusDMX;

public sealed class NewFixtureSheet
{
    public const string Title = "New Fixture";

    readonly AppModel _model;
    readonly Action<string, string> _made;
    readonly Action _changed;   // whether it can be made may have changed
    readonly TextBox _manufacturer, _name, _watts;
    readonly ContentControl _type = Host(), _turns = Host(), _problems = Host();
    readonly ListView _list = new() { SelectionMode = ListViewSelectionMode.Single, Height = 180 };
    readonly TextBlock _preview = UI.Text("", Font.MonoCaption).Secondary().Wrap(3);
    string _kindType = "spot";
    int _channels = 9, _panDeg = 540, _tiltDeg = 270;
    FixtureTemplates? _catalogue;
    string? _template;
    bool _autoPicked = true;   // the closest layout follows the type and channels until one is picked
    bool _busy, _quiet;
    CancellationTokenSource? _loading;

    static ContentControl Host() => new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public NewFixtureSheet(AppModel model, string brand, Action<string, string> made, Action changed)
    {
        _model = model;
        _made = made;
        _changed = changed;
        _manufacturer = new TextBox { PlaceholderText = "as on the box or label, or leave empty", Text = brand, Width = 300 };
        _name = new TextBox { PlaceholderText = "e.g. 60W LED Spot", Width = 300 };
        _name.TextChanged += (_, _) => _changed();
        _watts = new TextBox { PlaceholderText = "optional", Width = 120 };
        _watts.Tooltip("From the label: how bright the show thinks it is");
        _list.SelectionChanged += (_, _) =>
        {
            if (_quiet || _list.SelectedItem is not ListViewItem { Tag: string id }) return;
            _template = id;
            _autoPicked = false;
            Preview();
            _changed();
        };
    }

    bool Moving => _catalogue?.Types.FirstOrDefault(t => t.Type == _kindType)?.KindName == "moving_head";
    FixtureTemplates.Template? Chosen => _catalogue?.Templates.FirstOrDefault(t => t.Id == _template);

    public bool CanMake => _template is not null && _name.Text.Trim().Length > 0 && !_busy;

    public FrameworkElement Build()
    {
        var channels = Form.Stepper(_channels, 1, 64, v => $"Channels: {v}", v => { _channels = v; _ = LoadTemplates(); })
            .Tooltip("How many DMX channels it uses in the mode you'll run it in: the manual says, and the fixture's display often shows it (\"9CH\", \"d-11\")");
        Types();
        _ = LoadTemplates();
        return UI.VStack(14,
            UI.Text("For a fixture no library knows, often sold without a real brand. Most share a few common channel layouts: pick the one closest to the DMX table in its manual, then check it channel by channel on the fixture.")
                .Secondary().Wrap(),
            Form.Section(null,
            [
                Form.Row("Brand", _manufacturer),
                Form.Row("Name", _name),
                Form.Row("Type", _type),
                channels,
                _turns,
                Form.Row("Power (W)", _watts),
            ]),
            UI.Text("Closest layouts", Font.Headline),
            _list,
            _preview,
            _problems).MinWidth(520);
    }

    void Types()
    {
        var types = _catalogue?.Types ?? [];
        var chosen = types.FirstOrDefault(t => t.Type == _kindType);
        _type.Content = types.Count == 0 ? UI.Spinner()
            : UI.Picker(types, chosen!, t => t.Label, t => { _kindType = t.Type; _ = LoadTemplates(); }).MinWidth(200);
        _turns.Content = Moving
            ? UI.HStack(12,
                UI.Text("Pan"), UI.Picker(new[] { 360, 540, 630 }, _panDeg, v => $"{v}°", v => _panDeg = v),
                UI.Text("Tilt"), UI.Picker(new[] { 180, 220, 270 }, _tiltDeg, v => $"{v}°", v => _tiltDeg = v))
                .Tooltip("How far it turns and tilts (the manual says; most cheap heads: 540° and 270°)")
            : null;
    }

    async Task LoadTemplates()
    {
        _loading?.Cancel();
        var cts = _loading = new CancellationTokenSource();
        var (type, channels) = (_kindType, _channels);
        FixtureTemplates c;
        try
        {
            if (!await _model.EnsureSetupService() || cts.IsCancellationRequested) return;
            c = await _model.Api.FixtureTemplates(type, channels, cts.Token);
        }
        catch (Exception e) when (SetView.IsApiError(e) || e is OperationCanceledException) { return; }
        if (cts.IsCancellationRequested) return;
        _catalogue = c;
        // the closest one, unless one was picked by hand
        if (_autoPicked || _template is null) _template = c.Templates.FirstOrDefault()?.Id;
        Types();
        Templates();
        Preview();
        _changed();
    }

    void Templates()
    {
        _quiet = true;
        try
        {
            _list.Items.Clear();
            foreach (var t in _catalogue?.Templates ?? [])
            {
                var differs = t.Id != "blank" && t.Count != _channels;
                var item = new ListViewItem
                {
                    Tag = t.Id,
                    Content = UI.VStack(2,
                        UI.HStack(8,
                            UI.Text(t.Label),
                            UI.Spacer(),
                            differs
                                ? UI.Text(t.Count > _channels ? $"last {t.Count - _channels} left off" : $"{_channels - t.Count} more as unknown", Font.Caption).Secondary()
                                : null),
                        UI.Text(t.About, Font.Caption).Secondary().Wrap(2)).Padding(0, 4),
                    HorizontalContentAlignment = HorizontalAlignment.Stretch,
                };
                _list.Items.Add(item);
                if (t.Id == _template) _list.SelectedItem = item;
            }
        }
        finally { _quiet = false; }
    }

    /// The channels it gets, as numbered on the fixture.
    void Preview()
    {
        var t = Chosen;
        _preview.Text = t is null || t.Channels.Count == 0 ? ""
            : string.Join(" · ", Enumerable.Range(0, _channels).Select(i => $"{i + 1} {(i < t.Channels.Count ? t.Channels[i] : "unknown")}"));
        _preview.Visibility = _preview.Text.Length == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    void ShowProblems(IReadOnlyList<string> problems) =>
        _problems.Content = UI.VStack(4, [.. problems.Select(p => (UIElement)Form.Note("exclamationmark.triangle.fill", p, Tint.Red))]);

    /// Makes it; true when made (and handed to `made`).
    public async Task<bool> Make()
    {
        if (_template is not { } template || !CanMake) return false;
        _busy = true;
        _changed();
        try
        {
            var watts = int.TryParse(_watts.Text.Trim(), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var w) ? w : 0;
            if (!await _model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var r = await _model.Api.NewFixture(_manufacturer.Text, _name.Text, template, _channels, _kindType, watts, _panDeg, _tiltDeg);
            if (r is { Key: { } key, Mode: { } mode })
            {
                _made(key, mode);
                return true;
            }
            ShowProblems(r.Problems ?? ["Couldn’t make it"]);
        }
        catch (Exception e) when (SetView.IsApiError(e)) { ShowProblems([e.Message]); }
        finally
        {
            _busy = false;
            _changed();
        }
        return false;
    }
}
