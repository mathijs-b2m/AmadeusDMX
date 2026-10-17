// The final picture: bloom (downsample + Gaussian blur, Metal's MPS kernels) and the ACES tone curve.
#include "Common.hlsli"

Texture2D<float4> hdr : register(t0);
Texture2D<float4> bloomA : register(t1);
Texture2D<float4> bloomB : register(t2);

FSOut fullscreen_vertex(uint vid : SV_VertexID)
{
    float2 p = float2((vid << 1) & 2, vid & 2);
    FSOut o; o.pos = float4(p * 2.0 - 1.0, 0, 1); o.uv = float2(p.x, 1.0 - p.y); return o;
}

// invalid values (NaN, inf) become 0: one bad pixel would otherwise show black and the bloom would smear it
// (by their bits: the compiler may fold isnan() away)
float3 clean(float3 c)
{
    bool3 bad = (asuint(c) & 0x7F800000u) == 0x7F800000u;
    return bad ? float3(0, 0, 0) : c;
}

float3 aces(float3 x)
{
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

float4 composite_fragment(FSOut i) : SV_Target
{
    float3 c = clean(hdr.Sample(smp, i.uv).rgb);
    // bloom only from what is really bright (a soft knee), so lenses glow without hiding the rig in halos
    float3 ba = clean(bloomA.Sample(smp, i.uv).rgb), bb = clean(bloomB.Sample(smp, i.uv).rgb);
    ba *= saturate((max(ba.r, max(ba.g, ba.b)) - 0.35) / 1.2);
    bb *= saturate((max(bb.r, max(bb.g, bb.b)) - 0.35) / 1.2);
    c += ba * 0.45 + bb * 0.3;
    c *= params.z;
    // a soft vignette, like a camera
    float2 q = i.uv - 0.5;
    c *= 1.0 - dot(q, q) * 0.6;
    return float4(aces(c), 1);
}

// MPSImageBilinearScale: the light buffer, sampled bilinearly into a smaller target
float4 downsample_fragment(FSOut i) : SV_Target
{
    return float4(hdr.SampleLevel(smp, i.uv, 0).rgb, 1);
}

// MPSImageGaussianBlur, one direction per pass (horizontal, then vertical): weights out to 3 sigma
float4 blur_fragment(FSOut i) : SV_Target
{
    float sigma = max(blurStep.z, 0.5);
    int r = (int)ceil(sigma * 3.0);
    float3 sum = float3(0, 0, 0);
    float wsum = 0;
    [loop]
    for (int k = -r; k <= r; k++)
    {
        float w = exp(-(float)(k * k) / (2.0 * sigma * sigma));
        sum += hdr.SampleLevel(smp, i.uv + blurStep.xy * (float)k, 0).rgb * w;
        wsum += w;
    }
    return float4(sum / wsum, 1);
}
