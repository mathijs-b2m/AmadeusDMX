// The seam between the rig editor and the 3D stage. On the Mac the editor view owns a StageController and a
// StageView (mac/Sources/AmadeusDMX/Render/StageView.swift); the stage view hands clicks, drags, keys, drops and the
// pointer's moves to the editor (StageEditing, here IStageEditing) before it turns the camera, and the renderer
// draws what `input` returns, every frame: the selection, the hover and the drop target lit, the handles of a
// selected truss (its ends; a tower's top), the zones (all from StageInput.Selected / Zones).
//
// IEditorStage is exactly what RigEditorView uses of them. Render.StageView implements it (the lead's merge:
// `partial class StageView : IEditorStage`, or a thin adapter); until then the editor runs on PlaceholderStage, a
// plan view drawn in 2D that behaves like the stage view towards the editor (it is also what the editor falls back
// to when Direct3D isn't there). EditorViewport picks the stage (EditorViewport.MakeStage).
using System.Numerics;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.ApplicationModel.DataTransfer;
using Windows.Foundation;
using Windows.System;
using Windows.UI.Core;

namespace AmadeusDMX;

/// What the rig editor needs from the stage view (Swift: StageController + StageView + StageRenderer).
public interface IEditorStage
{
    /// The view to put in the editor (the SwapChainPanel's host). It takes keyboard focus on a click.
    FrameworkElement View { get; }

    /// What to draw, asked every frame (Swift: `controller.input = { (editor.stageInput(), editor.testFrame()) }`): the
    /// editor's StageInput and, while the light test is on, a still frame of the lit fixtures. A new `Key` means a new scene; `KeepCamera` leaves the camera where it is.
    /// Selected keys: "truss:ID", "fixture:ID", "zone:ID" (drawn selected; a selected horizontal truss shows a
    /// handle at each end, a selected tower one on top: the editor's Pick grabs them within 35 cm), "hover:KEY"
    /// (lit a little: what a click would pick).
    Func<(StageInput? Input, AmadeusKit.Frame? Frame)>? Input { get; set; }

    /// Gets first go at the pointer and keys (Swift: `controller.editor`). With an editor the stage view, like
    /// StageMTKView: on a press calls `Pick(ray, extend: Shift)`; if it grabbed, the moves call `Drag(ray, free:
    /// Alt)` and the release `EndDrag()` instead of turning the camera; if not, a single click calls `ClickedEmpty()`
    /// and the drag orbits (Alt / right button: pan; wheel: zoom; double click: back to the preset). Moves with no
    /// button call `Hover(ray)`. KeyDown goes to `Key(EditorKeys.From(e))` first (handled: true → e.Handled); the
    /// show's walking keys are off while there is an editor. Text dragged in (DataPackage text) goes to
    /// `DropHover` / `Drop(text, ray)` / `DropEnded` (AllowDrop on the view; accept as Move).
    IStageEditing? Editor { get; set; }

    /// The camera preset, by Swift's CameraPreset raw value: "Plan", "Drone", "Front of House", "Side" (the editor's
    /// buttons; also "In the Crowd", "DJ"). Setting it glides the camera there (Swift: `controller.preset`).
    string Preset { get; set; }

    /// 0…1: the room lit for working (the editor sets 1; Swift: `controller.workLight`).
    float WorkLight { get; set; }

    /// The ray through a point of the view (Swift: `renderer.ray(at:in:)`), for the editor's own use. `p` in the
    /// view's coordinates (DIPs, origin top-left; Swift's is bottom-left: flip y), `size` the view's size.
    (Vector3 Origin, Vector3 Dir) Ray(Point p, Size size);

    /// Something the editor shows changed: draw again soon (Swift: `renderer.wake()`; the renderer idles otherwise).
    void Wake();
}

/// WinUI's keys as the editor sees them (Swift: NSEvent's keyCode, modifiers and characters).
public static class EditorKeys
{
    static bool Down(VirtualKey k) => InputKeyboardSource.GetKeyStateForCurrentThread(k).HasFlag(CoreVirtualKeyStates.Down);

    public static bool ShiftDown => Down(VirtualKey.Shift);
    public static bool AltDown => Down(VirtualKey.Menu);
    public static bool ControlDown => Down(VirtualKey.Control);

    public static EditorKey From(KeyRoutedEventArgs e) => From(e.Key);

    public static EditorKey From(VirtualKey key)
    {
        bool shift = ShiftDown, alt = AltDown, control = ControlDown;
        var code = key switch
        {
            VirtualKey.Back => EditorKeyCode.Backspace,
            VirtualKey.Delete => EditorKeyCode.Delete,
            VirtualKey.Left => EditorKeyCode.Left,
            VirtualKey.Right => EditorKeyCode.Right,
            VirtualKey.Up => EditorKeyCode.Up,
            VirtualKey.Down => EditorKeyCode.Down,
            VirtualKey.Escape => EditorKeyCode.Escape,
            _ => EditorKeyCode.Other,
        };
        var chars = key is >= VirtualKey.A and <= VirtualKey.Z ? ((char)('a' + (key - VirtualKey.A))).ToString() : "";
        return new EditorKey(code, chars, shift, alt, control);
    }
}

/// The stage seen from straight above, drawn in 2D: the floor, the trusses and towers, the fixtures and the zones,
/// the selection, the hover, the drop target and the handles, as the renderer shows them. It turns the pointer
/// into rays from above and hands them to the editor exactly as the stage view does, so the whole editor works on
/// it. Wheel: zoom; right drag: pan; double click: fit.
public sealed class PlaceholderStage : IEditorStage
{
    readonly Canvas _canvas = new() { Background = new SolidColorBrush(Windows.UI.Color.FromArgb(255, 0x12, 0x13, 0x16)) };
    readonly ContentControl _host;
    double _scale = 40, _x0 = -2, _y0 = -8;   // pixels per metre; the world point at the view's top-left
    bool _fitted, _dragging, _panning;
    Point _last;
    string _sceneKey = "";

    public PlaceholderStage()
    {
        _host = new ContentControl
        {
            Content = _canvas, IsTabStop = true, UseSystemFocusVisuals = false, AllowDrop = true,
            HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch,
        };
        _canvas.SizeChanged += (_, _) => { _fitted = false; Draw(); };
        _host.PointerPressed += Pressed;
        _host.PointerMoved += Moved;
        _host.PointerReleased += Released;
        _host.PointerCaptureLost += (_, _) => Released(null, null);
        _host.PointerWheelChanged += Wheel;
        _host.DoubleTapped += (_, _) => { _fitted = false; Draw(); };
        _host.KeyDown += (_, e) => { if (Editor?.Key(EditorKeys.From(e)) == true) e.Handled = true; };
        _host.DragOver += (_, e) =>
        {
            if (!e.DataView.Contains(StandardDataFormats.Text) || Editor is null) return;
            e.AcceptedOperation = DataPackageOperation.Move;
            var (o, d) = RayAt(e.GetPosition(_canvas));
            Editor.DropHover(o, d);
        };
        _host.DragLeave += (_, _) => Editor?.DropEnded();
        _host.Drop += async (_, e) =>
        {
            if (Editor is null || !e.DataView.Contains(StandardDataFormats.Text)) return;
            var at = e.GetPosition(_canvas);
            var deferral = e.GetDeferral();
            try
            {
                var text = await e.DataView.GetTextAsync();
                var (o, d) = RayAt(at);
                Editor.Drop(text, o, d);
            }
            finally { deferral.Complete(); }
        };
    }

    public FrameworkElement View => _host;
    public Func<(StageInput? Input, AmadeusKit.Frame? Frame)>? Input { get; set; }
    public IStageEditing? Editor { get; set; }
    public string Preset { get; set; } = "Plan";
    public float WorkLight { get; set; }

    public (Vector3 Origin, Vector3 Dir) Ray(Point p, Size size) =>
        (new Vector3((float)(_x0 + p.X / _scale), (float)(_y0 + p.Y / _scale), 30), new Vector3(0, 0, -1));

    (Vector3, Vector3) RayAt(Point p) => Ray(p, new Size(_canvas.ActualWidth, _canvas.ActualHeight));

    public void Wake() => Draw();

    // MARK: the pointer, as StageMTKView hands it to the editor

    void Pressed(object sender, PointerRoutedEventArgs e)
    {
        _host.Focus(FocusState.Pointer);
        var pt = e.GetCurrentPoint(_canvas);
        _last = pt.Position;
        if (pt.Properties.IsRightButtonPressed || pt.Properties.IsMiddleButtonPressed)
        {
            _panning = _host.CapturePointer(e.Pointer);
            return;
        }
        if (Editor is { } editor)
        {
            var (o, d) = RayAt(pt.Position);
            if (editor.Pick(o, d, EditorKeys.ShiftDown))
            {
                _host.CapturePointer(e.Pointer);
                _dragging = true;
                e.Handled = true;
                return;
            }
            editor.ClickedEmpty();
        }
        _panning = _host.CapturePointer(e.Pointer);  // dragging empty space: the plan pans (the 3D stage orbits)
    }

    void Moved(object sender, PointerRoutedEventArgs e)
    {
        var p = e.GetCurrentPoint(_canvas).Position;
        if (_dragging && Editor is { } editor)
        {
            var (o, d) = RayAt(p);
            editor.Drag(o, d, EditorKeys.AltDown);
        }
        else if (_panning)
        {
            _x0 -= (p.X - _last.X) / _scale;
            _y0 -= (p.Y - _last.Y) / _scale;
            Draw();
        }
        else if (Editor is { } ed)
        {
            var (o, d) = RayAt(p);
            ed.Hover(o, d);
        }
        _last = p;
    }

    void Released(object? sender, PointerRoutedEventArgs? e)
    {
        if (_dragging) { _dragging = false; Editor?.EndDrag(); }
        _panning = false;
        if (e is not null) _host.ReleasePointerCapture(e.Pointer);
    }

    void Wheel(object sender, PointerRoutedEventArgs e)
    {
        var pt = e.GetCurrentPoint(_canvas);
        var k = Math.Pow(1.0015, pt.Properties.MouseWheelDelta);
        var wx = _x0 + pt.Position.X / _scale;
        var wy = _y0 + pt.Position.Y / _scale;
        _scale = Math.Clamp(_scale * k, 5, 400);
        _x0 = wx - pt.Position.X / _scale;
        _y0 = wy - pt.Position.Y / _scale;
        _fitted = true;
        Draw();
        e.Handled = true;
    }

    // MARK: drawing

    static readonly Windows.UI.Color TrussColor = Windows.UI.Color.FromArgb(255, 0x9A, 0xA0, 0xA8);
    static readonly Windows.UI.Color HandleColor = Windows.UI.Color.FromArgb(255, 0xD9, 0xF2, 0xFF);

    Point P(double x, double y) => new((x - _x0) * _scale, (y - _y0) * _scale);
    Point P(Vec3 v) => P(v.X, v.Y);

    void Fit(StageInput inp)
    {
        double W = inp.Stage.WidthM, D = inp.Stage.RoomDepthM;
        var ys = inp.Trusses.Select(t => t.YM).Concat(inp.Fixtures.Select(f => f.Pos.Y)).DefaultIfEmpty(-2).ToList();
        double top = Math.Min(-1, ys.Min()) - 1.5, bottom = Math.Max(2, Math.Min(D, ys.Max() + 6));
        double left = -2, right = W + 2;
        double w = Math.Max(1, _canvas.ActualWidth), h = Math.Max(1, _canvas.ActualHeight);
        _scale = Math.Min(w / (right - left), h / (bottom - top));
        _x0 = (left + right) / 2 - w / 2 / _scale;
        _y0 = (top + bottom) / 2 - h / 2 / _scale;
        _fitted = true;
    }

    void Draw()
    {
        if (Input?.Invoke().Input is not { } inp || _canvas.ActualWidth <= 0) { _canvas.Children.Clear(); return; }
        var scene = inp.Key.Split(':') is { Length: > 1 } k ? k[1] : inp.Key;  // "edit:SET on RIG:VERSION": another rig, fit again
        if (!_fitted || scene != _sceneKey)
        {
            Fit(inp);
            _sceneKey = scene;
        }
        var c = _canvas.Children;
        c.Clear();
        var sel = inp.Selected;
        var accent = Tint.Accent;
        double W = inp.Stage.WidthM;

        // the room's floor (to the audience: +y) and the stage (behind its front edge y = 0)
        AddRect(-1, 0, W + 1, Math.Max(2, inp.Stage.RoomDepthM), Windows.UI.Color.FromArgb(255, 0x1C, 0x1E, 0x22), null);
        AddRect(0, Math.Min(-3, inp.Trusses.Select(t => t.YM).DefaultIfEmpty(-3).Min() - 1), W, 0, Windows.UI.Color.FromArgb(255, 0x26, 0x28, 0x2D), null);
        if (inp.Screen) AddLine(new Vec3(W * 0.2, -0.05, 0), new Vec3(W * 0.8, -0.05, 0), Tint.Purple, 3);

        // zones: translucent, by kind
        foreach (var z in inp.Zones)
        {
            var on = sel.Contains($"zone:{z.Id}");
            var color = z.Kind == "laser_out" ? Tint.Red : z.Kind == "keep_in" ? Tint.Green : Tint.Blue;
            var corners = z.Corners.Take(4).Select(P).ToList();
            var poly = new Polygon
            {
                Fill = Tint.Brush(color, on ? 0.35 : 0.15), Stroke = Tint.Brush(color, on ? 1 : 0.6), StrokeThickness = on ? 2 : 1,
                IsHitTestVisible = false,
            };
            foreach (var p in corners) poly.Points.Add(p);
            c.Add(poly);
        }

        // trusses: lit when selected, hovered or the drop target; handles on a selected one
        foreach (var t in inp.Trusses)
        {
            bool on = sel.Contains($"truss:{t.Id}"), hov = sel.Contains($"hover:truss:{t.Id}");
            var color = on ? accent : hov ? Windows.UI.Color.FromArgb(255, 0xC8, 0xCE, 0xD6) : TrussColor;
            if (t.Vertical)
            {
                AddSquare(new Vec3(t.XM, t.YM, 0), 0.3, color);
                if (on) AddSquare(new Vec3(t.XM, t.YM, 0), 0.26, HandleColor, filled: false);
            }
            else
            {
                foreach (var (a, b) in t.Pieces()) AddLine(a, b, color, Math.Max(3, 0.3 * _scale));
                if (on && !t.IsRing)
                    foreach (var end in new[] { t.Point(-t.LengthM / 2), t.Point(t.LengthM / 2) }) AddSquare(end, 0.26, HandleColor);
            }
        }

        // fixtures: a dot (a bar along its length), its front marked
        foreach (var f in inp.Fixtures)
        {
            var id = f.Fixture ?? f.Id;
            bool on = sel.Contains($"fixture:{id}"), hov = sel.Contains($"hover:fixture:{id}");
            var color = on ? accent : hov ? Tint.White : f.Kind switch
            {
                FixtureKind.Head => Tint.Yellow, FixtureKind.Laser => Tint.Green, FixtureKind.Strobe => Tint.White,
                FixtureKind.Blinder => Tint.Orange, _ => Windows.UI.Color.FromArgb(255, 0xE0, 0x9C, 0x5A),
            };
            var pos = f.Pos;
            var r = Math.Max(4, 0.13 * _scale);
            var e = new Ellipse { Width = 2 * r, Height = 2 * r, Fill = new SolidColorBrush(color), IsHitTestVisible = false };
            if (on || hov) { e.Stroke = new SolidColorBrush(Tint.White); e.StrokeThickness = 1.5; }
            var p = P(pos);
            Canvas.SetLeft(e, p.X - r);
            Canvas.SetTop(e, p.Y - r);
            c.Add(e);
            var rot = f.Rot * Math.PI / 180;  // its front: towards +y turned by rot (a bar runs along x)
            AddLine(pos, pos + new Vec3(-Math.Sin(rot), Math.Cos(rot), 0) * 0.22, color, 2);
        }
    }

    void AddRect(double x0, double y0, double x1, double y1, Windows.UI.Color fill, Windows.UI.Color? stroke)
    {
        Point a = P(Math.Min(x0, x1), Math.Min(y0, y1)), b = P(Math.Max(x0, x1), Math.Max(y0, y1));
        var r = new Rectangle { Width = Math.Max(0, b.X - a.X), Height = Math.Max(0, b.Y - a.Y), Fill = new SolidColorBrush(fill), IsHitTestVisible = false };
        if (stroke is { } s) { r.Stroke = new SolidColorBrush(s); r.StrokeThickness = 1; }
        Canvas.SetLeft(r, a.X);
        Canvas.SetTop(r, a.Y);
        _canvas.Children.Add(r);
    }

    void AddSquare(Vec3 at, double size, Windows.UI.Color color, bool filled = true)
    {
        var px = Math.Max(6, size * _scale);
        var p = P(at);
        var r = new Rectangle { Width = px, Height = px, IsHitTestVisible = false, StrokeThickness = 2 };
        if (filled) r.Fill = new SolidColorBrush(color); else r.Stroke = new SolidColorBrush(color);
        Canvas.SetLeft(r, p.X - px / 2);
        Canvas.SetTop(r, p.Y - px / 2);
        _canvas.Children.Add(r);
    }

    void AddLine(Vec3 a, Vec3 b, Windows.UI.Color color, double width)
    {
        Point pa = P(a), pb = P(b);
        _canvas.Children.Add(new Line
        {
            X1 = pa.X, Y1 = pa.Y, X2 = pb.X, Y2 = pb.Y, Stroke = new SolidColorBrush(color), StrokeThickness = width,
            StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, IsHitTestVisible = false,
        });
    }
}
