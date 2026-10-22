// The rig editor's drawings under the rig: an imported plan's page lying on the stage floor, semi-transparent,
// under the trusses and fixtures (drawn after the solid scenery, depth tested, not written).
#include "Common.hlsli"

struct UnderlayIn { float3 pos : POSITION; float2 uv : TEXCOORD0; float alpha : TEXCOORD1; };
struct UnderlayOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; float alpha : TEXCOORD1; };

Texture2D<float4> pageTex : register(t0);

UnderlayOut underlay_vertex(UnderlayIn i)
{
    UnderlayOut o; o.pos = project(i.pos); o.uv = i.uv; o.alpha = i.alpha; return o;
}

float4 underlay_fragment(UnderlayOut i) : SV_Target
{
    // the page (premultiplied) as paper under the work light: readable on the dark floor, never glaring (no bloom)
    float4 page = pageTex.Sample(smp, i.uv);
    float light = 0.1 + 0.15 * ambient.w;
    return float4(page.rgb * light * i.alpha, page.a * i.alpha);   // premultiplied alpha over the scene
}
