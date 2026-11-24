// The LED Wall Output: the wall's picture (WallSource) on a real LED wall (mac/Sources/AmadeusDMX/Render/
// WallOutputController.swift). Like Resolume's Advanced Output or a media server's: a borderless window filling a
// monitor (the HDMI into the LED processor), the picture in the wall's rectangle of that monitor, pixel for pixel,
// black around it. Or in a window, to try it without a second monitor or to capture it (OBS).
//
// It draws on a thread of its own, paced by its own swap chain (flip model, vsync, a frame-latency waitable object:
// one frame per refresh of the monitor it is on), so it plays while no 3D stage is open and whatever the main window's
// monitor and the UI thread are doing; the Mac draws it on that display's own display link. (FramePacer and
// CompositionTarget.Rendering follow the app's window and the UI thread: the wrong clock for another monitor.) It
// shares the app's device with the stages (SharedGpu) and holds its lock while it draws.
//
// It never covers the monitor the app is on (QLC+ users lose their controls that way), goes black when the show
// stops (never a frozen picture), keeps that monitor awake, and comes back by itself when the monitor is plugged in
// again. The process is per-monitor DPI aware: the window and its swap chain are in the monitor's own pixels, so the
// scaling in Settings › Display never scales the wall.
using System.Runtime.InteropServices;
using Microsoft.UI.Dispatching;
using SharpGen.Runtime;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Vortice.Mathematics;
using static AmadeusDMX.WallOutputNative;
using Format = Vortice.DXGI.Format;
using Frame = AmadeusKit.Frame;   // not WinUI's Frame (the app's global usings)

namespace AmadeusDMX;

/// A monitor the output can go to.
internal sealed record OutputScreen(string Id, string Name, (int W, int H) Pixels, double Refresh, (int W, int H)? Native, bool HoldsApp)
{
    /// The monitor runs a mode other than its own (the wall's pixels may not land one to one).
    public bool NotNative => Native is { } n && n != Pixels && n != (Pixels.H, Pixels.W);

    public string Label => $"{Name} · {Pixels.W} × {Pixels.H}" + (Refresh > 0 ? $" · {(int)Math.Round(Refresh)} Hz" : "");
}

/// What the output's thread draws with: the settings and the monitor, as they are now (replaced, never changed).
internal sealed record OutputPlan((int W, int H)? Mode, PixelRect? Rect, float Brightness, bool TestPattern, int PanelPx)
{
    /// The wall's rectangle in the drawable's pixels, and where the picture (of the rig's shape, `aspect`) goes inside it.
    public (PixelRect Wall, PixelRect Picture) Layout((int W, int H) d, double aspect)
    {
        if (Mode is not { } mode)
        {
            var all = new PixelRect(0, 0, d.W, d.H);
            return (all, WallOutputLayout.Fit(all, aspect));
        }
        var wall = WallOutputLayout.Scaled(WallOutputLayout.WallRect(Rect, mode.W, mode.H), mode, d);
        return (wall, WallOutputLayout.Fit(wall, aspect));
    }

    /// How fine the picture is drawn for this wall (its rectangle, the rig's shape).
    public double PictureScale((int W, int H) d, double aspect, (float W, float H) canvas) =>
        WallOutputLayout.PictureScale(WallOutputLayout.Fit(ModeWall(d), aspect), (canvas.W, canvas.H));

    /// The wall's rectangle in the monitor's own pixels (what the processor is told), for the test card's labels.
    public PixelRect ModeWall((int W, int H) d)
    {
        var px = Mode ?? d;
        return WallOutputLayout.WallRect(Rect, px.W, px.H);
    }
}

public sealed class WallOutputController : Observable
{
    WallOutputSettings _settings = WallOutputSettings.Load();
    public WallOutputSettings Settings
    {
        get => _settings;
        set
        {
            if (value == _settings) return;
            var old = _settings;
            _settings = value;
            Changed();
            value.Save();
            Apply();
            if (value.On != old.On) OnToggle?.Invoke(value.On);
        }
    }

    IReadOnlyList<OutputScreen> _screens = [];
    internal IReadOnlyList<OutputScreen> Screens { get => _screens; private set => Set(ref _screens, value); }
    string? _problem, _playingOn;
    (int W, int H)? _outputPixels;
    /// What the output is doing, for the window: nil while all is well.
    public string? Problem { get => _problem; private set => Set(ref _problem, value); }
    /// Where it plays right now ("Display 2 · 1920 × 1080"), nil while it doesn't.
    public string? PlayingOn { get => _playingOn; private set => Set(ref _playingOn, value); }
    /// The pixels of what it plays on right now (the monitor's, or the window's).
    public (int W, int H)? OutputPixels { get => _outputPixels; private set => Set(ref _outputPixels, value); }

    /// The show: its hello, its newest frame, and whether frames still arrive. Called on the output's thread: it
    /// must only read what is safe to read from there (LiveFeed's LatestFrame is).
    public Func<(Hello?, Frame?, bool)> Source { get; set; } = () => (null, null, false);
    /// The output was switched on or off (the feed must carry full frames while it is on).
    public Action<bool>? OnToggle { get; set; }

    internal volatile OutputPlan Plan = new(null, null, 1, false, 128);
    readonly Dictionary<string, MonitorInfo> _monitors = [];
    WallOutputView? _view;
    Window? _appWindow;
    IntPtr _appMonitor, _listener;
    DispatcherQueueTimer? _settle;

    /// After launch, with the app's main window (which monitor it is on decides what the output may cover).
    public void Attach(Window appWindow)
    {
        _appWindow = appWindow;
        // the app's window moved to another monitor: what the output may cover changed
        appWindow.AppWindow.Changed += (_, e) =>
        {
            if (!e.DidPositionChange && !e.DidSizeChange) return;
            if (MonitorFromWindow(AppHwnd, MONITOR_DEFAULTTONEAREST) == _appMonitor) return;
            RefreshScreens();
            Apply();
        };
        appWindow.Closed += (_, _) => { Close(); if (_listener != IntPtr.Zero) DestroyWindow(_listener); _listener = IntPtr.Zero; };
        // monitors plugged in, out, or set to another mode (WM_DISPLAYCHANGE reaches every top-level window, a hidden
        // one too); the new layout settles a moment later
        _listener = CreateWindow("AmadeusDMXDisplayWatcher", (h, m, w, l) =>
        {
            if (m is WM_DISPLAYCHANGE or WM_DPICHANGED || (m == WM_SETTINGCHANGE && w == (IntPtr)0x2F /* SPI_SETWORKAREA */)) Settle();
            return DefWindowProcW(h, m, w, l);
        }, "", WS_POPUP, 0, 0, 0, 0, 0);
        UI.Later(() => { RefreshScreens(); Apply(); });
    }

    void Settle()
    {
        if (_settle is null)
        {
            _settle = DispatcherQueue.GetForCurrentThread().CreateTimer();
            _settle.IsRepeating = false;
            _settle.Interval = TimeSpan.FromMilliseconds(400);
            _settle.Tick += (_, _) => { RefreshScreens(); Apply(); };
        }
        _settle.Stop();
        _settle.Start();
    }

    IntPtr AppHwnd => _appWindow is null ? IntPtr.Zero : WinRT.Interop.WindowNative.GetWindowHandle(_appWindow);

    // MARK: monitors

    public void RefreshScreens()
    {
        _appMonitor = AppHwnd == IntPtr.Zero ? IntPtr.Zero : MonitorFromWindow(AppHwnd, MONITOR_DEFAULTTONEAREST);
        List<MonitorInfo> monitors;
        try { monitors = WallOutputNative.Monitors(); }
        catch (Exception e) when (e is DllNotFoundException or EntryPointNotFoundException) { monitors = []; }
        _monitors.Clear();
        foreach (var m in monitors) _monitors.TryAdd(m.Id, m);
        var list = _monitors.Values.Select(m => new OutputScreen(m.Id, m.Name, (m.PixelW, m.PixelH), m.Refresh, m.Native, m.Handle == _appMonitor)).ToList();
        if (!list.SequenceEqual(Screens)) Screens = list;
    }

    internal OutputScreen? ChosenScreen => Screens.FirstOrDefault(s => s.Id == Settings.Display);

    /// The monitor to offer first: one the app is not on.
    internal OutputScreen? SuggestedScreen => Screens.FirstOrDefault(s => !s.HoldsApp);

    // MARK: on and off

    /// Opens, moves or closes the output for the settings and the monitors connected now.
    bool _applying;

    public void Apply()
    {
        if (_applying) return;   // (opening a window can call back in here: on the Mac that looped until a crash)
        _applying = true;
        try { ApplyNow(); } finally { _applying = false; }
    }

    void ApplyNow()
    {
        WallSource.Shared.Lead = Settings.LeadMs / 1000;
        if (!Settings.On) { Close(); Problem = null; WallSource.Shared.Scale = 1; return; }
        switch (Settings.Target)
        {
            case WallOutputSettings.TargetKind.Window:
                Problem = null;
                Open(null);
                break;
            default:
                if (Settings.Display is not { } id) { Close(); Problem = L("Choose the display that goes to the LED wall."); return; }
                if (ChosenScreen is not { } info || !_monitors.TryGetValue(id, out var monitor))
                {
                    Close();
                    Problem = L("{0} isn't connected. The output starts by itself when it is.", Settings.DisplayName ?? L("The display"));
                    return;
                }
                if (info.HoldsApp)
                {
                    Close();
                    Problem = L("Amadeus DMX is on {0}. Move the app's window to another display, or choose another display: the output would cover it.", info.Name);
                    return;
                }
                Problem = info.NotNative && info.Native is { } n
                    ? L("{0} runs at {1} × {2}, not its own {3} × {4}: the wall's pixels may not land one to one. Choose its recommended resolution in Settings › System › Display.",
                        info.Name, info.Pixels.W, info.Pixels.H, n.W, n.H)
                    : null;
                Open(monitor);
                break;
        }
        UpdatePixels();
    }

    void Open(MonitorInfo? monitor)
    {
        // already there (the same monitor, or still the window): only follow a monitor's new place or size
        if (_view is { } v && v.MonitorId == monitor?.Id)
        {
            if (monitor is not null) v.Place(monitor.Bounds);
            PlayingOn = monitor is null ? L("a window") : ChosenScreen?.Label ?? monitor.Name;
            return;
        }
        Close();
        try
        {
            _view = new WallOutputView(this, monitor);
        }
        catch (Exception e) when (e is SharpGenException or InvalidOperationException or COMException)
        {
            Console.Error.WriteLine($"LED wall output: {e.Message}");
            Problem = L("The LED wall output can't start: {0}", e.Message);
            return;
        }
        PlayingOn = monitor is null ? L("a window") : ChosenScreen?.Label ?? monitor.Name;
    }

    public void Close()
    {
        var v = _view;
        _view = null;
        v?.Dispose();
        PlayingOn = null;
        OutputPixels = null;
    }

    /// The window's own close button (In a Window): the output is off.
    internal void WindowClosed()
    {
        if (_view is null) return;
        Settings = Settings with { On = false };
    }

    /// The pixels it plays on, what its thread draws with, and how fine the picture is drawn for it.
    internal void UpdatePixels()
    {
        var display = Settings.Target == WallOutputSettings.TargetKind.Display;
        (int W, int H)? px = _view is null ? null : display ? ChosenScreen?.Pixels ?? _view.ClientPixels : _view.ClientPixels;
        if (OutputPixels != px) OutputPixels = px;
        var s = Settings;
        Plan = new OutputPlan(display ? ChosenScreen?.Pixels : null, display ? s.Rect : null, (float)s.Brightness, s.TestPattern, s.PanelPx);
        if (px is { } p) UpdateScale(p);
    }

    /// Draw the picture as fine as the wall needs (its rectangle, the rig's shape). `pixels`: what it plays on.
    internal void UpdateScale((int W, int H) pixels)
    {
        var src = WallSource.Shared;
        src.Scale = Plan.PictureScale(pixels, src.Aspect, src.Canvas);
    }

    /// The window target's first size: 960 × 540 at the main window's scaling, where it was last time.
    internal RECT WindowFrame()
    {
        if (Defaults.Standard.String("LEDWallOutputWindow")?.Split(',') is { Length: 4 } f
            && f.Select(v => int.TryParse(v, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var n) ? n : (int?)null).ToArray() is [{ } x, { } y, { } w, { } h]
            && w >= 160 && h >= 90 && _monitors.Values.Any(m => x + w > m.Bounds.Left && x < m.Bounds.Right && y + h > m.Bounds.Top && y < m.Bounds.Bottom))
            return new RECT { Left = x, Top = y, Right = x + w, Bottom = y + h };
        var dpi = AppHwnd == IntPtr.Zero ? 96u : Math.Max(96u, GetDpiForWindow(AppHwnd));
        var r = new RECT { Left = 0, Top = 0, Right = (int)(960 * dpi / 96), Bottom = (int)(540 * dpi / 96) };
        AdjustWindowRectExForDpi(ref r, WS_OVERLAPPEDWINDOW, false, WS_EX_APPWINDOW, dpi);
        var at = _monitors.Values.FirstOrDefault(m => m.Handle == _appMonitor)?.Bounds ?? new RECT { Right = 1920, Bottom = 1080 };
        int ox = at.Left + (at.Width - r.Width) / 2, oy = at.Top + (at.Height - r.Height) / 2;
        return new RECT { Left = ox, Top = oy, Right = ox + r.Width, Bottom = oy + r.Height };
    }

    internal static void SaveWindowFrame(RECT r) =>
        Defaults.Standard.Set("LEDWallOutputWindow", string.Create(System.Globalization.CultureInfo.InvariantCulture, $"{r.Left},{r.Top},{r.Width},{r.Height}"));
}

/// Draws one picture of the output: black, and in it the wall's picture (fitted into the wall's rectangle) or the
/// test card (the whole rectangle). The output's view and the render self-test (development) draw with it. Use it
/// with the device's lock held.
public sealed class WallOutputDrawer : IDisposable
{
    int _generation = -1;
    ID3D11VertexShader? _vs;
    ID3D11PixelShader? _ps;
    ID3D11Buffer? _params;
    ID3D11SamplerState? _sampler;
    ID3D11RasterizerState? _noCull;   // the full-screen triangle is counter-clockwise: the default state culls it

    void Build(SharedGpu gpu)
    {
        Dispose();
        _generation = gpu.Generation;
        var d = gpu.Device;
        _vs = d.CreateVertexShader(ShaderLibrary.Bytecode("WallSource.hlsl", "wall_fs_vertex", "vs_4_0"));
        _ps = d.CreatePixelShader(ShaderLibrary.Bytecode("WallSource.hlsl", "wall_output", "ps_4_0"));
        _params = d.CreateBuffer(new BufferDescription(16, BindFlags.ConstantBuffer));
        _sampler = d.CreateSamplerState(new SamplerDescription
        {
            Filter = Filter.MinMagMipLinear,
            AddressU = TextureAddressMode.Clamp, AddressV = TextureAddressMode.Clamp, AddressW = TextureAddressMode.Clamp,
            ComparisonFunc = ComparisonFunction.Never, MinLOD = 0, MaxLOD = 0,   // the picture's full size (Metal: no mip filter)
        });
        _noCull = d.CreateRasterizerState(new RasterizerDescription(CullMode.None, FillMode.Solid));
    }

    /// `level`: the share of the wall's light that goes out (its level × the brightness ceiling × the fade; the card's:
    /// the ceiling); `card`: the test card, else the show's `picture`.
    public void Encode(SharedGpu gpu, ID3D11RenderTargetView target, PixelRect wall, PixelRect picture, float level,
                       ID3D11ShaderResourceView? card, ID3D11ShaderResourceView? show, float time)
    {
        if (_generation != gpu.Generation) Build(gpu);
        var ctx = gpu.Context;
        ctx.OMSetRenderTargets(target, null);
        ctx.ClearRenderTargetView(target, new Color4(0, 0, 0, 1));
        var texture = card ?? (level > 0 ? show : null);
        if (texture is null || _ps is null) return;
        var r = card is not null ? wall : picture;
        var p = new System.Numerics.Vector4(level, time, card is not null ? 1 : 0, 0);
        ctx.UpdateSubresource(in p, _params!);
        ctx.RSSetViewport(new Viewport(r.X, r.Y, r.W, r.H));
        ctx.RSSetState(_noCull);
        ctx.OMSetBlendState(null);
        ctx.OMSetDepthStencilState(null);
        ctx.IASetPrimitiveTopology(PrimitiveTopology.TriangleList);
        ctx.IASetInputLayout(null);
        ctx.VSSetShader(_vs);
        ctx.PSSetShader(_ps);
        ctx.PSSetConstantBuffer(1, _params);
        ctx.PSSetSampler(0, _sampler);
        ctx.PSSetShaderResource(0, texture);
        ctx.Draw(3, 0);
        ctx.PSSetShaderResource(0, null!);
    }

    public void Dispose()
    {
        _vs?.Dispose(); _ps?.Dispose(); _params?.Dispose(); _sampler?.Dispose(); _noCull?.Dispose();
        _vs = null; _ps = null; _params = null; _sampler = null; _noCull = null;
        _generation = -1;
    }

    /// The test card as a texture on `gpu`'s device.
    public static unsafe (ID3D11Texture2D Texture, ID3D11ShaderResourceView View) CardTexture(SharedGpu gpu, (int W, int H) pixels, PixelRect wall, int panelPx)
    {
        using var bmp = TestCard.Draw(pixels, wall, panelPx);
        var tex = gpu.Device.CreateTexture2D(new Texture2DDescription(Format.B8G8R8A8_UNorm, (uint)bmp.Width, (uint)bmp.Height, 1, 1, BindFlags.ShaderResource));
        gpu.Context.UpdateSubresource(tex, 0, null, bmp.GetPixels(), (uint)bmp.RowBytes, 0);
        return (tex, gpu.Device.CreateShaderResourceView(tex));
    }
}

/// The output's window and its drawing: a plain Win32 window (borderless over a monitor, or a normal one), its own
/// swap chain, and a thread that draws one frame per refresh of the monitor it is on.
internal sealed class WallOutputView : IDisposable
{
    readonly WallOutputController _controller;
    readonly IntPtr _hwnd;
    readonly bool _windowed;
    public string? MonitorId { get; }
    RECT _placed;
    readonly Thread _thread;
    volatile bool _running = true;
    volatile int _width = 1, _height = 1;   // the client area in pixels (WM_SIZE); the thread follows it

    // the thread's
    readonly WallOutputDrawer _drawer = new();
    IDXGISwapChain1? _swapChain;
    ID3D11RenderTargetView? _target;
    IntPtr _waitable;
    int _generation = -1, _bufferW, _bufferH;
    (string Key, ID3D11Texture2D Texture, ID3D11ShaderResourceView View)? _card;
    float _fade;
    double _last = StageRenderer.Now();
    readonly double _start0 = StageRenderer.Now();
    bool _reported;

    public WallOutputView(WallOutputController controller, MonitorInfo? monitor)
    {
        _controller = controller;
        _windowed = monitor is null;
        MonitorId = monitor?.Id;
        if (monitor is { } m)
        {
            // over the taskbar of that monitor, never taking the keyboard, not in Alt+Tab or the taskbar
            _hwnd = CreateWindow("AmadeusDMXLEDWall", Proc, "LED Wall", WS_POPUP, WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                                 m.Bounds.Left, m.Bounds.Top, m.Bounds.Width, m.Bounds.Height);
            if (_hwnd == IntPtr.Zero) throw new InvalidOperationException("no window");
            Place(m.Bounds);
            ShowWindow(_hwnd, SW_SHOWNOACTIVATE);
        }
        else
        {
            var f = controller.WindowFrame();
            _hwnd = CreateWindow("AmadeusDMXLEDWall", Proc, L("LED Wall"), WS_OVERLAPPEDWINDOW, WS_EX_APPWINDOW, f.Left, f.Top, f.Width, f.Height);
            if (_hwnd == IntPtr.Zero) throw new InvalidOperationException("no window");
            ShowWindow(_hwnd, SW_SHOW);
        }
        ReadClient();
        _thread = new Thread(Run) { IsBackground = true, Name = "LED wall output", Priority = ThreadPriority.AboveNormal };
        _thread.Start();
    }

    public (int W, int H) ClientPixels => (_width, _height);

    /// Over the whole monitor (its place on the desktop may change with the layout).
    public void Place(RECT r)
    {
        if (_windowed || r.Equals(_placed)) return;
        _placed = r;
        SetWindowPos(_hwnd, HWND_TOPMOST, r.Left, r.Top, r.Width, r.Height, SWP_NOACTIVATE | SWP_FRAMECHANGED);
        ReadClient();
    }

    void ReadClient()
    {
        if (!GetClientRect(_hwnd, out var c)) return;
        _width = Math.Max(1, c.Width);
        _height = Math.Max(1, c.Height);
    }

    IntPtr Proc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        switch (msg)
        {
            case WM_SIZE:
                ReadClient();
                _controller.UpdatePixels();
                return IntPtr.Zero;
            case WM_ERASEBKGND:
                return 1;   // the swap chain draws it all
            case WM_MOUSEACTIVATE when !_windowed:
                return MA_NOACTIVATE;
            case WM_SIZING when _windowed:
                KeepAspect(wParam.ToInt32(), lParam);
                return 1;
            case WM_CLOSE when _windowed:
                if (GetWindowRect(hwnd, out var r)) WallOutputController.SaveWindowFrame(r);
                _controller.WindowClosed();
                return IntPtr.Zero;
            case WM_CLOSE:
                return IntPtr.Zero;   // only the app closes the output on a monitor
        }
        return DefWindowProcW(hwnd, msg, wParam, lParam);
    }

    /// The window's picture stays 16:9 while it is dragged larger or smaller (contentAspectRatio).
    void KeepAspect(int edge, IntPtr rect)
    {
        var r = Marshal.PtrToStructure<RECT>(rect);
        if (!GetWindowRect(_hwnd, out var w) || !GetClientRect(_hwnd, out var c)) return;
        int fw = w.Width - c.Width, fh = w.Height - c.Height;   // the frame and the title bar
        int cw = Math.Max(160, r.Width - fw), ch = Math.Max(90, r.Height - fh);
        const int Top = 3, Bottom = 6, TopLeft = 4, TopRight = 5;
        if (edge is Top or Bottom) cw = (int)Math.Round(ch * 16 / 9.0);
        else ch = (int)Math.Round(cw * 9 / 16.0);
        if (edge is Top or TopLeft or TopRight) r.Top = r.Bottom - ch - fh; else r.Bottom = r.Top + ch + fh;
        if (edge is TopLeft or 1 or 7) r.Left = r.Right - cw - fw; else r.Right = r.Left + cw + fw;
        Marshal.StructureToPtr(r, rect, false);
    }

    public void Dispose()
    {
        _running = false;
        if (!_thread.Join(TimeSpan.FromSeconds(2))) Console.Error.WriteLine("LED wall output: the drawing thread didn't stop");
        if (_windowed && GetWindowRect(_hwnd, out var r)) WallOutputController.SaveWindowFrame(r);
        DestroyWindow(_hwnd);
    }

    // MARK: the drawing thread

    void Run()
    {
        // the monitor must not sleep while the wall plays (the idle timer would black out the LED wall mid-show);
        // per thread, so the engine's own keep-awake on the UI thread doesn't undo it
        SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED);
        try
        {
            while (_running)
            {
                SharedGpu gpu;
                try { gpu = SharedGpu.Get(); }
                catch (Exception e) when (e is SharpGenException or DllNotFoundException)
                {
                    Report(e);
                    Thread.Sleep(500);
                    continue;
                }
                try
                {
                    if (_swapChain is null || _generation != gpu.Generation) CreateSwapChain(gpu);
                    if (_width != _bufferW || _height != _bufferH) ResizeSwapChain(gpu);
                    if (_waitable != IntPtr.Zero) WaitForSingleObjectEx(_waitable, 100, true);
                    if (!_running) break;
                    DrawFrame(gpu);
                    _swapChain!.Present(1, PresentFlags.None).CheckError();
                }
                catch (SharpGenException e)
                {
                    // the device was lost (or the swap chain broke): everything again, on a new device if need be
                    Report(e);
                    if (gpu.Device.DeviceRemovedReason.Failure || e.ResultCode.Code is unchecked((int)0x887A0005) or unchecked((int)0x887A0007))
                        SharedGpu.Lost(gpu.Device);
                    ReleaseSwapChain(gpu);
                    Thread.Sleep(100);
                }
                catch (Exception e) when (e is InvalidOperationException or FileNotFoundException)
                {
                    Report(e);   // the shaders: nothing to draw with
                    Thread.Sleep(1000);
                }
            }
        }
        finally
        {
            ReleaseSwapChain(SharedGpu.Current);
            _drawer.Dispose();
            SetThreadExecutionState(ES_CONTINUOUS);
        }
    }

    void Report(Exception e)
    {
        if (_reported) return;
        _reported = true;
        Console.Error.WriteLine($"LED wall output: {e.Message}");
    }

    void CreateSwapChain(SharedGpu gpu)
    {
        ReleaseSwapChain(gpu);
        _generation = gpu.Generation;
        using var dxgi = gpu.Device.QueryInterface<IDXGIDevice>();
        using var adapter = dxgi.GetAdapter();
        using var factory = adapter.GetParent<IDXGIFactory2>();
        int w = _width, h = _height;
        var desc = new SwapChainDescription1
        {
            Width = (uint)w, Height = (uint)h, Format = Format.B8G8R8A8_UNorm, Stereo = false,
            SampleDescription = new SampleDescription(1, 0), BufferUsage = Usage.RenderTargetOutput, BufferCount = 2,
            Scaling = Scaling.Stretch, SwapEffect = SwapEffect.FlipDiscard, AlphaMode = AlphaMode.Ignore,
            Flags = SwapChainFlags.FrameLatencyWaitableObject,
        };
        _swapChain = factory.CreateSwapChainForHwnd(gpu.Device, _hwnd, desc);
        factory.MakeWindowAssociation(_hwnd, WindowAssociationFlags.IgnoreAltEnter);   // never exclusive full screen
        using (var sc2 = _swapChain.QueryInterface<IDXGISwapChain2>())
        {
            sc2.MaximumFrameLatency = 1;   // one frame queued: the wall is as close to the show as the monitor allows
            _waitable = sc2.FrameLatencyWaitableObject;
        }
        (_bufferW, _bufferH) = (w, h);
        MakeTarget(gpu);
    }

    void ResizeSwapChain(SharedGpu gpu)
    {
        int w = _width, h = _height;
        using (gpu.Lock())
        {
            _target?.Dispose();
            _target = null;
            gpu.Context.ClearState();   // the back buffers may still be bound
            _swapChain!.ResizeBuffers(2, (uint)w, (uint)h, Format.Unknown, SwapChainFlags.FrameLatencyWaitableObject).CheckError();
        }
        (_bufferW, _bufferH) = (w, h);
        MakeTarget(gpu);
    }

    void MakeTarget(SharedGpu gpu)
    {
        using var tex = _swapChain!.GetBuffer<ID3D11Texture2D>(0);
        // raw values, like the Mac's bgra8Unorm layer: the picture's pixels are what the LED processor gets
        _target = gpu.Device.CreateRenderTargetView(tex, new RenderTargetViewDescription(RenderTargetViewDimension.Texture2D, Format.B8G8R8A8_UNorm));
    }

    void ReleaseSwapChain(SharedGpu? gpu)
    {
        _target?.Dispose();
        _target = null;
        if (_card is { } c) { c.View.Dispose(); c.Texture.Dispose(); _card = null; }
        if (_waitable != IntPtr.Zero) { CloseHandle(_waitable); _waitable = IntPtr.Zero; }
        if (_swapChain is not null)
        {
            if (gpu is not null && gpu.Generation == _generation)
                using (gpu.Lock()) gpu.Context.ClearState();   // its buffers may still be bound
            _swapChain.Dispose();
            _swapChain = null;
        }
        _generation = -1;
    }

    void DrawFrame(SharedGpu gpu)
    {
        var now = StageRenderer.Now();
        var dt = (float)Math.Min(0.1, now - _last);
        _last = now;
        var plan = _controller.Plan;
        var (hello, frame, receiving) = _controller.Source();
        var state = WallSource.Shared.Update(frame, hello, now);
        // the show stopped (or this rig has no LED wall): black within half a second, never a frozen picture
        var live = receiving && state is not null ? 1f : 0f;
        _fade += (live - _fade) * MathF.Min(1, dt * (live > _fade ? 6 : 4));
        if (live == 0 && _fade < 0.01f) _fade = 0;

        var d = (_bufferW, _bufferH);
        var src = WallSource.Shared;
        src.Scale = plan.PictureScale(d, src.Aspect, src.Canvas);   // a show on a rig of another shape
        var (wall, pic) = plan.Layout(d, src.Aspect);
        using (gpu.Lock())
        {
            var picture = WallSource.Shared.Compose(gpu, now);
            var card = plan.TestPattern ? TestCardView(gpu, wall, plan.ModeWall(d), plan.PanelPx) : null;
            _drawer.Encode(gpu, _target!, wall, pic, plan.Brightness * (card is not null ? 1 : _fade * (state?.Level ?? 0)), card, picture, (float)(now - _start0));
        }
    }

    /// The test card's picture for this wall (kept until the wall's size or the panel size changes).
    ID3D11ShaderResourceView TestCardView(SharedGpu gpu, PixelRect wall, PixelRect modeWall, int panelPx)
    {
        var key = $"{wall.W}x{wall.H}:{modeWall.X},{modeWall.Y},{modeWall.W},{modeWall.H}:{panelPx}";
        if (_card is { } c && c.Key == key) return c.View;
        if (_card is { } old) { old.View.Dispose(); old.Texture.Dispose(); }
        var (t, v) = WallOutputDrawer.CardTexture(gpu, (wall.W, wall.H), modeWall, panelPx);
        _card = (key, t, v);
        return v;
    }
}
