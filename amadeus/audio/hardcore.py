"""Hardcore's sound, for the genre call: how much the track sounds like hardcore to EffNet-Discogs.

Hardcore (Rotterdam gabber, happy hardcore, speedcore: 160–200+ BPM) has a distorted kick on every beat. The tempo
alone doesn't tell it: it overlaps drum and bass, and hardstyle (150–160) has the same hard kick. The sound does.
The hardcore family is Gabber, Happy Hardcore, Hardcore and Speedcore, in the Electronic styles (Rock---Hardcore is
a punk band). Three facts:

- **hardcore**: the family's probability, on average over the track (styles aren't exclusive: it can pass 1);
- **hardcore_lead**: the share of the track where it beats what it is mistaken for: hardstyle and drum and bass;
- **happy**: Happy Hardcore's share of the family. The genre's two faces: the piano, the singer and the rave colours
  of Paul Elstak's "Rainbow in the Sky", or the black, red and white of Thunderdome.

Measured over 244 cached tracks: hardcore 0.67–1.65 leading ≥ 0.83 (Paul Elstak, Party Animals, Dune, Music Instructor,
a Dimitri Vegas hardcore remix), the nearest other 0.45 leading 0.42 (a track called GABBER that is hardstyle), then
everything ≤ 0.16: real hardstyle (Headhunterz, Max Enforcer) 0.11–0.16 leading ≤ 0.11.
"""

from __future__ import annotations

import numpy as np

SOUND, LEAD = 0.5, 0.6  # a track that sounds like hardcore this much, and leads this share of it, is hardcore
BPM = (150.0, 230.0)  # its tempo: the old Rotterdam sound and Elstak's first records to fast gabber and frenchcore
HAPPY = "Electronic---Happy Hardcore"
FAMILY = ("Electronic---Gabber", HAPPY, "Electronic---Hardcore", "Electronic---Speedcore")
RIVALS = {
    "hardstyle": ("Electronic---Hardstyle", "Electronic---Jumpstyle"),
    "dnb": ("Electronic---Drum n Bass", "Electronic---Jungle", "Electronic---Breakcore"),
}


def heard(f: dict) -> bool:
    """Does the track sound like hardcore (whatever tempo was counted)?"""
    return f.get("hardcore", 0.0) >= SOUND and f.get("hardcore_lead", 0.0) >= LEAD


def judge(styles: np.ndarray, names: list[str]) -> dict:
    """From the Discogs style probabilities per judgement ((n, 400)): {"hardcore", "hardcore_lead", "happy"}."""
    family = styles[:, [names.index(c) for c in FAMILY]].sum(1)
    rivals = np.stack([styles[:, [names.index(c) for c in fam]].sum(1) for fam in RIVALS.values()])
    mean = float(family.mean())
    return {
        "hardcore": round(mean, 2),
        "hardcore_lead": round(float((family > rivals.max(0)).mean()), 2),
        "happy": round(float(styles[:, names.index(HAPPY)].mean()) / mean, 2) if mean > 0 else 0.0,
    }
