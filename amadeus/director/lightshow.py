"""The lightshow director: a track played as a show piece, switched on by hand (the night card, `--director
lightshow`), for one song that should be a light show of its own (a demo, a headliner's anthem).

It plays like the cinematic program (amadeus/engine/lightshow.py: every hit by its own fixtures), but the story
around the hits is a **build-up**: the track starts with one section of lights playing everything, and with
every phrase that has the music for it a third of the rig joins with instruments of their own, until the whole
rig plays together (from the third loud phrase on). A quiet part afterwards takes layers away again (a
breakdown), the next loud part brings them all back at once. The colours warm up with the layers: cool, warm, then fire.
"""

from __future__ import annotations

import math

import numpy as np

from amadeus.audio.model import Analysis
from amadeus.director.decision import Decision

NAME = "lightshow"
JOINS_FROM = 0.3  # a phrase at least this loud (its rank in the track) brings more sections in…
JOIN_SHARE = 1 / 3  # …this share of the rig at a time: the whole rig plays from the third loud phrase
FULL_FROM = 0.4  # a phrase this loud wants every section (a quieter one fewer, the quietest one)
CLIMAX = 0.75  # a phrase this loud is the climax


def ranks(a: Analysis) -> np.ndarray:
    """Per phrase, how loud it is against the rest of the track: 0 the quietest, 1 the loudest."""
    loud = np.array([q.loudness_pct for q in a.phrases]) if a.phrases else np.zeros(0)
    return np.array([float(np.mean(loud <= v)) for v in loud])


def layers(a: Analysis, n: int) -> list[int]:
    """Per phrase, how many of the rig's `n` sections play (1..n): never more than the music's loudness asks for
    (a quiet part thins out; from FULL_FROM on, all), and a phrase loud enough brings at most a third of the rig
    that hasn't played yet (the build-up: the whole rig by the third loud phrase). After a breakdown the ones
    that played before come back at once."""
    if n <= 0:
        return [0] * len(a.phrases)
    out, top = [], 1
    for r in ranks(a):
        wants = n if r >= FULL_FROM else 1 + int(round(r / FULL_FROM * (n - 1)))
        k = max(1, min(wants, top + math.ceil(n * JOIN_SHARE) if r >= JOINS_FROM else top))
        top = max(top, k)
        out.append(k)
    return out


class LightshowDirector:
    name = NAME

    def decide(self, a: Analysis, i: int, history: list[Decision]) -> Decision:
        p = a.phrases[i]
        r = ranks(a)
        rank = float(r[i])
        built = float(np.mean(r[: i + 1] >= JOINS_FROM))  # how far the build has come (0..1, roughly)
        pos = p.start / a.duration
        peak_so_far = float(r[:i].max()) if i else 0.0
        if rank >= CLIMAX and (built >= 0.5 or pos > 0.4):
            section, palette = "drop", "fire"
        elif pos > 0.9 and rank < 0.5:
            section, palette = "outro", "ice"
        elif i == 0 or pos < 0.06:
            section, palette = "intro", "cool"
        elif rank < 0.35 and peak_so_far >= CLIMAX:
            section, palette = "breakdown", "ice"
        elif p.loudness_slope_db > 1.5 or (i + 1 < len(a.phrases) and r[i + 1] > rank + 0.25):
            section, palette = "buildup", "warm"
        else:
            section, palette = "groove", "warm" if rank >= 0.5 else "cool"
        return Decision(
            i, p.start, p.end, section, palette,
            par_base="off", par_accent="pulse", trigger="accents", head_light="accents", movement="still",
            formation="mirror", aim="crowd", head_color="base", dynamics="impact" if section == "drop" else "steady",
            beam_fx="open", gobo_style="dots", intensity=min(3, int(rank * 4)), source=NAME,
        )  # fmt: skip
