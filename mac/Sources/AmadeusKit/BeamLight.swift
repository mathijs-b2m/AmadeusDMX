// How bright a head's beam is drawn (same model in windows/AmadeusKit/BeamLight.cs and web/js/visualiser.js).
//
// A beam is drawn at its real beam angle (where the light is half the centre's), with a faint cone out to its field
// angle (where it fades out). Its light is the engine's `flux` (amadeus/engine/realism.py beam_info): the same light
// spread over a wider beam is dimmer. In the haze a shaft is as bright as its light over its width there, so it
// fades as it widens with the throw; a spot on a surface is as bright as its light over its size, so a spot far
// away is bigger and dimmer. Both are against a reference beam, a 4° beam 4 m out (gain 1).
import Foundation

public enum BeamLight {
    /// The reference beam's radius: 4° wide, 4 m from the lens.
    public static let refRadius: Float = 4 * tan(2 * .pi / 180)
    /// The field cone's light against the beam's own (the 10 % edge, a faint glow round the beam).
    public static let fieldGlow: Float = 0.12
    /// The most a narrow beam close to its lens is brightened (it would blow out the whole picture).
    public static let maxGain: Float = 3
    /// Field angle over beam angle when the fixture doesn't say (a smooth lens).
    public static let field = 1.8
    /// The light that counts as the reference (a Sharpy's), and how far a head may fall short of it or exceed it.
    public static let refLumens = 1500.0

    /// The haze shaft's strength (the spot's is 0.8): tuned so a show keeps its overall brightness.
    public static let haze: Float = 0.3
    /// The field cone's angle: the beam angle times the field ratio, at most 30° wider (a wide wash's glow stays round it).
    public static func fieldDeg(_ beamDeg: Float, _ field: Float) -> Float { min(beamDeg * field, beamDeg + 30) }

    /// How bright light spread to this radius is, against the reference beam.
    public static func gain(radius: Float) -> Float { min(maxGain, refRadius / max(radius, 0.02)) }

    /// A head's light against the reference beam, from its lumens (engine: realism.beam_info).
    public static func flux(lumens: Double?) -> Double {
        guard let lumens, lumens > 0 else { return 1 }
        return min(2.5, max(0.25, (lumens / refLumens).squareRoot()))
    }
}
