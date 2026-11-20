// Calibrate: the fixtures of one model put right on the real rig when they behave oddly (a head that goes the
// wrong way, a bar that runs backwards), by going through one of them: the others of the model get the same
// calibration. It stays with the fixture it was opened on (another one is chosen at the top, for one that behaves
// differently). First whether the head hangs or stands; then it is lit as it is placed on the rig: straight out to
// the audience, then the check after hanging's way (does it pan the right way round?), each with a picture of the
// head and where its beam should go; a bar's cells red, green, blue, white along it (reversed?). A head that
// doesn't do as its picture gets another calibration at a press (its pan home a quarter on, its pan the other
// way), until it does. Every press puts the fixture right at once (its calibration in the set, its placing on the
// rig) and lights it again to see (mac/Sources/AmadeusDMX/Sets/CalibrateSheet.swift).
namespace AmadeusDMX;

/// `Fixtures`: in the set's order; `Start`: the one to begin with.
public sealed record CalibrateTarget(string Key, string Name, IReadOnlyList<string> Fixtures, int Start = 0);

public sealed class CalibrateSheet
{
    enum Step { Mount, Front, Check, Cells }

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
    // what was put right, per fixture and step (`From`: put right as that one was, a sibling's fix)
    readonly Dictionary<string, Dictionary<Step, (string What, string? From)>> _fixed = [];
    Beam? _beam;                 // where the lit head's beam should go
    // the calibrations a head is tried with in this step, a press at a time: [0] the one it came with (nothing changed)
    List<Dictionary<string, JSONValue>> _ways = [];
    List<string> _wayNames = [];
    Dictionary<string, JSONValue> _wayBase = [];   // the fixture as it came
    int _way;
    bool _finished;                  // this fixture is through its steps
    List<string> _followers = [];    // the others of the model its calibration went to

    /// What a head's calibration is made of: copied to the others of its model when it is through.
    static readonly string[] Calibration = ["pan_home_deg", "pan_invert", "tilt_invert"];
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
        var grid = new Grid { MinWidth = 600, Height = 620 };
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
        _ = KeepLit();
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
                _target.Fixtures.Count > 1 && Id is { } now
                    ? UI.Picker(_target.Fixtures, now, f => f, f => { if (!_busy) Go(_target.Fixtures.ToList().IndexOf(f)); else Header(); })
                        .Tooltip(L("The fixture you go through. One is enough: the others of this model get its calibration. Choose another one only when it behaves differently"))
                    : null),
            UI.Text(L("Go through one fixture of this model: the others get the same calibration. Stand where the audience would be, facing the stage. It lights as it is placed on {0}, with a picture of what it should do. When the real one does something else, press until it matches.", _rig),
                    Font.Callout).Secondary().Wrap(),
            UI.Text(HangCheckPanel.Sides, Font.Callout).Secondary().Wrap()
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
        else if (_finished)
            foreach (var part in FinishedView(id)) panel.Children.Add(part);
        else if (_step is { } step)
            foreach (var part in StepView(id, step)) panel.Children.Add(part);
        if (_fixed.TryGetValue(id, out var done) && done.Count > 0)
        {
            var said = string.Join(", ", done.OrderBy(kv => kv.Key).Select(kv => kv.Value.What));
            panel.Children.Add(Form.Note("checkmark.circle.fill", SiblingNote(id) is { } others
                ? L("Put right: {0}. Saved, and for {1} too.", said, others)
                : L("Put right: {0}. Saved.", said), Tint.Green));
        }
        if (_note is { } n) panel.Children.Add(UI.Text(n, Font.Callout).Foreground(Tint.Orange).Wrap());
        if (_output.Length > 0) panel.Children.Add(UI.Text(_output, Font.Caption).Secondary().Lines(1));
        panel.Alignment = 0;
        _body.Content = UI.Scroll(panel.Padding(0, 12));
    }

    IEnumerable<UIElement> StepView(string id, Step step)
    {
        switch (step)
        {
            case Step.Mount:
                var hangs = Hangs(id);
                yield return Form.Note("questionmark.circle", L("How is the real {0} mounted?", id), null, Font.Callout).Bold();
                var answers = UI.HStack(12, MountButton(id, true, hangs), MountButton(id, false, !hangs));
                answers.HorizontalAlignment = HorizontalAlignment.Left;
                yield return answers;
                yield return UI.Text(hangs ? L("On {0} it is placed hanging. The pictures that follow show it the way you say here.", _rig)
                                           : L("On {0} it is placed standing. The pictures that follow show it the way you say here.", _rig),
                                     Font.Caption).Secondary().Wrap();
                break;
            case Step.Front:
                yield return Form.Note("light.beacon.max",
                    L("Its beam should point straight out at the audience, as in the picture. Only the direction counts: level, or a little up or down, is all fine."),
                    null, Font.Callout).Bold();
                foreach (var part in MatchView(id)) yield return part;
                break;
            case Step.Check:
                var c = _checks.GetValueOrDefault(id);
                yield return Form.Note("light.beacon.max",
                    c is { Expect.Length: > 0 } ? L("{0}, as in the picture.", c.Expect.TrimEnd('.')) : L("Its beam points to one side, as in the picture."),
                    null, Font.Callout).Bold();
                yield return UI.Text(L("This catches a head that pans the other way: pointing straight out, that looks right."), Font.Caption).Secondary().Wrap();
                foreach (var part in MatchView(id)) yield return part;
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

    /// The picture of where the beam should go, and the two answers: it does, or try the next calibration.
    IEnumerable<UIElement> MatchView(string id)
    {
        if (_beam is { } beam) yield return BeamPicture.Build(beam);
        var row = Buttons(
            UI.Button(L("Like the Picture"), Advance, "checkmark").Prominent(),
            UI.Button(L("Not Like It: Try Another Way"), () => TryNext(id), "arrow.triangle.2.circlepath")
                .Tooltip(L("The head is tried another way round (its pan home a quarter on, its pan the other way). Press until the real beam goes where the picture’s does")));
        if (_ways.Count > 1) row.Children.Add(UI.Text(L("Way {0} of {1}", _way + 1, _ways.Count), Font.Callout).Secondary());
        yield return row;
        yield return UI.Text(L("Nothing lights up or moves? Then {0} is not connected, or its address is not {1}.", id,
                               _checks.GetValueOrDefault(id)?.Dmx ?? L("the one in the set")), Font.Caption).Secondary().Wrap();
    }

    bool Hangs(string id) => Fixture(id)?.GetValueOrDefault("mount")?.String == "hang";

    /// One of the two answers to how the head is mounted: a drawing of it, the way it is placed on the rig marked.
    Button MountButton(string id, bool hanging, bool placed)
    {
        var stack = UI.VStack(4,
            BeamPicture.Icon(hanging),
            UI.Text(hanging ? L("Hanging") : L("Standing"), Font.Headline),
            UI.Text(hanging ? L("Under a truss or a bar") : L("On the floor, or on top of something"), Font.Caption).Secondary(),
            UI.Text(placed ? L("As placed on {0}", _rig) : " ", Font.Caption2).Foreground(Tint.Accent));
        var b = new Button { Content = stack, Width = 230, Padding = new Thickness(10), HorizontalContentAlignment = HorizontalAlignment.Center };
        if (placed)
        {
            b.BorderBrush = Tint.Brush(Tint.Accent);
            b.BorderThickness = new Thickness(2);
        }
        b.Click += (_, _) => { if (placed) Advance(); else SetMount(id, hanging); };
        return b.Disabled(_busy);
    }

    /// The fixture is through: what was done, and what happens to the others of its model.
    IEnumerable<UIElement> FinishedView(string id)
    {
        var title = UI.Label("checkmark.seal.fill", L("{0} is calibrated.", id), Font.Title3).Foreground(Tint.Green);
        yield return title;
        if (_followers.Count > 0)
        {
            yield return UI.Text(L("The other {0} of this model use the same calibration now: {1}. Mounted the same way round, they are right too; there is no need to go through them.",
                                   _followers.Count, string.Join(", ", _followers)), Font.Callout).Wrap();
            yield return UI.Text(L("One of them does behave differently? Choose it at the top right and go through it on its own."), Font.Callout).Secondary().Wrap();
        }
        yield return UI.Text(L("Colours, gobos or a prism that come out wrong are not put right here: that is Check Channels, on the Sets page."),
                             Font.Callout).Secondary().Wrap();
        yield return Buttons(UI.Button(L("Done"), () => _dialog.Hide()).Prominent());
    }

    FlowPanel Buttons(params Button[] buttons)
    {
        var row = new FlowPanel { Spacing = 8, LineSpacing = 8 };
        foreach (var b in buttons) row.Children.Add(b.Disabled(_busy));
        return row;
    }


    void Footer()
    {
        _footer.Content = UI.HStack(8,
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
            // hanging or standing is asked of a head on the floor, under or on top of a truss (not one on a truss's side)
            if ((f.GetValueOrDefault("truss_side")?.String ?? "under") is "under" or "top") out_.Add(Step.Mount);
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
        _ways = [];
        _way = 0;
        var all = Steps(id);
        if (_step is { } s && all.IndexOf(s) is var i and >= 0 && i + 1 < all.Count)
        {
            _step = all[i + 1];
            Render();
            _ = Light();
        }
        else Finish(id);
    }

    /// The fixture is through its steps: its calibration goes to the others of its model (those not gone through on
    /// their own), and the sheet stays with it.
    async void Finish(string id)
    {
        SetBusy(true);
        try
        {
            _followers = _definition is { IsMoving: true } ? await Update(id, Calibration, _ => { }) : [];
            _confirmed.Add(id);
            SwitchOff();
            _beam = null;
            _finished = true;
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _note = e.Message; }
        finally { SetBusy(false); }
    }

    /// The real head is mounted the other way than it is placed on the rig: its placing put right (under or on top
    /// of its truss), this one only.
    async void SetMount(string id, bool hanging)
    {
        _note = null;
        SetBusy(true);
        var done = false;
        try
        {
            await Update(id, [], f =>
            {
                f["mount"] = JSONValue.Of(hanging ? "hang" : "stand");
                if (!f.ContainsKey("truss")) return;
                f["truss_side"] = JSONValue.Of(hanging ? "under" : "top");
                f.Remove("mount_roll_deg");
            });
            Fixed(id, Step.Mount, hanging ? L("it hangs") : L("it stands"));
            done = true;
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _note = e.Message; }
        finally { SetBusy(false); }
        if (done) Advance();
    }

    void Go(int i)
    {
        if (i < 0 || i >= _target.Fixtures.Count) return;
        _index = i;
        _note = null;
        _ways = [];
        _way = 0;
        _finished = false;
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
        if (_step is not { } step || Unplaced(id)) { _output = ""; _beam = null; Body(); return; }
        try
        {
            var r = await _model.Api.TestLight(id, true, _layout,
                                               step == Step.Front ? "front" : step == Step.Check ? "check" : null,
                                               step == Step.Cells);
            _lit = id;
            _output = r.Summary;
            _order = r.Order;
            _beam = step is Step.Front or Step.Check && r is { Dir: { } d, Pos: { } p, Stage: { } st } ? new Beam(p, d, st, Hangs(id)) : null;
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _output = e.Message; _beam = null; }
        if (_closed) { SwitchOff(); return; }
        Body();
    }

    /// The engine's light test goes dark after a minute: kept lit for as long as it is looked at.
    async Task KeepLit()
    {
        while (!_closed)
        {
            await Task.Delay(TimeSpan.FromSeconds(20));
            if (_closed || _busy || _lit is not { } id) continue;
            try
            {
                if (!await _model.Api.KeepLight(id) && !_closed && !_busy && _lit == id) await Light();
            }
            catch (Exception e) when (SetView.IsApiError(e)) { }
        }
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

    /// The real head doesn't do as its picture: the next calibration it could have, saved, and lit again to see.
    /// Straight out: its pan home a quarter on, a press at a time (the rig editor's front test's fixes); the check's
    /// way: the hang check's faults. Round again, it is back as it came.
    async void TryNext(string id)
    {
        if (_step is not { } step || Fixture(id) is not { } fixture) return;
        _note = null;
        SetBusy(true);
        try
        {
            if (_ways.Count == 0)
            {
                (string Fix, string Name)[] options = step == Step.Front
                    ? [("left", L("its pan home turned")), ("back", L("turned round")), ("right", L("its pan home turned"))]
                    : [.. (_checks.GetValueOrDefault(id)?.Faults ?? []).Select(f => (f.Fix, HangCheckPanel.Cause.GetValueOrDefault(f.Fix) ?? f.Fix))];
                var found = new List<Dictionary<string, JSONValue>> { new() };
                var names = new List<string> { "" };
                foreach (var (fix, name) in options)
                {
                    Dictionary<string, JSONValue> fields;
                    try { fields = await _model.Api.HangCheckFix(_layout, id, fix); }
                    catch (Exception e) when (SetView.IsApiError(e)) { continue; }   // no calibration points that way
                    if (fields.Count == 0 || found.Any(o => Same(o, fields))) continue;
                    found.Add(fields);
                    names.Add(name);
                }
                if (found.Count < 2)
                {
                    _note = L("There is no other way to try this head. If it doesn’t do as the picture, it is placed differently here than it really hangs or stands: put that right on the Rigs page.");
                    return;
                }
                _ways = found;
                _wayNames = names;
                _wayBase = new(fixture);
                _way = 0;
            }
            var next = (_way + 1) % _ways.Count;
            string[] keys = [.. _ways.SelectMany(o => o.Keys).Distinct()];
            Dictionary<string, JSONValue> to = _ways[next], from = _wayBase;
            var also = await Update(id, keys, f =>
            {
                foreach (var k in keys)
                    if (to.TryGetValue(k, out var v) || from.TryGetValue(k, out v)) f[k] = v; else f.Remove(k);
            });
            _way = next;
            Fixed(id, step, next == 0 ? null : _wayNames[next]);
            foreach (var o in also) Fixed(o, step, next == 0 ? null : L("{0} (as {1})", _wayNames[next], id), id);
            if (next == 0)
                _note = L("That was every way, and it is back as it came. If none looked like the picture, it is placed differently here than it really hangs or stands (hanging or standing, or on another side of the truss): put that right on the Rigs page. Or its mode or address is off: see Check Channels.");
            await Light();
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _note = e.Message; }
        finally { SetBusy(false); }
    }

    static bool Same(Dictionary<string, JSONValue> a, Dictionary<string, JSONValue> b) =>
        a.Count == b.Count && a.All(kv => b.TryGetValue(kv.Key, out var v) && kv.Value.Equals(v));

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
            var was = _fixed.GetValueOrDefault(id)?.ContainsKey(Step.Cells) ?? false;   // pressed again: back as it came
            Fixed(id, Step.Cells, was ? null : L("its cells the other way round"));
            foreach (var o in also) Fixed(o, Step.Cells, was ? null : L("{0} (as {1})", L("its cells the other way round"), id), id);
            await Light();
        }
        catch (Exception e) when (SetView.IsApiError(e)) { _note = e.Message; }
        finally { SetBusy(false); }
    }

    /// What a step put right (null: nothing after all, it is back as it came); `from`: as that one was (a sibling's fix).
    void Fixed(string id, Step step, string? what, string? from = null)
    {
        if (!_fixed.TryGetValue(id, out var steps)) _fixed[id] = steps = [];
        if (what is null) steps.Remove(step); else steps[step] = (what, from);
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
        var others = _target.Fixtures.Where(o => o != id && (_fixed.GetValueOrDefault(o)?.Values.Any(v => v.From == id) ?? false)).ToList();
        return others.Count == 0 ? null : string.Join(", ", others);
    }

    Dictionary<string, JSONValue>? Fixture(string id) => SetLayout.Fixtures(_layout).FirstOrDefault(f => Patch.Id(f) == id);

    bool Unplaced(string id) => Fixture(id)?.ContainsKey(RigDocument.UnplacedKey) ?? false;
}
