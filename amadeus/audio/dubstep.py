"""Dubstep, heard: its sound for the genre call.

Dubstep's tempo says nothing (Skrillex plays 110, 128, 140 and 145 BPM), and its half-time drops fool the groove
check: a drop of talking growls and stabs doesn't repeat bar after bar the way house does, so "Scary Monsters and
Nice Sprites" and "First of the Year" read as film music (groove 0.33 < 0.35) and "Bangarang" as house.
EffNet-Discogs hears the growl. Over 347 cached tracks (2026-11-26):

- Skrillex' dubstep and brostep ("Right In", "Scary Monsters", "Make It Bun Dem", "First of the Year",
  "Bangarang"): 0.38–0.57 of the mass in Dubstep, at least 0.25 of it in 0.60–0.72 of the judgements;
- his complextro, the same growls on a 128 BPM four to the floor ("Rock n' Roll", "Kill Everybody"): 0.22–0.26
  (in 0.39–0.45);
- everything else at most 0.16 (in 0.24): Flume's future bass, then Brazilian funk 0.12, big-room electro ≤ 0.08.
"""

from __future__ import annotations

import numpy as np

FAMILY = ("Electronic---Dubstep",)
SOUND, SHARE = 0.2, 0.33  # a track this much in the family on average, at least AT_LEAST of it in this share of
AT_LEAST = 0.25  # the judgements, sounds like dubstep


def heard(f: dict) -> bool:
    """Does the track sound like dubstep (whatever its tempo)?"""
    return f.get("dubstep", 0.0) >= SOUND and f.get("dubstep_share", 0.0) >= SHARE


def judge(styles: np.ndarray, names: list[str]) -> dict:
    """From the Discogs style probabilities per judgement ((n, 400)): {"dubstep", "dubstep_share"}."""
    mass = styles[:, [names.index(c) for c in FAMILY]].sum(1)
    return {"dubstep": round(float(mass.mean()), 2), "dubstep_share": round(float((mass >= AT_LEAST).mean()), 2)}


# ---------------------------------------------------------------- form

# Dubstep's drop plays its kick on the one and its snare on the three: a kick on a third of the beats, which the
# usual rules call a break (all of Scary Monsters' drops came out breakdowns). Its levels tell the parts instead,
# measured on the six Skrillex tracks: the drops at 59–93 loudness and 53–88 low end (percentiles of the track),
# the builds into them 33–48, the breaks under 35 or without their low end.
DROP_LOUD, DROP_LOW = 58, 50
BREAK_LOUD, BREAK_LOW = 35, 25


def drop(p) -> bool:
    """A drop: the usual drop score, or the track loud with its low end."""
    from amadeus.audio.model import DROP_THRESHOLD

    return p.drop_score >= DROP_THRESHOLD or (p.loudness_pct >= DROP_LOUD and p.low_pct >= DROP_LOW)


def form(a, i: int, section: str) -> str:
    """The section of phrase `i` of a dubstep track (`section`: what the usual rules made of it)."""
    p = a.phrases[i]
    if drop(p):
        return "drop"
    if section in ("intro", "outro"):
        return section
    if i + 1 < len(a.phrases) and drop(a.phrases[i + 1]) and p.loudness_pct >= BREAK_LOUD - 10:
        return "buildup"
    if p.loudness_pct < BREAK_LOUD or p.low_pct < BREAK_LOW:
        return "breakdown"
    return "buildup" if section == "buildup" else "groove"
