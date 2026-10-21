// A set's DMX patch, the arithmetic the Set page does (mac/Sources/AmadeusDMX/Sets/PatchInspector.swift and
// AddToSetSheet.swift): a fixture's footprint, which fixtures overlap a range of channels, the first free start
// address in a universe, patching several fixtures one after another, names for new fixtures. Every universe has
// 512 channels. Fixtures are as in the set file ({"id", "fixture", "mode", "universe", "address", …}); one without
// an "address" has no start address yet (it plays in the visualiser only until you give it one) and overlaps nothing.
namespace AmadeusKit;

public sealed class Patch
{
    public const int UniverseSize = 512;

    readonly IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> _fixtures;
    readonly Func<string, string, int> _channels;

    /// `channels(key, mode)`: how many DMX channels that mode of that fixture takes (0: unknown, counted as 1).
    public Patch(IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> fixtures, Func<string, string, int> channels)
    {
        _fixtures = fixtures;
        _channels = channels;
    }

    /// With a workspace's definitions (yours win over the shipped library).
    public static Func<string, string, int> ChannelsFrom(Func<string, FixtureDefinition?> definition) =>
        (key, mode) => definition(key)?.ChannelCount(mode) ?? 0;

    // MARK: a fixture's fields

    public static string Id(IReadOnlyDictionary<string, JSONValue> f) => Str(f, "id");
    public static string Key(IReadOnlyDictionary<string, JSONValue> f) => Str(f, "fixture");
    public static string Mode(IReadOnlyDictionary<string, JSONValue> f) => Str(f, "mode");
    public static int Universe(IReadOnlyDictionary<string, JSONValue> f) => Int(f, "universe", 1);
    /// The start address, null when it has none yet (added fixtures wait for you to give them one).
    public static int? Address(IReadOnlyDictionary<string, JSONValue> f) => f.GetValueOrDefault("address")?.Number is { } n ? (int)n : null;

    public static string Str(IReadOnlyDictionary<string, JSONValue> f, string k) => f.GetValueOrDefault(k)?.String ?? "";
    public static int Int(IReadOnlyDictionary<string, JSONValue> f, string k, int d) =>
        f.GetValueOrDefault(k)?.Number is { } n ? (int)n : d;

    /// "1.043": universe and start address, as set on the fixture's display.
    public static string Where(int universe, int address) => $"{universe}.{address:000}";

    /// How many DMX channels a fixture takes.
    public int Footprint(IReadOnlyDictionary<string, JSONValue> f) => Math.Max(1, _channels(Key(f), Mode(f)));

    /// The selected fixtures in patch order (universe, then address; those without one last).
    public IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> Selected(IReadOnlySet<string> ids) =>
        _fixtures.Where(f => ids.Contains(Id(f))).OrderBy(Universe).ThenBy(f => Address(f) ?? UniverseSize + 1).ToList();

    /// The fixtures (by id) whose channels overlap `count` channels from `from`, in a universe.
    public IReadOnlyList<string> Clashes(int universe, int from, int count, IReadOnlySet<string> except) =>
        _fixtures.Where(f =>
        {
            if (except.Contains(Id(f)) || Universe(f) != universe || Address(f) is not { } b) return false;
            return b <= from + count - 1 && from <= b + Footprint(f) - 1;
        }).Select(Id).ToList();

    /// The first start address in a universe where `count` channels fit (nil: nowhere).
    public int? Free(int universe, int count, IReadOnlySet<string> except, int from = 1)
    {
        for (var a = Math.Max(1, from); a + count - 1 <= UniverseSize; a++)
            if (Clashes(universe, a, count, except).Count == 0) return a;
        return null;
    }

    /// Channels past the end of the universe (0: it fits).
    public static int Overflow(int address, int count) => Math.Max(0, address + count - 1 - UniverseSize);

    /// The selected fixtures one after another from `from` (in the order given), in their universe, around the other
    /// fixtures; one that doesn't fit goes on in the next universe. Id → (universe, address).
    public IReadOnlyDictionary<string, (int Universe, int Address)> InRow(IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> selected, int from)
    {
        var ids = selected.Select(Id).ToHashSet();
        var u = selected.Count == 0 ? 1 : selected.Min(Universe);
        var a = Math.Max(1, from);
        var placed = new Dictionary<string, (int, int)>();
        var taken = new List<(int U, int A, int N)>();
        foreach (var f in selected)
        {
            var n = Footprint(f);
            if (n > UniverseSize) n = UniverseSize;  // a fixture larger than a universe: start it at 1 (it can't fit anyway)
            while (true)
            {
                if (a + n - 1 > UniverseSize) { u++; a = 1; continue; }
                var clash = Clashes(u, a, n, ids).Count > 0 || taken.Any(t => t.U == u && t.A <= a + n - 1 && a <= t.A + t.N - 1);
                if (clash) { a++; continue; }
                break;
            }
            placed[Id(f)] = (u, a);
            taken.Add((u, a, n));
            a += n;
        }
        return placed;
    }

    // MARK: adding fixtures (Add Fixtures…)

    /// The name new fixtures of a model get, numbered: "beamz/fuze75b-beam" → "fuze" (fuze1, fuze2, …).
    public static string BaseName(string key)
    {
        var last = key.Split('/', StringSplitOptions.RemoveEmptyEntries).LastOrDefault() ?? "";
        var letters = new string(last.TakeWhile(char.IsLetter).ToArray());
        return letters.Length == 0 ? "fx" : letters;
    }

    /// `count` new fixtures of a model and mode, each with a name of its own: the fixtures to add. No start
    /// addresses: you give each the one set on the fixture (a guess is usually wrong, and then they overlap).
    public List<Dictionary<string, JSONValue>> NewFixtures(string key, string mode, int count)
    {
        var baseName = BaseName(key);
        var ids = _fixtures.Select(Id).ToHashSet();
        var added = new List<Dictionary<string, JSONValue>>();
        for (var i = 0; i < count; i++)
        {
            var n = 1;
            while (ids.Contains($"{baseName}{n}")) n++;
            ids.Add($"{baseName}{n}");
            added.Add(new Dictionary<string, JSONValue> { ["id"] = $"{baseName}{n}", ["fixture"] = key, ["mode"] = mode, ["universe"] = 1 });
        }
        return added;
    }
}

/// A set's layout (the set file, or a set on a rig) as the app edits it: its fixtures as mutable dictionaries.
public static class SetLayout
{
    public static Dictionary<string, JSONValue>? Parse(byte[]? data) => data is null ? null : JSONValue.ParseObject(data);

    public static List<Dictionary<string, JSONValue>> Fixtures(IReadOnlyDictionary<string, JSONValue> layout) =>
        (layout.GetValueOrDefault("fixtures")?.Array ?? []).Select(v => v.Object is { } o ? new Dictionary<string, JSONValue>(o) : null)
            .OfType<Dictionary<string, JSONValue>>().ToList();

    /// The layout with these fixtures.
    public static Dictionary<string, JSONValue> WithFixtures(IReadOnlyDictionary<string, JSONValue> layout,
                                                              IEnumerable<IReadOnlyDictionary<string, JSONValue>> fixtures)
    {
        var l = new Dictionary<string, JSONValue>(layout)
        {
            ["fixtures"] = JSONValue.Of(fixtures.Select(f => JSONValue.Of(f))),
        };
        return l;
    }

    /// Changes one fixture (by id) in a list of them.
    public static void Change(List<Dictionary<string, JSONValue>> all, string id, Action<Dictionary<string, JSONValue>> body)
    {
        if (all.FirstOrDefault(f => Patch.Id(f) == id) is { } f) body(f);
    }
}
