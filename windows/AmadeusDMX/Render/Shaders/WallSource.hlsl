// The LED wall's picture, once for the app (WallSource.cs; the Mac's WallShaders in WallSource.swift): the CPU's
// drawing or the psychedelic kaleidoscope, at the wall's level, into the picture every stage and the LED Wall Output
// read; and the output's own pass, the picture in the wall's rectangle under the brightness ceiling.
// Standalone (no Common.hlsli): Shader Model 4.0 like the stage's shaders.

cbuffer WallParams : register(b0)
{
    float4 info;        // x level, y psychedelic, z time, w aspect
    float4 bands;
    float4 pal[4];
};

cbuffer OutParams : register(b1)
{
    float4 out_info;    // x light 0..1, y time, z test card's moving bar on (1)
};

Texture2D<float4> tex : register(t0);
SamplerState smp : register(s0);

struct FSOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; };

FSOut wall_fs_vertex(uint vid : SV_VertexID)
{
    float2 p = float2((vid << 1) & 2, vid & 2);
    FSOut o; o.pos = float4(p * 2.0 - 1.0, 0, 1); o.uv = float2(p.x, 1.0 - p.y); return o;
}

float3 psychedelic(float2 uv, float t, float aspect)
{
    float2 p = (uv - 0.5) * float2(aspect, 1.0) * 2.0;   // round on a wall of any shape
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

// the picture as the wall shows it: the CPU's drawing or the psychedelic shader, at the wall's level (HDR: the
// stage's bloom sees the rings; the output clamps)
float4 wall_compose(FSOut i) : SV_Target
{
    // both branches evaluated (a vector ?: in SM4 isn't short-circuit); the picture has one level, no gradients needed
    float3 picture = tex.SampleLevel(smp, i.uv, 0).rgb;
    float3 c = info.y > 0.5 ? psychedelic(i.uv, info.z, info.w > 0.0 ? info.w : 16.0 / 9.0) : picture;
    return float4(c, 1);   // at full level: who shows it applies the wall's level (as light)
}

// the output: the picture in the wall's rectangle (the viewport), under the brightness ceiling
float4 wall_output(FSOut i) : SV_Target
{
    // out_info.x is a share of the wall's light (its level × the brightness ceiling × the fade): the picture is
    // sRGB-encoded, so it goes out as that share of light, not of the encoded value (18% of the value is 2% of the light)
    float k = pow(saturate(out_info.x), 1.0 / 2.2);
    float3 c = clamp(tex.SampleLevel(smp, i.uv, 0).rgb, 0.0, 1.0) * k;
    if (out_info.z > 0.5)   // the test card: a bar crossing every two seconds shows tearing and dropped frames
    {
        float x = frac(out_info.y * 0.5);
        if (abs(i.uv.x - x) < 0.006) c = float3(k, k, k);
    }
    return float4(c, 1);
}
