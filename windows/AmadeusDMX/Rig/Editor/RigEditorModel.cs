// The rig editor's state: a set placed on a rig. The rig's trusses can be placed, moved, raised, turned and
// resized; the set's fixtures snap onto trusses (and move along with them), slide along them, turn, and aim.
// Fixtures not mounted yet wait on the floor in front of the stage. Several fixtures can be selected and
// dragged together, or dropped onto a truss from the inspector; auto-mount places the rest.
// Saving goes through the engine, which writes the rig (trusses, stage, zones, placements) and the set.
//
// The port of mac/Sources/AmadeusDMX/Rig/Editor/RigEditorModel.swift. Swift's RigDocument is a value: here `Doc` is
// changed in place and a change keeps a Clone() of what was there (for undo, and to see whether anything changed).
// No WinUI in this file: it is compiled into the kit's tests too.
using System.Globalization;
using System.Numerics;
using AmadeusKit;

namespace AmadeusDMX;

public enum EditorSelectionKind { Truss, Fixture, Zone }

/// What is selected: a truss, a fixture or a zone (Swift: enum EditorSelection).
public readonly record struct EditorSelection(EditorSelectionKind Kind, string Id)
{
    public static EditorSelection Truss(string id) => new(EditorSelectionKind.Truss, id);
    public static EditorSelection Fixture(string id) => new(EditorSelectionKind.Fixture, id);
    public static EditorSelection Zone(string id) => new(EditorSelectionKind.Zone, id);

    public string Key => Kind switch
    {
        EditorSelectionKind.Truss => $"truss:{Id}",
        EditorSelectionKind.Fixture => $"fixture:{Id}",
        _ => $"zone:{Id}",
    };

    public bool IsFixture => Kind == EditorSelectionKind.Fixture;
    public bool IsZone => Kind == EditorSelectionKind.Zone;
    public string? TrussId => Kind == EditorSelectionKind.Truss ? Id : null;
    public string? FixtureId => Kind == EditorSelectionKind.Fixture ? Id : null;
    public string? ZoneId => Kind == EditorSelectionKind.Zone ? Id : null;
}

/// Building trusses in the stage, like a construction game: draw a truss on the floor, click to set a tower,
/// drag a truss's end handles to stretch or turn it, a tower's top to make it taller (Swift: RigEditorModel.Tool).
public enum EditorTool { Select, Truss, Tower }

public static class EditorTools
{
    public static string? Hint(this EditorTool t) => t switch
    {
        EditorTool.Truss => "Drag on the floor to draw a truss (½ m steps, 15° turns; Alt: free). Esc: done",
        EditorTool.Tower => "Click on the floor to set a tower. Esc: done",
        _ => null,
    };
}

public sealed class RigEditorModel : Observable, IStageEditing
{
    RigDocument _doc;
    RigDocument _saved;
    /// The set on the rig as edited (Swift: `private(set) var doc`). Read it; change it through the model.
    public RigDocument Doc { get => _doc; private set { _doc = value; Changed(nameof(Doc), nameof(IsDirty)); } }

    EditorSelection? _selection;
    /// The primary selection (what the inspector shows); `Group` holds more fixtures selected along with it.
    public EditorSelection? Selection
    {
        get => _selection;
        set
        {
            _selection = value;
            if (value is { IsFixture: false }) _group = [];
            Changed(nameof(Selection), nameof(Group), nameof(SelectedFixtures));
        }
    }

    HashSet<string> _group = [];
    public IReadOnlySet<string> Group
    {
        get => _group;
        set { _group = [.. value]; Changed(nameof(Group), nameof(SelectedFixtures)); }
    }

    string? _dropTarget;
    /// While something is dragged over the stage from the inspector: the truss it would land on.
    public string? DropTarget { get => _dropTarget; private set => Set(ref _dropTarget, value); }
    /// What the pointer is over (a click would pick it): lit a little.
    string? _hovered;

    bool _snap = true;
    public bool Snap { get => _snap; set => Set(ref _snap, value); }
    bool _showZones = true;
    public bool ShowZones { get => _showZones; set { if (Set(ref _showZones, value)) Refresh(); } }

    EditorTool _tool = EditorTool.Select;
    public EditorTool Tool { get => _tool; set { _tool = value; Changed(); Message = value.Hint(); } }
    double _buildHeight = 4.5, _towerHeight = 4.0;
    /// A new truss goes up to this height (m).
    public double BuildHeight { get => _buildHeight; set => Set(ref _buildHeight, value); }
    /// A new tower is this tall (m).
    public double TowerHeight { get => _towerHeight; set => Set(ref _towerHeight, value); }
    public const double BuildGrid = 0.5, BuildAngle = 15.0;

    (string Id, Vec2 Fixed, double PlaneZ, RigDocument Before, bool New)? _stretch;
    (string Id, RigDocument Before)? _raise;

    string? _message;
    public string? Message { get => _message; set { _message = value; Changed(); } }
    bool _busy;
    public bool Busy { get => _busy; set => Set(ref _busy, value); }
    public UndoManager? UndoManager { get; set; }
    readonly Dictionary<string, FixtureDefinition?> _defs = [];
    readonly Workspace _workspace;
    (EditorSelection Sel, Vec3 Grab, Vec3 Start, RigDocument Before)? _drag;
    int _version;
    /// Goes up with every change the stage should show (the scene's key).
    public int Version { get => _version; private set { _version = value; Changed(nameof(Version), nameof(Doc), nameof(IsDirty)); } }

    public const double HangDrop = 0.42;   // a fixture under a truss: its beam centre below the truss centre
    public const double SideOut = 0.4;     // a fixture on the front/back face: its centre out from the truss centre
    public static readonly string[] Sides = ["under", "top", "front", "back"];
    public static readonly string[] TowerSides = ["front", "back", "left", "right", "top"];
    public const double TowerOut = 0.32;   // a fixture on a tower's face: its centre out from the tower's centre
    public const double TowerTop = 0.3;    // a fixture on top of a tower: its centre above the top

    /// The outward direction of a tower's face (front: towards the audience; left/right: across the stage).
    public static Vec2 TowerNormal(Truss t, string side)
    {
        var r = t.RotDeg * Math.PI / 180;
        var front = new Vec2(-Math.Sin(r), Math.Cos(r));
        return side switch
        {
            "back" => front * -1,
            "right" => new Vec2(front.Y, -front.X),
            "left" => new Vec2(-front.Y, front.X),
            _ => front,
        };
    }

    public const double Grid = 0.25;      // snapping step (m)
    public const double Spacing = 0.6;    // fixtures dropped or dragged as a group: this far apart on a truss
    public const string PayloadPrefix = "fixtures:";

    /// Swift's `rounded()`: halves away from zero.
    static double Rounded(double v) => Math.Round(v, MidpointRounding.AwayFromZero);

    RigEditorModel(Workspace workspace, RigDocument d)
    {
        _workspace = workspace;
        _doc = d;
        _saved = d.Clone();
    }

    /// The editor for a set on a rig (`set` "": the rig alone); nil when the files can't be read (Swift's init?).
    public static RigEditorModel? Create(Workspace workspace, string rig, string set)
    {
        if (workspace.Document(rig, set) is not { } d) return null;
        // fixtures placed on a tower before towers had faces stood in front of it: onto its front face now
        foreach (var f in d.Fixtures)
        {
            if (f.Truss is not { } tid || d.Trusses.FirstOrDefault(t => t.Id == tid) is not { Vertical: true } t
                || TowerSides.Contains(f.Side ?? "")) continue;
            f.Side = "front";
            Place(f, t, f.TrussPos ?? t.LengthM - 0.3, d.Width);
        }
        return new RigEditorModel(workspace, d);
    }

    public bool IsDirty => !Same(Doc, _saved);
    public string RigName => Doc.Rig;
    public string SetName => Doc.Set;

    /// Swift's `doc != saved`: the documents as the editor sees them.
    public static bool Same(RigDocument a, RigDocument b) =>
        ReferenceEquals(a, b)
        || a.Rig == b.Rig && a.Set == b.Set && a.Stage == b.Stage && a.Trusses.SequenceEqual(b.Trusses) && a.Zones.SequenceEqual(b.Zones)
           && a.Fixtures.Count == b.Fixtures.Count && a.Fixtures.Zip(b.Fixtures).All(p => p.First.SamePlace(p.Second))
           && a.Raw.Count == b.Raw.Count && a.Raw.All(p => b.Raw.TryGetValue(p.Key, out var v) && p.Value.Equals(v));

    public FixtureDefinition? Definition(string key)
    {
        if (_defs.TryGetValue(key, out var d)) return d;
        d = _workspace.Definition(key);
        _defs[key] = d;
        return d;
    }

    /// Every selected fixture: the primary one and the group.
    public IReadOnlySet<string> SelectedFixtures
    {
        get
        {
            var s = new HashSet<string>(_group);
            if (Selection?.FixtureId is { } id) s.Add(id);
            return s;
        }
    }

    public void Select(IReadOnlyList<string> fixtures)
    {
        if (fixtures.Count == 0) { Selection = null; Group = new HashSet<string>(); return; }
        Selection = EditorSelection.Fixture(fixtures[0]);
        Group = fixtures.Skip(1).ToHashSet();
        Refresh();
    }

    // MARK: - what the stage shows

    public StageInput StageInput()
    {
        var els = RigElements.Elements(Doc, Definition);
        var selected = Selection is { } s ? new List<string> { s.Key } : [];
        selected.AddRange(_group.Select(id => $"fixture:{id}"));
        if (DropTarget is { } t) selected.Add($"truss:{t}");
        if (_hovered is { } h && !selected.Contains(h)) selected.Add("hover:" + h);
        return new StageInput
        {
            Key = $"edit:{Doc.Label}:{Version}", Fixtures = els, Stage = Doc.Stage with { }, Screen = Doc.HasScreen, Hello = null,
            Trusses = Doc.Trusses.Select(x => x with { }).ToList(), Selected = selected.ToHashSet(), KeepCamera = true,
            Zones = Doc.Zones.Where(z => ShowZones || Selection == EditorSelection.Zone(z.Id)).Select(z => z.Clone()).ToList(),
        };
    }

    // MARK: - changes (all undoable)

    void Change(string name, Action<RigDocument> body)
    {
        var before = Doc.Clone();
        body(Doc);
        if (Same(Doc, before)) return;
        Version++;
        RegisterUndo(name, before);
    }

    void RegisterUndo(string name, RigDocument before)
    {
        if (UndoManager is not { } u) return;
        u.RegisterUndo(() =>
        {
            var now = Doc;
            Doc = before;
            Version++;
            RegisterUndo(name, now);
        });
        u.SetActionName(name);
    }

    void Refresh() => Version++;

    // MARK: - the venue

    public void UpdateStage(Action<Stage> body) => UpdateStage("Change Stage", body);

    public void UpdateStage(string name, Action<Stage> body) => Change(name, d =>
    {
        var stage = d.Stage with { };
        body(stage);
        d.Stage = stage;
        // merged into what was there: the stage keeps the settings the editor doesn't show (eye safety…)
        var merged = d.Raw.GetValueOrDefault("stage")?.Object is { } o ? new Dictionary<string, JSONValue>(o) : [];
        foreach (var (k, v) in d.Stage.ToJSON().Object!) merged[k] = v;
        d.Raw["stage"] = JSONValue.Of(merged);
    });

    public void SetScreen(bool on) => Change(on ? "Add LED Wall" : "Remove LED Wall", d =>
    {
        if (on) d.Raw["screen"] = JSONValue.Of(new Dictionary<string, JSONValue> { ["width_m"] = Rounded(Math.Min(10, d.Width * 0.55)) });
        else d.Raw.Remove("screen");
    });

    // MARK: - trusses

    static int FirstFree(Func<int, bool> taken)
    {
        var i = 1;
        while (taken(i)) i++;
        return i;
    }

    public void AddTruss(double length, bool vertical = false)
    {
        var n = FirstFree(i => Doc.Trusses.Any(t => t.Id == $"truss{i}"));
        var W = Doc.Width;
        var t = new Truss($"truss{n}", length, W / 2, -1.5 - Doc.Trusses.Count % 4 * 1.2,
                          vertical ? length / 2 : Math.Min(Doc.Stage.CeilingM - 1, 4.5), vertical: vertical);
        if (vertical) { t.XM = Doc.Trusses.Count(x => x.Vertical) % 2 == 0 ? -0.6 : W + 0.6; t.YM = -1.5; }
        Change(vertical ? "Add Tower" : "Add Truss", d => d.Trusses.Add(t));
        Selection = EditorSelection.Truss(t.Id);
    }

    /// A round truss (a circle, or a half circle opening towards the audience) over the middle of the stage.
    public void AddRing(double diameter, double arc = 360)
    {
        var W = Doc.Width;
        var t = Truss.Ring(NewTrussID(arc >= 359.5 ? "ring" : "arc"), diameter, arc, W / 2, -0.6 - diameter / 2,
                           Math.Min(Doc.Stage.CeilingM - 1, 4.5), arc >= 359.5 ? 0 : 180);
        Change(arc >= 359.5 ? "Add Round Truss" : "Add Half Circle", d => d.Trusses.Add(t));
        Selection = EditorSelection.Truss(t.Id);
    }

    public void UpdateTruss(string id, Action<Truss> body) => UpdateTruss(id, "Change Truss", body);

    public void UpdateTruss(string id, string name, Action<Truss> body) => Change(name, d =>
    {
        var i = d.Trusses.FindIndex(t => t.Id == id);
        if (i < 0) return;
        var oldRot = d.Trusses[i].RotDeg;
        body(d.Trusses[i]);
        d.Trusses[i].Normalise();
        var turn = d.Trusses[i].RotDeg - oldRot;
        if (turn != 0)  // clamped fixtures turn with their truss
            foreach (var f in d.Fixtures.Where(f => f.Truss == id)) f.RotDeg = Wrap(f.RotDeg + turn);
        FollowTruss(d, d.Trusses[i]);
    });

    /// Fixtures on a truss go where the truss goes.
    static void FollowTruss(RigDocument d, Truss t)
    {
        foreach (var f in d.Fixtures.Where(f => f.Truss == t.Id)) Place(f, t, f.TrussPos ?? 0, d.Width);
    }

    /// Clamp a fixture to a truss (amadeus/rig/trusses.py place: the same rules).
    public static void Place(PlacedFixture f, Truss t, double u, double width)
    {
        if (t.IsFullRing)  // round the circle: past one end is the other
        {
            u = (u + t.LengthM / 2) % t.LengthM;
            if (u < 0) u += t.LengthM;
            u -= t.LengthM / 2;
        }
        u = t.Vertical ? Math.Max(0.2, Math.Min(t.LengthM, u)) : Math.Max(-t.LengthM / 2, Math.Min(t.LengthM / 2, u));
        if (f.Truss != t.Id && !t.Vertical) f.RotDeg = t.RotDeg;  // clamped on: square to the truss
        if (t.IsRing)  // on a ring: always turned with the arc, its front out of the circle
        {
            var r = (t.DirectionDeg(u) + 180) % 360;
            if (r < 0) r += 360;
            f.RotDeg = Rounded((r - 180) * 10) / 10;
        }
        f.Truss = t.Id;
        f.TrussPos = u;
        f.Waiting = false;
        if (t.Vertical)
        {
            // a tower's four faces: the fixture hangs off the face (base against the truss, head out of it, like
            // on a box truss's side); only on top does it stand
            var side = f.Side is { } s0 && TowerSides.Contains(s0) ? s0 : "front";
            var bottom = t.ZM - t.LengthM / 2;
            f.Side = side;
            if (side == "top")
            {
                f.TrussPos = t.LengthM;
                f.X = t.XM / width;
                f.YM = t.YM;
                f.ZM = bottom + t.LengthM + TowerTop;
                f.Mount = "stand";
                f.MountRoll = null;
            }
            else
            {
                var n = TowerNormal(t, side);
                f.TrussPos = Math.Max(0.2, Math.Min(t.LengthM - 0.2, u));
                f.X = (t.XM + n.X * TowerOut) / width;
                f.YM = t.YM + n.Y * TowerOut;
                f.ZM = bottom + f.TrussPos.Value;
                f.Mount = "hang";
                f.MountRoll = 90;
                var r = Math.Atan2(-n.X, n.Y) * 180 / Math.PI;
                if (r < 0) r += 360;
                f.RotDeg = Rounded(r * 10) / 10;
            }
        }
        else
        {
            // the box truss's four sides: under it, on top, on the front (audience) or the back face
            var side = f.Side is { } s1 && Sides.Contains(s1) ? s1 : f.Mount == "stand" ? "top" : "under";
            // n: towards the audience (on a ring: out of the circle)
            var p = t.Point(u);
            var r = t.DirectionDeg(u) * Math.PI / 180;
            var n = new Vec2(-Math.Sin(r), Math.Cos(r));
            var q = p.XY;
            var z = p.Z;
            // under = 0°, front = 90°, on top = 180°, back = 270°: the fixture rolled about the truss
            switch (side)
            {
                case "top": z += HangDrop; break;
                case "front": q += n * SideOut; break;
                case "back": q -= n * SideOut; break;
                default: z -= HangDrop; break;
            }
            f.Side = side;
            f.Mount = side == "top" ? "stand" : "hang";
            f.MountRoll = side == "front" ? 90 : side == "back" ? 270 : null;
            f.X = q.X / width;
            f.YM = q.Y;
            f.ZM = z;
        }
    }

    static string Capitalized(string s) => s.Length == 0 ? s : char.ToUpperInvariant(s[0]) + s[1..];

    public void SetSide(string id, string side) => UpdateFixture(id, $"Move to {Capitalized(side)}", f => f.Side = side);

    /// Every selected fixture on a box truss: onto this side of it.
    public void SetSide(IReadOnlySet<string> ids, string side) => Change($"Move to {Capitalized(side)}", d =>
    {
        foreach (var f in d.Fixtures.Where(f => ids.Contains(f.Id)))
        {
            if (f.Truss is not { } tid || d.Trusses.FirstOrDefault(t => t.Id == tid) is not { } t
                || !(t.Vertical ? TowerSides : Sides).Contains(side)) continue;
            f.Side = side;
            Place(f, t, f.TrussPos ?? 0, d.Width);
        }
    });

    // MARK: - fixtures

    public void UpdateFixture(string id, Action<PlacedFixture> body) => UpdateFixture(id, "Change Fixture", body);

    public void UpdateFixture(string id, string name, Action<PlacedFixture> body) => Change(name, d =>
    {
        if (d.Fixtures.FirstOrDefault(f => f.Id == id) is not { } f) return;
        body(f);
        f.Waiting = false;
        if (f.Truss is { } tid && d.Trusses.FirstOrDefault(t => t.Id == tid) is { } t) Place(f, t, f.TrussPos ?? 0, d.Width);
    });

    public void Attach(string id, string? trussID) => UpdateFixture(id, trussID is null ? "Take Off Truss" : "Put on Truss", f =>
    {
        if (trussID is not null)
        {
            f.Truss = trussID;
            f.TrussPos = 0;
            if (f.Mount == "floor") f.Mount = "hang";
        }
        else
        {
            f.Truss = null; f.TrussPos = null; f.Side = null; f.MountRoll = null;
            f.Mount = "floor"; f.ZM = 0.25;
        }
    });

    /// Back to waiting in front of the stage: not mounted on this rig any more (the set keeps them).
    public void Unmount(IReadOnlySet<string> ids)
    {
        Change(ids.Count == 1 ? "Unmount Fixture" : $"Unmount {ids.Count} Fixtures", d =>
        {
            foreach (var f in d.Fixtures.Where(f => ids.Contains(f.Id)))
            {
                f.Waiting = true;
                f.Truss = null; f.TrussPos = null; f.Side = null; f.MountRoll = null;
                f.RotDeg = 0; f.Aim = null;
            }
            LineUpWaiting(d);
        });
        Selection = null;
        Group = new HashSet<string>();
    }

    /// Waiting fixtures stand in a row on the floor at the front of the stage (as the engine puts them).
    static void LineUpWaiting(RigDocument d)
    {
        var waiting = d.Fixtures.Where(f => f.Waiting).ToList();
        for (var k = 0; k < waiting.Count; k++)
        {
            waiting[k].X = (k + 1.0) / (waiting.Count + 1);
            waiting[k].YM = -0.3;
            waiting[k].ZM = 0.25;
            waiting[k].Mount = "floor";
        }
    }

    /// Fixtures in a row along a truss, centred as near `u` as there is room (or one above the other on a tower),
    /// `spacing` apart, clear of the fixtures already on that side of the truss.
    static void Arrange(RigDocument d, IReadOnlyList<string> ids, Truss t, double u, string? side, Func<PlacedFixture, double> width)
    {
        var n = (double)ids.Count;
        var own = ids.Select(id => d.Fixtures.FirstOrDefault(f => f.Id == id)).OfType<PlacedFixture>().Select(width).DefaultIfEmpty(0.4).Max();
        var step = t.Vertical ? 0.6 : Math.Max(Spacing, own + 0.15);
        var span = step * (n - 1);
        // keep the whole row on the truss
        double lo = t.Vertical ? 0.3 : -t.LengthM / 2, hi = t.Vertical ? t.LengthM - 0.3 : t.LengthM / 2;
        var mine = ids.ToHashSet();
        var busy = d.Fixtures
            .Where(f => !mine.Contains(f.Id) && f.Truss == t.Id && (t.Vertical || (f.Side ?? "under") == (side ?? "under")))
            .Where(f => f.TrussPos is not null)
            .Select(f => (Pos: f.TrussPos!.Value, Width: t.Vertical ? 0.45 : width(f))).ToList();
        bool Fits(double start) =>  // housings at least 15 cm apart
            start >= lo - 1e-6 && start + span <= hi + 1e-6
            && Enumerable.Range(0, ids.Count).All(k => busy.All(b => Math.Abs(start + step * k - b.Pos) >= (own + b.Width) / 2 + 0.15));
        var wanted = Math.Max(lo, Math.Min(hi - span, u - span / 2));
        // the nearest free stretch: try further and further to either side
        double? found = null;
        for (var i = 0; found is null; i++)
        {
            var off = i * 0.05;
            if (off > t.LengthM) break;
            if (Fits(wanted - off)) found = wanted - off;
            else if (Fits(wanted + off)) found = wanted + off;
        }
        var start = found ?? wanted;
        for (var k = 0; k < ids.Count; k++)
        {
            if (d.Fixtures.FirstOrDefault(f => f.Id == ids[k]) is not { } f) continue;
            if (f.Truss != t.Id)
            {
                f.Side = side;
                if (f.Mount == "floor" || f.Waiting) f.Mount = "hang";
            }
            Place(f, t, start + step * k, d.Width);
        }
    }

    /// Fixtures in a row on the floor around a point, left to right.
    static void LineUp(RigDocument d, IReadOnlyList<string> ids, Vec2 p)
    {
        var span = Spacing * (ids.Count - 1);
        for (var k = 0; k < ids.Count; k++)
        {
            if (d.Fixtures.FirstOrDefault(f => f.Id == ids[k]) is not { } f) continue;
            f.Truss = null; f.TrussPos = null; f.Side = null; f.MountRoll = null;
            f.Waiting = false;
            f.Mount = "floor";
            f.ZM = 0.25;
            f.X = (p.X - span / 2 + Spacing * k) / d.Width;
            f.YM = p.Y;
        }
    }

    /// Adds fixtures to the set: spread along the selected truss, or in a row on the stage floor. No start
    /// addresses: you give them on the Sets page (a guess is usually wrong, and then they overlap).
    public void AddFixtures(string key, string mode, int count)
    {
        if (Definition(key) is not { } def || count <= 0) return;
        var last = key.Split('/').LastOrDefault() ?? "";
        var letters = new string(last.TakeWhile(char.IsLetter).ToArray());
        var prefix = letters.Length == 0 ? "fx" : letters;
        Change($"Add {count} × {def.Model}", d =>
        {
            var truss = Selection?.TrussId is { } tid ? d.Trusses.FirstOrDefault(t => t.Id == tid) : null;
            var newIDs = new List<string>();
            for (var k = 0; k < count; k++)
            {
                var n = 1;
                while (d.Fixtures.Any(f => f.Id == $"{prefix}{n}") || newIDs.Contains($"{prefix}{n}")) n++;
                var id = $"{prefix}{n}";
                newIDs.Add(id);
                var f = new PlacedFixture(id, key, mode, 1, null, "floor", (k + 1.0) / (count + 1), -0.6, 0.25, 0, null, null, null);
                if (truss is { } t)
                {
                    var span = t.Vertical ? t.LengthM : t.LengthM * 0.9;
                    var pos = t.Vertical ? span * (k + 1.0) / (count + 1) : -span / 2 + span * (k + 0.5) / count;
                    f.Mount = "hang";
                    Place(f, t, pos, d.Width);
                }
                d.Fixtures.Add(f);
            }
        });
    }

    // MARK: - auto-mount

    static string Error(Exception e) => e is AggregateException { InnerException: { } inner } ? inner.Message : e.Message;

    /// Mount fixtures the engine's way (amadeus/rig/automount.py): `ids`, or the ones waiting, or `all`.
    /// One undoable change; nothing is saved until Save.
    public async Task AutoMount(IRigEditorHost host, IReadOnlyList<string>? ids = null, bool all = false)
    {
        Busy = true;
        try
        {
            if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var (places, trusses) = await host.Api.AutomountPlacements(Doc.JsonObject(), ids, all);
            Apply(places, trusses, places.Count == 1 ? "Auto-Mount Fixture" : $"Auto-Mount {places.Count} Fixtures");
            if (trusses is { Length: > 0 } && Doc.Trusses.Count == trusses.Length)
            {
                Message = $"The rig had no trusses: it has {trusses.Length} now (where its fixtures hung, or a standard set-up)";
                return;
            }
            Message = places.Count == 0 ? "Everything is mounted already" : $"Mounted {places.Count} fixture{(places.Count == 1 ? "" : "s")}";
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            Message = Error(e);
        }
        finally { Busy = false; }
    }

    /// The hang sheet of the layout as it is now (saved or not), opened in the browser to print or save as PDF:
    /// where every fixture goes, which way round, its DMX address, and labels for the fixtures.
    public async Task HangSheet(IRigEditorHost host)
    {
        Busy = true;
        try
        {
            if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var page = await host.Api.HangSheet(Doc.JsonObject(), Doc.Set, Doc.Rig);
            var path = Path.Combine(Path.GetTempPath(), FileName($"Hang Sheet – {Doc.Set} on {Doc.Rig}.html"));
            await File.WriteAllBytesAsync(path, page);
            host.Open(path);
            Message = Doc.WaitingCount > 0 ? $"{Doc.WaitingCount} fixtures aren’t mounted yet: they’re not on the sheet" : "Hang sheet opened in your browser";
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            Message = Error(e);
        }
        finally { Busy = false; }
    }

    /// A file name without the characters Windows doesn't allow in one.
    static string FileName(string s) => string.Concat(s.Select(c => Path.GetInvalidFileNameChars().Contains(c) || c is ':' or '/' or '\\' ? '-' : c));

    // MARK: - the check after hanging

    /// The check after hanging: every fixture lit on its own in the hang sheet's order, a moving head pointing its
    /// beam a known way. What the crew sees wrong is put right here: two fixtures swapped, a head mirrored or turned
    /// round (its calibration). The changes are the editor's like any other: undo, Save.
    public sealed class HangCheck(IReadOnlyList<HangCheckStep> steps)
    {
        public IReadOnlyList<HangCheckStep> Steps { get; set; } = steps;
        public int Index { get; set; }
        public string Output { get; set; } = "";                 // where its DMX goes, in words
        public Dictionary<string, string> Fixed { get; } = [];   // fixture id → what was put right
        public HangCheckStep? Step => Index >= 0 && Index < Steps.Count ? Steps[Index] : null;
    }

    HangCheck? _check;
    public HangCheck? Check { get => _check; set { _check = value; Changed(); } }
    void CheckChanged() => Changed(nameof(Check));

    Dictionary<string, JSONValue> LayoutDict() => Doc.JsonObject();

    public async Task StartCheck(IRigEditorHost host)
    {
        Busy = true;
        try
        {
            if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var steps = await host.Api.HangCheck(LayoutDict());
            if (steps.Length == 0) { Message = "Nothing to check: no fixture is mounted yet"; return; }
            Check = new HangCheck(steps);
            await LightCheck(host);
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            Message = Error(e);
        }
        finally { Busy = false; }
    }

    public async Task StopCheck(IRigEditorHost host)
    {
        if (Check?.Step?.Id is not { } id) { Check = null; return; }
        Check = null;
        await Quietly(() => host.Api.TestLight(id, false, LayoutDict(), false));
    }

    static async Task Quietly(Func<Task> op)  // Swift's `_ = try? await …`
    {
        try { await op(); }
        catch (Exception e) when (e is not OutOfMemoryException) { }
    }

    public async Task MoveCheck(IRigEditorHost host, int index)
    {
        if (Check is not { } c || index < 0 || index >= c.Steps.Count) return;
        if (c.Step?.Id is { } id && id != c.Steps[index].Id)
            await Quietly(() => host.Api.TestLight(id, false, LayoutDict(), false));
        if (Check is null) return;
        Check.Index = index;
        CheckChanged();
        await LightCheck(host);
    }

    /// Light the step's fixture (with the layout as it is now, fixes and all) and select it in the view.
    async Task LightCheck(IRigEditorHost host)
    {
        if (Check?.Step is not { } step) return;
        Selection = EditorSelection.Fixture(step.Id);
        Group = new HashSet<string>();
        if (step.Dark.Length > 0) { Check.Output = ""; CheckChanged(); return; }
        string output;
        try
        {
            var r = await host.Api.TestLight(step.Id, true, LayoutDict(), step.Moving);
            output = r.Summary;
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            output = Error(e);
        }
        if (Check is { } now) { now.Output = output; CheckChanged(); }
    }

    /// The head is hung wrong the way the crew saw: its calibration put right, and lit again to see.
    public async Task FixCheck(IRigEditorHost host, HangCheckStep.Fault fault)
    {
        if (Check?.Step is not { } step) return;
        try
        {
            var fields = await host.Api.HangCheckFix(LayoutDict(), step.Id, fault.Fix);
            Change($"Fix {step.Label}", d => d.Calibrate(step.Id, fields));
            if (Check is { } c) c.Fixed[step.Id] = FixText.GetValueOrDefault(fault.Fix) ?? fault.Fix;
            CheckChanged();
            await RelightCheck(host);
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            Message = Error(e);
        }
    }

    public static readonly IReadOnlyDictionary<string, string> FixText = new Dictionary<string, string>
    {
        ["mirrored"] = "pans the other way now", ["turned"] = "turned round now", ["both"] = "turned round and pans the other way now",
    };

    /// The fixture lit at another step's place: the two trade places in the layout. The step stays at its place,
    /// now with the other fixture, lit to see.
    public async Task SwapCheck(IRigEditorHost host, HangCheckStep other)
    {
        if (Check?.Step is not { } step || step.Id == other.Id) return;
        Change($"Swap {step.Label} and {other.Label}", d => d.SwapPlacements(step.Id, other.Id));
        await Quietly(() => host.Api.TestLight(step.Id, false, LayoutDict(), false));
        if (Check is { } c)
        {
            c.Fixed[other.Id] = $"swapped with {step.Id}";
            c.Fixed[step.Id] = $"swapped with {other.Id}";
            CheckChanged();
        }
        await RelightCheck(host);
    }

    /// The steps again after a change (a swap changes which fixture is at a place), at the same place.
    async Task RelightCheck(IRigEditorHost host)
    {
        if (Check is not { } c) return;
        try
        {
            var steps = await host.Api.HangCheck(LayoutDict());
            if (steps.Length > 0 && Check is { } now)
            {
                now.Steps = steps;
                now.Index = Math.Min(c.Index, steps.Length - 1);
                CheckChanged();
            }
        }
        catch (Exception e) when (e is not OutOfMemoryException) { }
        await LightCheck(host);
    }

    /// The fixtures on the spots they already take, put in name order along the rig: top1 at the first place,
    /// top2 at the next (the hang sheet's order), so a name and a place count the same way.
    public async Task PutInOrder(IRigEditorHost host)
    {
        Busy = true;
        try
        {
            if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var places = await host.Api.InOrderPlacements(Doc.JsonObject());
            Apply(places, null, "Put in Name Order");
            Message = places.Count == 0 ? "Already in name order" : $"{places.Count} fixtures in name order now";
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            Message = Error(e);
        }
        finally { Busy = false; }
    }

    /// Placements (fixture id → position fields, as in a rig file) onto the fixtures.
    public void Apply(IReadOnlyDictionary<string, Dictionary<string, JSONValue>> places, IReadOnlyList<Truss>? trusses, string name) =>
        Change(name, d =>
        {
            if (trusses is not null && d.Trusses.Count == 0) d.Trusses = trusses.Select(t => t with { }).ToList();  // a rig without trusses got its structure
            foreach (var f in d.Fixtures)
            {
                if (!places.TryGetValue(f.Id, out var p)) continue;
                f.Waiting = false;
                f.Mount = p.GetValueOrDefault("mount")?.String ?? "stand";
                f.X = p.GetValueOrDefault("x")?.Number ?? f.X;
                f.YM = p.GetValueOrDefault("y_m")?.Number ?? f.YM;
                f.ZM = p.GetValueOrDefault("z_m")?.Number ?? f.ZM;
                f.RotDeg = p.GetValueOrDefault("rot_deg")?.Number ?? 0;
                f.Aim = p.GetValueOrDefault("aim")?.Array is { Count: 2 } a ? new Vec2(a[0].Number ?? 0, a[1].Number ?? 0) : null;
                f.Truss = p.GetValueOrDefault("truss")?.String;
                f.TrussPos = p.GetValueOrDefault("truss_pos_m")?.Number;
                f.Side = p.GetValueOrDefault("truss_side")?.String;
                f.MountRoll = p.GetValueOrDefault("mount_roll_deg")?.Number;
            }
            LineUpWaiting(d);
        });

    // MARK: - zones

    public enum ZonePreset { Wall, FloorArea, KeepIn, LaserAudience, LaserPlane }

    public static readonly ZonePreset[] ZonePresets = Enum.GetValues<ZonePreset>();

    public static string Title(ZonePreset p) => p switch
    {
        ZonePreset.Wall => "Keep Beams Off a Wall or Set Piece",
        ZonePreset.FloorArea => "Keep Beams Off a Floor Area",
        ZonePreset.KeepIn => "Keep Beams Inside an Area",
        ZonePreset.LaserAudience => "Laser Safety: Audience Box (no lasers)",
        _ => "Laser Safety: Floating Plane",
    };

    public static string Symbol(ZonePreset p) => p switch
    {
        ZonePreset.Wall => "rectangle.portrait",
        ZonePreset.FloorArea => "rectangle.dashed",
        ZonePreset.KeepIn => "cube.transparent",
        ZonePreset.LaserAudience => "person.3.fill",
        _ => "square.3.layers.3d.down.right",
    };

    public void AddZone(ZonePreset p)
    {
        var W = Doc.Width;
        var D = Doc.Stage.RoomDepthM;
        var back = Math.Min(-2.5, (Doc.Fixtures.Count == 0 ? -1 : Doc.Fixtures.Min(f => f.YM)) - 1.5);  // the room's back wall (as the visualisers place it)
        var n = FirstFree(i => Doc.Zones.Any(z => z.Id == $"zone{i}"));
        var id = $"zone{n}";
        var z = p switch
        {
            ZonePreset.Wall => new Zone(id, "Back wall", "avoid", "rect", new Vec3(W / 2, back + 0.1, 3), [Math.Min(W, 8), 4]),
            ZonePreset.FloorArea => new Zone(id, "VIP corner", "avoid", "rect", new Vec3(W * 0.85, D * 0.3, 0.05), [3, 3], tiltDeg: 90),
            ZonePreset.KeepIn => new Zone(id, "Dance floor and sky", "keep_in", "box", new Vec3(W / 2, D * 0.35, Doc.Stage.CeilingM / 2),
                                          [W + 2, D * 0.7, Doc.Stage.CeilingM]),
            ZonePreset.LaserAudience => new Zone(id, "Audience (no lasers)", "laser_out", "box", new Vec3(W / 2, D / 2 + 0.25, 1.5),
                                                 [W + 6, D - 0.5, 3]),
            _ => new Zone(id, "No lasers below", "laser_out", "rect", new Vec3(W / 2, D / 2, 3.0), [W + 6, D], tiltDeg: 90),
        };
        Change("Add Zone", d => d.Zones.Add(z));
        Selection = EditorSelection.Zone(z.Id);
    }

    public void UpdateZone(string id, Action<Zone> body) => UpdateZone(id, "Change Zone", body);

    public void UpdateZone(string id, string name, Action<Zone> body) => Change(name, d =>
    {
        if (d.Zones.FirstOrDefault(z => z.Id == id) is { } z) body(z);
    });

    /// Delete/Backspace: a zone or truss is deleted; fixtures are unmounted (they stay in the set, waiting in front).
    public void DeleteSelection()
    {
        if (Selection is not { } sel) return;
        switch (sel.Kind)
        {
            case EditorSelectionKind.Zone:
                Change("Delete Zone", d => d.Zones.RemoveAll(z => z.Id == sel.Id));
                break;
            case EditorSelectionKind.Truss:
                Change("Delete Truss", d =>
                {
                    d.Trusses.RemoveAll(t => t.Id == sel.Id);
                    foreach (var f in d.Fixtures.Where(f => f.Truss == sel.Id))
                    {
                        f.Truss = null; f.TrussPos = null;
                        f.Mount = "floor"; f.ZM = 0.25;
                    }
                });
                break;
            case EditorSelectionKind.Fixture:
                Unmount(SelectedFixtures);
                return;
        }
        Selection = null;
    }

    public void DuplicateSelection()
    {
        if (Selection?.ZoneId is { } zid && Doc.Zones.FirstOrDefault(z => z.Id == zid) is { } zone)
        {
            var n = FirstFree(i => Doc.Zones.Any(z => z.Id == $"zone{i}"));
            var c = zone.Clone();
            c.Id = $"zone{n}"; c.Name = zone.Name + " copy";
            c.CenterV += new Vec3(1, 1, 0);
            Change("Duplicate Zone", d => d.Zones.Add(c));
            Selection = EditorSelection.Zone(c.Id);
            return;
        }
        if (Selection?.TrussId is not { } id || Doc.Trusses.FirstOrDefault(t => t.Id == id) is not { } truss) return;
        var m = FirstFree(i => Doc.Trusses.Any(t => t.Id == $"truss{i}"));
        var copy = truss with { Id = $"truss{m}" };
        if (truss.Vertical) copy.XM += 1.0; else copy.YM -= 1.5;
        Change("Duplicate Truss", d => d.Trusses.Add(copy));
        Selection = EditorSelection.Truss(copy.Id);
    }

    public void RotateSelection(double by)
    {
        switch (Selection)
        {
            case { Kind: EditorSelectionKind.Truss, Id: var id }:
                UpdateTruss(id, "Rotate Truss", t => t.RotDeg = Wrap(t.RotDeg + by));
                break;
            case { Kind: EditorSelectionKind.Fixture }:
                var ids = SelectedFixtures;
                Change("Rotate", d =>
                {
                    foreach (var f in d.Fixtures.Where(f => ids.Contains(f.Id)))
                    {
                        f.RotDeg = Wrap(f.RotDeg + by);
                        f.Waiting = false;
                    }
                });
                break;
            case { Kind: EditorSelectionKind.Zone, Id: var zid }:
                UpdateZone(zid, "Rotate Zone", z => z.RotDeg = Wrap(z.RotDeg + by));
                break;
        }
    }

    public void Nudge(double dx, double dy)
    {
        switch (Selection)
        {
            case { Kind: EditorSelectionKind.Truss, Id: var id }:
                UpdateTruss(id, "Move Truss", t => { t.XM += dx; t.YM += dy; });
                break;
            case { Kind: EditorSelectionKind.Fixture }:
                var ids = SelectedFixtures;
                Change("Move", d =>
                {
                    foreach (var f in d.Fixtures.Where(f => ids.Contains(f.Id)))
                    {
                        f.Waiting = false;
                        if (f.Truss is { } tid && d.Trusses.FirstOrDefault(t => t.Id == tid) is { } t)
                            Place(f, t, (f.TrussPos ?? 0) + dx, d.Width);
                        else
                        {
                            f.X += dx / d.Width; f.YM += dy;
                        }
                    }
                });
                break;
            case { Kind: EditorSelectionKind.Zone, Id: var zid }:
                UpdateZone(zid, "Move Zone", z => z.CenterV += new Vec3(dx, dy, 0));
                break;
        }
    }

    /// ↑ / ↓ on fixtures clamped to a truss: round the truss to its next side (under → front → top → back), or
    /// round a tower to its next face (front → right → back → left). False if none of them is on a truss.
    public bool RollAround(int step)
    {
        if (Selection is not { IsFixture: true }) return false;
        var ids = SelectedFixtures;
        if (!Doc.Fixtures.Any(f => ids.Contains(f.Id) && f.Truss is not null)) return false;
        Change(step > 0 ? "Round the Truss" : "Round the Truss Back", d =>
        {
            foreach (var f in d.Fixtures.Where(f => ids.Contains(f.Id)))
            {
                if (f.Truss is not { } tid || d.Trusses.FirstOrDefault(t => t.Id == tid) is not { } t) continue;
                string[] order = t.Vertical ? ["front", "right", "back", "left"] : ["under", "front", "top", "back"];
                var now = f.Side ?? (t.Vertical ? "front" : f.Mount == "stand" ? "top" : "under");
                var k = Math.Max(0, Array.IndexOf(order, now));
                f.Side = order[((k + step) % order.Length + order.Length) % order.Length];
                f.Waiting = false;
                Place(f, t, f.TrussPos ?? 0, d.Width);
            }
        });
        return true;
    }

    public static double Wrap(double a)
    {
        a %= 360;
        if (a > 180) a -= 360;
        if (a <= -180) a += 360;
        return a;
    }

    // MARK: - save / revert

    /// Saved through the engine's setup API: it splits the layout into the rig file and the set file.
    public async Task Save(IRigEditorHost host)
    {
        if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
        var layout = Doc.JsonObject();
        var saving = Doc.Clone();
        if (Doc.Set.Length == 0)  // the rig alone
            await host.Api.SaveRigStructure(layout, Doc.Rig);
        else
            await host.Api.SaveRig(layout, Doc.Rig, Doc.Set);
        _saved = saving;
        Changed(nameof(IsDirty));
        Message = $"Saved {Doc.Rig}";
        host.ReloadSets();
    }

    /// The files changed (an auto-mount from elsewhere, a fixture added to the set): read them again, unless
    /// there are unsaved changes here.
    public void ReloadIfClean()
    {
        if (IsDirty || _workspace.Document(Doc.Rig, Doc.Set) is not { } d || Same(d, Doc)) return;
        Doc = d;
        _saved = d.Clone();
        Selection = null;
        Group = new HashSet<string>();
        Refresh();
    }

    public void Revert()
    {
        var before = Doc;
        Doc = _saved.Clone();
        Refresh();
        RegisterUndo("Revert", before);
    }

    // MARK: - picking and dragging (StageEditing)

    static Vec3 S(Vector3 v) => new(v.X, v.Y, v.Z);

    static double Dot(Vec3 a, Vec3 b) => Vec3.Dot(a, b);

    /// Distance from a ray to a segment, and how far along the ray.
    static (double Dist, double T) RayToSegment(Vec3 o, Vec3 d, Vec3 a, Vec3 b)
    {
        var u = b - a;
        var w = o - a;
        double A = Dot(d, d), B = Dot(d, u), C = Dot(u, u), D = Dot(d, w), E = Dot(u, w);
        var den = A * C - B * B;
        var tc = den > 1e-9 ? (A * E - B * D) / den : E / Math.Max(C, 1e-9);
        tc = Math.Max(0, Math.Min(1, tc));
        var sc = Math.Max(0, (B * tc - D) / A);
        return (((o + d * sc) - (a + u * tc)).Length, sc);
    }

    /// The truss a ray passes closest to (within `radius`), and where along it.
    (Truss Truss, double U)? TrussNear(Vec3 o, Vec3 d, double radius)
    {
        (Truss T, double U, double Dist)? best = null;
        foreach (var t in Doc.Trusses)
        {
            IReadOnlyList<(Vec3 A, Vec3 B)> pieces = t.Vertical ? [(new Vec3(t.XM, t.YM, 0), new Vec3(t.XM, t.YM, t.ZM + t.LengthM / 2))] : t.Pieces();
            foreach (var (a, b) in pieces)
            {
                var (dist, along) = RayToSegment(o, d, a, b);
                if (!(dist < radius) || best is { } bb && !(dist < bb.Dist)) continue;
                var hit = o + d * along;
                var u = t.Vertical ? hit.Z - (t.ZM - t.LengthM / 2) : t.Project(hit.XY).U;
                best = (t, u, dist);
            }
        }
        return best is { } r ? (r.T, r.U) : null;
    }

    // MARK: - building trusses

    static Vec2? Plane(Vec3 o, Vec3 d, double z)
    {
        if (!(Math.Abs(d.Z) > 1e-4)) return null;
        var t = (z - o.Z) / d.Z;
        if (!(t > 0)) return null;
        return (o + d * t).XY;
    }

    Vec2 Snapped(Vec2 p)
    {
        if (!Snap) return p;
        const double g = BuildGrid;
        return new Vec2(Rounded(p.X / g) * g, Rounded(p.Y / g) * g);
    }

    string NewTrussID(string prefix) => $"{prefix}{FirstFree(i => Doc.Trusses.Any(t => t.Id == $"{prefix}{i}"))}";

    /// The end points of a horizontal truss, seen from above.
    static (Vec2, Vec2) Ends(Truss t) => (t.Point(-t.LengthM / 2).XY, t.Point(t.LengthM / 2).XY);

    /// A press in a build tool, or on a selected truss's handle: true if it starts a build drag.
    bool PickBuild(Vec3 o, Vec3 d)
    {
        switch (Tool)
        {
            case EditorTool.Truss:
            {
                if (Plane(o, d, 0) is not { } p0) return false;
                var p = Snapped(p0);
                var before = Doc.Clone();
                var t = new Truss(NewTrussID("truss"), 0, p.X, p.Y, BuildHeight);
                Doc.Trusses.Add(t);
                Selection = EditorSelection.Truss(t.Id);
                _stretch = (t.Id, p, 0, before, true);
                Refresh();
                return true;
            }
            case EditorTool.Tower:
            {
                if (Plane(o, d, 0) is not { } p0) return false;
                var p = Snapped(p0);
                var t = new Truss(NewTrussID("tower"), TowerHeight, p.X, p.Y, TowerHeight / 2, vertical: true);
                Change("Place Tower", x => x.Trusses.Add(t));
                Selection = EditorSelection.Truss(t.Id);
                return true;
            }
            default:
            {
                if (Selection?.TrussId is not { } id || Doc.Trusses.FirstOrDefault(x => x.Id == id) is not { } t) return false;
                if (t.Vertical)  // the handle on top: taller or shorter
                {
                    var top = new Vec3(t.XM, t.YM, t.ZM + t.LengthM / 2);
                    if (RayToSegment(o, d, top, top + new Vec3(0, 0, 0.01)).Dist < 0.35) { _raise = (id, Doc.Clone()); return true; }
                    return false;
                }
                if (t.IsRing) return false;  // a ring has no ends to stretch: its size is in the inspector
                var (a, b) = Ends(t);
                foreach (var (end, other) in new[] { (a, b), (b, a) })
                {
                    var p = new Vec3(end.X, end.Y, t.ZM);
                    if (RayToSegment(o, d, p, p + new Vec3(0, 0, 0.01)).Dist < 0.35)  // an end handle: stretch or turn
                    {
                        _stretch = (id, other, t.ZM, Doc.Clone(), false);
                        return true;
                    }
                }
                return false;
            }
        }
    }

    static readonly CultureInfo Posix = CultureInfo.InvariantCulture;

    /// Dragging a build: true if one is going on.
    bool DragBuild(Vec3 o, Vec3 d, bool free)
    {
        if (_stretch is { } st)
        {
            var i = Doc.Trusses.FindIndex(t => t.Id == st.Id);
            if (i < 0 || Plane(o, d, st.PlaneZ) is not { } p0) return true;
            var p = free ? p0 : Snapped(p0);
            var v = p - st.Fixed;
            var length = v.Length;
            var angle = Math.Atan2(v.Y, v.X) * 180 / Math.PI;
            if (Snap && !free)
            {
                length = Rounded(length / BuildGrid) * BuildGrid;
                angle = Rounded(angle / BuildAngle) * BuildAngle;
            }
            var r = angle * Math.PI / 180;
            v = new Vec2(Math.Cos(r), Math.Sin(r)) * length;
            var t = Doc.Trusses[i];
            t.LengthM = length;
            t.RotDeg = Wrap(angle);
            t.XM = st.Fixed.X + v.X / 2;
            t.YM = st.Fixed.Y + v.Y / 2;
            FollowTruss(Doc, t);
            Message = string.Format(Posix, "{0:0.0} m at {1:0}°", length, Wrap(angle));
            Refresh();
            return true;
        }
        if (_raise is { } rs)
        {
            var i = Doc.Trusses.FindIndex(t => t.Id == rs.Id);
            if (i < 0) return true;
            var t = Doc.Trusses[i];
            // the pointer on an upright plane through the tower, facing the camera
            var n0 = new Vec3(d.X + 1e-9, d.Y, 0);
            var n = n0 / n0.Length;
            var a = new Vec3(t.XM, t.YM, 0);
            var den = Dot(d, n);
            if (!(Math.Abs(den) > 1e-6)) return true;
            var z = (o + d * (Dot(a - o, n) / den)).Z;
            var length = Math.Max(1, z);
            if (Snap && !free) length = Math.Max(1, Rounded(length / BuildGrid) * BuildGrid);
            t.LengthM = length;
            t.ZM = length / 2;
            FollowTruss(Doc, t);
            Message = string.Format(Posix, "tower {0:0.0} m", length);
            Refresh();
            return true;
        }
        return false;
    }

    public bool Pick(Vector3 origin, Vector3 dir, bool extend)
    {
        Vec3 o = S(origin), d = S(dir);
        if (PickBuild(o, d)) return true;
        if (Tool != EditorTool.Select) return true;  // building: the camera doesn't turn under the pointer
        if (Hit(o, d) is not { } b) return false;
        return Grab(b, extend);
    }

    /// What is under the pointer: a fixture when the ray passes right over it, else the nearest truss (as seen
    /// from the camera: a tolerance of about 1.5° of view, at least 30 cm), else a zone.
    (EditorSelection Sel, double Score, Vec3 At)? Hit(Vec3 o, Vec3 d)
    {
        (EditorSelection Sel, double Score, Vec3 At)? best = null;
        void Consider(EditorSelection sel, Vec3 a, Vec3 b, double radius)
        {
            var (dist, t) = RayToSegment(o, d, a, b);
            var tolerance = Math.Max(radius, t * PickAngle);
            if (!(dist < tolerance)) return;
            // how close the pointer is, as seen from the camera; a fixture right under the pointer wins from the
            // truss it hangs on, but a click on the truss between fixtures is the truss
            var score = dist / Math.Max(t, 0.5);
            if (sel.IsFixture && dist < FixtureCore) score -= 1;
            if (best is not { } bb || score < bb.Score) best = (sel, score, o + d * t);
        }
        foreach (var f in Doc.Fixtures)
        {
            var p = f.Position(Doc.Width);
            var def = Definition(f.Key);
            var L = (def?.Cells(f.Mode) ?? 1) > 1 ? def?.Size.X ?? 1 : 0.0;
            var r = f.RotDeg * Math.PI / 180;
            var ax = new Vec3(Math.Cos(r), Math.Sin(r), 0) * (L / 2);
            Consider(EditorSelection.Fixture(f.Id), p - ax, p + ax, 0.22);
            if (f.Mount == "stand" && f.Truss is null && p.Z > 0.6)  // its stand is the fixture too
                Consider(EditorSelection.Fixture(f.Id), new Vec3(p.X, p.Y, 0), new Vec3(p.X, p.Y, p.Z - 0.2), 0.15);
        }
        foreach (var t in Doc.Trusses)
        {
            if (t.Vertical)
                Consider(EditorSelection.Truss(t.Id), new Vec3(t.XM, t.YM, 0), new Vec3(t.XM, t.YM, t.ZM + t.LengthM / 2), 0.3);
            else
                foreach (var (a, b) in t.Pieces()) Consider(EditorSelection.Truss(t.Id), a, b, 0.3);
        }
        if (best is null)  // zones last: they're big and see-through, never in the way of rigging
        {
            // overlapping zones: the smallest wins (a big keep-in box would otherwise grab every click;
            // it stays selectable from the list)
            (Zone Z, double T, double Size)? pickZone = null;
            foreach (var z in Doc.Zones)
            {
                if (z.Hit(o, d) is not { } t) continue;
                var size = z.Shape == "box" ? Math.Pow(z.Size.Aggregate(1.0, (x, y) => x * y), 2.0 / 3.0) : z.Size.Take(2).Aggregate(1.0, (x, y) => x * y);
                if (pickZone is not { } pz || size < pz.Size) pickZone = (z, t, size);
            }
            if (pickZone is { } p) best = (EditorSelection.Zone(p.Z.Id), p.T, o + d * p.T);
        }
        return best;
    }

    public const double PickAngle = 0.026;     // ~1.5° of view: how close to something a click must be
    public const double FixtureCore = 0.2;     // a click this close to a fixture (m) is the fixture, not its truss

    /// The pointer moved over the stage: light up what a click would pick.
    public void Hover(Vector3 origin, Vector3 dir)
    {
        var key = Tool == EditorTool.Select ? Hit(S(origin), S(dir))?.Sel.Key : null;
        if (key != _hovered) { _hovered = key; Refresh(); }
    }

    bool Grab((EditorSelection Sel, double Score, Vec3 At) b, bool extend)
    {
        if (b.Sel.FixtureId is { } id)
        {
            if (extend)  // Shift-click: add to (or take out of) the selection
            {
                var all = new HashSet<string>(SelectedFixtures);
                if (!all.Remove(id)) all.Add(id);
                var ordered = new[] { id }.Concat(all.Where(x => x != id).Order(StringComparer.Ordinal)).ToList();
                Select(all.Contains(id) ? ordered : all.Order(StringComparer.Ordinal).ToList());
                if (!all.Contains(id)) return true;
            }
            else if (!SelectedFixtures.Contains(id))
            {
                Group = new HashSet<string>();
                Selection = b.Sel;
            }
            else  // a click on one of the selected fixtures: it leads, the others come along
            {
                var rest = new HashSet<string>(SelectedFixtures);
                rest.Remove(id);
                Selection = b.Sel;
                Group = rest;
            }
        }
        else
        {
            Group = new HashSet<string>();
            Selection = b.Sel;
        }
        Refresh();
        var start = b.Sel.Kind switch
        {
            EditorSelectionKind.Truss => TrussCentre(Doc.Trusses.First(t => t.Id == b.Sel.Id)),
            EditorSelectionKind.Fixture => Doc.Fixtures.First(f => f.Id == b.Sel.Id).Position(Doc.Width),
            _ => Doc.Zones.First(z => z.Id == b.Sel.Id).CenterV,
        };
        _drag = (b.Sel, b.At, start, Doc.Clone());
        return true;
    }

    static Vec3 TrussCentre(Truss t) => new(t.XM, t.YM, t.ZM);

    public void Drag(Vector3 origin, Vector3 dir, bool free)
    {
        if (DragBuild(S(origin), S(dir), free)) return;
        if (_drag is not { } g) return;
        Vec3 o = S(origin), d = S(dir);
        // move in the horizontal plane at the height where it was grabbed
        if (!(Math.Abs(d.Z) > 1e-4)) return;
        var t0 = (g.Grab.Z - o.Z) / d.Z;
        if (!(t0 > 0)) return;
        var hit = o + d * t0;
        var target = g.Start + (hit - g.Grab);
        const double grid = Grid;
        var snapOn = Snap && !free;
        Vec3 SnapXY(Vec3 v) => snapOn ? v with { X = Rounded(v.X / grid) * grid, Y = Rounded(v.Y / grid) * grid } : v;
        switch (g.Sel.Kind)
        {
            case EditorSelectionKind.Zone:
            {
                target = SnapXY(target);
                if (Doc.Zones.FirstOrDefault(z => z.Id == g.Sel.Id) is { } z) z.CenterV = new Vec3(target.X, target.Y, z.CenterV.Z);
                break;
            }
            case EditorSelectionKind.Truss:
            {
                target = SnapXY(target);
                if (Doc.Trusses.FirstOrDefault(t => t.Id == g.Sel.Id) is { } t)
                {
                    t.XM = target.X;
                    t.YM = target.Y;
                    FollowTruss(Doc, t);
                }
                break;
            }
            case EditorSelectionKind.Fixture:
            {
                var id = g.Sel.Id;
                if (Doc.Fixtures.FirstOrDefault(x => x.Id == id) is not { } f) return;
                f.Waiting = false;
                var p2 = target.XY;
                // snap onto the nearest truss within reach (towers by their footprint)
                var near = Doc.Trusses.Select(t => (T: t, P: t.Project(p2))).Where(x => x.P.Distance < 0.9).ToList();
                if (near.Count > 0 && (Snap || !free))
                {
                    var (tr, pr) = near.MinBy(x => x.P.Distance);
                    var u = tr.Vertical ? (f.Truss == tr.Id ? f.TrussPos ?? 1 : Math.Min(tr.LengthM - 0.3, 1.0)) : pr.U;
                    if (snapOn && !tr.Vertical) u = Rounded(u / grid) * grid;
                    if (f.Truss != tr.Id && f.Mount == "floor") { f.Mount = "hang"; f.Side = null; }
                    if (tr.Vertical)  // dragged off one side of the tower: onto that face (on top stays on top)
                    {
                        var off = p2 - new Vec2(tr.XM, tr.YM);
                        if (off.Length > 0.12 && f.Side != "top")
                            f.Side = new[] { "front", "back", "left", "right" }.MaxBy(s => Vec2.Dot(off, TowerNormal(tr, s)));
                        else if (f.Truss != tr.Id) f.Side = "front";
                    }
                    else  // dragged across the truss: onto its front or back face (centre: under / on top)
                    {
                        var r = tr.RotDeg * Math.PI / 180;
                        var n = new Vec2(-Math.Sin(r), Math.Cos(r));
                        var across = Vec2.Dot(p2 - tr.Point(pr.U).XY, n);
                        if (across > 0.2) f.Side = "front";
                        else if (across < -0.2) f.Side = "back";
                        else if (f.Side is "front" or "back" || f.Truss != tr.Id) f.Side = f.Mount == "stand" ? "top" : "under";
                    }
                    Place(f, tr, u, Doc.Width);
                    if (_group.Count > 0)  // the others come along, in a row on the same truss
                    {
                        var ids = RowOrder([id, .. _group], g.Before);
                        Arrange(Doc, ids, tr, GroupCentre(ids, id, u), f.Side, HousingWidth);
                    }
                }
                else
                {
                    target = SnapXY(target);
                    var delta = new Vec2(target.X - g.Start.X, target.Y - g.Start.Y);
                    if (f.Truss is not null) { f.Truss = null; f.TrussPos = null; f.Side = null; f.MountRoll = null; f.Mount = "floor"; f.ZM = 0.25; }
                    f.X = target.X / Doc.Width;
                    f.YM = target.Y;
                    foreach (var other in _group)  // the others move by as much, onto the floor
                    {
                        if (Doc.Fixtures.FirstOrDefault(x => x.Id == other) is not { } o2
                            || g.Before.Fixtures.FirstOrDefault(x => x.Id == other) is not { } was) continue;
                        var p = was.Position(Doc.Width);
                        o2.Waiting = false;
                        o2.Truss = null; o2.TrussPos = null; o2.Side = null; o2.MountRoll = null; o2.Mount = "floor"; o2.ZM = 0.25;
                        o2.X = (p.X + delta.X) / Doc.Width;
                        o2.YM = was.Waiting ? f.YM : p.Y + delta.Y;
                    }
                }
                break;
            }
        }
        Refresh();
    }

    /// How much of a truss a fixture takes up: its housing's width (a bar's length).
    double HousingWidth(PlacedFixture f) => Definition(f.Key)?.Size.X ?? 0.4;

    /// The order of a group in a row: as they were, left to right.
    static List<string> RowOrder(IEnumerable<string> ids, RigDocument before) =>
        ids.OrderBy(a => before.Fixtures.FirstOrDefault(f => f.Id == a)?.X ?? 0).ToList();  // stable, like Swift's sort here

    /// Where a group's row is centred so that the leading fixture stays under the pointer.
    static double GroupCentre(IReadOnlyList<string> ids, string lead, double leadU)
    {
        var k = (double)Math.Max(0, ids.ToList().IndexOf(lead));
        var n = (double)ids.Count;
        return leadU - (k - (n - 1) / 2) * Spacing;
    }

    public void EndDrag()
    {
        if (_stretch is { } st)
        {
            _stretch = null;
            if (Doc.Trusses.FirstOrDefault(t => t.Id == st.Id) is { } t && t.LengthM < BuildGrid)  // a click, no drag
            {
                Doc.Trusses.RemoveAll(x => x.Id == st.Id);
                if (st.New) Selection = null;
            }
            if (!Same(Doc, st.Before)) RegisterUndo(st.New ? "Draw Truss" : "Stretch Truss", st.Before);
            Refresh();
            return;
        }
        if (_raise is { } r)
        {
            _raise = null;
            if (!Same(Doc, r.Before)) RegisterUndo("Change Tower Height", r.Before);
            return;
        }
        if (_drag is not { } g) return;
        _drag = null;
        if (!Same(Doc, g.Before))
            RegisterUndo(g.Sel.IsFixture ? (_group.Count == 0 ? "Move Fixture" : "Move Fixtures") : g.Sel.IsZone ? "Move Zone" : "Move Truss",
                         g.Before);
        Changed(nameof(IsDirty));
    }

    public void ClickedEmpty()
    {
        if (Selection is not null || _group.Count > 0)
        {
            Selection = null;
            Group = new HashSet<string>();
            Refresh();
        }
    }

    // MARK: - dropping fixtures from the inspector

    public static string Payload(IEnumerable<string> ids) => PayloadPrefix + string.Join(",", ids);

    static List<string>? Ids(string payload)
    {
        if (!payload.StartsWith(PayloadPrefix, StringComparison.Ordinal)) return null;
        var ids = payload[PayloadPrefix.Length..].Split(',', StringSplitOptions.RemoveEmptyEntries).ToList();
        return ids.Count == 0 ? null : ids;
    }

    public void DropHover(Vector3 origin, Vector3 dir)
    {
        var t = TrussNear(S(origin), S(dir), 0.8)?.Truss.Id;
        if (t != DropTarget) { DropTarget = t; Refresh(); }
    }

    public void DropEnded()
    {
        if (DropTarget is not null) { DropTarget = null; Refresh(); }
    }

    /// Fixtures dropped on the stage: in a row on the truss under the pointer, else on the floor there.
    public bool Drop(string payload, Vector3 origin, Vector3 dir)
    {
        try
        {
            if (Ids(payload)?.Where(id => Doc.Fixtures.Any(f => f.Id == id)).ToList() is not { Count: > 0 } ids) return false;
            Vec3 o = S(origin), d = S(dir);
            if (TrussNear(o, d, 0.8) is { } near)
            {
                Change(ids.Count == 1 ? "Mount Fixture" : $"Mount {ids.Count} Fixtures", doc =>
                {
                    Arrange(doc, ids, near.Truss, near.U, null, HousingWidth);
                    LineUpWaiting(doc);
                });
            }
            else
            {
                if (!(d.Z < -1e-4)) return false;
                var hit = o + d * (-o.Z / d.Z);
                Change(ids.Count == 1 ? "Place Fixture" : $"Place {ids.Count} Fixtures", doc =>
                {
                    LineUp(doc, ids, hit.XY);
                    LineUpWaiting(doc);
                });
            }
            Select(ids);
            return true;
        }
        finally { DropEnded(); }
    }

    public bool Key(EditorKey e)
    {
        var shift = e.Shift;
        var step = shift ? 0.5 : 0.1;
        switch (e.Code)
        {
            case EditorKeyCode.Backspace or EditorKeyCode.Delete:
                DeleteSelection();
                return Selection is null;
            case EditorKeyCode.Left when !e.Alt:
                Nudge(-step, 0);
                return true;
            case EditorKeyCode.Right:
                Nudge(step, 0);
                return true;
            case EditorKeyCode.Down when !e.Alt:  // ↓: round the truss back, or towards the audience
                if (!RollAround(-1)) Nudge(0, step);
                return true;
            case EditorKeyCode.Up when !e.Alt:  // ↑: round the truss, or towards the back
                if (!RollAround(1)) Nudge(0, -step);
                return true;
        }
        if (e.Control && e.Characters == "a")  // Ctrl+A: every fixture
        {
            Select(Doc.Fixtures.Select(f => f.Id).ToList());
            return true;
        }
        if (e.Alt && (e.Code is EditorKeyCode.Up or EditorKeyCode.Down) && Selection?.TrussId is { } id)
        {
            var up = e.Code == EditorKeyCode.Up ? 0.25 : -0.25;  // Alt+↑ / Alt+↓: raise or lower the truss
            UpdateTruss(id, up > 0 ? "Raise Truss" : "Lower Truss", t =>
            {
                if (t.Vertical) { t.LengthM = Math.Max(1, t.LengthM + up); t.ZM = t.LengthM / 2; }
                else t.ZM = Math.Max(0.5, t.ZM + up);
            });
            return true;
        }
        if (e.Code == EditorKeyCode.Escape)
        {
            if (Tool != EditorTool.Select) Tool = EditorTool.Select; else ClickedEmpty();
            return true;
        }
        switch (e.Characters.ToLowerInvariant())
        {
            case "r": RotateSelection(shift ? 90 : 15); return true;
            case "t": Tool = EditorTool.Truss; return true;
            default: return false;
        }
    }
}
