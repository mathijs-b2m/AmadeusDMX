// The rig templates (amadeus/rig/templates.py): the structure a new rig starts from. The Mac keeps the enum in
// mac/Sources/AmadeusDMX/Rig/NewRigSheet.swift; here it lives in the kit, so the wizard and New Rig… share it and
// its rules are tested.
namespace AmadeusKit;

public enum RigTemplate { Floor, Stands, Bridge, Booth, Club, Stage, Ring }

public static class RigTemplates
{
    public static readonly RigTemplate[] All = Enum.GetValues<RigTemplate>();

    /// The name the engine knows it by ("club"); also a new rig's default name.
    public static string RawValue(this RigTemplate t) => t.ToString().ToLowerInvariant();

    public static string Title(this RigTemplate t) => t switch
    {
        RigTemplate.Floor => "Empty Room",
        RigTemplate.Stands => "Two Stands",
        RigTemplate.Bridge => "Light Bridge",
        RigTemplate.Booth => "Truss over the Booth",
        RigTemplate.Club => "Club",
        RigTemplate.Stage => "Concert Stage",
        _ => "Round Truss",
    };

    public static string Detail(this RigTemplate t) => t switch
    {
        RigTemplate.Floor => "Fixtures on the floor and on tripods.",
        RigTemplate.Stands => "A mobile DJ: a T-bar stand left and right of the booth.",
        RigTemplate.Bridge => "A mobile DJ: a bar over the booth on two stands.",
        RigTemplate.Booth => "One truss over the DJ.",
        RigTemplate.Club => "Two trusses over the booth, front and back.",
        RigTemplate.Stage => "Two overhead trusses, a low one at the back, a tower each side.",
        _ => "A circle over the booth, a half circle behind it: heads play crowns, cones and twisters.",
    };

    /// Width, truss height, room depth (m).
    public static (double Width, double Height, double Depth) Size(this RigTemplate t) => t switch
    {
        RigTemplate.Floor => (4, 2.5, 8),
        RigTemplate.Stands => (5, 2.5, 10),
        RigTemplate.Bridge => (5, 3, 10),
        RigTemplate.Booth => (6, 3.5, 12),
        RigTemplate.Club => (10, 4.5, 15),
        RigTemplate.Stage => (16, 7, 25),
        _ => (10, 4.5, 15),
    };

    /// A rig name still one of the templates' own (or empty) follows the template chosen; one typed stays.
    public static bool IsDefaultName(string name) => name.Length == 0 || All.Any(t => name.StartsWith(t.RawValue(), StringComparison.Ordinal));
}
