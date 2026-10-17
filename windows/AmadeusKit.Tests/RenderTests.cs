// The 3D stage's pure half (AmadeusDMX/Render, linked in): camera maths, the GPU buffers' packing against the
// HLSL, geometry, frame pacing, the adaptive resolution and the LED wall's picture. The Direct3D half needs Windows
// (`AmadeusDMX.exe -renderSelfTest`).
using System.Numerics;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using AmadeusDMX;

namespace AmadeusKit.Tests;

public class RenderTests
{
    static Vector4 Clip(Matrix4x4 m, Vector3 p) => Vector4.Transform(new Vector4(p, 1), m);

    [Fact]
    public void LookAtPutsTheTargetInTheMiddle()
    {
        var eye = new Vector3(3, 12, 4);
        var target = new Vector3(3, -1, 2);
        var vp = Float4x4.LookAt(eye, target, new(0, 0, 1)) * Float4x4.Perspective(0.75f, 16f / 9, 0.1f, 300);
        var c = Clip(vp, target);
        Assert.Equal(0, c.X / c.W, 4);
        Assert.Equal(0, c.Y / c.W, 4);
        Assert.InRange(c.Z / c.W, 0, 1);   // Direct3D's (and Metal's) depth range
        // up is up, and +x (stage left, seen from the audience) is on the screen's left
        var above = Clip(vp, target + new Vector3(0, 0, 1));
        Assert.True(above.Y / above.W > 0);
        var left = Clip(vp, target + new Vector3(1, 0, 0));
        Assert.True(left.X / left.W < 0);
    }

    [Fact]
    public void DepthRunsFromNearToFar()
    {
        var p = Float4x4.Perspective(0.75f, 1, 0.1f, 300);
        var near = Clip(p, new(0, 0, -0.1f));
        var far = Clip(p, new(0, 0, -300));
        Assert.Equal(0, near.Z / near.W, 4);
        Assert.Equal(1, far.Z / far.W, 3);
    }

    [Fact]
    public void MatricesAreLaidOutLikeSwiftsColumns()
    {
        // Swift's perspective has -1 in column 2, row 3: the 12th float (index 11) of a column-major float4x4
        var p = Float4x4.Perspective(0.75f, 1, 0.1f, 300);
        var floats = MemoryMarshal.Cast<Matrix4x4, float>(MemoryMarshal.CreateSpan(ref p, 1));
        Assert.Equal(-1, floats[11]);
        Assert.Equal(0, floats[14] == 0 ? 1 : 0);   // column 3, row 2: zs * near, non-zero
    }

    [Fact]
    public void PoseRoundTripsThroughEyeAndTarget()
    {
        var pose = CameraPose.From(new(5, 10, 6), new(3, -1, 2));
        Assert.Equal(5, pose.Eye.X, 3);
        Assert.Equal(10, pose.Eye.Y, 3);
        Assert.Equal(6, pose.Eye.Z, 3);
        var a = new CameraPose(Vector3.Zero, 3.0f, 0, 10);
        var b = new CameraPose(Vector3.Zero, -3.0f, 0, 10);
        var mid = CameraPose.Lerp(a, b, 0.5f);   // the short way round, across ±π
        Assert.True(MathF.Abs(MathF.Abs(mid.Yaw) - MathF.PI) < 0.2f);
    }

    [Fact]
    public void PresetsLookAtTheStage()
    {
        foreach (var p in CameraPresets.AllCases)
        {
            var pose = p.Pose(6, 3.5f, -4, 4.5f);
            Assert.True(pose.Distance > 1, p.RawValue());
            Assert.True(pose.Eye.Z > 0, p.RawValue());
            Assert.Equal(p, CameraPresets.FromRawValue(p.RawValue()));
        }
    }

    [Fact]
    public void RayThroughTheMiddleLooksAtTheTarget()
    {
        var r = Renderer(SceneSamples.Club());
        var (o, d) = r.Ray(new(400, 300), new(800, 600));
        var toTarget = Vector3.Normalize(r.Pose.Target - o);
        Assert.True(Vector3.Dot(d, toTarget) > 0.9999f);
        // a point above the middle (AppKit points: origin bottom-left) looks higher
        var (_, up) = r.Ray(new(400, 500), new(800, 600));
        Assert.True(up.Z > d.Z);
    }

    [Fact]
    public void ThePresetsFrameTheRig()
    {
        // end to end: the uniforms' matrix (as the shaders get it) puts every fixture on screen from the audience
        var inp = SceneSamples.Club();
        foreach (var preset in new[] { CameraPreset.FrontOfHouse, CameraPreset.Drone, CameraPreset.Plan })
        {
            var r = new StageRenderer { Input = () => (inp, null) };
            var f = new StageFrame();
            r.PrepareFrame(f, StageRenderer.Now(), new(1280, 720));
            r.SetPreset(preset, animated: false);
            r.PrepareFrame(f, StageRenderer.Now(), new(1280, 720));
            foreach (var fx in inp.Fixtures)
            {
                var c = Clip(f.U.ViewProj, fx.Pos.ToFloat());
                Assert.True(c.W > 0, $"{preset}: {fx.Id} behind the camera");
                Assert.InRange(c.X / c.W, -1, 1);
                Assert.InRange(c.Y / c.W, -1, 1);
                Assert.InRange(c.Z / c.W, 0, 1);
            }
        }
    }

    // MARK: packing: the C# structs against the HLSL declarations

    [Fact]
    public void StructSizesMatchTheShaders()
    {
        Assert.Equal(Uniforms.Size, Marshal.SizeOf<Uniforms>());
        Assert.Equal(Uniforms.Size, Unsafe.SizeOf<Uniforms>());
        Assert.Equal(BeamInstance.Size, Marshal.SizeOf<BeamInstance>());
        Assert.Equal(SpriteInstance.Size, Marshal.SizeOf<SpriteInstance>());
        Assert.Equal(DecalInstance.Size, Marshal.SizeOf<DecalInstance>());
        Assert.Equal(LineInstance.Size, Marshal.SizeOf<LineInstance>());
        Assert.Equal(WallParams.Size, Marshal.SizeOf<WallParams>());
        Assert.Equal(BlurParams.Size, Marshal.SizeOf<BlurParams>());
        Assert.Equal(SolidVertex.Size, Marshal.SizeOf<SolidVertex>());
        Assert.Equal(SolidVertex.NormalOffset, (int)Marshal.OffsetOf<SolidVertex>(nameof(SolidVertex.Normal)));
        Assert.Equal(SolidVertex.ColorOffset, (int)Marshal.OffsetOf<SolidVertex>(nameof(SolidVertex.Color)));
        Assert.Equal(WallVertex.Size, Marshal.SizeOf<WallVertex>());
        Assert.Equal(WallVertex.UvOffset, (int)Marshal.OffsetOf<WallVertex>(nameof(WallVertex.Uv)));
        foreach (var s in new[] { Uniforms.Size, WallParams.Size, BlurParams.Size }) Assert.Equal(0, s % 16);   // cbuffers
    }

    static string Shader(string name)
    {
        using var s = typeof(SceneSamples).Assembly.GetManifestResourceStream($"AmadeusDMX.Render.Shaders.{name}")
            ?? Assembly.GetExecutingAssembly().GetManifestResourceStream($"AmadeusDMX.Render.Shaders.{name}")
            ?? throw new FileNotFoundException(name);
        return new StreamReader(s).ReadToEnd();
    }

    /// The byte size of an HLSL struct of float4 / float4x4 members (all the shaders use), by its declaration.
    static int HlslSize(string source, string type)
    {
        var m = Regex.Match(source, @"(?:struct|cbuffer)\s+" + type + @"\b[^{]*\{(?<body>[^}]*)\}");
        Assert.True(m.Success, type);
        var size = 0;
        foreach (Match f in Regex.Matches(m.Groups["body"].Value, @"\b(float4x4|float4)\s+(\w+)\s*(?:\[(\d+)\])?\s*;"))
            size += (f.Groups[1].Value == "float4x4" ? 64 : 16) * (f.Groups[3].Success ? int.Parse(f.Groups[3].Value) : 1);
        Assert.False(Regex.IsMatch(m.Groups["body"].Value, @"\b(float|float2|float3|int|uint)\s+\w+\s*;"), $"{type}: only float4s");
        return size;
    }

    [Fact]
    public void HlslDeclarationsMatchTheStructs()
    {
        var common = Shader("Common.hlsli");
        Assert.Equal(Uniforms.Size, HlslSize(common, "Uniforms"));
        Assert.Equal(BeamInstance.Size, HlslSize(common, "BeamInstance"));
        Assert.Equal(SpriteInstance.Size, HlslSize(common, "SpriteInstance"));
        Assert.Equal(DecalInstance.Size, HlslSize(common, "DecalInstance"));
        Assert.Equal(LineInstance.Size, HlslSize(common, "LineInstance"));
        Assert.Equal(WallParams.Size, HlslSize(common, "WallParams"));
        Assert.Equal(BlurParams.Size, HlslSize(common, "BlurParams"));
    }

    [Fact]
    public void ShadersAreBalancedAndHaveTheirEntryPoints()
    {
        foreach (var (file, entries) in ShaderFiles)
        {
            var src = Shader(file);
            Assert.Equal(src.Count(c => c == '{'), src.Count(c => c == '}'));
            Assert.Equal(src.Count(c => c == '('), src.Count(c => c == ')'));
            foreach (var e in entries) Assert.Matches(new Regex(@"\b" + e + @"\s*\("), src);
            Assert.DoesNotContain("metal", src);
            Assert.DoesNotContain("[[", src);   // no Metal attributes left
        }
    }

    static readonly (string, string[])[] ShaderFiles =
    [
        ("Solid.hlsl", ["solid_vertex", "solid_fragment", "zone_fragment"]),
        ("Beam.hlsl", ["beam_vertex", "beam_fragment"]),
        ("Sprite.hlsl", ["sprite_vertex", "sprite_fragment"]),
        ("Decal.hlsl", ["decal_vertex", "decal_fragment"]),
        ("Line.hlsl", ["line_vertex", "line_fragment"]),
        ("Wall.hlsl", ["wall_vertex", "wall_fragment"]),
        ("Post.hlsl", ["fullscreen_vertex", "composite_fragment", "downsample_fragment", "blur_fragment"]),
    ];

    // MARK: scenery, models and lights

    static StageRenderer Renderer(StageInput inp, Frame? frame = null)
    {
        var r = new StageRenderer { Input = () => (inp, frame) };
        r.PrepareFrame(new StageFrame(), StageRenderer.Now(), new(800, 600));
        return r;
    }

    [Fact]
    public void SceneryIsBuiltFromTheRig()
    {
        var inp = SceneSamples.Club();
        var s = new Scenery(inp.Fixtures, inp.Stage, inp.Screen, inp.Trusses, inp.Selected);
        Assert.Equal(0, s.Vertices.Count % 3);
        Assert.True(s.Vertices.Count > 1000);
        Assert.NotNull(s.Wall);
        Assert.True(s.Room.Back < s.Wall!.Value.Center.Y);   // the back wall is behind the LED wall
        Assert.All(s.Vertices, v => Assert.True(float.IsFinite(v.Pos.X + v.Pos.Y + v.Pos.Z) && MathF.Abs(v.Normal.Length() - 1) < 1e-3f));
        // the units: 4 heads, one bar of 8 cells, 2 pars, a strobe, a laser, a smoke machine
        Assert.Equal(10, s.Models.Units.Count);
        Assert.Equal(8, s.Models.Units.Single(u => u.Id == "bar").Idx.Length);
    }

    [Fact]
    public void AFrameLightsTheRig()
    {
        var inp = SceneSamples.Club();
        var frame = SceneSamples.Frame(inp);
        var r = new StageRenderer { Input = () => (inp, frame) };
        var f = new StageFrame();
        r.PrepareFrame(f, StageRenderer.Now(), new(1280, 720));
        Assert.Equal(1280, f.Width);
        Assert.Equal(720, f.Height);
        // 4 heads (one through a prism: 3 rays), 8 cells, 2 pars, the strobe and the smoke plume
        Assert.Equal(3 + 3 + 8 + 2 + 1 + 1, f.Beams.Count);
        Assert.Equal(14, f.Lines.Count);   // 7 laser beams: a glow and a core each
        Assert.NotEmpty(f.Decals);
        Assert.NotEmpty(f.Parts.V);
        Assert.Equal(0, f.Parts.V.Count % 3);
        Assert.True(f.U.Ambient.X + f.U.Ambient.Y + f.U.Ambient.Z > 0);
        Assert.True(f.WallPictureChanged);   // the first show frame draws the wall's picture
        Assert.All(f.Beams, b => Assert.True(float.IsFinite(b.ApexLen.W) && b.ApexLen.W > 0 && b.DirRadius.W > 0));
        Assert.Equal(12, r.ZoneEdges.Count);  // a box zone: 12 edges
        Assert.Equal(36, r.ZoneVertices.Count);
    }

    [Fact]
    public void TheSceneryIsRebuiltOnlyWhenTheKeyChanges()
    {
        var inp = SceneSamples.Club();
        var r = new StageRenderer { Input = () => (inp, null) };
        var f = new StageFrame();
        r.PrepareFrame(f, StageRenderer.Now(), new(800, 600));
        var v = r.SceneryVersion;
        r.PrepareFrame(f, StageRenderer.Now(), new(800, 600));
        Assert.Equal(v, r.SceneryVersion);
        inp = inp with { Key = "other" };
        r.PrepareFrame(f, StageRenderer.Now(), new(800, 600));
        Assert.Equal(v + 1, r.SceneryVersion);
    }

    // MARK: camera controls

    [Fact]
    public void OrbitZoomAndPanMoveTheCamera()
    {
        var r = Renderer(SceneSamples.Club());
        var before = r.Pose;
        r.Orbit(100, 0);
        Assert.Equal(before.Yaw - 0.5f, r.Pose.Yaw, 4);
        r.Orbit(0, 10000);
        Assert.Equal(1.45f, r.Pose.Pitch, 4);   // never past straight down
        r.Zoom(0.5f);
        Assert.Equal(before.Distance * 0.5f, r.Pose.Distance, 3);
        var t = r.Pose.Target;
        r.Pan(100, 0);
        Assert.NotEqual(t, r.Pose.Target);
        Assert.Null(r.Goal);
    }

    [Fact]
    public void FlyingKeepsTheEyeAndWalksWithTheKeys()
    {
        var r = Renderer(SceneSamples.Club());
        var eye = r.Pose.Eye;
        r.Fly = true;
        Assert.Equal(StageRenderer.FlyReach, r.Pose.Distance, 3);
        Assert.True((r.Pose.Eye - eye).Length() < 1e-3f);
        r.KeyDown(StageRenderer.Key.W);
        var f = new StageFrame();
        var now = StageRenderer.Now();
        r.PrepareFrame(f, now + 0.05, new(800, 600));
        r.PrepareFrame(f, now + 0.1, new(800, 600));
        Assert.True((r.Pose.Eye - eye).Length() > 0.05f);
        r.KeyUp(StageRenderer.Key.W);
        Assert.Empty(r.HeldKeys);
        r.Move(up: -100);
        Assert.True(r.Pose.Eye.Z >= 0.149f);   // never below the floor
    }

    [Fact]
    public void ADoubleClickGlidesBackToThePreset()
    {
        var r = Renderer(SceneSamples.Club());
        r.Orbit(300, 50);
        r.SetPreset(r.Preset);
        Assert.NotNull(r.Goal);
        var f = new StageFrame();
        var now = StageRenderer.Now();
        for (var i = 1; i < 200 && r.Goal is not null; i++) r.PrepareFrame(f, now + i * 0.05, new(800, 600));
        Assert.Null(r.Goal);
    }

    // MARK: pacing and the adaptive resolution

    [Fact]
    public void TheFrameRateFollowsWhatChanges()
    {
        Assert.Equal(StageRenderer.ActiveFPS, StageRenderer.FramesPerSecond(10, 10, 10));      // the camera moves
        Assert.Equal(StageRenderer.ShowFPS, StageRenderer.FramesPerSecond(10, 9.99, 5));       // a show runs
        Assert.Equal(StageRenderer.IdleFPS, StageRenderer.FramesPerSecond(10, 8, 5));          // nothing changes
    }

    [Fact]
    public void TheResolutionAdaptsToTheGPU()
    {
        var s = 1.0;
        for (var i = 0; i < 20; i++) s = StageRenderer.NextScale(s, 14);
        Assert.Equal(StageRenderer.MinScale, s);   // never below half
        Assert.Equal(0.5 * 1.1, StageRenderer.NextScale(0.5, 3), 6);
        Assert.Equal(0.7, StageRenderer.NextScale(0.7, 6));   // in between: stays
        for (var i = 0; i < 20; i++) s = StageRenderer.NextScale(s, 2);
        Assert.Equal(1, s);
    }

    [Fact]
    public void ThePacerKeepsTheRate()
    {
        foreach (var (hz, fps) in new[] { (60, 40), (60, 60), (120, 40), (144, 60), (60, 4) })
        {
            var p = new FramePacer();
            var drawn = 0;
            for (var k = 0; k < hz * 10; k++) if (p.ShouldDraw(k / (double)hz, fps, 1.0 / hz)) drawn++;
            Assert.InRange(drawn / 10.0, fps * 0.95, fps * 1.05);
        }
    }

    [Fact]
    public void AutoExposureClosesFastAndOpensSlowly()
    {
        var r = new StageRenderer();
        var e1 = r.UpdateAutoExposure(2, 0.1f);       // bright: close
        Assert.True(r.AutoExposure < 1);
        var closed = r.AutoExposure;
        r.UpdateAutoExposure(0.01f, 0.1f);           // dark again: open, slower
        Assert.True(r.AutoExposure > closed);
        Assert.True(r.AutoExposure - closed < 1 - closed);
        Assert.Equal(1, r.UpdateAutoExposure(float.NaN, 0.1f) > 0 ? 1 : 0);
        Assert.True(e1 > 0);
    }

    [Fact]
    public void InvalidHalfsAreCounted()
    {
        ushort[] h = [0x3C00, 0x7C00, 0x7E00, 0xBC00, 0x8001, 0];   // 1, inf, NaN, -1, tiny negative, 0
        Assert.Equal((2, 1), StageRenderer.CountInvalid(h));
    }

    // MARK: the LED wall

    [Fact]
    public void TheWallDrawsItsScenes()
    {
        var inp = SceneSamples.Club();
        foreach (var scene in new[] { WallScene.Runner, WallScene.Dancer, WallScene.Crowd, WallScene.Pong, WallScene.Words, WallScene.Equalizer, WallScene.Ambient })
        {
            using var w = new WallRenderer { Force = scene };
            WallOutput o = default;
            for (var i = 0; i < 30; i++) o = w.Update(SceneSamples.Frame(inp, 30 + i * 0.05), inp.Hello!, 0.05f);
            Assert.Equal(scene, o.Scene);
            Assert.False(o.Psychedelic);
            Assert.True(o.Level > 0.1f, $"{scene}: {o.Level}");
            var lit = 0;
            var px = w.Pixels;
            for (var k = 0; k < px.Length; k += 4) if (px[k] + px[k + 1] + px[k + 2] > 60) lit++;
            Assert.True(lit > 200, $"{scene}: {lit} lit pixels");
            if (Environment.GetEnvironmentVariable("AMADEUS_WALL_PNGS") is { Length: > 0 } dir)
                File.WriteAllBytes(Path.Combine(dir, $"wall-{scene.RawValue()}.png"), w.Png());
        }
    }

    [Fact]
    public void TheWallFollowsTheDirectorAndCountsIntoTheDrop()
    {
        var inp = SceneSamples.Club();
        using var w = new WallRenderer();
        // the phrase before the drop: 3-2-1 (the words scene draws the countdown)
        var before = new Frame { T = 14, Phrase = 0, Bp = 14 * 128 / 60.0, Fx = [], Bands = [0.5f, 0.5f] };
        WallOutput o = default;
        for (var i = 0; i < 20; i++) o = w.Update(before, inp.Hello!, 0.05f);
        Assert.Equal(WallScene.Words, o.Scene);
        using var psy = new WallRenderer { Force = WallScene.Psychedelic };
        o = psy.Update(SceneSamples.Frame(inp), inp.Hello!, 0.1f);
        Assert.True(o.Psychedelic);
        Assert.Equal(4, o.Palette.Length);
    }

    [Fact]
    public void TheWallsHashIsSwifts()
    {
        Assert.Equal(2654435761L, WallRenderer.Hash(0));
        Assert.Equal((long)((2UL * 2654435761UL + 2 * 40503UL) % 4294967296UL), WallRenderer.Hash(1, 2));
        Assert.Equal((long)(unchecked((ulong)0 * 2654435761UL) % 4294967296UL), WallRenderer.Hash(-1));
    }
}
