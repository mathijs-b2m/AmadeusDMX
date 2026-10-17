// Swift's SIMD2<Double> / SIMD3<Double>: positions and directions in metres (x across the stage, y towards the
// audience, z up). The renderer's float vectors are System.Numerics.Vector3 (SIMD3<Float> in Swift).
using System.Numerics;

namespace AmadeusKit;

public readonly record struct Vec2(double X, double Y)
{
    public static Vec2 operator +(Vec2 a, Vec2 b) => new(a.X + b.X, a.Y + b.Y);
    public static Vec2 operator -(Vec2 a, Vec2 b) => new(a.X - b.X, a.Y - b.Y);
    public static Vec2 operator *(Vec2 a, double k) => new(a.X * k, a.Y * k);
    public static double Dot(Vec2 a, Vec2 b) => a.X * b.X + a.Y * b.Y;
    public double Length => Math.Sqrt(X * X + Y * Y);
}

public readonly record struct Vec3(double X, double Y, double Z)
{
    public static Vec3 operator +(Vec3 a, Vec3 b) => new(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
    public static Vec3 operator -(Vec3 a, Vec3 b) => new(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
    public static Vec3 operator -(Vec3 a) => new(-a.X, -a.Y, -a.Z);
    public static Vec3 operator *(Vec3 a, double k) => new(a.X * k, a.Y * k, a.Z * k);
    public static Vec3 operator /(Vec3 a, double k) => new(a.X / k, a.Y / k, a.Z / k);
    public static double Dot(Vec3 a, Vec3 b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
    public double Length => Math.Sqrt(Dot(this, this));
    public Vec2 XY => new(X, Y);
    public Vector3 ToFloat() => new((float)X, (float)Y, (float)Z);
    public double[] ToArray() => [X, Y, Z];
}
