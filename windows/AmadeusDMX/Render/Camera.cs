// An orbit camera around the stage (drag to turn, scroll/pinch to zoom, Alt-drag or right-drag to pan) with presets
// that glide into place (mac/Sources/AmadeusDMX/Render/Camera.swift).
//
// Matrices: the Swift code builds column-vector matrices (M * v). Here they are System.Numerics Matrix4x4 values
// holding the TRANSPOSE (row j = the Swift matrix's column j), which is System.Numerics' own row-vector convention:
// Vector4.Transform(v, M) gives the same result as Swift's M * v, `view * proj` here is Swift's `proj * view`, and the
// 16 floats in memory are in the same order as Swift's float4x4 (column-major). The HLSL cbuffer reads them as
// column_major (the default) and multiplies `mul(viewProj, v)`, like the Metal shader.
using System.Numerics;

namespace AmadeusDMX;

public static class Float4x4
{
    /// Swift `float4x4.lookAt(eye:target:up:)`: right-handed, the camera looking down -z.
    public static Matrix4x4 LookAt(Vector3 eye, Vector3 target, Vector3 up)
    {
        Vector3 f = Vector3.Normalize(target - eye), s = Vector3.Normalize(Vector3.Cross(f, up)), u = Vector3.Cross(s, f);
        return new Matrix4x4(
            s.X, u.X, -f.X, 0,
            s.Y, u.Y, -f.Y, 0,
            s.Z, u.Z, -f.Z, 0,
            -Vector3.Dot(s, eye), -Vector3.Dot(u, eye), Vector3.Dot(f, eye), 1);
    }

    /// Swift `float4x4.perspective(fovY:aspect:near:far:)`: depth 0 (near) … 1 (far), as in Metal and Direct3D.
    public static Matrix4x4 Perspective(float fovY, float aspect, float near, float far)
    {
        float ys = 1 / MathF.Tan(fovY / 2), xs = ys / aspect, zs = far / (near - far);
        return new Matrix4x4(
            xs, 0, 0, 0,
            0, ys, 0, 0,
            0, 0, zs, -1,
            0, 0, zs * near, 0);
    }
}

public readonly record struct CameraPose(Vector3 Target, float Yaw, float Pitch, float Distance)
{
    // Yaw: around z; 0 = looking from the audience (+y) towards the stage. Pitch: up from horizontal (radians).

    public Vector3 Eye =>
        Target + new Vector3(MathF.Sin(Yaw) * MathF.Cos(Pitch), MathF.Cos(Yaw) * MathF.Cos(Pitch), MathF.Sin(Pitch)) * Distance;

    public static CameraPose Lerp(CameraPose a, CameraPose b, float k)
    {
        var dy = b.Yaw - a.Yaw;
        while (dy > MathF.PI) dy -= 2 * MathF.PI;
        while (dy < -MathF.PI) dy += 2 * MathF.PI;
        return new CameraPose(Vector3.Lerp(a.Target, b.Target, k), a.Yaw + dy * k, a.Pitch + (b.Pitch - a.Pitch) * k,
            a.Distance + (b.Distance - a.Distance) * k);
    }

    public static CameraPose From(Vector3 eye, Vector3 target)
    {
        var v = eye - target;
        var d = v.Length();
        return new CameraPose(target, MathF.Atan2(v.X, v.Y), MathF.Asin(v.Z / MathF.Max(d, 1e-3f)), d);
    }
}

public enum CameraPreset { FrontOfHouse, Crowd, Drone, Side, Dj, Plan }

public static class CameraPresets
{
    public static readonly CameraPreset[] AllCases =
        [CameraPreset.FrontOfHouse, CameraPreset.Crowd, CameraPreset.Drone, CameraPreset.Side, CameraPreset.Dj, CameraPreset.Plan];

    /// Swift's rawValue: the name the UI shows (and `-camera Plan` reads).
    public static string RawValue(this CameraPreset p) => p switch
    {
        CameraPreset.FrontOfHouse => "Front of House",
        CameraPreset.Crowd => "In the Crowd",
        CameraPreset.Drone => "Drone",
        CameraPreset.Side => "Side",
        CameraPreset.Dj => "DJ",
        _ => "Plan",
    };

    public static CameraPreset? FromRawValue(string? raw) => AllCases.Cast<CameraPreset?>().FirstOrDefault(p => p!.Value.RawValue() == raw);

    public static string Symbol(this CameraPreset p) => p switch
    {
        CameraPreset.FrontOfHouse => "person.2",
        CameraPreset.Crowd => "person.3.sequence",
        CameraPreset.Drone => "airplane",
        CameraPreset.Side => "arrow.left.and.right",
        CameraPreset.Dj => "headphones",
        _ => "square.grid.3x3",
    };

    /// The pose for a room (fits the rig, like the web visualiser's camera); `deck`: the stage's height above the
    /// hall floor (what looks at the stage floor looks that much higher, the DJ stands on it).
    public static CameraPose Pose(this CameraPreset p, float width, float top, float back, float ceiling, float deck = 0)
    {
        var W = width;
        var cx = W / 2;
        var roomH = MathF.Max(top + 1, MathF.Min(ceiling, top + 4));
        var tz = MathF.Max(1.3f, roomH * 0.5f);
        var dist = MathF.Max(MathF.Max(9.5f, (roomH - tz + 0.5f) * 2.2f), (W / 2 + 2) * 1.6f);
        switch (p)
        {
            case CameraPreset.FrontOfHouse:
                return CameraPose.From(new(cx, dist * 1.12f, MathF.Max(2.6f, roomH * 0.38f)), new(cx, MathF.Max(-0.5f, back / 3), tz * 0.9f));
            case CameraPreset.Crowd:
                return CameraPose.From(new(cx - W * 0.12f, dist * 0.45f, 1.7f), new(cx, back / 2, tz * 1.15f));
            case CameraPreset.Drone:
                return CameraPose.From(new(cx + W * 0.45f, dist * 1.25f, roomH + dist * 0.75f), new(cx, back / 2.5f, deck + 1.0f));
            case CameraPreset.Side:
                return CameraPose.From(new(cx + W * 0.5f + dist * 0.75f, dist * 0.35f, roomH * 0.55f), new(cx, back / 3, tz));
            case CameraPreset.Dj:
                return CameraPose.From(new(cx, back + 1.6f, deck + 2.6f), new(cx, 8, 1.8f));
            default:  // Plan: top-down (almost: straight down has no "up" for the camera)
                var span = MathF.Max(W + 6, -back + 8);
                return new CameraPose(new(cx, back / 2 + 1, deck), 0, 1.45f, span * 1.25f);
        }
    }
}
