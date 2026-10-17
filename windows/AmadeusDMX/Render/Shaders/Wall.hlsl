// The LED wall: the picture WallRenderer draws, or the psychedelic kaleidoscope drawn here.
#include "Common.hlsli"

struct WallIn { float3 pos : POSITION; float2 uv : TEXCOORD0; };
struct WallOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; };

Texture2D<float4> wallTex : register(t0);

WallOut wall_vertex(WallIn i)
{
    WallOut o; o.pos = project(i.pos); o.uv = i.uv; return o;
}

float3 psychedelic(float2 uv, float t)
{
    float2 p = (uv - 0.5) * float2(16.0 / 9.0, 1.0) * 2.0;
    // kaleidoscope: fold the angle into 6 slices, then a flowing plasma that the bass pushes outwards
    float a = atan2(p.y, p.x), r = length(p);
    float k = 3.14159 / 3.0;
    a = abs(fmod(a + t * 0.15 + 100.0 * k, 2.0 * k) - k);
    float2 q = float2(cos(a), sin(a)) * r;
    float bass = bands.x, mid = bands.y, hi = bands.z;
    float v = sin(q.x * 6.0 + t * 1.3) + sin(q.y * 7.0 - t * 0.9 + bass * 3.0)
            + sin((q.x + q.y) * 5.0 + t * 0.7) + sin(r * (10.0 + mid * 8.0) - t * 3.0 - bass * 6.0);
    float s = v * 0.25 + 0.5;
    float3 c0 = pal[0].rgb, c1 = pal[1].rgb, c2 = pal[2].rgb, c3 = pal[3].rgb;
    float3 c = s < 0.33 ? lerp(c0, c1, s / 0.33) : (s < 0.66 ? lerp(c1, c2, (s - 0.33) / 0.33) : lerp(c2, c3, (s - 0.66) / 0.34));
    float rings = smoothstep(0.85, 1.0, sin(r * 18.0 - t * 5.0 - bass * 8.0) * 0.5 + 0.5);
    c += rings * (0.4 + hi);
    c *= 0.55 + 0.6 * bass + 0.25 * smoothstep(1.2, 0.0, r);
    return c;
}

float4 wall_fragment(WallOut i) : SV_Target
{
    // both branches evaluated (a vector ?: in SM5 isn't short-circuit): sampling outside the branch keeps gradients valid
    float3 picture = wallTex.Sample(smp, i.uv).rgb;
    float3 c = info.y > 0.5 ? psychedelic(i.uv, info.z) : picture;
    // LED pixel grid, faintly visible up close
    float2 px = frac(i.uv * float2(192.0, 108.0));
    float grid = 0.85 + 0.15 * smoothstep(0.0, 0.15, min(min(px.x, 1.0 - px.x), min(px.y, 1.0 - px.y)));
    return float4(c * info.x * 1.6 * grid + float3(0.004, 0.004, 0.004), 1);
}
