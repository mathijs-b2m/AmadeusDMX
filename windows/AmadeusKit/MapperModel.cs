// The DMX mapper's editing (mac/Sources/AmadeusDMX/Sets/MapperSheet.swift): a fixture mode channel by channel, each
// channel played (a role, optionally for one cell of a bar) or held at a value, and the values to try on the
// lights. FixtureMapping is immutable; this keeps the edited copy.
namespace AmadeusKit;

public sealed class MapperModel : Observable
{
    FixtureMapping? _mapping;
    public FixtureMapping? Mapping { get => _mapping; set => Set(ref _mapping, value); }

    /// Can it be edited here (a mode the mapper takes)?
    public bool Editable => Mapping is { Refusal.Length: 0 };

    public void SetKind(string kind)
    {
        if (Mapping is { } m) Mapping = m with { Kind = kind };
    }

    public void SetChannel(int index, Func<FixtureMapping.Channel, FixtureMapping.Channel> change)
    {
        if (Mapping is not { } m || index < 0 || index >= m.Channels.Count) return;
        var list = m.Channels.ToList();
        list[index] = change(list[index]);
        Mapping = m with { Channels = list };
    }

    public void SetRole(int index, string role) => SetChannel(index, c => c with { Role = role });
    public void SetCell(int index, int cell) => SetChannel(index, c => c with { Cell = Math.Clamp(cell, 0, 64) });
    public void SetValue(int index, int value) => SetChannel(index, c => c with { Value = Math.Clamp(value, 0, 255) });

    /// The kinds to choose from, by label; the fixture's own first when the list doesn't have it.
    public static IReadOnlyList<(string Kind, string Label)> KindChoices(FixtureMapping m)
    {
        var o = m.Kinds.OrderBy(p => p.Value, StringComparer.Ordinal).Select(p => (p.Key, p.Value)).ToList();
        if (!m.Kinds.ContainsKey(m.Kind)) o.Insert(0, (m.Kind, Formatting(m.Kind)));
        return o;
    }

    /// "moving_head" → "Moving Head"
    static string Formatting(string s) =>
        string.Join(' ', s.Replace('_', ' ').Split(' ').Select(w => w.Length == 0 ? w : char.ToUpperInvariant(w[0]) + w[1..].ToLowerInvariant()));

    /// The role groups, sorted, and their roles (the channel's picker).
    public static IReadOnlyList<(string Group, IReadOnlyList<FixtureMapping.Role> Roles)> Groups(FixtureMapping m) =>
        m.Roles.Select(r => r.Group).Distinct().Order(StringComparer.Ordinal)
            .Select(g => (g, (IReadOnlyList<FixtureMapping.Role>)m.Roles.Where(r => r.Group == g).ToList())).ToList();

    /// The values as they are, channel by channel (what "Try on the Lights" sends).
    public IReadOnlyList<int> Raw => Mapping?.Channels.Select(c => c.Value).ToList() ?? [];

    /// The channels given a light role: the engine keeps them under the brightness limiter.
    public IReadOnlyList<int> Light => Mapping?.LightChannels ?? [];

    // MARK: the check, channel by channel on the fixture

    /// Made from a common layout and not checked on the fixture yet.
    public bool NeedsCheck => Mapping is { Made: true, Checked: false };

    /// What the check found channel `index` does.
    public void Answer(FixtureMapping.Answer a, int index)
    {
        if (Mapping is { } m) Mapping = m.Answered(a, index);
    }

    /// The colour wheel's slots (`ring`: the ring's), as named in the check.
    public void SetWheel(IReadOnlyList<FixtureMapping.Slot> slots, bool ring = false)
    {
        if (Mapping is { } m) Mapping = ring ? m with { Ring = slots } : m with { Wheel = slots };
    }

    /// The colour wheel's slots, or the ring's.
    public IReadOnlyList<FixtureMapping.Slot> Slots(bool ring) => (ring ? Mapping?.Ring : Mapping?.Wheel) ?? [];

    /// Is channel `index` a ring's colours (ring_color) rather than a colour wheel's?
    public bool IsRing(int index) => Mapping is { } m && index >= 0 && index < m.Channels.Count && m.Channels[index].Role == "ring_color";

    /// The mapper's Colours…: the usual wheel (or ring) when it has none yet; the value to show first (the first
    /// colour's middle).
    public int OpenWheel(bool ring = false)
    {
        if (ring && Mapping is { Ring.Count: 0 } r) Mapping = r with { Ring = FixtureMapping.UsualRing };
        if (!ring && Mapping is { Wheel.Count: 0 } m) Mapping = m with { Wheel = FixtureMapping.UsualWheel };
        return Slots(ring).FirstOrDefault()?.Mid ?? 0;
    }

    public void SetSlot(int index, Func<FixtureMapping.Slot, FixtureMapping.Slot> change, bool ring = false)
    {
        var slots = Slots(ring);
        if (Mapping is null || index < 0 || index >= slots.Count) return;
        var list = slots.ToList();
        list[index] = change(list[index]);
        SetWheel(list, ring);
    }
}
