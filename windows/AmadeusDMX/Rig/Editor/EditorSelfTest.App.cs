// `-editorSelfTest NAME` in the app: the checks (EditorSelfTest.cs) on the set NAME placed on the rig NAME, then the
// report in %TEMP%\editor-selftest.txt and the app quits. Use copies of a set and a rig: IT SAVES INTO THEM.
namespace AmadeusDMX;

public static partial class EditorSelfTest
{
    /// Called once the app is up (the Mac: AppModel's init, on the main queue's next turn).
    public static void RunIfRequested(AppModel model)
    {
        if (Defaults.Standard.String("editorSelfTest") is not { Length: > 0 } name || model.Workspace is not { } ws
            || RigEditorModel.Create(ws, name, name) is not { } e) return;
        Go(model, ws, e, name);
    }

    static async void Go(AppModel model, Workspace ws, RigEditorModel e, string name)
    {
        List<string> out_;
        try { out_ = await Run(new AppEditorHost(model), ws, e, name); }
        catch (Exception ex) when (ex is not OutOfMemoryException) { out_ = [$"FAIL  the self test stopped  ({ex.Message})"]; }
        try { File.WriteAllText(ReportPath, string.Join("\n", out_)); }
        catch (IOException) { }
        Application.Current.Exit();
    }
}
