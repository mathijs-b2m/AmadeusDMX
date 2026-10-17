// Wizard: what the app does (mac/Sources/AmadeusDMX/Wizard/Steps/WelcomeStep.swift).
namespace AmadeusDMX;

public static class WelcomeStep
{
    public static UIElement Build() =>
        UI.VStack(18,
            StepHeader.Build(null, "Amadeus DMX",
                "An AI lighting director for DJ sets. It listens to the music, plans every phrase and drop, and runs your lights live with your DJ software."),
            Feature.Build("light.overhead.right", "Your rig",
                "Moving heads, pars, lasers, blinders and an LED wall, from the QLC+ and Open Fixture libraries."),
            Feature.Build("wand.and.stars", "A director, not a sound-to-light",
                "Builds-ups, drops and breakdowns get their own looks, with restraint early in a track."),
            Feature.Build("dot.radiowaves.left.and.right", "Live with your DJ software",
                "VirtualDJ, Mixxx or djay Pro tells the engine what plays; the lights follow the mix."));
}
