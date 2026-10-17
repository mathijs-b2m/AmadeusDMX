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

struct BeamInstance { float4 apexLen; float4 dirRadius; float4 colorIntensity; float4 extra; };  // extra.x = lens radius
struct SpriteInstance { float4 centerSize; float4 colorIntensity; float4 extra; };              // extra.x = hardness
struct DecalInstance { float4 centerRadius; float4 normal; float4 colorIntensity; };
struct LineInstance { float4 p0Width; float4 p1; float4 colorIntensity; };

SamplerState smp : register(s0);

static const float2 QUAD[6] = { float2(-1, -1), float2(1, -1), float2(1, 1), float2(-1, -1), float2(1, 1), float2(-1, 1) };

float4 project(float3 world) { return mul(viewProj, float4(world, 1)); }

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
