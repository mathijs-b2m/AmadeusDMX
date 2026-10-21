// A stand-in for clang's hlsl.h (Apple's clang has the HLSL front end but not its header): the types and
// intrinsics the stage shaders use, declared well enough for check-hlsl.sh's -fsyntax-only pass. Not a real header.
typedef unsigned int uint;
typedef vector<float, 2> float2; typedef vector<float, 3> float3; typedef vector<float, 4> float4;
typedef vector<uint, 2> uint2; typedef vector<uint, 3> uint3; typedef vector<uint, 4> uint4;
typedef vector<int, 2> int2; typedef vector<int, 3> int3;
typedef vector<bool, 2> bool2; typedef vector<bool, 3> bool3; typedef vector<bool, 4> bool4;
struct float4x4 { float4 c0, c1, c2, c3; };
#define OV1(name) float name(float); float2 name(float2); float3 name(float3); float4 name(float4);
#define OV2(name) float name(float, float); float2 name(float2, float2); float3 name(float3, float3); float4 name(float4, float4);
#define OV3(name) float name(float, float, float); float2 name(float2, float2, float2); float3 name(float3, float3, float3); float4 name(float4, float4, float4);
OV1(normalize) OV1(saturate) OV1(exp) OV1(log2) OV1(fwidth) OV1(ddx) OV1(ddy) OV1(abs) OV1(frac) OV1(floor) OV1(ceil) OV1(sin) OV1(cos) OV1(sqrt)
OV2(pow) OV2(max) OV2(min) OV2(atan2) OV2(fmod) OV2(step)
OV3(lerp) OV3(smoothstep) OV3(clamp)
float dot(float2, float2); float dot(float3, float3); float dot(float4, float4);
float length(float2); float length(float3); float length(float4);
float distance(float3, float3);
float3 cross(float3, float3);
uint asuint(float); uint3 asuint(float3);
#define mul(m, v) ((void)(m).c0, (v))
template <typename T> struct Texture2D { T Sample(int s, float2 uv); T SampleLevel(int s, float2 uv, float lod); };
template <typename T> struct Texture2DArray { T SampleLevel(int s, float3 uvw, float lod); };
typedef int SamplerState;
float2 lerp(float2, float2, float); float3 lerp(float3, float3, float); float4 lerp(float4, float4, float);
float2 clamp(float2, float, float); float3 clamp(float3, float, float); float4 clamp(float4, float, float);
