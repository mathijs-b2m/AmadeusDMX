// Laser beams (and the rig editor's zone edges): thin camera-facing ribbons.
#include "Common.hlsli"

struct LineOut { float4 pos : SV_Position; float across : TEXCOORD0; float along : TEXCOORD1; float4 color : COLOR0; };

StructuredBuffer<LineInstance> lineInstances : register(t0);

LineOut line_vertex(uint vid : SV_VertexID, uint iid : SV_InstanceID)
{
    LineInstance s = lineInstances[iid];
    float2 q = QUAD[vid];
    float t = q.x * 0.5 + 0.5;
    float3 p = lerp(s.p0Width.xyz, s.p1.xyz, t);
    float3 seg = s.p1.xyz - s.p0Width.xyz;
    float3 dir = seg / max(length(seg), 1e-6);
    float3 toCam = normalize(camPos.xyz - p + float3(0, 0, 1e-4));
    float3 sc = cross(dir, toCam);
    float3 side = length(sc) > 1e-5 ? normalize(sc) : float3(1, 0, 0);   // pointing at the camera: any side
    // keep a minimum on-screen width far away (otherwise the beam flickers out)
    float dist = length(camPos.xyz - p);
    float w = max(s.p0Width.w, dist * 0.0012);
    LineOut o;
    o.pos = project(p + side * q.y * w);
    o.across = q.y; o.along = t;
    o.color = s.colorIntensity;
    return o;
}

float4 line_fragment(LineOut i) : SV_Target
{
    float g = exp(-i.across * i.across * 5.0);
    float fade = 1.0 - 0.55 * i.along;
    return float4(i.color.rgb * g * fade * i.color.a, 0);
}
