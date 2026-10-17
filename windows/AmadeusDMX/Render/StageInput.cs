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
