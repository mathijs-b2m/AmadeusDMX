"""What the director model reads: each phrase described in words, the prompt, and the questions it answers."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from amadeus.audio.model import DROP_THRESHOLD, Analysis, Phrase
from amadeus.director.arc import SYNTH_LINE, arc_hint, song_arc, synth_line
from amadeus.director.decision import Decision, fmt_time
from amadeus.director.style import Style
from amadeus.director.vocabulary import (
    BASE_GLOWS,
    DEFAULT_PALETTES,
    FOG_LEVELS,
    FORMATIONS,
    GROUPINGS,
    INTENSITY_LEVELS,
    LASER_COLORS,
    LASER_LOOKS,
    LASER_MOVES,
    LAYER_SPLITS,
    LAYERS,
    MOVEMENTS,
    PALETTES,
    SCREEN_MODES,
    SECTIONS,
    SPECIALS,
)


def _level(pct: float) -> str:
    return (
        "very low" if pct < 15 else "low" if pct < 35 else "medium" if pct < 65 else "high" if pct < 85 else "very high"
    )


def describe(p: Phrase, prev: Phrase | None = None, riff: float = 0.0) -> str:
    kick = (
        "running on every beat"
        if p.kick_ratio > 0.85
        else "on most beats"
        if p.kick_ratio > 0.6
        else "intermittent"
        if p.kick_ratio > 0.25
        else "absent"
    )
    lines = [
        f"{p.bars} bars, {p.end - p.start:.0f} s, {p.bpm:.0f} BPM.",
        f"Loudness: {_level(p.loudness_pct)} ({p.loudness_pct:.0f}th percentile of the set), "
        f"{p.loudness_slope_db:+.1f} dB from first to last bar.",
        f"Kick drum: {kick} ({p.kick_ratio:.0%} of beats).",
        f"Low end (sub+bass): {_level(p.low_pct)} ({p.low_pct:.0f}th pct). "
        f"Mids: {_level(p.mid_pct)}. Highs: {_level(p.high_pct)}.",
        f"Hi-hats: {p.hat_density:.1f} per beat. Snare/clap: {p.snare_density:.1f} per beat, "
        f"{'rising' if p.snare_trend > 0.4 else 'falling' if p.snare_trend < -0.4 else 'steady'} "
        f"towards the end ({p.snare_trend:+.1f}).",
        f"Brightness: {'rising' if p.brightness_trend > 300 else 'falling' if p.brightness_trend < -300 else 'stable'} "
        f"({p.brightness_trend:+.0f} Hz).",
        f"Steady synth riff on the beat grid: {'clear' if riff >= 0.6 else 'some' if riff >= 0.4 else 'none'} "
        f"(tightness {riff:.2f}).",
        f"Synth stutters/gates (rhythmic chopping of the sound): "
        f"{'strong' if p.stutter > 0.5 else 'some' if p.stutter > 0.25 else 'none'} ({p.stutter:.2f}).",
    ]
    if p.instruments:
        lines.append(f"Melodic instruments (from the separated melodic part): {p.instruments}.")
    if prev is not None:
        lines.append(
            f"Change vs previous phrase: loudness {p.loudness_pct - prev.loudness_pct:+.0f} pct-points, "
            f"low end {p.low_pct - prev.low_pct:+.0f}, kick {prev.kick_ratio:.0%} → {p.kick_ratio:.0%}."
        )
    return "\n".join(lines)


def synth_riff(a: Analysis, p: Phrase) -> float:
    """How much the melodic notes in a phrase form a steady, grid-locked synth riff (0..1).

    Tightness above chance: the share of notes within SYNTH_SNAP_S of the 1/16 grid, corrected for
    the share you'd get with random timing. Vocals and loose notes score ~0; arps and riffs ~0.8+.
    """
    t = a.onsets.get("lead", (np.zeros(0), None))[0]
    t = t[(t >= p.start) & (t < p.end)]
    b = a.beats[(a.beats >= p.start - 1) & (a.beats < p.end + 1)]
    beats_in = max(1, int(((b >= p.start) & (b < p.end)).sum()))
    if len(b) < 3 or len(t) < 0.8 * beats_in:  # too few notes for a riff
        return 0.0
    step = float(np.median(np.diff(b))) / 4
    grid = np.concatenate([b[:-1] + step * q for q in range(4)])
    on = np.mean([np.min(np.abs(grid - x)) < SYNTH_SNAP_S for x in t])
    chance = 2 * SYNTH_SNAP_S / step
    return round(max(0.0, (on - chance) / (1 - chance)), 2)


SYNTH_SNAP_S = 0.02


def drop_scores(a: Analysis) -> list[float]:
    return [p.drop_score for p in a.phrases]


def _look_text(d: Decision) -> str:
    return (
        f"{d.section}: pars {d.par_base} between hits, {d.par_accent} on {d.trigger}; heads {d.head_light} light, "
        f"{d.movement} in {d.formation} formation aimed at the {d.aim}, {d.head_color} colour, "
        f"{d.beam_fx}{f' ({d.gobo_style})' if d.beam_fx in ('gobo', 'gobo_shake', 'gobo_rotate') else ''} beam; "
        f"{d.dynamics}; "
        f"palette {d.palette}"
        + (
            ""
            if d.grouping == "unison"
            else f"; groups: {d.grouping}"
            + (f" (featured {d.featured})" if d.grouping in ("split", "solo") else "")
            + (f", others {d.movement2} in {d.formation2}" if d.grouping == "split" else "")
        )
        + ("" if d.layer_split == "none" else f"; layers: {d.layer_split} with a {d.base_glow} base glow")
        + ("" if d.laser_look == "off" else f"; lasers {d.laser_look} {d.laser_move} in {d.laser_color}")
        + ("" if d.screen == "off" else f"; LED wall {d.screen}")
        + ("" if d.fog == "none" else f"; smoke {d.fog}")
    )


def build_prompt(
    a: Analysis,
    i: int,
    history: list[Decision],
    groups: list[dict] | None = None,
    lasers: list[dict] | None = None,
    screen: bool = False,
    style: Style | None = None,
    theme: str | None = None,
    fog: bool = False,
    outdoor: bool = False,
) -> str:
    phrases = a.phrases
    p = phrases[i]
    prev = phrases[i - 1] if i > 0 else None
    nxt = phrases[i + 1] if i + 1 < len(phrases) else None
    parts = [
        "You are the lighting operator for a DJ set with moving heads and LED pars. Build the look for the "
        "CURRENT phrase from independent layers. Think like a real operator: match the energy of the music, "
        "but keep the show interesting. Within a section, change at least one layer every phrase (a different "
        "trigger, accent style, movement or head colour) instead of repeating the previous look. Contrast is "
        "good: steady beams with moving heads, pars in one colour popping to another, sparse accents in "
        "quiet parts. Use the heads' freedom and make them rhythmic, not only slow: per-beat moves (bounce, "
        "swing, step_on_beat) combined with flick, beat or alternate light give a sharp beat-locked look, and a "
        "tilt wave rolling over the row of heads (light steady, or pulsing at random) is a classic for energetic "
        "grooves and drops; vary "
        "the path, the formation (sync, mirror, wave, fan, focus on one point, cross) and where the beams aim "
        "(crowd, stage, sky), e.g. sky for breakdowns and buildups, focus or cross for big moments. The heads' "
        "default is a plain, crisp OPEN beam, also in calm parts. Use beam effects deliberately for specific "
        "parts, not all the time; frost is a rare exception. A rotating gobo suits calm parts and builds, a gobo "
        "(with a fitting style) or gobo shake for a groove that needs texture, prism or rotating prism for drops. "
        "Keep the palette within a section, and change it at each drop and each breakdown. "
        "Reserve the impact energy curve and Maximum intensity for real drops.",
        f"Set position: {fmt_time(p.start)} of {fmt_time(a.duration)} ({p.start / a.duration:.0%}).",
        f"Track: {Path(str(a.path)).stem} (the title can be a hint for the mood or the show).",
    ]
    if style:
        parts.append(
            f"STYLE: this part of the set is {style.genre}. Its house style, as a LEAN, not a rule: {style.text} "
            f"Keep its colours, so the set looks like one show. For movement and light, let the music of THIS "
            f"phrase decide (a song changes: a quiet piano part, a big drop), leaning towards the style where it fits."
        )
    if groups and len(groups) > 1:
        from amadeus.rig.groups import describe as describe_groups

        n = sum(len(g["ids"]) for g in groups)
        parts.append(
            f"The RIG: {n} moving heads in {len(groups)} groups (positions as the audience sees them):\n"
            + describe_groups(groups)
            + "\n"
            "Every head knows its place in its group and where its group is. This is an audience-scanning show: "
            "most beams sweep over the crowd. Use the groups like a real lighting designer: not all heads doing the "
            "same thing all the time. Vary the grouping: the whole rig in unison for the biggest moments, each "
            "group as its own unit, one group featured against the others (split: the others do a contrasting "
            "counter-movement), only one group performing (solo) to build up and reveal, the light chasing from "
            "group to group, or every head on its own path (individual) for an organic, busy texture. Change the "
            "grouping often (every phrase or two) and save unison for drops and peaks. LAYER the light too: with "
            "this many heads, let part of them hold a soft base glow (every other head, the outer heads, the high "
            "heads, or whole groups) while the others play the accents on the hits; no layering is for unified "
            "moments."
        )
    if screen:
        parts.append(
            "There is an LED WALL behind the DJ. Like a real one, it is often dark and comes in when it adds "
            "something: ambient colour in calm parts, playful outlined characters (a runner, a dancer, a "
            "jumping crowd, pong) or big words in grooves and builds, and full psychedelic visuals only for "
            "the biggest moments. Keep it fun to watch, not only abstract; vary it."
        )
    if outdoor:  # (indoors the prompt is unchanged: the ceiling guard keeps beams off a low ceiling)
        parts.append(
            "This is an OUTDOOR show: there is no ceiling, the night sky is the canvas. Beams up into the sky "
            "(aim 'sky') are a big part of the look here, not only for breakdowns and buildups: tall still beams, "
            "slow fans and sweeps across the sky, a sky full of beams for the big moments. Still bring the beams "
            "down over the crowd for contrast in grooves and drops."
        )
    if fog:
        parts.append(
            "There is a SMOKE MACHINE: haze makes the beams visible (the 'fog' question: how hazy the room "
            "should be in the CURRENT phrase; the program fires the machine, ahead of time and on the beat, sized "
            "to the machine and the room). Smoke lingers for minutes: plan in long arcs, not phrase by phrase. "
            "Clear air in the intro, a light haze for grooves, more for builds and drops, a burst only on the "
            "downbeat of a big drop, and let it clear towards the end."
        )
    if theme == "stars":
        parts.append(
            "This track is ABOUT STARS (it is in the title): you have a special STARFIELD look (the 'special' "
            "question). Switch it on at the moments that carry the song: a deep, still starfield in a calm or "
            "breakdown part, a bright one on a big chorus or drop. A few phrases, not all the time (never "
            "more than two phrases in a row); the rest of the song is lit as usual."
        )
    if lasers and re.search(r"la[sz]er", Path(str(a.path)).stem, re.I):
        parts.append(
            "This track is ABOUT LASERS (it is in the title): make the lasers the star of this track. "
            "Use them in the builds, drops and energetic grooves, with variety (fans, sheets, tunnels, "
            "cones, waves; rainbow and multicolour); only the intro, outro and quiet passages stay dark."
        )
    if lasers:
        parts.append(
            f"The rig also has {len(lasers)} multicolour LASERS ("
            + ", ".join(sorted({x["where"] for x in lasers}))
            + "). They always stay ABOVE the audience. Lasers are "
            "the most intense element: use them deliberately (builds, drops, peaks, a hypnotic tunnel in a "
            "breakdown) and keep them off for a good part of the set so they keep their impact."
        )
    if history:
        parts.append("Previous phrases (oldest first):\n" + "\n".join(f"- {_look_text(d)}" for d in history[-4:]))
    scores = drop_scores(a)
    hints = []
    if scores[i] >= DROP_THRESHOLD:
        hints.append(
            f"Analysis: this phrase STARTS WITH A DROP (energy jump score {scores[i]:.2f}): loudness "
            f"{p.loudness_pct - prev.loudness_pct:+.0f} and low end {p.low_pct - prev.low_pct:+.0f} "
            f"percentile points versus the phrase before. Treat it as a drop, even if it is not the "
            f"loudest part of the set yet."
        )
    if i + 1 < len(phrases) and scores[i + 1] >= DROP_THRESHOLD:
        hints.append(
            "Analysis: the NEXT phrase starts with a drop, so this phrase is most likely the BUILDUP "
            "towards it (use the rise energy curve; the 'roll' trigger accelerates with the build)."
        )
    if getattr(p, "melody_change", False):
        hints.append(
            "Analysis: a NEW MELODY comes in at the start of this phrase (the melodic part clearly changes sound or "
            "register while the beat goes on). Answer it with a clear change of look: other colours, movement or "
            "light pattern than the phrase before."
        )
    if p.kick_ratio < 0.5:
        hints.append(
            "Analysis: little or no kick. Keep movement slow and smooth; let the light breathe with the "
            "music (heads 'breathe') rather than following individual notes or vocals."
        )
    loudest_so_far = max([q.loudness_pct for q in phrases[:i]] or [0])
    if i and p.loudness_pct > loudest_so_far + 5:
        hints.append("Analysis: this is the loudest part of the set so far.")
    riff = synth_riff(a, p)
    if riff >= 0.6 and p.kick_ratio >= 0.5:
        hints.append(
            "Analysis: a steady synth riff runs over the beat. Layer it: one group on the 'synth' "
            "trigger, the other on the kick (pars trigger vs head_trigger)."
        )
    line = synth_line(a, p)
    if line >= SYNTH_LINE:
        hints.append(
            f"Analysis (separated instruments): a clear synth line plays ({line:.1f} notes per beat). The "
            f"lasers can play it note for note (laser movement 'melody'); heads or pars can follow it too."
        )
    for q, which in ((p, "This section"), (nxt, "The NEXT section")):
        if q is not None and getattr(q, "pickup_beats", 0):
            how = "a drum fill" if q.pickup_kind == "fill" else "the new part (a vocal or melody line) coming in early"
            hints.append(
                f"Analysis: {which} starts with an anacrusis: {q.pickup_beats} beat(s) of {how} before its "
                f"downbeat. The lights lead into it on the pickup (unless it is a drop); its look lands on the "
                f"downbeat."
            )
    hint = arc_hint(song_arc(a)[i])
    if hint:
        hints.append(hint)
    parts.append("CURRENT phrase:\n" + describe(p, prev, riff) + ("\n" + "\n".join(hints) if hints else ""))
    if nxt is not None:  # recorded audio lets us look ahead, e.g. to tell a buildup from a groove
        parts.append("NEXT phrase (look-ahead, for context only):\n" + describe(nxt, p, synth_riff(a, nxt)))
    else:
        parts.append("This is the last phrase of the recording.")
    return "\n\n".join(parts)


def _choice(name: str, options, instructions: str) -> dict:
    return {
        "type": "choice",
        "name": name,
        "instructions": instructions,
        "choices": [{"value": v, "description": d} for v, d in options],
    }


QUESTIONS = [
    _choice("section", SECTIONS, "Which part of a track structure is the CURRENT phrase?"),
    _choice(
        "palette",
        [(v, PALETTES[v][0]) for v in DEFAULT_PALETTES],
        "Which colour palette fits the mood? Keep it within a section; change it at drops and breakdowns.",
    ),
    *[_choice(name, options, q) for name, options, q in LAYERS],
    {
        "type": "score",
        "name": "intensity",
        "instructions": "How intense should the lighting be for the CURRENT phrase?",
        "levels": [{"label": name, "description": d} for name, d in INTENSITY_LEVELS],
    },
]


def questions_for(
    groups: list[dict] | None,
    lasers: list[dict] | None = None,
    screen: bool = False,
    style: Style | None = None,
    theme: str | None = None,
    fog: bool = False,
) -> list[dict]:
    """The questions for this rig: group/layer questions only with several groups of heads, laser questions
    only with lasers. With a genre's style its palettes are the colours offered (the rest of a style is a lean,
    in the prompt). A track with a theme in its title gets the theme's special look as a question."""
    qs = _questions_for(groups, lasers, screen)
    if style:
        qs = [_styled(q, style) for q in qs]
    if theme:
        options = [(v, d) for v, d in SPECIALS if v in ("off", theme)]
        qs = qs + [_choice("special", options, f"Switch on the {theme} look for the CURRENT phrase?")]
    if fog:
        qs = qs + [_choice("fog", FOG_LEVELS, "How hazy should the room be in the CURRENT phrase (smoke machine)?")]
    return qs


def _styled(q: dict, style: Style) -> dict:
    """The palette question with the style's palettes only; the other questions as they are."""
    if q["type"] != "choice" or q["name"] != "palette":
        return q
    return {**q, "choices": [{"value": v, "description": PALETTES[v][0]} for v in style.palettes]}


def _questions_for(groups: list[dict] | None, lasers: list[dict] | None = None, screen: bool = False) -> list[dict]:
    out = _group_questions(groups) if groups and len(groups) > 1 else []
    if lasers:
        out += [
            _choice(
                "laser_look",
                LASER_LOOKS,
                "What should the LASERS draw in the CURRENT phrase (they always stay above the audience)?",
            ),
            _choice("laser_move", LASER_MOVES, "How should the laser shapes move?"),
            _choice("laser_color", LASER_COLORS, "Which colours should the laser beams have?"),
        ]
    if screen:
        out.append(
            _choice(
                "screen",
                SCREEN_MODES,
                "What should the LED wall behind the DJ show in the CURRENT phrase? "
                "A real wall is often dark; keep it varied and a bit playful.",
            )
        )
    return QUESTIONS + out if out else QUESTIONS


def _group_questions(groups: list[dict]) -> list[dict]:
    from amadeus.rig.groups import CLASSES, classes

    cls = classes(groups)
    featured = (
        [(c, CLASSES.get(c, c)) for c in cls]
        if len(cls) >= 2
        else [(g["name"], f"the group '{g['name']}' ({len(g['ids'])} heads)") for g in groups]
    )
    return [
        _choice(
            "grouping", GROUPINGS, "How should the GROUPS of moving heads relate to each other in the CURRENT phrase?"
        ),
        _choice(
            "featured",
            featured,
            "Which part of the rig leads? (split: it does the main movement; solo: only "
            "it performs; ignored otherwise.)",
        ),
        _choice(
            "movement2",
            MOVEMENTS,
            "split only: the counter-movement of the other groups (contrast with the "
            "main movement, e.g. slow sweep against per-beat steps).",
        ),
        _choice("formation2", FORMATIONS, "split only: the formation of the other groups."),
        _choice(
            "layer_split",
            LAYER_SPLITS,
            "LAYERING: which heads hold a dim base layer and which play the accents on the hits?",
        ),
        _choice("base_glow", BASE_GLOWS, "If layered: how should the base layer shine?"),
    ]
