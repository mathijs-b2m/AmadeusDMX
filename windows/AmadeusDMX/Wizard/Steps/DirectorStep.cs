// Wizard: the decision model (rules, OpenAI, or a local model) (mac/Sources/AmadeusDMX/Wizard/Steps/DirectorStep.swift).
namespace AmadeusDMX;

public static class DirectorStep
{
    public static UIElement Build(WizardModel w) =>
        UI.VStack(16,
            StepHeader.Build("wand.and.stars", "Who Directs?",
                "Every phrase of every track gets a lighting decision. The engine always starts with a quick rules plan; an AI director then takes over."),
            UI.Live(w, () => Choices(w), nameof(WizardModel.Directors), nameof(WizardModel.Director)));

    static UIElement Choices(WizardModel w)
    {
        if (w.Directors.Count == 0) return UI.HStack(8, UI.Spinner(), UI.Text("Asking the engine…").Secondary());
        return UI.VStack(8, [.. w.Directors.Select(d =>
        {
            var row = UI.HStack(12,
                ChoiceCard.Radio(w.Director == d.Value, d.Available),
                UI.VStack(2, UI.Text(d.Label, Font.Headline), d.Note is { } n ? UI.Text(n, Font.Callout).Secondary().Wrap() : null).Grow());
            row.Alignment = 0;
            var card = ChoiceCard.Build(row, () => { if (d.Available) w.Director = d.Value; }, enabled: d.Available);
            card.Opacity = d.Available ? 1 : 0.5;
            return (UIElement)card;
        })]);
    }
}
