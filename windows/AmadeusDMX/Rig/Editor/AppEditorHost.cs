// The app as the rig editor's host: the AppModel's setup service and API, its sets, and the browser.
using System.Diagnostics;

namespace AmadeusDMX;

public sealed class AppEditorHost(AppModel model) : IRigEditorHost
{
    readonly SetupEditorAPI _api = new(model.Api);

    public Task<bool> EnsureSetupService() => model.EnsureSetupService();
    public IRigEditorAPI Api => _api;
    public void ReloadSets() => model.ReloadSets();

    /// Opened with the program Windows has for it (the browser, for the hang sheet's HTML).
    public void Open(string path)
    {
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })?.Dispose(); }
        catch (System.ComponentModel.Win32Exception) { }
    }
}
