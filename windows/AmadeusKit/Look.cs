// Colours and room geometry shared by every view of the show (same values as web/index.html).
using System.Numerics;

namespace AmadeusKit;

public static class Palettes
{
    static Vector3 C(float r, float g, float b) => new(r, g, b);

    public static readonly IReadOnlyDictionary<string, Vector3[]> All = new Dictionary<string, Vector3[]>
    {
        ["warm"] = [C(1, 0.45f, 0), C(1, 0.15f, 0), C(0.9f, 0, 0.05f), C(1, 0.7f, 0.2f)],
        ["cool"] = [C(0, 0.3f, 1), C(0, 0.8f, 1), C(0.45f, 0, 1), C(0.1f, 0.1f, 0.9f)],
        ["neon"] = [C(1, 0, 0.8f), C(0.4f, 1, 0), C(0, 1, 0.9f), C(0.8f, 0, 1)],
        ["fire"] = [C(1, 0, 0), C(1, 0.35f, 0), C(1, 0.9f, 0.7f), C(0.8f, 0.05f, 0)],
        ["ice"] = [C(0.85f, 0.95f, 1), C(0.3f, 0.8f, 1), C(0.1f, 0.35f, 1), C(1, 1, 1)],
        ["gold"] = [C(1, 0.65f, 0.1f), C(0.55f, 0, 0.9f), C(1, 0.85f, 0.45f), C(0.9f, 0.3f, 0.6f)],
        ["stage"] = [C(1, 0.85f, 0.65f), C(1, 0.55f, 0.1f), C(0.1f, 0.2f, 0.9f), C(1, 1, 1)],
    };

    public static Vector3[] Colors(string? name) => All.GetValueOrDefault(name ?? "") ?? [C(1, 0.3f, 0.8f), C(0.2f, 0.7f, 1)];
}

public static class Sections
{
    public static readonly string[] Order = ["intro", "groove", "buildup", "drop", "breakdown", "outro", "verse", "chorus", "bridge"];

    public static readonly IReadOnlyDictionary<string, Vector3> Colors = new Dictionary<string, Vector3>
    {
        ["intro"] = new(0.357f, 0.420f, 0.549f), ["groove"] = new(0.247f, 0.561f, 0.420f), ["buildup"] = new(0.788f, 0.510f, 0.169f),
        ["drop"] = new(0.847f, 0.271f, 0.310f), ["breakdown"] = new(0.424f, 0.333f, 0.722f), ["outro"] = new(0.290f, 0.322f, 0.376f),
        ["verse"] = new(0.310f, 0.498f, 0.659f), ["chorus"] = new(0.816f, 0.439f, 0.227f), ["bridge"] = new(0.541f, 0.373f, 0.627f),
    };

    public static Vector3 Color(string s) => Colors.GetValueOrDefault(s, new Vector3(0.4f, 0.4f, 0.45f));
}

/// The room the show happens in: floor, ceiling, walls. Beams stop where they would hit one.
public sealed record Room
{
    public enum Surface { Floor, Ceiling, Back, Front, Left, Right, Air }

    public float Width { get; init; }
    public float Ceiling { get; init; }
    public float Depth { get; init; }
    public float Back { get; init; }
    public float Side { get; init; } = 2;
    /// An open-air stage: no ceiling, beams going up end in the air.
    public bool Outdoor { get; init; }

    /// The back wall stands 1.5 m behind the rearmost fixture or truss (a round truss: its back edge).
    public Room(Stage stage, IEnumerable<FixtureInfo> fixtures, IEnumerable<Truss>? trusses = null)
    {
        Width = (float)stage.WidthM;
        Ceiling = (float)stage.CeilingM;
        Outdoor = stage.Outdoor;
        Depth = (float)stage.RoomDepthM;
        var trussBack = (trusses ?? []).Select(t => t.Vertical ? t.YM : t.Pieces().Select(p => Math.Min(p.A.Y, p.B.Y)).DefaultIfEmpty(t.YM).Min());
        var rear = fixtures.Select(f => f.Pos.Y).Concat(trussBack).DefaultIfEmpty(-1).Min();
        Back = Math.Min(-2.5f, (float)rear - 1.5f);
    }

    /// Where a beam from `p` along `d` ends: distance and surface (at most `maxLen`).
    public (float T, Surface Surface) Hit(Vector3 p, Vector3 d, float maxLen = 30)
    {
        var best = (maxLen, Surface.Air);
        void Consider(float t, Surface s) { if (t > 0 && t < best.Item1) best = (t, s); }
        if (d.Z < -1e-3f) Consider(-p.Z / d.Z, Surface.Floor);
        if (d.Z > 1e-3f && !Outdoor) Consider((Ceiling - p.Z) / d.Z, Surface.Ceiling);
        if (d.Y > 1e-3f) Consider((Depth - p.Y) / d.Y, Surface.Front);
        if (d.Y < -1e-3f) Consider((Back - p.Y) / d.Y, Surface.Back);
        if (d.X > 1e-3f) Consider((Width + Side - p.X) / d.X, Surface.Right);
        if (d.X < -1e-3f) Consider((-Side - p.X) / d.X, Surface.Left);
        return best;
    }

    public static Vector3 Normal(Surface s) => s switch
    {
        Surface.Floor => new(0, 0, 1),
        Surface.Ceiling => new(0, 0, -1),
        Surface.Front => new(0, -1, 0),
        Surface.Back => new(0, 1, 0),
        Surface.Left => new(1, 0, 0),
        Surface.Right => new(-1, 0, 0),
        _ => new(0, 1, 0),
    };
}
