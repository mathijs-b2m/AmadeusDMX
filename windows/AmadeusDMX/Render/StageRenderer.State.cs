// The stage renderer's inputs, camera and frame pacing: everything about a frame that is not Direct3D
// (mac/Sources/AmadeusDMX/Render/StageRenderer.swift, the parts before the encoding). Pure C#: the tests run it on a
// Mac (RenderTests), the Direct3D half (StageRenderer.cs) draws what PrepareFrame worked out.
using System.Diagnostics;
using System.Numerics;
using System.Runtime.InteropServices;
using SkiaSharp;

using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

/// What one frame draws, worked out on the CPU (reused frame to frame: the lists are cleared, not reallocated).
public sealed class StageFrame
{
    public Uniforms U;
    public WallParams Wp;
    public readonly List<BeamInstance> Beams = [];
    public readonly List<SpriteInstance> Sprites = [];
    public readonly List<DecalInstance> Decals = [];
    public readonly List<LineInstance> Lines = [];
    public readonly List<GoboBeamInstance> GoboBeams = [];
    public readonly List<GoboDecalInstance> GoboDecals = [];
    public readonly MeshBuilder Parts = new();
    /// The scenery to draw (start, count): all of it but what the camera is behind.
    public readonly List<(int Start, int Count)> SceneryRanges = [];
    /// The camera is behind the LED wall: it isn't drawn.
    public bool ScreenCut;
    /// The wall's picture changed this frame (upload it to the wall texture).
    public bool WallPictureChanged;
    /// The scene's size in pixels (the window's, times the adaptive render scale).
    public int Width, Height;
    public float Dt;
    public Frame? Show;

    internal void Clear()
    {
        Beams.Clear(); Sprites.Clear(); Decals.Clear(); Lines.Clear(); GoboBeams.Clear(); GoboDecals.Clear(); Parts.Clear();
        WallPictureChanged = false;
        Show = null;
        Wp = default;
    }
}

public sealed partial class StageRenderer
{
    static readonly Stopwatch Clock = Stopwatch.StartNew();
    /// CACurrentMediaTime(): seconds, monotonic.
    public static double Now() => Clock.Elapsed.TotalSeconds;

    // inputs
    public Func<(StageInput?, Frame?)>? Input { get; set; }
    IReadOnlySet<string> _highlight = new HashSet<string>();
    public IReadOnlySet<string> Highlight { get => _highlight; set { _highlight = value; Wake(); } }
    float _haze = 0.75f;
    public float Haze { get => _haze; set { _haze = value; Wake(); } }
    // smoke machines: each one's plume (how much, how long since it last fired) and the haze they built up
    internal readonly Dictionary<string, Vector2> FogPuffs = [];
    internal float RoomFog;
    internal float FogT;
    // gobos: the hello's pictures (texture slices, uploaded by the Direct3D half when GoboVersion changes), and per
    // head how far its gobo has turned (radians) and the direction its picture's x axis lies in (kept while the beam
    // points along the mount, where it is undefined)
    public const int GoboSize = 128, MaxGobos = 256;
    internal IReadOnlyList<string> GoboKeys = [];
    internal IReadOnlyList<GoboPicture>? GoboPictures;
    internal int GoboSlices;
    internal int GoboVersion;
    internal readonly Dictionary<string, float> GoboTurn = [];
    internal readonly Dictionary<string, Vector3> GoboAxis = [];
    internal float GoboT;
    float _exposure = 1.0f;
    public float Exposure { get => _exposure; set { _exposure = value; Wake(); } }

    public const double WallInterval = 0.05;
    WallOutput? _wallOut;
    double _wallAt;
    double? _wallShowT;
    float _wallDt;

    /// Every frame's GPU time (seconds), for the power meter.
    public static Action<double>? OnGPUTime { get; set; }

    // idle: with nothing changing (no show frames, no camera move, no input) the stage draws only a few frames a
    // second, so an open window with no show doesn't keep the GPU (and the compositor) busy
    // a running show changes 40 times a second (the engine's frame rate): drawn at 40; at 60 only while the camera
    // moves (you, an animation, auto-orbit), which is where smoothness shows
    public const int ActiveFPS = 60, ShowFPS = 40, IdleFPS = 4;
    public const double IdleAfter = 1.5, InteractionFor = 2;
    double _lastActive = Now();
    double _lastInteraction;
    double? _lastShowT;

    int _preferredFramesPerSecond = ActiveFPS;
    /// MTKView.preferredFramesPerSecond: the rate the view should draw at now (it listens to the change).
    public int PreferredFramesPerSecond
    {
        get => _preferredFramesPerSecond;
        private set
        {
            if (_preferredFramesPerSecond == value) return;
            _preferredFramesPerSecond = value;
            PreferredFramesPerSecondChanged?.Invoke();
        }
    }
    public event Action? PreferredFramesPerSecondChanged;

    // adaptive resolution: the scene renders at a share of the window's pixels, lowered while the GPU takes too long
    // per frame (beams and bloom are soft: it barely shows) and raised again when there's room
    public const double GpuBudgetMs = 9.0, GpuRoomMs = 4.5, MinScale = 0.5;
    public double RenderScale { get; private set; } = 1;
    double _gpuMs;
    double _scaledAt = Now();

    /// Something changed (input, a setting): draw at full rate again.
    public void Wake()
    {
        _lastActive = Now();
        _lastInteraction = _lastActive;
        PreferredFramesPerSecond = ActiveFPS;
    }

    /// One GPU time measurement (ms), smoothed: steers the adaptive resolution.
    internal void RecordGpuMs(double ms) => _gpuMs = _gpuMs * 0.9 + ms * 0.1;
    internal double GpuMs => _gpuMs;

    /// The next render scale for a smoothed GPU time (pure: the rule, tested).
    public static double NextScale(double scale, double gpuMs)
    {
        if (gpuMs > GpuBudgetMs && scale > MinScale) return Math.Max(MinScale, scale * 0.85);
        if (gpuMs < GpuRoomMs && scale < 1) return Math.Min(1, scale * 1.1);
        return scale;
    }

    void AdaptScale(double now)
    {
        if (now - _scaledAt <= 1) return;
        _scaledAt = now;
        RenderScale = NextScale(RenderScale, _gpuMs);
    }

    /// The frame rate for the moment (pure: the rule, tested).
    public static int FramesPerSecond(double now, double lastActive, double lastInteraction)
    {
        var moving = now - lastInteraction < InteractionFor;
        return now - lastActive > IdleAfter ? IdleFPS : moving ? ActiveFPS : ShowFPS;
    }

    public float AutoExposure { get; private set; } = 1.0f;

    /// The average light of a frame (read back a frame later) steers the exposure, like a camera: closes fast,
    /// opens slowly. Returns the exposure the composite uses.
    internal float UpdateAutoExposure(float lum, float dt)
    {
        lum = MathF.Max(0, lum);
        var target = float.IsFinite(lum) ? MathF.Min(1, MathF.Max(0.3f, 0.22f / MathF.Max(lum, 1e-4f))) : 1;
        AutoExposure += (target - AutoExposure) * MathF.Min(1, dt * (target < AutoExposure ? 4 : 1.2f));
        LastLum = lum; LastExposure = AutoExposure;
        return Exposure * AutoExposure;
    }

    bool _autoOrbit;
    public bool AutoOrbit { get => _autoOrbit; set { _autoOrbit = value; Wake(); } }
    float _workLight;
    /// Light the room so the rig is easy to see (rig pages, no show).
    public float WorkLight { get => _workLight; set { _workLight = value; Wake(); } }
    readonly WallRenderer _wall = new();
    public WallScene WallScene { get => _wall.Force; set { _wall.Force = value; Wake(); } }
    /// What the wall shows right now (for the UI).
    public WallScene WallNow { get; private set; } = WallScene.Off;
    /// The wall's picture (BGRA, WallRenderer.W × H), for the texture upload.
    internal WallRenderer Wall => _wall;

    // camera
    public CameraPose Pose { get; private set; } = new(new(3, -1, 2), 0, 0.15f, 12);
    public CameraPose? Goal { get; set; }
    public CameraPreset Preset { get; private set; } = CameraPreset.FrontOfHouse;
    double _lastTime = Now();
    readonly double _startTime = Now();
    /// The drawable's size in pixels (MTKView.drawableSize).
    public Vector2 ViewSize { get; private set; } = new(1, 1);

    /// The scene, rebuilt when the input's key changes; SceneryVersion counts the rebuilds (the GPU half uploads).
    public Scenery? Scenery { get; private set; }
    internal string SceneryKey = "";
    internal int SceneryVersion;
    internal readonly List<SolidVertex> ZoneVertices = [];
    internal readonly List<LineInstance> ZoneEdges = [];
    internal WallVertex[]? WallVertices;
    /// The drawings under the rig (rig editor): each one's page and its triangles on the floor.
    internal readonly List<(string Key, DrawingPicture Picture, UnderlayVertex[] Vertices)> DrawingQuads = [];

    /// The view has keyboard focus (the window is the key window): held keys whose key-up went elsewhere are dropped.
    public Func<bool>? HasKeyFocus { get; set; }
    /// Shift and Alt held now (NSEvent.modifierFlags).
    public Func<(bool Shift, bool Alt)>? ModifierKeys { get; set; }

    // MARK: camera

    public void SetPreset(CameraPreset p, bool animated = true)
    {
        Wake();
        Preset = p;
        if (Scenery is not { } s) return;
        var target = p.Pose(s.Room.Width, s.Top, s.Room.Back, s.Room.Ceiling, s.Room.Deck);
        if (animated) Goal = target; else { Pose = target; Goal = null; }
    }

    /// The ray through a point of the view (in points, origin bottom-left like AppKit), for picking.
    public (Vector3 Origin, Vector3 Dir) Ray(Vector2 p, Vector2 size)
    {
        var eye = Pose.Eye;
        var f = Vector3.Normalize(Pose.Target - eye);
        var right = Vector3.Normalize(Vector3.Cross(f, new(0, 0, 1)));
        var up = Vector3.Cross(right, f);
        var aspect = MathF.Max(1, size.X) / MathF.Max(1, size.Y);
        var t = MathF.Tan(0.75f / 2);
        float nx = p.X / MathF.Max(1, size.X) * 2 - 1, ny = p.Y / MathF.Max(1, size.Y) * 2 - 1;
        return (eye, Vector3.Normalize(f + right * (nx * t * aspect) + up * (ny * t)));
    }

    public void Orbit(float dx, float dy)
    {
        Wake();
        Goal = null;
        if (Fly) { Look(dx, dy); return; }
        Pose = Pose with { Yaw = Pose.Yaw - dx * 0.005f, Pitch = MathF.Min(1.45f, MathF.Max(-0.05f, Pose.Pitch + dy * 0.004f)) };
    }

    public void Zoom(float factor)
    {
        Wake();
        Goal = null;
        if (Fly) { Move(forward: (1 - factor) * 6); return; }
        Pose = Pose with { Distance = MathF.Min(120, MathF.Max(0.6f, Pose.Distance * factor)) };
    }

    // MARK: flying

    bool _fly;
    /// Fly mode: you are the camera. Drag turns your head, scroll/pinch and the keys move you through the room.
    public bool Fly
    {
        get => _fly;
        set
        {
            if (_fly == value) return;
            _fly = value;
            Wake();
            Goal = null;
            // keep the eye where it is; only the point it turns around changes: right in front of you while flying
            // (looking around turns your head), a stage-sized step ahead again when orbiting
            SetDistance(_fly ? FlyReach : MathF.Max(6, (Pose.Target - Pose.Eye).Length()));
        }
    }
    public const float FlyReach = 1;

    HashSet<ushort> _heldKeys = [];
    /// Keys held down (key codes by position, Key below: other layouts fly the same), read every frame.
    public IReadOnlySet<ushort> HeldKeys => _heldKeys;
    public void KeyDown(ushort code) { if (_heldKeys.Add(code)) Wake(); }
    public void KeyUp(ushort code) => _heldKeys.Remove(code);
    public void ReleaseKeys() => _heldKeys = [];

    void SetDistance(float d)
    {
        var eye = Pose.Eye;
        var dir = Vector3.Normalize(Pose.Target - eye);
        Pose = Pose with { Distance = d, Target = eye + dir * d };
    }

    /// Turn the head: the eye stays put, the view swings. Drag right looks right, drag up looks up.
    void Look(float dx, float dy)
    {
        var eye = Pose.Eye;
        var yaw = Pose.Yaw + dx * 0.004f;
        var pitch = MathF.Min(1.5f, MathF.Max(-1.5f, Pose.Pitch - dy * 0.004f));
        var dir = new Vector3(MathF.Sin(yaw) * MathF.Cos(pitch), MathF.Cos(yaw) * MathF.Cos(pitch), MathF.Sin(pitch));
        Pose = Pose with { Yaw = yaw, Pitch = pitch, Target = eye - dir * Pose.Distance };
    }

    /// Move the eye (and what it looks at) in metres: forward along the floor, right, up.
    public void Move(float forward = 0, float right = 0, float up = 0)
    {
        Wake();
        Goal = null;
        Vector3 fwd = new(-MathF.Sin(Pose.Yaw), -MathF.Cos(Pose.Yaw), 0), r = new(-MathF.Cos(Pose.Yaw), MathF.Sin(Pose.Yaw), 0);
        Pose = Pose with { Target = Pose.Target + fwd * forward + r * right + new Vector3(0, 0, up) };
        const float floor = 0.15f;  // never below the floor
        var z = Pose.Eye.Z;
        if (z < floor) Pose = Pose with { Target = Pose.Target + new Vector3(0, 0, floor - z) };
    }

    /// Key codes: the keyboard's scan codes (set 1, by position like the Mac's ANSI key codes), extended keys with
    /// 0xE000. The view turns a KeyRoutedEventArgs into one (StageView.Code).
    public static class Key
    {
        public const ushort W = 0x11, A = 0x1E, S = 0x1F, D = 0x20, Q = 0x10, E = 0x12, F = 0x21, Escape = 0x01;
        public const ushort Left = 0xE04B, Right = 0xE04D, Down = 0xE050, Up = 0xE048;
        public const ushort Plus = 0x0D, Minus = 0x0C, KeypadPlus = 0x4E, KeypadMinus = 0x4A;
        public static readonly IReadOnlySet<ushort> Movement = new HashSet<ushort> { W, A, S, D, Q, E, Left, Right, Down, Up, Plus, Minus, KeypadPlus, KeypadMinus };
    }

    /// Walk/fly with the held keys: WASD or arrows move, Q/E go down/up, +/− zoom (or move forward/back while
    /// flying). Shift is faster, Alt slower.
    void ApplyHeldKeys(float dt)
    {
        if (_heldKeys.Count == 0) return;
        float Axis(ushort[] pos, ushort[] neg) => (pos.Any(_heldKeys.Contains) ? 1 : 0) - (neg.Any(_heldKeys.Contains) ? 1 : 0);
        var (shift, alt) = ModifierKeys?.Invoke() ?? (false, false);
        var speed = 4 * (shift ? 3 : 1) * (alt ? 0.3f : 1) * dt;
        float fwd = Axis([Key.W, Key.Up], [Key.S, Key.Down]), side = Axis([Key.D, Key.Right], [Key.A, Key.Left]);
        float lift = Axis([Key.E], [Key.Q]), zoomIn = Axis([Key.Plus, Key.KeypadPlus], [Key.Minus, Key.KeypadMinus]);
        if (Fly)
        {
            Move(forward: (fwd + zoomIn) * speed, right: side * speed, up: lift * speed);
        }
        else
        {
            Move(forward: fwd * speed, right: side * speed, up: lift * speed);
            if (zoomIn != 0) Zoom(1 - zoomIn * MathF.Min(0.5f, speed / MathF.Max(1, Pose.Distance) * 1.5f));
        }
    }

    public void Pan(float dx, float dy)
    {
        Wake();
        Goal = null;
        var eye = Pose.Eye;
        var f = Vector3.Normalize(Pose.Target - eye);
        var r = Vector3.Normalize(Vector3.Cross(f, new(0, 0, 1)));
        var u = Vector3.Cross(r, f);
        var k = Pose.Distance * 0.0012f;
        Pose = Pose with { Target = Pose.Target + (-r * dx + u * dy) * k };
    }

    // MARK: the frame, on the CPU

    /// MTKView's drawableSizeWillChange.
    public void DrawableSizeWillChange(Vector2 size) => ViewSize = size;

    /// Everything a frame needs before the GPU draws it: time, pacing, the scenery, the camera, the lights, the
    /// uniforms and the wall's picture. `drawable`: the window's size in pixels.
    public void PrepareFrame(StageFrame out_, double now, Vector2 drawable)
    {
        out_.Clear();
        var dt = (float)Math.Min(0.1, now - _lastTime);
        _lastTime = now;
        out_.Dt = dt;
        var (inp, frame) = Input?.Invoke() ?? (null, null);
        out_.Show = frame;
        if (frame is not null && frame.T != _lastShowT) { _lastShowT = frame.T; _lastActive = now; }  // the show moves
        if (Goal is not null || AutoOrbit || _heldKeys.Count > 0 || (inp is not null && inp.Key != SceneryKey)) { _lastActive = now; _lastInteraction = now; }
        PreferredFramesPerSecond = FramesPerSecond(now, _lastActive, _lastInteraction);
        if (GpuStats && frame is not null && frame.T != LastFrameT) { LastFrameT = frame.T; NewFrames += 1; }
        if (inp is not null && inp.Key != SceneryKey) RebuildScenery(inp);
        if (Goal is { } g)
        {
            Pose = CameraPose.Lerp(Pose, g, 1 - MathF.Exp(-dt * 4));
            if (MathF.Abs(Pose.Distance - g.Distance) < 0.01f && (Pose.Target - g.Target).Length() < 0.01f) { Pose = g; Goal = null; }
        }
        if (_heldKeys.Count > 0 && HasKeyFocus is { } focus && !focus()) _heldKeys = [];  // keyUp went elsewhere
        ApplyHeldKeys(dt);
        if (AutoOrbit && Goal is null && !Fly) Pose = Pose with { Yaw = Pose.Yaw + dt * 0.05f };

        AdaptScale(now);
        out_.Width = Math.Max(1, (int)Math.Round(drawable.X * RenderScale));
        out_.Height = Math.Max(1, (int)Math.Round(drawable.Y * RenderScale));

        // camera
        var eye = Pose.Eye;
        var aspect = MathF.Max(1, drawable.X) / MathF.Max(1, drawable.Y);
        var viewM = Float4x4.LookAt(eye, Pose.Target, new(0, 0, 1));
        var proj = Float4x4.Perspective(0.75f, aspect, 0.1f, 300);
        var f = Vector3.Normalize(Pose.Target - eye);
        var right = Vector3.Normalize(Vector3.Cross(f, new(0, 0, 1)));
        var up = Vector3.Cross(right, f);

        // lights
        var ambient = Vector3.Zero;
        var t = (float)(now - _startTime);
        if (inp?.Hello?.Gobos is { } pics && (GoboPictures is null || !pics.Select(p => p.Key).SequenceEqual(GoboKeys))) SetGobos(pics);
        if (Scenery is { } sc0) { sc0.VisibleRanges(eye, out_.SceneryRanges); out_.ScreenCut = sc0.ScreenCut(eye); }
        else { out_.SceneryRanges.Clear(); out_.ScreenCut = false; }
        if (inp is not null && Scenery is { } s)
            BuildLights(inp, frame, s, eye, t, out_.Beams, out_.Sprites, out_.Decals, out_.Lines, out_.GoboBeams, out_.GoboDecals,
                        ref ambient);

        var u = new Uniforms
        {
            ViewProj = viewM * proj,   // Swift: proj * viewM (see Camera.cs)
            CamPos = new(eye, 1), CamRight = new(right, 0), CamUp = new(up, 0),
            Params = new(t, Haze * (1 + RoomFog), Exposure, 0.9f), Ambient = new(ambient, WorkLight),
        };

        // the wall's picture
        if (inp is { Hello: { } h } && frame is not null && Scenery?.Wall is not null)
        {
            // the wall's picture is drawn on the CPU, once per show frame (the engine's 40 a second: its figures move
            // with the music as fluently as the lights); while the show stands still, WallInterval keeps it alive
            _wallDt += dt;
            if (_wallOut is null || frame.T != _wallShowT || now - _wallAt >= WallInterval)
            {
                var o = _wall.Update(frame, h, _wallDt);
                _wallOut = o;
                _wallAt = now;
                _wallShowT = frame.T;
                _wallDt = 0;
                if (!o.Psychedelic) out_.WallPictureChanged = true;
            }
            var wo = _wallOut.Value;
            WallNow = wo.Scene;
            var p = wo.Palette.Concat(Enumerable.Repeat(wo.Palette.Length > 0 ? wo.Palette[^1] : Vector3.One, Math.Max(0, 4 - wo.Palette.Length))).ToArray();
            out_.Wp = new WallParams
            {
                Info = new(wo.Level, wo.Psychedelic ? 1 : 0, t, 0), Bands = wo.Bands,
                Pal0 = new(p[0], 1), Pal1 = new(p[1], 1), Pal2 = new(p[2], 1), Pal3 = new(p[3], 1),
            };
            // the wall lights the stage around it a little
            ambient += (wo.Psychedelic ? (p[0] + p[1]) * 0.5f : new Vector3(0.4f)) * wo.Level * 0.08f;
            u.Ambient = new(ambient, WorkLight);
        }
        out_.U = u;

        // the fixtures' moving parts and lenses: where the beams point, in the colours they play
        if (Scenery is { } sc && inp is not null) sc.Models.Dynamic(inp.Fixtures, frame, Highlight, out_.Parts);
    }

    // MARK: the gobo pictures (the CPU half of StageRenderer+Setup's buildGobos)

    /// New gobo pictures: slice i is picture i (at most MaxGobos); the Direct3D half builds the texture from them.
    void SetGobos(IReadOnlyList<GoboPicture> pictures)
    {
        GoboKeys = pictures.Select(p => p.Key).ToArray();
        GoboPictures = pictures;
        GoboSlices = pictures.Count == 0 ? 0 : Math.Min(pictures.Count, MaxGobos);
        GoboVersion++;
    }

    /// A gobo picture as `size` × `size` RGBA pixels (rows from the top), drawn over black like the Mac's Core
    /// Graphics context (its alpha ignored, set to 255); null when it isn't a PNG or JPEG in base64.
    internal static byte[]? GoboPixels(GoboPicture p, int size)
    {
        byte[] data;
        try { data = Convert.FromBase64String(p.Img); }
        catch (FormatException) { return null; }
        using var img = SKImage.FromEncodedData(data);
        if (img is null) return null;
        using var bmp = new SKBitmap(new SKImageInfo(size, size, SKColorType.Rgba8888, SKAlphaType.Premul));
        using (var canvas = new SKCanvas(bmp))
        {
            canvas.Clear(SKColors.Transparent);
            canvas.DrawImage(img, new SKRect(0, 0, size, size), new SKSamplingOptions(SKFilterMode.Linear, SKMipmapMode.Linear));
        }
        var px = bmp.Bytes;
        for (var i = 3; i < px.Length; i += 4) px[i] = 255;
        return px;
    }

    // MARK: the scenery and the zones (the CPU half of StageRenderer+Setup)

    void RebuildScenery(StageInput inp)
    {
        var first = Scenery is null;
        var s = new Scenery(inp.Fixtures, inp.Stage, inp.Screen, inp.Trusses, inp.Selected);
        Scenery = s;
        SceneryKey = inp.Key;
        BuildZones(inp);
        DrawingQuads.Clear();
        foreach (var d in inp.Drawings)
            if (DrawingVertices(d, s.Deck) is { Length: > 0 } dv) DrawingQuads.Add((d.Key, d.Picture, dv));
        if (s.Wall is { } w)
        {
            var c = w.Corners;
            // seen from the audience, world +x is on the left: the picture's left edge goes on the +x side
            WallVertices = [new(c.Bl, new(1, 1)), new(c.Br, new(0, 1)), new(c.Tr, new(0, 0)),
                            new(c.Bl, new(1, 1)), new(c.Tr, new(0, 0)), new(c.Tl, new(1, 0))];
        }
        else
        {
            WallVertices = null;
        }
        SceneryVersion++;
        if (first || !inp.KeepCamera) SetPreset(Preset, animated: false);
    }

    /// How far above the floor a drawing lies (m): just clear of it, under everything standing on it.
    public const float DrawingLift = 0.008f;

    /// A drawing's triangles: its plan (the page's crop) on the floor at its corners (rig metres are world x/y, as the
    /// trusses'), and where a big or raised stage's deck is, the part over the deck again on top of it (the floor's
    /// copy is hidden under it). The page lies on the rig turned and scaled, never sheared: its texture coordinates
    /// interpolate exactly.
    public static UnderlayVertex[] DrawingVertices(StageDrawing d, (float X0, float X1, float Y0, float Y1, float Top)? deck)
    {
        if (d.Corners.Count < 4) return [];
        var crop = d.Crop is { Count: 4 } c4 ? c4.Select(v => (float)v).ToArray() : [0, 0, 1, 1];
        Vector2[] uv = [new(crop[0], crop[1]), new(crop[2], crop[1]), new(crop[2], crop[3]), new(crop[0], crop[3])];
        var page = d.Corners.Take(4).Select((c, i) => (P: new Vector2((float)c.X, (float)c.Y), Uv: uv[i])).ToList();
        var out_ = new List<UnderlayVertex>();
        void Fan(List<(Vector2 P, Vector2 Uv)> poly, float z)
        {
            for (var i = 1; i + 1 < poly.Count; i++)
                foreach (var v in new[] { poly[0], poly[i], poly[i + 1] })
                    out_.Add(new UnderlayVertex(new Vector3(v.P, z), v.Uv, d.Opacity));
        }
        Fan(page, DrawingLift);
        if (deck is { } k)
        {
            // Sutherland–Hodgman against the deck's four sides
            var poly = page;
            foreach (var (axis, limit, keepBelow) in new[] { (0, k.X0, false), (0, k.X1, true), (1, k.Y0, false), (1, k.Y1, true) })
                poly = Clip(poly, axis, limit, keepBelow);
            if (poly.Count >= 3) Fan(poly, k.Top + DrawingLift);
        }
        return [.. out_];
    }

    static List<(Vector2 P, Vector2 Uv)> Clip(List<(Vector2 P, Vector2 Uv)> poly, int axis, float limit, bool keepBelow)
    {
        var out_ = new List<(Vector2 P, Vector2 Uv)>();
        bool Inside((Vector2 P, Vector2 Uv) v) => keepBelow ? v.P[axis] <= limit : v.P[axis] >= limit;
        for (var i = 0; i < poly.Count; i++)
        {
            var (a, b) = (poly[i], poly[(i + 1) % poly.Count]);
            if (Inside(a)) out_.Add(a);
            if (Inside(a) != Inside(b))
            {
                var t = (limit - a.P[axis]) / (b.P[axis] - a.P[axis]);
                out_.Add((Vector2.Lerp(a.P, b.P, t), Vector2.Lerp(a.Uv, b.Uv, t)));
            }
        }
        return out_;
    }

    /// Zone faces (translucent) and their edges (thin glowing lines), coloured by kind.
    void BuildZones(StageInput inp)
    {
        var v = ZoneVertices;
        v.Clear();
        ZoneEdges.Clear();
        foreach (var z in inp.Zones)
        {
            var sel = inp.Selected.Contains($"zone:{z.Id}");
            var col = z.Kind == "laser_out" ? new Vector3(1, 0.25f, 0.2f) : z.Kind == "keep_in" ? new Vector3(0.2f, 0.9f, 0.5f) : new Vector3(0.3f, 0.55f, 1);
            var alpha = !z.Enabled ? 0.05f : sel ? 0.3f : 0.16f;
            var c = z.Corners.Select(p => p.ToFloat()).ToArray();
            void Face(int a, int b, int cc, int d)
            {
                var n = Vector3.Normalize(Vector3.Cross(c[b] - c[a], c[d] - c[a]));
                foreach (var i in new[] { a, b, cc, a, cc, d }) v.Add(new SolidVertex(c[i], n, new Vector4(col, alpha)));
            }
            (int, int)[] edges;
            if (z.Shape == "box")
            {
                Face(0, 1, 2, 3); Face(4, 5, 6, 7); Face(0, 1, 5, 4); Face(2, 3, 7, 6); Face(1, 2, 6, 5); Face(0, 3, 7, 4);
                edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)];
            }
            else
            {
                Face(0, 1, 2, 3);
                edges = [(0, 1), (1, 2), (2, 3), (3, 0)];
            }
            var glow = !z.Enabled ? 0.15f : sel ? 2.2f : 0.9f;
            foreach (var (a, b) in edges)
                ZoneEdges.Add(new LineInstance(new(c[a], sel ? 0.03f : 0.018f), new(c[b], 0), new(col, glow)));
        }
    }
}

static class ListSpans
{
    public static Span<T> Span<T>(this List<T> list) => CollectionsMarshal.AsSpan(list);
}
