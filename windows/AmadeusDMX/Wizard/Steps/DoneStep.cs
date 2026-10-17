// Wizard: saved; what to do next (mac/Sources/AmadeusDMX/Wizard/Steps/DoneStep.swift).
namespace AmadeusDMX;

public static class DoneStep
{
    public static UIElement Build(WizardModel w) =>
        UI.VStack(18,
            StepHeader.Build("checkmark.seal.fill", $"“{w.Name}” on “{(w.UseExistingRig ? w.ExistingRig : w.RigName)}” Is Ready",
                w.AutoMount
                    ? "Both are selected in the main window. Check where everything hangs on the Rig page, then start the show with Ctrl+R or try a track (Ctrl+O)."
                    : "Both are selected in the main window. Your fixtures wait in front of the stage: drag them onto the trusses on the Rig page."),
            Feature.Build("dot.radiowaves.left.and.right", "Connect your DJ software",
                "VirtualDJ: install the AmadeusLink plugin (Settings › Integrations) and add it as master effect. Mixxx or djay Pro: choose it in the Start menu."),
            Feature.Build("light.overhead.right", "Check the patch",
                "The Set page lists every fixture with its DMX address; Identify lights one on the real rig."),
            Feature.Build("square.split.bottomrightquarter", "Another venue?",
                "Make a rig for it (Rig › New Rig…) and mount the same set on it."));
}
