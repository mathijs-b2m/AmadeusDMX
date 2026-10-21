// The engine's live feed (WebSocket, the same one the web visualiser uses): one "hello" per track the lights
// follow, then "frame" messages at ~40 fps. Mirrors amadeus/player.py and amadeus/live.py.
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace AmadeusKit;

public enum JSONKind { String, Number, Bool, Array, Object, Null }

/// Any JSON value: for the parts of a message the app only shows (the director's free-form fields), and for files
/// edited without knowing all their keys (sets, rigs). Immutable, compared by value.
[JsonConverter(typeof(JSONValueConverter))]
public sealed class JSONValue : IEquatable<JSONValue>
{
    public JSONKind Kind { get; }
    readonly string? _string;
    readonly double _number;
    readonly bool _bool;
    readonly JSONValue[]? _array;
    readonly Dictionary<string, JSONValue>? _object;

    JSONValue(JSONKind kind, string? s = null, double n = 0, bool b = false, JSONValue[]? a = null,
              Dictionary<string, JSONValue>? o = null)
    {
        Kind = kind; _string = s; _number = n; _bool = b; _array = a; _object = o;
    }

    public static readonly JSONValue Null = new(JSONKind.Null);
    public static readonly JSONValue True = new(JSONKind.Bool, b: true);
    public static readonly JSONValue False = new(JSONKind.Bool, b: false);
    public static JSONValue Of(string s) => new(JSONKind.String, s: s);
    public static JSONValue Of(double n) => new(JSONKind.Number, n: n);
    public static JSONValue Of(bool b) => b ? True : False;
    public static JSONValue Of(IEnumerable<JSONValue> a) => new(JSONKind.Array, a: a.ToArray());
    public static JSONValue Of(IEnumerable<KeyValuePair<string, JSONValue>> o) =>
        new(JSONKind.Object, o: new Dictionary<string, JSONValue>(o));

    public static implicit operator JSONValue(string s) => Of(s);
    public static implicit operator JSONValue(double n) => Of(n);
    public static implicit operator JSONValue(int n) => Of(n);
    public static implicit operator JSONValue(bool b) => Of(b);

    public string? String => Kind == JSONKind.String ? _string : null;
    public double? Number => Kind == JSONKind.Number ? _number : null;
    public bool? Bool => Kind == JSONKind.Bool ? _bool : null;
    public IReadOnlyList<JSONValue>? Array => _array;
    public IReadOnlyDictionary<string, JSONValue>? Object => _object;
    public bool IsNull => Kind == JSONKind.Null;

    /// A field of an object (nil when it isn't one, or has no such key).
    public JSONValue? this[string key] => _object?.GetValueOrDefault(key);

    /// Short text for display.
    public string Text => Kind switch
    {
        JSONKind.String => _string!,
        JSONKind.Number => _number == Math.Round(_number) && Math.Abs(_number) < 9e18
            ? ((long)_number).ToString(CultureInfo.InvariantCulture)
            : _number.ToString("0.00", CultureInfo.InvariantCulture),
        JSONKind.Bool => _bool ? "yes" : "no",
        JSONKind.Null => "–",
        JSONKind.Array => string.Join(", ", _array!.Select(v => v.Text)),
        _ => "…",
    };

    // MARK: reading and writing

    public static JSONValue From(JsonElement e) => e.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined => Null,
        JsonValueKind.True => True,
        JsonValueKind.False => False,
        JsonValueKind.Number => Of(e.GetDouble()),
        JsonValueKind.String => Of(e.GetString()!),
        JsonValueKind.Array => new(JSONKind.Array, a: e.EnumerateArray().Select(From).ToArray()),
        _ => new(JSONKind.Object, o: e.EnumerateObject().ToDictionary(p => p.Name, p => From(p.Value))),
    };

    /// Parses JSON text (throws when it isn't JSON).
    public static JSONValue Parse(ReadOnlySpan<byte> utf8) => J.DecodeOrThrow(utf8, From);
    public static JSONValue Parse(string text) => Parse(Encoding.UTF8.GetBytes(text));

    /// A JSON object as a dictionary (nil when it isn't JSON or not an object): `[String: JSONValue]` in Swift.
    public static Dictionary<string, JSONValue>? ParseObject(ReadOnlySpan<byte> utf8)
    {
        try { return Parse(utf8)._object is { } o ? new Dictionary<string, JSONValue>(o) : null; }
        catch (JsonException) { return null; }
    }

    public void WriteTo(Utf8JsonWriter w, bool sortKeys = false)
    {
        switch (Kind)
        {
            case JSONKind.Null: w.WriteNullValue(); break;
            case JSONKind.Bool: w.WriteBooleanValue(_bool); break;
            case JSONKind.Number: WriteNumber(w, _number); break;
            case JSONKind.String: w.WriteStringValue(_string); break;
            case JSONKind.Array:
                w.WriteStartArray();
                foreach (var v in _array!) v.WriteTo(w, sortKeys);
                w.WriteEndArray();
                break;
            case JSONKind.Object:
                WriteObject(w, _object!, sortKeys);
                break;
        }
    }

    internal static void WriteObject(Utf8JsonWriter w, IEnumerable<KeyValuePair<string, JSONValue>> o, bool sortKeys)
    {
        w.WriteStartObject();
        foreach (var (k, v) in sortKeys ? o.OrderBy(p => p.Key, StringComparer.Ordinal) : o)
        {
            w.WritePropertyName(k);
            v.WriteTo(w, sortKeys);
        }
        w.WriteEndObject();
    }

    /// Whole numbers without ".0", like Swift's JSONEncoder and Python's json for ints.
    internal static void WriteNumber(Utf8JsonWriter w, double n)
    {
        if (n == Math.Floor(n) && Math.Abs(n) < 9e15) w.WriteNumberValue((long)n);
        else w.WriteNumberValue(n);
    }

    public byte[] ToJson(bool pretty = false, bool sortKeys = false) => Encode(w => WriteTo(w, sortKeys), pretty);

    public static byte[] ToJson(IEnumerable<KeyValuePair<string, JSONValue>> o, bool pretty = false, bool sortKeys = false) =>
        Encode(w => WriteObject(w, o, sortKeys), pretty);

    public override string ToString() => Encoding.UTF8.GetString(ToJson());

    internal static byte[] Encode(Action<Utf8JsonWriter> write, bool pretty = false)
    {
        using var ms = new MemoryStream();
        using (var w = new Utf8JsonWriter(ms, new JsonWriterOptions
               {
                   Indented = pretty,
                   Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
               }))
            write(w);
        return ms.ToArray();
    }

    // MARK: equality

    public bool Equals(JSONValue? other)
    {
        if (other is null || Kind != other.Kind) return false;
        return Kind switch
        {
            JSONKind.Null => true,
            JSONKind.Bool => _bool == other._bool,
            JSONKind.Number => _number == other._number,
            JSONKind.String => _string == other._string,
            JSONKind.Array => _array!.SequenceEqual(other._array!),
            _ => _object!.Count == other._object!.Count
                 && _object.All(p => other._object.TryGetValue(p.Key, out var v) && p.Value.Equals(v)),
        };
    }

    public override bool Equals(object? obj) => obj is JSONValue v && Equals(v);

    public override int GetHashCode() => Kind switch
    {
        JSONKind.Bool => _bool.GetHashCode(),
        JSONKind.Number => _number.GetHashCode(),
        JSONKind.String => _string!.GetHashCode(),
        JSONKind.Array => _array!.Length,
        JSONKind.Object => _object!.Count * 31,
        _ => 0,
    };

    public static bool operator ==(JSONValue? a, JSONValue? b) => a?.Equals(b) ?? b is null;
    public static bool operator !=(JSONValue? a, JSONValue? b) => !(a == b);
}

/// JSONValue in System.Text.Json (request bodies of the setup API).
public sealed class JSONValueConverter : JsonConverter<JSONValue>
{
    public override JSONValue Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        using var doc = JsonDocument.ParseValue(ref reader);
        return JSONValue.From(doc.RootElement);
    }

    public override void Write(Utf8JsonWriter writer, JSONValue value, JsonSerializerOptions options) => value.WriteTo(writer);
}

public sealed record Stage
{
    public double WidthM { get; set; } = 6;
    public double CeilingM { get; set; } = 4.5;
    public double RoomDepthM { get; set; } = 6;
    /// Moving-head beams stay off the ceiling / never shine back at the stage and the DJ (on unless switched off).
    public bool CeilingGuard { get; set; } = true;
    public bool BackGuard { get; set; } = true;
    /// An open-air stage: no ceiling, the sky is free for beams (the director aims there far more often).
    public bool Outdoor { get; set; }

    public Stage(double widthM = 6, double ceilingM = 4.5, double roomDepthM = 6)
    {
        WidthM = widthM; CeilingM = ceilingM; RoomDepthM = roomDepthM;
    }

    public static Stage From(JsonElement c) => new()
    {
        WidthM = J.Val(c, "width_m", J.Double) ?? 6,
        CeilingM = J.Val(c, "ceiling_m", J.Double) ?? 4.5,
        RoomDepthM = J.Val(c, "room_depth_m", J.Double) ?? 6,
        CeilingGuard = J.Val(c, "ceiling_guard", J.Bool) ?? true,
        BackGuard = J.Val(c, "back_guard", J.Bool) ?? true,
        Outdoor = J.Val(c, "outdoor", J.Bool) ?? false,
    };

    public JSONValue ToJSON() => JSONValue.Of(new Dictionary<string, JSONValue>
    {
        ["width_m"] = WidthM, ["ceiling_m"] = CeilingM, ["room_depth_m"] = RoomDepthM, ["ceiling_guard"] = CeilingGuard,
        ["back_guard"] = BackGuard, ["outdoor"] = Outdoor,
    });
}

public enum FixtureKind { Head, Laser, Blinder, Par, Strobe, Smoke, Other }

public static class FixtureKinds
{
    public static FixtureKind Parse(string s) => s switch
    {
        "head" => FixtureKind.Head, "laser" => FixtureKind.Laser, "blinder" => FixtureKind.Blinder, "par" => FixtureKind.Par,
        "strobe" => FixtureKind.Strobe, "smoke" => FixtureKind.Smoke, _ => FixtureKind.Other,
    };

    public static string RawValue(this FixtureKind k) => k.ToString().ToLowerInvariant();
}

/// One light element as the visualiser sees it (a fixture can have several, e.g. a multi-cell bar).
public sealed record FixtureInfo
{
    public string Id { get; set; }
    public FixtureKind Kind { get; set; }
    public string Label { get; set; }
    public Vec3 Pos { get; set; }
    public string Mount { get; set; }
    public double BeamDeg { get; set; }
    public double BeamWide { get; set; }
    public double Output { get; set; } = 1;
    public double OutputWide { get; set; } = 1;
    // drawing facts (newer engines): the fixture it belongs to, its housing, rotation, cells, static aim
    public string? Fixture { get; set; }
    public string? Body { get; set; }
    public double Rot { get; set; }
    public double[]? Size { get; set; }
    public int? Cells { get; set; }
    public double? Length { get; set; }
    public Vec3? Dir { get; set; }
    /// Base → head (moving heads): down when hanging, up on a stand, out of a truss face when side-mounted.
    public Vec3? Up { get; set; }
    /// The truss it is clamped to (nil: on the floor, or on its own stand).
    public string? Truss { get; set; }

    public FixtureInfo(string id, FixtureKind kind, string label, Vec3 pos, string mount, double beamDeg, double? beamWide = null)
    {
        Id = id; Kind = kind; Label = label; Pos = pos; Mount = mount; BeamDeg = beamDeg; BeamWide = beamWide ?? beamDeg;
    }

    static Vec3? Vector(JsonElement c, string key) =>
        J.Ref(c, key, J.ArrayOf(J.Double)) is { Length: 3 } d ? new Vec3(d[0], d[1], d[2]) : null;

    public static FixtureInfo From(JsonElement c)
    {
        var id = J.Req(c, "id", J.String);
        var p = J.Req(c, "pos", J.ArrayOf(J.Double));
        var beamDeg = J.Val(c, "beam_deg", J.Double) ?? 25;
        return new FixtureInfo(id, J.Ref(c, "kind", J.String) is { } k ? FixtureKinds.Parse(k) : FixtureKind.Other,
            J.Ref(c, "label", J.String) ?? id, new Vec3(p[0], p[1], p.Length > 2 ? p[2] : 0),
            J.Ref(c, "mount", J.String) ?? "stand", beamDeg, J.Val(c, "beam_wide", J.Double) ?? beamDeg)
        {
            Output = J.Val(c, "output", J.Double) ?? 1,
            OutputWide = J.Val(c, "output_wide", J.Double) ?? 1,
            Fixture = J.Ref(c, "fixture", J.String),
            Body = J.Ref(c, "body", J.String),
            Rot = J.Val(c, "rot", J.Double) ?? 0,
            Size = J.Ref(c, "size", J.ArrayOf(J.Double)),
            Cells = J.Val(c, "cells", J.Int),
            Length = J.Val(c, "length", J.Double),
            Dir = Vector(c, "dir"),
            Up = Vector(c, "up"),
            Truss = J.Ref(c, "truss", J.String),
        };
    }

    /// What the Swift encoder writes (the basic fields only).
    public JSONValue ToJSON() => JSONValue.Of(new Dictionary<string, JSONValue>
    {
        ["id"] = Id, ["kind"] = Kind.RawValue(), ["label"] = Label,
        ["pos"] = JSONValue.Of([Pos.X, Pos.Y, Pos.Z]), ["mount"] = Mount,
        ["beam_deg"] = BeamDeg, ["beam_wide"] = BeamWide, ["output"] = Output, ["output_wide"] = OutputWide,
    });
}

/// What the director decided for one phrase. The well-known fields are typed; everything is also kept in
/// `Fields` (the vocabulary grows on the Python side without the app having to follow).
public sealed class Decision
{
    public int Phrase { get; init; }
    public double Start { get; init; }
    public double End { get; init; }
    public string Section { get; init; } = "groove";
    public string Palette { get; init; } = "cool";
    public int Intensity { get; init; } = 1;
    public string Source { get; init; } = "rules";
    public double DropScore { get; init; }
    public string? Screen { get; init; }
    public string Prompt { get; init; } = "";
    public IReadOnlyDictionary<string, double> Confidence { get; init; } = new Dictionary<string, double>();
    public IReadOnlyDictionary<string, IReadOnlyDictionary<string, double>> Probabilities { get; init; } =
        new Dictionary<string, IReadOnlyDictionary<string, double>>();
    public IReadOnlyDictionary<string, JSONValue> Fields { get; init; } = new Dictionary<string, JSONValue>();

    public int Id => Phrase;

    static Dictionary<string, double> Numbers(JSONValue? v) =>
        (v?.Object ?? new Dictionary<string, JSONValue>())
        .Where(p => p.Value.Number is not null).ToDictionary(p => p.Key, p => p.Value.Number!.Value);

    public static Decision From(JsonElement e)
    {
        if (e.ValueKind != JsonValueKind.Object) throw new JsonException("a decision is an object");
        var all = J.Dict(e, JSONValue.From);
        JSONValue? F(string k) => all.GetValueOrDefault(k);
        return new Decision
        {
            Fields = all,
            Phrase = (int)(F("phrase")?.Number ?? 0),
            Start = F("start")?.Number ?? 0,
            End = F("end")?.Number ?? 0,
            Section = F("section")?.String ?? "groove",
            Palette = F("palette")?.String ?? "cool",
            Intensity = (int)(F("intensity")?.Number ?? 1),
            Source = F("source")?.String ?? "rules",
            DropScore = F("drop_score")?.Number ?? 0,
            Screen = F("screen")?.String,
            Prompt = F("prompt")?.String ?? "",
            Confidence = Numbers(F("confidence")),
            Probabilities = (F("probabilities")?.Object ?? new Dictionary<string, JSONValue>())
                .Where(p => p.Value.Object is not null)
                .ToDictionary(p => p.Key, p => (IReadOnlyDictionary<string, double>)Numbers(p.Value)),
        };
    }

    public string this[string key] => Fields.GetValueOrDefault(key)?.Text ?? "–";
}

public sealed partial class Hello
{
    public string Track { get; init; } = "";
    public double Duration { get; init; }
    public double Bpm { get; init; } = 120;
    public string Director { get; init; } = "rules";
    public IReadOnlyList<FixtureInfo> Fixtures { get; init; } = [];
    public Stage Stage { get; init; } = new();
    public IReadOnlyList<Decision> Plan { get; init; } = [];
    public double MaxFlashHz { get; init; } = 3;
    public IReadOnlyList<double> Energy { get; init; } = [];
    public bool Screen { get; init; }
    /// The phrase of the drop the LED wall counts into (3-2-1 DROP!): a rare moment, once or twice a night.
    public int? Countdown { get; init; }
    public IReadOnlyList<Truss> Trusses { get; init; } = [];
    public IReadOnlyList<Zone> Zones { get; init; } = [];
    /// What kind of music (one word), where that came from (you, ai, tag, audio), and the program it gets.
    public string Genre { get; init; } = "";
    public string GenreSource { get; init; } = "";
    public string Program { get; init; } = "";
    /// The genre whose house style the plan follows: in a live set the set's genre, which can differ.
    public string Style { get; init; } = "";

    public static Hello From(JsonElement c) => new()
    {
        Track = J.Ref(c, "track", J.String) ?? "",
        Duration = J.Val(c, "duration", J.Double) ?? 0,
        Bpm = J.Val(c, "bpm", J.Double) ?? 120,
        Director = J.Ref(c, "director", J.String) ?? "rules",
        Fixtures = J.Ref(c, "fixtures", J.ArrayOf(FixtureInfo.From)) ?? [],
        Stage = J.Ref(c, "stage", Stage.From) ?? new Stage(),
        Plan = J.Ref(c, "plan", J.ArrayOf(Decision.From)) ?? [],
        MaxFlashHz = J.Val(c, "max_flash_hz", J.Double) ?? 3,
        Energy = J.Ref(c, "energy", J.ArrayOf(J.Double)) ?? [],
        Screen = J.Val(c, "screen", J.Bool) ?? false,
        Countdown = J.Try(() => J.Val(c, "countdown", J.Int)),
        Trusses = J.Try(() => J.Ref(c, "trusses", J.ArrayOf(Truss.From))) ?? [],
        Genre = J.Try(() => J.Ref(c, "genre", J.String)) ?? "",
        GenreSource = J.Try(() => J.Ref(c, "genre_source", J.String)) ?? "",
        Program = J.Try(() => J.Ref(c, "program", J.String)) ?? "",
        Style = J.Try(() => J.Ref(c, "style", J.String)) ?? "",
        Zones = J.Try(() => J.Ref(c, "zones", J.ArrayOf(Zone.From))) ?? [],
    };

    [GeneratedRegex(@"^Deck \w+:\s*")]
    private static partial Regex DeckPrefix();

    /// The track title without the "Deck A: " prefix and the file extension.
    public string Title
    {
        get
        {
            var t = DeckPrefix().Replace(Track, "", 1);
            // NSString.deletingPathExtension: only an extension after the last "/", never a leading dot alone
            var slash = t.LastIndexOf('/');
            var dot = t.LastIndexOf('.');
            return dot > slash + 1 ? t[..dot] : t;
        }
    }

    public int? PhraseIndex(double t)
    {
        for (var i = Plan.Count - 1; i >= 0; i--)
            if (Plan[i].Start <= t) return i;
        return null;
    }
}

/// What is ready for a track in live mode: analysis, separated instruments, AI plan.
public sealed record TrackStatus
{
    public string? Analysis { get; init; }
    public string? Stems { get; init; }
    public string? Ai { get; init; }
    public int? AiDone { get; init; }
    public int? AiTotal { get; init; }
    public string? Lights { get; init; }
    public int? Elapsed { get; init; }
    public string? Stream { get; init; }  // a streamed track ("spotify"): its local copy is fetched first
    public string? Copy { get; init; }

    public static TrackStatus From(JsonElement c) => new()
    {
        Analysis = J.Ref(c, "analysis", J.String), Stems = J.Ref(c, "stems", J.String), Ai = J.Ref(c, "ai", J.String),
        AiDone = J.Val(c, "ai_done", J.Int), AiTotal = J.Val(c, "ai_total", J.Int), Lights = J.Ref(c, "lights", J.String),
        Elapsed = J.Val(c, "elapsed", J.Int), Stream = J.Ref(c, "stream", J.String), Copy = J.Ref(c, "copy", J.String),
    };
}

public sealed record DeckInfo
{
    public int Deck { get; init; }
    public string Track { get; init; } = "";
    public double Vol { get; init; }
    public bool Play { get; init; }
    public bool Ready { get; init; }
    public TrackStatus? Status { get; init; }
    public string? Genre { get; init; }
    public string? Style { get; init; }
    public int Id => Deck;

    public static DeckInfo From(JsonElement c) => new()
    {
        Deck = J.Req(c, "deck", J.Int), Track = J.Req(c, "track", J.String), Vol = J.Req(c, "vol", J.Double),
        Play = J.Req(c, "play", J.Bool), Ready = J.Req(c, "ready", J.Bool), Status = J.Ref(c, "status", TrackStatus.From),
        Genre = J.Ref(c, "genre", J.String), Style = J.Ref(c, "style", J.String),
    };
}

/// One laser beam: direction from the laser, colour and brightness.
public readonly record struct LaserBeam(Vector3 Dir, Vector3 Color, float Bright);

/// The show arc (live mode): the night's clock, the stage the music is in, and the knobs
/// (amadeus/show/arc.py). Every value is 0..1; `Manual` names the knobs the operator holds.
public sealed record ArcStatus
{
    public bool On { get; init; }
    public double Length { get; init; }
    /// Seconds since the music first played tonight (nil: the night hasn't started).
    public double? Elapsed { get; init; }
    public string Stage { get; init; } = "";
    /// [key, name] per stage, named for the event.
    public IReadOnlyList<IReadOnlyList<string>> Stages { get; init; } = [];
    public string Event { get; init; } = "";
    /// [key, title] per event type.
    public IReadOnlyList<IReadOnlyList<string>> Events { get; init; } = [];
    public bool Locked { get; init; }
    public double Heat { get; init; }
    public double Trend { get; init; }
    public double? Bpm { get; init; }
    public double? BaseBpm { get; init; }
    public IReadOnlyDictionary<string, double> Values { get; init; } = new Dictionary<string, double>();
    public IReadOnlyList<string> Manual { get; init; } = [];
    public int Groups { get; init; }
    public int Playing { get; init; }
    /// The heads' movement the plans are calmed to: 0 calm, 1 moderate, 2 as the director planned.
    public int? MovementLevel { get; init; }
    /// How many phrases a look is held (1: every phrase as the director planned it).
    public int? Hold { get; init; }

    public string StageName => Stages.FirstOrDefault(s => s.Count > 0 && s[0] == Stage) is { Count: > 0 } s ? s[^1] : Stage;
    public double? Remaining => Elapsed is { } e ? Length - e : null;

    public static ArcStatus From(JsonElement c)
    {
        var pairs = J.ArrayOf(J.ArrayOf(J.String));
        return new ArcStatus
        {
            On = J.Req(c, "on", J.Bool), Length = J.Req(c, "length", J.Double), Elapsed = J.Val(c, "elapsed", J.Double),
            Stage = J.Req(c, "stage", J.String), Stages = J.Req(c, "stages", pairs), Event = J.Req(c, "event", J.String),
            Events = J.Req(c, "events", pairs), Locked = J.Req(c, "locked", J.Bool), Heat = J.Req(c, "heat", J.Double),
            Trend = J.Req(c, "trend", J.Double), Bpm = J.Val(c, "bpm", J.Double), BaseBpm = J.Val(c, "base_bpm", J.Double),
            Values = J.Req(c, "values", J.DictOf(J.Double)), Manual = J.Req(c, "manual", J.ArrayOf(J.String)),
            Groups = J.Req(c, "groups", J.Int), Playing = J.Req(c, "playing", J.Int),
            MovementLevel = J.Val(c, "movement_level", J.Int), Hold = J.Val(c, "hold", J.Int),
        };
    }

    public bool Equals(ArcStatus? o) =>
        o is not null && On == o.On && Length == o.Length && Elapsed == o.Elapsed && Stage == o.Stage
        && Stages.Count == o.Stages.Count && Stages.Zip(o.Stages).All(p => p.First.SequenceEqual(p.Second))
        && Event == o.Event && Events.Count == o.Events.Count && Events.Zip(o.Events).All(p => p.First.SequenceEqual(p.Second))
        && Locked == o.Locked && Heat == o.Heat && Trend == o.Trend && Bpm == o.Bpm && BaseBpm == o.BaseBpm
        && Values.Count == o.Values.Count && Values.All(p => o.Values.TryGetValue(p.Key, out var v) && v == p.Value)
        && Manual.SequenceEqual(o.Manual) && Groups == o.Groups && Playing == o.Playing
        && MovementLevel == o.MovementLevel && Hold == o.Hold;

    public override int GetHashCode() => HashCode.Combine(Stage, Heat, Elapsed, Manual.Count, Values.Count);
}

public sealed class Frame
{
    public double T { get; init; }
    public int Phrase { get; init; }
    /// The beat position (beat index + phase), when the engine sends it.
    public double? Bp { get; init; }
    /// Per element: [dimmer, r, g, b, white, pan, tilt]
    public float[][] Fx { get; init; } = [];
    public float[] Bands { get; init; } = [];
    public string?[] Beam { get; init; } = [];
    public Vector3?[] Dirs { get; init; } = [];
    public LaserBeam[]?[] Lz { get; init; } = [];
    public IReadOnlyList<DeckInfo>? Decks { get; init; }
    /// What the laser guard did this frame: laser id → "zone 'Audience'" / "blanked (…)".
    public IReadOnlyDictionary<string, string>? LaserGuard { get; init; }
    /// VirtualDJ on another computer: the link's health.
    public LinkStatus? Link { get; init; }
    /// A status frame (Perform mode): time, phrase, decks; no fixtures.
    public bool Lite { get; init; }
    /// Each smoke machine's output now, 0..1 (element id → level).
    public IReadOnlyDictionary<string, float> Fog { get; init; } = new Dictionary<string, float>();
    /// The show arc (live mode).
    public ArcStatus? Arc { get; init; }

    public Frame() { }

    /// A still frame made in the app (the rig editor's light test): fixtures lit, heads pointed.
    public Frame(float[][] fx, Vector3?[] dirs)
    {
        Fx = fx;
        Beam = dirs.Select(d => d is null ? null : "open").ToArray();
        Dirs = dirs;
        Lz = new LaserBeam[]?[fx.Length];
    }

    static Vector3? Direction(JsonElement e)
    {
        if (e.ValueKind == JsonValueKind.Null) return null;
        var d = J.Array(e, J.Float);
        return d.Length >= 3 ? new Vector3(d[0], d[1], d[2]) : null;
    }

    static LaserBeam[]? Beams(JsonElement e)
    {
        if (e.ValueKind == JsonValueKind.Null) return null;
        return J.Array(e, J.ArrayOf(J.Float))
            .Where(b => b.Length >= 7)
            .Select(b => new LaserBeam(new Vector3(b[0], b[1], b[2]), new Vector3(b[3], b[4], b[5]), b[6]))
            .ToArray();
    }

    public static Frame From(JsonElement c) => new()
    {
        T = J.Val(c, "t", J.Double) ?? 0,
        Phrase = J.Val(c, "phrase", J.Int) ?? 0,
        Bp = J.Val(c, "bp", J.Double),
        Fx = J.Ref(c, "fx", J.ArrayOf(J.ArrayOf(J.Float))) ?? [],
        Bands = J.Ref(c, "bands", J.ArrayOf(J.Float)) ?? [],
        Beam = J.Ref(c, "beam", J.ArrayOf(J.OrNull(J.String))) ?? [],
        Dirs = J.Ref(c, "dirs", J.ArrayOf(Direction)) ?? [],
        Lz = J.Ref(c, "lz", J.ArrayOf(Beams)) ?? [],
        Decks = J.Ref(c, "decks", J.ArrayOf(DeckInfo.From)),
        LaserGuard = J.Try(() => J.Ref(c, "guard", J.DictOf(J.String))),
        Link = J.Try(() => J.Ref(c, "link", LinkStatus.From)),
        Lite = J.Val(c, "lite", J.Bool) ?? false,
        Fog = J.Try(() => J.Ref(c, "fog", J.DictOf(J.Float))) ?? new Dictionary<string, float>(),
        Arc = J.Try(() => J.Ref(c, "arc", ArcStatus.From)),
    };
}

/// A message on the feed: a HelloMessage or a FrameMessage.
public abstract record FeedMessage
{
    public static FeedMessage? Decode(ReadOnlySpan<byte> utf8)
    {
        try
        {
            var reader = new Utf8JsonReader(utf8);
            using var doc = JsonDocument.ParseValue(ref reader);
            var root = doc.RootElement;
            string kind;
            try { kind = J.Req(root, "type", J.String); }
            catch (JsonException) { return null; }
            return kind switch
            {
                "hello" => J.Try(() => Hello.From(root)) is { } h ? new HelloMessage(h) : null,
                "frame" => J.Try(() => Frame.From(root)) is { } f ? new FrameMessage(f) : null,
                _ => null,
            };
        }
        catch (JsonException) { return null; }
    }

    public static FeedMessage? Decode(string text) => Decode(Encoding.UTF8.GetBytes(text));
}

public sealed record HelloMessage(Hello Hello) : FeedMessage;

public sealed record FrameMessage(Frame Frame) : FeedMessage;
