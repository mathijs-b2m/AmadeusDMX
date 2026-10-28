// The selected fixtures of a set: name, DMX mode, universe and start address (checked against the 512 channels and
// the other fixtures), and for moving heads the direction of pan and tilt. With several selected: one mode or
// universe for all of them, or patch them one after another (mac/Sources/AmadeusDMX/Sets/PatchInspector.swift).
// The arithmetic is the kit's Patch.
namespace AmadeusDMX;

public sealed class PatchInspector(
    IReadOnlySet<string> ids,
    IReadOnlyList<Dictionary<string, JSONValue>> fixtures,   // the set's fixtures, as in its file
    Func<string, FixtureDefinition?> definition,
    /// Change the set's fixtures (the action gets them to change); saved at once.
    Action<string, Action<List<Dictionary<string, JSONValue>>>> apply,
    Action<string, string> rename,
    PatchInspector.Typing typing,
    /// Saves a fixture's lens (key, beam angle, widest, lumens): the problems; then the definition is read again.
    Func<string, double, double?, double?, Task<IReadOnlyList<string>>>? saveLens = null)
{
    readonly Patch _patch = new(fixtures, Patch.ChannelsFrom(definition));
    readonly string _key = string.Join("\n", ids.Order(StringComparer.Ordinal));
    TextBox? _name, _address;

    /// What is typed in the name and address fields (SwiftUI's @State): the page keeps it, as the inspector is made
    /// again after every change. What is typed there is saved on Enter, on leaving the field or on Save.
    public sealed class Typing
    {
        internal string? For;               // the selection it was synced for (the ids)
        internal PatchInspector? Owner;     // the inspector showing it (an old one, still losing focus, saves nothing)
        internal string Name = "", Address = "";
        internal string? Focus;             // "name" | "address": the field being edited, focused again when made again
        internal string Sent = "";          // the last change sent ("id:address" or "id>name"): sent once, not on every blur

        /// Another set: nothing typed is kept, and no inspector saves any more.
        public void Forget() { For = null; Owner = null; Focus = null; }
    }

    public FrameworkElement Build()
    {
        var sel = _patch.Selected(ids);
        typing.Owner = this;
        if (typing.For != _key) Sync(sel);
        var sections = sel.Count == 1 ? Single(sel[0]) : sel.Count > 1 ? Several(sel) : [];
        return Form.Page(520, [.. sections]);
    }

    static string Str(IReadOnlyDictionary<string, JSONValue> f, string k) => Patch.Str(f, k);

    void Set(string what, string id, Action<Dictionary<string, JSONValue>> body) =>
        apply(what, all => SetLayout.Change(all, id, body));

    static IReadOnlyList<string> Modes(FixtureDefinition? d) => d?.Modes.Keys.Order(StringComparer.Ordinal).ToList() ?? [];

    /// Another fixture picked: its name and address in the fields.
    void Sync(IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> sel)
    {
        typing.For = _key;
        typing.Focus = null;
        if (sel.Count != 1) return;
        typing.Name = Patch.Id(sel[0]);
        typing.Address = Patch.Address(sel[0])?.ToString() ?? "";
    }

    /// What is typed in the name and address fields, saved (for the one fixture `ids` holds). The page calls it
    /// too when another fixture is picked: what was typed is kept.
    public void Commit()
    {
        if (typing.Owner != this || ids.Count != 1 || fixtures.FirstOrDefault(x => Patch.Id(x) == ids.First()) is not { } f) return;
        var id = Patch.Id(f);
        var a = Patch.Address(f);
        var typed = typing.Address.Trim();
        if (typed.Length == 0 && a is not null && typing.Sent != $"{id}:-")  // cleared: no start address (until given one)
        {
            typing.Sent = $"{id}:-";
            Set("Clear Address", id, x => x.Remove("address"));
        }
        else if (int.TryParse(typed, out var v) && v != a && typing.Sent != $"{id}:{v}")
        {
            if (v is >= 1 and <= Patch.UniverseSize)
            {
                typing.Sent = $"{id}:{v}";
                Set("Change Address", id, x => x["address"] = v);
            }
            else SetAddress(a?.ToString() ?? "");
        }
        var name = typing.Name.Trim();
        if (name.Length == 0) SetName(id);
        else if (name != id && typing.Sent != $"{id}>{name}") { typing.Sent = $"{id}>{name}"; rename(id, name); }
    }

    void SetName(string v) { typing.Name = v; if (_name is { } t) t.Text = v; }
    void SetAddress(string v) { typing.Address = v; if (_address is { } t) t.Text = v; }

    /// A field whose text is kept in `typing`, saved on Enter and when it loses focus, focused again when the
    /// inspector is made again while it was being edited.
    TextBox Field(string which, string text, string placeholder, Action<string> typed)
    {
        var t = new TextBox { Text = text, PlaceholderText = placeholder, MinWidth = 0 };
        t.TextChanged += (_, _) => typed(t.Text);
        t.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) { Commit(); e.Handled = true; } };
        t.GotFocus += (_, _) => { if (typing.Owner == this) typing.Focus = which; };
        t.LostFocus += (_, _) =>
        {
            if (typing.Owner != this) return;
            if (typing.Focus == which) typing.Focus = null;
            Commit();
        };
        if (typing.Focus == which)
            t.Loaded += (_, _) => { t.Focus(FocusState.Programmatic); t.SelectionStart = t.Text.Length; };
        return t;
    }

    /// A button that leaves the focus in the field (else leaving it would save before the button acts).
    static Button Keep(Button b) { b.AllowFocusOnInteraction = false; return b; }

    // MARK: one fixture

    List<UIElement?> Single(IReadOnlyDictionary<string, JSONValue> f)
    {
        string id = Patch.Id(f), key = Patch.Key(f);
        var def = definition(key);
        int u = Patch.Universe(f), n = _patch.Footprint(f);
        var a = Patch.Address(f);
        var none = new HashSet<string> { id };

        var renameButton = Keep(UI.Button("Rename", () => { typing.Sent = ""; Commit(); }).Prominent());
        void Renamed() => renameButton.Visible(typing.Name != id);
        _name = Field("name", typing.Name, "Name", v => { typing.Name = v; Renamed(); });
        _name.Tooltip("The fixture's name in the set (renaming keeps where it hangs on your rigs). Saved on Enter or when you leave the field.");
        Renamed();
        var mode = UI.Picker(Modes(def), Patch.Mode(f), m => $"{m} · {def?.ChannelCount(m) ?? 0} ch",
                             m => Set("Change Mode", id, x => x["mode"] = m));

        var buttons = new ContentControl { IsTabStop = false };
        var checks = new ContentControl { IsTabStop = false, HorizontalContentAlignment = HorizontalAlignment.Stretch };
        void Typed()
        {
            var text = typing.Address.Trim();
            int? typed = int.TryParse(text, out var t) && t is >= 1 and <= Patch.UniverseSize ? t : null;
            var edited = text.Length == 0 ? a is not null : typed is not null && typed != a;
            buttons.Content = edited
                ? UI.HStack(8,
                    Keep(UI.Button("Save", () => { typing.Sent = ""; Commit(); }).Prominent()),
                    Keep(UI.Button("Revert", () => SetAddress(a?.ToString() ?? ""))))
                : Keep(UI.Button("Next Free", () =>
                {
                    if (_patch.Free(u, n, none) is { } v)
                    {
                        SetAddress(v.ToString());
                        Set("Change Address", id, x => x["address"] = v);
                    }
                })).Tooltip($"The first address in this universe where its {n} channels fit");

            var rows = UI.VStack(8);
            if (int.TryParse(typing.Address, out _) && typed is null)
                rows.Children.Add(Form.Note("exclamationmark.triangle.fill", "A start address is 1 to 512.", Tint.Orange));
            if ((text.Length == 0 ? null : typed ?? a) is { } shown)  // what is typed, checked before it is saved
            {
                rows.Children.Add(Form.Row("Channels", UI.Text($"{Patch.Where(u, shown)} – {Patch.Where(u, shown + n - 1)}"
                                                               + (shown != a ? " (not saved yet)" : "")).Secondary()));
                if (Patch.Overflow(shown, n) is > 0 and var over)
                    rows.Children.Add(Form.Note("exclamationmark.triangle.fill", $"It doesn't fit in the universe: {over} channels past 512.", Tint.Orange));
                var c = _patch.Clashes(u, shown, n, none);
                if (c.Count > 0)
                    rows.Children.Add(Form.Note("exclamationmark.triangle.fill",
                        $"Overlaps {string.Join(", ", c)}. It is saved anyway, so you can move the others next.", Tint.Orange));
            }
            else
                rows.Children.Add(Form.Note("info.circle",
                    "No start address yet: it plays in the visualiser only until it has one. Type the address set on the fixture, or Next Free."));
            checks.Content = rows;
        }
        _address = Field("address", typing.Address, "not set", v => { typing.Address = v; Typed(); });
        _address.Width = 90;
        _address.Tooltip("The address set on the fixture itself. Saved on Enter, when you leave the field, or with Save; empty: none yet");
        Typed();

        var patch = new List<UIElement?>
        {
            Form.Stepper(u, 1, 64, v => $"Universe {v}", v => Set("Change Universe", id, x => x["universe"] = v)),
            Form.Row("Start address", UI.HStack(8, _address, buttons)),
            checks,
        };

        var sections = new List<UIElement?>
        {
            Form.Section(def?.Name ?? key, [Form.Row("Name", UI.HStack(8, _name.MinWidth(180), renameButton)), Form.Row("DMX mode", mode)]),
            Form.Section("DMX patch", patch),
        };
        if (def is not null && saveLens is not null && def.ElementKind is not (FixtureKind.Smoke or FixtureKind.Laser))
            sections.Add(LensSection(key, def, saveLens));
        if (def?.IsMoving == true)
            sections.Add(Form.Section("Motion",
            [
                Form.Row("Invert pan", UI.Toggle("", f.GetValueOrDefault("pan_invert")?.Bool ?? false,
                    v => Set("Invert Pan", id, x => { if (v) x["pan_invert"] = true; else x.Remove("pan_invert"); }))),
                Form.Row("Invert tilt", UI.Toggle("", f.GetValueOrDefault("tilt_invert")?.Bool ?? false,
                    v => Set("Invert Tilt", id, x => { if (v) x["tilt_invert"] = true; else x.Remove("tilt_invert"); }))),
            ]));
        return sections;
    }

    /// A fixture's lens and light as its manual gives them (POST /api/fixture/lens): the beam angle (with a zoom: its
    /// tightest and widest) and the lumens. The show's zoom and the visualisers' beams follow them; every fixture of
    /// this model in your sets changes with it (Swift: LensSection).
    static FrameworkElement LensSection(string key, FixtureDefinition def, Func<string, double, double?, double?, Task<IReadOnlyList<string>>> save)
    {
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        var zoom = def.Modes.Values.Any(m => m.Any(c => c.GetValueOrDefault("attr")?.String == "zoom"));
        string Num(double? v) => v is { } x && x > 0 ? x.ToString("0.#", inv) : "";
        double? Parse(TextBox t) => double.TryParse(t.Text.Trim(), System.Globalization.NumberStyles.Float, inv, out var v) && v > 0 ? v : null;
        var beam = new TextBox { Text = Num(def.Physical?.BeamDeg ?? 25), Width = 90 };
        beam.Tooltip("The manual's beam angle: where the light is half the centre's (not the wider field angle)");
        var wide = new TextBox { Text = Num(def.Physical?.BeamDegMax), PlaceholderText = "no zoom range", Width = 120 };
        wide.Tooltip("How wide the zoom opens: the manual gives it as e.g. 4°–40°");
        var lumens = new TextBox { Text = Num(def.Physical?.Lumens), PlaceholderText = "unknown", Width = 120 };
        lumens.Tooltip("Lumens from the manual: the visualiser draws the beam as bright as its light over its width");
        var problems = UI.VStack(6);
        var saving = false;
        var saveButton = UI.Button("Save", async () =>
        {
            if (saving) return;
            if (Parse(beam) is not { } b) { problems.Children.Clear(); problems.Children.Add(Form.Note("exclamationmark.triangle.fill", "Give the beam angle in degrees.", Tint.Orange)); return; }
            saving = true;
            try
            {
                var found = await save(key, b, zoom ? Parse(wide) : null, Parse(lumens));
                problems.Children.Clear();
                foreach (var p in found) problems.Children.Add(Form.Note("exclamationmark.triangle.fill", p, Tint.Orange));
            }
            catch (Exception e) { problems.Children.Clear(); problems.Children.Add(Form.Note("exclamationmark.triangle.fill", e.Message, Tint.Orange)); }
            finally { saving = false; }
        }).Prominent();
        return Form.Section("Lens",
        [
            Form.Row(zoom ? "Beam angle, tightest (°)" : "Beam angle (°)", beam),
            zoom ? Form.Row("Beam angle, widest (°)", wide) : null,
            Form.Row("Light output (lm)", lumens),
            saveButton,
            problems,
        ], $"For every {def.Name} in your sets. The visualiser draws its beam this wide, as bright as its light allows, dimmer the further it throws.");
    }

    // MARK: several

    List<UIElement?> Several(IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> sel)
    {
        var keys = sel.Select(Patch.Key).ToHashSet();
        var selIds = sel.Select(Patch.Id).ToList();
        var universes = sel.Select(Patch.Universe).ToHashSet();
        var rows = new List<UIElement?>();
        if (keys.Count == 1 && definition(keys.First()) is { } def)
        {
            var modes = sel.Select(Patch.Mode).ToHashSet();
            var choices = new List<string>();
            if (modes.Count > 1) choices.Add("");
            choices.AddRange(Modes(def));
            rows.Add(Form.Row("DMX mode", UI.Picker(choices, modes.Count == 1 ? modes.First() : "",
                m => m.Length == 0 ? "Mixed" : $"{m} · {def.ChannelCount(m)} ch",
                m =>
                {
                    if (m.Length == 0) return;
                    apply("Change Modes", all => { foreach (var id in selIds) SetLayout.Change(all, id, x => x["mode"] = m); });
                })));
        }
        rows.Add(Form.Stepper(universes.Min(), 1, 64, v => universes.Count == 1 ? $"Universe {v}" : "Universe (mixed)",
            v => apply("Change Universe", all => { foreach (var id in selIds) SetLayout.Change(all, id, x => x["universe"] = v); })));

        var from = new TextBox { PlaceholderText = "From address", Text = "1", MinWidth = 120 };
        var inRow = UI.Button("Patch in a Row", () => PatchInRow(sel, int.TryParse(from.Text, out var x) ? x : 1));
        return
        [
            Form.Section($"{sel.Count} fixtures", rows),
            Form.Section("Addresses", [Form.Row(from.Grow(), inRow)],
                "One after another from that address (in the order shown), in their universe, around the other fixtures; a fixture that doesn't fit goes on in the next universe."),
        ];
    }

    void PatchInRow(IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> sel, int start)
    {
        var placed = _patch.InRow(sel, start);
        apply("Patch in a Row", all =>
        {
            foreach (var (id, p) in placed)
                SetLayout.Change(all, id, x => { x["universe"] = p.Universe; x["address"] = p.Address; });
        });
    }
}
