// The DMX mapper: what each channel of a fixture's mode does, set by hand, for fixtures the show can't play from
// their library file (effect lights, colour macros, numbered or unnamed channels). Each channel is played (a
// dimmer, a colour, pan or tilt, optionally for one cell of a bar) or held at a value. "Try on the Lights" sends
// the values as they are to one fixture of the set, so you can find what a channel does; the library's names and
// ranges are shown where QLC+ or the Open Fixture Library has them. Saved into your copy of the definition
// (amadeus/library/mapper.py): every fixture of that model plays by it (mac/Sources/AmadeusDMX/Sets/MapperSheet.swift).
namespace AmadeusDMX;

/// `Fixture`: the one tried on the lights; `Address` null: it has no start address yet (nothing can be tried).
public sealed record MapTarget(string Key, string Mode, string Fixture, int? Address, int Universe)
{
    public string Id => $"{Key}|{Mode}";
}

public sealed class MapperSheet
{
    readonly AppModel _model;
    readonly MapTarget _target;
    readonly string? _tryRefusal;   // why it can't be tried on the lights now (nil: it can)
    readonly Action _saved;
    readonly MapperModel _m = new();
    readonly ContentDialog _dialog = new();
    readonly ContentControl _header = Host(), _body = Host(), _problems = Host();
    string? _error;
    bool _trying, _saving;
    CancellationTokenSource? _sending;
    IReadOnlyList<string> _problemList = [];

    static ContentControl Host() => new()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
    };

    MapperSheet(AppModel model, MapTarget target, string? tryRefusal, Action saved)
    {
        _model = model;
        _target = target;
        _tryRefusal = tryRefusal;
        _saved = saved;
    }

    public static async void Present(AppModel model, XamlRoot? root, MapTarget target, string? tryRefusal, Action saved)
    {
        if (root is null) return;
        await new MapperSheet(model, target, tryRefusal, saved).Show(root);
    }

    async Task Show(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        _dialog.Resources["ContentDialogMaxWidth"] = 900.0;
        _dialog.Resources["ContentDialogMaxHeight"] = 760.0;
        _dialog.CloseButtonText = "Cancel";
        _dialog.PrimaryButtonText = "Save Mapping";
        _dialog.DefaultButton = ContentDialogButton.Primary;
        _dialog.PrimaryButtonClick += async (_, e) =>
        {
            e.Cancel = true;
            var deferral = e.GetDeferral();
            try { if (await Save()) _dialog.Hide(); }
            finally { deferral.Complete(); }
        };
        _dialog.Closed += (_, _) => StopTrying();
        var grid = new Grid { MinWidth = 760, Height = 540 };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Grid.SetRow(_header, 0);
        Grid.SetRow(_body, 1);
        Grid.SetRow(_problems, 2);
        grid.Children.Add(_header);
        grid.Children.Add(_body);
        grid.Children.Add(_problems);
        _dialog.Content = grid;
        _body.Content = UI.Spinner(32);
        Header();
        Footer();
        _ = Load();
        await Dialogs.Show(_dialog);
    }

    // MARK: parts

    void Header()
    {
        var m = _m.Mapping;
        var title = UI.HStack(8,
            UI.Text("Map DMX Channels", Font.Title2),
            UI.Text(m?.Name ?? _target.Key).Secondary(),
            UI.Spacer(),
            m is { Refusal.Length: 0 }
                ? UI.Picker(MapperModel.KindChoices(m), MapperModel.KindChoices(m).FirstOrDefault(k => k.Kind == m.Kind), k => k.Label,
                            k => _m.SetKind(k.Kind))
                    .Tooltip("What it is, when its channels don't say: pan and tilt make a moving head, cells a bar")
                : null);
        var tryIt = Form.ToggleButton(UI.Label(_trying ? "lightbulb.fill" : "lightbulb", "Try on the Lights"), _trying, on =>
        {
            if (on) StartTrying(); else StopTrying();
            Header();
        });
        tryIt.IsEnabled = _tryRefusal is null && _m.Editable;
        if (_trying) tryIt.Foreground(Tint.Yellow);
        tryIt.Tooltip(_tryRefusal ?? $"Send these values as they are to {_target.Fixture} (the rest of the set dark, a running show paused), to see what each channel does");
        var line = UI.HStack(14,
            UI.Text($"Mode {_target.Mode}", Font.Callout).Secondary(),
            m is null ? null
                : m.Plays ? UI.Label("checkmark.circle", "The show plays it", Font.Callout).Secondary()
                : UI.Label("exclamationmark.triangle.fill", "The show plays nothing in this mode yet", Font.Callout).Foreground(Tint.Orange),
            UI.Spacer(),
            tryIt);
        _header.Content = UI.VStack(8, title, line,
            UI.Text($"Give each channel what the show plays on it, or hold it at a value (programs off, a shutter open, a macro on a colour). Every {m?.Name ?? "fixture of this model"} in your sets plays by it.",
                    Font.Caption).Secondary().Wrap()).Margin(0, 0, 0, 10);
    }

    void Body()
    {
        if (_m.Mapping is { } m)
        {
            if (m.Refusal.Length > 0) { _body.Content = UI.Unavailable("exclamationmark.triangle", "Not Mapped Here", m.Refusal); return; }
            var list = UI.VStack(0);
            for (var i = 0; i < m.Channels.Count; i++)
            {
                if (i > 0) list.Children.Add(UI.Divider());
                var row = new ChannelRow(_m, i, _target.Address + i, _target.Universe, ValuesChanged).Build().Padding(4, 6);
                if (i % 2 == 1) row.Background(Theme.Brush("SubtleFillColorSecondaryBrush"));
                list.Children.Add(row);
            }
            _body.Content = UI.Scroll(list);
        }
        else if (_error is { } e)
            _body.Content = UI.Unavailable("exclamationmark.triangle", "Couldn’t Read the Fixture", e);
    }

    void Footer()
    {
        _problems.Content = UI.VStack(4, [.. _problemList.Select(p => (UIElement)Form.Note("exclamationmark.triangle.fill", p, Tint.Orange))]);
        _dialog.IsPrimaryButtonEnabled = _m.Editable && !_saving && !_model.EngineRunning;
    }

    // MARK: loading and saving

    async Task Load()
    {
        if (!await _model.EnsureSetupService()) { _error = SetupAPIException.NotRunningError().Message; Body(); return; }
        try { _m.Mapping = await _model.Api.Mapping(_target.Key, _target.Mode); }
        catch (Exception e) when (SetView.IsApiError(e)) { _error = e.Message; }
        Header();
        Body();
        Footer();
    }

    async Task<bool> Save()
    {
        if (_m.Mapping is not { } m) return false;
        _saving = true;
        Footer();
        try
        {
            _problemList = await _model.Api.SaveMapping(m);
            if (_problemList.Count == 0)
            {
                StopTrying();
                _saved();
                return true;
            }
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _problemList = [e.Message]; }
        finally
        {
            _saving = false;
            Footer();
        }
        return false;
    }

    // MARK: trying on the lights

    void StartTrying()
    {
        _trying = true;
        Send();
    }

    void StopTrying()
    {
        if (!_trying) return;
        _trying = false;
        _sending?.Cancel();
        var (id, rig, set) = (_target.Fixture, _model.SelectedRig, _model.EditingSet);
        _ = Task.Run(async () =>
        {
            try { await _model.Api.TestLight(id, false, rig: rig, set: set); }
            catch (Exception e) when (SetView.IsApiError(e)) { }
        });
    }

    void ValuesChanged() { if (_trying) Send(); }

    /// The values to the fixture, at most ~20 times a second while a slider moves.
    async void Send()
    {
        _sending?.Cancel();
        var cts = _sending = new CancellationTokenSource();
        var (values, lit, id, rig, set) = (_m.Raw, _m.Light, _target.Fixture, _model.SelectedRig, _model.EditingSet);
        try { await Task.Delay(50, cts.Token); }
        catch (TaskCanceledException) { return; }
        if (!_trying) return;
        try { await _model.Api.TestLight(id, true, values, lit, rig, set); }
        catch (Exception e) when (SetView.IsApiError(e))
        {
            _trying = false;
            _problemList = [e.Message];
            Header();
            Footer();
        }
    }
}

/// One channel: its number and address, the library's name and ranges, what the show does with it, its value.
public sealed class ChannelRow(MapperModel m, int index, int? address, int universe, Action changed)
{
    FixtureMapping.Channel Channel => m.Mapping!.Channels[index];
    readonly ContentControl _cell = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false, Width = 110 };
    Slider? _slider;
    TextBox? _value;
    bool _quiet;

    public FrameworkElement Build()
    {
        var c = Channel;
        var number = UI.VStack(1,
            UI.Text($"{c.N}").Bold(),
            UI.Text(address is { } a ? Patch.Where(universe, a) : "–", Font.Caption2).Secondary()).Frame(width: 44);

        var name = UI.HStack(4, UI.Text(c.Name).Lines(1));
        if (c.Ranges.Count > 0)
        {
            var ranges = UI.MenuButton(UI.Icon("list.bullet", 12), () => UI.Menu([.. c.Ranges.Select(r =>
                (MenuFlyoutItemBase)UI.Item($"{r.Lo}–{r.Hi}  {(r.What.Length == 0 ? "–" : r.What)}", () => SetValue(r.Mid)))]))
                .Tooltip("What its values do (from the fixture library): pick one to set it");
            ranges.Padding = new Thickness(6, 2, 6, 2);
            name.Children.Add(ranges);
        }
        name.Width = 200;

        var role = RolePicker().Frame(width: 150);
        _slider = UI.Slider(c.Value, 0, 255, v => SetValue((int)Math.Round(v)), step: 1).MinWidth(120)
            .Tooltip(c.Role == "hold" ? "The value it is held at" : "A value to try on the lights (the show plays this channel)");
        _value = new TextBox { Text = c.Value.ToString(), Width = 56, TextAlignment = TextAlignment.Right };
        _value.TextChanged += (_, _) =>
        {
            if (_quiet || !int.TryParse(_value.Text, out var v)) return;
            SetValue(Math.Clamp(v, 0, 255), fromField: true);
        };
        Cell();
        return UI.HStack(12, number, name, role, _cell, _slider.Grow(), _value);
    }

    /// Hold at value, keep (as converted), then the roles by group.
    ComboBox RolePicker()
    {
        var c = Channel;
        var box = new ComboBox { MinWidth = 140 };
        void Add(string? role, string text, bool header = false)
        {
            var item = new ComboBoxItem { Content = text, Tag = role, IsEnabled = !header };
            if (header) item.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
            box.Items.Add(item);
            if (role == c.Role) box.SelectedItem = item;
        }
        Add("hold", "Hold at value");
        if (c.Role == "keep") Add("keep", $"Keep ({c.Attr.Replace('_', ' ')})");
        foreach (var (group, roles) in MapperModel.Groups(m.Mapping!))
        {
            Add(null, group, header: true);
            foreach (var r in roles) Add(r.RoleName, "  " + r.Label);
        }
        box.SelectionChanged += (_, _) =>
        {
            if (box.SelectedItem is ComboBoxItem { Tag: string role } && role != Channel.Role)
            {
                m.SetRole(index, role);
                Cell();
                _slider?.Tooltip(role == "hold" ? "The value it is held at" : "A value to try on the lights (the show plays this channel)");
                if (_value is not null) _value.Opacity = role == "hold" ? 1 : 0.6;
            }
        };
        return box;
    }

    /// Which cell of a bar it belongs to, for a role that can be a cell's.
    void Cell()
    {
        var role = m.Mapping!.Roles.FirstOrDefault(r => r.RoleName == Channel.Role);
        _cell.Content = role?.Cell == true
            ? Form.Stepper(Channel.Cell, 0, 64, v => v == 0 ? "Whole" : $"Cell {v}", v => m.SetCell(index, v))
                .Tooltip("Which cell of a bar it belongs to (Whole: the fixture as one)")
            : null;
    }

    void SetValue(int v, bool fromField = false)
    {
        m.SetValue(index, v);
        _quiet = true;
        try
        {
            _slider?.SetValueQuietly(Channel.Value);
            if (!fromField && _value is not null) _value.Text = Channel.Value.ToString();
        }
        finally { _quiet = false; }
        changed();
    }
}
