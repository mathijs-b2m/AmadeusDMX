// Where the Show page puts the 3D stage, and the stage's controls (the camera, flying, the LED wall scene, haze,
// exposure) that StageControls turns.
//
// The stage itself (Render/StageView, Render/StageController: the Direct3D port of mac/Sources/AmadeusDMX/Render)
// is written alongside this page; until it is wired in, StageHost.Create returns a placeholder. StageSettings
// holds what Swift's StageController publishes, under the same names, so StageControls works now and the lead
// only has to hand the values on (see Create).
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
        // lead: swap for new Render.StageView(...). What the Swift does with it, call for call:
        //
        //   var controller = new StageController();                      // MainView's @StateObject (one per window)
        //   controller.Input = () => (model.StageInput(), model.Feed.LatestFullFrame);   // ShowView's .onAppear
        //   void Apply() {                                               // StageControls' bindings
        //       controller.Preset = CameraPreset(rawValue: stage.Preset);   // renderer.setPreset(preset)
        //       controller.Haze = stage.Haze;  controller.Exposure = stage.Exposure;
        //       controller.AutoOrbit = stage.AutoOrbit;  controller.Fly = stage.Fly;   // fly: the stage takes the keys (focus it)
        //       controller.WallScene = WallScene(rawValue: stage.WallScene);
        //   }
        //   Apply(); stage.PropertyChanged += (_, _) => Apply();         // (and back: the stage's F / Esc set stage.Fly)
        //   return new StageView(controller);                            // .ignoresSafeArea(): edge to edge, under the cards
        //
        // The stage adds its GPU time to model.Power (Sidebar's power meter), as on the Mac.
        _ = model;
        _ = stage;
        var placeholder = new Grid { Background = Theme.Brush("SolidBackgroundFillColorBaseBrush") };
        placeholder.Children.Add(UI.Text("3D stage", Font.Title3).Secondary().Center().Opacity(0.4));
        return placeholder;
    }
}
