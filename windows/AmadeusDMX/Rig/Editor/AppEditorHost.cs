// The app as the rig editor's host: the AppModel's setup service and API, its sets, the show, and the browser.
using System.Diagnostics;

namespace AmadeusDMX;

public sealed class AppEditorHost(AppModel model) : IRigEditorHost
{
    readonly SetupEditorAPI _api = new(model.Api);

    public Task<bool> EnsureSetupService() => model.EnsureSetupService();
    public IRigEditorAPI Api => _api;
    public void ReloadSets() => model.ReloadSets();
    public bool EngineRunning => model.EngineRunning;
    public bool IsVirtual(string set) => model.Sets.FirstOrDefault(s => s.Name == set)?.IsVirtual ?? true;

    /// Opened with the program Windows has for it (the browser, for the hang sheet's HTML).
    public void Open(string path)
    {
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })?.Dispose(); }
        catch (System.ComponentModel.Win32Exception) { }
    }
}
