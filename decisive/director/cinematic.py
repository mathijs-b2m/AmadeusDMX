"""The cinematic director: the arc of a film-score track, phrase by phrase.

In the cinematic program the hits themselves are the show (decisive/engine/cinematic.py plays every one).
What the director decides is the story around them: how loud a part is against the rest of the track and
whether it rises or falls, and from that the section and the colours. Calm passages are cold (ice), swells
warm up, the climaxes burn (fire), and the end goes back to ice. No language model: the music decides.
"""

from __future__ import annotations

import numpy as np

from decisive.audio.model import Analysis
from decisive.director.decision import Decision

NAME = "cinematic"


class CinematicDirector:
    name = NAME

    def decide(self, a: Analysis, i: int, history: list[Decision]) -> Decision:
        p = a.phrases[i]
        loud = np.array([q.loudness_pct for q in a.phrases])
        rank = float(np.mean(loud <= p.loudness_pct))  # 0 = the quietest part of the track, 1 = the loudest
        pos = p.start / a.duration
        rising = p.loudness_slope_db > 1.5 or (
            i + 1 < len(a.phrases) and a.phrases[i + 1].loudness_pct > p.loudness_pct + 20
        )
        if rank >= 0.8:
            section, palette = "drop", "fire"  # the climax
        elif pos > 0.9 and rank < 0.5:
            section, palette = "outro", "ice"
        elif i == 0 or pos < 0.08:
            section, palette = "intro", "ice"
        elif rising:
            section, palette = "buildup", "warm"
        elif rank < 0.35:
            section, palette = "breakdown", "ice"
        else:
            section, palette = "groove", "cool" if rank < 0.6 else "warm"
        return Decision(
            i, p.start, p.end, section, palette,
            par_base="off", par_accent="pulse", trigger="accents", head_light="accents", movement="still",
            formation="mirror", aim="crowd", head_color="base", dynamics="impact" if section == "drop" else "steady",
            beam_fx="open", gobo_style="dots", intensity=min(3, int(rank * 4)), source=NAME,
        )  # fmt: skip
