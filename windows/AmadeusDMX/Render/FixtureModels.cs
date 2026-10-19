// The fixtures as they look: a moving head is a base, a yoke that pans and a head that tilts to where its beam
// points; a moving bar tilts on its yoke ends; pixel bars, pars, strobes, blinders and lasers have their
// housings, and every lens glows in the colour the fixture plays. Sized from the fixture's real dimensions
// (mac/Sources/AmadeusDMX/Render/FixtureModels.swift).
//
// What never moves (bases, bar housings, cans, boxes) is built once with the scenery; the moving parts and the
// lenses are built every frame from the show's frame (beam directions, colours).
using System.Numerics;

using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

/// An orthonormal frame: x across, y the other way across, z "up" (the part's own axis).
public readonly record struct Basis(Vector3 X, Vector3 Y, Vector3 Z)
{
    /// z along `axis`, x as close to `hint` as possible.
    public static Basis Along(Vector3 axis, Vector3 hint)
    {
        var z = Vector3.Normalize(axis);
        var x = hint - z * Vector3.Dot(hint, z);
        if (x.Length() < 1e-4f) x = MathF.Abs(z.Z) < 0.9f ? Vector3.Cross(new(0, 0, 1), z) : new(1, 0, 0);
        x = Vector3.Normalize(x);
        return new Basis(x, Vector3.Cross(z, x), z);
    }
}

/// Triangles for the solid pipeline. Reused frame to frame (Clear()), so the moving parts don't allocate.
public sealed class MeshBuilder
{
    public List<SolidVertex> V { get; } = [];

    public void Clear() => V.Clear();

    public void Quad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 n, Vector4 col)
    {
        V.Add(new(a, n, col)); V.Add(new(b, n, col)); V.Add(new(c, n, col));
        V.Add(new(a, n, col)); V.Add(new(c, n, col)); V.Add(new(d, n, col));
    }

    /// A box around `c`, its edges along the basis; size = (x, y, z).
    public void Box(Vector3 c, Basis b, Vector3 size, Vector3 color, float emissive = 0)
    {
        var col = new Vector4(color, emissive);
        var h = size / 2;
        Vector3 P(float i, float j, float k) => c + b.X * (i * h.X) + b.Y * (j * h.Y) + b.Z * (k * h.Z);
        Quad(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), b.Z, col);
        Quad(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1), -b.Z, col);
        Quad(P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1), P(1, 1, -1), b.Y, col);
        Quad(P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), P(-1, -1, -1), -b.Y, col);
        Quad(P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), P(1, -1, -1), b.X, col);
        Quad(P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1), P(-1, 1, -1), -b.X, col);
    }

    /// A cylinder around `c` along `axis` (unit), with caps.
    public void Cylinder(Vector3 c, Vector3 axis, float radius, float length, Vector3 color, float emissive = 0, int segments = 16,
                         bool caps = true)
    {
        float r = radius, L = length;
        var n = segments;
        var b = Basis.Along(axis, new(1, 0, 0));
        var col = new Vector4(color, emissive);
        Vector3 top = c + b.Z * (L / 2), bottom = c - b.Z * (L / 2);
        for (var k = 0; k < n; k++)
        {
            float a0 = (float)k / n * 2 * MathF.PI, a1 = (float)(k + 1) / n * 2 * MathF.PI;
            Vector3 r0 = b.X * MathF.Cos(a0) + b.Y * MathF.Sin(a0), r1 = b.X * MathF.Cos(a1) + b.Y * MathF.Sin(a1);
            Quad(bottom + r0 * r, bottom + r1 * r, top + r1 * r, top + r0 * r, Vector3.Normalize(r0 + r1), col);
            if (caps)
            {
                V.Add(new(top, b.Z, col)); V.Add(new(top + r0 * r, b.Z, col)); V.Add(new(top + r1 * r, b.Z, col));
                V.Add(new(bottom, -b.Z, col)); V.Add(new(bottom + r1 * r, -b.Z, col)); V.Add(new(bottom + r0 * r, -b.Z, col));
            }
        }
    }

    /// A flat disc facing `normal`.
    public void Disc(Vector3 c, Vector3 normal, float radius, Vector3 color, float emissive = 0, int segments = 16)
    {
        var b = Basis.Along(normal, new(1, 0, 0));
        var col = new Vector4(color, emissive);
        for (var k = 0; k < segments; k++)
        {
            float a0 = (float)k / segments * 2 * MathF.PI, a1 = (float)(k + 1) / segments * 2 * MathF.PI;
            V.Add(new(c, b.Z, col));
            V.Add(new(c + (b.X * MathF.Cos(a0) + b.Y * MathF.Sin(a0)) * radius, b.Z, col));
            V.Add(new(c + (b.X * MathF.Cos(a1) + b.Y * MathF.Sin(a1)) * radius, b.Z, col));
        }
    }
}

/// The rig's fixtures as models.
public sealed class FixtureModels
{
    public enum Shape { BeamHead, SpotHead, WashHead, MovingBar, CurveBar, ParBar, Par, Strobe, Blinder, Laser, Smoke }

    public sealed record Unit
    {
        public required string Id { get; init; }
        public required Shape Shape { get; init; }
        public required int[] Idx { get; init; }       // its elements (cells) in the hello's fixture list
        public Vector3 P { get; init; }                 // centre (a head: the tilt axis)
        public Vector3 Up { get; init; }                // base → head (heads), the static aim (others)
        public Vector3 Across { get; init; }            // along a bar, across a head's base
        public float Length { get; init; }              // a bar's length
        public float Scale { get; init; }               // the model's size against a typical fixture of its kind
        public Vector3? Size { get; init; }             // real housing size (m) when known
        public bool Selected { get; init; }
        public bool Hovered { get; init; }
        public bool OnStand { get; init; }              // standing in the air, not on a truss: it has its own tripod stand
    }

    public static readonly Vector3 BodyColor = new(0.075f, 0.078f, 0.088f);
    public static readonly Vector3 YokeColor = new(0.095f, 0.098f, 0.11f);
    public static readonly Vector3 GlassColor = new(0.05f, 0.06f, 0.075f);
    public static readonly Vector3 Pick = new(0.25f, 0.55f, 1.0f);
    public static readonly Vector3 Lit = new(0.35f, 0.45f, 0.6f);  // under the pointer
    public static readonly Vector3 StandColor = new(0.13f, 0.135f, 0.15f);

    readonly List<Unit> _units = [];
    public IReadOnlyList<Unit> Units => _units;
    readonly Dictionary<string, Vector3> _tiltAxis = [];   // the last tilt axis per head (when the beam is along the pan axis)
    readonly Vector3[] _positions;

    static float Max(Vector3 v) => MathF.Max(v.X, MathF.Max(v.Y, v.Z));

    public FixtureModels(IReadOnlyList<FixtureInfo> fixtures, IReadOnlySet<string> selected)
    {
        _positions = fixtures.Select(f => f.Pos.ToFloat()).ToArray();
        var groups = new Dictionary<string, List<int>>();
        var order = new List<string>();
        for (var i = 0; i < fixtures.Count; i++)
        {
            var k = fixtures[i].Fixture ?? fixtures[i].Id;
            if (!groups.TryGetValue(k, out var g)) { order.Add(k); groups[k] = g = []; }
            g.Add(i);
        }
        foreach (var k in order)
        {
            var idx = groups[k].ToArray();
            var f = fixtures[idx[0]];
            var p = idx.Select(i => _positions[i]).Aggregate(Vector3.Zero, (a, b) => a + b) / idx.Length;
            var r = (float)f.Rot * MathF.PI / 180;
            var across = new Vector3(MathF.Cos(r), MathF.Sin(r), 0);
            if (idx.Length > 1 && (_positions[idx[^1]] - _positions[idx[0]]).Length() > 0.05f)
                across = Vector3.Normalize(_positions[idx[^1]] - _positions[idx[0]]);
            Vector3? size = f.Size is { Length: >= 3 } s ? new Vector3((float)s[0], (float)s[1], (float)s[2]) : null;
            var body = f.Body ?? (f.Kind == FixtureKind.Head ? "moving_head" : f.Kind.RawValue());
            var hang = f.Mount == "hang";
            var up = new Vector3(0, 0, hang ? -1 : 1);
            if (f.Up is { } u) up = Vector3.Normalize(u.ToFloat());
            if (f.Dir is { } d && f.Kind != FixtureKind.Head) up = Vector3.Normalize(d.ToFloat());
            var shape = body switch
            {
                "moving_bar" => Shape.MovingBar,
                "curve_bar" => Shape.CurveBar,
                "par_bar" => Shape.ParBar,
                "strobe" => Shape.Strobe,
                "blinder" => Shape.Blinder,
                "laser" => Shape.Laser,
                "smoke" => Shape.Smoke,
                "moving_head" => f.BeamDeg <= 6 ? Shape.BeamHead : f.BeamDeg <= 20 ? Shape.SpotHead : Shape.WashHead,
                _ => f.Kind == FixtureKind.Head ? Shape.SpotHead : idx.Length > 1 ? Shape.ParBar : Shape.Par,
            };
            if (shape == Shape.Laser) up = Vector3.Normalize(new Vector3(0, 1, 0.15f));
            // heads: the model's height against a typical 55 cm head
            var scale = shape is Shape.BeamHead or Shape.SpotHead or Shape.WashHead
                ? MathF.Min(1.5f, MathF.Max(0.6f, (size is { } sz ? MathF.Max(sz.X, sz.Z) : 0.55f) / 0.55f)) : 1;
            var length = (float)(f.Length ?? (double)(size?.X ?? 1));
            var stand = f.Mount == "stand" && f.Truss is null && p.Z > 0.6f;
            _units.Add(new Unit
            {
                Id = k, Shape = shape, Idx = idx, P = p, Up = up, Across = across, Length = length, Scale = scale, Size = size,
                Selected = selected.Contains($"fixture:{k}"), Hovered = selected.Contains($"hover:fixture:{k}"), OnStand = stand,
            });
        }
    }

    // MARK: the parts that never move (built with the scenery)

    /// A tripod stand from the floor up to `top`, under a fixture that stands in the air.
    static void Tripod(MeshBuilder m, Vector3 p, float top, Vector3 col, float em)
    {
        if (top <= 0.3f) return;
        m.Cylinder(new(p.X, p.Y, top / 2), new(0, 0, 1), radius: 0.022f, length: top, col, emissive: em, segments: 8);
        m.Cylinder(new(p.X, p.Y, top - 0.01f), new(0, 0, 1), radius: 0.04f, length: 0.03f, col, emissive: em, segments: 8);
        var hub = new Vector3(p.X, p.Y, MathF.Min(0.55f, top * 0.4f));
        for (var k = 0; k < 3; k++)  // three legs out from the hub to the floor
        {
            var a = (float)k / 3 * 2 * MathF.PI + 0.5f;
            var foot = new Vector3(p.X + MathF.Cos(a) * 0.38f, p.Y + MathF.Sin(a) * 0.38f, 0.01f);
            var v = hub - foot;
            m.Cylinder((hub + foot) / 2, Vector3.Normalize(v), radius: 0.014f, length: v.Length(), col, emissive: em, segments: 6);
        }
    }

    public void AddStatic(MeshBuilder m)
    {
        foreach (var u in _units)
        {
            var col = u.Selected ? Pick : u.Hovered ? Lit : BodyColor;
            var em = u.Selected ? 0.7f : u.Hovered ? 0.3f : 0;
            if (u.OnStand)  // its own stand, under the fixture's lowest point
            {
                var bottom = u.Shape switch
                {
                    Shape.BeamHead or Shape.SpotHead or Shape.WashHead => u.P.Z - (HeadGeometryOf(u).ArmLen + 0.12f * u.Scale),
                    Shape.MovingBar or Shape.CurveBar => u.P.Z - 0.25f,
                    _ => u.P.Z - 0.2f,
                };
                Tripod(m, u.P, bottom, u.Selected ? Pick : u.Hovered ? Lit : StandColor, em);
            }
            switch (u.Shape)
            {
                case Shape.BeamHead or Shape.SpotHead or Shape.WashHead:
                {
                    var s = u.Scale;
                    var g = HeadGeometryOf(u);
                    var b = Basis.Along(u.Up, u.Across);
                    var baseC = u.P - u.Up * (g.ArmLen + 0.06f * s);
                    m.Box(baseC, b, new(g.ArmOffset * 2 + 0.1f * s, 0.3f * s, 0.12f * s), col, emissive: em);
                    // the display on the base, faintly lit
                    m.Box(baseC + b.Y * (0.151f * s), b, new(0.08f * s, 0.002f, 0.035f * s), new(0.25f, 0.45f, 0.9f), emissive: 0.5f);
                    break;
                }
                case Shape.MovingBar:
                {
                    var b = Basis.Along(new(0, 0, 1), u.Across);
                    float h = 0.12f, hang = u.Up.Z < 0 ? 1 : -1;
                    foreach (var e in new[] { -1f, 1f })   // the yoke ends that carry the tilting bar
                        m.Box(u.P + u.Across * ((u.Length / 2 + 0.05f) * e) + new Vector3(0, 0, hang * h * 0.55f), b, new(0.07f, 0.12f, h * 1.9f),
                              col * 1.1f, emissive: em);
                    break;
                }
                case Shape.CurveBar:
                {
                    // the base that stays put; its cells tilt on their own above it (dynamic)
                    var b = Basis.Along(u.Up, u.Across);
                    m.Box(u.P - u.Up * 0.1f, b, new(u.Length, 0.16f, 0.08f), col, emissive: em);
                    break;
                }
                case Shape.ParBar:
                {
                    var b = Basis.Along(u.Up, u.Across);
                    float d = MathF.Min(0.25f, u.Size?.Y ?? 0.12f), h = MathF.Min(0.25f, u.Size?.Z ?? 0.1f);
                    m.Box(u.P - u.Up * (h / 2), b, new(u.Length, d, h), col, emissive: em);
                    foreach (var e in new[] { -1f, 1f })   // the brackets
                        m.Box(u.P - u.Up * (h * 0.9f) + u.Across * ((u.Length / 2 - 0.08f) * e), b, new(0.03f, d * 1.2f, h * 0.9f),
                              col * 1.2f, emissive: em);
                    break;
                }
                case Shape.Par:
                {
                    m.Cylinder(u.P - u.Up * 0.1f, u.Up, radius: 0.1f, length: 0.2f, col, emissive: em);
                    m.Cylinder(u.P - u.Up * 0.205f, u.Up, radius: 0.06f, length: 0.02f, col * 0.8f, emissive: em);
                    var b = Basis.Along(u.Up, u.Across);
                    foreach (var e in new[] { -1f, 1f })   // a U bracket
                        m.Box(u.P - u.Up * 0.1f + b.X * (0.12f * e), b, new(0.015f, 0.04f, 0.24f), col * 1.2f, emissive: em);
                    break;
                }
                case Shape.Strobe:
                {
                    var b = Basis.Along(u.Up, u.Across);
                    float w = u.Size?.X ?? 0.42f, h = u.Size?.Z ?? 0.24f;
                    m.Box(u.P - u.Up * 0.08f, b, new(w, h, 0.16f), col, emissive: em);
                    m.Box(u.P - u.Up * 0.165f, b, new(w * 0.6f, h * 0.6f, 0.02f), col * 0.8f, emissive: em);   // the cooling back
                    break;
                }
                case Shape.Blinder:
                {
                    var b = Basis.Along(u.Up, u.Across);
                    m.Box(u.P - u.Up * 0.06f, b, new(0.42f, 0.24f, 0.12f), col, emissive: em);
                    break;
                }
                case Shape.Smoke:
                {
                    // a level box (the real housing when known), its nozzle towards where it blows
                    var s = u.Size ?? new Vector3(0.4f, 0.25f, 0.22f);
                    var fwd = new Vector3(u.Up.X, u.Up.Y, 0);
                    fwd = fwd.Length() > 0.05f ? Vector3.Normalize(fwd) : new Vector3(0, 1, 0);
                    var b = new Basis(Vector3.Cross(fwd, new(0, 0, 1)), new(0, 0, 1), fwd);
                    var c = u.P - fwd * (s.Y / 2) + new Vector3(0, 0, s.Z / 2 - 0.1f);
                    m.Box(c, b, new(s.X, s.Z, s.Y), col, emissive: em);
                    m.Cylinder(u.P + new Vector3(0, 0, s.Z / 2 - 0.12f) + u.Up * 0.02f, u.Up, radius: MathF.Min(0.045f, s.X * 0.15f), length: 0.06f,
                               col * 1.4f, emissive: em);
                    break;
                }
                case Shape.Laser:
                {
                    var b = Basis.Along(u.Up, new(1, 0, 0));
                    m.Box(u.P - u.Up * 0.12f, b, new(0.24f, 0.12f, 0.24f), col * 0.9f, emissive: em);
                    m.Box(u.P - u.Up * 0.12f + b.Y * 0.061f, b, new(0.2f, 0.002f, 0.08f), new(0.6f, 0.6f, 0.65f), emissive: 0.05f);  // the label
                    break;
                }
            }
        }
    }

    // MARK: every frame: the moving parts and the lenses

    /// What an element shows this frame: its dimmer and colour (normalised).
    static (float Dim, Vector3 Col) Light(int i, Frame? frame, bool hl)
    {
        float dim = 0;
        var col = Vector3.One;
        if (frame is not null && i < frame.Fx.Length && frame.Fx[i].Length >= 5)
        {
            var v = frame.Fx[i];
            dim = MathF.Min(1, v[0]); col = new Vector3(v[1] + v[4], v[2] + v[4], v[3] + v[4]);
        }
        if (hl) { dim = 1; col = Vector3.One; }
        return (dim, col / MathF.Max(Max(col), 1));
    }

    static void Lens(MeshBuilder m, Vector3 c, Vector3 n, float r, float dim, Vector3 col, float glow = 1.4f)
    {
        if (dim > 0.01f) m.Disc(c, n, radius: r, col, emissive: glow * dim + 0.05f);
        else m.Disc(c, n, radius: r, GlassColor, emissive: 0);
    }

    readonly record struct HeadGeometry(float HeadR, float HeadL, float LensR, float ArmOffset, float ArmLen);

    static HeadGeometry HeadGeometryOf(Unit u)
    {
        var s = u.Scale;
        return u.Shape switch
        {
            Shape.BeamHead => new(0.1f * s, 0.3f * s, 0.08f * s, 0.14f * s, 0.22f * s),
            Shape.WashHead => new(0.17f * s, 0.2f * s, 0.155f * s, 0.2f * s, 0.26f * s),
            _ => new(0.13f * s, 0.4f * s, 0.09f * s, 0.17f * s, 0.26f * s),
        };
    }

    static Vector3? Dir(Frame? frame, int i) => frame is not null && i < frame.Dirs.Length ? frame.Dirs[i] : null;

    /// The moving parts and lenses for this frame, into `m` (cleared first).
    public void Dynamic(IReadOnlyList<FixtureInfo> fixtures, Frame? frame, IReadOnlySet<string> highlight, MeshBuilder m)
    {
        m.Clear();
        if (m.V.Capacity < _units.Count * 400) m.V.Capacity = _units.Count * 400;
        foreach (var u in _units)
        {
            var col = u.Selected ? Pick : u.Hovered ? Lit : YokeColor;
            var em = u.Selected ? 0.7f : u.Hovered ? 0.3f : 0;
            var hl = u.Idx.Any(i => highlight.Contains(fixtures[i].Id));
            switch (u.Shape)
            {
                case Shape.BeamHead or Shape.SpotHead or Shape.WashHead:
                {
                    var i = u.Idx[0];
                    var g = HeadGeometryOf(u);
                    var s = u.Scale;
                    var d = Vector3.Normalize(Dir(frame, i) ?? Vector3.Normalize(u.Up + new Vector3(0, 0.6f, 0)));
                    // the yoke pans so the tilt axis is square to the beam; along the pan axis it keeps its last angle
                    var t = Vector3.Cross(u.Up, d);
                    if (t.Length() < 0.05f) t = _tiltAxis.TryGetValue(u.Id, out var keep) ? keep : Basis.Along(u.Up, u.Across).X;
                    t = Vector3.Normalize(t);
                    if (_tiltAxis.TryGetValue(u.Id, out var last) && Vector3.Dot(last, t) < 0) t = -t;   // a symmetric yoke: no sudden flips
                    _tiltAxis[u.Id] = t;
                    var yoke = new Basis(t, Vector3.Cross(u.Up, t), u.Up);
                    // the yoke: a turntable, a bridge and two arms up to the tilt axis
                    m.Cylinder(u.P - u.Up * (g.ArmLen - 0.005f * s), u.Up, radius: 0.07f * s, length: 0.03f * s, col * 0.8f, emissive: em);
                    m.Box(u.P - u.Up * (g.ArmLen - 0.03f * s), yoke, new(g.ArmOffset * 2 + 0.05f * s, 0.11f * s, 0.04f * s), col, emissive: em);
                    foreach (var e in new[] { -1f, 1f })
                    {
                        m.Box(u.P - u.Up * (g.ArmLen / 2 - 0.01f * s) + t * (g.ArmOffset * e), yoke,
                              new(0.04f * s, 0.1f * s, g.ArmLen + 0.02f * s), col, emissive: em);
                        m.Cylinder(u.P + t * ((g.ArmOffset - 0.025f * s) * e), t, radius: 0.045f * s, length: 0.03f * s,
                                   col * 1.15f, emissive: em);
                    }
                    // the head: a barrel along the beam, a bezel and the lens
                    var headCol = u.Selected ? Pick : BodyColor;
                    m.Cylinder(u.P - d * (g.HeadL * 0.15f), d, radius: g.HeadR, length: g.HeadL, headCol, emissive: em);
                    var front = u.P + d * (g.HeadL * 0.35f);
                    m.Cylinder(front, d, radius: g.HeadR * 1.04f, length: 0.025f * s, headCol * 1.6f, emissive: em, caps: false);
                    var (dim, lc) = Light(i, frame, hl);
                    Lens(m, front + d * 0.003f, d, g.LensR, dim, lc, glow: u.Shape == Shape.WashHead ? 0.6f : 1.6f);
                    if (u.Shape == Shape.WashHead)   // the LEDs of a wash: one in the middle, a ring around it
                    {
                        var b = Basis.Along(d, t);
                        for (var k = 0; k < 7; k++)
                        {
                            var a = (float)k / 6 * 2 * MathF.PI;
                            var off = k == 6 ? Vector3.Zero : (b.X * MathF.Cos(a) + b.Y * MathF.Sin(a)) * (g.LensR * 0.62f);
                            Lens(m, front + d * 0.006f + off, d, g.LensR * 0.22f, dim, lc, glow: 1.8f);
                        }
                    }
                    break;
                }
                case Shape.MovingBar:
                {
                    // the bar tilts on its long axis towards where its cells shine
                    var face = Vector3.Zero;
                    foreach (var i in u.Idx)
                        if (Dir(frame, i) is { } v) face += Vector3.Normalize(v);
                    if (face.Length() < 1e-3f) face = u.Up + new Vector3(0, 0.6f, 0);
                    face -= u.Across * Vector3.Dot(face, u.Across);
                    if (face.Length() < 1e-3f) face = u.Up;
                    face = Vector3.Normalize(face);
                    var b = Basis.Along(face, u.Across);
                    float h = 0.12f, d = 0.1f;
                    m.Box(u.P - face * 0.02f, b, new(u.Length, d, h), u.Selected ? Pick : BodyColor, emissive: em);
                    foreach (var e in new[] { -1f, 1f })
                        m.Cylinder(u.P + u.Across * ((u.Length / 2 + 0.01f) * e), u.Across, radius: 0.04f, length: 0.03f, col, emissive: em);
                    var pitch = u.Length / Math.Max(1, u.Idx.Length);
                    foreach (var i in u.Idx)
                    {
                        var (dim, lc) = Light(i, frame, hl);
                        var along = Vector3.Dot(_positions[i] - u.P, u.Across);
                        Lens(m, u.P + u.Across * along + face * (h / 2 - 0.02f + 0.002f), face, MathF.Min(0.04f, pitch * 0.38f), dim, lc);
                    }
                    break;
                }
                case Shape.CurveBar:
                {
                    // every cell its own little head, tilting on its own motor towards where it shines
                    var pitch = u.Length / Math.Max(1, u.Idx.Length);
                    foreach (var i in u.Idx)
                    {
                        var face = Dir(frame, i) ?? u.Up + new Vector3(0, 0.6f, 0);
                        face -= u.Across * Vector3.Dot(face, u.Across);
                        face = face.Length() < 1e-3f ? u.Up : Vector3.Normalize(face);
                        var along = Vector3.Dot(_positions[i] - u.P, u.Across);
                        var c = u.P + u.Across * along;
                        m.Box(c - u.Up * 0.04f, Basis.Along(u.Up, u.Across), new(pitch * 0.25f, 0.08f, 0.06f), col, emissive: em);
                        m.Box(c, Basis.Along(face, u.Across), new(pitch * 0.8f, 0.09f, 0.1f), u.Selected ? Pick : BodyColor, emissive: em);
                        var (dim, lc) = Light(i, frame, hl);
                        Lens(m, c + face * 0.052f, face, MathF.Min(0.035f, pitch * 0.33f), dim, lc);
                    }
                    break;
                }
                case Shape.ParBar:
                {
                    var pitch = u.Length / Math.Max(1, u.Idx.Length);
                    var d = MathF.Min(0.25f, u.Size?.Y ?? 0.12f);
                    foreach (var i in u.Idx)
                    {
                        var (dim, lc) = Light(i, frame, hl);
                        var along = Vector3.Dot(_positions[i] - u.P, u.Across);
                        Lens(m, u.P + u.Across * along + u.Up * 0.002f, u.Up, MathF.Min(MathF.Min(0.05f, d * 0.4f), pitch * 0.4f), dim, lc);
                    }
                    break;
                }
                case Shape.Par:
                {
                    var (dim, lc) = Light(u.Idx[0], frame, hl);
                    Lens(m, u.P + u.Up * 0.002f, u.Up, 0.085f, dim, lc);
                    break;
                }
                case Shape.Strobe:
                {
                    var (dim, _) = Light(u.Idx[0], frame, hl);
                    var b = Basis.Along(u.Up, u.Across);
                    float w = u.Size?.X ?? 0.42f, hh = u.Size?.Z ?? 0.24f;
                    m.Box(u.P + u.Up * 0.002f, b, new(w * 0.86f, hh * 0.62f, 0.004f), dim > 0.01f ? new(0.9f, 0.95f, 1) : GlassColor,
                          emissive: dim > 0.01f ? dim * 3 : 0);
                    break;
                }
                case Shape.Blinder:
                {
                    var (dim, lc) = Light(u.Idx[0], frame, hl);
                    var b = Basis.Along(u.Up, u.Across);
                    var warm = Vector3.Lerp(lc, new(1, 0.75f, 0.45f), 0.5f);
                    foreach (var e in new[] { -1f, 1f })
                    {
                        var c = u.P + u.Up * 0.002f + b.X * (0.1f * e);
                        m.Cylinder(c - u.Up * 0.01f, u.Up, radius: 0.09f, length: 0.02f, BodyColor * 1.5f, caps: false);
                        Lens(m, c, u.Up, 0.08f, dim, warm, glow: 1.8f);
                    }
                    break;
                }
                case Shape.Laser:
                {
                    var (dim, lc) = Light(u.Idx[0], frame, hl);
                    Lens(m, u.P + u.Up * 0.002f, u.Up, 0.025f, dim, lc, glow: 3);
                    break;
                }
                case Shape.Smoke:
                {
                    // its ready light: green, amber while it fires
                    var firing = hl || (frame?.Fog.GetValueOrDefault(fixtures[u.Idx[0]].Id) ?? 0) > 0;
                    var s = u.Size ?? new Vector3(0.4f, 0.25f, 0.22f);
                    m.Disc(u.P + new Vector3(0, 0, s.Z / 2 - 0.1f + 0.001f), new(0, 0, 1), radius: 0.012f,
                           firing ? new(1, 0.6f, 0.2f) : new(0.3f, 0.8f, 0.45f), emissive: firing ? 3 : 0.8f);
                    break;
                }
            }
        }
    }
}
