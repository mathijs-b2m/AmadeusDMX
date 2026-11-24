// The LED wall's picture, once for the whole app (mac/Sources/AmadeusDMX/Render/WallSource.swift). The 3D stages show
// it on their wall, and the LED Wall Output puts it on a real one (a monitor: the HDMI into the LED processor).
// WallRenderer draws the picture on the CPU, once per show frame (this half, pure C#: RenderTests). WallSource.Gpu.cs
// puts it on the GPU, draws the psychedelic shader in its place and applies the wall's level, so every one of them
// shows the same picture, also while no 3D stage is open (Perform mode).
//
// Two threads use it: the UI thread (the stages) and the output's own render thread. Update and the GPU half's
// Compose take the same lock; Compose is called with the GPU's lock held (SharedGpu.Lock), Update without it, so the
// order is always GPU first, then this one.
using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

public sealed partial class WallSource
{
    public static readonly WallSource Shared = new();

    /// The composed picture for a wall of this shape: twice the canvas (1280×720 for 16:9), at most 2560 on its long
    /// side (the stage samples it with mipmaps, the output fits it to the wall).
    public static (int W, int H) PictureSize(double aspect)
    {
        var c = WallRenderer.Canvas(aspect);
        var k = Math.Min(2, 2560 / Math.Max(c.W, c.H));
        return ((int)MathF.Round(c.W * k, MidpointRounding.AwayFromZero), (int)MathF.Round(c.H * k, MidpointRounding.AwayFromZero));
    }

    /// A still show keeps the wall alive (its fades, the equaliser).
    public const double UpdateInterval = 0.05;

    readonly Lock _lock = new();
    WallRenderer _renderer = new();
    WallState? _state;
    WallScene _force = WallScene.Auto;
    double _scale = 1;
    double _aspect = ScreenShape.DefaultAspect;
    double? _lastShowT;
    double _updatedAt;
    double? _lastTick;
    float _pending;
    // the GPU half's work: the CPU picture changed (upload it), the state changed (compose again)
    int _pictureVersion, _stateVersion;

    internal WallSource() { }

    /// What the wall showed last.
    public WallState? State { get { lock (_lock) return _state; } }

    /// The director's choice, or one scene tried out (the stage's LED wall menu). One for the app.
    public WallScene Force
    {
        get { lock (_lock) return _force; }
        set { lock (_lock) { _force = value; _renderer.Force = value; } }
    }

    /// How much finer than its units the CPU draws (WallOutputLayout.PictureScale: the output's wall).
    public double Scale
    {
        get { lock (_lock) return _scale; }
        set
        {
            lock (_lock)
            {
                if (value == _scale) return;
                _scale = value;
                Rebuild();
            }
        }
    }

    /// The wall's shape, width over height: the show's rig (its pixels), 16:9 without them.
    public double Aspect { get { lock (_lock) return _aspect; } }

    /// The canvas the picture is drawn on, in units (the wall's shape).
    public (float W, float H) Canvas { get { lock (_lock) return WallRenderer.Canvas(_aspect); } }

    void Rebuild()
    {
        _renderer.Dispose();
        _renderer = new WallRenderer((float)_scale, _aspect) { Force = _force };
        _state = null;
        _pictureVersion++;
    }

    /// Seconds the picture runs ahead of the show's clock (the output's lead).
    public double Lead { get; set; }

    /// Brings the picture up to date for this moment of the show (the CPU half: only when the show moved on, or
    /// UpdateInterval passed: every caller in the same moment shares it). Returns what the wall shows, or nil
    /// without a show on a rig with an LED wall; then nothing changes (a stage without a show, the rig editor's,
    /// leaves the picture to the ones that have one).
    public WallState? Update(Frame? frame, Hello? hello, double now)
    {
        lock (_lock)
        {
            var dt = (float)Math.Min(0.1, Math.Max(0, now - (_lastTick ?? now)));
            _lastTick = Math.Max(_lastTick ?? now, now);
            if (hello is not { Screen: true } h || frame is not { Lite: false } f) return null;
            if (h.ScreenAspect != _aspect) { _aspect = h.ScreenAspect; Rebuild(); }   // (the GPU half resizes the picture)
            _pending += dt;
            var lead = Lead;
            if (lead != 0)   // ahead of the lights: the clock and the beat move on, the plan is known in advance
                f = f.At(f.T + lead, f.Bp is { } bp ? bp + lead * h.Bpm / 60 : null);
            if (_state is null || f.T != _lastShowT || now - _updatedAt >= UpdateInterval)
            {
                var s = _renderer.Update(f, h, _pending);
                _pending = 0;
                _updatedAt = now;
                _lastShowT = f.T;
                _state = s;
                if (!s.Psychedelic) _pictureVersion++;
                _stateVersion++;
            }
            return _state;
        }
    }

    /// Counts the CPU picture's changes, and the state's (the GPU half uploads and composes when they move on).
    internal int PictureVersion { get { lock (_lock) return _pictureVersion; } }
    internal int StateVersion { get { lock (_lock) return _stateVersion; } }
}
