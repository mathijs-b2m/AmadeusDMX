// Client for the engine's setup API (amadeus/web/): the same endpoints the web setup page uses.
// The app runs `amadeus setup --port 8181` in the background for it.
//
// Request bodies are plain objects (anonymous types, dictionaries, JSONValue), serialised as they are; layouts (a
// set on a rig) go as the JSONValue dictionaries RigDocument and `Rig()` work with.
using System.Net.Http.Headers;
using System.Numerics;
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
                            CancellationToken ct) =>
        (await Exchange(method, path, body, query, timeout, ct)).Data;

    /// A request and the whole answer: its status, its content type and its bytes.
    async Task<(int Status, string? Type, byte[] Data)> Exchange(HttpMethod method, string path, object? body,
                                                                IReadOnlyDictionary<string, string>? query, double timeout, CancellationToken ct)
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
        return ((int)resp.StatusCode, resp.Content.Headers.ContentType?.MediaType, await resp.Content.ReadAsByteArrayAsync(cts.Token));
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

    /// Converts a .gdtf file (from the maker's site or your own GDTF Share account) into your fixtures; returns its
    /// library key and default mode. Your copy only: GDTF fixtures are never shipped.
    public Task<AmadeusKit.NewFixture> ImportGDTF(string name, byte[] data, CancellationToken ct = default) =>
        Post("api/fixture/gdtf", new { name, data = Convert.ToBase64String(data) }, AmadeusKit.NewFixture.From, timeout: 120, ct: ct);

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

    /// The rig editor's test: a moving head straight out to the audience (the reply's `Dir`), whatever its placing.
    public Task<LightTest> TestLightFront(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout,
                                          CancellationToken ct = default) =>
        Post("api/test-light", new { fixture, rig = layout, on, point = "front" }, LightTest.From, ct: ct);

    /// The check after hanging for a layout: its fixtures in the hang sheet's order, with what to see.
    public Task<HangCheckStep[]> HangCheck(IReadOnlyDictionary<string, JSONValue> layout, CancellationToken ct = default) =>
        Post("api/hangcheck", new { rig = layout }, c => J.Req(c, "steps", J.ArrayOf(HangCheckStep.From)), ct: ct);

    /// The calibration that puts a head right the check found hung wrong ("mirrored", "turned", "both"), or the rig
    /// editor's front test saw its beam go "left", "right" or "back" instead.
    public Task<Dictionary<string, JSONValue>> HangCheckFix(IReadOnlyDictionary<string, JSONValue> layout, string fixture, string fix,
                                                           CancellationToken ct = default) =>
        Post("api/hangcheck/fix", new { rig = layout, fixture, fix }, c => J.Req(c, "fields", AnyObject), ct: ct);

    /// A fixture mode channel by channel, for the DMX mapper.
    public Task<FixtureMapping> Mapping(string key, string mode, CancellationToken ct = default) =>
        Get("api/fixture/map", FixtureMapping.From, new Dictionary<string, string> { ["key"] = key, ["mode"] = mode }, ct);

    /// Saves a hand mapping into your copy of the definition (every fixture of that model plays by it). `checked`:
    /// every channel was checked on the fixture, and the colour wheel's (or the ring's) slots named then are saved with it.
    public async Task<IReadOnlyList<string>> SaveMapping(FixtureMapping m, bool @checked = false, bool wheel = false, bool ring = false,
                                                         CancellationToken ct = default)
    {
        var r = await Post("api/fixture/map", MappingBody(m, @checked, wheel, ring), SaveResult.From, ct: ct);
        return r.Problems ?? [];
    }

    /// SaveMapping's body: `checked`: every channel was checked on the fixture; `wheel`, `ring`: the colour wheel's or
    /// the ring's colours were named (saved with it, as they are after a check too).
    internal static Dictionary<string, object?> MappingBody(FixtureMapping m, bool @checked, bool wheel, bool ring = false)
    {
        var chans = m.Channels.Select(c => new { role = c.Role, cell = c.Cell, value = c.Value, attr = c.Attr }).ToList();
        var body = new Dictionary<string, object?>
        {
            ["key"] = m.Key, ["mode"] = m.Mode, ["kind"] = m.Kind, ["channels"] = chans, ["checked"] = @checked,
        };
        if ((@checked || wheel) && m.Channels.Any(c => c.Role == "color_wheel") && m.Wheel.Count > 0)
            body["wheel"] = m.Wheel.Select(w => new { name = w.Name, from = w.From, to = w.To, rgb = w.Rgb }).ToList();
        if ((@checked || ring) && m.Channels.Any(c => c.Role == "ring_color") && m.Ring.Count > 0)
            body["ring"] = m.Ring.Select(w => new { name = w.Name, from = w.From, to = w.To, rgb = w.Rgb }).ToList();
        return body;
    }

    /// The common layouts a fixture without a brand is made from, the closest to `type` and `channels` first.
    public Task<AmadeusKit.FixtureTemplates> FixtureTemplates(string type = "", int channels = 0, CancellationToken ct = default) =>
        Get("api/fixture/templates", AmadeusKit.FixtureTemplates.From,
            new Dictionary<string, string> { ["type"] = type, ["channels"] = channels.ToString(System.Globalization.CultureInfo.InvariantCulture) }, ct);

    /// Makes a fixture in your library from a template; returns its key and mode, or the problems.
    public Task<AmadeusKit.NewFixture> NewFixture(string manufacturer, string model, string template, int channels, string type,
                                                  int watts, int panDeg, int tiltDeg, CancellationToken ct = default) =>
        Post("api/fixture/new", new
        {
            manufacturer, model, template, channels, type, watts, pan_deg = panDeg, tilt_deg = tiltDeg,
        }, AmadeusKit.NewFixture.From, ct: ct);

    // MARK: importing a venue's documents (amadeus/web/importer.py)

    /// Starts building a set and a rig `name` from a venue's files (PDFs, MVR, patch sheets): the job to follow with
    /// ImportStatus. Null when a set or rig of that name exists already and not `replace` (the engine's 409).
    /// Generous time: the files go up whole, in base64.
    public async Task<string?> StartImport(string name, IEnumerable<(string Name, byte[] Data)> files, bool replace = false,
                                           CancellationToken ct = default)
    {
        var body = new
        {
            name, replace, files = files.Select(f => new { name = f.Name, data = Convert.ToBase64String(f.Data) }).ToList(),
        };
        var (status, _, data) = await Exchange(HttpMethod.Post, "api/import", body, null, 300, ct);
        if (status == 409 && !replace) return null;
        return Decode(data, c => J.Req(c, "job", J.String));
    }

    /// How an import goes: its step while it runs, the report when it is done or failed.
    public Task<ImportStatus> ImportStatus(string job, CancellationToken ct = default) =>
        Get("api/import", AmadeusKit.ImportStatus.From, new Dictionary<string, string> { ["job"] = job }, ct);

    /// Stops an import at its next step; nothing is saved.
    public Task<ImportStatus> CancelImport(string job, CancellationToken ct = default) =>
        Post("api/import/cancel", new { job }, AmadeusKit.ImportStatus.From, ct: ct);

    /// The drawings under a rig (the plans an import placed its fixtures from), each with its corners on the rig.
    public Task<Underlay[]> Underlays(string rig, CancellationToken ct = default) =>
        Get("api/underlays", c => J.Req(c, "underlays", J.ArrayOf(Underlay.From)), new Dictionary<string, string> { ["rig"] = rig }, ct);

    /// A drawing's page: a one-page PDF.
    public async Task<byte[]> UnderlayPage(string file, CancellationToken ct = default)
    {
        var (_, type, data) = await Exchange(HttpMethod.Get, "api/underlay/page", null, new Dictionary<string, string> { ["file"] = file }, 60, ct);
        if (type?.StartsWith("application/pdf", StringComparison.Ordinal) != true)
        {
            Decode(data, AnyObject);  // throws the engine's error
            throw SetupAPIException.Server("The engine sent no page.");
        }
        return data;
    }

    /// Lines a drawing up again: `a` and `b` (page fractions from its top left) are the stage's front edge at stage
    /// left and at stage right, `widthM` apart. The rig file is saved, its fixtures and their trusses moved.
    public Task<Underlay> AlignUnderlay(string rig, string id, Vec2 a, Vec2 b, double widthM, CancellationToken ct = default) =>
        Post("api/underlay/align", new { rig, id, a = new[] { a.X, a.Y }, b = new[] { b.X, b.Y }, width_m = widthM },
            c => J.Req(c, "underlay", Underlay.From), ct: ct);

    /// Takes a drawing away (the fixtures stay where they are); the drawings left.
    public Task<Underlay[]> RemoveUnderlay(string rig, string id, CancellationToken ct = default) =>
        Post("api/underlay/remove", new { rig, id }, c => J.Req(c, "underlays", J.ArrayOf(Underlay.From)), ct: ct);

    // MARK: DMX devices (config/devices.json)

    /// Your DMX devices, and the USB DMX interfaces plugged in now.
    public Task<(DMXDevice[] Devices, USBInterface[] Usb)> DmxDevices(CancellationToken ct = default) =>
        Get("api/devices", c => (J.Req(c, "devices", J.ArrayOf(DMXDevice.From)), J.Req(c, "usb", J.ArrayOf(USBInterface.From))), ct: ct);

    /// Saves your DMX devices; returns the problems (nothing saved if any).
    public Task<string[]> SaveDMXDevices(IEnumerable<DMXDevice> devices, CancellationToken ct = default) =>
        Post("api/devices", new { devices = devices.Select(d => d.Json).ToList() },
            c => { J.Req(c, "ok", J.Bool); return J.Req(c, "problems", J.ArrayOf(J.String)); }, ct: ct);
}

/// What an import of a venue's documents says about itself (GET /api/import?job=…).
public sealed record ImportStatus
{
    /// A line of the report: "ok" (✓), "check" (? a guess to check), "missing" (✗); `Ids` the fixtures it is about.
    public sealed record Note(string Level, string Text, IReadOnlyList<string> Ids)
    {
        public static Note From(JsonElement c) =>
            new(J.Req(c, "level", J.String), J.Req(c, "text", J.String), J.Ref(c, "ids", J.ArrayOf(J.String)) ?? []);
    }

    public string State { get; init; } = "running";   // running | done | failed | cancelled
    public string Step { get; init; } = "";
    public IReadOnlyList<Note> Notes { get; init; } = [];
    public string Name { get; init; } = "";
    public int? Fixtures { get; init; }
    public int? Trusses { get; init; }
    public int? Underlays { get; init; }
    public string? Error { get; init; }

    public bool Running => State == "running";
    public bool Done => State == "done";
    public bool Failed => State == "failed";

    public static ImportStatus From(JsonElement c) => new()
    {
        State = J.Req(c, "state", J.String), Step = J.Ref(c, "step", J.String) ?? "", Notes = J.Ref(c, "notes", J.ArrayOf(Note.From)) ?? [],
        Name = J.Ref(c, "name", J.String) ?? "", Fixtures = J.Val(c, "fixtures", J.Int), Trusses = J.Val(c, "trusses", J.Int),
        Underlays = J.Val(c, "underlays", J.Int), Error = J.Ref(c, "error", J.String),
    };

    /// The report in the order it is read: what is missing first, then what to check, then what went right.
    public IReadOnlyList<Note> Report =>
        Notes.Select((n, i) => (n, i)).OrderBy(p => p.n.Level switch { "missing" => 0, "check" => 1, _ => 2 }).ThenBy(p => p.i)
            .Select(p => p.n).ToList();
}

/// A drawing under a rig (amadeus/rig/importer/underlay.py): a plan's page, and where it lies on the rig.
/// `A`/`B` and `Fixtures` are page fractions (0..1, from the page's top left): the stage's front edge at stage left and
/// stage right, and where each of its fixtures was drawn. `Crop`: the part of the page that is this plan ([x0, y0, x1,
/// y1], page fractions: a page can hold several). `Corners`: that part's top-left, top-right, bottom-right and
/// bottom-left corners on the rig, in rig metres (x from stage left, y towards the audience: the trusses' frame).
public sealed record Underlay
{
    public string Id { get; init; } = "";
    public string Title { get; init; } = "";
    public string Source { get; init; } = "";
    public string File { get; init; } = "";
    public double W { get; init; }
    public double H { get; init; }
    public string Set { get; init; } = "";
    public Vec2 A { get; init; }
    public Vec2 B { get; init; }
    public Vec2 AM { get; init; }
    public Vec2 BM { get; init; }
    public IReadOnlyDictionary<string, Vec2> Fixtures { get; init; } = new Dictionary<string, Vec2>();
    public IReadOnlyList<Vec2> Corners { get; init; } = [];
    public IReadOnlyList<double> Crop { get; init; } = WholePage;

    /// The crop of a page that is one plan.
    public static readonly IReadOnlyList<double> WholePage = [0, 0, 1, 1];

    static Vec2 Point(JsonElement e)
    {
        var a = J.Array(e, J.Double);
        if (a.Length < 2) throw new JsonException("a point is [x, y]");
        return new(a[0], a[1]);
    }

    public static Underlay From(JsonElement c) => new()
    {
        Id = J.Req(c, "id", J.String), Title = J.Ref(c, "title", J.String) ?? "", Source = J.Ref(c, "source", J.String) ?? "",
        File = J.Req(c, "file", J.String), W = J.Val(c, "w", J.Double) ?? 0, H = J.Val(c, "h", J.Double) ?? 0,
        Set = J.Ref(c, "set", J.String) ?? "",
        A = J.Val(c, "a", Point) ?? new(0, 0), B = J.Val(c, "b", Point) ?? new(1, 0),
        AM = J.Val(c, "a_m", Point) ?? new(0, 0), BM = J.Val(c, "b_m", Point) ?? new(0, 0),
        Fixtures = J.Ref(c, "fixtures", J.DictOf(Point)) ?? [],
        Corners = J.Ref(c, "corners", J.ArrayOf(Point)) ?? [],
        Crop = J.Ref(c, "crop", J.ArrayOf(J.Double)) is { Length: 4 } crop ? crop : WholePage,
    };

    /// The name to show: its title, else where it came from.
    public string Name => Title.Length > 0 ? Title : Source.Length > 0 ? Source : Id;

    /// The distance between its two reference points on the rig (m): the stage width it was lined up with.
    public double WidthM => (BM - AM).Length;

    public bool Equals(Underlay? o) => o is not null && Id == o.Id && File == o.File && Set == o.Set && A == o.A && B == o.B
                                       && AM == o.AM && BM == o.BM && Corners.SequenceEqual(o.Corners)
                                       && Crop.SequenceEqual(o.Crop);
    public override int GetHashCode() => HashCode.Combine(Id, File);
}

/// A fixture mode as the DMX mapper shows it (amadeus/library/mapper.py).
public sealed record FixtureMapping
{
    /// `Light`: it carries light (kept under the brightness limiter when tried); `Check`: its value while another
    /// channel is checked (the light on, the head centred).
    public sealed record Role(string RoleName, string Label, string Group, bool Cell, bool? Light = null, int? Check = null)  // "role" in the file
    {
        public static Role From(JsonElement c) =>
            new(J.Req(c, "role", J.String), J.Req(c, "label", J.String), J.Req(c, "group", J.String), J.Req(c, "cell", J.Bool),
                J.Val(c, "light", J.Bool), J.Val(c, "check", J.Int));
    }

    /// An answer in the channel-by-channel check: what the channel did, and what that makes it.
    public sealed record Answer(string AnswerText, string Role, string? Attr, int? Value)  // "answer" in the file
    {
        public static Answer From(JsonElement c) =>
            new(J.Req(c, "answer", J.String), J.Req(c, "role", J.String), J.Ref(c, "attr", J.String), J.Val(c, "value", J.Int));
    }

    /// A colour of the wheel (or of a ring round the lens): its DMX values and how it looks.
    public sealed record Slot(string Name, int From, int To, IReadOnlyList<double> Rgb)
    {
        public static Slot Decode(JsonElement c) =>
            new(J.Req(c, "name", J.String), J.Req(c, "from", J.Int), J.Req(c, "to", J.Int), J.Req(c, "rgb", J.ArrayOf(J.Double)));

        public int Id => From;
        public int Mid => (From + To) / 2;
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
    public bool Made { get; init; }                 // made here from a template: it wants the check on the fixture
    public bool Checked { get; init; } = true;
    public IReadOnlyList<Answer> Check { get; init; } = [];
    public IReadOnlyList<Slot> Wheel { get; init; } = [];
    public IReadOnlyList<Slot> Ring { get; init; } = [];   // the colours of an LED ring or strip round the lens (a ring_color channel)

    public static FixtureMapping From(JsonElement c) => new()
    {
        Key = J.Req(c, "key", J.String), Name = J.Req(c, "name", J.String), Mode = J.Req(c, "mode", J.String),
        Kind = J.Req(c, "kind", J.String), Kinds = J.Req(c, "kinds", J.DictOf(J.String)), Roles = J.Req(c, "roles", J.ArrayOf(Role.From)),
        Channels = J.Req(c, "channels", J.ArrayOf(Channel.From)), Plays = J.Req(c, "plays", J.Bool), Mapped = J.Req(c, "mapped", J.Bool),
        Refusal = J.Req(c, "refusal", J.String),
        Made = J.Val(c, "made", J.Bool) ?? false, Checked = J.Val(c, "checked", J.Bool) ?? true,
        Check = J.Ref(c, "check", J.ArrayOf(Answer.From)) ?? [], Wheel = J.Ref(c, "wheel", J.ArrayOf(Slot.Decode)) ?? [],
        Ring = J.Ref(c, "ring", J.ArrayOf(Slot.Decode)) ?? [],
    };

    /// The values sent while channel `probe` is checked at `value`: the others hold the light on and the head in
    /// the middle (their role's check value), held ones at their value.
    public IReadOnlyList<int> CheckValues(int probe, int value) =>
        Channels.Select((ch, i) => i == probe ? value : Roles.FirstOrDefault(r => r.RoleName == ch.Role)?.Check ?? ch.Value).ToList();

    /// The channels that carry light (kept under the brightness limiter when tried).
    public IReadOnlyList<int> LightChannels
    {
        get
        {
            var lit = Roles.Where(r => r.Light ?? (r.Group != "Position")).Select(r => r.RoleName).ToHashSet();
            return Channels.Select((ch, i) => (ch, i)).Where(p => lit.Contains(p.ch.Role)).Select(p => p.i).ToList();
        }
    }

    /// What the check found channel `i` does: a changed copy (Swift's mutating answer(_:for:)).
    public FixtureMapping Answered(Answer a, int i)
    {
        if (i < 0 || i >= Channels.Count) return this;
        var list = Channels.ToList();
        var ch = list[i] with { Role = a.Role };
        if (a.Attr is { } attr) ch = ch with { Attr = attr };
        else if (a.Role == "hold") ch = ch with { Attr = $"channel_{ch.N}" };
        if (a.Value is { } v) ch = ch with { Value = v };
        if (a.Role != "hold") ch = ch with { Cell = 0 };
        list[i] = ch;
        // a colour wheel: the usual cheap wheel until its colours are named
        return this with
        {
            Channels = list, Wheel = a.Role == "color_wheel" && Wheel.Count == 0 ? UsualWheel : Wheel,
            Ring = a.Role == "ring_color" && Ring.Count == 0 ? UsualRing : Ring,
        };
    }

    /// The same colours, slot by slot (Swift's `==` on [Slot]: a record compares its Rgb list by reference here).
    public static bool SameWheel(IReadOnlyList<Slot> a, IReadOnlyList<Slot> b) =>
        a.Count == b.Count && a.Zip(b).All(p => p.First.Name == p.Second.Name && p.First.From == p.Second.From
                                                && p.First.To == p.Second.To && p.First.Rgb.SequenceEqual(p.Second.Rgb));

    public static readonly IReadOnlyList<Slot> UsualWheel = new (string Name, double[] Rgb)[]
    {
        ("open", [1, 1, 1]), ("red", [1, 0, 0]), ("green", [0, 1, 0]), ("blue", [0, 0.2, 1]),
        ("yellow", [1, 0.9, 0]), ("magenta", [1, 0, 0.8]), ("cyan", [0, 0.9, 1]), ("orange", [1, 0.45, 0]),
    }.Select((s, i) => new Slot(s.Name, i * 16, i * 16 + 15, s.Rgb)).ToList();

    /// A guess at a ring's colours until they are named (amadeus/library/generic.py RING_SLOTS).
    public static readonly IReadOnlyList<Slot> UsualRing = new (string Name, double[] Rgb)[]
    {
        ("off", [0, 0, 0]), ("red", [1, 0, 0]), ("green", [0, 1, 0]), ("blue", [0, 0.2, 1]),
        ("yellow", [1, 0.9, 0]), ("magenta", [1, 0, 0.8]), ("cyan", [0, 0.9, 1]), ("white", [1, 1, 1]),
    }.Select((s, i) => new Slot(s.Name, i * 16, i * 16 + 15, s.Rgb)).ToList();
}

/// The layouts a new fixture is made from (amadeus/library/generic.py).
public sealed record FixtureTemplates(IReadOnlyList<FixtureTemplates.Kind> Types, IReadOnlyList<FixtureTemplates.Template> Templates)
{
    public sealed record Kind(string Type, string Label, string KindName)  // "kind" in the file
    {
        public static Kind From(JsonElement c) => new(J.Req(c, "type", J.String), J.Req(c, "label", J.String), J.Req(c, "kind", J.String));
    }

    public sealed record Template(string Id, string Label, string Type, string About, IReadOnlyList<string> Channels, int Count)
    {
        public static Template From(JsonElement c) => new(J.Req(c, "id", J.String), J.Req(c, "label", J.String), J.Req(c, "type", J.String),
            J.Req(c, "about", J.String), J.Req(c, "channels", J.ArrayOf(J.String)), J.Req(c, "count", J.Int));
    }

    public static FixtureTemplates From(JsonElement c) =>
        new(J.Req(c, "types", J.ArrayOf(Kind.From)), J.Req(c, "templates", J.ArrayOf(Template.From)));
}

public sealed record NewFixture(string? Key, string? Mode, IReadOnlyList<string>? Problems)
{
    public static NewFixture From(JsonElement c) =>
        new(J.Ref(c, "key", J.String), J.Ref(c, "mode", J.String), J.Ref(c, "problems", J.ArrayOf(J.String)));
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
    public IReadOnlyList<int> Channels { get; init; } = [];  // first and last DMX channel (empty: no start address)
    public Vector3? Dir { get; init; }                // a pointed head: where its beam goes (world, as the feed's)

    public static LightTest From(JsonElement c) => new()
    {
        On = J.Req(c, "on", J.Bool), Seconds = J.Req(c, "seconds", J.Double), Output = J.Req(c, "output", J.String),
        Universe = J.Req(c, "universe", J.Int), WireUniverse = J.Val(c, "wire_universe", J.Int),
        Channels = J.Ref(c, "channels", J.ArrayOf(J.Int)) ?? [],  // null: no start address (switching off one)
        Dir = J.Ref(c, "dir", J.ArrayOf(J.Float)) is { Length: >= 3 } d ? new Vector3(d[0], d[1], d[2]) : null,
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
