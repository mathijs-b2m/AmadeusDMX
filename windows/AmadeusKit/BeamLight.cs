// How bright a head's beam is drawn (mac/Sources/AmadeusKit/BeamLight.swift; the same model in web/js/visualiser.js).
//
// A beam is drawn at its real beam angle (where the light is half the centre's), with a faint cone out to its field
// angle (where it fades out). Its light is the engine's `flux` (amadeus/engine/realism.py beam_info): the same light
// spread over a wider beam is dimmer. In the haze a shaft is as bright as its light over its width there, so it
// fades as it widens with the throw; a spot on a surface is as bright as its light over its size, so a spot far
// away is bigger and dimmer. Both are against a reference beam, a 4° beam 4 m out (gain 1).
namespace AmadeusKit;

public static class BeamLight
{
    /// The reference beam's radius: 4° wide, 4 m from the lens.
    public static readonly float RefRadius = 4 * MathF.Tan(2 * MathF.PI / 180);
    /// The field cone's light against the beam's own (the 10 % edge, a faint glow round the beam).
    public const float FieldGlow = 0.12f;
    /// The most a narrow beam close to its lens is brightened (it would blow out the whole picture).
    public const float MaxGain = 3;
    /// Field angle over beam angle when the fixture doesn't say (a smooth lens).
    public const double Field = 1.8;
    /// The light that counts as the reference (a Sharpy's), and how far a head may fall short of it or exceed it.
    public const double RefLumens = 1500.0;

    /// The haze shaft's strength (the spot's is 0.8): tuned so a show keeps its overall brightness.
    public const float Haze = 0.3f;
    /// The field cone's angle: the beam angle times the field ratio, at most 30° wider (a wide wash's glow stays round it).
    public static float FieldDeg(float beamDeg, float field) => MathF.Min(beamDeg * field, beamDeg + 30);

    /// How bright light spread to this radius is, against the reference beam.
    public static float Gain(float radius) => MathF.Min(MaxGain, RefRadius / MathF.Max(radius, 0.02f));

    /// A head's light against the reference beam, from its lumens (engine: realism.beam_info).
    public static double Flux(double? lumens)
    {
        if (lumens is not { } l || l <= 0) return 1;
        return Math.Min(2.5, Math.Max(0.25, Math.Sqrt(l / RefLumens)));
    }
}
