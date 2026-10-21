// Where a gobo beam lands on the floor, the walls and the ceiling: the gobo's picture, projected.
#include "Common.hlsli"

StructuredBuffer<GoboDecalInstance> goboDecals : register(t0);
Texture2DArray<float4> goboPictures : register(t1);

GoboOut gobo_decal_vertex(uint vid : SV_VertexID, uint iid : SV_InstanceID)
{
    GoboDecalInstance g = goboDecals[iid];
    float3 n = normalize(g.normal.xyz);
    float3 side = abs(n.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 a = normalize(cross(n, side)), b = cross(n, a);
    float2 q = QUAD[vid];
    GoboOut o;
    o.world = g.centerRadius.xyz + n * 0.014 + (a * q.x + b * q.y) * g.centerRadius.w * g.normal.w;
    o.pos = project(o.world);
    o.iid = iid;
    return o;
}

float4 gobo_decal_fragment(GoboOut i) : SV_Target
{
    GoboDecalInstance g = goboDecals[i.iid];
    float3 A = g.apexLen.xyz, d = normalize(g.dirK.xyz + float3(0, 0, 1e-7));
    float3 bu = beam_axis(g.axis.xyz, d), bv = cross(d, bu);
    float a = max(dot(i.world - A, d), 1e-3);
    float3 rad = i.world - A - d * a;
    float2 q = float2(dot(rad, bu), dot(rad, bv)) / (g.wheel.w + g.dirK.w * a);
    // sharp where the picture is big on screen, blurred (a lower mip) where it is small
    float lod = log2(max(max(length(ddx(q)), length(ddy(q))) * 64.0, 1e-4));
    if (dot(q, q) >= 1.0) discard;
    float3 m = gobo_at(goboPictures, q, g.wheel, g.axis.w, max(lod, 0.0));
    return float4(clean(g.colorIntensity.rgb * m * g.colorIntensity.a), 0);
}
