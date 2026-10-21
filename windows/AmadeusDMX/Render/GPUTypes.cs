// Buffer layouts shared with the shaders (Render/Shaders/*.hlsl): keep both in step (mac/.../Render/GPUTypes.swift).
//
// Packing, Metal vs Direct3D:
// - Constant buffers (Uniforms, WallParams, BlurParams) follow HLSL's cbuffer rules: members never straddle a 16-byte
//   boundary, every array element starts on one, and the buffer's size is a multiple of 16. Everything here is float4
//   or float4x4, so the C# structs are packed tight and match (sizes checked in RenderTests).
// - Instance data (BeamInstance, SpriteInstance, DecalInstance, LineInstance, GoboBeamInstance, GoboDecalInstance) is read in the vertex shader as a
//   StructuredBuffer (Metal: `const device T*`), whose stride is the C# struct's size; float4 only, so no padding.
// - Vertex buffers (SolidVertex, WallVertex, the cone's float3) go through an input layout with explicit offsets.
//   Swift's SIMD3<Float> takes 16 bytes (a SolidVertex is 48 there); here a Vector3 is 12 and a SolidVertex 40.
using System.Numerics;
using System.Runtime.InteropServices;

namespace AmadeusDMX;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct Uniforms
{
    public Matrix4x4 ViewProj;   // see Camera.cs: the transpose of the math matrix, column-major for HLSL
    public Vector4 CamPos;       // xyz
    public Vector4 CamRight;     // xyz
    public Vector4 CamUp;        // xyz
    public Vector4 Params;       // x time, y haze, z exposure, w room bounce strength
    public Vector4 Ambient;      // rgb: the colour the rig throws around the room; w: work light (rig preview)

    public const int Size = 144;
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct BeamInstance(Vector4 apexLen, Vector4 dirRadius, Vector4 color, Vector4 extra)
{
    public Vector4 ApexLen = apexLen;       // xyz apex, w length
    public Vector4 DirRadius = dirRadius;   // xyz direction, w end radius
    public Vector4 Color = color;           // rgb, a intensity
    public Vector4 Extra = extra;           // x lens radius

    public const int Size = 64;
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct SpriteInstance(Vector4 centerSize, Vector4 color, Vector4 extra)
{
    public Vector4 CenterSize = centerSize;
    public Vector4 Color = color;
    public Vector4 Extra = extra;           // x hardness

    public const int Size = 48;
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct DecalInstance(Vector4 centerRadius, Vector4 normal, Vector4 color)
{
    public Vector4 CenterRadius = centerRadius;
    public Vector4 Normal = normal;         // xyz normal, w squash (a beam landing at a shallow angle on the floor)
    public Vector4 Color = color;

    public const int Size = 48;
}

/// A beam with a gobo (Shaders/GoboBeam.hlsl): wheel = (picture, next picture, slide, lens radius), axis = (the
/// picture's x direction across the beam, its rotation).
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct GoboBeamInstance(Vector4 apexLen, Vector4 dirRadius, Vector4 color, Vector4 wheel, Vector4 axis)
{
    public Vector4 ApexLen = apexLen;       // xyz apex, w length
    public Vector4 DirRadius = dirRadius;   // xyz direction, w end radius
    public Vector4 Color = color;           // rgb, a intensity
    public Vector4 Wheel = wheel;           // x picture (texture slice; -1 the open hole), y next, z slide 0..1, w lens radius
    public Vector4 Axis = axis;             // xyz the picture's x direction, w its rotation (radians)

    public const int Size = 80;
}

/// Where a gobo beam lands: the decal quad, and the beam it projects (apex and length, direction and spread per metre).
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct GoboDecalInstance(Vector4 centerRadius, Vector4 normal, Vector4 color, Vector4 apexLen, Vector4 dirK, Vector4 wheel,
                                Vector4 axis)
{
    public Vector4 CenterRadius = centerRadius;
    public Vector4 Normal = normal;         // xyz normal, w squash
    public Vector4 Color = color;
    public Vector4 ApexLen = apexLen;
    public Vector4 DirK = dirK;             // xyz direction, w how much the radius grows per metre
    public Vector4 Wheel = wheel;
    public Vector4 Axis = axis;

    public const int Size = 112;
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct LineInstance(Vector4 p0Width, Vector4 p1, Vector4 color)
{
    public Vector4 P0Width = p0Width;
    public Vector4 P1 = p1;
    public Vector4 Color = color;

    public const int Size = 48;
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct WallVertex(Vector3 pos, Vector2 uv)
{
    public Vector3 Pos = pos;
    public Vector2 Uv = uv;

    public const int Size = 20, UvOffset = 12;
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct WallParams
{
    public Vector4 Info;    // x level, y psychedelic, z time
    public Vector4 Bands;
    public Vector4 Pal0, Pal1, Pal2, Pal3;   // HLSL: float4 pal[4]

    public const int Size = 96;
}

/// The bloom's blur (Direct3D only: Metal used MPSImageGaussianBlur): x/y one texel along the pass's direction,
/// z sigma (texels), w unused.
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct BlurParams
{
    public Vector4 Step;

    public const int Size = 16;
}
