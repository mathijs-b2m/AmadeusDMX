// The app's pages, the show's state, and what a show does with the computer (the mode).
namespace AmadeusDMX;

public enum Section { Show, Dmx, Set, Rig, Engine, Settings }

public static class SectionExtensions
{
    public static readonly Section[] All = Enum.GetValues<Section>();  // the sidebar's order

    public static string RawValue(this Section s) => s.ToString().ToLowerInvariant();

    public static Section? Parse(string? raw) => raw switch
    {
        "show" => Section.Show, "dmx" => Section.Dmx, "set" or "sets" => Section.Set, "rig" => Section.Rig, "engine" => Section.Engine,
        "settings" => Section.Settings, _ => null,
    };

    public static string Title(this Section s) => s switch
    {
        Section.Show => "Show",
        Section.Dmx => "DMX Output",
        Section.Rig => "Rigs",
        Section.Set => "Sets",
        Section.Engine => "Engine",
        _ => "Settings",
    };

    public static string Symbol(this Section s) => s switch
    {
        Section.Show => "sparkles.tv",
        Section.Dmx => "cable.connector",
        Section.Rig => "square.split.bottomrightquarter",
        Section.Set => "light.overhead.right",
        Section.Engine => "terminal",
        _ => "gearshape",
    };

    /// What the page is for, in a few words (the sidebar's tooltip).
    public static string Help(this Section s) => s switch
    {
        Section.Show => "The show: the stage, the music and the director",
        Section.Dmx => "Your DMX devices (Art-Net and sACN nodes, USB interfaces), and where each universe of the set goes (Ctrl+Shift+D)",
        Section.Rig => "Your rigs (the venues: trusses, stage, zones), and the sets placed on them",
        Section.Set => "Your sets of fixtures: their DMX patch and where the DMX goes",
        Section.Engine => "The engine's log",
        _ => "The engine folder, the director and its AI key, the DJ software integrations (also Ctrl+,)",
    };
}

public enum ShowStateKind
{
    Stopped,
    Starting,
    WaitingForDJ,   // running, the DJ software not sending (yet)
    Live,           // lights follow the mix
    Playing,        // a track played by the engine itself
    Attached,       // an engine started elsewhere (terminal) is sending: we only watch
    Failed,
}

/// What the show engine is doing, as the user sees it (failed: with why).
public readonly record struct ShowState(ShowStateKind Kind, string Reason = "")
{
    public static readonly ShowState Stopped = new(ShowStateKind.Stopped);
    public static readonly ShowState Starting = new(ShowStateKind.Starting);
    public static readonly ShowState WaitingForDJ = new(ShowStateKind.WaitingForDJ);
    public static readonly ShowState Live = new(ShowStateKind.Live);
    public static readonly ShowState Playing = new(ShowStateKind.Playing);
    public static readonly ShowState Attached = new(ShowStateKind.Attached);
    public static ShowState Failed(string why) => new(ShowStateKind.Failed, why);

    public string Title => Kind switch
    {
        ShowStateKind.Stopped => "Stopped",
        ShowStateKind.Starting => "Starting…",
        ShowStateKind.WaitingForDJ => "Waiting for the DJ software",  // (AppModel.ShowTitle names it)
        ShowStateKind.Live => "Live",
        ShowStateKind.Playing => "Playing",
        ShowStateKind.Attached => "Watching",
        _ => "Engine Stopped",
    };

    public string Symbol => Kind switch
    {
        ShowStateKind.Stopped => "stop.circle",
        ShowStateKind.Starting => "hourglass",
        ShowStateKind.WaitingForDJ => "dot.radiowaves.left.and.right",
        ShowStateKind.Live => "waveform",
        ShowStateKind.Playing => "play.circle",
        ShowStateKind.Attached => "eye",
        _ => "exclamationmark.triangle",
    };

    public bool IsActive => Kind is ShowStateKind.Live or ShowStateKind.Playing or ShowStateKind.Attached;

    /// The state's colour (the status dot, the sidebar's footer).
    public Windows.UI.Color Color => Kind switch
    {
        ShowStateKind.Live or ShowStateKind.Playing => Tint.Green,
        ShowStateKind.WaitingForDJ or ShowStateKind.Starting => Tint.Orange,
        ShowStateKind.Attached => Tint.Blue,
        ShowStateKind.Failed => Tint.Red,
        _ => Tint.Gray,
    };
}

/// What a show does with the computer: draw the stage, drive the lights, or both.
public enum ShowMode { Visualise, Perform, Both }

public static class ShowModes
{
    public static readonly ShowMode[] All = Enum.GetValues<ShowMode>();

    public static string RawValue(this ShowMode m) => m.ToString().ToLowerInvariant();

    public static ShowMode? Parse(string? raw) => raw switch
    {
        "visualise" => ShowMode.Visualise, "perform" => ShowMode.Perform, "both" => ShowMode.Both, _ => null,
    };

    public static string Title(this ShowMode m) => m switch
    {
        ShowMode.Visualise => "Visualise Only",
        ShowMode.Perform => "Perform Only",
        _ => "Perform + Visualise",
    };

    public static string Symbol(this ShowMode m) => m switch
    {
        ShowMode.Visualise => "cube.transparent",
        ShowMode.Perform => "light.beacon.max",
        _ => "square.stack.3d.up",
    };

    public static string Detail(this ShowMode m) => m switch
    {
        ShowMode.Visualise => "The 3D stage only: nothing goes to the lights.",
        ShowMode.Perform => "The lights only: no 3D stage, the computer's power goes to the show.",
        _ => "The lights, and the 3D stage alongside.",
    };

    public static bool SendsDMX(this ShowMode m) => m != ShowMode.Visualise;
    public static bool Renders3D(this ShowMode m) => m != ShowMode.Perform;
}
