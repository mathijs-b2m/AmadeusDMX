// The check after hanging, over the stage: the fixture lit now (in the hang sheet's order), where it should be and
// what its beam should do, and what to do when it isn't so: the head mirrored or turned round, or the light at
// another fixture's place (the two swapped). The editor puts it right; Save keeps it.
using Windows.System;

namespace AmadeusDMX;

public sealed class HangCheckPanel(RigEditorModel editor, IRigEditorHost host)
{
    public static readonly IReadOnlyDictionary<string, string> Cause = new Dictionary<string, string>
    {
        ["mirrored"] = "it pans the other way", ["turned"] = "it is turned round", ["both"] = "turned round, and pans the other way",
    };

    static string Capitalised(string s) => s.Length == 0 ? s : char.ToUpperInvariant(s[0]) + s[1..];

    public FrameworkElement Build() => UI.Live(editor, Panel, nameof(RigEditorModel.Check));

    UIElement? Panel()
    {
        if (editor.Check is not { } c || c.Step is not { } step) return null;
        void Go(int i) => _ = editor.MoveCheck(host, i);

        var back = UI.Button("Back", () => Go(c.Index - 1), "chevron.left").Disabled(c.Index == 0)
            .Shortcut(VirtualKey.Left, VirtualKeyModifiers.Control);
        var next = UI.Button(c.Index + 1 < c.Steps.Count ? "Right, Next" : "Right", () => Go(c.Index + 1), "checkmark").Prominent()
            .Disabled(c.Index + 1 >= c.Steps.Count).Shortcut(VirtualKey.Right, VirtualKeyModifiers.Control)
            .Tooltip("It lit at its place, the right way round: the next one (Ctrl+→)");
        var actions = UI.HStack(8, back, next);
        if (step.Faults.Count > 0)
            actions.Children.Add(UI.MenuButton(UI.Text("Beam Goes Elsewhere"), () => UI.Menu([
                .. step.Faults.Select(f => UI.Item($"{Capitalised(f.Seen)}: {Cause.GetValueOrDefault(f.Fix) ?? f.Fix}",
                                                   () => _ = editor.FixCheck(host, f))),
            ])).Tooltip("The head is hung turned round, or pans the other way: say where its beam goes and the app is put right"));
        actions.Children.Add(UI.MenuButton(UI.Text("Lit Somewhere Else"), () => UI.Menu([
            .. c.Steps.Where(o => o.Id != step.Id).Select(o => UI.Item($"At {o.Label} ({o.Id})", () => _ = editor.SwapCheck(host, o))),
        ])).Tooltip("The light came on at another fixture's place: the two swap places here, so you needn't swap them on the truss"));

        var what = step.Dark.Length > 0
            ? UI.Label("eye", $"Not lit by the check ({step.Dark.Trim('.', ',', ';', ':', '!', '?')}): check it by eye.", Font.Callout).Foreground(Tint.Orange)
            : step.Expect.Length > 0 ? UI.Label("light.beacon.max", step.Expect, Font.Callout).Bold()
            : UI.Label("lightbulb.max", "It lights up white.", Font.Callout).Bold();
        var big = UI.Text(step.Label, Font.LargeTitle);
        big.FontSize = 26;
        var panel = UI.VStack(8,
            UI.HStack(8, UI.Label("checklist", "Check the Hang", Font.Headline), UI.Text($"{c.Index + 1} of {c.Steps.Count}").Secondary(), UI.Spacer(),
                      UI.Button("Done", () => _ = editor.StopCheck(host))),
            UI.HStack(10, big, UI.Text($"{step.Id} · {step.Model} · {step.Dmx}").Secondary().Lines(1)),
            UI.Text(step.Where, Font.Callout).Wrap(),
            UI.Text(Capitalised(step.Facing), Font.Callout).Secondary().Wrap(),
            what,
            c.Fixed.TryGetValue(step.Id, out var done)
                ? UI.Label("checkmark.circle.fill", $"Put right: {done}. Save to keep it.", Font.Callout).Foreground(Tint.Green) : null,
            actions,
            c.Output.Length > 0 ? UI.Text(c.Output, Font.Caption).Secondary().Lines(1) : null);
        panel.Alignment = 0;
        return new Border
        {
            Child = panel, Padding = new Thickness(14), CornerRadius = new CornerRadius(16), MaxWidth = 560,
            HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Bottom,
            Background = Theme.Brush("AcrylicInAppFillColorDefaultBrush"), BorderBrush = Theme.Brush("CardStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(1),
        };
    }
}
