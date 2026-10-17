// The editor's stage: the seam to the renderer (IEditorStage.cs). It sets the stage up the way RigEditorView.swift
// does on appear (work light on, the editor first for the pointer, the editor's scene as the input, the drone's
// view) and wakes it whenever the editor changes something the stage shows.
namespace AmadeusDMX;

public sealed class EditorViewport
{
    /// Makes the editor's stage: the 3D one, or the plan view when the 3D stage can't be made (no Direct3D 11).
    public static Func<IEditorStage> MakeStage { get; set; } =
        () => D3DEditorStage.Available ? new D3DEditorStage() : new PlaceholderStage();

    /// The camera buttons under the stage (Swift: CameraPreset .plan, .drone, .frontOfHouse, .side and their symbols).
    public static readonly (string Preset, string Symbol)[] CameraPresets =
        [("Plan", "square.grid.3x3"), ("Drone", "airplane"), ("Front of House", "person.2"), ("Side", "arrow.left.and.right")];

    readonly RigEditorModel _editor;
    public IEditorStage Stage { get; }

    public EditorViewport(RigEditorModel editor)
    {
        _editor = editor;
        IEditorStage stage;
        try { stage = MakeStage(); }
        catch (Exception e) when (e is not OutOfMemoryException) { stage = new PlaceholderStage(); }
        Stage = stage;
        Stage.WorkLight = 1;
        Stage.Editor = editor;
        Stage.Input = () => (editor.StageInput(), null);
        Stage.Preset = "Drone";
    }

    public string Preset
    {
        get => Stage.Preset;
        set => Stage.Preset = value;
    }

    public FrameworkElement Build() =>
        Stage.View.Bind(_editor, [nameof(RigEditorModel.Version), nameof(RigEditorModel.Selection), nameof(RigEditorModel.DropTarget)],
                        _ => Stage.Wake());
}
