// What the 3D stage draws: the rig (from the show's hello, or a preview of the set on the rig before a show runs).
// The renderer itself (Direct3D 11, a port of the Mac's Metal StageRenderer) comes with the Show page.
namespace AmadeusDMX;

public sealed record StageInput
{
    public required string Key { get; init; }               // changes when the rig changes (rebuild the scenery)
    public required IReadOnlyList<FixtureInfo> Fixtures { get; init; }
    public required Stage Stage { get; init; }
    public bool Screen { get; init; }
    public Hello? Hello { get; init; }
    public IReadOnlyList<Truss> Trusses { get; init; } = [];
    public IReadOnlySet<string> Selected { get; init; } = new HashSet<string>();  // "truss:ID" / "fixture:ID" (rig editor)
    public bool KeepCamera { get; init; }                  // the editor rebuilds the scene on every change: leave the camera alone
    public IReadOnlyList<Zone> Zones { get; init; } = [];   // drawn translucent (rig editor)
    public IReadOnlyList<StageDrawing> Drawings { get; init; } = [];  // the plans under the rig, on the floor (rig editor)

    /// Where the trusses and fixtures are, for the key: a truss moved (same count) is a different rig to draw.
    public static int Layout(IEnumerable<FixtureInfo> fixtures, IEnumerable<Truss> trusses)
    {
        var h = new HashCode();
        foreach (var t in trusses) h.Add(t);
        foreach (var f in fixtures)
        {
            h.Add(f.Id); h.Add(f.Pos); h.Add(f.Rot); h.Add(f.Mount); h.Add(f.Up); h.Add(f.Truss);
        }
        return h.ToHashCode();
    }
}

/// A drawing's page as pixels: BGRA, premultiplied, rows from the top (rendered once per file from its PDF).
public sealed record DrawingPicture(int Width, int Height, byte[] Bgra);

/// A drawing on the stage floor: its page (`Key`: the page's file, one texture per file), its four corners on the
/// rig (top left, top right, bottom right, bottom left of its `Crop`; rig metres, the trusses' x/y), how opaque, and
/// the part of the page that is this plan (`Crop`: [x0, y0, x1, y1], page fractions; null: the whole page).
public sealed record StageDrawing(string Key, DrawingPicture Picture, IReadOnlyList<Vec2> Corners, float Opacity,
                                  IReadOnlyList<double>? Crop = null);
