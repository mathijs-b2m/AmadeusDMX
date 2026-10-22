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
    public void ARaisedStageIsAPlatformAndTheCameraLooksAtItsFloor()
    {
        // no height: a big rig's 15 cm deck as before, a small one none
        Assert.Equal((-0.5f, 12.5f, -3f, -0.2f, 0.15f), new Scenery([], new Stage(12), false).Deck);
        Assert.Null(new Scenery([], new Stage(4), false).Deck);
        // 1.5 m: a platform that high up to the stage's front edge, its face to the audience; a small stage too
        foreach (var w in new[] { 12.0, 4.0 })
        {
            var s = new Scenery([], new Stage(w) { DeckM = 1.5 }, false);
            var (x0, x1, _, y1, top) = s.Deck!.Value;
            Assert.Equal((-0.5f, (float)w + 0.5f, 0f, 1.5f), (x0, x1, y1, top));
            Assert.Contains(s.Vertices, v => v.Normal == new Vector3(0, 1, 0) && v.Pos.Y == 0 && v.Pos.Z == 1.5f);   // its front face
            Assert.Contains(s.Vertices, v => v.Normal == new Vector3(0, 1, 0) && v.Pos.Y == 0 && v.Pos.Z == 0);
            Assert.True(s.DjHead.Z > 1.5f + 1.5f);   // the DJ stands on it
        }
        // what frames the stage's floor looks that much higher
        Assert.Equal(1.5f, CameraPreset.Plan.Pose(12, 4, -6, 8, deck: 1.5f).Target.Z, 4);
        Assert.Equal(2.5f, CameraPreset.Drone.Pose(12, 4, -6, 8, deck: 1.5f).Target.Z, 4);
        Assert.Equal(CameraPreset.Dj.Pose(12, 4, -6, 8).Eye.Z + 1.5f, CameraPreset.Dj.Pose(12, 4, -6, 8, deck: 1.5f).Eye.Z, 3);
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
        Assert.Equal(GoboBeamInstance.Size, Marshal.SizeOf<GoboBeamInstance>());
        Assert.Equal(GoboDecalInstance.Size, Marshal.SizeOf<GoboDecalInstance>());
        Assert.Equal(WallParams.Size, Marshal.SizeOf<WallParams>());
        Assert.Equal(BlurParams.Size, Marshal.SizeOf<BlurParams>());
        Assert.Equal(SolidVertex.Size, Marshal.SizeOf<SolidVertex>());
        Assert.Equal(SolidVertex.NormalOffset, (int)Marshal.OffsetOf<SolidVertex>(nameof(SolidVertex.Normal)));
        Assert.Equal(SolidVertex.ColorOffset, (int)Marshal.OffsetOf<SolidVertex>(nameof(SolidVertex.Color)));
        Assert.Equal(WallVertex.Size, Marshal.SizeOf<WallVertex>());
        Assert.Equal(WallVertex.UvOffset, (int)Marshal.OffsetOf<WallVertex>(nameof(WallVertex.Uv)));
        Assert.Equal(UnderlayVertex.Size, Marshal.SizeOf<UnderlayVertex>());
        Assert.Equal(UnderlayVertex.UvOffset, (int)Marshal.OffsetOf<UnderlayVertex>(nameof(UnderlayVertex.Uv)));
        Assert.Equal(UnderlayVertex.AlphaOffset, (int)Marshal.OffsetOf<UnderlayVertex>(nameof(UnderlayVertex.Alpha)));
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
        Assert.Equal(GoboBeamInstance.Size, HlslSize(common, "GoboBeamInstance"));
        Assert.Equal(GoboDecalInstance.Size, HlslSize(common, "GoboDecalInstance"));
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
        ("GoboBeam.hlsl", ["gobo_beam_vertex", "gobo_beam_fragment"]),
        ("GoboDecal.hlsl", ["gobo_decal_vertex", "gobo_decal_fragment"]),
        ("Wall.hlsl", ["wall_vertex", "wall_fragment"]),
        ("Underlay.hlsl", ["underlay_vertex", "underlay_fragment"]),
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
    public void WhatStandsAtTheBackIsCutAwayWhileTheCameraIsBehindIt()
    {
        var inp = SceneSamples.Club();
        var s = new Scenery(inp.Fixtures, inp.Stage, inp.Screen, inp.Trusses, inp.Selected);
        var ranges = new List<(int Start, int Count)>();
        int Drawn() => ranges.Sum(r => r.Count);
        bool BackWallDrawn() => ranges.Any(r => Enumerable.Range(r.Start, r.Count)
            .Any(i => s.Vertices[i].Pos.Y == s.Room.Back && s.Vertices[i].Normal == new Vector3(0, 1, 0)));
        // from the audience: everything, the back wall and the LED wall too
        var front = new Vector3(s.Room.Width / 2, 10, 3);
        s.VisibleRanges(front, ranges);
        Assert.Equal(s.Vertices.Count, Drawn());
        Assert.True(BackWallDrawn());
        Assert.False(s.ScreenCut(front) || s.BackCut(front));
        // orbiting round behind the room: no back wall, no LED wall, the rest (the DJ, the rig) still there
        var behind = new Vector3(s.Room.Width / 2, s.Room.Back - 5, 3);
        s.VisibleRanges(behind, ranges);
        Assert.False(BackWallDrawn());
        Assert.True(s.ScreenCut(behind) && s.BackCut(behind));
        Assert.True(Drawn() < s.Vertices.Count && Drawn() > s.Vertices.Count - 200);
        // between the LED wall and the back wall: only the LED wall goes
        var between = new Vector3(s.Room.Width / 2, (s.Room.Back + s.Wall!.Value.Center.Y - 0.35f) / 2, 3);
        s.VisibleRanges(between, ranges);
        Assert.True(BackWallDrawn());
        Assert.True(s.ScreenCut(between) && !s.BackCut(between));
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
        // 4 heads (one through a prism: 3 rays, one with a gobo: a gobo beam), 8 cells, 2 pars, the strobe and the smoke plume
        Assert.Equal(3 + 2 + 8 + 2 + 1 + 1, f.Beams.Count);
        Assert.Single(f.GoboBeams);
        Assert.Single(f.GoboDecals);   // it lands on the floor
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
    public void AGoboHeadThrowsAGoboBeamThatTurns()
    {
        var inp = SceneSamples.Club();
        var frame = SceneSamples.Frame(inp);
        var r = new StageRenderer { Input = () => (inp, frame) };
        var f = new StageFrame();
        var now = StageRenderer.Now();
        r.PrepareFrame(f, now, new(800, 600));
        Assert.Equal(1, r.GoboSlices);
        Assert.Equal(new[] { "sample/dots" }, r.GoboKeys);
        var b = Assert.Single(f.GoboBeams);
        Assert.Equal(new Vector4(0, -1, 0, 0.05f), b.Wheel);   // the picture, the open hole next, not sliding, the lens
        Assert.True(MathF.Abs(new Vector3(b.Axis.X, b.Axis.Y, b.Axis.Z).Length() - 1) < 1e-4f);
        Assert.True(b.DirRadius.W > b.Wheel.W && float.IsFinite(b.ApexLen.W) && b.ApexLen.W > 0);
        var d = Assert.Single(f.GoboDecals);
        Assert.Equal(b.ApexLen, d.ApexLen);
        Assert.Equal(b.Color.W * 0.75f, d.Color.W, 5);
        Assert.Equal((b.DirRadius.W - b.Wheel.W) / b.ApexLen.W, d.DirK.W, 5);
        // half a turn a second on the renderer's clock: a tenth of a second later it has turned 0.1π further
        var before = b.Axis.W;
        r.PrepareFrame(f, now + 0.1, new(800, 600));
        Assert.Equal(before + 0.5f * 2 * MathF.PI * 0.1f, f.GoboBeams[0].Axis.W, 4);
        Assert.Equal(1, r.GoboVersion);   // the same pictures: not uploaded again
        // a gobo the hello has no pictures for draws a plain beam
        var plain = inp with { Hello = new Hello { Fixtures = inp.Hello!.Fixtures, Stage = inp.Stage } };
        var r2 = new StageRenderer { Input = () => (plain, frame) };
        r2.PrepareFrame(f, now, new(800, 600));
        Assert.Empty(f.GoboBeams);
        Assert.Equal(3 + 3 + 8 + 2 + 1 + 1, f.Beams.Count);
    }

    [Fact]
    public void GoboPicturesDecodeToTextureSlices()
    {
        var px = StageRenderer.GoboPixels(SceneSamples.DotsGobo(), StageRenderer.GoboSize)!;
        const int n = StageRenderer.GoboSize;
        Assert.Equal(n * n * 4, px.Length);
        int At(int x, int y, int c) => px[(y * n + x) * 4 + c];
        Assert.True(At(n / 2, n / 2, 0) > 240 && At(n / 2, n / 2, 1) > 240 && At(n / 2, n / 2, 2) > 240);   // the middle hole
        Assert.True(At(2, 2, 0) < 10 && At(n / 2 + 19, n / 2, 0) < 10);   // the metal
        Assert.True(At(n / 2 + 40, n / 2, 0) > 240);   // a hole of the ring
        Assert.Equal(255, At(2, 2, 3));
        Assert.Null(StageRenderer.GoboPixels(new GoboPicture { Key = "x", Img = "not base64!", Style = "dots" }, n));
        Assert.Null(StageRenderer.GoboPixels(new GoboPicture { Key = "x", Img = "aGVsbG8=", Style = "dots" }, n));   // not a picture
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
