// The spots where beams land on the floor, the walls and the ceiling (decals).
#include "Common.hlsli"

StructuredBuffer<DecalInstance> decalInstances : register(t0);

QuadOut decal_vertex(uint vid : SV_VertexID, uint iid : SV_InstanceID)
{
    DecalInstance s = decalInstances[iid];
    float3 n = normalize(s.normal.xyz);
    float3 side = abs(n.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 a = normalize(cross(n, side)), b = cross(n, a);
    float2 q = QUAD[vid];
    float3 w = s.centerRadius.xyz + n * 0.012 + (a * q.x + b * q.y) * s.centerRadius.w * s.normal.w;
    QuadOut o;
    o.pos = project(w);
    o.uv = q; o.color = s.colorIntensity; o.hard = 0;
    return o;
}

float4 decal_fragment(QuadOut i) : SV_Target
{
    float r = length(i.uv);
    if (r > 1.0) discard;
    float spot = (1.0 - smoothstep(0.55, 1.0, r)) * 0.7 + exp(-r * r * 6.0) * 0.6;
    return float4(i.color.rgb * spot * i.color.a, 0);
}
