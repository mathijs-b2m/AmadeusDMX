// Wizard step 2: the set, your fixtures (after the DMX output): search the libraries, choose the mode and how many of each
// (mac/Sources/AmadeusDMX/Wizard/Steps/FixturesStep.swift).
namespace AmadeusDMX;

public sealed class FixturesStep(AppModel model, WizardModel w)
{
    readonly TextBox _query = new() { PlaceholderText = "e.g. beamz fuze, mac encore, laserworld", BorderThickness = new Thickness(0) };
    CancellationTokenSource? _typing;

    public UIElement Build()
    {
        _query.Text = w.Query;
        _query.TextChanged += (_, _) => { w.Query = _query.Text; Typed(); };
        _query.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) { _typing?.Cancel(); _ = w.Search(model.Api); } };
        var spinner = UI.Spinner().Bind(w, nameof(WizardModel.Searching), s => s.Visible(w.Searching));
        var field = new Border
        {
            Child = UI.HStack(8, UI.Icon("magnifyingglass").Secondary(), _query.Grow(), spinner).Padding(9, 4),
            CornerRadius = new CornerRadius(9), Background = Theme.Brush("ControlFillColorSecondaryBrush"),
        };
        return UI.VStack(14,
            StepHeader.Build("light.overhead.right.fill", "Your Fixtures",
                "The gear you bring to every gig: your set. Search our library, QLC+ and the Open Fixture Library by brand or model. Where they hang comes next."),
            field,
            UI.Live(w, Results, nameof(WizardModel.Results)),
            UI.Live(w, Planned, nameof(WizardModel.Planned), nameof(WizardModel.Results)));
    }

    /// Searches once typing pauses (SwiftUI's .task(id: query) with a sleep).
    async void Typed()
    {
        _typing?.Cancel();
        var cts = _typing = new CancellationTokenSource();
        try { await Task.Delay(350, cts.Token); }
        catch (TaskCanceledException) { return; }
        await w.Search(model.Api);
    }

    UIElement? Results()
    {
        if (w.Results.Count == 0) return null;
        var list = UI.VStack(0);
        foreach (var e in w.Results.Take(6))
        {
            list.Children.Add(UI.HStack(8,
                UI.Icon(AddToSetSheet.Icon(e)).Secondary().Frame(width: 22),
                UI.VStack(1,
                    UI.Text($"{e.Manufacturer} {e.Model}"),
                    UI.Text(string.Join(" · ", new[] { e.Type, e.Look, e.IsLocal ? "in your library" : e.Source?.ToUpperInvariant() }.OfType<string>()),
                            Font.Caption).Secondary()).Grow(),
                UI.Button("Add", () =>
                {
                    _ = w.Add(e, model.Api);
                    _typing?.Cancel();
                    _query.Text = "";
                    w.Results = [];
                })).Padding(8, 6));
            list.Children.Add(UI.Divider());
        }
        return new Border { Child = list, CornerRadius = new CornerRadius(9), Background = Theme.Brush("CardBackgroundFillColorDefaultBrush") };
    }

    UIElement? Planned()
    {
        if (w.Planned.Count == 0) return w.Results.Count == 0 ? UI.Text("No fixtures yet.").Secondary() : null;
        var list = UI.VStack(8, [.. w.Planned.Select(p =>
        {
            var row = UI.HStack(10,
                UI.Icon(AddToSetSheet.Icon(p.Entry)).Foreground(Tint.Accent).Frame(width: 22),
                UI.Text($"{p.Entry.Manufacturer} {p.Entry.Model}").Lines(1).Grow(),
                p.Modes.Count > 1 ? UI.Picker(p.Modes, p.Mode, m => m, m => { p.Mode = m; w.PlannedChanged(); }).Frame(width: 110) : null,
                Form.Stepper(p.Count, 1, 120, v => $"{v}×", v => { p.Count = v; w.PlannedChanged(); }).Frame(width: 120),
                UI.IconButton("minus.circle.fill", "Remove", () => w.Remove(p)));
            return (UIElement)UI.Card(row, padding: 10);
        })]);
        if (Capacity() is { } c) list.Children.Add(c);
        return list;
    }

    /// The universes the fixtures take against what the DMX output carries.
    UIElement? Capacity()
    {
        var need = w.UniversesNeeded;
        if (w.UniversesAvailable is { } have && need > have)
            return Form.Note("exclamationmark.triangle.fill",
                $"{need} universes needed, {w.OutputText} carries {have}. The fixtures past universe {have} stay dark: take fewer, a smaller mode, or go back and tick another node.",
                Tint.Orange);
        if (need > 0)
            return Form.Note("cable.connector", $"{need} universe{(need == 1 ? "" : "s")}"
                + (w.UniversesAvailable is { } a ? $" of the {a} on {w.OutputText}" : w.OutputKind == WizardModel.Output.Visualiser ? " (visualiser only)" : ""));
        return null;
    }
}
