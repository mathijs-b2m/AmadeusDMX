// Where the Show page puts the 3D stage, and the stage's controls (the camera, flying, the LED wall scene, haze,
// exposure) that StageControls turns.
//
// The stage itself is Render/StageView with its StageController (the Direct3D port of mac/Sources/AmadeusDMX/Render).
// StageSettings holds what Swift's StageController publishes, under the same names; Create hands them on.
namespace AmadeusDMX;

/// What the Show page sets on the stage (Swift's StageController's @Published properties).
public sealed class StageSettings : Observable
{
    /// Swift's CameraPreset (Render/Camera.swift): its raw value (the title) and its symbol, in its order.
    public static readonly IReadOnlyList<(string RawValue, string Symbol)> Presets =
    [
        ("Front of House", "person.2"), ("In the Crowd", "person.3.sequence"), ("Drone", "airplane"),
        ("Side", "arrow.left.and.right"), ("DJ", "headphones"), ("Plan", "square.grid.3x3"),
    ];

    /// Swift's WallScene (Render/WallRenderer.swift): raw value, title, symbol.
    public static readonly IReadOnlyList<(string RawValue, string Title, string Symbol)> WallScenes =
    [
        ("auto", "Director's Choice", "wand.and.stars"), ("off", "Off", "rectangle.slash"), ("ambient", "Ambient", "cloud.fog"),
        ("runner", "Runner", "figure.run"), ("dancer", "Dancer", "figure.dance"), ("crowd", "Crowd", "person.3"),
        ("pong", "Pong", "gamecontroller"), ("words", "Words", "textformat.size"), ("equalizer", "Equalizer", "chart.bar"),
        ("psychedelic", "Psychedelic", "circle.hexagongrid"),
    ];

    // -camera Plan / Drone … (development), as on the Mac
    string _preset = Defaults.Standard.String("camera") is { } c && Presets.Any(p => p.RawValue == c) ? c : "Front of House";
    double _haze = 0.6, _exposure = 1.0;
    bool _autoOrbit, _fly;
    string _wallScene = "auto";

    /// The camera preset (CameraPreset's raw value).
    public string Preset { get => _preset; set => Set(ref _preset, value); }
    public double Haze { get => _haze; set => Set(ref _haze, value); }
    public double Exposure { get => _exposure; set => Set(ref _exposure, value); }
    public bool AutoOrbit { get => _autoOrbit; set => Set(ref _autoOrbit, value); }
    /// Fly through the room: you are the camera (the stage takes the keys).
    public bool Fly { get => _fly; set => Set(ref _fly, value); }
    /// The LED wall's scene (WallScene's raw value; "auto": the director's choice).
    public string WallScene { get => _wallScene; set => Set(ref _wallScene, value); }

    public string WallSymbol => WallScenes.FirstOrDefault(s => s.RawValue == WallScene).Symbol ?? "tv";
}

public static class StageHost
{
    /// The 3D stage for the Show page (Swift's `StageView(controller: stage)` in ShowView). Made again whenever
    /// the page switches back from Perform Only (no stage at all meanwhile: nothing drawn 60 times a second).
    public static FrameworkElement Create(AppModel model, StageSettings stage)
    {
        var controller = new StageController { Input = () => (model.StageInput(), model.Feed.LatestFullFrame) };
        bool applying = false;
        void Apply()   // StageControls' bindings
        {
            applying = true;
            if (CameraPresets.FromRawValue(stage.Preset) is { } p) controller.Preset = p;
            controller.Haze = stage.Haze;
            controller.Exposure = stage.Exposure;
            controller.AutoOrbit = stage.AutoOrbit;
            controller.Fly = stage.Fly;
            if (WallScenes.FromRawValue(stage.WallScene) is { } w) controller.WallScene = w;
            applying = false;
        }
        Apply();
        stage.PropertyChanged += (_, _) => Apply();
        // and back: the stage's own F / Esc fly and land
        controller.PropertyChanged += (_, e) =>
        {
            if (!applying && e.PropertyName == nameof(StageController.Fly)) stage.Fly = controller.Fly;
        };
        return new StageView(controller);
    }
}
