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
        if (screen)  // the LED wall stands behind the DJ: the room's back wall is behind it
        {
            var wallY = Big ? MathF.Min(-4.5f, Room.Back + 1.5f) - 2.2f : -2.0f;
            Room = Room with { Back = MathF.Min(Room.Back, wallY - 0.8f) };
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

        // stage, DJ riser and booth
        // a raised stage (stage.deck_m): a solid platform that high up to the stage's front edge, its face to the
        // audience; else a big rig's deck stands 15 cm high
        float boothY, boothZ;
        var raised = MathF.Max(0, (float)stage.DeckM);
        if (Big || raised > 0)
        {
            var deckBack = MathF.Min(-3, back + 1.0f);
            float deckTop = raised > 0 ? raised : 0.15f, front = raised > 0 ? 0 : -0.2f;
            Box(-0.5f, W + 0.5f, deckBack, front, 0, deckTop, V(0.055f, 0.058f, 0.07f));
            Deck = (-0.5f, W + 0.5f, deckBack, front, deckTop);
            if (Big)
            {
                float ry = MathF.Max(deckBack + 0.5f, -4.5f), rd = 2.2f, rw = MathF.Min(5, W * 0.3f);
                Box(cx - rw / 2, cx + rw / 2, ry - rd, ry, deckTop, deckTop + 0.8f, V(0.07f, 0.074f, 0.09f));
                boothY = ry - 0.4f; boothZ = deckTop + 0.8f;
            }
            else
            {
                boothY = -1.3f; boothZ = deckTop;
            }
            // a lit edge along the front of the deck
            Box(-0.5f, W + 0.5f, front - 0.04f, front, deckTop - 0.02f, deckTop, V(0.25f, 0.27f, 0.35f), emissive: 0.6f);
        }
        else
        {
            boothY = -1.3f; boothZ = 0;
        }
        var bw = Big ? 2.4f : 1.6f;
        Box(cx - bw / 2, cx + bw / 2, boothY - 0.55f, boothY, boothZ, boothZ + 1.0f, V(0.08f, 0.085f, 0.10f));
        Box(cx - bw / 2 - 0.05f, cx + bw / 2 + 0.05f, boothY - 0.6f, boothY + 0.05f, boothZ + 1.0f, boothZ + 1.05f,
            V(0.12f, 0.13f, 0.16f));
        // decks: two faintly lit platters
        foreach (var ddx in new[] { -0.45f, 0.45f })
            Box(cx + ddx - 0.18f, cx + ddx + 0.18f, boothY - 0.45f, boothY - 0.1f, boothZ + 1.05f, boothZ + 1.08f,
                V(0.3f, 0.35f, 0.5f), emissive: 0.5f);
        // the DJ
        float dy = boothY - 0.9f, dz = boothZ;
        Box(cx - 0.12f, cx + 0.12f, dy - 0.1f, dy + 0.1f, dz, dz + 0.85f, V(0.05f, 0.05f, 0.06f));            // legs
        Box(cx - 0.22f, cx + 0.22f, dy - 0.13f, dy + 0.13f, dz + 0.85f, dz + 1.45f, V(0.06f, 0.06f, 0.07f));  // torso
        Box(cx - 0.11f, cx + 0.11f, dy - 0.11f, dy + 0.11f, dz + 1.5f, dz + 1.75f, V(0.07f, 0.065f, 0.065f)); // head
        Box(cx - 0.36f, cx - 0.22f, dy + 0.0f, dy + 0.4f, dz + 1.15f, dz + 1.25f, V(0.06f, 0.06f, 0.07f));    // arms on the decks
        Box(cx + 0.22f, cx + 0.36f, dy + 0.0f, dy + 0.4f, dz + 1.15f, dz + 1.25f, V(0.06f, 0.06f, 0.07f));
        DjHead = V(cx, dy, dz + 1.62f);

        // the LED wall behind the DJ
        if (screen)
        {
            var sw = Big ? MathF.Min(10, W * 0.55f) : 2.6f;
            var sh = sw * 9 / 16;
            var sy = Big ? MathF.Min(-4.5f, new Room(stage, fixtures, trusses).Back + 1.5f) - 2.2f : -2.0f;
            var sz = (Big ? 1.4f : 1.15f) + raised;  // over the stage, as high as it stands
            Wall = new WallPlacement(V(cx, sy, sz + sh / 2), sw, sh);
            var screenAt = Vertices.Count;
            Box(cx - sw / 2 - 0.12f, cx + sw / 2 + 0.12f, sy - 0.35f, sy - 0.02f, sz - 0.12f, sz + sh + 0.12f, V(0.03f, 0.03f, 0.035f));
            if (Big)  // legs
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
                TrussBeam(t, color: sel ? pick : hov ? lit : truss, emissive: sel ? 0.6f : hov ? 0.3f : 0);
                if (sel && !t.IsRing)  // the end handles: drag one to stretch or turn the truss
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
    /// the camera is behind it.
    public void VisibleRanges(Vector3 eye, List<(int Start, int Count)> into)
    {
        into.Clear();
        var at = 0;
        foreach (var c in Cutaways.OrderBy(c => c.Start))
        {
            if (eye.Y >= c.Y) continue;
            if (c.Start > at) into.Add((at, c.Start - at));
            at = Math.Max(at, c.End);
        }
        if (at < Vertices.Count) into.Add((at, Vertices.Count - at));
    }

    /// Whether the room's back wall is cut away with the camera at `eye` (beams then leave no spot on it).
    public bool BackCut(Vector3 eye) => eye.Y < Room.Back;

    /// Whether the LED wall is cut away with the camera at `eye`.
    public bool ScreenCut(Vector3 eye) => Wall is { } w && eye.Y < w.Center.Y - 0.35f;

    // MARK: building blocks

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

    /// A horizontal quatro truss from the set: four chords along it and lacing, turned with it.
    void TrussBeam(Truss t, Vector3 color, float emissive)
    {
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
