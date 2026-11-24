// The LED wall's picture on the GPU (the Direct3D half of mac/Sources/AmadeusDMX/Render/WallSource.swift): the CPU's
// drawing uploaded, then one pass draws it or the psychedelic shader, times the wall's level, into a 1280×720 RGBA16F
// texture with mipmaps that every stage and the LED Wall Output read (WallSource.hlsl).
//
// The Mac draws everything on one Metal queue, so the picture is written before anyone reads it. Here that is one
// Direct3D 11 device and its immediate context for the whole app (SharedGpu): every StageView (the show's, the rig
// editor's, the set page's) and the output draw with it. The output renders on a thread of its own (it follows its
// monitor's refresh, not the app's), so the device is multithread-protected and every draw holds its lock
// (SharedGpu.Lock) from the first state it sets to its last draw: the stage's frame, the output's frame and the
// compose pass never interleave.
using System.Numerics;
using SharpGen.Runtime;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Vortice.Mathematics;
using Format = Vortice.DXGI.Format;

namespace AmadeusDMX;

/// The app's one Direct3D 11 device and immediate context (the Mac's WallSource.gpu: device and queue).
public sealed class SharedGpu : IDisposable
{
    static readonly Lock Gate = new();
    static SharedGpu? _current;
    static int _generations;

    public ID3D11Device Device { get; }
    public ID3D11DeviceContext Context { get; }
    public FeatureLevel FeatureLevel { get; }
    /// Counts the devices made: a new one (after a lost device) means everything on the old one is gone.
    public int Generation { get; }
    readonly ID3D11Multithread? _multithread;

    SharedGpu(ID3D11Device device, ID3D11DeviceContext context, FeatureLevel level, int generation)
    {
        Device = device;
        Context = context;
        FeatureLevel = level;
        Generation = generation;
        _multithread = context.QueryInterfaceOrNull<ID3D11Multithread>() ?? device.QueryInterfaceOrNull<ID3D11Multithread>();
        _multithread?.SetMultithreadProtected(true);
    }

    /// The device, made on first use (or again after it was lost). Throws when Direct3D 11 isn't available at all.
    public static SharedGpu Get()
    {
        lock (Gate) return _current ??= Create();
    }

    /// The device, when one is up already (nil: none yet, or it was lost).
    public static SharedGpu? Current { get { lock (Gate) return _current; } }

    /// `device` was lost (a driver update, the GPU reset, a laptop switching GPUs): the next Get makes a new one.
    /// The first of its users to notice says so; the others find a newer generation and only make theirs again. The
    /// old one is let go, not released: another thread may be in the middle of a frame with it (a rare moment, and a
    /// lost device holds little).
    public static void Lost(ID3D11Device? device)
    {
        lock (Gate)
        {
            if (_current is not { } c || (device is not null && device.NativePointer != c.Device.NativePointer)) return;
            _current = null;
        }
    }

    /// The highest feature level asked for: `-d3dFeatureLevel 10.0` (or 10.1, 11.0) tries the stage as older graphics
    /// draw it, on any card (for testing).
    static FeatureLevel[] Levels(string? cap)
    {
        FeatureLevel[] all = [FeatureLevel.Level_11_1, FeatureLevel.Level_11_0, FeatureLevel.Level_10_1, FeatureLevel.Level_10_0];
        var max = cap switch { "10.0" or "10_0" => FeatureLevel.Level_10_0, "10.1" or "10_1" => FeatureLevel.Level_10_1, "11.0" or "11_0" => FeatureLevel.Level_11_0, _ => FeatureLevel.Level_11_1 };
        return all.Where(l => l <= max).ToArray();
    }

    /// The default adapter (WARP, Windows's software renderer, when there is no usable GPU).
    static SharedGpu Create()
    {
        var levels = Levels(Defaults.Standard.String("d3dFeatureLevel"));
        var flags = DeviceCreationFlags.BgraSupport;
        var dev = Defaults.Standard.Bool("d3dDebug") ? flags | DeviceCreationFlags.Debug : flags;
        var hr = D3D11.D3D11CreateDevice(null, DriverType.Hardware, dev, levels, out var device, out var level, out var context);
        if (hr.Failure && dev != flags) hr = D3D11.D3D11CreateDevice(null, DriverType.Hardware, flags, levels, out device, out level, out context);
        if (hr.Failure) hr = D3D11.D3D11CreateDevice(null, DriverType.Warp, flags, levels, out device, out level, out context);
        hr.CheckError();
        return new SharedGpu(device!, context!, level, ++_generations);
    }

    /// Holds the device for a whole sequence of state and draws (ID3D11Multithread::Enter … Leave; re-entrant).
    public Held Lock()
    {
        _multithread?.Enter();
        return new Held(_multithread);
    }

    public readonly struct Held(ID3D11Multithread? m) : IDisposable
    {
        public void Dispose() => m?.Leave();
    }

    public void Dispose()
    {
        _multithread?.Dispose();
        Context.Dispose();
        Device.Dispose();
    }
}

public sealed partial class WallSource
{
    readonly double _startTime = StageRenderer.Now();
    int _gpuGeneration = -1;
    ID3D11Texture2D? _cpu, _picture;
    ID3D11ShaderResourceView? _cpuView, _pictureView;
    ID3D11RenderTargetView? _pictureTarget;
    ID3D11VertexShader? _vs;
    ID3D11PixelShader? _composePS;
    ID3D11Buffer? _params;
    ID3D11SamplerState? _sampler;
    int _cpuW, _cpuH;
    int _uploaded = -1, _composed = -1;
    double _composedAt = double.NegativeInfinity;

    /// Brings the GPU's picture up to what Update last made: the upload and the compose pass, only when they changed
    /// (psychedelic moves on the GPU's own clock: drawn again for every display frame, at most 90 a second). Call it
    /// with `gpu`'s lock held. Returns the picture (on `gpu`'s device), nil while there is none.
    public ID3D11ShaderResourceView? Compose(SharedGpu gpu, double now)
    {
        lock (_lock)
        {
            if (_gpuGeneration != gpu.Generation) Build(gpu);
            if (_state is not { } s || _pictureView is null || _composePS is null) return _pictureView;
            if (!s.Psychedelic && _uploaded != _pictureVersion) Upload(gpu);
            if (_composed != _stateVersion || (s.Psychedelic && now - _composedAt > 1.0 / 90))
            {
                if (s.Psychedelic || _cpuView is not null) Draw(gpu, s, now);
                _composed = _stateVersion;
                _composedAt = now;
            }
            return _pictureView;
        }
    }

    void Build(SharedGpu gpu)
    {
        ReleaseGpu();
        _gpuGeneration = gpu.Generation;
        var d = gpu.Device;
        try
        {
            _vs = d.CreateVertexShader(ShaderLibrary.Bytecode("WallSource.hlsl", "wall_fs_vertex", "vs_4_0"));
            _composePS = d.CreatePixelShader(ShaderLibrary.Bytecode("WallSource.hlsl", "wall_compose", "ps_4_0"));
        }
        catch (Exception e) when (e is InvalidOperationException or SharpGenException or FileNotFoundException)
        {
            Console.Error.WriteLine($"wall shaders: {e.Message}");
        }
        _params = d.CreateBuffer(new BufferDescription(WallParams.Size, BindFlags.ConstantBuffer));
        _sampler = d.CreateSamplerState(new SamplerDescription
        {
            Filter = Filter.MinMagMipLinear,
            AddressU = TextureAddressMode.Clamp, AddressV = TextureAddressMode.Clamp, AddressW = TextureAddressMode.Clamp,
            ComparisonFunc = ComparisonFunction.Never, MinLOD = 0, MaxLOD = float.MaxValue,
        });
        var mips = (uint)(Math.Floor(Math.Log2(Math.Max(PictureW, PictureH))) + 1);
        _picture = d.CreateTexture2D(new Texture2DDescription(Format.R16G16B16A16_Float, PictureW, PictureH, 1, mips,
            BindFlags.ShaderResource | BindFlags.RenderTarget, ResourceUsage.Default, CpuAccessFlags.None, 1, 0, ResourceOptionFlags.GenerateMips));
        _pictureTarget = d.CreateRenderTargetView(_picture);   // mip 0
        _pictureView = d.CreateShaderResourceView(_picture);
        // black until the first compose (a stage that reads it before then shows a dark wall, never garbage)
        gpu.Context.ClearRenderTargetView(_pictureTarget, new Color4(0, 0, 0, 1));
        gpu.Context.GenerateMips(_pictureView);
        _uploaded = _composed = -1;
    }

    unsafe void Upload(SharedGpu gpu)
    {
        var r = _renderer;
        int w = r.PixelWidth, h = r.PixelHeight;
        if (_cpu is null || _cpuW != w || _cpuH != h)
        {
            _cpuView?.Dispose(); _cpu?.Dispose();
            _cpu = gpu.Device.CreateTexture2D(new Texture2DDescription(Format.B8G8R8A8_UNorm, (uint)w, (uint)h, 1, 1, BindFlags.ShaderResource));
            _cpuView = gpu.Device.CreateShaderResourceView(_cpu);
            (_cpuW, _cpuH) = (w, h);
        }
        var px = r.Pixels;
        fixed (byte* p = px)
            gpu.Context.UpdateSubresource(_cpu, 0, null, (IntPtr)p, (uint)r.RowBytes, 0);
        _uploaded = _pictureVersion;
    }

    void Draw(SharedGpu gpu, WallState s, double now)
    {
        var ctx = gpu.Context;
        var pal = s.Palette.Length > 0 ? s.Palette : [Vector3.One];
        Vector3 P(int i) => pal[Math.Min(i, pal.Length - 1)];
        var wp = new WallParams
        {
            Info = new(s.Level, s.Psychedelic ? 1 : 0, (float)(now - _startTime), 0), Bands = s.Bands,
            Pal0 = new(P(0), 1), Pal1 = new(P(1), 1), Pal2 = new(P(2), 1), Pal3 = new(P(3), 1),
        };
        ctx.UpdateSubresource(in wp, _params!);
        ctx.OMSetRenderTargets(_pictureTarget!, null);
        ctx.RSSetViewport(new Viewport(PictureW, PictureH));
        ctx.RSSetState(null);
        ctx.OMSetBlendState(null);
        ctx.OMSetDepthStencilState(null);
        ctx.IASetPrimitiveTopology(PrimitiveTopology.TriangleList);
        ctx.IASetInputLayout(null);
        ctx.VSSetShader(_vs);
        ctx.PSSetShader(_composePS);
        ctx.PSSetConstantBuffer(0, _params);
        ctx.PSSetSampler(0, _sampler);
        ctx.PSSetShaderResource(0, _cpuView!);   // (psychedelic: whatever was drawn last, unused)
        ctx.Draw(3, 0);
        ctx.PSSetShaderResource(0, null!);
        ctx.UnsetRenderTargets();                       // the picture is read next: not a target any more
        ctx.GenerateMips(_pictureView!);                // the stage's wall, seen small
    }

    void ReleaseGpu()
    {
        foreach (var o in new IDisposable?[] { _cpuView, _cpu, _pictureView, _pictureTarget, _picture, _vs, _composePS, _params, _sampler })
            o?.Dispose();
        _cpuView = _pictureView = null;
        _cpu = _picture = null;
        _pictureTarget = null;
        _vs = null;
        _composePS = null;
        _params = null;
        _sampler = null;
        _cpuW = _cpuH = 0;
        _gpuGeneration = -1;
    }
}
