"""Disco's sound, for the genre call: how much the track sounds like disco to EffNet-Discogs.

Disco's beat is house's (four to the floor, an open hat on every "and", 110–130 BPM), so the rhythm can't tell
them apart; the sound can: the bass guitar's octaves, strings and horns, a band's swing. EffNet-Discogs
(amadeus/audio/instruments.py) judges about two seconds of the mix at a time against 400 Discogs styles; the
disco family is Disco (Electronic and Funk / Soul), Euro-, Italo- and Nu-Disco and Boogie. Two facts:

- **disco**: the family's probability, on average over the track;
- **disco_lead**: the share of the track where it beats the families disco is mistaken for: funk and soul
  (Afrobeat, P.Funk, Jazz-Funk …) and house (Deep, Tech, Progressive …).

Measured over 75 cached tracks: disco (Chemise, Klein & M.B.O., I Coccodrilli) 0.39–0.76 and leading 0.64–0.98;
house 0.02–0.33, leading ≤ 0.18; afrobeat-funk 0.44 but leading 0.14; reggaeton, techno, hip-hop ≤ 0.02.

Judged with the other sounds (amadeus/audio/sound.py).
"""

from __future__ import annotations

import numpy as np

FAMILIES = {
    "disco": ("Electronic---Disco", "Electronic---Euro-Disco", "Electronic---Italo-Disco", "Electronic---Nu-Disco",
              "Funk / Soul---Disco", "Funk / Soul---Boogie"),
    "funk": ("Funk / Soul---Funk", "Funk / Soul---P.Funk", "Funk / Soul---Afrobeat", "Jazz---Afrobeat",
             "Jazz---Jazz-Funk", "Funk / Soul---Free Funk", "Funk / Soul---Soul"),
    "house": ("Electronic---House", "Electronic---Deep House", "Electronic---Tech House",
              "Electronic---Progressive House", "Electronic---Tropical House"),
}  # fmt: skip


def judge(styles: np.ndarray, names: list[str]) -> dict:
    """From the Discogs style probabilities per judgement ((n, 400)): {"disco", "disco_lead"}."""
    mass = np.stack([styles[:, [names.index(c) for c in fam]].sum(1) for fam in FAMILIES.values()])
    return {"disco": round(float(mass[0].mean()), 2), "disco_lead": round(float((mass.argmax(0) == 0).mean()), 2)}
