// Which director decides the show: the rules, OpenAI, or a local decision model in Ollama (which one, and
// where Ollama runs). The choice belongs to the selected set on its rig, like the toolbar's director menu
// (mac/Sources/AmadeusDMX/Settings/DirectorChoiceView.swift).
namespace AmadeusDMX;

public sealed class DirectorChoiceSection(AppModel model)
{
    IReadOnlyList<DirectorOption> _options = [];
    string _current = "rules";
    bool _loading;
    string? _problem;
    string _host = Defaults.Standard.String("ollamaHost") ?? "";
    readonly ContentControl _body = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };
    readonly TextBlock _footer = Form.Footer("");

    IReadOnlyList<DirectorOption> Local => _options.Where(o => o.Value.StartsWith("ollama:", StringComparison.Ordinal)).ToList();
    DirectorOption? Option => _options.FirstOrDefault(o => o.Value == _current);
    DirectorKind Kind => DirectorKinds.Of(_current);

    public FrameworkElement Build()
    {
        var section = Form.Section(UI.Text("Who decides the show", Font.Subheadline).Secondary().Bold(), [_body], _footer);
        Show();
        // read again whenever the show's set or rig changes (SwiftUI's .task(id:))
        return section.Bind(model, [nameof(AppModel.SelectedRig), nameof(AppModel.SelectedSet)], c => { _ = Load(); });
    }

    void Show()
    {
        _footer.Text = model.SelectedSet.Length == 0 ? "Choose a set first."
            : $"For the set {model.SelectedSet} on the rig {model.SelectedRig}, like the director menu in the toolbar. A running show switches at once; tracks already decided keep their plan until they are decided again. Rules: instant, offline. OpenAI: needs the key below, ~1 s per phrase. Local: free and offline in Ollama, slower (~7 s per phrase on a laptop).";
        var kinds = UI.Segmented(DirectorKinds.All, Kind, k => k.Title(), Pick);
        foreach (var b in kinds.Children.OfType<Control>()) b.IsEnabled = model.SelectedSet.Length > 0 && !_loading;
        var rows = new List<UIElement?> { kinds };
        if (Kind == DirectorKind.Local)
        {
            var local = Local;
            var picker = UI.Picker(local, local.FirstOrDefault(o => o.Value == _current) ?? local.FirstOrDefault()!,
                                   o => o.Value[7..] + (o.Available ? "" : $" ({o.Note ?? "not available"})"), o => Choose(o.Value));
            rows.Add(Form.Row("Model", picker));
            var host = Form.Submit("localhost:11434", _host, h => { _host = h; _ = SaveHost(); });
            host.MinWidth = 220;
            rows.Add(Form.Row("Ollama address", host));
        }
        UIElement? status = null;
        if (_problem is { } p) status = Form.Note("exclamationmark.triangle", p, Tint.Orange);
        else if (Option is { } o)
            status = Form.Note(o.Available ? "checkmark.circle" : "exclamationmark.triangle", o.Note ?? o.Label, o.Available ? null : Tint.Orange);
        rows.Add(UI.HStack(8, status?.Grow() ?? UI.Spacer(), UI.Button(_loading ? "Refreshing…" : "Refresh", () => _ = Load()).Disabled(_loading)));
        if (Kind == DirectorKind.Local && Local.Any(o => !o.Available && o.Note?.StartsWith("no decision", StringComparison.Ordinal) == true))
            rows.Add(UI.Text("Models without decision support are listed but can't be chosen: the director needs one that gives probabilities per option (ollama pull nimble).", Font.Callout).Secondary().Wrap());
        _body.Content = UI.VStack(12, [.. rows]);
    }

    async Task Load()
    {
        if (model.SelectedSet.Length == 0) { Show(); return; }
        _loading = true;
        Show();
        try
        {
            if (!await model.EnsureSetupService()) { _problem = "The engine's setup service doesn't start."; return; }
            try { _options = await model.Api.Directors(); }
            catch (Exception e) when (IsApiError(e)) { _options = []; }
            try
            {
                var raw = await model.Api.Rig(model.SelectedRig, model.SelectedSet);
                _current = raw.GetValueOrDefault("director")?.String ?? "rules";
            }
            catch (Exception e) when (IsApiError(e)) { _current = "rules"; }
            if (_current == "ollama") _current = "ollama:nimble";
            _problem = null;
        }
        finally
        {
            _loading = false;
            Show();
        }
    }

    void Pick(DirectorKind k)
    {
        switch (k)
        {
            case DirectorKind.Rules: Choose("rules"); break;
            case DirectorKind.OpenAI: Choose("openai"); break;
            default:
                if (Local.FirstOrDefault(o => o.Available) is { } o) Choose(o.Value);
                else
                {
                    _current = Local.FirstOrDefault()?.Value ?? "ollama:nimble";
                    _problem = Local.FirstOrDefault()?.Note ?? "No local decision model found.";
                    Show();
                }
                break;
        }
    }

    async void Choose(string value)
    {
        if (value == _current && _problem is null) return;
        if (_options.FirstOrDefault(o => o.Value == value) is { Available: false } o)
        {
            _problem = o.Note ?? "Not available right now.";
            Show();
            return;
        }
        var before = _current;
        _current = value;
        Show();
        try
        {
            await model.Api.SetDirector(value, model.SelectedRig, model.SelectedSet);
            _problem = null;
        }
        catch (Exception e) when (IsApiError(e))
        {
            _current = before;
            _problem = $"Couldn't switch: {e.Message}";
        }
        Show();
    }

    async Task SaveHost()
    {
        var h = _host.Trim();
        Defaults.Standard.Set("ollamaHost", h);
        await model.RestartSetupService();  // it lists the models of the Ollama at that address
        await Load();
    }

    static bool IsApiError(Exception e) =>
        e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException;
}
