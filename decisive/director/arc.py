"""The song's arc: which drops are the main ones, and how that shapes each phrase's look (lasers, energy)."""

from __future__ import annotations

import re
from pathlib import Path

from decisive.audio.model import DROP_THRESHOLD, Analysis
from decisive.director.decision import Decision, fmt_time

MAIN_DROP_SHARE = 0.92  # a drop with at least this share of the song's biggest drop energy is a main drop


SYNTH_LINE = 0.75  # separated synth notes per beat from which a phrase has a clear synth line


EARLY_SHARE = 0.2  # drops in the first 20% of a song hold back when an equally big drop follows later


def song_arc(a: Analysis) -> list[dict]:
    """Where each phrase sits in the song's dramaturgy, so the show saves its biggest weapons for the
    biggest moment: per phrase its energy relative to the song's biggest drop, and a role:
    main_drop, gentle_drop (an early or smaller drop: hold back), into_main (the build into a main drop),
    peak (the high-energy phrases right after a main drop), early (before the first main drop), other."""
    ph = a.phrases
    energy = [0.55 * p.loudness_pct + 0.45 * p.low_pct for p in ph]
    drops = [i for i, p in enumerate(ph) if p.drop_score >= DROP_THRESHOLD]
    main_level = max([energy[i] for i in drops] or [max(energy or [1.0])]) or 1.0
    early_end = EARLY_SHARE * a.duration
    mains = [
        i
        for i in drops
        if energy[i] >= MAIN_DROP_SHARE * main_level
        and not any(energy[j] > energy[i] + 8 for j in drops if j > i)
        # a drop early in the song, with an equally big one still to come, is not the moment to go all in
        and not (ph[i].start < early_end and any(energy[j] >= energy[i] - 5 for j in drops if j > i))
    ]
    if drops and not mains:
        mains = [max(drops, key=lambda i: energy[i])]
    first_main = mains[0] if mains else len(ph)
    laser_song = bool(re.search(r"la[sz]er", Path(str(a.path)).stem, re.I))  # the track is ABOUT lasers
    out = []
    for i, p in enumerate(ph):
        rel = energy[i] / main_level
        if i in mains:
            role = "main_drop"
        elif i in drops:
            role = "gentle_drop"
        elif i + 1 in mains:
            role = "into_main"
        elif any(m < i <= m + 2 for m in mains) and rel >= 0.9:
            role = "peak"
        elif i < first_main and (drops or p.start < EARLY_SHARE * a.duration):
            role = "early"  # (a track without drops is only "early" in its first part)
        else:
            role = "other"
        out.append(
            {
                "role": role,
                "energy": round(rel, 2),
                "laser_song": laser_song,
                "synth": round(synth_line(a, p), 2),
                "main_at": ph[first_main].start if first_main < len(ph) else None,
            }
        )
    return out


def synth_line(a: Analysis, p) -> float:
    """Notes per beat of the separated synth/melody instrument in a phrase (0 without separation)."""
    if a.synth_notes is None:
        return 0.0
    t, s, _ = a.synth_notes
    sel = (t >= p.start) & (t < p.end) & (s > 0.25)
    beats = max((p.end - p.start) / (60.0 / max(a.bpm, 1.0)), 1.0)
    return float(sel.sum()) / beats


def arc_hint(arc: dict) -> str:
    when = f" (the main drop is at {fmt_time(arc['main_at'])})" if arc.get("main_at") else ""
    if arc.get("laser_song") and arc["role"] in ("early", "gentle_drop", "other"):
        return (
            "Song arc: build the show over the track; the lasers are the star of this track, so use them "
            "wherever the energy is up (not in the quiet edges)."
        )
    return {
        "main_drop": "Song arc: this is a MAIN drop, the song's biggest moment: go all in (the whole rig, big "
        "movement, lasers, maximum intensity).",
        "gentle_drop": f"Song arc: this is a GENTLE drop: only {arc['energy']:.0%} of the energy of the song's "
        f"biggest drop{when}. Hold back: no lasers, moderate movement, not the whole rig at once; "
        "save the full show for the main drop.",
        "into_main": "Song arc: this phrase builds into the MAIN drop. Build with flashing, pulsing light and "
        "accelerating rhythm rather than big movement; lasers may come in late in the build.",
        "peak": "Song arc: the peak right after the main drop: full energy is fine.",
        "early": f"Song arc: early in the song, before its first main drop{when}. Keep something in reserve: "
        "no lasers, moderate intensity; buildups use flashing light, not big movement.",
    }.get(arc["role"], "")


def laser_star(d: Decision, arc: dict, lasers, next_best=None) -> bool:
    """A track about lasers: lasers on wherever the energy is up (the model's next-best look, else a fan)."""
    if not (lasers and arc.get("laser_song")):
        return False
    if d.laser_look != "off":  # the laser sound is the star: the lasers play it
        if arc.get("synth", 0) >= SYNTH_LINE and d.laser_move != "melody":
            d.laser_move = "melody"
            return True
        return False
    if d.section in ("groove", "buildup", "drop") and arc["energy"] >= 0.6:
        d.laser_look = (next_best("laser_look", {"off"}) if next_best else None) or "fan"
        if arc.get("synth", 0) >= SYNTH_LINE:
            d.laser_move = "melody"
        elif d.laser_move == "still":
            d.laser_move = (next_best("laser_move", {"still"}) if next_best else None) or "scan"
        return True
    return False


def apply_arc(d: Decision, arc: dict, lasers, groups, next_best=None) -> bool:
    """Restraint by the song's arc (safety net for both directors). Returns True if something changed."""
    changed = False
    if lasers and d.laser_move == "melody" and arc.get("synth", 0) < 0.3:  # nothing to play: lasers would be dark
        d.laser_move, changed = (next_best("laser_move", {"melody", "still"}) if next_best else None) or "scan", True
    role = arc["role"]
    laser_ok = role in ("main_drop", "into_main", "peak")
    if arc.get("laser_song"):  # a track about lasers: they are the star, everywhere but the quiet edges
        laser_ok = d.section not in ("intro", "outro") and arc["energy"] >= 0.3
    if lasers and d.laser_look != "off" and not laser_ok:
        d.laser_look, changed = "off", True  # lasers only where the song really needs them
    if d.screen == "psychedelic" and role not in ("main_drop", "peak"):
        d.screen, changed = "figure", True  # the full-on visuals are for the biggest moments
    elif role == "main_drop" and d.source == "rules" and d.screen != "off":
        d.screen = "psychedelic"
    if role in ("gentle_drop", "early"):
        if d.intensity > 2:
            d.intensity, changed = 2, True
        if d.movement == "ballyhoo":
            d.movement, changed = "step_on_beat", True
        multi = groups and len(groups) > 1
        if multi and d.grouping == "unison":
            d.grouping, changed = "split", True
        if multi and role == "gentle_drop" and d.layer_split == "none":
            d.layer_split, changed = "alternate", True
    if d.section == "buildup":  # flashing, pulsing light builds better than big movement
        if d.head_light in ("steady", "breathe"):
            d.head_light, changed = "pulse", True
        if d.movement in ("ballyhoo", "figure8", "circle"):
            d.movement, changed = "nod", True
    # the tilt wave and randomly pulsing heads are for medium and intense moments, not for calm ones
    calm = d.section in ("intro", "breakdown", "outro") or d.intensity < 1
    if calm and d.movement == "tilt_wave":
        d.movement, changed = "nod", True
    if calm and d.head_light == "random":
        d.head_light, changed = "breathe", True
    if role == "main_drop" and d.intensity < 3:
        d.intensity, changed = 3, True
    return changed
