// Wizard: find the engine folder and check its Python environment (mac/Sources/AmadeusDMX/Wizard/Steps/EngineStep.swift).
namespace AmadeusDMX;

public sealed class EngineStep(AppModel model)
{
    string? _error;
    readonly ContentControl _checks = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public UIElement Build()
    {
        _checks.Bind(model, nameof(AppModel.Workspace), c => c.Content = Checks());
        return UI.VStack(16,
            StepHeader.Build("shippingbox.fill", "The Engine",
                "The analysis, the director and the DMX output run in the Amadeus DMX engine (Python). The app starts it for you."),
            UI.Card(_checks, padding: 12),
            UI.Text("OpenAI API Key (optional: the rule-based director works without)", Font.Subheadline).Secondary().Bold(),
            UI.Card(new OpenAIKeyView(model).Build(), padding: 12));
    }

    UIElement Checks()
    {
        var ws = model.Workspace;
        var rows = UI.VStack(10);
        if (ws?.IsBuiltIn == true)
            rows.Children.Add(Check.Build(true, "Engine", "Built into the app"));
        else
        {
            rows.Children.Add(Check.Build(ws?.HasPackage == true, "Engine folder", ws?.Root ?? "Not found"));
            rows.Children.Add(Check.Build(ws?.IsValid == true, "Python environment (.venv)", ws?.Python ?? "–"));
        }
        rows.Children.Add(UI.HStack(8,
            UI.Button("Choose Engine Folder…", Choose),
            _error is { } e ? UI.Text(e, Font.Callout).Foreground(Tint.Red) : null));
        return rows;
    }

    async void Choose()
    {
        if (await Dialogs.ChooseFolder(_checks, "Choose") is not { } folder) return;
        _error = model.UseWorkspace(folder) ? null : "No engine in that folder.";
        _checks.Content = Checks();
    }
}

/// A line that is right or not (or optional), with what it found.
public static class Check
{
    public static FrameworkElement Build(bool ok, string text, string detail, bool optional = false)
    {
        var icon = UI.Icon(ok ? "checkmark.circle.fill" : optional ? "circle.dashed" : "xmark.circle.fill");
        if (ok) icon.Foreground(Tint.Green); else if (optional) icon.Secondary(); else icon.Foreground(Tint.Red);
        var d = UI.Text(detail, Font.Caption).Secondary();
        d.TextTrimming = TextTrimming.CharacterEllipsis;
        var row = UI.HStack(10, icon, UI.VStack(1, UI.Text(text), d).Grow());
        row.Alignment = 0;
        return row;
    }
}
