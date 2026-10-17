// WinUI ↔ Direct3D: the stage view with mouse/touchpad camera control (mac/.../Render/StageView.swift).
//   drag: orbit · Alt- or Ctrl-drag, right- or middle-drag: pan · wheel / pinch: zoom · two-finger touchpad scroll:
//   orbit (with Ctrl or Alt: zoom) · double-click: back to the preset
//   the show also walks and flies: WASD/arrows move, Q/E down/up, +/− zoom, F flies (drag looks around), Esc lands
//
// A SwapChainPanel with a flip-model swap chain (DXGI composition swap chain, set through ISwapChainPanelNative),
// sized in pixels (the panel's size × CompositionScaleX/Y; the inverse scale goes on the swap chain so the
// compositor maps it back onto the panel). Drawing happens on the UI thread (like MTKView on the main thread): on
// CompositionTarget.Rendering ticks at the rate the renderer asks for (FramePacer), or from a timer while the
// stage is idle (4 fps). Nothing is drawn while the window is minimised or hidden. A lost device (driver update,
// GPU reset) is made again on the spot.
//
// The pages embed it like the Mac's StageView(controller:): `new StageView(controller)`; it is a Grid, so overlays
// (toolbars, cards) can go in its Children on top of the picture. The controller outlives the view (the Mac's
// MainView keeps the show's StageController; the rig editor makes its own); the view makes its renderer when it
// is loaded and lets it go when it is unloaded.
//
//   Show page (ShowView.swift):
//     var stage = new StageView(model.Stage);                  // a StageController the app keeps
//     model.Stage.Input = () => (model.StageInput(), model.Feed.LatestFullFrame);
//     controls: model.Stage.Preset / Fly / WallScene / Haze / Exposure / AutoOrbit (observable: UI.Bind),
//     CameraPresets.AllCases with .RawValue() / .Symbol(), WallScenes.AllCases with .Title() / .Symbol()
//   Rig editor (RigEditorView.swift):
//     var stage = new StageController { WorkLight = 1, Editor = editor, Preset = CameraPreset.Drone };
//     stage.Input = () => (editor.StageInput(), null);       // editor : StageEditing (Pick/Drag/EndDrag/…/Key)
//   Set page (SetView.swift): WorkLight = 1, Input = a preview, Highlight = the selected elements' ids.
using System.Numerics;
using System.Runtime.InteropServices;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using SharpGen.Runtime;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Windows.ApplicationModel.DataTransfer;
using Windows.System;
using Windows.UI.Core;
using DispatcherQueue = Microsoft.UI.Dispatching.DispatcherQueue;
using DispatcherQueueTimer = Microsoft.UI.Dispatching.DispatcherQueueTimer;
using Format = Vortice.DXGI.Format;
using Point = Windows.Foundation.Point;

namespace AmadeusDMX;

public sealed partial class StageView : SwapChainPanel
{
    readonly StageController _controller;
    StageRenderer? _renderer;
    IDXGISwapChain1? _swapChain;
    ID3D11RenderTargetView? _backBuffer;
    Vector2 _pixels = new(1, 1);
    readonly FramePacer _pacer = new();
    DispatcherQueueTimer? _idleTimer;
    bool _onRendering, _visible = true, _loaded, _focused;
    double _lastTick, _refresh = 1.0 / 60;

    // pointer state
    Point _last;
    bool _dragging, _picked;
    uint? _captured;

    public StageView(StageController controller)
    {
        _controller = controller;
        // no Background: a SwapChainPanel takes none (it is hit-tested over its whole area anyway)
        IsTabStop = true;
        AllowDrop = true;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        SizeChanged += (_, _) => Resize();
        CompositionScaleChanged += (_, _) => Resize();
        PointerPressed += OnPointerPressed;
        PointerMoved += OnPointerMoved;
        PointerReleased += OnPointerReleased;
        PointerCaptureLost += (_, _) => EndPointer();
        PointerWheelChanged += OnPointerWheelChanged;
        DoubleTapped += (_, _) => { if (_renderer is { } r && !_picked) r.SetPreset(r.Preset); };   // not on what the editor picked
        KeyDown += OnKeyDown;
        KeyUp += OnKeyUp;
        GotFocus += (_, _) => _focused = true;
        LostFocus += (_, _) => { _focused = false; _renderer?.ReleaseKeys(); };
        DragOver += OnDragOver;
        DragLeave += (_, _) => _controller.Editor?.DropEnded();
        Drop += OnDrop;
    }

    public StageRenderer? Renderer => _renderer;

    internal void FocusForKeys() => Focus(FocusState.Programmatic);

    // MARK: lifetime

    void OnLoaded(object sender, RoutedEventArgs e)
    {
        _loaded = true;
        _controller.View = this;
        if (_renderer is null)
        {
            _renderer = StageRenderer.Make();
            if (_renderer is null) return;   // no Direct3D 11: the stage stays empty (the page still works)
            _renderer.HasKeyFocus = () => _focused;
            _renderer.ModifierKeys = () => (IsDown(VirtualKey.Shift), IsDown(VirtualKey.Menu));
            _renderer.PreferredFramesPerSecondChanged += Schedule;
            _controller.Attach(_renderer);
        }
        if (XamlRoot is { } root)
        {
            root.Changed += OnRootChanged;
            _visible = root.IsHostVisible;
        }
        Resize();
        Schedule();
    }

    void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (IsLoaded) return;   // moved to another parent (WinUI can send the new Loaded before the old Unloaded)
        _loaded = false;
        if (XamlRoot is { } root) root.Changed -= OnRootChanged;
        StopLoop();
        if (_controller.View == this) _controller.View = null;
        if (_renderer is { } r)
        {
            r.PreferredFramesPerSecondChanged -= Schedule;
            _controller.Detach(r);
            ReleaseSwapChain();
            r.Dispose();
            _renderer = null;
        }
    }

    // nobody sees a minimised or hidden window: the lights don't need it drawn
    void OnRootChanged(XamlRoot sender, XamlRootChangedEventArgs args)
    {
        var visible = sender.IsHostVisible;
        if (visible == _visible) return;
        _visible = visible;
        if (visible) _renderer?.Wake();
        Schedule();
    }

    // MARK: the swap chain

    void Resize()
    {
        if (_renderer is null || !_loaded) return;
        var w = Math.Max(1, (int)Math.Round(ActualWidth * CompositionScaleX));
        var h = Math.Max(1, (int)Math.Round(ActualHeight * CompositionScaleY));
        try
        {
            if (_swapChain is null) CreateSwapChain(w, h);
            else if (w != (int)_pixels.X || h != (int)_pixels.Y)
            {
                _backBuffer?.Dispose();
                _backBuffer = null;
                _swapChain.ResizeBuffers(2, (uint)w, (uint)h, Format.Unknown, SwapChainFlags.None).CheckError();
                MakeBackBuffer();
            }
            _pixels = new Vector2(w, h);
            using (var sc2 = _swapChain!.QueryInterfaceOrNull<IDXGISwapChain2>())
                if (sc2 is not null) sc2.MatrixTransform = Matrix3x2.CreateScale(1 / CompositionScaleX, 1 / CompositionScaleY);
            _renderer.DrawableSizeWillChange(_pixels);
            _renderer.Wake();
            Draw();
        }
        catch (SharpGenException ex) { DeviceLost(ex); }
    }

    void CreateSwapChain(int w, int h)
    {
        var device = _renderer!.Device;
        using var dxgiDevice = device.QueryInterface<IDXGIDevice>();
        using var adapter = dxgiDevice.GetAdapter();
        using var factory = adapter.GetParent<IDXGIFactory2>();
        var desc = new SwapChainDescription1
        {
            Width = (uint)w, Height = (uint)h, Format = Format.B8G8R8A8_UNorm, Stereo = false,
            SampleDescription = new SampleDescription(1, 0), BufferUsage = Usage.RenderTargetOutput, BufferCount = 2,
            Scaling = Scaling.Stretch, SwapEffect = SwapEffect.FlipSequential, AlphaMode = AlphaMode.Ignore, Flags = SwapChainFlags.None,
        };
        _swapChain = factory.CreateSwapChainForComposition(device, desc, null);
        SetPanelSwapChain(_swapChain.NativePointer);
        MakeBackBuffer();
    }

    void MakeBackBuffer()
    {
        using var tex = _swapChain!.GetBuffer<ID3D11Texture2D>(0);
        // the buffers are B8G8R8A8_UNORM (flip model has no _SRGB swap chains); the view encodes to sRGB, like the
        // Mac's bgra8Unorm_srgb drawable
        _backBuffer = _renderer!.Device.CreateRenderTargetView(tex, new RenderTargetViewDescription(RenderTargetViewDimension.Texture2D, Format.B8G8R8A8_UNorm_SRgb));
    }

    void ReleaseSwapChain()
    {
        _backBuffer?.Dispose();
        _backBuffer = null;
        if (_swapChain is not null)
        {
            SetPanelSwapChain(IntPtr.Zero);
            _swapChain.Dispose();
            _swapChain = null;
        }
    }

    static readonly Guid ISwapChainPanelNative = new("63aad0b8-7c24-40ff-85a8-640d944cc325");

    /// ISwapChainPanelNative::SetSwapChain (microsoft.ui.xaml.media.dxinterop.h): the one method after IUnknown's three.
    unsafe void SetPanelSwapChain(IntPtr swapChain)
    {
        var unknown = ((WinRT.IWinRTObject)this).NativeObject.ThisPtr;
        var iid = ISwapChainPanelNative;
        Marshal.ThrowExceptionForHR(Marshal.QueryInterface(unknown, in iid, out var native));
        try
        {
            var setSwapChain = (delegate* unmanaged[Stdcall]<IntPtr, IntPtr, int>)(*(void***)native)[3];
            Marshal.ThrowExceptionForHR(setSwapChain(native, swapChain));
        }
        finally { Marshal.Release(native); }
    }

    // MARK: the loop

    /// Run the loop the way the renderer's frame rate asks for: on display refreshes, from a timer while idle, or
    /// not at all while nobody can see the stage.
    void Schedule()
    {
        if (_renderer is null || !_loaded || !_visible) { StopLoop(); return; }
        var fps = _renderer.PreferredFramesPerSecond;
        if (fps > FramePacer.TimerBelow)
        {
            _idleTimer?.Stop();
            if (!_onRendering) { CompositionTarget.Rendering += OnRendering; _onRendering = true; _pacer.Reset(); }
        }
        else
        {
            if (_onRendering) { CompositionTarget.Rendering -= OnRendering; _onRendering = false; }
            _idleTimer ??= MakeIdleTimer();
            _idleTimer.Interval = TimeSpan.FromSeconds(1.0 / Math.Max(1, fps));
            if (!_idleTimer.IsRunning) _idleTimer.Start();
        }
    }

    DispatcherQueueTimer MakeIdleTimer()
    {
        var t = DispatcherQueue.GetForCurrentThread().CreateTimer();
        t.IsRepeating = true;
        t.Tick += (_, _) => Draw();
        return t;
    }

    void StopLoop()
    {
        if (_onRendering) { CompositionTarget.Rendering -= OnRendering; _onRendering = false; }
        _idleTimer?.Stop();
    }

    void OnRendering(object? sender, object e)
    {
        var now = StageRenderer.Now();
        var dt = now - _lastTick;
        _lastTick = now;
        if (dt > 1.0 / 400 && dt < 1.0 / 20) _refresh = _refresh * 0.9 + dt * 0.1;   // the display's refresh, measured
        if (_renderer is { } r && _pacer.ShouldDraw(now, r.PreferredFramesPerSecond, _refresh)) Draw();
    }

    void Draw()
    {
        if (_renderer is not { } r || _swapChain is null || _backBuffer is null || !_visible) return;
        try
        {
            r.Draw(_backBuffer, _pixels);
            var hr = _swapChain.Present(0, PresentFlags.None);
            if (hr.Failure) DeviceLost(new SharpGenException(hr));
        }
        catch (SharpGenException ex) { DeviceLost(ex); }
    }

    static bool IsDeviceLost(Result r) =>
        r.Code is unchecked((int)0x887A0005) or unchecked((int)0x887A0006) or unchecked((int)0x887A0007) or unchecked((int)0x887A0020);

    /// The GPU went away (or the device broke): make everything again, then carry on.
    void DeviceLost(SharpGenException ex)
    {
        if (_renderer is not { } r) return;
        var removed = r.Device?.DeviceRemovedReason ?? Result.Ok;
        if (!IsDeviceLost(ex.ResultCode) && removed.Success)
        {
            Console.Error.WriteLine($"stage: {ex.Message}");
            return;
        }
        ReleaseSwapChain();
        try
        {
            r.ResetDevice();
            _pixels = new(1, 1);
            Resize();
        }
        catch (SharpGenException again) { Console.Error.WriteLine($"stage: the device can't be made again: {again.Message}"); }
    }

    // MARK: pointer: the camera, and the rig editor first

    /// The ray through a point of the view (DIPs, origin top-left), for the editor.
    (Vector3, Vector3)? RayAt(Point p)
    {
        if (_renderer is not { } r) return null;
        var size = new Vector2((float)Math.Max(1, ActualWidth), (float)Math.Max(1, ActualHeight));
        var (o, d) = r.Ray(new Vector2((float)p.X, size.Y - (float)p.Y), size);   // the renderer's rays: origin bottom-left
        return (o, d);
    }

    static bool IsDown(VirtualKey k) => InputKeyboardSource.GetKeyStateForCurrentThread(k).HasFlag(CoreVirtualKeyStates.Down);

    void OnPointerPressed(object sender, PointerRoutedEventArgs e)
    {
        _renderer?.Wake();
        var pt = e.GetCurrentPoint(this);
        _last = pt.Position;
        Focus(FocusState.Pointer);
        if (CapturePointer(e.Pointer)) _captured = e.Pointer.PointerId;
        _picked = false;
        if (pt.Properties.IsLeftButtonPressed && _controller.Editor is { } editor && RayAt(pt.Position) is var (o, d))
        {
            if (editor.Pick(o, d, extend: e.KeyModifiers.HasFlag(VirtualKeyModifiers.Shift))) { _dragging = _picked = true; return; }
            editor.ClickedEmpty();
        }
    }

    void OnPointerMoved(object sender, PointerRoutedEventArgs e)
    {
        var pt = e.GetCurrentPoint(this);
        var props = pt.Properties;
        var p = pt.Position;
        if (_dragging)
        {
            if (RayAt(p) is var (o, d)) _controller.Editor?.Drag(o, d, free: e.KeyModifiers.HasFlag(VirtualKeyModifiers.Menu));
            return;
        }
        // AppKit points go up, WinUI's down: dy is flipped so a drag up turns the camera like on the Mac
        float dx = (float)(p.X - _last.X), dy = -(float)(p.Y - _last.Y);
        _last = p;
        if (props.IsLeftButtonPressed)
        {
            if (e.KeyModifiers.HasFlag(VirtualKeyModifiers.Menu) || e.KeyModifiers.HasFlag(VirtualKeyModifiers.Control)) _renderer?.Pan(dx, dy);
            else _renderer?.Orbit(dx, dy);
        }
        else if (props.IsRightButtonPressed || props.IsMiddleButtonPressed)
        {
            _renderer?.Pan(dx, dy);
        }
        else
        {
            _renderer?.Wake();
            if (_controller.Editor is { } editor && RayAt(p) is var (o, d)) editor.Hover(o, d);
        }
    }

    void OnPointerReleased(object sender, PointerRoutedEventArgs e)
    {
        var props = e.GetCurrentPoint(this).Properties;
        if (props.IsLeftButtonPressed || props.IsRightButtonPressed || props.IsMiddleButtonPressed) return;   // another button still down
        EndPointer();
        if (_captured is { } id && id == e.Pointer.PointerId) ReleasePointerCapture(e.Pointer);
        _captured = null;
    }

    void EndPointer()
    {
        if (_dragging) { _controller.Editor?.EndDrag(); _dragging = false; }
    }

    void OnPointerWheelChanged(object sender, PointerRoutedEventArgs e)
    {
        if (_renderer is not { } r) return;
        e.Handled = true;
        var pt = e.GetCurrentPoint(this);
        var delta = pt.Properties.MouseWheelDelta;
        var horizontal = pt.Properties.IsHorizontalMouseWheel;
        // a precision touchpad scrolls in small steps (and sideways); a mouse wheel in notches of 120
        var precise = pt.PointerDeviceType == PointerDeviceType.Touchpad || horizontal || delta % 120 != 0;
        var mods = e.KeyModifiers;
        if (!precise) { r.Zoom(1 - delta / 120f * 0.04f); return; }
        var points = delta / 120f * 30;   // the touchpad's travel, in the Mac's points
        if (mods.HasFlag(VirtualKeyModifiers.Control) || mods.HasFlag(VirtualKeyModifiers.Menu))
        {
            if (!horizontal) r.Zoom(1 - points * 0.01f);   // Ctrl/Alt + two-finger scroll, and pinch (Ctrl+wheel): zoom
        }
        else if (horizontal) r.Orbit(-points * 1.5f, 0);   // two-finger scroll orbits, like turning a model
        else r.Orbit(0, -points * 1.5f);
    }

    // MARK: keys

    /// The key's position: scan code, 0xE000 for the extended keys (arrows), as StageRenderer.Key lists them.
    static ushort Code(KeyRoutedEventArgs e) => (ushort)(e.KeyStatus.ScanCode | (e.KeyStatus.IsExtendedKey ? 0xE000u : 0));

    void OnKeyDown(object sender, KeyRoutedEventArgs e)
    {
        var key = new StageKey(e.Key, Code(e), IsDown(VirtualKey.Shift), IsDown(VirtualKey.Control), IsDown(VirtualKey.Menu), e.KeyStatus.WasKeyDown);
        if (_controller.Editor is { } editor)
        {
            if (editor.Key(key)) e.Handled = true;
            return;
        }
        if (FlyKey(key)) e.Handled = true;
    }

    void OnKeyUp(object sender, KeyRoutedEventArgs e) => _renderer?.KeyUp(Code(e));

    /// The show's walking and flying keys (not the rig editor's: its keys edit the rig).
    bool FlyKey(StageKey e)
    {
        if (_renderer is not { } r || e.Control) return false;
        if (StageRenderer.Key.Movement.Contains(e.Code))
        {
            r.KeyDown(e.Code);
            return true;
        }
        if (e.Repeat) return false;
        switch (e.Code)
        {
            case StageRenderer.Key.F: _controller.Fly = !_controller.Fly; return true;
            case StageRenderer.Key.Escape when r.Fly: _controller.Fly = false; return true;
            default: return false;
        }
    }

    // MARK: fixtures dragged in from the inspector

    void OnDragOver(object sender, DragEventArgs e)
    {
        if (_controller.Editor is not { } editor || RayAt(e.GetPosition(this)) is not var (o, d)) return;
        e.AcceptedOperation = DataPackageOperation.Move;
        editor.DropHover(o, d);
    }

    async void OnDrop(object sender, DragEventArgs e)
    {
        if (_controller.Editor is not { } editor || !e.DataView.Contains(StandardDataFormats.Text)) return;
        var at = RayAt(e.GetPosition(this));
        var deferral = e.GetDeferral();
        try
        {
            var text = await e.DataView.GetTextAsync();
            if (at is var (o, d)) e.AcceptedOperation = editor.Drop(text, o, d) ? DataPackageOperation.Move : DataPackageOperation.None;
        }
        finally { deferral.Complete(); }
    }
}
