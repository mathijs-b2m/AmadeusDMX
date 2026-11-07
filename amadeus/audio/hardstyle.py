"""Hardstyle, heard: its sound for the genre call, its form, and its kick.

**Sound.** Hardstyle's tempo is psytrance's (150 BPM) and its vocals make it a pop song to the form check, so the
beat can't call it. EffNet-Discogs hears the distorted kick: over 199 cached tracks hardstyle, gabber and rawstyle
(Headhunterz, Frontliner, DYEN) had 0.65–0.89 of their mass in FAMILY and led RIVALS 59–78% of the time; everything
else stayed under 0.5 or under 0.45 lead. Happy hardcore and donk share the words but not the sound: they are rivals.

**Form.** A hardstyle track is two levels: the climax (kick and bass, flat out) and everything else. The usual
section rules misjudge both, because the kick's distorted tail hides its onsets: in Headhunterz' "Destiny" the loud
pre-climax read as a breakdown (kick_ratio 0.48) and a whisper-quiet break as a groove (the kick "ran" at 15%
loudness). `form` reads the levels instead: a climax is loud and low, what leads into one is its build, and what
is quiet or kickless is a break.

**Kick.** Inside a climax the onset detector finds 4–6 of 8 kicks. The kick is on every beat there, so `grid_kicks`
plays the beat grid, wherever the low end is really there.
"""

from __future__ import annotations

import numpy as np

from amadeus.audio.model import DROP_THRESHOLD, Analysis

FAMILY = ("Electronic---Hardstyle", "Electronic---Jumpstyle", "Electronic---Gabber", "Electronic---Hardcore",
          "Electronic---Speedcore")  # fmt: skip
RIVALS = ("Electronic---Happy Hardcore", "Electronic---Makina", "Electronic---Hands Up", "Electronic---Hard Trance",
          "Electronic---Euro House", "Electronic---Donk", "Electronic---Hard House", "Electronic---Psy-Trance",
          "Electronic---Goa Trance", "Electronic---Techno", "Electronic---Hard Techno", "Electronic---Schranz",
          "Electronic---Trance")  # fmt: skip

CLIMAX_LOUD, CLIMAX_LOW = 65, 70  # a climax: at least this loud and this low, in percentiles of the track
BREAK_LOUD = 40  # quieter than this: a break, whatever the kick detector says
BREAK_KICK = 0.5  # or this little kick
KICK_GAP_DB = 10.0  # a beat is a kick when the low end comes this close to its level in the phrase
KICK_LOOK_S = 0.1  # …just after the beat


def judge(styles: np.ndarray, names: list[str]) -> dict:
    """From the Discogs style probabilities per judgement ((n, 400)): {"hardstyle", "hardstyle_lead"}."""
    mass = styles[:, [names.index(c) for c in FAMILY]].sum(1)
    rivals = styles[:, [names.index(c) for c in RIVALS]].sum(1)
    return {"hardstyle": round(float(mass.mean()), 2), "hardstyle_lead": round(float((mass > rivals).mean()), 2)}


def _climax(p) -> bool:
    return p.drop_score >= DROP_THRESHOLD or (p.loudness_pct >= CLIMAX_LOUD and p.low_pct >= CLIMAX_LOW)


def form(a: Analysis, i: int, section: str) -> str:
    """The section of phrase `i` of a hardstyle track (`section`: what the usual rules made of it)."""
    p = a.phrases[i]
    if _climax(p):
        return "drop"
    if section in ("intro", "outro"):
        return section
    if i + 1 < len(a.phrases) and _climax(a.phrases[i + 1]):
        return "buildup"
    if p.loudness_pct < BREAK_LOUD or p.kick_ratio < BREAK_KICK:
        return "breakdown"
    return "buildup" if section == "buildup" else "groove"


def grid_kicks(a: Analysis, plan, sections: tuple) -> tuple[np.ndarray, np.ndarray]:
    """The kicks (times, strengths) with the phrases in `sections` played off the beat grid: a beat is a kick where
    the low end is there (a stop in the climax stays a stop)."""
    times, strengths = (np.asarray(x, dtype=float) for x in a.onsets["kick"])
    low = np.maximum(a.bands_db["sub"], a.bands_db["bass"])
    look = max(int(KICK_LOOK_S * a.fps), 1)
    for d in plan:
        if d.section not in sections:
            continue
        beats = a.beats[(a.beats >= d.start) & (a.beats < d.end)]
        frames = (beats * a.fps).astype(int)
        frames = frames[(frames >= 0) & (frames < len(low))]
        if not len(frames):
            continue
        levels = np.array([low[f : f + look].max() for f in frames])
        kicks = frames[levels >= np.median(levels) - KICK_GAP_DB] / a.fps
        keep = (times < d.start) | (times >= d.end)
        times = np.concatenate([times[keep], kicks])
        strengths = np.concatenate([strengths[keep], np.ones(len(kicks))])
    order = np.argsort(times)
    return times[order], strengths[order].astype(np.float32)
