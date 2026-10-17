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
    Action<string, string> rename)
{
    readonly Patch _patch = new(fixtures, Patch.ChannelsFrom(definition));

    public FrameworkElement Build()
    {
        var sel = _patch.Selected(ids);
        var sections = sel.Count == 1 ? Single(sel[0]) : sel.Count > 1 ? Several(sel) : [];
        return Form.Page(520, [.. sections]);
    }

    static string Str(IReadOnlyDictionary<string, JSONValue> f, string k) => Patch.Str(f, k);

    void Set(string what, string id, Action<Dictionary<string, JSONValue>> body) =>
        apply(what, all => SetLayout.Change(all, id, body));

    static IReadOnlyList<string> Modes(FixtureDefinition? d) => d?.Modes.Keys.Order(StringComparer.Ordinal).ToList() ?? [];

    // MARK: one fixture

    List<UIElement?> Single(IReadOnlyDictionary<string, JSONValue> f)
    {
        string id = Patch.Id(f), key = Patch.Key(f);
        var def = definition(key);
        int u = Patch.Universe(f), a = Patch.Address(f), n = _patch.Footprint(f);
        var none = new HashSet<string> { id };

        var name = Form.Submit("Name", id, v => { if (v.Length > 0 && v != id) rename(id, v); })
            .Tooltip("The fixture's name in the set (renaming keeps where it hangs on your rigs). Press Enter to rename.");
        var mode = UI.Picker(Modes(def), Patch.Mode(f), m => $"{m} · {def?.ChannelCount(m) ?? 0} ch",
                             m => Set("Change Mode", id, x => x["mode"] = m));
        var address = Form.Submit("Start address", a.ToString(), v =>
        {
            if (int.TryParse(v, out var x) && x is >= 1 and <= Patch.UniverseSize) Set("Change Address", id, y => y["address"] = x);
        });
        address.LostFocus += (_, _) => { if (!int.TryParse(address.Text, out var x) || x is < 1 or > Patch.UniverseSize) address.Text = a.ToString(); };
        var nextFree = UI.Button("Next Free", () =>
        {
            if (_patch.Free(u, n, none) is { } v)
            {
                address.Text = v.ToString();
                Set("Change Address", id, x => x["address"] = v);
            }
        }).Tooltip($"The first address in this universe where its {n} channels fit");

        var patch = new List<UIElement?>
        {
            Form.Stepper(u, 1, 64, v => $"Universe {v}", v => Set("Change Universe", id, x => x["universe"] = v)),
            Form.Row(address.Grow(), nextFree),
            Form.Row("Channels", UI.Text($"{Patch.Where(u, a)} – {Patch.Where(u, a + n - 1)}").Secondary()),
        };
        if (Patch.Overflow(a, n) is > 0 and var over)
            patch.Add(Form.Note("exclamationmark.triangle.fill", $"It doesn't fit in the universe: {over} channels past 512.", Tint.Orange));
        var c = _patch.Clashes(u, a, n, none);
        if (c.Count > 0) patch.Add(Form.Note("exclamationmark.triangle.fill", $"Overlaps {string.Join(", ", c)}", Tint.Orange));

        var sections = new List<UIElement?>
        {
            Form.Section(def?.Name ?? key, [Form.Row("Name", name.MinWidth(180)), Form.Row("DMX mode", mode)]),
            Form.Section("DMX patch", patch),
        };
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
