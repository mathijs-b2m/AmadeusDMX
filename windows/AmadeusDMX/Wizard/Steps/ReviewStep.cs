// Wizard: the set, the rig and how the set goes on it, before anything is made
// (mac/Sources/AmadeusDMX/Wizard/Steps/ReviewStep.swift).
namespace AmadeusDMX;

public static class ReviewStep
{
    public static UIElement Build(WizardModel w)
    {
        var name = UI.Field(L("Set name"), w.Name, v => w.Name = v).MinWidth(220);
        var fixtures = UI.VStack(2, [.. w.Planned.Select(p => (UIElement)UI.Text($"{p.Count}× {p.Entry.Model}").Align(HorizontalAlignment.Right))]);
        var rig = w.UseExistingRig
            ? new List<UIElement?> { Value(L("Rig"), w.ExistingRig) }
            :
            [
                Value(L("Rig"), $"{w.RigName}: {w.Template.Title().ToLower(Strings.Culture)}"),
                Value(L("Size"), w.Template == RigTemplate.Floor ? L("{0:0.###} m wide", w.Width) : L("{0:0.###} m wide, trusses at {1:0.###} m", w.Width, w.Height)),
                Value(L("LED wall"), w.LedWall ? L("Yes") : L("No")),
            ];
        return UI.VStack(16,
            StepHeader.Build("checklist", L("Ready to Create"),
                L("Your set (the fixtures) goes on the rig (the venue). Later you can mount the same set on other rigs.")),
            Form.Section(L("1 · The set"),
            [
                Form.Row(L("Set name"), name),
                Value(L("DMX output"), w.OutputText),
                Form.Row(L("Fixtures"), fixtures),
                Value(L("Director"), w.Directors.FirstOrDefault(d => d.Value == w.Director)?.Label ?? w.Director),
            ]),
            Form.Section(L("2 · The rig"), rig),
            Form.Section(L("3 · On the rig"), [Value(L("Fixtures"), w.AutoMount ? L("Auto-mounted") : L("Placed by hand in the rig editor"))]));
    }

    static Stack Value(string label, string value) => Form.Row(label, UI.Text(value).Secondary());
}
