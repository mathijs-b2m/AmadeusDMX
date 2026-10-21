// Client for the engine's setup API (amadeus/web/): the same endpoints the web setup page uses.
// The app runs `amadeus setup --port 8181` in the background for it.
//
// Request bodies are plain objects (anonymous types, dictionaries, JSONValue), serialised as they are; layouts (a
// set on a rig) go as the JSONValue dictionaries RigDocument and `Rig()` work with.
using System.Net.Http.Headers;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace AmadeusKit;

public sealed record CatalogEntry
{
    public required string Key { get; init; }
    public required string Manufacturer { get; init; }
    public required string Model { get; init; }
    public string? Source { get; init; }
    public string? Type { get; init; }
    public string? Look { get; init; }
    public IReadOnlyDictionary<string, int>? Modes { get; init; }
    public string Id => Key;
    public bool IsLocal => Source == "local" || !Key.Contains(':');

    public static CatalogEntry From(JsonElement c) => new()
    {
        Key = J.Req(c, "key", J.String), Manufacturer = J.Req(c, "manufacturer", J.String), Model = J.Req(c, "model", J.String),
        Source = J.Ref(c, "source", J.String), Type = J.Ref(c, "type", J.String), Look = J.Ref(c, "look", J.String),
        Modes = J.Ref(c, "modes", J.DictOf(J.Int)),
    };

    public bool Equals(CatalogEntry? o) => o is not null && Key == o.Key && Manufacturer == o.Manufacturer && Model == o.Model
                                           && Source == o.Source && Type == o.Type && Look == o.Look;
    public override int GetHashCode() => Key.GetHashCode();
}

public sealed record CatalogDetails
{
    public required string Key { get; init; }
    public string? Manufacturer { get; init; }
    public string? Model { get; init; }
    public required IReadOnlyDictionary<string, JSONValue> Modes { get; init; }
    public string? DefaultMode { get; init; }

    public static CatalogDetails From(JsonElement c) => new()
    {
        Key = J.Req(c, "key", J.String), Manufacturer = J.Ref(c, "manufacturer", J.String), Model = J.Ref(c, "model", J.String),
        Modes = J.Req(c, "modes", J.DictOf(JSONValue.From)), DefaultMode = J.Ref(c, "default_mode", J.String),
    };

    /// Mode name → channel count, sorted by size (largest first: most features).
    public IReadOnlyList<(string Name, int Channels)> ModeList =>
        Modes.Select(p => (p.Key, p.Value.Array?.Count ?? (int)(p.Value.Number ?? 0))).OrderByDescending(m => m.Item2).ToList();
}

public sealed record ArtNetNode(string Ip, string Name, string? LongName, int? Outputs, IReadOnlyList<int>? Universes = null)
{
    public string Id => Ip;

    public static ArtNetNode From(JsonElement c) =>
        new(J.Req(c, "ip", J.String), J.Req(c, "name", J.String), J.Ref(c, "long_name", J.String), J.Val(c, "outputs", J.Int),
            c.TryGetProperty("universes", out var u) && u.ValueKind == JsonValueKind.Array ? u.EnumerateArray().Select(e => e.GetInt32()).ToList() : null);
}

public sealed record USBInterface(string Port, string? Description, string? Manufacturer, bool? Pro, string? WidgetSerial, string? Firmware)
{
    public string Id => Port;
    /// Answers the DMX USB Pro protocol (ENTTEC Pro and compatibles).
    public bool IsPro => Pro ?? false;

    public static USBInterface From(JsonElement c) => new(J.Req(c, "port", J.String), J.Ref(c, "description", J.String),
        J.Ref(c, "manufacturer", J.String), J.Val(c, "pro", J.Bool), J.Ref(c, "widget_serial", J.String), J.Ref(c, "firmware", J.String));
}

public sealed record DirectorOption(string Value, string Label, bool Available, string? Note)
{
    public string Id => Value;

    public static DirectorOption From(JsonElement c) =>
        new(J.Req(c, "value", J.String), J.Req(c, "label", J.String), J.Req(c, "available", J.Bool), J.Ref(c, "note", J.String));
}

public sealed record SaveResult(bool? Saved, IReadOnlyList<string>? Problems, string? Error)
{
    public static SaveResult From(JsonElement c) =>
        new(J.Val(c, "saved", J.Bool), J.Ref(c, "problems", J.ArrayOf(J.String)), J.Ref(c, "error", J.String));
}

/// What went wrong talking to the setup service (Swift: SetupAPIError): the engine's own words, or not running.
public sealed class SetupAPIException(string message, bool notRunning = false) : Exception(message)
{
    public bool NotRunning { get; } = notRunning;
    public static SetupAPIException Server(string s) => new(s);
    public static SetupAPIException NotRunningError() => new("The engine's setup service is not running.", true);
}

public sealed class SetupAPI
{
    public Uri Base { get; }

    static readonly HttpClient Http = new() { Timeout = Timeout.InfiniteTimeSpan };  // each request has its own

    /// Request bodies: names as written, JSONValue as JSON, nothing escaped that needn't be.
    public static readonly JsonSerializerOptions JsonOptions = new()
    {
        Converters = { new JSONValueConverter() },
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public SetupAPI(int port = 8181) { Base = new Uri($"http://127.0.0.1:{port}/"); }

    public async Task<bool> IsUp(CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(1));
        try
        {
            using var r = await Http.GetAsync(new Uri(Base, "api/sets"), cts.Token);
            return true;
        }
        catch (Exception e) when (e is HttpRequestException or OperationCanceledException) { return false; }
    }

    Uri Url(string path, IReadOnlyDictionary<string, string>? query)
    {
        var b = new UriBuilder(new Uri(Base, path));
        if (query is { Count: > 0 })
            b.Query = string.Join("&", query.Select(p => $"{Uri.EscapeDataString(p.Key)}={Uri.EscapeDataString(p.Value)}"));
        return b.Uri;
    }

    async Task<byte[]> Send(HttpMethod method, string path, object? body, IReadOnlyDictionary<string, string>? query, double timeout,
                            CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(timeout));
        using var req = new HttpRequestMessage(method, Url(path, query));
        if (body is not null)
        {
            req.Content = new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(body, body.GetType(), JsonOptions));
            req.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        }
        using var resp = await Http.SendAsync(req, cts.Token);
        return await resp.Content.ReadAsByteArrayAsync(cts.Token);
    }

    internal async Task<T> Get<T>(string path, Func<JsonElement, T> decode, IReadOnlyDictionary<string, string>? query = null,
                                  CancellationToken ct = default) =>
        Decode(await Send(HttpMethod.Get, path, null, query, 30, ct), decode);

    internal async Task<T> Post<T>(string path, object body, Func<JsonElement, T> decode, IReadOnlyDictionary<string, string>? query = null,
                                   double timeout = 60, CancellationToken ct = default) =>
        Decode(await Send(HttpMethod.Post, path, body, query, timeout, ct), decode);

    /// The engine's error, when it sent one; else the answer.
    static T Decode<T>(byte[] data, Func<JsonElement, T> decode)
    {
        if (JSONValue.ParseObject(data)?.GetValueOrDefault("error")?.String is { } e) throw SetupAPIException.Server(e);
        return J.DecodeOrThrow(data, decode);
    }

    static readonly Func<JsonElement, Dictionary<string, JSONValue>> AnyObject = J.DictOf(JSONValue.From);

    static void ThrowProblems(SaveResult r)
    {
        if (r.Saved == false) throw SetupAPIException.Server(string.Join("\n", r.Problems ?? []));
    }

    // MARK: endpoints

    public Task<CatalogEntry[]> Catalog(string query, int limit = 25, CancellationToken ct = default) =>
        Get("api/catalog", J.ArrayOf(CatalogEntry.From), new Dictionary<string, string> { ["q"] = query, ["limit"] = limit.ToString() }, ct);

    public Task<CatalogDetails> Details(string key, CancellationToken ct = default) =>
        Get("api/catalog/details", CatalogDetails.From, new Dictionary<string, string> { ["key"] = key }, ct);

    /// Converts a QLC+/OFL entry into the local fixture library; returns its library key.
    public Task<string> AddToLibrary(string key, CancellationToken ct = default) =>
        Post("api/catalog/add", new { key }, c => J.Req(c, "key", J.String), ct: ct);

    /// USB DMX interfaces plugged into this computer (probed for the DMX USB Pro protocol).
    public Task<USBInterface[]> UsbInterfaces(CancellationToken ct = default) =>
        Get("api/outputs", c => J.Req(c, "usb", J.ArrayOf(USBInterface.From)), ct: ct);

    public Task<DirectorOption[]> Directors(CancellationToken ct = default) => Get("api/directors", J.ArrayOf(DirectorOption.From), ct: ct);

    /// The decision model of a set (on a rig; the active ones by default). A live show follows the change.
    public Task SetDirector(string value, string? rig = null, string? set = null, CancellationToken ct = default) =>
        Post("api/director", new { director = value }, SaveResult.From, Pair(rig, set), ct: ct);

    public Task<ArtNetNode[]> Discover(CancellationToken ct = default) =>
        Post("api/discover", new { }, c => J.Req(c, "nodes", J.ArrayOf(ArtNetNode.From)), timeout: 20, ct: ct);

    // MARK: sets (gear) and rigs (venues)

    /// Creates a set and makes it the active one. `grid`: a generated test rig (`layout: "concert"` with
    /// model/count/width/height/depth/lasers; its positions become a rig of the same name), or an empty set.
    public Task CreateSet(string name, IReadOnlyDictionary<string, object?>? grid = null, string? copyOf = null, CancellationToken ct = default)
    {
        var body = new Dictionary<string, object?> { ["name"] = name };
        if (grid is not null) body["grid"] = grid;
        if (copyOf is not null) body["copy"] = copyOf;
        return Post("api/sets", body, AnyObject, ct: ct);
    }

    public Task MakeDefault(string name, CancellationToken ct = default) => Post("api/sets", new { active = name }, AnyObject, ct: ct);

    public Task DeleteSet(string name, CancellationToken ct = default) => Post("api/sets", new { delete = name }, AnyObject, ct: ct);

    public Task RenameSet(string name, string to, CancellationToken ct = default) =>
        Post("api/sets", new { rename = name, to }, AnyObject, ct: ct);

    /// A new rig from a template (floor, stands, booth, club, stage), or a copy of a rig; it becomes active.
    public Task CreateRig(string name, string template = "booth", double width = 8, double height = 4.5, double depth = 15,
                          bool screen = false, string? copyOf = null, CancellationToken ct = default)
    {
        var body = new Dictionary<string, object?>
        {
            ["name"] = name, ["template"] = template, ["width"] = width, ["height"] = height, ["depth"] = depth, ["screen"] = screen,
        };
        if (copyOf is not null) body["copy"] = copyOf;
        return Post("api/rigs", body, AnyObject, ct: ct);
    }

    public Task MakeDefaultRig(string name, CancellationToken ct = default) => Post("api/rigs", new { active = name }, AnyObject, ct: ct);

    /// Puts a set on a rig: a combination the show can run (`auto`: auto-mount its fixtures).
    public Task PlaceSet(string set, string on, bool auto, CancellationToken ct = default) =>
        Post("api/rigs", new { rig = on, place = set, auto }, AnyObject, timeout: 120, ct: ct);

    /// Takes a set off a rig (its placements there are forgotten).
    public Task UnplaceSet(string set, string from, CancellationToken ct = default) =>
        Post("api/rigs", new { rig = from, unplace = set }, AnyObject, ct: ct);

    /// Renames a fixture of a set, and where it hangs on every rig.
    public Task RenameFixture(string old, string to, string set, CancellationToken ct = default) =>
        Post("api/fixture/rename", new { set, from = old, to }, AnyObject, ct: ct);

    /// Saves a set alone (its fixtures, patch, output): no rig is touched.
    public async Task SaveSet(IReadOnlyDictionary<string, JSONValue> layout, string set, CancellationToken ct = default) =>
        ThrowProblems(await Post("api/rig", layout, SaveResult.From, new Dictionary<string, string> { ["set"] = set, ["setonly"] = "1" }, ct: ct));

    /// Saves a rig's structure alone (stage, trusses, zones, LED wall), no set placed on it.
    public Task SaveRigStructure(IReadOnlyDictionary<string, JSONValue> layout, string rig, CancellationToken ct = default) =>
        Post("api/rig", layout, SaveResult.From, new Dictionary<string, string> { ["rig"] = rig, ["structure"] = "1" }, ct: ct);

    public Task DeleteRig(string name, CancellationToken ct = default) => Post("api/rigs", new { delete = name }, AnyObject, ct: ct);

    public Task RenameRig(string name, string to, CancellationToken ct = default) =>
        Post("api/rigs", new { rename = name, to }, AnyObject, ct: ct);

    static Dictionary<string, string> Pair(string? rig, string? set)
    {
        var q = new Dictionary<string, string>();
        if (rig is not null) q["rig"] = rig;
        if (set is not null) q["set"] = set;
        return q;
    }

    /// A set on a rig (the active ones by default), as raw JSON for editing.
    public async Task<Dictionary<string, JSONValue>> Rig(string? rig = null, string? set = null, CancellationToken ct = default) =>
        JSONValue.ParseObject(await Send(HttpMethod.Get, "api/rig", null, Pair(rig, set), 60, ct)) ?? [];

    /// Saves a set on a rig: the engine splits it into the set file and the rig file.
    public async Task<SaveResult> SaveRig(IReadOnlyDictionary<string, JSONValue> rig, string? rigName = null, string? setName = null,
                                          CancellationToken ct = default)
    {
        var r = await Post("api/rig", rig, SaveResult.From, Pair(rigName, setName), ct: ct);
        ThrowProblems(r);
        return r;
    }

    /// Auto-mount on the saved rig: `ids`, else the fixtures not mounted yet (`all`: every one). Saves.
    public Task Automount(string rig, string set, IReadOnlyList<string>? ids = null, bool all = false, CancellationToken ct = default)
    {
        var body = new Dictionary<string, object?> { ["all"] = all };
        if (ids is not null) body["ids"] = ids;
        return Post("api/automount", body, AnyObject, Pair(rig, set), ct: ct);
    }

    /// Auto-mount on an unsaved layout (a combined set-on-rig dict): the placements come back, and for a rig
    /// that had no trusses the structure it got (read from where its fixtures hang, or a standard one).
    public Task<(Dictionary<string, Dictionary<string, JSONValue>> Placements, Truss[]? Trusses)> AutomountPlacements(
        IReadOnlyDictionary<string, JSONValue> layout, IReadOnlyList<string>? ids, bool all, CancellationToken ct = default)
    {
        var body = new Dictionary<string, object?> { ["rig"] = layout, ["all"] = all };
        if (ids is not null) body["ids"] = ids;
        return Post("api/automount", body, c => (J.Req(c, "placements", J.DictOf(AnyObject)), J.Ref(c, "trusses", J.ArrayOf(Truss.From))), ct: ct);
    }

    /// The hang sheet of a layout (a combined set-on-rig dict, saved or not): a printable HTML page saying where
    /// every fixture goes, its DMX address and labels for it.
    public async Task<byte[]> HangSheet(IReadOnlyDictionary<string, JSONValue> layout, string set, string rig, CancellationToken ct = default)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(30));
        using var req = new HttpRequestMessage(HttpMethod.Post, new Uri(Base, "api/hangsheet"))
        {
            Content = new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(new { rig = layout, names = new[] { set, rig } }, JsonOptions)),
        };
        req.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        using var resp = await Http.SendAsync(req, cts.Token);
        var data = await resp.Content.ReadAsByteArrayAsync(cts.Token);
        if (resp.Content.Headers.ContentType?.MediaType?.StartsWith("text/html", StringComparison.Ordinal) != true)
        {
            Decode(data, AnyObject);  // throws the engine's error
            throw SetupAPIException.Server("The engine sent no hang sheet.");
        }
        return data;
    }

    /// The mounted fixtures of a layout put in name order on the spots they take (top1 at the first place along
    /// the rig, top2 at the next): the placements that change. Nothing moves to a new spot.
    public Task<Dictionary<string, Dictionary<string, JSONValue>>> InOrderPlacements(IReadOnlyDictionary<string, JSONValue> layout,
                                                                                    CancellationToken ct = default) =>
        Post("api/automount", new { rig = layout, order = true }, c => J.Req(c, "placements", J.DictOf(AnyObject)), ct: ct);

    /// Free start addresses for `count` fixtures of a mode: tightly packed, or on easy-to-dial numbers.
    public Task<int[]> Suggest(string key, string mode, int count, int universe = 1, CancellationToken ct = default) =>
        Post("api/suggest", new { key, mode, count, universe },
            c => J.Ref(c, "easy", J.ArrayOf(J.Int)) ?? J.Ref(c, "packed", J.ArrayOf(J.Int)) ?? [], ct: ct);

    public async Task AddFixtures(string key, string mode, IReadOnlyList<int> addresses, int universe = 1, CancellationToken ct = default) =>
        ThrowProblems(await Post("api/rig/add", new { key, mode, addresses, universe }, SaveResult.From, ct: ct));

    /// Lights one fixture white for 2 s (on the real rig).
    public async Task Identify(string fixture, string? rig = null, string? set = null, CancellationToken ct = default)
    {
        var layout = await Rig(rig, set, ct);
        await Post("api/identify", new { fixture, rig = layout }, AnyObject, ct: ct);
    }

    /// Keeps one fixture lit on the real rig (the show pauses), or switches it off again: is it patched and
    /// connected? It goes dark by itself after `seconds`. Lasers and smoke machines are refused.
    /// With `raw`, its channels get those values as they are (the DMX mapper: what does this channel do?);
    /// `light`: the channels (from 0) that carry light, kept under the brightness limiter.
    public async Task<LightTest> TestLight(string fixture, bool on, IReadOnlyList<int>? raw = null, IReadOnlyList<int>? light = null,
                                           string? rig = null, string? set = null, CancellationToken ct = default)
    {
        var layout = await Rig(rig, set, ct);
        var body = new Dictionary<string, object?> { ["fixture"] = fixture, ["rig"] = layout, ["on"] = on };
        if (raw is not null) { body["raw"] = raw; body["light"] = light ?? []; }
        return await Post("api/test-light", body, LightTest.From, ct: ct);
    }

    /// Light one fixture of a layout (an editor's, saved or not); `point`: a moving head points its beam the way the
    /// check after hanging says.
    public Task<LightTest> TestLight(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout, bool point,
                                     CancellationToken ct = default) =>
        Post("api/test-light", new { fixture, rig = layout, on, point }, LightTest.From, ct: ct);

    /// The check after hanging for a layout: its fixtures in the hang sheet's order, with what to see.
    public Task<HangCheckStep[]> HangCheck(IReadOnlyDictionary<string, JSONValue> layout, CancellationToken ct = default) =>
        Post("api/hangcheck", new { rig = layout }, c => J.Req(c, "steps", J.ArrayOf(HangCheckStep.From)), ct: ct);

    /// The calibration that puts a head right the check found hung wrong ("mirrored", "turned", "both").
    public Task<Dictionary<string, JSONValue>> HangCheckFix(IReadOnlyDictionary<string, JSONValue> layout, string fixture, string fix,
                                                           CancellationToken ct = default) =>
        Post("api/hangcheck/fix", new { rig = layout, fixture, fix }, c => J.Req(c, "fields", AnyObject), ct: ct);

    /// A fixture mode channel by channel, for the DMX mapper.
    public Task<FixtureMapping> Mapping(string key, string mode, CancellationToken ct = default) =>
        Get("api/fixture/map", FixtureMapping.From, new Dictionary<string, string> { ["key"] = key, ["mode"] = mode }, ct);

    /// Saves a hand mapping into your copy of the definition (every fixture of that model plays by it).
    public async Task<IReadOnlyList<string>> SaveMapping(FixtureMapping m, CancellationToken ct = default)
    {
        var chans = m.Channels.Select(c => new { role = c.Role, cell = c.Cell, value = c.Value }).ToList();
        var r = await Post("api/fixture/map", new { key = m.Key, mode = m.Mode, kind = m.Kind, channels = chans }, SaveResult.From, ct: ct);
        return r.Problems ?? [];
    }

    // MARK: DMX devices (config/devices.json)

    /// Your DMX devices, and the USB DMX interfaces plugged in now.
    public Task<(DMXDevice[] Devices, USBInterface[] Usb)> DmxDevices(CancellationToken ct = default) =>
        Get("api/devices", c => (J.Req(c, "devices", J.ArrayOf(DMXDevice.From)), J.Req(c, "usb", J.ArrayOf(USBInterface.From))), ct: ct);

    /// Saves your DMX devices; returns the problems (nothing saved if any).
    public Task<string[]> SaveDMXDevices(IEnumerable<DMXDevice> devices, CancellationToken ct = default) =>
        Post("api/devices", new { devices = devices.Select(d => d.Json).ToList() },
            c => { J.Req(c, "ok", J.Bool); return J.Req(c, "problems", J.ArrayOf(J.String)); }, ct: ct);
}

/// A fixture mode as the DMX mapper shows it (amadeus/library/mapper.py).
public sealed record FixtureMapping
{
    public sealed record Role(string RoleName, string Label, string Group, bool Cell)  // "role" in the file
    {
        public static Role From(JsonElement c) =>
            new(J.Req(c, "role", J.String), J.Req(c, "label", J.String), J.Req(c, "group", J.String), J.Req(c, "cell", J.Bool));
    }

    /// What a range of a channel's values does, from the QLC+ or OFL file.
    public sealed record Range(int Lo, int Hi, string What)
    {
        public static Range From(JsonElement c)
        {
            if (c.ValueKind != JsonValueKind.Array || c.GetArrayLength() < 3) throw new JsonException("a range is [lo, hi, what]");
            return new(J.Int(c[0]), J.Int(c[1]), J.String(c[2]));
        }

        public int Mid => (Lo + Hi) / 2;
    }

    public sealed record Channel
    {
        public int N { get; init; }
        public string Attr { get; init; } = "";
        public string Role { get; init; } = "";    // a Role's role, "hold" (held at value) or "keep" (as converted)
        public int Cell { get; init; }             // 0: the whole fixture
        public int Value { get; init; }
        public string Name { get; init; } = "";
        public IReadOnlyList<Range> Ranges { get; init; } = [];
        public int Id => N;

        public static Channel From(JsonElement c) => new()
        {
            N = J.Req(c, "n", J.Int), Attr = J.Req(c, "attr", J.String), Role = J.Req(c, "role", J.String),
            Cell = J.Req(c, "cell", J.Int), Value = J.Req(c, "value", J.Int), Name = J.Req(c, "name", J.String),
            Ranges = J.Req(c, "ranges", J.ArrayOf(Range.From)),
        };
    }

    public string Key { get; init; } = "";
    public string Name { get; init; } = "";
    public string Mode { get; init; } = "";
    public string Kind { get; init; } = "";
    public IReadOnlyDictionary<string, string> Kinds { get; init; } = new Dictionary<string, string>();
    public IReadOnlyList<Role> Roles { get; init; } = [];
    public IReadOnlyList<Channel> Channels { get; init; } = [];
    public bool Plays { get; init; }
    public bool Mapped { get; init; }
    public string Refusal { get; init; } = "";

    public static FixtureMapping From(JsonElement c) => new()
    {
        Key = J.Req(c, "key", J.String), Name = J.Req(c, "name", J.String), Mode = J.Req(c, "mode", J.String),
        Kind = J.Req(c, "kind", J.String), Kinds = J.Req(c, "kinds", J.DictOf(J.String)), Roles = J.Req(c, "roles", J.ArrayOf(Role.From)),
        Channels = J.Req(c, "channels", J.ArrayOf(Channel.From)), Plays = J.Req(c, "plays", J.Bool), Mapped = J.Req(c, "mapped", J.Bool),
        Refusal = J.Req(c, "refusal", J.String),
    };
}

/// One step of the check after hanging (amadeus/rig/hangsheet.py check_steps).
public sealed record HangCheckStep
{
    public sealed record Fault(string Fix, string Seen)  // fix: mirrored | turned | both; seen: where the beam goes then, in words
    {
        public static Fault From(JsonElement c) => new(J.Req(c, "fix", J.String), J.Req(c, "seen", J.String));
    }

    public string Id { get; init; } = "";
    public string Label { get; init; } = "";
    public string Model { get; init; } = "";
    public string Where { get; init; } = "";
    public string Facing { get; init; } = "";
    public bool Moving { get; init; }
    public string Expect { get; init; } = "";
    public IReadOnlyList<Fault> Faults { get; init; } = [];
    public string Dark { get; init; } = "";    // why it can't be lit (a laser, a smoke machine), or ""
    public string Dmx { get; init; } = "";

    public static HangCheckStep From(JsonElement c) => new()
    {
        Id = J.Req(c, "id", J.String), Label = J.Req(c, "label", J.String), Model = J.Req(c, "model", J.String),
        Where = J.Req(c, "where", J.String), Facing = J.Req(c, "facing", J.String), Moving = J.Req(c, "moving", J.Bool),
        Expect = J.Req(c, "expect", J.String), Faults = J.Req(c, "faults", J.ArrayOf(Fault.From)), Dark = J.Req(c, "dark", J.String),
        Dmx = J.Req(c, "dmx", J.String),
    };

    public bool Equals(HangCheckStep? o) => o is not null && Id == o.Id && Label == o.Label && Model == o.Model && Where == o.Where
        && Facing == o.Facing && Moving == o.Moving && Expect == o.Expect && Faults.SequenceEqual(o.Faults) && Dark == o.Dark && Dmx == o.Dmx;
    public override int GetHashCode() => Id.GetHashCode();
}

/// Where a tested fixture's DMX goes.
public sealed record LightTest
{
    public bool On { get; init; }
    public double Seconds { get; init; }
    public string Output { get; init; } = "";         // the set's output, in words ("Art-Net → 2.0.0.10:6454")
    public int Universe { get; init; }
    public int? WireUniverse { get; init; }           // the Art-Net / sACN universe it goes out as
    public IReadOnlyList<int> Channels { get; init; } = [];  // first and last DMX channel

    public static LightTest From(JsonElement c) => new()
    {
        On = J.Req(c, "on", J.Bool), Seconds = J.Req(c, "seconds", J.Double), Output = J.Req(c, "output", J.String),
        Universe = J.Req(c, "universe", J.Int), WireUniverse = J.Val(c, "wire_universe", J.Int),
        Channels = J.Req(c, "channels", J.ArrayOf(J.Int)),
    };

    /// "universe 1, channels 43–50 · Art-Net → 2.0.0.10:6454 (universe 1 on the wire)"
    public string Summary
    {
        get
        {
            var first = Channels.Count > 0 ? Channels[0] : 0;
            var last = Channels.Count > 0 ? Channels[^1] : first;
            var s = new StringBuilder($"universe {Universe}, channels {first}–{last} · {Output}");
            if (WireUniverse is { } w) s.Append($" (universe {w} on the wire)");
            return s.ToString();
        }
    }
}

// MARK: - DMX devices (config/devices.json): the controllers, apart from the sets

/// A DMX device you have: an Art-Net node, an sACN node or a USB interface. A set maps its universes onto them.
public sealed record DMXDevice
{
    public string Id { get; set; }
    public string Name { get; set; }
    public string Type { get; set; }            // artnet | sacn | enttec_pro
    public string? Ip { get; set; }             // Art-Net: the node; sACN: unicast to it (nil: multicast)
    public int? UdpPort { get; set; }           // Art-Net (default 6454)
    public int? Priority { get; set; }          // sACN
    public int? FirstUniverse { get; set; }     // the protocol universe of its first output (Art-Net usually 0, sACN 1)
    public int? Outputs { get; set; }           // how many DMX outputs it has
    public string? Port { get; set; }           // USB: the device path (COM3 on Windows), or "auto"
    public string? Serial { get; set; }         // USB: the widget's serial (to recognise it)

    public DMXDevice(string id, string name, string type) { Id = id; Name = name; Type = type; }

    public static DMXDevice From(JsonElement c) => new(J.Req(c, "id", J.String), J.Req(c, "name", J.String), J.Req(c, "type", J.String))
    {
        Ip = J.Ref(c, "ip", J.String), UdpPort = J.Val(c, "udp_port", J.Int), Priority = J.Val(c, "priority", J.Int),
        FirstUniverse = J.Val(c, "first_universe", J.Int), Outputs = J.Val(c, "outputs", J.Int), Port = J.Ref(c, "port", J.String),
        Serial = J.Ref(c, "serial", J.String),
    };

    public string KindText => Type switch { "sacn" => "sACN", "enttec_pro" => "USB", _ => "Art-Net" };

    public string AddressText => Type switch
    {
        "sacn" => Ip ?? "multicast",
        "enttec_pro" => Port is { } p ? (p == "auto" ? "first one found" : RigFile.LastPathComponent(p)) : "auto",
        _ => Ip ?? "–",
    };

    /// How many outputs to offer (a USB interface has one).
    public int OutputCount => Type == "enttec_pro" ? 1 : Math.Max(1, Outputs ?? 4);

    /// JSON for the setup API (nil fields left out).
    public Dictionary<string, JSONValue> Json
    {
        get
        {
            var o = new Dictionary<string, JSONValue> { ["id"] = Id, ["name"] = Name, ["type"] = Type };
            if (Ip is { Length: > 0 }) o["ip"] = Ip;
            if (UdpPort is { } u) o["udp_port"] = u;
            if (Priority is { } pr) o["priority"] = pr;
            if (FirstUniverse is { } f) o["first_universe"] = f;
            if (Outputs is { } n) o["outputs"] = n;
            if (Port is not null) o["port"] = Port;
            if (Serial is { Length: > 0 }) o["serial"] = Serial;
            return o;
        }
    }
}
