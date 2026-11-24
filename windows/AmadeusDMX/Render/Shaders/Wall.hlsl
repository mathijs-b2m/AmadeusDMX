// The LED wall: its picture comes ready (WallSource: the drawing or the psychedelic shader, at the wall's level, in
// WallSource.hlsl), here only put on the stage's wall with its LED grid.
#include "Common.hlsli"

struct WallIn { float3 pos : POSITION; float2 uv : TEXCOORD0; };
struct WallOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; };

Texture2D<float4> wallTex : register(t0);

WallOut wall_vertex(WallIn i)
{
    WallOut o; o.pos = project(i.pos); o.uv = i.uv; return o;
}

float4 wall_fragment(WallOut i) : SV_Target
{
    // mipmapped (the sampler's MinMagMipLinear): the 1280x720 picture seen small doesn't shimmer
    float3 c = wallTex.Sample(smp, i.uv).rgb * wallOn.x;
    // LED pixel grid, faintly visible up close
    float2 px = frac(i.uv * float2(192.0, 108.0));
    float grid = 0.85 + 0.15 * smoothstep(0.0, 0.15, min(min(px.x, 1.0 - px.x), min(px.y, 1.0 - px.y)));
    return float4(c * 1.6 * grid + float3(0.004, 0.004, 0.004), 1);
}
