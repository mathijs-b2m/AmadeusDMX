// Where a gobo beam lands on the floor, the walls and the ceiling: the gobo's picture, projected.
#include "Common.hlsli"

Texture2DArray<float4> goboPictures : register(t1);

GoboDecalOut gobo_decal_vertex(uint vid : SV_VertexID, GoboDecalInstance g)
{
    float3 n = normalize(g.normal.xyz);
    float3 side = abs(n.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 a = normalize(cross(n, side)), b = cross(n, a);
    float2 q = QUAD[vid];
    GoboDecalOut o;
    o.world = g.centerRadius.xyz + n * 0.014 + (a * q.x + b * q.y) * g.centerRadius.w * g.normal.w;
    o.pos = project(o.world);
    o.colorIntensity = g.colorIntensity; o.apexLen = g.apexLen; o.dirK = g.dirK; o.wheel = g.wheel; o.axis = g.axis;
    return o;
}

float4 gobo_decal_fragment(GoboDecalOut g) : SV_Target
{
    GoboDecalOut i = g;
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
