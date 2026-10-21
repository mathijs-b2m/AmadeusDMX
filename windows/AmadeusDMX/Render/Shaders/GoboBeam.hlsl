// Gobo beams: the pattern in the haze. A gobo beam is a volume: the view ray is marched through the cone (closed at
// its end, StageRenderer.CappedConeVertices), the gobo picture is its cross-section at every distance.
#include "Common.hlsli"

struct ConeIn { float3 local : POSITION; };   // x = cos, y = sin, z = 0 (lens) .. 1 (end)

StructuredBuffer<GoboBeamInstance> goboBeams : register(t0);
Texture2DArray<float4> goboPictures : register(t1);

GoboOut gobo_beam_vertex(ConeIn i, uint iid : SV_InstanceID)
{
    GoboBeamInstance b = goboBeams[iid];
    float3 d = normalize(b.dirRadius.xyz + float3(0, 0, 1e-7));
    float3 bu = beam_axis(b.axis.xyz, d), bv = cross(d, bu);
    float r = lerp(b.wheel.w, b.dirRadius.w, i.local.z);
    GoboOut o;
    o.world = b.apexLen.xyz + d * (i.local.z * b.apexLen.w) + (bu * i.local.x + bv * i.local.y) * r;
    o.pos = project(o.world);
    o.iid = iid;
    return o;
}

float4 gobo_beam_fragment(GoboOut i) : SV_Target
{
    GoboBeamInstance b = goboBeams[i.iid];
    // how much of the world one pixel covers per metre of distance (for the picture's detail, below)
    float pixel = length(fwidth(i.world)) / max(distance(i.world, camPos.xyz), 0.1);
    float3 A = b.apexLen.xyz, d = normalize(b.dirRadius.xyz + float3(0, 0, 1e-7));
    float len = max(b.apexLen.w, 1e-3), R = b.dirRadius.w, r0 = b.wheel.w;
    float k = max((R - r0) / len, 1e-4);   // the radius grows this much per metre
    float3 bu = beam_axis(b.axis.xyz, d), bv = cross(d, bu);
    float3 C = camPos.xyz;
    float far = distance(i.world, C);
    float3 v = (i.world - C) / max(far, 1e-5);
    // this fragment's face: the cone's side (outward normal) or its end cap
    float aP = dot(i.world - A, d);
    float3 radP = i.world - A - d * aP;
    float3 n = d;
    if (!(aP > len * 0.999)) n = normalize(normalize(radP + float3(1e-6, 0, 0)) - d * k);
    bool facing = dot(n, v) < 0.0;
    float ca = dot(C - A, d);
    bool inside = ca > 0.0 && ca < len && length(C - A - d * ca) < r0 + k * ca;
    // seen from inside: from the eye to the far side; from outside: from the near side on through the beam
    if (inside == facing) discard;
    float s0 = inside ? 0.0 : far, s1 = far;
    float dv = dot(v, d);
    if (!inside)
    {
        // where the view ray leaves the cone
        float3 o = C - (A - d * (r0 / k));
        float kk = 1.0 + k * k, dO = dot(o, d);
        float qa = 1.0 - kk * dv * dv, qb = 2.0 * (dot(o, v) - kk * dO * dv), qc = dot(o, o) - kk * dO * dO;
        float disc = qb * qb - 4.0 * qa * qc;
        s1 = far + 4.0 * R;
        if (disc > 0.0 && abs(qa) > 1e-6)
        {
            float sq = sqrt(disc);
            float x1 = (-qb - sq) / (2.0 * qa), x2 = (-qb + sq) / (2.0 * qa);
            // the entry is this fragment (one root, give or take rounding): the exit is the farther root, if it is on
            // the beam's side of the apex and really beyond the entry
            float exitAt = -1.0;
            if (dO + x1 * dv > 0.0) exitAt = max(exitAt, x1);
            if (dO + x2 * dv > 0.0) exitAt = max(exitAt, x2);
            if (exitAt > far + 0.02 * r0) s1 = exitAt;
        }
        if (abs(dv) > 1e-5)    // or through the end, or the lens
        {
            float sEnd = ((dv > 0.0 ? len : 0.0) - ca) / dv;
            if (sEnd > far) s1 = min(s1, sEnd);
        }
    }
    if (v.z < -1e-4) s1 = min(s1, -C.z / v.z);   // the floor
    if (s1 <= s0) discard;
    // steps: enough to cross the pattern a few times per beam width along the way (a view along a thin beam crosses
    // many shafts), at least 16, at most 64
    float mid = dot(C + v * (0.5 * (s0 + s1)) - A, d);
    float width = r0 + k * clamp(mid, 0.0, len);
    int N = int(clamp((s1 - s0) / (0.35 * width), 16.0, 64.0));
    float ds = (s1 - s0) / float(N);
    float jitter = frac(52.9829189 * frac(dot(i.pos.xy, float2(0.06711056, 0.00583715))));   // interleaved gradient noise
    float3 acc = float3(0, 0, 0);
    [loop]
    for (int j = 0; j < N; j++)
    {
        float s = s0 + (float(j) + jitter) * ds;
        float3 X = C + v * s;
        float a = dot(X - A, d);
        if (a < 0.0 || a > len) continue;
        float3 rad = X - A - d * a;
        float rr = r0 + k * a;
        float2 q = float2(dot(rad, bu), dot(rad, bv)) / rr;
        if (dot(q, q) >= 1.0) continue;
        float t = a / len;
        float fade = pow(1.0 - t, 1.6) * (0.4 + 0.6 * exp(-t * 5.0));
        // a beam right next to (or through) the camera: fade its haze, it would white out the whole picture
        float nearK = smoothstep(0.4, 2.5, s);
        // the picture as fine as a pixel there can show: near the lens it shrinks to a few pixels, blurred, not noise
        float lod = clamp(log2(64.0 * pixel * s / rr) + 1.0, 1.0, 6.0);
        acc += gobo_at(goboPictures, q, b.wheel, b.axis.w, lod) * (fade * nearK / rr);
    }
    // an open beam: as bright through its middle as the plain beams (their two faces), the pattern cuts it up
    float3 c = b.colorIntensity.rgb * acc * ds * b.colorIntensity.a * params.y;
    return float4(clean(c), 0);
}
