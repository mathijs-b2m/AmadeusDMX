// HLSL (Shader Model 5.0, D3DCompiler) port of mac/Sources/AmadeusDMX/Render/Shaders.swift: what every stage
// shader shares. ShaderLibrary.cs pastes this file in place of `#include "Common.hlsli"`.
//
// World: x across the stage, y towards the audience, z up (metres), like the engine.
// Everything renders into an HDR target; light (beams, lasers, spots, flares, the LED wall) adds up there,
// then bloom and an ACES tone curve make the final picture.
//
// Bindings (Metal → Direct3D 11):
//   Uniforms        buffer(1)  → cbuffer b0 (vertex and pixel)
//   WallParams      buffer(3)  → cbuffer b1 (pixel)
//   BlurParams      (MPS blur) → cbuffer b2 (pixel)
//   instances       buffer(2)  → StructuredBuffer t0 (vertex)
//   textures        texture(n) → Texture2D tn (pixel), sampler s0: linear, clamp to edge
//   gobo beams and decals read their instances in the pixel shader too (StructuredBuffer t0 in both stages), the
//   gobo pictures are a Texture2DArray at t1 (Metal's texture(0))
// Matrices are column_major (the C# side stores Swift's column-major float4x4), multiplied mul(M, v) like Metal's M * v.
// Keep the structs in step with Render/GPUTypes.cs (RenderTests compares the sizes).

cbuffer Uniforms : register(b0)
{
    column_major float4x4 viewProj;
    float4 camPos;      // xyz
    float4 camRight;    // xyz
    float4 camUp;       // xyz
    float4 params;      // x time, y haze, z exposure, w room bounce strength
    float4 ambient;     // rgb: the colour the rig throws around the room; w: work light (rig preview)
};

cbuffer WallParams : register(b1)
{
    float4 info;        // x level, y psychedelic, z time
    float4 bands;
    float4 pal[4];
};

cbuffer BlurParams : register(b2)
{
    float4 blurStep;    // xy one texel along the pass's direction (uv), z sigma (texels)
};

struct BeamInstance { float4 apexLen; float4 dirRadius; float4 colorIntensity; float4 extra; };  // extra.x = lens radius, y = reference radius (BeamLight)
struct SpriteInstance { float4 centerSize; float4 colorIntensity; float4 extra; };              // extra.x = hardness
struct DecalInstance { float4 centerRadius; float4 normal; float4 colorIntensity; };
struct LineInstance { float4 p0Width; float4 p1; float4 colorIntensity; };
// gobos (GoboBeam.hlsl, GoboDecal.hlsl). wheel: x the picture (texture slice; -1: the open hole), y the next one on the
// wheel, z how far the wheel has turned towards it (0..1), w the lens radius; axis: xyz the picture's x direction
// across the beam, w its rotation
struct GoboBeamInstance { float4 apexLen; float4 dirRadius; float4 colorIntensity; float4 wheel; float4 axis; };
struct GoboDecalInstance { float4 centerRadius; float4 normal; float4 colorIntensity; float4 apexLen; float4 dirK; float4 wheel; float4 axis; };

SamplerState smp : register(s0);

static const float2 QUAD[6] = { float2(-1, -1), float2(1, -1), float2(1, 1), float2(-1, -1), float2(1, 1), float2(-1, 1) };

float4 project(float3 world) { return mul(viewProj, float4(world, 1)); }

// invalid values (NaN, inf) become 0: one bad pixel would otherwise show black and the bloom would smear it
// (by their bits: the compiler may fold isnan() away)
float3 clean(float3 c)
{
    bool3 bad = (asuint(c) & 0x7F800000u) == 0x7F800000u;
    return bad ? float3(0, 0, 0) : c;
}

struct QuadOut
{
    float4 pos : SV_Position;
    float2 uv : TEXCOORD0;
    float4 color : COLOR0;
    float hard : TEXCOORD1;
};

struct FSOut
{
    float4 pos : SV_Position;
    float2 uv : TEXCOORD0;
};

// ---------------------------------------------------------------- gobos (GoboBeam.hlsl, GoboDecal.hlsl)
// Every hole of a gobo throws its own shaft of light: the gobo picture (turned in its slot, sliding on its wheel) is
// the beam's cross-section at every distance. The pictures are the slices of a Texture2DArray, light where light
// passes.

static const float WHEEL_PITCH = 2.3;   // from one gobo to the next on the wheel, in gobo radii

float3 gobo_light(Texture2DArray<float4> pics, float2 p, float slot, float lod)
{
    float r = length(p);
    if (r >= 1.0) return float3(0, 0, 0);
    float edge = 1.0 - smoothstep(0.94, 1.0, r);
    if (slot < 0.0) return float3(edge, edge, edge);
    return pics.SampleLevel(smp, float3(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5, floor(slot)), lod).rgb * edge;
}

// the light the gobo lets through at q (the aperture, radius 1): the picture in it and the next one sliding in
float3 gobo_at(Texture2DArray<float4> pics, float2 q, float4 wheel, float rot, float lod)
{
    float c = cos(rot), s = sin(rot);
    float off = wheel.z * WHEEL_PITCH;
    float2 pa = q + float2(off, 0), pb = q + float2(off - WHEEL_PITCH, 0);
    pa = float2(c * pa.x + s * pa.y, -s * pa.x + c * pa.y);
    pb = float2(c * pb.x + s * pb.y, -s * pb.x + c * pb.y);
    float3 next = float3(0, 0, 0);
    if (wheel.z > 0.0) next = gobo_light(pics, pb, wheel.y, lod);
    return gobo_light(pics, pa, wheel.x, lod) + next;
}

float3 beam_axis(float3 axis, float3 d) { return normalize(axis - d * dot(axis, d) + float3(1e-6, 0, 0)); }

struct GoboOut
{
    float4 pos : SV_Position;
    float3 world : TEXCOORD0;
    nointerpolation uint iid : TEXCOORD1;
};
