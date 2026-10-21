// What the rig editor needs from the app (Swift passes the AppModel): the engine's setup service and the API calls
// it makes through it, reading the sets again after a save, opening a file (the hang sheet) in the browser, and
// whether the light test may light anything (a show running, a set without a DMX output).
// The app's is AppEditorHost (AppModel); the tests fake it.
//
// No WinUI in this file: it is compiled into the kit's tests too.
using AmadeusKit;

namespace AmadeusDMX;

public interface IRigEditorHost
{
    /// Starts the setup service if it isn't running; false if it didn't come up.
    Task<bool> EnsureSetupService();
    IRigEditorAPI Api { get; }
    /// The sets and rigs were saved: read them again.
    void ReloadSets();
    /// A file for people (the hang sheet): opened in the browser.
    void Open(string path);
    /// A show is running (the light test waits for it to stop).
    bool EngineRunning { get; }
    /// The set only feeds the visualiser, no DMX output (true too for a set the app doesn't know).
    bool IsVirtual(string set);
}

/// The setup API calls the editor makes (SetupAPI's, with the layouts as JSON objects).
public interface IRigEditorAPI
{
    Task<(Dictionary<string, Dictionary<string, JSONValue>> Placements, Truss[]? Trusses)> AutomountPlacements(
        IReadOnlyDictionary<string, JSONValue> layout, IReadOnlyList<string>? ids, bool all);
    Task<byte[]> HangSheet(IReadOnlyDictionary<string, JSONValue> layout, string set, string rig);
    Task<HangCheckStep[]> HangCheck(IReadOnlyDictionary<string, JSONValue> layout);
    Task<LightTest> TestLight(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout, bool point);
    Task<LightTest> TestLightFront(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout);
    Task<Dictionary<string, JSONValue>> HangCheckFix(IReadOnlyDictionary<string, JSONValue> layout, string fixture, string fix);
    Task<Dictionary<string, Dictionary<string, JSONValue>>> InOrderPlacements(IReadOnlyDictionary<string, JSONValue> layout);
    Task SaveRigStructure(IReadOnlyDictionary<string, JSONValue> layout, string rig);
    Task SaveRig(IReadOnlyDictionary<string, JSONValue> layout, string rigName, string setName);
}

/// The editor's calls on the engine's setup API.
public sealed class SetupEditorAPI(SetupAPI api) : IRigEditorAPI
{
    public Task<(Dictionary<string, Dictionary<string, JSONValue>> Placements, Truss[]? Trusses)> AutomountPlacements(
        IReadOnlyDictionary<string, JSONValue> layout, IReadOnlyList<string>? ids, bool all) => api.AutomountPlacements(layout, ids, all);

    public Task<byte[]> HangSheet(IReadOnlyDictionary<string, JSONValue> layout, string set, string rig) => api.HangSheet(layout, set, rig);

    public Task<HangCheckStep[]> HangCheck(IReadOnlyDictionary<string, JSONValue> layout) => api.HangCheck(layout);

    public Task<LightTest> TestLight(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout, bool point) =>
        api.TestLight(fixture, on, layout, point);

    public Task<LightTest> TestLightFront(string fixture, bool on, IReadOnlyDictionary<string, JSONValue> layout) =>
        api.TestLightFront(fixture, on, layout);

    public Task<Dictionary<string, JSONValue>> HangCheckFix(IReadOnlyDictionary<string, JSONValue> layout, string fixture, string fix) =>
        api.HangCheckFix(layout, fixture, fix);

    public Task<Dictionary<string, Dictionary<string, JSONValue>>> InOrderPlacements(IReadOnlyDictionary<string, JSONValue> layout) =>
        api.InOrderPlacements(layout);

    public Task SaveRigStructure(IReadOnlyDictionary<string, JSONValue> layout, string rig) => api.SaveRigStructure(layout, rig);

    public Task SaveRig(IReadOnlyDictionary<string, JSONValue> layout, string rigName, string setName) =>
        api.SaveRig(layout, rigName, setName);
}
