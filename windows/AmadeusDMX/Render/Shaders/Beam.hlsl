// Volumetric beams: open cones from the lens, lit by the haze.
#include "Common.hlsli"

struct ConeIn { float3 local : POSITION; };   // x = cos, y = sin, z = 0 (lens) .. 1 (end)
struct BeamOut { float4 pos : SV_Position; float3 world : TEXCOORD0; float3 normal : TEXCOORD1; float along : TEXCOORD2; float4 color : COLOR0; };

StructuredBuffer<BeamInstance> beamInstances : register(t0);

BeamOut beam_vertex(ConeIn i, uint iid : SV_InstanceID)
{
    BeamInstance b = beamInstances[iid];
    float3 d = normalize(b.dirRadius.xyz + float3(0, 0, 1e-7));
    float3 side = abs(d.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 bu = normalize(cross(d, side)), bv = cross(d, bu);
    float len = b.apexLen.w, R = b.dirRadius.w, r0 = b.extra.x;
    float r = lerp(r0, R, i.local.z);
    float3 radial = bu * i.local.x + bv * i.local.y;
    BeamOut o;
    o.world = b.apexLen.xyz + d * (i.local.z * len) + radial * r;
    o.normal = normalize(radial * len - d * (R - r0));
    o.pos = project(o.world);
    o.along = i.local.z;
    o.color = b.colorIntensity;
    return o;
}

float4 beam_fragment(BeamOut i) : SV_Target
{
    float3 v = normalize(camPos.xyz - i.world);
    // light scattered by the haze: strongest where the view crosses the most beam (facing the axis)
    float facing = saturate(abs(dot(normalize(i.normal + float3(1e-6, 1e-6, 1e-6)), v)));
    float along = saturate(i.along);       // can overshoot 1 by a hair: pow() of a negative number is NaN
    float body = pow(facing, 2.2);          // soft edges: a cylinder of haze, not a slab
    float fade = pow(1.0 - along, 1.6) * (0.4 + 0.6 * exp(-along * 5.0));
    // a beam right next to (or through) the camera: fade its haze, it would white out the whole picture
    float nearK = smoothstep(0.4, 2.5, distance(camPos.xyz, i.world));
    float a = i.color.a * body * fade * nearK * params.y;
    return float4(i.color.rgb * a, 0);
}
