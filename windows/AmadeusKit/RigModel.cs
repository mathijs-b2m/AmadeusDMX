// A set on a rig, editable: the rig's trusses, stage and zones, and where every fixture of the set sits on it.
// It is the combined view the engine reads (amadeus/rig/store.py compose); saving goes through the engine's
// setup API, which splits it back into the set file (the gear) and the rig file (the venue and placements).
// Unknown keys are kept as they are, so the engine and the web UI keep working.
//
// Placement model (shared with amadeus/geometry.py):
//   fixture.x       position across the stage as a fraction of stage.width_m
//   fixture.y_m     towards the audience (y = 0: the stage's front edge), z_m: height
//   fixture.rot_deg the fixture turned counter-clockwise seen from above; a bar runs along +x at 0°
//   fixture.aim     [azimuth°, elevation°] for fixtures without motors (pars, bars, strobes, blinders)
//   fixture.mount   hang (under a truss) | stand (on top / on a stand) | floor
//   fixture.truss, truss_pos_m, truss_side: the truss it is clamped to, where along it, and on which of the
//                   box truss's four sides: under | top | front (audience side) | back (editor bookkeeping)
//
// Swift's structs are value types; here the editable ones are classes with Clone() (RigDocument.Clone copies
// everything), so an editor keeps a copy before it changes one.
using System.Text.Json;

namespace AmadeusKit;

public sealed record Truss
{
    public string Id { get; set; }
    public string Type { get; set; } = "quatro";
    public double LengthM { get; set; }
    public double XM { get; set; }
    public double YM { get; set; }
    public double ZM { get; set; }
    public double RotDeg { get; set; }
    public bool Vertical { get; set; }
    /// "circle": a round truss, hung flat (amadeus/rig/trusses.py): a full circle or an arc of `ArcDeg` of
    /// `DiameterM`, centred on XM/YM, the middle of the arc facing the audience (turned by RotDeg); LengthM is the
    /// length round the arc and follows the two.
    public string? Shape { get; set; }
    public double? DiameterM { get; set; }
    public double? ArcDeg { get; set; }
    /// Where the heads on it play: "audience" or "down"; nil: automatic (down when it hangs over the crowd).
    public string? Aim { get; set; }
    /// A light stand's (type "bridge" or "tbar") limits as the maker gives them: what it takes, how high it goes.
    public double? MaxKg { get; set; }
    public double? MaxHeightM { get; set; }
    public double? MinHeightM { get; set; }

    /// The usual round truss sizes (any other works too) and arcs.
    public static readonly double[] RingDiameters = [2, 3, 4, 5, 6, 8];
    public static readonly double[] RingArcs = [360, 180];

    /// A light stand as it is sold (amadeus/rig/trusses.py): a bridge on two tripods or a T-bar on one.
    public sealed record StandPreset(string Type, double LengthM, double? MinHeightM, double MaxHeightM, double MaxKg)
    {
        public string Title
        {
            get
            {
                var what = Type == "tbar" ? "T-bar stand" : "Light bridge";
                return $"{what} {Format.Number(LengthM)} m · up to {Format.Number(MaxHeightM)} m, {Format.Number(MaxKg)} kg";
            }
        }
    }
    /// The usual budget ones: 3 m bridges up to 3 m (60 kg) and 2.65 m (25 kg), a sturdy T-bar stand up to 3.5 m
    /// (50 kg) and a light one up to 2.5 m (10 kg).
    public static readonly StandPreset[] StandPresets =
    [
        new("bridge", 3, null, 3, 60),
        new("bridge", 3, 1.2, 2.65, 25),
        new("tbar", 1.2, 1.6, 3.5, 50),
        new("tbar", 1, 1.05, 2.5, 10),
    ];
    /// A light bridge's stands: this far in from the bar's ends.
    public const double StandInsetM = 0.05;

    public Truss(string id, double lengthM, double xM, double yM, double zM, double rotDeg = 0, bool vertical = false)
    {
        Id = id; LengthM = lengthM; XM = xM; YM = yM; ZM = zM; RotDeg = rotDeg; Vertical = vertical;
    }

    public static Truss From(JsonElement c)
    {
        var t = new Truss(J.Req(c, "id", J.String), J.Val(c, "length_m", J.Double) ?? 2, J.Val(c, "x_m", J.Double) ?? 0,
            J.Val(c, "y_m", J.Double) ?? -1, J.Val(c, "z_m", J.Double) ?? 3, J.Val(c, "rot_deg", J.Double) ?? 0,
            J.Val(c, "vertical", J.Bool) ?? false)
        {
            Type = J.Ref(c, "type", J.String) ?? "quatro",
            Shape = J.Ref(c, "shape", J.String),
            DiameterM = J.Val(c, "diameter_m", J.Double),
            ArcDeg = J.Val(c, "arc_deg", J.Double),
            Aim = J.Ref(c, "aim", J.String),
            MaxKg = J.Val(c, "max_kg", J.Double),
            MaxHeightM = J.Val(c, "max_height_m", J.Double),
            MinHeightM = J.Val(c, "min_height_m", J.Double),
        };
        t.Normalise();
        return t;
    }

    public static Truss From(JSONValue v) => J.DecodeOrThrow(v.ToJson(), From);

    public JSONValue ToJSON()
    {
        var o = new Dictionary<string, JSONValue>
        {
            ["id"] = Id, ["type"] = Type, ["length_m"] = LengthM, ["x_m"] = XM, ["y_m"] = YM, ["z_m"] = ZM,
            ["rot_deg"] = RotDeg, ["vertical"] = Vertical,
        };
        if (Shape is not null) o["shape"] = Shape;
        if (DiameterM is { } d) o["diameter_m"] = d;
        if (ArcDeg is { } a) o["arc_deg"] = a;
        if (Aim is not null) o["aim"] = Aim;
        if (MaxKg is { } kg) o["max_kg"] = kg;
        if (MaxHeightM is { } top) o["max_height_m"] = top;
        if (MinHeightM is { } bottom) o["min_height_m"] = bottom;
        return JSONValue.Of(o);
    }

    /// A round truss.
    public static Truss Ring(string id, double diameter, double arc, double xM, double yM, double zM, double rotDeg = 0)
    {
        var t = new Truss(id, 1, xM, yM, zM, rotDeg) { Shape = "circle", DiameterM = diameter, ArcDeg = arc };
        t.Normalise();
        return t;
    }

    /// A truss this far in front of the stage edge hangs over the crowd (amadeus/rig/trusses.py OVER_CROWD_M).
    public const double OverCrowdM = 1.0;

    /// Where the heads on it play, automatic resolved: "audience", "down", or nil (wherever the director aims).
    public string? LightAim => Aim is "audience" or "down" ? Aim : !Vertical && YM >= OverCrowdM ? "down" : null;

    public bool IsRing => Shape == "circle" && !Vertical;
    /// A light stand: a tube on tripods (a bridge or a T-bar), not a box truss.
    public bool IsStand => Type is "bridge" or "tbar" && !Vertical && !IsRing;
    /// Where a light stand's tripods stand: under both ends of a bridge, under the middle of a T-bar.
    public IReadOnlyList<Vec2> StandFeet
    {
        get
        {
            if (!IsStand) return [];
            if (Type == "tbar") return [new(XM, YM)];
            var u = Math.Max(0, LengthM / 2 - StandInsetM);
            return [Point(-u).XY, Point(u).XY];
        }
    }
    public bool IsFullRing => IsRing && Arc >= 359.5;
    public double Arc => Math.Min(360, Math.Max(10, ArcDeg ?? 360));
    public double Radius => (DiameterM ?? 4) / 2;

    /// A round truss's length follows its diameter and arc (they are what is edited).
    public void Normalise()
    {
        if (IsRing) LengthM = RigDocument.Round(Arc * Math.PI / 180 * Radius, 1000);
        if (IsStand) ZM = Math.Min(Math.Max(ZM, MinHeightM ?? 0), MaxHeightM ?? ZM);  // a stand goes as high as it does
    }

    /// The angle (radians, counter-clockwise from +x) of the point `u` along a round truss from its arc's middle.
    public double RingAngle(double u) => (RotDeg + 90) * Math.PI / 180 - u / Radius;

    /// Which way the truss runs at `u` (degrees; on a ring the tangent, so its "front" faces out of the circle).
    public double DirectionDeg(double u) => IsRing ? RingAngle(u) * 180 / Math.PI - 90 : RotDeg;

    /// Unit vector along the truss (horizontal trusses).
    public Vec2 Axis => new(Math.Cos(RotDeg * Math.PI / 180), Math.Sin(RotDeg * Math.PI / 180));

    /// A point on the truss: `u` metres from its centre along it (or above its base, for a tower).
    public Vec3 Point(double u)
    {
        if (Vertical) return new(XM, YM, ZM - LengthM / 2 + u);
        if (IsRing)
        {
            var a = RingAngle(u);
            return new(XM + Radius * Math.Cos(a), YM + Radius * Math.Sin(a), ZM);
        }
        return new(XM + Axis.X * u, YM + Axis.Y * u, ZM);
    }

    /// A horizontal truss as straight pieces (one for a straight truss, short chords round a ring), for drawing and
    /// picking.
    public IReadOnlyList<(Vec3 A, Vec3 B)> Pieces(double step = 0.4)
    {
        if (!IsRing) return [(Point(-LengthM / 2), Point(LengthM / 2))];
        var n = Math.Max(8, (int)Math.Ceiling(LengthM / step));
        return Enumerable.Range(0, n)
            .Select(k => (Point(-LengthM / 2 + LengthM * k / n), Point(-LengthM / 2 + LengthM * (k + 1) / n))).ToList();
    }

    /// Where a point (seen from above) lands on the truss, and how far it is from it.
    public (double U, double Distance) Project(Vec2 p)
    {
        if (Vertical) return (0, (p - new Vec2(XM, YM)).Length);
        if (IsRing)  // round the circle from the arc's middle, kept on the arc
        {
            var d = p - new Vec2(XM, YM);
            var u = ((RotDeg + 90) * Math.PI / 180 - Math.Atan2(d.Y, d.X)) * Radius;
            var C = 2 * Math.PI * Radius;
            u = (u + C / 2) % C;  // like truncatingRemainder: the sign of the dividend
            if (u < 0) u += C;
            u -= C / 2;
            u = Math.Max(-LengthM / 2, Math.Min(LengthM / 2, u));
            var q = Point(u);
            return (u, (p - q.XY).Length);
        }
        var dd = p - new Vec2(XM, YM);
        var uu = Math.Max(-LengthM / 2, Math.Min(LengthM / 2, Vec2.Dot(dd, Axis)));
        var qq = new Vec2(XM, YM) + Axis * uu;
        return (uu, (p - qq).Length);
    }
}

/// A fixture definition (fixtures/BRAND/MODEL.json), the parts placement and drawing need.
public sealed class FixtureDefinition
{
    public sealed record PhysicalInfo(double? BeamDeg, double? BeamDegMax, double? Lumens, double[]? SizeMM, double? FieldDeg = null)
    {
        public static PhysicalInfo From(JsonElement c) => new(J.Val(c, "beam_deg", J.Double), J.Val(c, "beam_deg_max", J.Double),
            J.Val(c, "lumens", J.Double), J.Ref(c, "size_mm", J.ArrayOf(J.Double)), J.Val(c, "field_deg", J.Double));
    }

    public string Manufacturer { get; init; } = "";
    public string Model { get; init; } = "";
    public string Kind { get; init; } = "par";
    public PhysicalInfo? Physical { get; init; }
    public IReadOnlyDictionary<string, IReadOnlyList<IReadOnlyDictionary<string, JSONValue>>> Modes { get; init; } =
        new Dictionary<string, IReadOnlyList<IReadOnlyDictionary<string, JSONValue>>>();
    /// Why the show never drives it ("" if it does): see fixtures.inert in the engine.
    public string Inert { get; init; } = "";
    /// Something the user must do for it to be safe (a laser DMX can't keep off).
    public string? Warning { get; init; }
    /// Made here from a common layout and not yet checked channel by channel on the fixture.
    public bool NeedsCheck { get; init; }

    public static FixtureDefinition From(JsonElement c)
    {
        var kind = J.Ref(c, "kind", J.String) ?? "par";
        var modes = J.Try(() => J.Ref(c, "modes", J.DictOf(J.ArrayOf(J.DictOf(JSONValue.From)))))?
            .ToDictionary(p => p.Key, p => (IReadOnlyList<IReadOnlyDictionary<string, JSONValue>>)p.Value)
            ?? new Dictionary<string, IReadOnlyList<IReadOnlyDictionary<string, JSONValue>>>();
        var reason = J.Ref(c, "inert", J.String) ?? "";
        var warning = J.Ref(c, "warning", J.String);
        return new FixtureDefinition
        {
            Manufacturer = J.Ref(c, "manufacturer", J.String) ?? "",
            Model = J.Ref(c, "model", J.String) ?? "",
            Kind = kind,
            Physical = J.Ref(c, "physical", PhysicalInfo.From),
            Modes = modes,
            Warning = warning,
            NeedsCheck = J.Try(() => J.Val(c, "made", m => !(J.Val(m, "checked", J.Bool) ?? false))) ?? false,
            Inert = reason.Length > 0 ? reason
                : kind == "smoke" && !modes.Values.SelectMany(m => m).Any(ch => ch.GetValueOrDefault("attr")?.String == "fog")
                    ? "a smoke machine whose output channel isn’t known: the show never fires it"
                : kind == "laser" && !J.Has(c, "laser") ? "a laser whose channels aren’t mapped by hand yet: it stays dark"
                : "",
        };
    }

    /// What to tell someone adding it (nil: nothing special).
    public string? AddingNote
    {
        get
        {
            var parts = new[] { Inert.Length == 0 ? null : $"Not driven by the show: {Inert}.", Warning is null ? null : $"⚠ {Warning}." }
                .OfType<string>().ToList();
            return parts.Count == 0 ? null : string.Join(" ", parts);
        }
    }

    public string Name => $"{Manufacturer} {Model}";
    public bool IsMoving => Kind is "moving_head" or "moving_bar";

    /// Housing size in metres (width = along a bar, height, depth).
    public Vec3 Size => Physical?.SizeMM is { Length: 3 } s && s.All(v => v > 0) ? new Vec3(s[0], s[1], s[2]) / 1000
        : Kind is "par_bar" or "moving_bar" ? new Vec3(1.0, 0.15, 0.1) : new Vec3(0.3, 0.35, 0.25);

    public FixtureKind ElementKind => Kind switch
    {
        "moving_head" or "moving_bar" => FixtureKind.Head,
        "laser" => FixtureKind.Laser,
        "blinder" => FixtureKind.Blinder,
        "strobe" => FixtureKind.Strobe,
        "smoke" => FixtureKind.Smoke,
        _ => FixtureKind.Par,
    };

    IReadOnlyList<IReadOnlyDictionary<string, JSONValue>> Channels(string mode) =>
        Modes.GetValueOrDefault(mode) ?? [];

    /// Cells per mode (1 = the fixture is one element).
    public int Cells(string mode) =>
        Math.Max(1, Channels(mode).Select(c => c.GetValueOrDefault("head")?.Number).OfType<double>().Select(n => (int)n).Distinct().Count());

    public int ChannelCount(string mode) => Modes.GetValueOrDefault(mode)?.Count ?? 0;

    static readonly HashSet<string> Light = ["dimmer", "red", "green", "blue", "white", "uv", "cyan", "magenta", "yellow"];

    /// Does the show light anything in this mode? (amadeus/library/mapper.py `plays`) A fixture that plays
    /// nothing (only effect, macro or unnamed channels) is one for the DMX mapper.
    public bool Plays(string mode)
    {
        var attrs = Modes.Values.SelectMany(m => m).Select(c => c.GetValueOrDefault("attr")?.String).OfType<string>().ToHashSet();
        var blacklight = attrs.Contains("uv") && !attrs.Overlaps(["red", "green", "blue", "white", "cyan", "color_wheel"]);
        return Channels(mode).Any(c =>
            c.GetValueOrDefault("attr")?.String is { } a && Light.Contains(a) && (!c.ContainsKey("default") || (a == "uv" && blacklight)));
    }

    public string DefaultMode
    {
        get
        {
            string? best = null;
            var most = -1;
            foreach (var (k, v) in Modes) if (v.Count > most) { best = k; most = v.Count; }
            return best ?? "";
        }
    }
}

public sealed class PlacedFixture
{
    /// "1.033", or what it is without a start address.
    public string PatchText => Address is { } a ? $"{Universe}.{a:000}" : "no address";

    public string Id { get; set; }
    public string Key { get; set; }
    public string Mode { get; set; }
    public int Universe { get; set; }
    public int? Address { get; set; }     // null: no start address yet (the visualiser only until you give it one)
    public string Mount { get; set; }
    public double X { get; set; }          // fraction of the stage width
    public double YM { get; set; }
    public double ZM { get; set; }
    public double RotDeg { get; set; }
    public Vec2? Aim { get; set; }         // azimuth, elevation (fixtures without motors)
    public string? Truss { get; set; }
    public double? TrussPos { get; set; }
    public string? Side { get; set; }      // under | top | front | back (on a truss)
    public double? MountRoll { get; set; } // 90: on the front face, 270: on the back face (rolled about the truss)
    /// Not mounted on this rig yet: it waits on the floor at the front (the engine's waiting spot).
    public bool Waiting { get; set; }

    public PlacedFixture(string id, string key, string mode, int universe, int? address, string mount, double x, double yM,
                         double zM, double rotDeg, Vec2? aim, string? truss, double? trussPos, string? side = null,
                         double? mountRoll = null)
    {
        Id = id; Key = key; Mode = mode; Universe = universe; Address = address; Mount = mount; X = x; YM = yM; ZM = zM;
        RotDeg = rotDeg; Aim = aim; Truss = truss; TrussPos = trussPos; Side = side; MountRoll = mountRoll;
    }

    public PlacedFixture Clone() => (PlacedFixture)MemberwiseClone();

    /// Base → head, as the engine sees it (geometry.mount_up).
    public Vec3 Up
    {
        get
        {
            var down = Mount == "hang";
            if (!down || MountRoll is not { } roll || roll == 0) return new(0, 0, down ? -1 : 1);
            double t = roll * Math.PI / 180, r = RotDeg * Math.PI / 180;
            var n = new Vec3(-Math.Sin(r), Math.Cos(r), 0);  // R(-z) = -z cos t + n sin t
            return new Vec3(0, 0, -Math.Cos(t)) + n * Math.Sin(t);
        }
    }

    public Vec3 Position(double width) => new(X * width, YM, ZM);

    public bool SamePlace(PlacedFixture o) =>
        Id == o.Id && Key == o.Key && Mode == o.Mode && Universe == o.Universe && Address == o.Address && Mount == o.Mount
        && X == o.X && YM == o.YM && ZM == o.ZM && RotDeg == o.RotDeg && Aim == o.Aim && Truss == o.Truss
        && TrussPos == o.TrussPos && Side == o.Side && MountRoll == o.MountRoll && Waiting == o.Waiting;
}

/// A set on a rig, editable. `Raw` keeps everything the editor doesn't touch.
public sealed class RigDocument
{
    public string Rig { get; set; }
    public string Set { get; set; }
    public Dictionary<string, JSONValue> Raw { get; set; }
    public List<Truss> Trusses { get; set; }
    public List<PlacedFixture> Fixtures { get; set; }
    public List<Zone> Zones { get; set; }
    public Stage Stage { get; set; }

    /// What belongs to the rig rather than the set, and a fixture's fields that say where it is
    /// (amadeus/rig/store.py: RIG_KEYS, PLACEMENT_KEYS).
    public static readonly string[] RigKeys = ["stage", "trusses", "zones", "screen"];
    public static readonly string[] PlacementKeys = ["x", "y_m", "z_m", "mount", "rot_deg", "aim", "truss", "truss_pos_m", "truss_side",
                                                     "mount_roll_deg", "reverse", "width", "group"];
    public const string UnplacedKey = "_unplaced";

    /// Swift's `(v * k).rounded() / k` (halves away from zero).
    internal static double Round(double v, double k) => Math.Round(v * k, MidpointRounding.AwayFromZero) / k;

    /// The set placed on the rig (amadeus/rig/store.py compose).
    public static Dictionary<string, JSONValue> Compose(IReadOnlyDictionary<string, JSONValue> set,
                                                        IReadOnlyDictionary<string, JSONValue> rig, string setName)
    {
        var out_ = set.Where(p => !RigKeys.Contains(p.Key)).ToDictionary(p => p.Key, p => p.Value);
        foreach (var k in RigKeys) if (rig.TryGetValue(k, out var v)) out_[k] = v;
        var places = rig.GetValueOrDefault("placements")?[setName]?.Object ?? new Dictionary<string, JSONValue>();
        var fixtures = (out_.GetValueOrDefault("fixtures")?.Array ?? []).Select(v => v.Object).OfType<IReadOnlyDictionary<string, JSONValue>>()
            .Select(o => new Dictionary<string, JSONValue>(o)).ToList();
        var waiting = fixtures.Count(f => !places.ContainsKey(f.GetValueOrDefault("id")?.String ?? ""));
        var deck = out_.GetValueOrDefault("stage")?["deck_m"]?.Number ?? 0;   // a raised stage: they wait on its deck (store.py)
        var k2 = 0;
        foreach (var f in fixtures)
        {
            foreach (var key in PlacementKeys) f.Remove(key);
            if (places.GetValueOrDefault(f.GetValueOrDefault("id")?.String ?? "")?.Object is { } p)
                foreach (var (pk, pv) in p) f[pk] = pv;
            else
            {
                var spot = new Dictionary<string, JSONValue>
                {
                    ["x"] = Round((k2 + 1.0) / (waiting + 1), 10000), ["y_m"] = -0.3, ["z_m"] = Round(0.25 + deck, 1000), ["mount"] = "floor",
                };
                foreach (var (sk, sv) in spot) f[sk] = sv;
                f[UnplacedKey] = JSONValue.Of(spot);
                k2++;
            }
        }
        out_["fixtures"] = JSONValue.Of(fixtures.Select(f => JSONValue.Of(f)));
        return out_;
    }

    static readonly Dictionary<string, (double Y, double Z)> MountDefaults = new()
    {
        ["stand"] = (-0.6, 1.8), ["hang"] = (-1.0, 3.0), ["floor"] = (-0.4, 0.3),
    };

    /// Reads a combined set-on-rig document (throws when it isn't a JSON object).
    public RigDocument(string rig, string set, ReadOnlySpan<byte> data)
    {
        Rig = rig;
        Set = set;
        Raw = JSONValue.ParseObject(data) ?? throw new JsonException("a rig is a JSON object");
        Stage = Raw.GetValueOrDefault("stage") is { } st ? J.Try(() => J.DecodeOrThrow(st.ToJson(), Stage.From)) ?? new Stage() : new Stage();
        Trusses = Raw.GetValueOrDefault("trusses") is { } ts ? J.Try(() => J.DecodeOrThrow(ts.ToJson(), J.ArrayOf(Truss.From)).ToList()) ?? [] : [];
        Zones = Raw.GetValueOrDefault("zones") is { } zs ? J.Try(() => J.DecodeOrThrow(zs.ToJson(), J.ArrayOf(Zone.From)).ToList()) ?? [] : [];
        Fixtures = (Raw.GetValueOrDefault("fixtures")?.Array ?? []).Select(v =>
        {
            if (v.Object is not { } o || o.GetValueOrDefault("id")?.String is not { } id || o.GetValueOrDefault("fixture")?.String is not { } key)
                return null;
            var mount = o.GetValueOrDefault("mount")?.String ?? "stand";
            var d = MountDefaults.TryGetValue(mount, out var md) ? md : (Y: -0.6, Z: 1.8);
            var aim = o.GetValueOrDefault("aim")?.Array is { Count: 2 } a ? new Vec2(a[0].Number ?? 0, a[1].Number ?? 0) : (Vec2?)null;
            double? N(string k) => o.GetValueOrDefault(k)?.Number;
            return new PlacedFixture(id, key, o.GetValueOrDefault("mode")?.String ?? "", (int)(N("universe") ?? 1),
                (int?)N("address"), mount, N("x") ?? 0.5, N("y_m") ?? d.Y, N("z_m") ?? d.Z, N("rot_deg") ?? 0, aim,
                o.GetValueOrDefault("truss")?.String, N("truss_pos_m"), o.GetValueOrDefault("truss_side")?.String,
                N("mount_roll_deg"))
            {
                Waiting = o.ContainsKey(UnplacedKey),
            };
        }).OfType<PlacedFixture>().ToList();
    }

    RigDocument(RigDocument o)
    {
        Rig = o.Rig; Set = o.Set; Raw = new(o.Raw); Stage = o.Stage with { };
        Trusses = o.Trusses.Select(t => t with { }).ToList();
        Fixtures = o.Fixtures.Select(f => f.Clone()).ToList();
        Zones = o.Zones.Select(z => z.Clone()).ToList();
    }

    /// A copy to change (Swift's value semantics).
    public RigDocument Clone() => new(this);

    public double Width => Stage.WidthM;
    public string Label => $"{Set} on {Rig}";

    /// Two fixtures trade places (where each hangs, which way round, on which truss): the check after hanging found
    /// them hung the other way about. Their gear, patch and calibration stay their own.
    public void SwapPlacements(string a, string b)
    {
        var i = Fixtures.FindIndex(f => f.Id == a);
        var j = Fixtures.FindIndex(f => f.Id == b);
        if (a == b || i < 0 || j < 0) return;
        PlacedFixture fi = Fixtures[i].Clone(), fj = Fixtures[j].Clone();
        foreach (var (k, from) in new[] { (i, fj), (j, fi) })
        {
            var f = Fixtures[k];
            f.Mount = from.Mount; f.X = from.X; f.YM = from.YM; f.ZM = from.ZM; f.RotDeg = from.RotDeg; f.Aim = from.Aim;
            f.Truss = from.Truss; f.TrussPos = from.TrussPos; f.Side = from.Side; f.MountRoll = from.MountRoll;
            f.Waiting = from.Waiting;
        }
        // the placement fields the editor doesn't model (reverse, width, group) trade places too
        var other = PlacementKeys.Except(["x", "y_m", "z_m", "mount", "rot_deg", "aim", "truss", "truss_pos_m", "truss_side",
                                          "mount_roll_deg"]).ToList();
        var ra = RawFixture(a);
        var rb = RawFixture(b);
        UpdateRaw(a, o => { foreach (var k in other) Put(o, k, rb.GetValueOrDefault(k)); });
        UpdateRaw(b, o => { foreach (var k in other) Put(o, k, ra.GetValueOrDefault(k)); });
    }

    static void Put(Dictionary<string, JSONValue> o, string key, JSONValue? v)
    {
        if (v is null) o.Remove(key); else o[key] = v;
    }

    /// Calibration fields set on a fixture of the set (pan_invert, pan_home_deg, tilt_invert…).
    public void Calibrate(string id, IReadOnlyDictionary<string, JSONValue> fields) =>
        UpdateRaw(id, o => { foreach (var (k, v) in fields) o[k] = v; });

    /// The head group a fixture is put in by hand (amadeus/rig/groups.py); null: grouped by where it stands.
    public string? Group(string id) => RawFixture(id).GetValueOrDefault("group")?.String;

    /// The hand-made group names on this rig, sorted.
    public IReadOnlyList<string> GroupNames =>
        [.. Fixtures.Where(f => !f.Waiting).Select(f => Group(f.Id)).OfType<string>().Distinct().Order(StringComparer.Ordinal)];

    /// These fixtures into one hand-made group, or back to grouping by where they stand (null or blank).
    public void SetGroup(IEnumerable<string> ids, string? name)
    {
        var n = name?.Trim() ?? "";
        foreach (var id in ids) UpdateRaw(id, o => Put(o, "group", n.Length == 0 ? null : JSONValue.Of(n)));
    }

    public IReadOnlyDictionary<string, JSONValue> RawFixture(string id) =>
        (Raw.GetValueOrDefault("fixtures")?.Array ?? []).Select(v => v.Object).OfType<IReadOnlyDictionary<string, JSONValue>>()
        .FirstOrDefault(o => o.GetValueOrDefault("id")?.String == id) ?? new Dictionary<string, JSONValue>();

    void UpdateRaw(string id, Action<Dictionary<string, JSONValue>> body)
    {
        if (Raw.GetValueOrDefault("fixtures")?.Array is not { } list) return;
        var i = list.ToList().FindIndex(v => v["id"]?.String == id);
        if (i < 0 || list[i].Object is not { } obj) return;
        var o = new Dictionary<string, JSONValue>(obj);
        body(o);
        var copy = list.ToArray();
        copy[i] = JSONValue.Of(o);
        Raw["fixtures"] = JSONValue.Of(copy);
    }

    public int WaitingCount => Fixtures.Count(f => f.Waiting);

    public bool HasScreen => Raw.GetValueOrDefault("screen") is { } s && !s.IsNull && s.Bool != false;

    /// The set as JSON, with the editor's changes merged into what was there.
    public byte[] Json()
    {
        var out_ = new Dictionary<string, JSONValue>(Raw);
        Put(out_, "trusses", Trusses.Count == 0 ? null : JSONValue.Of(Trusses.Select(t => t.ToJSON())));
        Put(out_, "zones", Zones.Count == 0 ? null : JSONValue.Of(Zones.Select(z => z.ToJSON())));
        var old = new Dictionary<string, IReadOnlyDictionary<string, JSONValue>>();
        foreach (var v in Raw.GetValueOrDefault("fixtures")?.Array ?? [])
            if (v.Object is { } o && o.GetValueOrDefault("id")?.String is { } id) old.TryAdd(id, o);
        out_["fixtures"] = JSONValue.Of(Fixtures.Select(f =>
        {
            var o = old.TryGetValue(f.Id, out var was) ? new Dictionary<string, JSONValue>(was) : new Dictionary<string, JSONValue>();
            void Patch()
            {
                o["id"] = f.Id; o["fixture"] = f.Key; o["mode"] = f.Mode; o["universe"] = f.Universe; Put(o, "address", f.Address is { } ad ? ad : null);
            }
            if (f.Waiting)  // not mounted: its waiting spot, marked as such (the engine doesn't save it as a place)
            {
                foreach (var k in PlacementKeys) o.Remove(k);
                var spot = new Dictionary<string, JSONValue>
                {
                    ["x"] = Round(f.X, 10000), ["y_m"] = Round(f.YM, 1000), ["z_m"] = Round(f.ZM, 1000), ["mount"] = f.Mount,
                };
                foreach (var (k, v) in spot) o[k] = v;
                o[UnplacedKey] = JSONValue.Of(spot);
                Patch();
                return JSONValue.Of(o);
            }
            o.Remove(UnplacedKey);
            Patch();
            o["mount"] = f.Mount;
            o["x"] = Round(f.X, 10000); o["y_m"] = Round(f.YM, 1000); o["z_m"] = Round(f.ZM, 1000);
            Put(o, "rot_deg", f.RotDeg == 0 ? null : Round(f.RotDeg, 10));
            Put(o, "aim", f.Aim is { } a ? JSONValue.Of([Round(a.X, 10), Round(a.Y, 10)]) : null);
            Put(o, "truss", f.Truss is { } t ? JSONValue.Of(t) : null);
            Put(o, "truss_pos_m", f.TrussPos is { } tp ? Round(tp, 1000) : null);
            Put(o, "truss_side", f.Truss is null || f.Side is null ? null : JSONValue.Of(f.Side));
            Put(o, "mount_roll_deg", (f.MountRoll ?? 0) == 0 ? null : f.MountRoll!.Value);
            return JSONValue.Of(o);
        }));
        return JSONValue.ToJson(out_, pretty: true, sortKeys: true);
    }

    /// The document as JSON values (for the setup API's layout parameters).
    public Dictionary<string, JSONValue> JsonObject() => JSONValue.ParseObject(Json())!;
}

// MARK: - elements, as the engine expands them (amadeus/fixtures.py expand + geometry.position)

public static class RigElements
{
    static readonly Dictionary<FixtureKind, Vec2> StaticAim = new()
    {
        [FixtureKind.Par] = new(0, 80), [FixtureKind.Blinder] = new(0, 7), [FixtureKind.Strobe] = new(0, 8), [FixtureKind.Smoke] = new(0, 10),
    };

    public static Vec3 Direction(double azimuth, double elevation)
    {
        double a = azimuth * Math.PI / 180, e = elevation * Math.PI / 180;
        return new(Math.Cos(e) * Math.Sin(a), Math.Cos(e) * Math.Cos(a), Math.Sin(e));
    }

    /// Visualiser elements for a set (cells of bars along the bar), with the extra drawing facts.
    public static IReadOnlyList<FixtureInfo> Elements(RigDocument doc, Func<string, FixtureDefinition?> definitions)
    {
        var out_ = new List<FixtureInfo>();
        foreach (var f in doc.Fixtures)
        {
            var def = definitions(f.Key);
            var kind = def?.ElementKind ?? FixtureKind.Par;
            var n = def?.Cells(f.Mode) ?? 1;
            var length = def?.Size.X ?? 1;
            var basePos = f.Position(doc.Width);
            var r = f.RotDeg * Math.PI / 180;
            for (var k = 0; k < n; k++)
            {
                var off = n == 1 ? 0 : -length / 2 + length * (k + 0.5) / n;
                var pos = basePos + new Vec3(off * Math.Cos(r), off * Math.Sin(r), 0);
                var info = new FixtureInfo(n == 1 ? f.Id : $"{f.Id}.{k + 1}", kind, def?.Name ?? f.Key, pos, f.Mount,
                    def?.Physical?.BeamDeg ?? 25, def?.Physical?.BeamDegMax)
                {
                    Fixture = f.Id,
                    Body = def?.Kind,
                    Rot = f.RotDeg,
                    Truss = f.Truss,
                };
                if (kind == FixtureKind.Head)
                {
                    info.Flux = BeamLight.Flux(def?.Physical?.Lumens);
                    if (def?.Physical?.FieldDeg is { } fd && fd > info.BeamDeg) info.Field = fd / info.BeamDeg;
                }
                if (kind == FixtureKind.Head) info.Up = f.Up;
                info.Size = def is null ? null : def.Size.ToArray();
                if (n > 1) { info.Cells = n; info.Length = length; }
                if (kind is FixtureKind.Par or FixtureKind.Blinder or FixtureKind.Strobe or FixtureKind.Smoke)
                {
                    var aim = f.Aim ?? StaticAim.GetValueOrDefault(kind, new Vec2(0, 80));
                    info.Dir = Direction(aim.X - f.RotDeg, aim.Y);
                }
                out_.Add(info);
            }
        }
        return out_;
    }
}

// MARK: - zones: where beams may (not) go

/// A zone in the room that limits beams (`zones` in the set file; amadeus/zones.py enforces them).
///
///   kind  avoid     artistic: moving-head beams stay off it (a wall, the set, the LED wall, a VIP corner)
///         keep_in   artistic: moving-head beams land only inside it (e.g. the dance floor and the sky)
///         laser_out safety: no laser beam may enter it (with a safety margin); the engine lifts/shrinks
///                   the pattern, or blanks the laser. On top of the laser's masking plate, never instead.
///   shape rect  a flat rectangle: `size` = [width, height], turned by `rot_deg` (around z) and tilted by
///               `tilt_deg` (0 = upright, facing the audience; 90 = lying flat, like a ceiling over the crowd)
///         box   `size` = [width, depth, height], turned by `rot_deg`
public sealed class Zone : IEquatable<Zone>
{
    public string Id { get; set; }
    public string Name { get; set; }
    public string Kind { get; set; }          // avoid | keep_in | laser_out
    public string Shape { get; set; }         // rect | box
    public double[] Center { get; set; }      // x, y, z (m)
    public double[] Size { get; set; }
    public double RotDeg { get; set; }
    public double TiltDeg { get; set; }
    public double MarginDeg { get; set; } = 3;
    public string Applies { get; set; } = "auto";  // auto (heads for avoid/keep_in, lasers for laser_out) | heads | lasers | all
    public bool Enabled { get; set; } = true;

    public Zone(string id, string name, string kind, string shape, Vec3 center, double[] size, double rotDeg = 0, double tiltDeg = 0)
    {
        Id = id; Name = name; Kind = kind; Shape = shape; Center = center.ToArray(); Size = size; RotDeg = rotDeg; TiltDeg = tiltDeg;
        MarginDeg = kind == "laser_out" ? 5 : 2;
    }

    Zone(string id) { Id = id; Name = id; Kind = "avoid"; Shape = "rect"; Center = [0, 0, 2]; Size = [2, 2, 2]; }

    public static Zone From(JsonElement c)
    {
        var id = J.Req(c, "id", J.String);
        return new Zone(id)
        {
            Name = J.Ref(c, "name", J.String) ?? id,
            Kind = J.Ref(c, "kind", J.String) ?? "avoid",
            Shape = J.Ref(c, "shape", J.String) ?? "rect",
            Center = J.Ref(c, "center", J.ArrayOf(J.Double)) ?? [0, 0, 2],
            Size = J.Ref(c, "size", J.ArrayOf(J.Double)) ?? [2, 2, 2],
            RotDeg = J.Val(c, "rot_deg", J.Double) ?? 0,
            TiltDeg = J.Val(c, "tilt_deg", J.Double) ?? 0,
            MarginDeg = J.Val(c, "margin_deg", J.Double) ?? 3,
            Applies = J.Ref(c, "applies", J.String) ?? "auto",
            Enabled = J.Val(c, "enabled", J.Bool) ?? true,
        };
    }

    public JSONValue ToJSON() => JSONValue.Of(new Dictionary<string, JSONValue>
    {
        ["id"] = Id, ["name"] = Name, ["kind"] = Kind, ["shape"] = Shape, ["center"] = JSONValue.Of(Center.Select(JSONValue.Of)),
        ["size"] = JSONValue.Of(Size.Select(JSONValue.Of)), ["rot_deg"] = RotDeg, ["tilt_deg"] = TiltDeg,
        ["margin_deg"] = MarginDeg, ["applies"] = Applies, ["enabled"] = Enabled,
    });

    public Zone Clone()
    {
        var z = (Zone)MemberwiseClone();
        z.Center = (double[])Center.Clone();
        z.Size = (double[])Size.Clone();
        return z;
    }

    public Vec3 CenterV
    {
        get => new(Center[0], Center[1], Center.Length > 2 ? Center[2] : 0);
        set => Center = value.ToArray();
    }

    public bool IsSafety => Kind == "laser_out";

    double SizeAt(int i) => Size.Length > i ? Size[i] : 1;

    /// The zone's own axes: u along its width, v along its height (rect) / depth (box), n its normal (rect) / up (box).
    public (Vec3 U, Vec3 V, Vec3 N) Axes
    {
        get
        {
            var r = RotDeg * Math.PI / 180;
            var u = new Vec3(Math.Cos(r), Math.Sin(r), 0);
            if (Shape == "box") return (u, new Vec3(-Math.Sin(r), Math.Cos(r), 0), new Vec3(0, 0, 1));
            var t = TiltDeg * Math.PI / 180;
            var facing = new Vec3(-Math.Sin(r), Math.Cos(r), 0);               // upright: faces the audience
            var n = facing * Math.Cos(t) + new Vec3(0, 0, 1) * Math.Sin(t);    // tilted back to lie flat (normal up)
            var v = new Vec3(0, 0, 1) * Math.Cos(t) - facing * Math.Sin(t);
            return (u, v, n);
        }
    }

    /// The rectangle's four corners (rect), or the box's eight corners.
    public IReadOnlyList<Vec3> Corners
    {
        get
        {
            var (u, v, n) = Axes;
            var c = CenterV;
            if (Shape == "box")
            {
                double w = Size[0] / 2, d = SizeAt(1) / 2, h = SizeAt(2) / 2;
                (int, int, int)[] signs = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)];
                return signs.Select(s => c + u * (s.Item1 * w) + v * (s.Item2 * d) + n * (s.Item3 * h)).ToList();
            }
            double w2 = Size[0] / 2, h2 = SizeAt(1) / 2;
            return [c - u * w2 - v * h2, c + u * w2 - v * h2, c + u * w2 + v * h2, c - u * w2 + v * h2];
        }
    }

    /// Where a ray enters the zone (distance), or nil.
    public double? Hit(Vec3 o, Vec3 d)
    {
        var (u, v, n) = Axes;
        var c = CenterV;
        if (Shape == "box")  // slab test in the box's frame
        {
            var p = o - c;
            double[] lo = [Vec3.Dot(p, u), Vec3.Dot(p, v), Vec3.Dot(p, n)], dd = [Vec3.Dot(d, u), Vec3.Dot(d, v), Vec3.Dot(d, n)];
            double[] half = [Size[0] / 2, SizeAt(1) / 2, SizeAt(2) / 2];
            double t0 = double.NegativeInfinity, t1 = double.PositiveInfinity;
            for (var k = 0; k < 3; k++)
            {
                if (Math.Abs(dd[k]) < 1e-9) { if (Math.Abs(lo[k]) > half[k]) return null; continue; }
                double a = (-half[k] - lo[k]) / dd[k], b = (half[k] - lo[k]) / dd[k];
                if (a > b) (a, b) = (b, a);
                t0 = Math.Max(t0, a); t1 = Math.Min(t1, b);
                if (t0 > t1) return null;
            }
            return t1 < 0 ? null : Math.Max(t0, 0);
        }
        var den = Vec3.Dot(d, n);
        if (Math.Abs(den) <= 1e-9) return null;
        var t = Vec3.Dot(c - o, n) / den;
        if (t <= 0) return null;
        var q = o + d * t - c;
        return Math.Abs(Vec3.Dot(q, u)) <= Size[0] / 2 && Math.Abs(Vec3.Dot(q, v)) <= SizeAt(1) / 2 ? t : null;
    }

    public bool Equals(Zone? o) =>
        o is not null && Id == o.Id && Name == o.Name && Kind == o.Kind && Shape == o.Shape && Center.SequenceEqual(o.Center)
        && Size.SequenceEqual(o.Size) && RotDeg == o.RotDeg && TiltDeg == o.TiltDeg && MarginDeg == o.MarginDeg
        && Applies == o.Applies && Enabled == o.Enabled;

    public override bool Equals(object? obj) => obj is Zone z && Equals(z);
    public override int GetHashCode() => HashCode.Combine(Id, Kind, Shape, RotDeg, TiltDeg);
}
