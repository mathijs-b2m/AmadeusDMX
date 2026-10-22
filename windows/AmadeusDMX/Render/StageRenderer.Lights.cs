// The lights of one frame: beams, spots on surfaces, lens flares and laser lines, from the feed's frame
// (mac/Sources/AmadeusDMX/Render/StageRenderer+Lights.swift). A head with a gobo in its beam draws it as a gobo beam:
// the pattern in the haze and projected where it lands, turning, shaking and sliding on its wheel as the frame says;
// its zoom sets how wide the beam opens.
using System.Numerics;

using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

public sealed partial class StageRenderer
{
    static float Max(Vector3 v) => MathF.Max(v.X, MathF.Max(v.Y, v.Z));

    internal void BuildLights(StageInput inp, Frame? frame, Scenery s, Vector3 eye, float t, List<BeamInstance> beams,
                              List<SpriteInstance> sprites, List<DecalInstance> decals, List<LineInstance> lines,
                              List<GoboBeamInstance> goboBeams, List<GoboDecalInstance> goboDecals, ref Vector3 ambient)
    {
        var room = s.Room;
        var nHeads = Math.Max(1, inp.Fixtures.Count(f => f.Kind == FixtureKind.Head));
        var density = MathF.Min(1, 4 / MathF.Sqrt(nHeads));
        var lightSum = Vector3.Zero;
        var highlight = Highlight;

        void Beam(Vector3 p, Vector3 d, float spreadDeg, Vector3 color, float intensity, float maxLen = 30, bool spot = true)
        {
            var (len, surf) = room.Hit(p, d, maxLen);
            var R = MathF.Max(0.05f, len * MathF.Tan(spreadDeg * MathF.PI / 360));
            beams.Add(new BeamInstance(new(p, len), new(d, R), new(color, intensity), new(0.05f, 0, 0, 0)));
            if (spot && surf != Room.Surface.Air)
            {
                var n = Room.Normal(surf);
                var squash = surf == Room.Surface.Floor ? MathF.Max(1, MathF.Min(3, 1 / MathF.Max(0.25f, MathF.Abs(d.Z)))) : 1;
                decals.Add(new DecalInstance(new(p + d * len, MathF.Max(0.12f, R * 1.3f)), new(n, squash), new(color, intensity * 0.9f)));
            }
        }

        void GoboBeam(Vector3 p, Vector3 d, float spreadDeg, Vector3 color, float intensity, Vector4 wheel, Vector4 axis)
        {
            var (len, surf) = room.Hit(p, d, 30);
            float r0 = wheel.W, R = MathF.Max(r0 + 0.01f, len * MathF.Tan(spreadDeg * MathF.PI / 360));
            goboBeams.Add(new GoboBeamInstance(new(p, len), new(d, R), new(color, intensity), wheel, axis));
            if (surf != Room.Surface.Air)
            {
                var n = Room.Normal(surf);
                var squash = MathF.Max(1, MathF.Min(3, 1 / MathF.Max(0.25f, MathF.Abs(Vector3.Dot(d, n)))));
                goboDecals.Add(new GoboDecalInstance(new(p + d * len, MathF.Max(0.12f, R * 1.15f)), new(n, squash),
                                                     new(color, intensity * 0.75f), new(p, len),
                                                     new(d, (R - r0) / MathF.Max(len, 1e-3f)), wheel, axis));
            }
        }

        // gobos turn and shake with the renderer's own clock (smooth between the show's frames)
        var gdt = MathF.Min(0.2f, MathF.Max(0, t - GoboT));
        GoboT = t;

        // smoke: a plume blows out of the nozzle on each burst and lingers; the room's haze builds up and clears
        var dt = MathF.Min(0.2f, MathF.Max(0, t - FogT));
        FogT = t;
        float fogSum = 0;
        foreach (var fx in inp.Fixtures)
        {
            if (fx.Kind != FixtureKind.Smoke) continue;
            var output = highlight.Contains(fx.Id) ? 0.6f : frame?.Fog.GetValueOrDefault(fx.Id) ?? 0;
            var pf = FogPuffs.TryGetValue(fx.Id, out var had) ? had : new Vector2(0, 9);   // (amount, seconds since it fired)
            pf = output > 0 ? new Vector2(MathF.Max(pf.X, output), 0) : new Vector2(pf.X * MathF.Exp(-dt / 2.5f), pf.Y + dt);
            FogPuffs[fx.Id] = pf;
            fogSum += output;
            if (pf.X <= 0.02f) continue;
            var p = fx.Pos.ToFloat();
            var d = fx.Dir?.ToFloat() ?? new Vector3(0, 0.98f, 0.17f);
            d = Vector3.Normalize(d + new Vector3(0, 0, 0.15f * MathF.Min(1, pf.Y / 3)));   // warm fog rises as it drifts
            var reach = 0.6f + 2.6f * MathF.Min(1, pf.Y / 2 + pf.X * 0.6f);
            Beam(p, d, spreadDeg: 38 + 20 * MathF.Min(1, pf.Y / 3), color: new(0.82f, 0.85f, 0.9f), intensity: 0.5f * pf.X,
                 maxLen: reach, spot: false);
        }
        RoomFog = MathF.Min(1, RoomFog * MathF.Exp(-dt / 90) + fogSum * dt * 0.08f);

        Span<Vector3> rays = stackalloc Vector3[3];
        for (var i = 0; i < inp.Fixtures.Count; i++)
        {
            var fx = inp.Fixtures[i];
            var p = fx.Pos.ToFloat();
            float dim = 0;
            var col = Vector3.One;
            if (frame is not null && i < frame.Fx.Length)
            {
                var v = frame.Fx[i];
                if (v.Length >= 5) { dim = MathF.Min(1, v[0]); col = new Vector3(v[1] + v[4], v[2] + v[4], v[3] + v[4]); }
            }
            else if (highlight.Contains(fx.Id))
            {
                dim = 1;
            }
            if (highlight.Contains(fx.Id)) { dim = MathF.Max(dim, 0.9f); col = Vector3.One; }
            var cm = MathF.Max(Max(col), 1);
            col /= cm;
            if (dim <= 0.01f || fx.Kind == FixtureKind.Smoke) continue;   // a dark fixture: its model shows it (dark glass in the lens)
            lightSum += col * dim;

            switch (fx.Kind)
            {
                case FixtureKind.Head:
                {
                    var rest = fx.Up?.ToFloat() ?? new Vector3(0, 0, -1);
                    var d = Vector3.Normalize((frame is not null && i < frame.Dirs.Length ? frame.Dirs[i] : null)
                                              ?? Vector3.Normalize(rest + new Vector3(0, 0.6f, 0)));
                    var name = (frame is not null && i < frame.Beam.Length ? frame.Beam[i] : null) ?? "open";
                    var gobo = highlight.Contains(fx.Id) ? null : frame is not null && i < frame.Gobo.Length ? frame.Gobo[i] : null;
                    // the lens with the zoom the show sends: between its tightest and widest beam, as bright as the light
                    // packed into it
                    var zoom = frame is not null && i < frame.Zoom.Length ? frame.Zoom[i] : null;
                    var lens = (float)fx.BeamDeg + (float)(fx.BeamWide - fx.BeamDeg) * (zoom ?? 0);
                    var zoomed = (float)fx.Output + (float)(fx.OutputWide - fx.Output) * (zoom ?? 0);
                    // the gobo's picture across the beam: along the head's tilt axis (pan turns it with the head)
                    var tilt = Vector3.Cross(rest, d);
                    if (tilt.Length() > 0.15f) GoboAxis[fx.Id] = Vector3.Normalize(tilt);
                    var across = GoboAxis.TryGetValue(fx.Id, out var kept) ? kept
                        : MathF.Abs(d.Z) > 0.9f ? new Vector3(1, 0, 0) : Vector3.Normalize(Vector3.Cross(d, new Vector3(0, 0, 1)));
                    var turn = GoboTurn.GetValueOrDefault(fx.Id);
                    if (gobo is { } gt) turn = (turn + gt.Turn * 2 * MathF.PI * gdt) % (2 * MathF.PI);
                    GoboTurn[fx.Id] = turn;
                    var prism = name.StartsWith("prism", StringComparison.Ordinal) || gobo?.Prism == true;
                    var nRays = 1;
                    rays[0] = d;
                    if (prism)
                    {
                        var side = MathF.Abs(d.Z) > 0.9f ? new Vector3(1, 0, 0) : new Vector3(0, 0, 1);
                        var a1 = Vector3.Normalize(Vector3.Cross(d, side));
                        var a2 = Vector3.Cross(d, a1);
                        var spin = gobo is not null ? turn : name != "prism" ? t * 2.5f : 0;
                        for (var k = 0; k < 3; k++)
                        {
                            var a = spin + k * 2.094f;
                            rays[k] = Vector3.Normalize(d + 0.07f * (MathF.Cos(a) * a1 + MathF.Sin(a) * a2));
                        }
                        nRays = 3;
                    }
                    var frost = name == "frost";
                    var spread = frost ? MathF.Max((float)fx.BeamWide, 25) * 1.2f : MathF.Max(lens * 1.6f, 2.5f);
                    var strength = frost ? (float)fx.OutputWide : zoomed;
                    var a0 = (frost ? dim * 0.45f : nRays > 1 ? dim * 0.6f : dim) * density * strength * 0.75f;
                    if (highlight.Contains(fx.Id)) a0 = 2.5f;
                    if (gobo is { } g && GoboSlices > 0)
                    {
                        // a shaking gobo wobbles on its wheel: a little to and fro, a little turned
                        var wobble = g.Shake > 0 ? MathF.Sin(t * g.Shake * 2 * MathF.PI) : 0;
                        var slices = GoboSlices;
                        float Slot(int k) => k >= 0 && k < slices ? k : -1;
                        var wheel = new Vector4(Slot(g.Picture), Slot(g.Next), MathF.Min(1, MathF.Max(0, g.Slide + wobble * 0.06f)), 0.05f);
                        var rot = (prism ? 0 : turn) + wobble * 0.25f;
                        // a gobo is projected with the lens as it is (the haze cone's extra width would blur the pattern); its
                        // shafts a little brighter than a plain beam's haze, as the metal between them takes most of the light
                        for (var k = 0; k < nRays; k++)
                            GoboBeam(p, rays[k], spreadDeg: MathF.Max(lens * 1.25f, 2.5f), color: col, intensity: a0 * 1.5f, wheel: wheel,
                                     axis: new Vector4(across, rot));
                    }
                    else
                    {
                        for (var k = 0; k < nRays; k++) Beam(p, rays[k], spreadDeg: spread, color: col, intensity: a0);
                    }
                    // the lens glows in the model; a flare only when the head points at the viewer (audience scanning),
                    // smaller for the cells of a bar (many small lenses, not one big one)
                    var toEye = Vector3.Normalize(eye - p);
                    var glare = MathF.Pow(MathF.Max(0, Vector3.Dot(d, toEye)), 8);
                    if (glare > 0.05f)
                    {
                        var cellK = 1 / MathF.Sqrt(Math.Max(1, fx.Cells ?? 1));
                        var size = MathF.Min(0.08f + 0.3f * glare, MathF.Max(0.1f, (eye - p).Length() * 0.035f)) * cellK;
                        sprites.Add(new SpriteInstance(new(p, size), new(col, MathF.Min(2.0f, dim * glare * 2) * cellK),
                                                       new(glare > 0.6f ? 1 : 0.3f, 0, 0, 0)));
                    }
                    break;
                }
                case FixtureKind.Laser:
                {
                    var beamsLZ = frame is not null && i < frame.Lz.Length ? frame.Lz[i] : null;
                    if (beamsLZ is null || beamsLZ.Length == 0)
                    {
                        if (highlight.Contains(fx.Id))
                            sprites.Add(new SpriteInstance(new(p, 0.2f), new(0, 1, 0.3f, 2), new(1, 0, 0, 0)));
                        continue;
                    }
                    var thin = 1 / MathF.Max(1, MathF.Sqrt(beamsLZ.Length / 6f));
                    var hot = Vector3.Zero;
                    foreach (var b in beamsLZ)
                    {
                        var a = b.Bright * dim;
                        if (a <= 0.02f) continue;
                        var d = Vector3.Normalize(b.Dir);
                        var (len, surf) = room.Hit(p, d, maxLen: 40);
                        var end = p + d * len;
                        lines.Add(new LineInstance(new(p, 0.05f * thin), new(end, 0), new(b.Color, a * 0.22f * thin)));
                        lines.Add(new LineInstance(new(p, 0.008f), new(end, 0), new(b.Color, a * 2.6f)));
                        if (surf != Room.Surface.Air)
                            decals.Add(new DecalInstance(new(end, 0.06f), new(Room.Normal(surf), 1), new(b.Color, a * 3)));
                        hot += b.Color * a / beamsLZ.Length;
                    }
                    var hm = MathF.Max(Max(hot), 0.01f);
                    sprites.Add(new SpriteInstance(new(p, 0.22f), new(hot / hm, MathF.Min(1, dim) * 2.5f), new(1, 0, 0, 0)));
                    break;
                }
                case FixtureKind.Blinder:
                {
                    var bd = fx.Dir?.ToFloat() ?? new Vector3(0, 1, 0.12f);
                    Beam(p, Vector3.Normalize(bd), spreadDeg: 70, color: col, intensity: dim * 0.5f, maxLen: 5, spot: false);
                    sprites.Add(new SpriteInstance(new(p + Vector3.Normalize(bd) * 0.02f, 0.18f * (1 + dim)),
                                                   new(Vector3.Lerp(col, new(1, 0.95f, 0.85f), 0.5f), dim * 0.9f), new(0.3f, 0, 0, 0)));
                    break;
                }
                case FixtureKind.Strobe:
                {
                    // one blinding white flash from the face, flooding the room for a moment
                    var sd = fx.Dir?.ToFloat() ?? new Vector3(0, 1, 0.14f);
                    Beam(p, Vector3.Normalize(sd), spreadDeg: 100, color: Vector3.One, intensity: dim * 0.9f, maxLen: 8);
                    sprites.Add(new SpriteInstance(new(p, 0.35f * (1 + 1.5f * dim)), new(0.9f, 0.95f, 1, dim * 3), new(1, 0, 0, 0)));
                    lightSum += new Vector3(dim * 8);   // the whole room lights up
                    break;
                }
                default:  // par, smoke, other
                {
                    // a bar's cells share its light: many small beams, not many full-strength ones
                    var cellK = (fx.Cells ?? 1) > 1 ? 1.6f / fx.Cells!.Value : 1;
                    var pd = fx.Dir?.ToFloat() ?? new Vector3(0, 0.18f, 1);
                    // a wash with a zoom opens as the show sends it
                    var zoom = frame is not null && i < frame.Zoom.Length ? frame.Zoom[i] : null;
                    var lens = zoom is { } z ? (float)fx.BeamDeg + (float)(fx.BeamWide - fx.BeamDeg) * z : MathF.Min((float)fx.BeamDeg, 40);
                    Beam(p, Vector3.Normalize(pd), spreadDeg: lens, color: col, intensity: dim * 0.8f * cellK, maxLen: 3.5f);
                    if ((fx.Cells ?? 1) <= 1)   // a bar's cells glow in its model; a single par gets a soft halo
                        sprites.Add(new SpriteInstance(new(p, 0.16f), new(col, dim * 0.35f), Vector4.Zero));
                    break;
                }
            }
        }
        ambient = lightSum / Math.Max(1, inp.Fixtures.Count) * 0.8f;
    }
}
