// The solid scenery (floor, walls, stage, trusses, the fixtures' bodies) and the rig editor's translucent zones.
#include "Common.hlsli"

struct SolidIn { float3 pos : POSITION; float3 normal : NORMAL; float4 color : COLOR0; };
struct SolidOut { float4 pos : SV_Position; float3 world : TEXCOORD0; float3 normal : TEXCOORD1; float4 color : COLOR0; };

SolidOut solid_vertex(SolidIn i)
{
    SolidOut o;
    o.pos = project(i.pos);
    o.world = i.pos; o.normal = i.normal; o.color = i.color;
    return o;
}

float4 solid_fragment(SolidOut i) : SV_Target
{
    float3 n = normalize(i.normal);
    float key = max(0.0, dot(n, normalize(float3(0.3, 0.6, 1.0))));
    float3 base = i.color.rgb;
    float3 c = base * (0.04 + 0.22 * key);   // a dark venue: the lights do the lighting
    // the rig lights the room a little: surfaces facing up and towards the audience catch most of it
    c += base * ambient.rgb * params.w * 1.6 * (0.5 + 0.5 * max(n.z, 0.0));
    c += base * ambient.w * (0.25 + 0.75 * key);  // work light: see the rig when nothing is lit
    c += i.color.a * base;  // emissive (a = how much the surface glows on its own)
    // subtle sheen on the floor near the viewer direction
    float3 v = normalize(camPos.xyz - i.world);
    if (n.z > 0.9) c += ambient.rgb * 0.05 * pow(1.0 - abs(dot(v, n)), 4.0);
    return float4(c, 1);
}

// ---------------------------------------------------------------- zones (translucent, rig editor)
float4 zone_fragment(SolidOut i) : SV_Target
{
    // a faint fill with diagonal hatching, so a zone reads as "not a real surface"
    float h = frac((i.world.x + i.world.y + i.world.z) * 2.5);
    float a = i.color.a * (0.75 + 0.25 * step(0.5, h));
    return float4(i.color.rgb * a, a);
}
