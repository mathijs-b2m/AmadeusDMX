// The solid part of the scene, built once per rig: floor, back wall, stage deck, DJ riser + booth + DJ,
// trusses and towers the fixtures hang on, the fixtures' fixed parts and the LED wall's frame
// (mac/Sources/AmadeusDMX/Render/Scenery.swift).
using System.Numerics;
using System.Runtime.InteropServices;

namespace AmadeusDMX;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct SolidVertex(Vector3 pos, Vector3 normal, Vector4 color)
{
    public Vector3 Pos = pos;
    public Vector3 Normal = normal;
    public Vector4 Color = color;   // rgb, a = emissive

    public const int Size = 40, NormalOffset = 12, ColorOffset = 24;
}

/// Where the LED wall hangs (same rule as the web visualiser).
public readonly record struct WallPlacement(Vector3 Center, float Width, float Height)
{
    // Center: the middle of the picture
    public (Vector3 Bl, Vector3 Br, Vector3 Tr, Vector3 Tl) Corners
    {
        get
        {
            float hw = Width / 2, hh = Height / 2;
            var c = Center;
            return (new(c.X - hw, c.Y, c.Z - hh), new(c.X + hw, c.Y, c.Z - hh), new(c.X + hw, c.Y, c.Z + hh), new(c.X - hw, c.Y, c.Z + hh));
        }
    }
}

public sealed class Scenery
{
    public List<SolidVertex> Vertices { get; } = [];
    public WallPlacement? Wall { get; private set; }
    public Room Room { get; private set; }
    public bool Big { get; }
    /// A big or raised stage's deck (x from, x to, y from, y to, its top), the floor the rig editor's drawings lie on there.
    public (float X0, float X1, float Y0, float Y1, float Top)? Deck { get; }
    public float Top { get; }
    public Vector3 DjHead { get; private set; }
    public FixtureModels Models { get; }
    /// What stands at the back (the room's back wall, the LED wall and its frame): its vertices and the depth of its
    /// back. While the camera is behind that (orbiting round the stage), it isn't drawn, so it doesn't hide the stage.
    public List<(int Start, int End, float Y)> Cutaways { get; } = [];
    /// The rest of the room's shell (side walls, the far wall, the ceiling), drawn only while the room is shown: its
    /// vertices and a point and direction of its inside. Seen from behind (Plan, gliding out) it isn't drawn.
    public List<(int Start, int End, Vector3 At, Vector3 Inward)> Shell { get; } = [];

    static Vector3 V(float x, float y, float z) => new(x, y, z);
    static Vector3 V(double x, double y, double z) => new((float)x, (float)y, (float)z);

    public Scenery(IReadOnlyList<FixtureInfo> fixtures, Stage stage, bool screen, IReadOnlyList<Truss>? trusses = null,
                   IReadOnlySet<string>? selected = null)
    {
        trusses ??= [];
        selected ??= new HashSet<string>();
        Room = new Room(stage, fixtures, trusses);
        Models = new FixtureModels(fixtures, selected);
        float W = Room.Width, cx = W / 2;
        var heads = fixtures.Count(f => f.Kind == FixtureKind.Head);
        Big = W >= 6 || heads >= 8;
        Top = MathF.Max(2, fixtures.Count > 0 ? (float)fixtures.Max(f => f.Pos.Z) : 2);
        // a scaffold wall behind the stage: the LED wall hangs on its front, the stage stops at it
        var scaffoldWall = Truss.ScreenWall(trusses);
        float? wallFront = scaffoldWall is null ? null : (float)(scaffoldWall.YM + scaffoldWall.ScaffoldDepth / 2);
        if (screen && scaffoldWall is null)  // the LED wall stands behind the DJ: the room's back wall is behind it
        {
            var wallY = Big ? MathF.Min(-4.5f, Room.Back + 1.5f) - 2.2f : -2.0f;
            if (!Room.BackFixed) Room = Room with { Back = MathF.Min(Room.Back, wallY - 0.8f) };
        }
        var back = Room.Back;

        // floor and room
        var floorC = V(0.030f, 0.032f, 0.040f);
        Quad(V(-Room.Side - 8, back - 4, 0), V(W + Room.Side + 8, back - 4, 0), V(W + Room.Side + 8, Room.Depth, 0),
             V(-Room.Side - 8, Room.Depth, 0), floorC);
        var wallAt = Vertices.Count;
        Quad(V(-Room.Side - 8, back, 0), V(W + Room.Side + 8, back, 0), V(W + Room.Side + 8, back, Room.Ceiling),
             V(-Room.Side - 8, back, Room.Ceiling), V(0.018f, 0.019f, 0.024f), normal: V(0, 1, 0));
        Cutaways.Add((wallAt, Vertices.Count, back));
        RoomShell();

        // stage, DJ riser and booth
        // a raised stage (stage.deck_m): a solid platform that high up to the stage's front edge, its face to the
        // audience; else a big rig's deck stands 15 cm high. A DJ on the floor (stage.dj_floor) has no riser, no such
        // deck under them (a raised stage stays: that is their floor) and a lower, narrower console
        float boothY = Room.BackFixed ? MathF.Max(-1.3f, back + 1.1f) : -1.3f, boothZ = 0;
        var raised = MathF.Max(0, (float)stage.DeckM);
        var deckBack = wallFront ?? (Room.BackFixed ? back : MathF.Min(-3, back + 1.0f));
        if (raised > 0 || (Big && !stage.DjFloor))
        {
            float deckTop = raised > 0 ? raised : 0.15f, front = raised > 0 ? 0 : -0.2f;
            if (stage.DeckScaffold && raised > 0)  // a plate on open tube
            {
                Box(-0.5f, W + 0.5f, deckBack, front, deckTop - 0.1f, deckTop, V(0.055f, 0.058f, 0.07f));
                ScaffoldDeck(-0.5f, W + 0.5f, deckBack, front, deckTop - 0.1f);
            }
            else
            {
                Box(-0.5f, W + 0.5f, deckBack, front, 0, deckTop, V(0.055f, 0.058f, 0.07f));
            }
            Deck = (-0.5f, W + 0.5f, deckBack, front, deckTop);
            boothZ = deckTop;
            // a lit edge along the front of the deck
            Box(-0.5f, W + 0.5f, front - 0.04f, front, deckTop - 0.02f, deckTop, V(0.25f, 0.27f, 0.35f), emissive: 0.6f);
        }
        if (Big)
        {
            // (against a scaffold: the riser and the DJ stay in front of the LED wall)
            // (a back wall the rig fixes: all of it in front of that wall)
            var ry = MathF.Max(deckBack + (wallFront is null ? 0.5f : 2.8f), -4.5f);
            if (Room.BackFixed && wallFront is null) ry = MathF.Min(-0.3f, MathF.Max(ry, back + 2.2f));
            float rd = wallFront is null && !Room.BackFixed ? 2.2f : MathF.Min(2.2f, ry - deckBack), rw = MathF.Min(5, W * 0.3f);
            boothY = ry - 0.4f;
            if (!stage.DjFloor)
            {
                Box(cx - rw / 2, cx + rw / 2, ry - rd, ry, boothZ, boothZ + 0.8f, V(0.07f, 0.074f, 0.09f));
                boothZ += 0.8f;
            }
        }
        float bw = Big && !stage.DjFloor ? 2.4f : 1.6f, bh = stage.DjFloor ? 0.8f : 1.0f;
        Box(cx - bw / 2, cx + bw / 2, boothY - 0.55f, boothY, boothZ, boothZ + bh, V(0.08f, 0.085f, 0.10f));
        Box(cx - bw / 2 - 0.05f, cx + bw / 2 + 0.05f, boothY - 0.6f, boothY + 0.05f, boothZ + bh, boothZ + bh + 0.05f,
            V(0.12f, 0.13f, 0.16f));
        // decks: two faintly lit platters
        foreach (var ddx in new[] { -0.45f, 0.45f })
            Box(cx + ddx - 0.18f, cx + ddx + 0.18f, boothY - 0.45f, boothY - 0.1f, boothZ + bh + 0.05f, boothZ + bh + 0.08f,
                V(0.3f, 0.35f, 0.5f), emissive: 0.5f);
        // the DJ (where the engine thinks their head is, to keep beams from meeting on it: geometry.dj_head)
        float dy = boothY - 0.9f, dz = boothZ;
        Box(cx - 0.12f, cx + 0.12f, dy - 0.1f, dy + 0.1f, dz, dz + 0.85f, V(0.05f, 0.05f, 0.06f));            // legs
        Box(cx - 0.22f, cx + 0.22f, dy - 0.13f, dy + 0.13f, dz + 0.85f, dz + 1.45f, V(0.06f, 0.06f, 0.07f));  // torso
        Box(cx - 0.11f, cx + 0.11f, dy - 0.11f, dy + 0.11f, dz + 1.5f, dz + 1.75f, V(0.07f, 0.065f, 0.065f)); // head
        Box(cx - 0.36f, cx - 0.22f, dy + 0.0f, dy + 0.4f, dz + bh + 0.15f, dz + bh + 0.25f, V(0.06f, 0.06f, 0.07f));    // arms on the decks
        Box(cx + 0.22f, cx + 0.36f, dy + 0.0f, dy + 0.4f, dz + bh + 0.15f, dz + bh + 0.25f, V(0.06f, 0.06f, 0.07f));
        DjHead = V(cx, dy, dz + 1.62f);

        // the LED wall behind the DJ
        if (screen)
        {
            var sw = Big ? MathF.Min(10, W * 0.55f) : 2.6f;
            var sh = sw * 9 / 16;
            var free = Big ? MathF.Min(-4.5f, new Room(stage, fixtures, trusses).Back + 1.5f) - 2.2f : -2.0f;
            var sy = wallFront is { } wf ? wf + 0.37f
                : Room.BackFixed ? MathF.Max(free, back + 0.45f) : free;  // (its frame against a back wall the rig fixes)
            var sz = (Big ? 1.4f : 1.15f) + raised;  // over the stage, as high as it stands
            Wall = new WallPlacement(V(cx, sy, sz + sh / 2), sw, sh);
            var screenAt = Vertices.Count;
            Box(cx - sw / 2 - 0.12f, cx + sw / 2 + 0.12f, sy - 0.35f, sy - 0.02f, sz - 0.12f, sz + sh + 0.12f, V(0.03f, 0.03f, 0.035f));
            if (Big && scaffoldWall is null)  // legs
            {
                Box(cx - sw / 2 - 0.1f, cx - sw / 2 + 0.1f, sy - 0.3f, sy - 0.1f, 0, sz, V(0.06f, 0.06f, 0.07f));
                Box(cx + sw / 2 - 0.1f, cx + sw / 2 + 0.1f, sy - 0.3f, sy - 0.1f, 0, sz, V(0.06f, 0.06f, 0.07f));
            }
            Cutaways.Add((screenAt, Vertices.Count, sy - 0.35f));
        }

        // trusses: the set's own (rig editor), else: hanging fixtures at the same depth and height share one bar
        var truss = V(0.16f, 0.17f, 0.2f);
        var pick = V(0.25f, 0.55f, 1.0f);
        var lit = V(0.35f, 0.45f, 0.6f);  // under the pointer: what a click would pick
        foreach (var t in trusses)
        {
            var sel = selected.Contains($"truss:{t.Id}");
            var hov = selected.Contains($"hover:truss:{t.Id}");
            var handle = V(0.85f, 0.95f, 1.0f);
            if (t.Vertical)
            {
                TrussTower((float)t.XM, (float)t.YM, (float)(t.ZM + t.LengthM / 2), color: sel ? pick : hov ? lit : truss,
                           emissive: sel ? 0.6f : hov ? 0.3f : 0);
                if (sel)  // the handle on top: drag it to make the tower taller or shorter
                {
                    float x = (float)t.XM, y = (float)t.YM, z = (float)(t.ZM + t.LengthM / 2) + 0.2f;
                    Box(x - 0.13f, x + 0.13f, y - 0.13f, y + 0.13f, z - 0.13f, z + 0.13f, handle, emissive: 1.5f);
                }
            }
            else
            {
                if (t.IsStand)
                    LightStand(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6f : hov ? 0.3f : 0);
                else if (t.IsScaffold)
                    Scaffold(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6f : hov ? 0.3f : 0);
                else
                    TrussBeam(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6f : hov ? 0.3f : 0);
                if (sel && !t.IsLoop)  // the end handles: drag one to stretch or turn the truss
                {
                    var r = (float)t.RotDeg * MathF.PI / 180;
                    var ax = V(MathF.Cos(r), MathF.Sin(r), 0);
                    foreach (var e in new[] { -1f, 1f })
                    {
                        var p = V(t.XM, t.YM, t.ZM) + ax * ((float)t.LengthM / 2 * e);
                        Box(p.X - 0.13f, p.X + 0.13f, p.Y - 0.13f, p.Y + 0.13f, p.Z - 0.13f, p.Z + 0.13f, handle, emissive: 1.5f);
                    }
                }
            }
        }
        var rows = new Dictionary<(int, int), List<FixtureInfo>>();
        if (trusses.Count == 0)
            foreach (var f in fixtures.Where(f => f.Mount == "hang"))
            {
                var key = ((int)Math.Round(f.Pos.Y * 2, MidpointRounding.AwayFromZero), (int)Math.Round(f.Pos.Z * 2, MidpointRounding.AwayFromZero));
                if (!rows.TryGetValue(key, out var list)) rows[key] = list = [];
                list.Add(f);
            }
        foreach (var fs in rows.Values)
        {
            var xs = fs.Select(f => (float)f.Pos.X).ToList();
            float y = (float)fs[0].Pos.Y, z = (float)fs.Max(f => f.Pos.Z) + 0.3f;
            TrussBar(xs.Min() - 0.5f, xs.Max() + 0.5f, y, z, truss);
            if (fs.Count >= 3 || Big)  // chain motors up to the ceiling
                foreach (var x in new[] { xs.Min() - 0.3f, xs.Max() + 0.3f })
                    Box(x - 0.015f, x + 0.015f, y - 0.015f, y + 0.015f, z + 0.15f, Room.Outdoor ? z + 1.2f : Room.Ceiling, V(0.08f, 0.08f, 0.09f));
        }
        // (a fixture standing in the air has its own stand: part of the fixture, see FixtureModels)

        // the fixtures: what never moves now, the moving parts and lenses every frame (FixtureModels)
        var mb = new MeshBuilder();
        Models.AddStatic(mb);
        Vertices.AddRange(mb.V);
    }

    /// The parts of `Vertices` to draw with the camera at `eye` (start, count): all but what stands at the back while
    /// the camera is behind it, and the room's shell unless it is shown (`inRoom`) and seen from inside.
    public void VisibleRanges(Vector3 eye, List<(int Start, int Count)> into, bool inRoom = false)
    {
        into.Clear();
        var at = 0;
        var hidden = Cutaways.Where(c => eye.Y < c.Y).Select(c => (c.Start, c.End))
            .Concat(Shell.Where(s => !inRoom || Vector3.Dot(eye - s.At, s.Inward) < 0).Select(s => (s.Start, s.End)));
        foreach (var (start, end) in hidden.OrderBy(r => r.Start))
        {
            if (start > at) into.Add((at, start - at));
            at = Math.Max(at, end);
        }
        if (at < Vertices.Count) into.Add((at, Vertices.Count - at));
    }

    /// Whether the room's back wall is cut away with the camera at `eye` (beams then leave no spot on it).
    public bool BackCut(Vector3 eye) => eye.Y < Room.Back;

    /// Whether a surface of the room shown (`inRoom`) is seen from behind, and so not drawn.
    public bool ShellCut(Room.Surface surf, Vector3 eye)
    {
        var n = Room.Normal(surf);
        return Shell.Any(s => Vector3.Dot(s.Inward, n) > 0.5f && Vector3.Dot(eye - s.At, n) < 0);
    }

    /// Whether the LED wall is cut away with the camera at `eye`.
    public bool ScreenCut(Vector3 eye) => Wall is { } w && eye.Y < w.Center.Y - 0.35f;

    // MARK: building blocks

    /// The walls and ceiling that make the room a room. Outdoors there is none.
    void RoomShell()
    {
        if (Room.Outdoor) return;
        float x0 = -Room.Side, x1 = Room.Width + Room.Side, y0 = Room.Back, y1 = Room.Depth, h = Room.Ceiling;
        Vector3 wall = V(0.075f, 0.078f, 0.09f), ceiling = V(0.05f, 0.052f, 0.06f);
        void Add(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 color, Vector3 inward)
        {
            var at = Vertices.Count;
            Quad(a, b, c, d, color, normal: inward);
            Shell.Add((at, Vertices.Count, a, inward));
        }
        // (the back wall as well, just in front of the darker one the stage always has)
        Add(V(x0, y0 + 0.002f, 0), V(x1, y0 + 0.002f, 0), V(x1, y0 + 0.002f, h), V(x0, y0 + 0.002f, h), wall, V(0, 1, 0));
        Add(V(x0, y0, 0), V(x0, y1, 0), V(x0, y1, h), V(x0, y0, h), wall, V(1, 0, 0));
        Add(V(x1, y1, 0), V(x1, y0, 0), V(x1, y0, h), V(x1, y1, h), wall, V(-1, 0, 0));
        Add(V(x0, y1, 0), V(x1, y1, 0), V(x1, y1, h), V(x0, y1, h), wall, V(0, -1, 0));
        Add(V(x0, y0, h), V(x1, y0, h), V(x1, y1, h), V(x0, y1, h), ceiling, V(0, 0, -1));
    }

    void Quad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 color, Vector3? normal = null, float emissive = 0)
    {
        var n = normal ?? Vector3.Normalize(Vector3.Cross(b - a, d - a));
        var col = new Vector4(color, emissive);
        Vertices.Add(new(a, n, col)); Vertices.Add(new(b, n, col)); Vertices.Add(new(c, n, col));
        Vertices.Add(new(a, n, col)); Vertices.Add(new(c, n, col)); Vertices.Add(new(d, n, col));
    }

    public void Box(float x0, float x1, float y0, float y1, float z0, float z1, Vector3 color, float emissive = 0)
    {
        static Vector3 P(float x, float y, float z) => new(x, y, z);
        Quad(P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1), color, normal: V(0, 0, 1), emissive: emissive);
        Quad(P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1), color, normal: V(0, 1, 0), emissive: emissive);
        Quad(P(x1, y0, z0), P(x0, y0, z0), P(x0, y0, z1), P(x1, y0, z1), color, normal: V(0, -1, 0), emissive: emissive);
        Quad(P(x0, y0, z0), P(x0, y1, z0), P(x0, y1, z1), P(x0, y0, z1), color, normal: V(-1, 0, 0), emissive: emissive);
        Quad(P(x1, y1, z0), P(x1, y0, z0), P(x1, y0, z1), P(x1, y1, z1), color, normal: V(1, 0, 0), emissive: emissive);
        Quad(P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0), P(x0, y0, z0), color, normal: V(0, 0, -1), emissive: emissive);
    }

    /// A box with its own axes: `ex` along it, `ez` its "up"; size = (along ex, across, along ez).
    public void OrientedBox(Vector3 c, Vector3 ex0, Vector3 ez0, Vector3 size, Vector3 color, float emissive = 0)
    {
        var ez = Vector3.Normalize(ez0);
        var ex = ex0 - ez * Vector3.Dot(ex0, ez);
        if (ex.Length() < 1e-4f) ex = MathF.Abs(ez.Z) < 0.9f ? Vector3.Cross(V(0, 0, 1), ez) : V(1, 0, 0);
        ex = Vector3.Normalize(ex);
        var ey = Vector3.Cross(ez, ex);
        float hx = size.X / 2, hy = size.Y / 2, hz = size.Z / 2;
        Vector3 P(float i, float j, float k) => c + ex * (i * hx) + ey * (j * hy) + ez * (k * hz);
        Quad(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), color, normal: ez, emissive: emissive);
        Quad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), color, normal: -ez, emissive: emissive);
        Quad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), color, normal: ey, emissive: emissive);
        Quad(P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), P(-1, -1, -1), color, normal: -ey, emissive: emissive);
        Quad(P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), P(1, -1, -1), color, normal: ex, emissive: emissive);
        Quad(P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), color, normal: -ex, emissive: emissive);
    }

    /// A box turned around z (counter-clockwise from above) about its centre; size = (along, across, height).
    public void RotatedBox(Vector3 c, Vector3 size, float rotDeg, Vector3 color, float emissive = 0)
    {
        var r = rotDeg * MathF.PI / 180;
        Vector3 ax = V(MathF.Cos(r), MathF.Sin(r), 0), ay = V(-MathF.Sin(r), MathF.Cos(r), 0);
        float hx = size.X / 2, hy = size.Y / 2, hz = size.Z / 2;
        Vector3 P(float i, float j, float k) => c + ax * (i * hx) + ay * (j * hy) + V(0, 0, k * hz);
        Quad(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), color, normal: V(0, 0, 1), emissive: emissive);
        Quad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), color, normal: V(0, 0, -1), emissive: emissive);
        Quad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), color, normal: ay, emissive: emissive);
        Quad(P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), P(-1, -1, -1), color, normal: -ay, emissive: emissive);
        Quad(P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), P(1, -1, -1), color, normal: ax, emissive: emissive);
        Quad(P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), color, normal: -ax, emissive: emissive);
    }

    /// A scaffold wall: two frames of standards and ledgers, transoms between them, every other bay braced, base plates.
    void Scaffold(Truss t, Vector3 color, float emissive)
    {
        float rot = (float)t.RotDeg, r = rot * MathF.PI / 180, L = (float)t.LengthM, H = (float)t.ZM, D = (float)t.ScaffoldDepth;
        Vector3 ax = V(MathF.Cos(r), MathF.Sin(r), 0), ay = V(-MathF.Sin(r), MathF.Cos(r), 0), c = V(t.XM, t.YM, 0);
        int bays = t.ScaffoldBays, lifts = t.ScaffoldLifts;
        float tube = 0.05f, bay = L / bays, lift = H / lifts;
        Vector3 At(float u, float v, float z) => c + ax * u + ay * v + V(0, 0, z);
        foreach (var v in new[] { D / 2, -D / 2 })
        {
            for (var k = 0; k <= bays; k++)
            {
                var u = -L / 2 + bay * k;
                RotatedBox(At(u, v, H / 2 + 0.15f), V(tube, tube, H + 0.3f), rot, color, emissive: emissive);
                RotatedBox(At(u, v, 0.015f), V(0.2f, 0.2f, 0.03f), rot, color * 0.7f, emissive: emissive);
            }
            for (var k = 1; k <= lifts; k++) RotatedBox(At(0, v, lift * k), V(L, tube, tube), rot, color, emissive: emissive);
            for (var k = 0; k < bays; k += 2)  // a brace up each braced bay, zigzag from lift to lift
            {
                var u = -L / 2 + bay * k;
                for (var j = 0; j < lifts; j++)
                {
                    var z = lift * j;
                    var up = j % 2 == 0;
                    Strut(At(up ? u : u + bay, v, z), At(up ? u + bay : u, v, z + lift), color * 0.85f, emissive: emissive);
                }
            }
        }
        for (var k = 0; k <= bays; k++)  // transoms between the frames
        {
            var u = -L / 2 + bay * k;
            for (var j = 1; j <= lifts; j++) RotatedBox(At(u, 0, lift * j), V(tube * 0.8f, D, tube * 0.8f), rot, color * 0.9f, emissive: emissive);
        }
    }

    /// Open tube under a raised stage's plate: standards about 2 m apart, a ledger round each row, braces.
    void ScaffoldDeck(float x0, float x1, float y0, float y1, float top)
    {
        var c = V(0.16f, 0.17f, 0.2f);
        const float t = 0.025f;
        int nx = Math.Max(1, (int)MathF.Round((x1 - x0) / 2.5f, MidpointRounding.AwayFromZero));
        int ny = Math.Max(1, (int)MathF.Round((y1 - y0) / 2.5f, MidpointRounding.AwayFromZero));
        float dx = (x1 - x0) / nx, dy = (y1 - y0) / ny;
        for (var i = 0; i <= nx; i++)
            for (var j = 0; j <= ny; j++)
            {
                float x = x0 + dx * i, y = y0 + dy * j;
                Box(x - t, x + t, y - t, y + t, 0, top, c);
            }
        foreach (var z in new[] { top * 0.5f, top - 0.05f })
        {
            for (var j = 0; j <= ny; j++) { var y = y0 + dy * j; Box(x0, x1, y - t, y + t, z - t, z + t, c); }
            for (var i = 0; i <= nx; i++) { var x = x0 + dx * i; Box(x - t, x + t, y0, y1, z - t, z + t, c); }
        }
        for (var i = 0; i < nx; i += 2)  // the bays along the front and the back, braced
        {
            var x = x0 + dx * i;
            foreach (var y in new[] { y0, y1 }) Strut(V(x, y, 0), V(x + dx, y, top - 0.05f), c * 0.85f);
        }
    }

    /// A thin tube from `a` to `b` in any direction (a brace).
    void Strut(Vector3 a, Vector3 b, Vector3 color, float emissive = 0)
    {
        var m = new MeshBuilder();
        m.Cylinder((a + b) / 2, Vector3.Normalize(b - a), radius: 0.016f, length: (b - a).Length(), color, emissive: emissive, segments: 5);
        Vertices.AddRange(m.V);
    }

    /// A light stand: its bar (a 40 mm tube) and a tripod under each end of a bridge, under the middle of a T-bar,
    /// from the floor up to the bar.
    void LightStand(Truss t, Vector3 color, float emissive)
    {
        var m = new MeshBuilder();
        float z = (float)t.ZM, r = (float)t.RotDeg * MathF.PI / 180;
        var pole = t.IsDeco ? z - 0.095f : z - 0.02f;  // where the stand's pole meets the bar
        if (t.IsDeco)
        {
            // three chords, point up, laced on each face
            Vector3 ax = V(MathF.Cos(r), MathF.Sin(r), 0), n = V(-MathF.Sin(r), MathF.Cos(r), 0), mid = V(t.XM, t.YM, z);
            var len = (float)t.LengthM;
            Vector3[] chords = [n * -0.11f + V(0, 0, -0.095f), n * 0.11f + V(0, 0, -0.095f), V(0, 0, 0.095f)];
            foreach (var c in chords) m.Cylinder(mid + c, ax, radius: 0.012f, length: len, color, emissive: emissive, segments: 6);
            var bays = Math.Max(1, (int)MathF.Round(len / 0.22f));
            for (var i = 0; i < 3; i++)
            {
                Vector3 c = chords[i], d = chords[(i + 1) % 3];
                for (var k = 0; k < bays; k++)
                {
                    float u0 = -len / 2 + len * k / bays, u1 = u0 + len / bays;
                    Vector3 a = mid + ax * u0 + (k % 2 == 0 ? c : d), b = mid + ax * u1 + (k % 2 == 0 ? d : c);
                    m.Cylinder((a + b) / 2, Vector3.Normalize(b - a), radius: 0.006f, length: (b - a).Length(), color,
                               emissive: emissive, segments: 4);
                }
            }
        }
        else
        {
            m.Cylinder(V(t.XM, t.YM, z), V(MathF.Cos(r), MathF.Sin(r), 0), radius: 0.02f, length: (float)t.LengthM, color,
                       emissive: emissive, segments: 10);
        }
        var spread = MathF.Min(0.75f, 0.25f + z * 0.15f);  // a taller stand stands wider
        foreach (var f in t.StandFeet)
        {
            float px = (float)f.X, py = (float)f.Y;
            m.Cylinder(V(px, py, pole / 2), V(0, 0, 1), radius: 0.025f, length: pole, color * 0.85f,
                       emissive: emissive, segments: 8);
            var hub = V(px, py, MathF.Min(0.7f, z * 0.3f));
            // three legs out from the hub to the floor: a bridge's with one leg in along the bar (as a crew sets it,
            // so the others stick out least past its ends), a T-bar's with one towards the audience
            var first = t.Type == "tbar" ? r + MathF.PI / 2 : MathF.Atan2((float)t.YM - py, (float)t.XM - px);
            for (var k = 0; k < 3; k++)
            {
                var a = k / 3f * 2 * MathF.PI + first;
                var foot = V(px + MathF.Cos(a) * spread, py + MathF.Sin(a) * spread, 0.01f);
                var v = hub - foot;
                m.Cylinder((hub + foot) / 2, Vector3.Normalize(v), radius: 0.015f, length: v.Length(), color * 0.85f,
                           emissive: emissive, segments: 6);
            }
        }
        Vertices.AddRange(m.V);
    }

    /// A horizontal quatro truss from the set: four chords along it and lacing, turned with it.
    void TrussBeam(Truss t, Vector3 color, float emissive)
    {
        if (t.IsCarre)  // its four sides, end plates at the corners, and a tower under each corner down to the floor
        {
            foreach (var (a, b) in t.Pieces())
            {
                var side = new Truss(t.Id, (b - a).Length, (a.X + b.X) / 2, (a.Y + b.Y) / 2, t.ZM,
                    Math.Atan2(b.Y - a.Y, b.X - a.X) * 180 / Math.PI) { Type = t.Type };
                StraightBeam(side, color, emissive, [-1, 1]);
            }
            foreach (var c in t.CarreCorners) TrussTower((float)c.X, (float)c.Y, (float)t.ZM - 0.05f, color: color, emissive: emissive);
            return;
        }
        if (t.IsRing)  // round: short straight pieces round the arc, end plates only where an arc ends
        {
            var pieces = t.Pieces(0.3);
            for (var k = 0; k < pieces.Count; k++)
            {
                var (a, b) = pieces[k];
                var piece = new Truss(t.Id, (b - a).Length + 0.02, (a.X + b.X) / 2, (a.Y + b.Y) / 2, t.ZM,
                    Math.Atan2(b.Y - a.Y, b.X - a.X) * 180 / Math.PI) { Type = t.Type };
                var ends = new List<float>();
                if (!t.IsFullRing)
                {
                    if (k == 0) ends.Add(-1);
                    if (k == pieces.Count - 1) ends.Add(1);
                }
                StraightBeam(piece, color, emissive, ends);
            }
            return;
        }
        StraightBeam(t, color, emissive, [-1, 1]);
    }

    void StraightBeam(Truss t, Vector3 color, float emissive, IReadOnlyList<float> ends)
    {
        float r = (float)t.RotDeg, L = (float)t.LengthM, h = 0.15f;
        var c = V(t.XM, t.YM, t.ZM);
        Vector3 ay = V(-MathF.Sin(r * MathF.PI / 180), MathF.Cos(r * MathF.PI / 180), 0), ax = V(MathF.Cos(r * MathF.PI / 180), MathF.Sin(r * MathF.PI / 180), 0);
        foreach (var dy in new[] { -h, h })
            foreach (var dz in new[] { -h, h })
                RotatedBox(c + ay * dy + V(0, 0, dz), V(L, 0.045f, 0.045f), r, color, emissive: emissive);
        var u = -L / 2 + 0.15f;
        while (u < L / 2 - 0.15f)
        {
            foreach (var dy in new[] { -h, h }) RotatedBox(c + ax * u + ay * dy, V(0.016f, 0.016f, 2 * h), r, color * 0.8f, emissive: emissive);
            u += 0.5f;
        }
        foreach (var e in ends) RotatedBox(c + ax * (L / 2) * e, V(0.05f, 2 * h + 0.05f, 2 * h + 0.05f), r, color * 0.9f, emissive: emissive);
    }

    /// A 30 cm box truss: four chords and diagonal lacing.
    void TrussBar(float x0, float x1, float y, float z, Vector3 c)
    {
        float h = 0.15f, t = 0.022f;
        foreach (var dy in new[] { -h, h })
            foreach (var dz in new[] { -h, h })
                Box(x0, x1, y + dy - t, y + dy + t, z + dz - t, z + dz + t, c);
        var x = x0;
        while (x < x1 - 0.3f)
        {
            foreach (var dy in new[] { -h, h }) Box(x, x + 0.3f, y + dy - 0.008f, y + dy + 0.008f, z - h, z + h, c * 0.8f);
            x += 0.6f;
        }
    }

    void TrussTower(float x, float y, float h, Vector3? color = null, float emissive = 0)
    {
        var c = color ?? V(0.16f, 0.17f, 0.2f);
        float w = 0.15f, t = 0.02f;
        foreach (var dx in new[] { -w, w })
            foreach (var dy in new[] { -w, w })
                Box(x + dx - t, x + dx + t, y + dy - t, y + dy + t, 0, h + 0.2f, c, emissive: emissive);
        var z = 0.3f;
        while (z < h) { Box(x - w, x + w, y - w - 0.008f, y - w + 0.008f, z, z + 0.02f, c * 0.8f, emissive: emissive); z += 0.5f; }
        Box(x - 0.4f, x + 0.4f, y - 0.4f, y + 0.4f, 0, 0.03f, c * 0.7f, emissive: emissive);
    }
}
