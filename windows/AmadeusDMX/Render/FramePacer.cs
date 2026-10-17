// When to draw: MTKView's preferredFramesPerSecond on Windows. The view gets a tick per display refresh
// (CompositionTarget.Rendering) and draws on the ticks that keep the asked rate: 40 a second on a 60 Hz display is
// two frames out of three, on 120 Hz one out of three. Below `TimerBelow` fps (idle) the view stops listening to
// the display and uses a timer instead, so an idle stage costs no per-refresh work at all.
namespace AmadeusDMX;

public sealed class FramePacer
{
    /// Rates at or below this run from a timer, not from the display's refresh.
    public const int TimerBelow = 10;

    double _due = double.NegativeInfinity;

    /// A tick at `now` (seconds), the display refreshing every `refresh` seconds: draw now? Keeps the long-run
    /// rate at `fps` (never above the display's), drawing on the refresh nearest to when a frame is due.
    public bool ShouldDraw(double now, int fps, double refresh = 1.0 / 60)
    {
        var interval = 1.0 / Math.Max(1, fps);
        if (now < _due - refresh / 2) return false;
        // due again one interval after the frame was due (not after now), so the rate holds; fallen behind (a
        // stall, or the rate went up): start counting from now
        _due = now - _due > interval ? now + interval : _due + interval;
        return true;
    }

    /// Draw on the next tick whatever the rate (a wake-up).
    public void Reset() => _due = double.NegativeInfinity;
}
