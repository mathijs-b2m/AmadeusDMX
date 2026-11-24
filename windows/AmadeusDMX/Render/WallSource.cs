// The LED wall's picture, once for the whole app (mac/Sources/AmadeusDMX/Render/WallSource.swift). The 3D stages show
// it on their wall, and the LED Wall Output puts it on a real one (a monitor: the HDMI into the LED processor).
// WallRenderer draws the picture on the CPU, once per show frame (this half, pure C#: RenderTests). WallSource.Gpu.cs
// puts it on the GPU and draws the psychedelic shader in its place (the wall's level is light: each reader applies
// it), so every one of them shows the same picture, also while no 3D stage is open (Perform mode).
//
// A big output (a 4K projector) gets a big picture: the composed picture is the size of the wall on the monitor, and
// the CPU draws the figures that fine, on a thread of its own (the Painter: a 4K picture takes too long to draw beside
// the UI or the output's frames). When a picture takes longer than the show's frames allow, it draws coarser, and
// finer again when there is room.
//
// Three threads: the UI thread (the stages), the output's render thread, and the painter's. Update and the GPU half's
// Compose take WallSource's lock; Compose is called with the GPU's lock held (SharedGpu.Lock), Update without it, so
// the order is always GPU first, then this one, then the painter's own (short: handing a picture over). The painter
// draws holding none of them, and nobody waits for it: a show frame that comes while it draws waits for the next.
using System.Diagnostics;
using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)
namespace AmadeusDMX;

public sealed partial class WallSource
{
    public static readonly WallSource Shared = new();

    /// The composed picture for a wall of this shape: twice the canvas (1280×720 for 16:9), or the output's wall
    /// (`output`, its pixels) when that is bigger, at most 4096 on its long side (the stage samples it with mipmaps,
    /// the output fits it to the wall).
    public static (int W, int H) PictureSize(double aspect, (int W, int H)? output = null)
    {
        var c = WallRenderer.Canvas(aspect);
        double w = c.W * 2, h = c.H * 2;
        if (output is { } o && o.W > w) { w = o.W; h = w * c.H / c.W; }
        var k = Math.Min(1, 4096 / Math.Max(w, h));
        return (Math.Max(1, (int)Math.Round(w * k, MidpointRounding.AwayFromZero)), Math.Max(1, (int)Math.Round(h * k, MidpointRounding.AwayFromZero)));
    }

    /// A still show keeps the wall alive (its fades, the equaliser).
    public const double UpdateInterval = 0.05;

    readonly Lock _lock = new();
    readonly Painter _painter = new();
    int _paintedSeq;
    WallState? _state;
    WallScene _force = WallScene.Auto;
    double _scale = 1, _drawScale = 1, _scaleCap = double.PositiveInfinity, _adaptedAt = double.NegativeInfinity;
    double _aspect = ScreenShape.DefaultAspect;
    (int W, int H)? _outputPicture;
    double? _lastShowT;
    double _updatedAt;
    double? _lastTick;
    float _pending;
    // the GPU half's work: the state changed (compose again)
    int _stateVersion;

    internal WallSource() { }

    /// What the wall showed last.
    public WallState? State { get { lock (_lock) return _state; } }

    /// The director's choice, or one scene tried out (the stage's LED wall menu). One for the app.
    public WallScene Force
    {
        get { lock (_lock) return _force; }
        set { lock (_lock) _force = value; }
    }

    /// How much finer than its units the CPU should draw (WallOutputLayout.PictureScale: the output's wall).
    public double Scale
    {
        get { lock (_lock) return _scale; }
        set { lock (_lock) _scale = value; }
    }

    /// How fine it does draw: Scale, unless that takes too long (Adapt).
    public double DrawScale { get { lock (_lock) return _drawScale; } }

    /// The output's wall in pixels (the picture fitted into its rectangle), nil while there is no output: it sizes
    /// the composed picture.
    public (int W, int H)? OutputPicture
    {
        get { lock (_lock) return _outputPicture; }
        set { lock (_lock) _outputPicture = value; }
    }

    /// The wall's shape, width over height: the show's rig (its pixels), 16:9 without them.
    public double Aspect { get { lock (_lock) return _aspect; } }

    /// The canvas the picture is drawn on, in units (the wall's shape).
    public (float W, float H) Canvas { get { lock (_lock) return WallRenderer.Canvas(_aspect); } }

    /// Seconds the picture runs ahead of the show's clock (the output's lead).
    public double Lead { get; set; }

    /// Brings the picture up to date for this moment of the show: the next picture goes to the painter (only when
    /// the show moved on, or UpdateInterval passed, and only while it isn't drawing one: every caller in the same
    /// moment shares it), the newest one drawn is taken. Returns what the wall shows, or nil without a show on a rig
    /// with an LED wall (then nothing changes: a stage without a show, the rig editor's, leaves the picture to the
    /// ones that have one), and nil until the first picture of this shape is drawn.
    public WallState? Update(Frame? frame, Hello? hello, double now)
    {
        lock (_lock)
        {
            var dt = (float)Math.Min(0.1, Math.Max(0, now - (_lastTick ?? now)));
            _lastTick = Math.Max(_lastTick ?? now, now);
            if (hello is not { Screen: true } h || frame is not { Lite: false } f) return null;
            if (h.ScreenAspect != _aspect) { _aspect = h.ScreenAspect; _state = null; }   // (the GPU half resizes the picture)
            _pending += dt;
            var lead = Lead;
            if (lead != 0)   // ahead of the lights: the clock and the beat move on, the plan is known in advance
                f = f.At(f.T + lead, f.Bp is { } bp ? bp + lead * h.Bpm / 60 : null);
            Adapt(now);
            if ((_state is null || f.T != _lastShowT || now - _updatedAt >= UpdateInterval)
                && _painter.Submit(new Painter.Job(f, h, _pending, _force, _drawScale, _aspect)))
            {
                _pending = 0;
                _updatedAt = now;
                _lastShowT = f.T;
            }
            // the newest picture drawn (its pixels go onto the GPU in Compose)
            if (_painter.Take(_paintedSeq) is { } p)
            {
                _paintedSeq = p.Seq;
                if (p.Aspect == _aspect)
                {
                    _state = p.State;
                    _stateVersion++;
                }
            }
            return _state;
        }
    }

    /// Draw coarser when a picture takes longer than the show's frames allow (40 a second: 25 ms, kept to 20), finer
    /// again when there is room: looked at once a second, a step at a time.
    void Adapt(double now)
    {
        var ms = _painter.DrawMs;
        if (now - _adaptedAt >= 1)
        {
            _adaptedAt = now;
            if (ms > 20 && _drawScale > 1) _scaleCap = Math.Max(1, Math.Floor(_drawScale * 0.75 * 2) / 2);
            else if (ms > 0 && ms < 9 && _scaleCap < _scale) _scaleCap += 0.5;
        }
        _drawScale = Math.Max(1, Math.Min(_scale, _scaleCap));
    }

    /// Wait for the picture being drawn (development: the render self-test, and the tests). Never from the UI or
    /// the output's thread in the app.
    public void Flush() => _painter.Flush();

    /// Milliseconds a picture takes to draw (smoothed); 0 before the first.
    public double DrawMs => _painter.DrawMs;

    /// Counts the state's changes (the GPU half composes again when it moves on).
    internal int StateVersion { get { lock (_lock) return _stateVersion; } }

    /// Draws the wall's pictures on a thread of its own, one at a time (WallRenderer keeps the last picture: its
    /// trails fade on it). The pixels are copied out into one of two buffers: the newest one is never written while
    /// it is the newest, so a reader copies it under the lock while the next picture is drawn into the other.
    internal sealed class Painter
    {
        public sealed record Job(Frame Frame, Hello Hello, float Dt, WallScene Force, double Scale, double Aspect);
        public sealed record Picture(int Seq, WallState State, double Aspect);

        readonly Lock _lock = new();
        readonly ManualResetEventSlim _idle = new(true);
        readonly AutoResetEvent _work = new(false);
        Thread? _thread;
        Job? _job;                              // the rest under the lock
        bool _busy;
        int _seq, _pixelsSeq;
        Picture? _latest;
        byte[]? _front, _back;                  // _front: the newest pixels (_pixelsSeq), _back: where the next goes
        int _w, _h;
        double _ms;
        WallRenderer? _renderer;                // only on the painter's thread

        /// Milliseconds a picture takes to draw (smoothed); 0 before the first.
        public double DrawMs { get { lock (_lock) return _ms; } }

        /// Starts drawing the next picture; false while the last one is still being drawn.
        public bool Submit(Job job)
        {
            lock (_lock)
            {
                if (_busy) return false;
                _busy = true;
                _job = job;
                _idle.Reset();
                if (_thread is null)
                {
                    _thread = new Thread(Run) { IsBackground = true, Name = "LED wall painter", Priority = ThreadPriority.AboveNormal };
                    _thread.Start();
                }
            }
            _work.Set();
            return true;
        }

        /// The newest picture, if it is newer than `after`.
        public Picture? Take(int after)
        {
            lock (_lock) return _latest is { } p && p.Seq > after ? p : null;
        }

        /// The newest pixels (BGRA, premultiplied, w × 4 bytes a row), if newer than `after`: handed to `use` under the
        /// lock (copy them out there). Returns their number, or `after` when there were none newer.
        public int CopyPixels(int after, Action<byte[], int, int> use)
        {
            lock (_lock)
            {
                if (_front is null || _pixelsSeq <= after) return after;
                use(_front, _w, _h);
                return _pixelsSeq;
            }
        }

        public void Flush() => _idle.Wait();

        void Run()
        {
            while (true)
            {
                _work.WaitOne();
                Job? job;
                lock (_lock) job = _job;
                if (job is null) continue;
                try { Paint(job); }
                catch (Exception e)
                {
                    Console.Error.WriteLine($"LED wall painter: {e.Message}");
                    lock (_lock) { _busy = false; _job = null; }
                }
                lock (_lock) if (!_busy) _idle.Set();
            }
        }

        void Paint(Job job)
        {
            if (_renderer is not { } r || r.Scale != (float)job.Scale || r.Aspect != job.Aspect)
            {
                _renderer?.Dispose();
                _renderer = r = new WallRenderer((float)job.Scale, job.Aspect);
            }
            r.Force = job.Force;
            var t0 = Stopwatch.GetTimestamp();
            var s = r.Update(job.Frame, job.Hello, job.Dt);
            int w = r.PixelWidth, h = r.PixelHeight;
            byte[]? back = null;
            if (!s.Psychedelic)
            {
                lock (_lock) back = _back;
                if (back is null || back.Length != w * h * 4) back = new byte[w * h * 4];
                var px = r.Pixels;
                var row = r.RowBytes;
                if (row == w * 4) px[..back.Length].CopyTo(back);
                else for (var y = 0; y < h; y++) px.Slice(y * row, w * 4).CopyTo(back.AsSpan(y * w * 4));
            }
            var took = Stopwatch.GetElapsedTime(t0).TotalMilliseconds;
            lock (_lock)
            {
                _seq++;
                _latest = new Picture(_seq, s, job.Aspect);
                if (back is not null)
                {
                    _back = _front;   // the old newest is written next time
                    _front = back;
                    (_w, _h, _pixelsSeq) = (w, h, _seq);
                }
                _ms = _ms == 0 ? took : _ms * 0.8 + took * 0.2;
                _busy = false;
                _job = null;
            }
        }
    }
}
