// The stage renderer's setup: pipelines and the beam cone mesh (mac/.../Render/StageRenderer+Setup.swift; the
// scenery and zones are built on the CPU in StageRenderer.State.cs and uploaded in StageRenderer.cs).
using System.Numerics;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Format = Vortice.DXGI.Format;

namespace AmadeusDMX;

public sealed partial class StageRenderer
{
    void BuildPipelines()
    {
        additive = Device.CreateBlendState(new BlendDescription(Blend.One, Blend.One, Blend.One, Blend.One));
        // zones: premultiplied alpha over the scene
        premultiplied = Device.CreateBlendState(new BlendDescription(Blend.One, Blend.InverseSourceAlpha, Blend.One, Blend.InverseSourceAlpha));

        Pipeline Pipe(string file, string v, string f, InputElementDescription[]? layout, ID3D11BlendState? blend)
        {
            var vs = ShaderLibrary.Bytecode(file, v, "vs_5_0");
            var ps = ShaderLibrary.Bytecode(file, f, "ps_5_0");
            return new Pipeline(Device.CreateVertexShader(vs), Device.CreatePixelShader(ps),
                layout is null ? null : Device.CreateInputLayout(layout, vs), blend);
        }
        InputElementDescription[] solidVD =
        [
            new("POSITION", 0, Format.R32G32B32_Float, 0, 0),
            new("NORMAL", 0, Format.R32G32B32_Float, SolidVertex.NormalOffset, 0),
            new("COLOR", 0, Format.R32G32B32A32_Float, SolidVertex.ColorOffset, 0),
        ];
        InputElementDescription[] coneVD = [new("POSITION", 0, Format.R32G32B32_Float, 0, 0)];
        InputElementDescription[] wallVD =
        [
            new("POSITION", 0, Format.R32G32B32_Float, 0, 0),
            new("TEXCOORD", 0, Format.R32G32_Float, WallVertex.UvOffset, 0),
        ];

        solidPipe = Pipe("Solid.hlsl", "solid_vertex", "solid_fragment", solidVD, null);
        wallPipe = Pipe("Wall.hlsl", "wall_vertex", "wall_fragment", wallVD, null);
        beamPipe = Pipe("Beam.hlsl", "beam_vertex", "beam_fragment", coneVD, additive);
        spritePipe = Pipe("Sprite.hlsl", "sprite_vertex", "sprite_fragment", null, additive);
        decalPipe = Pipe("Decal.hlsl", "decal_vertex", "decal_fragment", null, additive);
        linePipe = Pipe("Line.hlsl", "line_vertex", "line_fragment", null, additive);
        compositePipe = Pipe("Post.hlsl", "fullscreen_vertex", "composite_fragment", null, null);
        downsamplePipe = Pipe("Post.hlsl", "fullscreen_vertex", "downsample_fragment", null, null);
        blurPipe = Pipe("Post.hlsl", "fullscreen_vertex", "blur_fragment", null, null);
        zonePipe = Pipe("Solid.hlsl", "solid_vertex", "zone_fragment", solidVD, premultiplied);

        solidDepth = Device.CreateDepthStencilState(new DepthStencilDescription(true, DepthWriteMask.All, ComparisonFunction.Less));
        lightDepth = Device.CreateDepthStencilState(new DepthStencilDescription(true, DepthWriteMask.Zero, ComparisonFunction.Less));
        rasterizer = Device.CreateRasterizerState(new RasterizerDescription(CullMode.None, FillMode.Solid));
        sampler = Device.CreateSamplerState(new SamplerDescription
        {
            Filter = Filter.MinMagMipLinear,
            AddressU = TextureAddressMode.Clamp, AddressV = TextureAddressMode.Clamp, AddressW = TextureAddressMode.Clamp,
            ComparisonFunc = ComparisonFunction.Never, MinLOD = 0, MaxLOD = float.MaxValue,
        });
    }

    /// A unit cone (open), x/y = direction around the axis, z = 0 (lens) … 1 (end), in rings for a smooth fade.
    public static Vector3[] ConeVertices()
    {
        const int seg = 40, rings = 10;
        var v = new List<Vector3>(seg * rings * 6);
        for (var r = 0; r < rings; r++)
        {
            float z0 = (float)r / rings, z1 = (float)(r + 1) / rings;
            for (var s = 0; s < seg; s++)
            {
                float a0 = (float)s / seg * 2 * MathF.PI, a1 = (float)(s + 1) / seg * 2 * MathF.PI;
                Vector3 p00 = new(MathF.Cos(a0), MathF.Sin(a0), z0), p10 = new(MathF.Cos(a1), MathF.Sin(a1), z0);
                Vector3 p01 = new(MathF.Cos(a0), MathF.Sin(a0), z1), p11 = new(MathF.Cos(a1), MathF.Sin(a1), z1);
                v.AddRange([p00, p10, p11, p00, p11, p01]);
            }
        }
        return [.. v];
    }

    void BuildCone()
    {
        var v = ConeVertices();
        coneCount = v.Length;
        coneBuffer = Device.CreateBuffer((ReadOnlySpan<Vector3>)v, BindFlags.VertexBuffer);
    }
}
