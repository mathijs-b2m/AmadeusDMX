// Metal shaders for the stage, compiled at runtime (SwiftPM doesn't build .metal files).
//
// World: x across the stage, y towards the audience, z up (metres), like the engine.
// Everything renders into an HDR target; light (beams, lasers, spots, flares, the LED wall) adds up there,
// then bloom and an ACES tone curve make the final picture.
enum Shaders {
    static let source = #"""
#include <metal_stdlib>
using namespace metal;

struct Uniforms {
    float4x4 viewProj;
    float4 camPos;      // xyz
    float4 camRight;    // xyz
    float4 camUp;       // xyz
    float4 params;      // x time, y haze, z exposure, w room bounce strength
    float4 ambient;     // rgb: the colour the rig throws around the room; w: work light (rig preview)
};

// invalid values (NaN, inf) become 0: one bad pixel would otherwise show black and the bloom would smear it
float3 clean(float3 c) { return select(c, float3(0), isnan(c) || isinf(c)); }

// ---------------------------------------------------------------- solid scenery
struct SolidIn { float3 pos [[attribute(0)]]; float3 normal [[attribute(1)]]; float4 color [[attribute(2)]]; };
struct SolidOut { float4 pos [[position]]; float3 world; float3 normal; float4 color; };

vertex SolidOut solid_vertex(SolidIn in [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    SolidOut o;
    o.pos = u.viewProj * float4(in.pos, 1);
    o.world = in.pos; o.normal = in.normal; o.color = in.color;
    return o;
}

fragment float4 solid_fragment(SolidOut in [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    float3 n = normalize(in.normal);
    float key = max(0.0, dot(n, normalize(float3(0.3, 0.6, 1.0))));
    float3 base = in.color.rgb;
    float3 c = base * (0.04 + 0.22 * key);   // a dark venue: the lights do the lighting
    // the rig lights the room a little: surfaces facing up and towards the audience catch most of it
    c += base * u.ambient.rgb * u.params.w * 1.6 * (0.5 + 0.5 * max(n.z, 0.0));
    c += base * u.ambient.w * (0.25 + 0.75 * key);  // work light: see the rig when nothing is lit
    c += in.color.a * base;  // emissive (a = how much the surface glows on its own)
    // subtle sheen on the floor near the viewer direction
    float3 v = normalize(u.camPos.xyz - in.world);
    if (n.z > 0.9) c += u.ambient.rgb * 0.05 * pow(1.0 - abs(dot(v, n)), 4.0);
    return float4(c, 1);
}

// ---------------------------------------------------------------- zones (translucent, rig editor)
fragment float4 zone_fragment(SolidOut in [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    // a faint fill with diagonal hatching, so a zone reads as "not a real surface"
    float h = fract((in.world.x + in.world.y + in.world.z) * 2.5);
    float a = in.color.a * (0.75 + 0.25 * step(0.5, h));
    return float4(in.color.rgb * a, a);
}

// ---------------------------------------------------------------- volumetric beams (cones)
struct ConeIn { float3 local [[attribute(0)]]; };   // x = cos, y = sin, z = 0 (lens) .. 1 (end)
struct BeamInstance { float4 apexLen; float4 dirRadius; float4 colorIntensity; float4 extra; };  // extra.x = lens radius
struct BeamOut { float4 pos [[position]]; float3 world; float3 normal; float along; float4 color; };

vertex BeamOut beam_vertex(ConeIn in [[stage_in]], uint iid [[instance_id]],
                           const device BeamInstance *beams [[buffer(2)]], constant Uniforms &u [[buffer(1)]]) {
    BeamInstance b = beams[iid];
    float3 d = normalize(b.dirRadius.xyz + float3(0, 0, 1e-7));
    float3 side = abs(d.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 bu = normalize(cross(d, side)), bv = cross(d, bu);
    float len = b.apexLen.w, R = b.dirRadius.w, r0 = b.extra.x;
    float r = mix(r0, R, in.local.z);
    float3 radial = bu * in.local.x + bv * in.local.y;
    BeamOut o;
    o.world = b.apexLen.xyz + d * (in.local.z * len) + radial * r;
    o.normal = normalize(radial * len - d * (R - r0));
    o.pos = u.viewProj * float4(o.world, 1);
    o.along = in.local.z;
    o.color = b.colorIntensity;
    return o;
}

fragment float4 beam_fragment(BeamOut in [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    float3 v = normalize(u.camPos.xyz - in.world);
    // light scattered by the haze: strongest where the view crosses the most beam (facing the axis)
    float facing = saturate(abs(dot(normalize(in.normal + float3(1e-6)), v)));
    float along = saturate(in.along);       // can overshoot 1 by a hair: pow() of a negative number is NaN
    float body = pow(facing, 2.2);          // soft edges: a cylinder of haze, not a slab
    float fade = pow(1.0 - along, 1.6) * (0.4 + 0.6 * exp(-along * 5.0));
    // a beam right next to (or through) the camera: fade its haze, it would white out the whole picture
    float near = smoothstep(0.4, 2.5, distance(u.camPos.xyz, in.world));
    float a = in.color.a * body * fade * near * u.params.y;
    return float4(in.color.rgb * a, 0);
}

// ---------------------------------------------------------------- camera-facing sprites (lenses, flares)
struct SpriteInstance { float4 centerSize; float4 colorIntensity; float4 extra; };   // extra.x = hardness
struct QuadOut { float4 pos [[position]]; float2 uv; float4 color; float hard; };

constant float2 QUAD[6] = { float2(-1,-1), float2(1,-1), float2(1,1), float2(-1,-1), float2(1,1), float2(-1,1) };

vertex QuadOut sprite_vertex(uint vid [[vertex_id]], uint iid [[instance_id]],
                             const device SpriteInstance *s [[buffer(2)]], constant Uniforms &u [[buffer(1)]]) {
    SpriteInstance i = s[iid];
    float2 q = QUAD[vid];
    float3 w = i.centerSize.xyz + (u.camRight.xyz * q.x + u.camUp.xyz * q.y) * i.centerSize.w;
    QuadOut o;
    o.pos = u.viewProj * float4(w, 1);
    o.uv = q; o.color = i.colorIntensity; o.hard = i.extra.x;
    return o;
}

fragment float4 sprite_fragment(QuadOut in [[stage_in]]) {
    float r = length(in.uv);
    if (r > 1.0) discard_fragment();
    float core = exp(-r * r * (8.0 + in.hard * 40.0));
    float halo = pow(saturate(1.0 - r), 2.0) * 0.35;
    float3 c = in.color.rgb * (core * 2.0 + halo) + float3(1.0) * core * in.hard * 0.8;
    return float4(c * in.color.a, 0);
}

// ---------------------------------------------------------------- spots where beams land (decals)
struct DecalInstance { float4 centerRadius; float4 normal; float4 colorIntensity; };

vertex QuadOut decal_vertex(uint vid [[vertex_id]], uint iid [[instance_id]],
                            const device DecalInstance *s [[buffer(2)]], constant Uniforms &u [[buffer(1)]]) {
    DecalInstance i = s[iid];
    float3 n = normalize(i.normal.xyz);
    float3 side = abs(n.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 a = normalize(cross(n, side)), b = cross(n, a);
    float2 q = QUAD[vid];
    float3 w = i.centerRadius.xyz + n * 0.012 + (a * q.x + b * q.y) * i.centerRadius.w * i.normal.w;
    QuadOut o;
    o.pos = u.viewProj * float4(w, 1);
    o.uv = q; o.color = i.colorIntensity; o.hard = 0;
    return o;
}

fragment float4 decal_fragment(QuadOut in [[stage_in]]) {
    float r = length(in.uv);
    if (r > 1.0) discard_fragment();
    float spot = (1.0 - smoothstep(0.55, 1.0, r)) * 0.7 + exp(-r * r * 6.0) * 0.6;   // edges in order (reversed is undefined)
    return float4(in.color.rgb * spot * in.color.a, 0);
}

// ---------------------------------------------------------------- gobo beams: the pattern in the haze and where it lands
// Every hole of a gobo throws its own shaft of light. A gobo beam is a volume: the view ray is marched through the
// cone, the gobo picture (turned in its slot, sliding on its wheel) is its cross-section at every distance.
struct GoboBeam { float4 apexLen; float4 dirRadius; float4 colorIntensity; float4 wheel; float4 axis; };
struct GoboDecal { float4 centerRadius; float4 normal; float4 colorIntensity; float4 apexLen; float4 dirK; float4 wheel; float4 axis; };
// wheel: x the picture (texture slice; -1: the open hole), y the next one on the wheel, z how far the wheel has
// turned towards it (0..1), w the lens radius; axis: xyz the picture's x direction across the beam, w its rotation
struct GoboOut { float4 pos [[position]]; float3 world; uint iid [[flat]]; };

constant float WHEEL_PITCH = 2.3;   // from one gobo to the next on the wheel, in gobo radii

float3 gobo_light(texture2d_array<float> pics, float2 p, float slot, float lod) {
    float r = length(p);
    if (r >= 1.0) return float3(0);
    float edge = 1.0 - smoothstep(0.94, 1.0, r);
    if (slot < 0.0) return float3(edge);
    constexpr sampler smp(filter::linear, mip_filter::linear, address::clamp_to_edge);
    return pics.sample(smp, float2(p.x * 0.5 + 0.5, 0.5 - p.y * 0.5), uint(slot), level(lod)).rgb * edge;
}

// the light the gobo lets through at q (the aperture, radius 1): the picture in it and the next one sliding in
float3 gobo_at(texture2d_array<float> pics, float2 q, float4 wheel, float rot, float lod) {
    float c = cos(rot), s = sin(rot);
    float off = wheel.z * WHEEL_PITCH;
    float2 pa = q + float2(off, 0), pb = q + float2(off - WHEEL_PITCH, 0);
    pa = float2(c * pa.x + s * pa.y, -s * pa.x + c * pa.y);
    pb = float2(c * pb.x + s * pb.y, -s * pb.x + c * pb.y);
    return gobo_light(pics, pa, wheel.x, lod) + (wheel.z > 0.0 ? gobo_light(pics, pb, wheel.y, lod) : float3(0));
}

float3 beam_axis(float3 axis, float3 d) { return normalize(axis - d * dot(axis, d) + float3(1e-6, 0, 0)); }

vertex GoboOut gobo_beam_vertex(ConeIn in [[stage_in]], uint iid [[instance_id]],
                                const device GoboBeam *beams [[buffer(2)]], constant Uniforms &u [[buffer(1)]]) {
    GoboBeam b = beams[iid];
    float3 d = normalize(b.dirRadius.xyz + float3(0, 0, 1e-7));
    float3 bu = beam_axis(b.axis.xyz, d), bv = cross(d, bu);
    float r = mix(b.wheel.w, b.dirRadius.w, in.local.z);
    GoboOut o;
    o.world = b.apexLen.xyz + d * (in.local.z * b.apexLen.w) + (bu * in.local.x + bv * in.local.y) * r;
    o.pos = u.viewProj * float4(o.world, 1);
    o.iid = iid;
    return o;
}

fragment float4 gobo_beam_fragment(GoboOut in [[stage_in]], const device GoboBeam *beams [[buffer(2)]],
                                   texture2d_array<float> pics [[texture(0)]], constant Uniforms &u [[buffer(1)]]) {
    GoboBeam b = beams[in.iid];
    // how much of the world one pixel covers per metre of distance (for the picture's detail, below)
    float pixel = length(fwidth(in.world)) / max(distance(in.world, u.camPos.xyz), 0.1);
    float3 A = b.apexLen.xyz, d = normalize(b.dirRadius.xyz + float3(0, 0, 1e-7));
    float len = max(b.apexLen.w, 1e-3), R = b.dirRadius.w, r0 = b.wheel.w;
    float k = max((R - r0) / len, 1e-4);   // the radius grows this much per metre
    float3 bu = beam_axis(b.axis.xyz, d), bv = cross(d, bu);
    float3 C = u.camPos.xyz;
    float far = distance(in.world, C);
    float3 v = (in.world - C) / max(far, 1e-5);
    // this fragment's face: the cone's side (outward normal) or its end cap
    float aP = dot(in.world - A, d);
    float3 radP = in.world - A - d * aP;
    float3 n = aP > len * 0.999 ? d : normalize(normalize(radP + float3(1e-6, 0, 0)) - d * k);
    bool facing = dot(n, v) < 0.0;
    float ca = dot(C - A, d);
    bool inside = ca > 0.0 && ca < len && length(C - A - d * ca) < r0 + k * ca;
    // seen from inside: from the eye to the far side; from outside: from the near side on through the beam
    if (inside == facing) discard_fragment();
    float s0 = inside ? 0.0 : far, s1 = far;
    float dv = dot(v, d);
    if (!inside) {
        // where the view ray leaves the cone
        float3 o = C - (A - d * (r0 / k));
        float kk = 1.0 + k * k, dO = dot(o, d);
        float qa = 1.0 - kk * dv * dv, qb = 2.0 * (dot(o, v) - kk * dO * dv), qc = dot(o, o) - kk * dO * dO;
        float disc = qb * qb - 4.0 * qa * qc;
        s1 = far + 4.0 * R;
        if (disc > 0.0 && abs(qa) > 1e-6) {
            float sq = sqrt(disc);
            float x1 = (-qb - sq) / (2.0 * qa), x2 = (-qb + sq) / (2.0 * qa);
            // the entry is this fragment (one root, give or take rounding): the exit is the farther root, if it is on
            // the beam's side of the apex and really beyond the entry
            float exitAt = -1.0;
            if (dO + x1 * dv > 0.0) exitAt = max(exitAt, x1);
            if (dO + x2 * dv > 0.0) exitAt = max(exitAt, x2);
            if (exitAt > far + 0.02 * r0) s1 = exitAt;
        }
        if (abs(dv) > 1e-5) {   // or through the end, or the lens
            float sEnd = ((dv > 0.0 ? len : 0.0) - ca) / dv;
            if (sEnd > far) s1 = min(s1, sEnd);
        }
    }
    if (v.z < -1e-4) s1 = min(s1, -C.z / v.z);   // the floor
    if (s1 <= s0) discard_fragment();
    // steps: enough to cross the pattern a few times per beam width along the way (a view along a thin beam crosses
    // many shafts), at least 16, at most 64
    float mid = dot(C + v * (0.5 * (s0 + s1)) - A, d);
    float width = r0 + k * clamp(mid, 0.0, len);
    int N = int(clamp((s1 - s0) / (0.35 * width), 16.0, 64.0));
    float ds = (s1 - s0) / float(N);
    float jitter = fract(52.9829189 * fract(dot(in.pos.xy, float2(0.06711056, 0.00583715))));   // interleaved gradient noise
    float3 acc = float3(0);
    for (int i = 0; i < N; i++) {
        float s = s0 + (float(i) + jitter) * ds;
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
        float near = smoothstep(0.4, 2.5, s);
        // the picture as fine as a pixel there can show: near the lens it shrinks to a few pixels, blurred, not noise
        float lod = clamp(log2(64.0 * pixel * s / rr) + 1.0, 1.0, 6.0);
        acc += gobo_at(pics, q, b.wheel, b.axis.w, lod) * (fade * near / rr);
    }
    // an open beam: as bright through its middle as the plain beams (their two faces), the pattern cuts it up
    float3 c = b.colorIntensity.rgb * acc * ds * b.colorIntensity.a * u.params.y;
    return float4(clean(c), 0);
}

vertex GoboOut gobo_decal_vertex(uint vid [[vertex_id]], uint iid [[instance_id]],
                                 const device GoboDecal *s [[buffer(2)]], constant Uniforms &u [[buffer(1)]]) {
    GoboDecal i = s[iid];
    float3 n = normalize(i.normal.xyz);
    float3 side = abs(n.z) < 0.95 ? float3(0, 0, 1) : float3(1, 0, 0);
    float3 a = normalize(cross(n, side)), b = cross(n, a);
    float2 q = QUAD[vid];
    GoboOut o;
    o.world = i.centerRadius.xyz + n * 0.014 + (a * q.x + b * q.y) * i.centerRadius.w * i.normal.w;
    o.pos = u.viewProj * float4(o.world, 1);
    o.iid = iid;
    return o;
}

fragment float4 gobo_decal_fragment(GoboOut in [[stage_in]], const device GoboDecal *s [[buffer(2)]],
                                    texture2d_array<float> pics [[texture(0)]]) {
    GoboDecal g = s[in.iid];
    float3 A = g.apexLen.xyz, d = normalize(g.dirK.xyz + float3(0, 0, 1e-7));
    float3 bu = beam_axis(g.axis.xyz, d), bv = cross(d, bu);
    float a = max(dot(in.world - A, d), 1e-3);
    float3 rad = in.world - A - d * a;
    float2 q = float2(dot(rad, bu), dot(rad, bv)) / (g.wheel.w + g.dirK.w * a);
    // sharp where the picture is big on screen, blurred (a lower mip) where it is small
    float lod = log2(max(max(length(dfdx(q)), length(dfdy(q))) * 64.0, 1e-4));
    if (dot(q, q) >= 1.0) discard_fragment();
    float3 m = gobo_at(pics, q, g.wheel, g.axis.w, max(lod, 0.0));
    return float4(clean(g.colorIntensity.rgb * m * g.colorIntensity.a), 0);
}

// ---------------------------------------------------------------- laser beams (thin lines)
struct LineInstance { float4 p0Width; float4 p1; float4 colorIntensity; };
struct LineOut { float4 pos [[position]]; float across; float along; float4 color; };

vertex LineOut line_vertex(uint vid [[vertex_id]], uint iid [[instance_id]],
                           const device LineInstance *s [[buffer(2)]], constant Uniforms &u [[buffer(1)]]) {
    LineInstance i = s[iid];
    float2 q = QUAD[vid];
    float t = q.x * 0.5 + 0.5;
    float3 p = mix(i.p0Width.xyz, i.p1.xyz, t);
    float3 seg = i.p1.xyz - i.p0Width.xyz;
    float3 dir = seg / max(length(seg), 1e-6);
    float3 toCam = normalize(u.camPos.xyz - p + float3(0, 0, 1e-4));
    float3 sc = cross(dir, toCam);
    float3 side = length(sc) > 1e-5 ? normalize(sc) : float3(1, 0, 0);   // pointing at the camera: any side
    // keep a minimum on-screen width far away (otherwise the beam flickers out)
    float dist = length(u.camPos.xyz - p);
    float w = max(i.p0Width.w, dist * 0.0012);
    LineOut o;
    o.pos = u.viewProj * float4(p + side * q.y * w, 1);
    o.across = q.y; o.along = t;
    o.color = i.colorIntensity;
    return o;
}

fragment float4 line_fragment(LineOut in [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    float g = exp(-in.across * in.across * 5.0);
    float fade = 1.0 - 0.55 * in.along;
    return float4(in.color.rgb * g * fade * in.color.a, 0);
}

// ---------------------------------------------------------------- the LED wall
struct WallIn { float3 pos [[attribute(0)]]; float2 uv [[attribute(1)]]; };
struct WallOut { float4 pos [[position]]; float2 uv; };
struct WallParams { float4 info; float4 bands; float4 pal[4]; };   // info: x level, y psychedelic, z time

vertex WallOut wall_vertex(WallIn in [[stage_in]], constant Uniforms &u [[buffer(1)]]) {
    WallOut o; o.pos = u.viewProj * float4(in.pos, 1); o.uv = in.uv; return o;
}

float3 psychedelic(float2 uv, float t, float4 bands, constant float4 *pal) {
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
    float3 c = s < 0.33 ? mix(c0, c1, s / 0.33) : s < 0.66 ? mix(c1, c2, (s - 0.33) / 0.33) : mix(c2, c3, (s - 0.66) / 0.34);
    float rings = smoothstep(0.85, 1.0, sin(r * 18.0 - t * 5.0 - bass * 8.0) * 0.5 + 0.5);
    c += rings * (0.4 + hi);
    c *= 0.55 + 0.6 * bass + 0.25 * smoothstep(1.2, 0.0, r);
    return c;
}

fragment float4 wall_fragment(WallOut in [[stage_in]], texture2d<float> tex [[texture(0)]],
                              constant WallParams &w [[buffer(3)]]) {
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    float3 c = w.info.y > 0.5 ? psychedelic(in.uv, w.info.z, w.bands, w.pal) : tex.sample(smp, in.uv).rgb;
    // LED pixel grid, faintly visible up close
    float2 px = fract(in.uv * float2(192.0, 108.0));
    float grid = 0.85 + 0.15 * smoothstep(0.0, 0.15, min(min(px.x, 1.0 - px.x), min(px.y, 1.0 - px.y)));
    return float4(c * w.info.x * 1.6 * grid + float3(0.004), 1);
}

// ---------------------------------------------------------------- a drawing on the floor (rig editor)
// d: x opacity, y brightness (white paper as the work-lit floor shows it); premultiplied alpha over the scene
fragment float4 drawing_fragment(WallOut in [[stage_in]], texture2d<float> tex [[texture(0)]],
                                 constant float4 &d [[buffer(3)]]) {
    constexpr sampler smp(filter::linear, mip_filter::linear, address::clamp_to_edge);
    float4 c = tex.sample(smp, in.uv);
    float a = c.a * d.x;
    return float4(c.rgb * d.y * d.x, a);
}

// ---------------------------------------------------------------- final picture: bloom + tone curve
struct FSOut { float4 pos [[position]]; float2 uv; };

vertex FSOut fullscreen_vertex(uint vid [[vertex_id]]) {
    float2 p = float2((vid << 1) & 2, vid & 2);
    FSOut o; o.pos = float4(p * 2.0 - 1.0, 0, 1); o.uv = float2(p.x, 1.0 - p.y); return o;
}


float3 aces(float3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

fragment float4 composite_fragment(FSOut in [[stage_in]], texture2d<float> hdr [[texture(0)]],
                                   texture2d<float> bloomA [[texture(1)]], texture2d<float> bloomB [[texture(2)]],
                                   constant Uniforms &u [[buffer(1)]]) {
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    float3 c = clean(hdr.sample(smp, in.uv).rgb);
    // bloom only from what is really bright (a soft knee), so lenses glow without hiding the rig in halos
    float3 ba = clean(bloomA.sample(smp, in.uv).rgb), bb = clean(bloomB.sample(smp, in.uv).rgb);
    ba *= saturate((max(ba.r, max(ba.g, ba.b)) - 0.35) / 1.2);
    bb *= saturate((max(bb.r, max(bb.g, bb.b)) - 0.35) / 1.2);
    c += ba * 0.45 + bb * 0.3;
    c *= u.params.z;
    // a soft vignette, like a camera
    float2 q = in.uv - 0.5;
    c *= 1.0 - dot(q, q) * 0.6;
    return float4(aces(c), 1);
}
"""#
}
