// Camera-facing sprites: lenses, flares.
#include "Common.hlsli"

StructuredBuffer<SpriteInstance> spriteInstances : register(t0);

QuadOut sprite_vertex(uint vid : SV_VertexID, uint iid : SV_InstanceID)
{
    SpriteInstance s = spriteInstances[iid];
    float2 q = QUAD[vid];
    float3 w = s.centerSize.xyz + (camRight.xyz * q.x + camUp.xyz * q.y) * s.centerSize.w;
    QuadOut o;
    o.pos = project(w);
    o.uv = q; o.color = s.colorIntensity; o.hard = s.extra.x;
    return o;
}

float4 sprite_fragment(QuadOut i) : SV_Target
{
    float r = length(i.uv);
    if (r > 1.0) discard;
    float core = exp(-r * r * (8.0 + i.hard * 40.0));
    float halo = pow(saturate(1.0 - r), 2.0) * 0.35;
    float3 c = i.color.rgb * (core * 2.0 + halo) + float3(1.0, 1.0, 1.0) * core * i.hard * 0.8;
    return float4(c * i.color.a, 0);
}
