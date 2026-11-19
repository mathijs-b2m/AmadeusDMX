// Calibrate: the fixtures of one model put right on the real rig when they behave oddly (a head that goes the
// wrong way, a bar that runs backwards), one at a time, as `amadeus test` asks in the terminal. Each fixture is lit
// as it hangs on the rig: a head straight out to the audience (where does it really point?), then the check after
// hanging's way (does it pan the right way round?); a bar's cells red, green, blue, white along it (reversed?).
// Every answer puts the fixture right at once (its calibration in the set, a bar's `reverse` on the rig) and lights
// it again to see (mac/Sources/AmadeusDMX/Sets/CalibrateSheet.swift).
namespace AmadeusDMX;

/// `Fixtures`: in the set's order; `Start`: the one to begin with.
public sealed record CalibrateTarget(string Key, string Name, IReadOnlyList<string> Fixtures, int Start = 0);

public sealed class CalibrateSheet
{
    enum Step { Front, Check, Cells }

    readonly AppModel _model;
    readonly CalibrateTarget _target;
    readonly FixtureDefinition? _definition;
    readonly string _rig, _set;
    readonly Action _saved;
    readonly ContentDialog _dialog = new();
    readonly ContentControl _header = Host(), _body = Host(), _footer = Host();

    Dictionary<string, JSONValue> _layout = [];   // the set on the rig, calibrations and all
    Dictionary<string, HangCheckStep> _checks = [];
    int _index;
    Step? _step;
    string _order = "";          // which end of the bar red should be at
    string _output = "";
    readonly Dictionary<string, List<string>> _fixed = [];   // what was put right, per fixture
    readonly Dictionary<string, HashSet<string>> _fixedAs = [];   // the ones whose fix each was put right with
    readonly HashSet<string> _confirmed = [];   // said right, or put right on its own: siblings' fixes pass it by
    string? _note;
    string? _error;
    bool _busy;
    string? _lit;
    bool _closed;

    static ContentControl Host() => new()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
    };

    CalibrateSheet(AppModel model, CalibrateTarget target, FixtureDefinition? definition, string rig, string set, Action saved)
    {
        _model = model;
        _target = target;
        _definition = definition;
        _rig = rig;
        _set = set;
        _saved = saved;
    }

    public static async void Present(AppModel model, XamlRoot? root, CalibrateTarget target, FixtureDefinition? definition,
                                     string rig, string set, Action saved)
    {
        if (root is null) return;
        await new CalibrateSheet(model, target, definition, rig, set, saved).Show(root);
    }

    string? Id => _index >= 0 && _index < _target.Fixtures.Count ? _target.Fixtures[_index] : null;

    async Task Show(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        _dialog.Resources["ContentDialogMaxWidth"] = 760.0;
        _dialog.CloseButtonText = L("Done");
        _dialog.Closed += (_, _) =>
        {
            if (_closed) return;
            _closed = true;
            SwitchOff();
            _saved();
        };
        var grid = new Grid { MinWidth = 580, Height = 420 };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var top = UI.Divider();
        var bottom = UI.Divider();
        Grid.SetRow(_header, 0);
        Grid.SetRow(top, 1);
        Grid.SetRow(_body, 2);
        Grid.SetRow(bottom, 3);
        Grid.SetRow(_footer, 4);
        foreach (var e in new UIElement[] { _header, top, _body, bottom, _footer }) grid.Children.Add(e);
        _dialog.Content = grid;
        Render();
        _ = Load();
        await Dialogs.Show(_dialog);
    }

    // MARK: parts

    void Render()
    {
        Header();
        Body();
        Footer();
    }

    void Header()
    {
        _header.Content = UI.VStack(4,
            UI.HStack(8,
                UI.Text(L("Calibrate"), Font.Title2).Bold(),
                UI.Text(_target.Name).Secondary(),
                UI.Spacer(),
                _target.Fixtures.Count > 0 ? UI.Text(L("{0} of {1}", _index + 1, _target.Fixtures.Count)).Secondary() : null),
            UI.Text(L("Stand where the audience would be, facing the stage. Each one lights as it hangs on {0}; say what the real one does and it is put right, and the others of this model with it (except those you already went through).", _rig),
                    Font.Callout).Secondary().Wrap()
        ).Margin(0, 0, 0, 12);
    }

    void Body()
    {
        if (_error is { } e) { _body.Content = UI.Unavailable("exclamationmark.triangle", L("Couldn’t Light It"), e); return; }
        if (Id is not { } id) { _body.Content = UI.Spinner(32); return; }
        var big = UI.Text(id, Font.Mono).Bold();
        big.FontSize = 26;
        var c = _checks.GetValueOrDefault(id);
        var panel = UI.VStack(12,
            UI.HStack(10, big, c is null ? null : UI.Text($"{c.Label} · {c.Dmx}").Secondary()),
            c is null ? null : UI.Text(c.Where, Font.Callout).Wrap());
        if (Unplaced(id))
            panel.Children.Add(Form.Note("exclamationmark.triangle.fill",
                L("Not placed on {0} yet: place it on the Rigs page first, so the calibration knows how it hangs.", _rig), Tint.Orange, Font.Body));
        else if (_step is { } step)
            foreach (var part in StepView(id, step)) panel.Children.Add(part);
        if (_fixed.TryGetValue(id, out var done) && done.Count > 0)
            panel.Children.Add(Form.Note("checkmark.circle.fill", SiblingNote(id) is { } others
                ? L("Put right: {0}. Saved, and for {1} too.", string.Join(", ", done), others)
                : L("Put right: {0}. Saved.", string.Join(", ", done)), Tint.Green));
        if (_note is { } n) panel.Children.Add(UI.Text(n, Font.Callout).Foreground(Tint.Orange).Wrap());
        if (_output.Length > 0) panel.Children.Add(UI.Text(_output, Font.Caption).Secondary().Lines(1));
        panel.Alignment = 0;
        _body.Content = UI.Scroll(panel.Padding(0, 12));
    }

    IEnumerable<UIElement> StepView(string id, Step step)
    {
        switch (step)
        {
            case Step.Front:
                yield return Form.Note("light.beacon.max",
                    L("Its beam should point straight out at the audience, a little down (up when it stands on the floor). Where does the real one point?"),
                    null, Font.Callout).Bold();
                yield return Buttons(
                    UI.Button(L("At the Audience"), Advance, "checkmark").Prominent(),
                    UI.Button(L("Left"), () => Fix(id, "left", L("its pan home turned")), "arrow.left"),
                    UI.Button(L("Right"), () => Fix(id, "right", L("its pan home turned")), "arrow.right"),
                    UI.Button(L("Back at the Stage"), () => Fix(id, "back", L("turned round")), "arrow.uturn.down"),
                    UI.Button(L("Up or Down"), () =>
                    {
                        _note = L("A head that points at the ceiling or the floor here is placed the wrong way up: on the Rigs page, put it hanging under the truss or standing, as it really is.");
                        Body();
                    })
                ).Tooltip(L("Left and right as you see it, facing the stage. Pressed the wrong one, it ends up the other way: press that one"));
                break;
            case Step.Check:
                var c = _checks.GetValueOrDefault(id);
                yield return Form.Note("light.beacon.max", c is { Expect.Length: > 0 } ? c.Expect : L("Its beam points to one side."), null, Font.Callout).Bold();
                yield return UI.Text(L("This catches a head that pans the other way: pointing straight out, that looks right."), Font.Caption).Secondary().Wrap();
                yield return Buttons([
                    UI.Button(L("Yes, There"), Advance, "checkmark").Prominent(),
                    .. (c?.Faults ?? []).Select(f => UI.Button(L("No, it points {0}", f.Seen),
                                                               () => Fix(id, f.Fix, HangCheckPanel.Cause.GetValueOrDefault(f.Fix) ?? f.Fix))),
                ]);
                break;
            case Step.Cells:
                yield return Form.Note("light.strip.2", _order.Length == 0 ? L("Its cells light red, green, blue, white along it.") : _order,
                                       null, Font.Callout).Bold();
                yield return Buttons(
                    UI.Button(L("Yes"), Advance, "checkmark").Prominent(),
                    UI.Button(L("The Other Way Round"), () => Reverse(id), "arrow.left.arrow.right"));
                break;
        }
    }

    FrameworkElement Buttons(params Button[] buttons)
    {
        var row = new FlowPanel { Spacing = 8, LineSpacing = 8 };
        foreach (var b in buttons) row.Children.Add(b.Disabled(_busy));
        return row;
    }


    void Footer()
    {
        _footer.Content = UI.HStack(8,
            UI.Button(L("Previous"), () => Go(_index - 1), "chevron.left").Disabled(_index == 0 || _busy),
            UI.Button(L("Skip"), () => Go(_index + 1), "chevron.right").Disabled(_index + 1 >= _target.Fixtures.Count || _busy)
                .Tooltip(L("On to the next one, without finishing this one")),
            UI.Spacer()
        ).Margin(0, 12, 0, 0);
    }

    // MARK: steps

    List<Step> Steps(string id)
    {
        if (Fixture(id) is not { } f || _definition is not { } d) return [];
        var out_ = new List<Step>();
        if (d.IsMoving)
        {
            out_.Add(Step.Front);
            if (_checks.GetValueOrDefault(id) is { Faults.Count: > 0 }) out_.Add(Step.Check);
        }
        if (d.Cells(f.GetValueOrDefault("mode")?.String ?? "") > 1) out_.Add(Step.Cells);
        return out_;
    }

    void Advance()
    {
        if (Id is not { } id) return;
        _note = null;
        var all = Steps(id);
        if (_step is { } s && all.IndexOf(s) is var i and >= 0 && i + 1 < all.Count)
        {
            _step = all[i + 1];
            Render();
            _ = Light();
        }
        else if (_index + 1 < _target.Fixtures.Count) { _confirmed.Add(id); Go(_index + 1); }
        else { _confirmed.Add(id); _dialog.Hide(); }   // Closed: switched off, saved()
    }

    void Go(int i)
    {
        if (i < 0 || i >= _target.Fixtures.Count) return;
        _index = i;
        _note = null;
        var all = Steps(_target.Fixtures[i]);
        _step = all.Count > 0 ? all[0] : null;
        Render();
        _ = Light();
    }

    // MARK: the engine

    async Task Load()
    {
        try
        {
            if (!await _model.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            _layout = await _model.Api.Rig(_rig, _set);
            await RefreshChecks();
            _index = Math.Min(Math.Max(_target.Start, 0), Math.Max(_target.Fixtures.Count - 1, 0));
            var all = Id is { } id ? Steps(id) : [];
            _step = all.Count > 0 ? all[0] : null;
            Render();
            await Light();
        }
        catch (Exception e) when (SetView.IsApiError(e))
        {
            _error = e.Message;
            Render();
        }
    }

    async Task RefreshChecks()
    {
        var all = await _model.Api.HangCheck(_layout);
        _checks = [];
        foreach (var s in all) _checks.TryAdd(s.Id, s);
    }

    /// The fixture lit for its step (the one lit before switched off).
    async Task Light()
    {
        if (Id is not { } id || _closed) return;
        if (_lit is { } was && was != id)
        {
            try { await _model.Api.TestLight(was, false, _layout, null, false); }
            catch (Exception e) when (SetView.IsApiError(e)) { }
        }
        _lit = null;
        if (_step is not { } step || Unplaced(id)) { _output = ""; Body(); return; }
        try
        {
            var r = await _model.Api.TestLight(id, true, _layout,
                                               step == Step.Front ? "front" : step == Step.Check ? "check" : null,
                                               step == Step.Cells);
            _lit = id;
            _output = r.Summary;
            _order = r.Order;
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _output = e.Message; }
        if (_closed) { SwitchOff(); return; }
        Body();
    }

    void SwitchOff()
    {
        if (_lit is not { } was) return;
        _lit = null;
        var l = _layout;
        _ = Task.Run(async () =>
        {
            try { await _model.Api.TestLight(was, false, l, null, false); }
            catch (Exception e) when (SetView.IsApiError(e)) { }
        });
    }

    /// The head's calibration put right for what was seen (the rig editor's front test, the hang check's faults),
    /// saved, and lit again to see.
    async void Fix(string id, string seen, string what)
    {
        _note = null;
        SetBusy(true);
        try
        {
            var fields = await _model.Api.HangCheckFix(_layout, id, seen);
            var also = await Update(id, [.. fields.Keys], f => { foreach (var (k, v) in fields) f[k] = v; });
            Fixed(id, what);
            foreach (var o in also) Fixed(o, L("{0} (as {1})", what, id), id);
            await Light();
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _note = e.Message; }
        finally { SetBusy(false); }
    }

    /// The bar runs the other way on the real rig: its `reverse` (where it hangs, on the rig) flipped.
    async void Reverse(string id)
    {
        _note = null;
        SetBusy(true);
        try
        {
            var also = await Update(id, ["reverse"], f =>
            {
                if (f.GetValueOrDefault("reverse")?.Bool ?? false) f.Remove("reverse"); else f["reverse"] = JSONValue.True;
            });
            Fixed(id, L("its cells the other way round"));
            foreach (var o in also) Fixed(o, L("{0} (as {1})", L("its cells the other way round"), id), id);
            await Light();
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _note = e.Message; }
        finally { SetBusy(false); }
    }

    /// `from`: put right as that one was (a sibling's fix).
    void Fixed(string id, string what, string? from = null)
    {
        if (!_fixed.TryGetValue(id, out var l)) _fixed[id] = l = [];
        l.Add(what);
        if (from is null) return;
        if (!_fixedAs.TryGetValue(id, out var s)) _fixedAs[id] = s = [];
        s.Add(from);
    }

    void SetBusy(bool busy)
    {
        _busy = busy;
        Body();
        Footer();
    }

    /// A change to one fixture, its `keys` then copied to the siblings of its model in the set that weren't said
    /// right or put right on their own yet (hung alike, they are wrong alike); saved at once (the engine splits it
    /// into the set and the rig). Returns the siblings it went to.
    async Task<List<string>> Update(string id, string[] keys, Action<Dictionary<string, JSONValue>> body)
    {
        var fixtures = SetLayout.Fixtures(_layout);
        if (fixtures.FirstOrDefault(f => Patch.Id(f) == id) is not { } f) return [];
        body(f);
        var model = f.GetValueOrDefault("fixture")?.String;
        var also = new List<string>();
        foreach (var o in fixtures)
        {
            if (ReferenceEquals(o, f) || o.GetValueOrDefault("fixture")?.String != model || _confirmed.Contains(Patch.Id(o))) continue;
            foreach (var k in keys)
                if (f.TryGetValue(k, out var v)) o[k] = v; else o.Remove(k);
            also.Add(Patch.Id(o));
        }
        var l = SetLayout.WithFixtures(_layout, fixtures);
        await _model.Api.SaveRig(l, _rig, _set);
        _layout = l;
        _confirmed.Add(id);
        await RefreshChecks();
        _model.ReloadSets();
        return also;
    }

    /// The siblings a fix of this one went to, listed (null: none).
    string? SiblingNote(string id)
    {
        var others = _target.Fixtures.Where(o => o != id && (_fixedAs.GetValueOrDefault(o)?.Contains(id) ?? false)).ToList();
        return others.Count == 0 ? null : string.Join(", ", others);
    }

    Dictionary<string, JSONValue>? Fixture(string id) => SetLayout.Fixtures(_layout).FirstOrDefault(f => Patch.Id(f) == id);

    bool Unplaced(string id) => Fixture(id)?.ContainsKey(RigDocument.UnplacedKey) ?? false;
}
