// The rig editor on the 3D stage: Render's StageController and StageView behind IEditorStage, and the editor
// handed to the stage view as its StageEditing (the keys translated to the editor's EditorKey).
using System.ComponentModel;
using System.Numerics;
using Windows.Foundation;

namespace AmadeusDMX;

public sealed class D3DEditorStage : IEditorStage
{
    readonly StageController _controller = new();
    readonly StageView _view;
    IStageEditing? _editor;

    public D3DEditorStage()
    {
        _view = new StageView(_controller);
        _controller.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(StageController.Fly)) PropertyChanged?.Invoke(this, new(nameof(Fly)));
        };
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    static bool? _available;
    /// Direct3D 11 is there (tried once): else the editor uses the plan view.
    public static bool Available => _available ??= StageRenderer.Make() is { } r && Dispose(r);
    static bool Dispose(StageRenderer r) { r.Dispose(); return true; }

    public FrameworkElement View => _view;

    public Func<(StageInput? Input, AmadeusKit.Frame? Frame)>? Input
    {
        get => _controller.Input is { } f ? () => f() : null;
        set => _controller.Input = value is { } f ? () => f() : null;
    }

    public IStageEditing? Editor
    {
        get => _editor;
        set { _editor = value; _controller.Editor = value is null ? null : new Editing(value); }
    }

    public string Preset
    {
        get => _controller.Preset.RawValue();
        set { if (CameraPresets.FromRawValue(value) is { } p) _controller.Preset = p; }
    }

    public bool Fly { get => _controller.Fly; set => _controller.Fly = value; }
    public bool CanFly => true;

    public float WorkLight { get => _controller.WorkLight; set => _controller.WorkLight = value; }

    // the renderer's points have their origin bottom-left, like AppKit's
    public (Vector3 Origin, Vector3 Dir) Ray(Point p, Size size) =>
        _controller.Renderer?.Ray(new Vector2((float)p.X, (float)(size.Height - p.Y)), new Vector2((float)size.Width, (float)size.Height))
        ?? (new Vector3(0, 0, 30), new Vector3(0, 0, -1));

    public void Wake() => _controller.Renderer?.Wake();

    sealed class Editing(IStageEditing editor) : StageEditing
    {
        public bool Pick(Vector3 origin, Vector3 dir, bool extend) => editor.Pick(origin, dir, extend);
        public void Drag(Vector3 origin, Vector3 dir, bool free) => editor.Drag(origin, dir, free);
        public void EndDrag() => editor.EndDrag();
        public void ClickedEmpty() => editor.ClickedEmpty();
        public bool Key(StageKey e) => editor.Key(EditorKeys.From(e.Key) with { Shift = e.Shift, Alt = e.Alt, Control = e.Control });
        public void DropHover(Vector3 origin, Vector3 dir) => editor.DropHover(origin, dir);
        public bool Drop(string payload, Vector3 origin, Vector3 dir) => editor.Drop(payload, origin, dir);
        public void DropEnded() => editor.DropEnded();
        public void Hover(Vector3 origin, Vector3 dir) => editor.Hover(origin, dir);
    }
}
