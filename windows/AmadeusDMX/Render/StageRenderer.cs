// The Direct3D 11 stage (mac/Sources/AmadeusDMX/Render/StageRenderer.swift): scenery, volumetric beams, gobo beams
// and their projections, spots, lasers, flares and the LED wall into an HDR target, then bloom (a blur at half and quarter resolution) and a
// tone curve into the window. What a frame shows is worked out on the CPU first (StageRenderer.State.cs,
// PrepareFrame); this half puts it on the GPU. The view (StageView) owns the swap chain and presents; the render
// self-test draws into a texture instead.
//
// Metal → Direct3D 11: MTLRenderPipelineState = a vertex + pixel shader, input layout and blend state (Pipeline);
// setVertexBytes = a dynamic buffer refilled per frame; MPSImageBilinearScale / MPSImageGaussianBlur /
// MPSImageStatisticsMean = a downsample pass / a two-pass Gaussian blur / GenerateMips down to 1×1; the command
// buffer's gpuStartTime/gpuEndTime = timestamp queries (GpuTimer).
using System.Numerics;
using System.Runtime.InteropServices;
using SharpGen.Runtime;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Vortice.Mathematics;
using Format = Vortice.DXGI.Format;

namespace AmadeusDMX;

public sealed partial class StageRenderer : IDisposable
{
    /// A vertex and a pixel shader with their input layout and blend state.
    sealed class Pipeline(ID3D11VertexShader vs, ID3D11PixelShader ps, ID3D11InputLayout? layout, ID3D11BlendState? blend) : IDisposable
    {
        public readonly ID3D11VertexShader VS = vs;
        public readonly ID3D11PixelShader PS = ps;
        public readonly ID3D11InputLayout? Layout = layout;
        public readonly ID3D11BlendState? Blend = blend;

        public void Dispose() { VS.Dispose(); PS.Dispose(); Layout?.Dispose(); }
    }

    /// A buffer refilled every frame (Metal's setVertexBytes), grown when a frame needs more.
    sealed class DynamicBuffer(BindFlags bind, int stride, bool structured) : IDisposable
    {
        public ID3D11Buffer? Buffer;
        public ID3D11ShaderResourceView? View;
        int _capacity;

        public unsafe void Upload<T>(ID3D11Device device, ID3D11DeviceContext context, ReadOnlySpan<T> data) where T : unmanaged
        {
            if (data.Length == 0) return;
            if (data.Length > _capacity)
            {
                Dispose();
                _capacity = (int)BitOperations.RoundUpToPowerOf2((uint)Math.Max(64, data.Length));
                Buffer = device.CreateBuffer(new BufferDescription((uint)(_capacity * stride), bind, ResourceUsage.Dynamic, CpuAccessFlags.Write,
                    structured ? ResourceOptionFlags.BufferStructured : ResourceOptionFlags.None, structured ? (uint)stride : 0));
                if (structured)
                    View = device.CreateShaderResourceView(Buffer, new ShaderResourceViewDescription(Buffer, Format.Unknown, 0, (uint)_capacity, BufferExtendedShaderResourceViewFlags.None));
            }
            var m = context.Map(Buffer!, 0, MapMode.WriteDiscard, Vortice.Direct3D11.MapFlags.None);
            data.CopyTo(new Span<T>((void*)m.DataPointer, data.Length));
            context.Unmap(Buffer!, 0);
        }

        public void Dispose()
        {
            View?.Dispose(); View = null;
            Buffer?.Dispose(); Buffer = null;
            _capacity = 0;
        }
    }

    /// A render target with its views.
    sealed class Target : IDisposable
    {
        public required ID3D11Texture2D Texture;
        public required ID3D11RenderTargetView RTV;
        public required ID3D11ShaderResourceView SRV;
        public int Width, Height, Mips = 1;

        public void Dispose() { SRV.Dispose(); RTV.Dispose(); Texture.Dispose(); }
    }

    public ID3D11Device Device { get; private set; } = null!;
    public ID3D11DeviceContext Context { get; private set; } = null!;
    public FeatureLevel FeatureLevel { get; private set; }
    Pipeline? solidPipe, beamPipe, spritePipe, decalPipe, linePipe, wallPipe, compositePipe, zonePipe, downsamplePipe, blurPipe;
    Pipeline? goboBeamPipe, goboDecalPipe, underlayPipe;
    ID3D11DepthStencilState? solidDepth, lightDepth;
    ID3D11RasterizerState? rasterizer;
    ID3D11SamplerState? sampler;
    ID3D11BlendState? additive, premultiplied;
    ID3D11Buffer? coneBuffer, cappedConeBuffer;
    int coneCount, cappedConeCount;
    // the gobo pictures (StageRenderer.State.cs GoboPictures) as texture slices
    ID3D11Texture2D? goboTexture;
    ID3D11ShaderResourceView? goboView;
    int _uploadedGobos = -1;
    ID3D11Buffer? sceneryBuffer, zoneBuffer, wallBuffer;
    int sceneryCount, zoneCount;
    int _uploadedScenery = -1;
    // the rig editor's drawings: a texture per page file (kept while it is drawn), the triangles per drawing
    readonly Dictionary<string, (ID3D11Texture2D Texture, ID3D11ShaderResourceView View)> _pages = [];
    readonly List<(ID3D11Buffer Buffer, int Count, ID3D11ShaderResourceView View)> _drawings = [];
    ID3D11Texture2D? wallTexture;
    ID3D11ShaderResourceView? wallView;
    Target? hdr, halfA, halfB, halfT, quarterA, quarterB, quarterT;
    ID3D11Texture2D? depthTexture;
    ID3D11DepthStencilView? depth;
    ID3D11Buffer? uniformsBuffer, wallParamsBuffer, blurBuffer;
    readonly DynamicBuffer _parts = new(BindFlags.VertexBuffer, SolidVertex.Size, false);
    readonly DynamicBuffer _beams = new(BindFlags.ShaderResource, BeamInstance.Size, true);
    readonly DynamicBuffer _sprites = new(BindFlags.ShaderResource, SpriteInstance.Size, true);
    readonly DynamicBuffer _decals = new(BindFlags.ShaderResource, DecalInstance.Size, true);
    readonly DynamicBuffer _lines = new(BindFlags.ShaderResource, LineInstance.Size, true);
    readonly DynamicBuffer _goboBeams = new(BindFlags.ShaderResource, GoboBeamInstance.Size, true);
    readonly DynamicBuffer _goboDecals = new(BindFlags.ShaderResource, GoboDecalInstance.Size, true);
    readonly DynamicBuffer _zoneEdges = new(BindFlags.ShaderResource, LineInstance.Size, true);
    // auto exposure: the mean of the quarter-size light buffer, read back a couple of frames later (no stall)
    readonly ID3D11Texture2D?[] _stats = new ID3D11Texture2D?[3];
    int _statsFrame;
    GpuTimer? _timer;
    readonly StageFrame _frame = new();

    /// Metal's init?(view:): a renderer on the default adapter (WARP, Windows's software renderer, when there is no
    /// usable GPU), or nil when Direct3D 11 isn't available at all.
    public static StageRenderer? Make()
    {
        var r = new StageRenderer();
        try
        {
            r.CreateDevice();
            return r;
        }
        catch (Exception e) when (e is SharpGenException or InvalidOperationException or FileNotFoundException or DllNotFoundException)
        {
            Console.Error.WriteLine($"stage: {e.Message}");
            r.Dispose();
            return null;
        }
    }

    void CreateDevice()
    {
        FeatureLevel[] levels = [FeatureLevel.Level_11_1, FeatureLevel.Level_11_0, FeatureLevel.Level_10_1, FeatureLevel.Level_10_0];
        var flags = DeviceCreationFlags.BgraSupport;
        var dev = Defaults.Standard.Bool("d3dDebug") ? flags | DeviceCreationFlags.Debug : flags;
        var hr = D3D11.D3D11CreateDevice(null, DriverType.Hardware, dev, levels, out var device, out var level, out var context);
        if (hr.Failure && dev != flags) hr = D3D11.D3D11CreateDevice(null, DriverType.Hardware, flags, levels, out device, out level, out context);
        if (hr.Failure) hr = D3D11.D3D11CreateDevice(null, DriverType.Warp, flags, levels, out device, out level, out context);
        hr.CheckError();
        Device = device!;
        Context = context!;
        FeatureLevel = level;
        BuildPipelines();
        BuildCone();
        var td = new Texture2DDescription(Format.B8G8R8A8_UNorm, WallRenderer.W, WallRenderer.H, 1, 1, BindFlags.ShaderResource);
        wallTexture = Device.CreateTexture2D(td);
        wallView = Device.CreateShaderResourceView(wallTexture);
        uniformsBuffer = Device.CreateBuffer(new BufferDescription(Uniforms.Size, BindFlags.ConstantBuffer));
        wallParamsBuffer = Device.CreateBuffer(new BufferDescription(WallParams.Size, BindFlags.ConstantBuffer));
        blurBuffer = Device.CreateBuffer(new BufferDescription(BlurParams.Size, BindFlags.ConstantBuffer));
        for (var i = 0; i < _stats.Length; i++)
            _stats[i] = Device.CreateTexture2D(new Texture2DDescription(Format.R16G16B16A16_Float, 1, 1, 1, 1, BindFlags.None,
                ResourceUsage.Staging, CpuAccessFlags.Read));
        _timer = new GpuTimer(Device);
        _uploadedScenery = -1;
        _uploadedGobos = -1;
    }

    /// The device was lost (a driver update, the GPU reset, a laptop switching GPUs): everything on the GPU is
    /// made again; the scene uploads itself on the next frame.
    public void ResetDevice()
    {
        ReleaseDevice();
        CreateDevice();
        Wake();
    }

    void ReleaseDevice()
    {
        ReleaseTargets();
        foreach (var p in new[] { solidPipe, beamPipe, spritePipe, decalPipe, linePipe, wallPipe, compositePipe, zonePipe, downsamplePipe, blurPipe,
                                  goboBeamPipe, goboDecalPipe, underlayPipe })
            p?.Dispose();
        solidPipe = beamPipe = spritePipe = decalPipe = linePipe = wallPipe = compositePipe = zonePipe = downsamplePipe = blurPipe = null;
        goboBeamPipe = goboDecalPipe = underlayPipe = null;
        ReleaseDrawings(keep: null);
        solidDepth?.Dispose(); lightDepth?.Dispose(); rasterizer?.Dispose(); sampler?.Dispose(); additive?.Dispose(); premultiplied?.Dispose();
        solidDepth = lightDepth = null; rasterizer = null; sampler = null; additive = premultiplied = null;
        coneBuffer?.Dispose(); cappedConeBuffer?.Dispose(); sceneryBuffer?.Dispose(); zoneBuffer?.Dispose(); wallBuffer?.Dispose();
        coneBuffer = cappedConeBuffer = sceneryBuffer = zoneBuffer = wallBuffer = null;
        goboView?.Dispose(); goboTexture?.Dispose(); goboView = null; goboTexture = null;
        wallView?.Dispose(); wallTexture?.Dispose(); wallView = null; wallTexture = null;
        uniformsBuffer?.Dispose(); wallParamsBuffer?.Dispose(); blurBuffer?.Dispose();
        uniformsBuffer = wallParamsBuffer = blurBuffer = null;
        foreach (var d in new[] { _parts, _beams, _sprites, _decals, _lines, _zoneEdges, _goboBeams, _goboDecals }) d.Dispose();
        for (var i = 0; i < _stats.Length; i++) { _stats[i]?.Dispose(); _stats[i] = null; }
        _timer?.Dispose(); _timer = null;
        Context?.ClearState();
        Context?.Dispose();
        Device?.Dispose();
        Context = null!;
        Device = null!;
    }

    public void Dispose()
    {
        ReleaseDevice();
        _wall.Dispose();
    }

    void ReleaseTargets()
    {
        foreach (var t in new[] { hdr, halfA, halfB, halfT, quarterA, quarterB, quarterT }) t?.Dispose();
        hdr = halfA = halfB = halfT = quarterA = quarterB = quarterT = null;
        depth?.Dispose(); depthTexture?.Dispose();
        depth = null; depthTexture = null;
    }

    Target MakeTarget(int w, int h, bool mips = false)
    {
        w = Math.Max(1, w); h = Math.Max(1, h);
        var levels = mips ? 1 + (int)Math.Floor(Math.Log2(Math.Max(w, h))) : 1;
        var d = new Texture2DDescription(Format.R16G16B16A16_Float, (uint)w, (uint)h, 1, (uint)levels, BindFlags.ShaderResource | BindFlags.RenderTarget,
            ResourceUsage.Default, CpuAccessFlags.None, 1, 0, mips ? ResourceOptionFlags.GenerateMips : ResourceOptionFlags.None);
        var tex = Device.CreateTexture2D(d);
        return new Target
        {
            Texture = tex, Width = w, Height = h, Mips = levels,
            RTV = Device.CreateRenderTargetView(tex),   // mip 0
            SRV = Device.CreateShaderResourceView(tex),
        };
    }

    void EnsureTargets(int w, int h)
    {
        if (hdr is { } t && t.Width == w && t.Height == h) return;
        ReleaseTargets();
        hdr = MakeTarget(w, h);
        depthTexture = Device.CreateTexture2D(new Texture2DDescription(Format.D32_Float, (uint)w, (uint)h, 1, 1, BindFlags.DepthStencil));
        depth = Device.CreateDepthStencilView(depthTexture);
        halfA = MakeTarget(w / 2, h / 2); halfB = MakeTarget(w / 2, h / 2); halfT = MakeTarget(w / 2, h / 2);
        quarterA = MakeTarget(w / 4, h / 4, mips: true); quarterB = MakeTarget(w / 4, h / 4); quarterT = MakeTarget(w / 4, h / 4);
    }

    // MARK: drawing

    /// Draw a frame into `target` (the swap chain's back buffer, or the self-test's texture), `size` its pixels.
    /// Throws a SharpGenException when the device is lost (the caller resets it).
    public void Draw(ID3D11RenderTargetView target, Vector2 size, double? now = null)
    {
        var f = _frame;
        PrepareFrame(f, now ?? Now(), size);
        EnsureTargets(f.Width, f.Height);
        var ctx = Context;
        UploadScenery();
        if (GoboPictures is { } pics && (_uploadedGobos != GoboVersion || goboView is null))
        {
            _uploadedGobos = GoboVersion;
            BuildGobos(pics);
        }
        _timer?.Begin(ctx);

        // the frame's buffers
        ctx.UpdateSubresource(in f.U, uniformsBuffer!);
        ctx.UpdateSubresource(in f.Wp, wallParamsBuffer!);
        if (f.WallPictureChanged) UploadWall();
        _parts.Upload(Device, ctx, (ReadOnlySpan<SolidVertex>)f.Parts.V.Span());
        _beams.Upload(Device, ctx, (ReadOnlySpan<BeamInstance>)f.Beams.Span());
        _sprites.Upload(Device, ctx, (ReadOnlySpan<SpriteInstance>)f.Sprites.Span());
        _decals.Upload(Device, ctx, (ReadOnlySpan<DecalInstance>)f.Decals.Span());
        _lines.Upload(Device, ctx, (ReadOnlySpan<LineInstance>)f.Lines.Span());
        _goboBeams.Upload(Device, ctx, (ReadOnlySpan<GoboBeamInstance>)f.GoboBeams.Span());
        _goboDecals.Upload(Device, ctx, (ReadOnlySpan<GoboDecalInstance>)f.GoboDecals.Span());

        // scene → HDR
        ctx.RSSetState(rasterizer);
        ctx.IASetPrimitiveTopology(PrimitiveTopology.TriangleList);
        ctx.VSSetConstantBuffer(0, uniformsBuffer);
        ctx.PSSetConstantBuffer(0, uniformsBuffer);
        ctx.PSSetSampler(0, sampler);
        ctx.OMSetRenderTargets(hdr!.RTV, depth);
        ctx.RSSetViewport(new Viewport(f.Width, f.Height));
        ctx.ClearRenderTargetView(hdr.RTV, new Color4(0.004f, 0.004f, 0.007f, 1));
        ctx.ClearDepthStencilView(depth!, DepthStencilClearFlags.Depth, 1, 0);
        if (sceneryBuffer is not null)
        {
            Use(solidPipe!, solidDepth);
            ctx.IASetVertexBuffer(0, sceneryBuffer, SolidVertex.Size);
            ctx.Draw((uint)sceneryCount, 0);
        }
        // the fixtures' moving parts and lenses: where the beams point, in the colours they play
        if (f.Parts.V.Count > 0)
        {
            Use(solidPipe!, solidDepth);
            ctx.IASetVertexBuffer(0, _parts.Buffer!, SolidVertex.Size);
            ctx.Draw((uint)f.Parts.V.Count, 0);
        }
        if (wallBuffer is not null)
        {
            Use(wallPipe!, solidDepth);
            ctx.IASetVertexBuffer(0, wallBuffer, WallVertex.Size);
            ctx.PSSetShaderResource(0, wallView!);
            ctx.PSSetConstantBuffer(1, wallParamsBuffer);
            ctx.Draw(6, 0);
        }
        // the rig editor's drawings on the floor: over the floor and the deck, under everything standing on them
        if (_drawings.Count > 0)
        {
            Use(underlayPipe!, lightDepth);
            foreach (var (buffer, count, view) in _drawings)
            {
                ctx.IASetVertexBuffer(0, buffer, UnderlayVertex.Size);
                ctx.PSSetShaderResource(0, view);
                ctx.Draw((uint)count, 0);
            }
            UnbindShaderResources();
        }
        if (f.Decals.Count > 0) Instanced(decalPipe!, _decals, 6, f.Decals.Count);
        // gobos: the instances are read by the pixel shader too, the pictures are a texture array
        if (f.GoboDecals.Count > 0 && goboView is not null)
        {
            Use(goboDecalPipe!, lightDepth);
            ctx.VSSetShaderResource(0, _goboDecals.View!);
            ctx.PSSetShaderResource(0, _goboDecals.View!);
            ctx.PSSetShaderResource(1, goboView);
            ctx.DrawInstanced(6, (uint)f.GoboDecals.Count, 0, 0);
            UnbindShaderResources();
        }
        if (f.GoboBeams.Count > 0 && goboView is not null)
        {
            Use(goboBeamPipe!, lightDepth);
            ctx.IASetVertexBuffer(0, cappedConeBuffer!, 12);
            ctx.VSSetShaderResource(0, _goboBeams.View!);
            ctx.PSSetShaderResource(0, _goboBeams.View!);
            ctx.PSSetShaderResource(1, goboView);
            ctx.DrawInstanced((uint)cappedConeCount, (uint)f.GoboBeams.Count, 0, 0);
            UnbindShaderResources();
        }
        if (f.Beams.Count > 0)
        {
            Use(beamPipe!, lightDepth);
            ctx.IASetVertexBuffer(0, coneBuffer!, 12);
            ctx.VSSetShaderResource(0, _beams.View!);
            ctx.DrawInstanced((uint)coneCount, (uint)f.Beams.Count, 0, 0);
        }
        if (f.Lines.Count > 0) Instanced(linePipe!, _lines, 6, f.Lines.Count);
        if (zoneBuffer is not null)
        {
            Use(zonePipe!, lightDepth);
            ctx.IASetVertexBuffer(0, zoneBuffer, SolidVertex.Size);
            ctx.Draw((uint)zoneCount, 0);
        }
        if (ZoneEdges.Count > 0) Instanced(linePipe!, _zoneEdges, 6, ZoneEdges.Count);
        if (f.Sprites.Count > 0) Instanced(spritePipe!, _sprites, 6, f.Sprites.Count);

        // bloom
        Pass(downsamplePipe!, hdr.SRV, halfA!);
        Pass(downsamplePipe!, hdr.SRV, quarterA!);
        Blur(halfA!, halfT!, halfB!, sigma: 4);
        Blur(quarterA!, quarterT!, quarterB!, sigma: 9);

        // auto exposure: the average light of this frame (read back two frames later) steers the exposure, like a camera
        var u = f.U;
        if (ReadStats() is { } lum) u.Params.Z = UpdateAutoExposure(lum, f.Dt);
        else u.Params.Z = Exposure * AutoExposure;
        ctx.GenerateMips(quarterA!.SRV);
        var slot = _stats[_statsFrame % _stats.Length];
        if (slot is not null) ctx.CopySubresourceRegion(slot, 0, 0, 0, 0, quarterA.Texture, (uint)(quarterA.Mips - 1), null);
        _statsFrame++;

        // composite → window
        ctx.UpdateSubresource(in u, uniformsBuffer!);
        ctx.OMSetRenderTargets(target, null);
        ctx.RSSetViewport(new Viewport(size.X, size.Y));
        Use(compositePipe!, null);
        ctx.IASetInputLayout(null);
        ctx.PSSetShaderResource(0, hdr.SRV);
        ctx.PSSetShaderResource(1, halfB!.SRV);
        ctx.PSSetShaderResource(2, quarterB!.SRV);
        ctx.Draw(3, 0);
        UnbindShaderResources();

        if (GpuStats && (DateTime.UtcNow - NanCheckAt).TotalSeconds > 3) CheckInvalid();
        _timer?.End(ctx);
        // the stage's GPU time: the power meter, the adaptive resolution (a few frames late: the queries don't stall)
        if (_timer?.Read(ctx) is { } seconds)
        {
            OnGPUTime?.Invoke(seconds);
            RecordGpuMs(seconds * 1000);
            if (GpuStats) RecordGPU(seconds * 1000, beams: f.Beams.Count, new Vector2(f.Width, f.Height));
        }
    }

    void Use(Pipeline p, ID3D11DepthStencilState? depthState)
    {
        var ctx = Context;
        ctx.VSSetShader(p.VS);
        ctx.PSSetShader(p.PS);
        ctx.IASetInputLayout(p.Layout);
        ctx.OMSetBlendState(p.Blend);
        ctx.OMSetDepthStencilState(depthState);
    }

    void Instanced(Pipeline p, DynamicBuffer instances, int vertices, int count)
    {
        Use(p, lightDepth);
        Context.VSSetShaderResource(0, instances.View!);
        Context.DrawInstanced((uint)vertices, (uint)count, 0, 0);
    }

    void UnbindShaderResources()
    {
        for (var i = 0u; i < 3; i++) Context.PSSetShaderResource(i, null!);
    }

    /// A full-screen pass: `source` → `dest` (bilinear scale, or a blur direction).
    void Pass(Pipeline p, ID3D11ShaderResourceView source, Target dest)
    {
        var ctx = Context;
        ctx.OMSetRenderTargets(dest.RTV, null);
        ctx.RSSetViewport(new Viewport(dest.Width, dest.Height));
        Use(p, null);
        ctx.PSSetShaderResource(0, source);
        ctx.Draw(3, 0);
        UnbindShaderResources();
    }

    /// MPSImageGaussianBlur: horizontal into `temp`, vertical into `dest`.
    void Blur(Target source, Target temp, Target dest, float sigma)
    {
        var ctx = Context;
        ctx.PSSetConstantBuffer(2, blurBuffer);
        var b = new BlurParams { Step = new Vector4(1f / source.Width, 0, sigma, 0) };
        ctx.UpdateSubresource(in b, blurBuffer!);
        Pass(blurPipe!, source.SRV, temp);
        b.Step = new Vector4(0, 1f / temp.Height, sigma, 0);
        ctx.UpdateSubresource(in b, blurBuffer!);
        Pass(blurPipe!, temp.SRV, dest);
    }

    /// The light of the frame two frames ago (luminance), when the GPU has it ready.
    unsafe float? ReadStats()
    {
        if (_statsFrame < _stats.Length - 1) return null;
        var slot = _stats[(_statsFrame + 1) % _stats.Length];
        if (slot is null) return null;
        var r = Context.Map(slot, 0, MapMode.Read, Vortice.Direct3D11.MapFlags.DoNotWait, out var m);
        if (r.Failure) return null;
        try
        {
            var px = (Half*)m.DataPointer;
            return 0.2126f * (float)px[0] + 0.7152f * (float)px[1] + 0.0722f * (float)px[2];
        }
        finally { Context.Unmap(slot, 0); }
    }

    unsafe void UploadWall()
    {
        var px = Wall.Pixels;
        fixed (byte* p = px)
            Context.UpdateSubresource(wallTexture!, 0, null, (IntPtr)p, (uint)Wall.RowBytes, 0);
    }

    void UploadScenery()
    {
        if (_uploadedScenery == SceneryVersion) return;
        _uploadedScenery = SceneryVersion;
        sceneryBuffer?.Dispose(); zoneBuffer?.Dispose(); wallBuffer?.Dispose();
        sceneryBuffer = zoneBuffer = wallBuffer = null;
        sceneryCount = Scenery?.Vertices.Count ?? 0;
        if (sceneryCount > 0) sceneryBuffer = Device.CreateBuffer((ReadOnlySpan<SolidVertex>)Scenery!.Vertices.Span(), BindFlags.VertexBuffer);
        zoneCount = ZoneVertices.Count;
        if (zoneCount > 0) zoneBuffer = Device.CreateBuffer((ReadOnlySpan<SolidVertex>)ZoneVertices.Span(), BindFlags.VertexBuffer);
        _zoneEdges.Upload(Device, Context, (ReadOnlySpan<LineInstance>)ZoneEdges.Span());
        if (WallVertices is { } wv) wallBuffer = Device.CreateBuffer((ReadOnlySpan<WallVertex>)wv, BindFlags.VertexBuffer);
        UploadDrawings();
    }

    /// The drawings' triangles, and a texture for each page not on the GPU yet (one per file; gone when no longer drawn).
    void UploadDrawings()
    {
        ReleaseDrawings(keep: DrawingQuads.Select(d => d.Key).ToHashSet());
        foreach (var (key, picture, vertices) in DrawingQuads)
        {
            if (!_pages.TryGetValue(key, out var page)) _pages[key] = page = PageTexture(picture);
            _drawings.Add((Device.CreateBuffer((ReadOnlySpan<UnderlayVertex>)vertices, BindFlags.VertexBuffer), vertices.Length, page.View));
        }
    }

    /// The drawings' buffers, and the page textures not in `keep` (null: all of them).
    void ReleaseDrawings(IReadOnlySet<string>? keep)
    {
        foreach (var d in _drawings) d.Buffer.Dispose();
        _drawings.Clear();
        foreach (var key in _pages.Keys.Where(k => keep is null || !keep.Contains(k)).ToList())
        {
            _pages[key].View.Dispose();
            _pages[key].Texture.Dispose();
            _pages.Remove(key);
        }
    }

    /// Development: count invalid (NaN/inf) pixels in the light buffer → %TEMP%\gpu-stats.txt.
    unsafe void CheckInvalid()
    {
        NanCheckAt = DateTime.UtcNow;
        var t = hdr!;
        using var staging = Device.CreateTexture2D(new Texture2DDescription(Format.R16G16B16A16_Float, (uint)t.Width, (uint)t.Height, 1, 1,
            BindFlags.None, ResourceUsage.Staging, CpuAccessFlags.Read));
        Context.CopyResource(staging, t.Texture);
        var m = Context.Map(staging, 0, MapMode.Read, Vortice.Direct3D11.MapFlags.None);
        int bad = 0, neg = 0;
        for (var y = 0; y < t.Height; y++)
        {
            var row = new ReadOnlySpan<ushort>((byte*)m.DataPointer + y * m.RowPitch, t.Width * 4);
            var (b, n) = CountInvalid(row);
            bad += b; neg += n;
        }
        Context.Unmap(staging, 0);
        AppendStats($"invalid values in the light buffer: {bad} negative: {neg}\n");
    }

    /// The finished frame as BGRA pixels (the self-test's PNG): `texture` must be B8G8R8A8.
    public unsafe byte[] ReadPixels(ID3D11Texture2D texture, int width, int height)
    {
        using var staging = Device.CreateTexture2D(new Texture2DDescription(texture.Description.Format, (uint)width, (uint)height, 1, 1,
            BindFlags.None, ResourceUsage.Staging, CpuAccessFlags.Read));
        Context.CopyResource(staging, texture);
        var m = Context.Map(staging, 0, MapMode.Read, Vortice.Direct3D11.MapFlags.None);
        var result = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
            Marshal.Copy((IntPtr)((byte*)m.DataPointer + y * m.RowPitch), result, y * width * 4, width * 4);
        Context.Unmap(staging, 0);
        return result;
    }
}
