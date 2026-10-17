// Wizard: the set, the rig and how the set goes on it, before anything is made
// (mac/Sources/AmadeusDMX/Wizard/Steps/ReviewStep.swift).
namespace AmadeusDMX;

public static class ReviewStep
{
    public static UIElement Build(WizardModel w)
    {
        var name = UI.Field("Set name", w.Name, v => w.Name = v).MinWidth(220);
        var fixtures = UI.VStack(2, [.. w.Planned.Select(p => (UIElement)UI.Text($"{p.Count}× {p.Entry.Model}").Align(HorizontalAlignment.Right))]);
        var rig = w.UseExistingRig
            ? new List<UIElement?> { Value("Rig", w.ExistingRig) }
            :
            [
                Value("Rig", $"{w.RigName}: {w.Template.Title().ToLowerInvariant()}"),
                Value("Size", $"{Format.Number(w.Width)} m wide{(w.Template == RigTemplate.Floor ? "" : $", trusses at {Format.Number(w.Height)} m")}"),
                Value("LED wall", w.LedWall ? "Yes" : "No"),
            ];
        return UI.VStack(16,
            StepHeader.Build("checklist", "Ready to Create",
                "Your set (the fixtures) goes on the rig (the venue). Later you can mount the same set on other rigs."),
            Form.Section("1 · The set",
            [
                Form.Row("Set name", name),
                Form.Row("Fixtures", fixtures),
                Value("Lights", w.OutputText),
                Value("Director", w.Directors.FirstOrDefault(d => d.Value == w.Director)?.Label ?? w.Director),
            ]),
            Form.Section("2 · The rig", rig),
            Form.Section("3 · On the rig", [Value("Fixtures", w.AutoMount ? "Auto-mounted" : "Placed by hand in the rig editor")]));
    }

    static Stack Value(string label, string value) => Form.Row(label, UI.Text(value).Secondary());
}
