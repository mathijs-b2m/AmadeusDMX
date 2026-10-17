// Owns the renderer for a view's lifetime and lets the pages talk to it (mac/.../Render/StageView.swift's
// StageController), and the rig editor's hooks into the stage (StageEditing).
using Windows.System;
using Frame = AmadeusKit.Frame;   // not WinUI's Frame

namespace AmadeusDMX;

/// A key on the stage, for the rig editor (the Mac passes the NSEvent). `Code`: the key's position (scan code,
/// StageRenderer.Key); `Key`: what it means in the keyboard layout.
public readonly record struct StageKey(VirtualKey Key, ushort Code, bool Shift, bool Control, bool Alt, bool Repeat);

/// The rig editor: gets first go at clicks, drags and keys on the stage. Rays are world-space (metres): the eye
/// and the direction through the pointer.
public interface StageEditing
{
    /// A click: true if it grabbed something (then drags move it instead of the camera). `extend`: Shift held.
    bool Pick(System.Numerics.Vector3 origin, System.Numerics.Vector3 dir, bool extend);
    /// A drag of what Pick grabbed; `free`: Alt held.
    void Drag(System.Numerics.Vector3 origin, System.Numerics.Vector3 dir, bool free);
    void EndDrag();
    void ClickedEmpty();
    /// A key while the stage has focus: true if the editor used it.
    bool Key(StageKey e);
    /// Something dragged in from elsewhere (text, e.g. fixture ids) is over / dropped on the stage.
    void DropHover(System.Numerics.Vector3 origin, System.Numerics.Vector3 dir) { }
    bool Drop(string payload, System.Numerics.Vector3 origin, System.Numerics.Vector3 dir) => false;
    void DropEnded() { }
    /// The pointer moved over the stage (no button down).
    void Hover(System.Numerics.Vector3 origin, System.Numerics.Vector3 dir) { }
}

public sealed class StageController : Observable
{
    public StageRenderer? Renderer { get; private set; }
    internal StageView? View;

    CameraPreset _preset = CameraPresets.FromRawValue(Defaults.Standard.String("camera")) ?? CameraPreset.FrontOfHouse;  // -camera Plan / Drone … (development)
    public CameraPreset Preset
    {
        get => _preset;
        set { if (Set(ref _preset, value)) Renderer?.SetPreset(value); }
    }

    double _haze = 0.6;
    public double Haze { get => _haze; set { if (Set(ref _haze, value) && Renderer is { } r) r.Haze = (float)value; } }

    double _exposure = 1.0;
    public double Exposure { get => _exposure; set { if (Set(ref _exposure, value) && Renderer is { } r) r.Exposure = (float)value; } }

    bool _autoOrbit;
    public bool AutoOrbit { get => _autoOrbit; set { if (Set(ref _autoOrbit, value) && Renderer is { } r) r.AutoOrbit = value; } }

    bool _fly;
    /// Fly through the room: you are the camera.
    public bool Fly
    {
        get => _fly;
        set
        {
            if (!Set(ref _fly, value)) return;
            if (Renderer is { } r) r.Fly = value;
            if (value) View?.FocusForKeys();   // the keys go to the stage
        }
    }

    float _workLight;
    public float WorkLight { get => _workLight; set { _workLight = value; if (Renderer is { } r) r.WorkLight = value; } }

    WallScene _wallScene = WallScene.Auto;
    public WallScene WallScene { get => _wallScene; set { if (Set(ref _wallScene, value) && Renderer is { } r) r.WallScene = value; } }

    Func<(StageInput?, Frame?)>? _input;
    public Func<(StageInput?, Frame?)>? Input { get => _input; set { _input = value; if (Renderer is { } r) r.Input = value; } }

    IReadOnlySet<string> _highlight = new HashSet<string>();
    public IReadOnlySet<string> Highlight { get => _highlight; set { _highlight = value; if (Renderer is { } r) r.Highlight = value; } }

    StageEditing? _editor;
    public StageEditing? Editor { get => _editor; set => _editor = value; }

    public void SetPreset(CameraPreset p) => Preset = p;

    internal void Attach(StageRenderer r)
    {
        Renderer = r;
        r.Input = Input;
        r.Highlight = Highlight;
        r.Haze = (float)Haze;
        r.Exposure = (float)Exposure;
        r.AutoOrbit = AutoOrbit;
        r.Fly = Fly;
        r.WorkLight = WorkLight;
        r.WallScene = WallScene;
        r.SetPreset(Preset, animated: false);
    }

    internal void Detach(StageRenderer r)
    {
        if (Renderer == r) Renderer = null;
    }
}
