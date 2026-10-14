"""The rule director: hand-written thresholds. Predictable, offline, and a baseline to compare the AI against."""

from __future__ import annotations

from amadeus.audio.model import DROP_THRESHOLD, Analysis
from amadeus.director.arc import apply_arc, laser_star, song_arc
from amadeus.director.decision import Decision
from amadeus.director.style import Style
from amadeus.director.vocabulary import DEFAULT_PALETTES

# Looks per section, used round-robin so consecutive phrases of a section differ:
# (par_base, par_accent, trigger, head_light, movement, head_color, dynamics)
RULE_LOOKS = {
    # (par_base, par_accent, trigger, head_light, movement, formation, aim, head_color, dynamics)
    "intro": [
        ("dim", "sparkle", "accents", "breathe", "sweep", "mirror", "sky", "base", "steady"),
        ("fade", "none", "bars", "steady", "nod", "sync", "sky", "base", "steady"),
        ("dim", "sparkle", "accents", "accents", "sweep", "mirror", "sky", "white", "steady"),
    ],
    "groove": [
        ("dim", "pulse", "kick", "steady", "figure8", "mirror", "crowd", "accent", "steady"),
        ("full", "color_pop", "kick", "steady", "step_on_beat", "sync", "crowd", "white", "steady"),
        ("off", "chase", "hats", "steady", "circle", "focus", "crowd", "base", "steady"),
        ("dim", "alternate", "backbeat", "pulse", "sweep", "wave", "stage", "accent", "steady"),
        ("full", "none", "kick", "pulse", "step_on_beat", "fan", "crowd", "cycle", "steady"),
        ("dim", "color_pop", "backbeat", "steady", "sweep", "cross", "crowd", "white", "steady"),
        ("full", "none", "kick", "flick", "bounce", "sync", "crowd", "white", "steady"),
        ("dim", "pulse", "kick", "alternate", "swing", "mirror", "crowd", "accent", "steady"),
        ("off", "chase", "eighths", "steady", "sweep", "mirror", "crowd", "base", "steady"),
        ("dim", "chase", "synth", "pulse", "step_on_beat", "mirror", "crowd", "white", "steady"),
        ("off", "pulse", "kick", "steady", "tilt_wave", "wave", "crowd", "white", "steady"),
        ("dim", "chase", "hats", "random", "tilt_wave", "mirror", "crowd", "accent", "steady"),
    ],
    "buildup": [
        ("dim", "pulse", "roll", "pulse", "nod", "fan", "sky", "white", "rise"),
        ("off", "chase", "hats", "steady", "circle", "focus", "sky", "white", "rise"),
    ],
    "drop": [
        ("off", "pulse", "kick", "steady", "ballyhoo", "mirror", "crowd", "white", "impact"),
        ("full", "color_pop", "kick", "pulse", "step_on_beat", "cross", "crowd", "accent", "impact"),
        ("off", "pulse", "kick", "flick", "bounce", "mirror", "crowd", "white", "impact"),
        ("off", "pulse", "kick", "random", "tilt_wave", "wave", "crowd", "white", "impact"),
        ("full", "color_pop", "kick", "steady", "tilt_wave", "mirror", "sky", "accent", "impact"),
    ],
    "breakdown": [
        ("dim", "none", "accents", "breathe", "circle", "wave", "sky", "base", "steady"),
        ("fade", "sparkle", "accents", "accents", "sweep", "wave", "sky", "white", "steady"),
        ("dim", "none", "bars", "steady", "circle", "focus", "stage", "base", "steady"),
    ],
    "outro": [("fade", "none", "bars", "steady", "sweep", "mirror", "sky", "base", "steady")],
}


RULE_BEAM_FX = {  # rotated per section, like RULE_LOOKS; an open beam is the default
    "intro": [("open", "rings"), ("gobo_rotate", "rings")],
    "groove": [
        ("open", "dots"),
        ("open", "dots"),
        ("gobo", "dots"),
        ("open", "shapes"),
        ("gobo_shake", "shapes"),
        ("open", "curves"),
    ],
    "buildup": [("gobo_rotate", "shapes"), ("gobo_shake", "shapes"), ("prism", "dots")],
    "drop": [("prism_spin", "dots"), ("open", "dots")],
    "breakdown": [("gobo_rotate", "rings"), ("open", "curves")],
    "outro": [("open", "rings")],
}


RULE_GROUPING = {  # rotated per section, like RULE_LOOKS (rigs with several head groups only)
    "intro": ["solo", "individual", "solo"],
    "groove": ["per_group", "split", "chase", "individual", "split", "per_group", "unison"],
    "buildup": ["chase", "per_group"],
    "drop": ["unison", "split", "per_group"],
    "breakdown": ["solo", "individual", "per_group"],
    "outro": ["solo"],
}


PER_BEAT = {"step_on_beat", "bounce", "swing", "ballyhoo", "tilt_wave"}


RULE_LAYERS = {  # (layer_split, base_glow), rotated per section
    "intro": [("alternate", "breathe"), ("high_low", "breathe")],
    "groove": [
        ("alternate", "low"),
        ("none", "low"),
        ("high_low", "medium"),
        ("inner_outer", "low"),
        ("featured", "low"),
    ],
    "buildup": [("high_low", "medium"), ("none", "low")],
    "drop": [("none", "low"), ("alternate", "medium"), ("high_low", "low")],
    "breakdown": [("high_low", "breathe"), ("alternate", "breathe")],
    "outro": [("high_low", "breathe")],
}


RULE_LASERS = {  # (laser_look, laser_move, laser_color): off for much of the set, so they keep their impact
    "intro": [("off", "still", "base")],
    "groove": [
        ("off", "still", "base"),
        ("beams", "scan", "base"),
        ("off", "still", "base"),
        ("fan", "wave", "accent"),
        ("off", "still", "base"),
    ],
    "buildup": [("fan", "ripple", "multi"), ("tunnel", "rotate", "base"), ("fan", "wave", "white")],
    "drop": [
        ("sheet", "wave", "rainbow"),
        ("fan", "pulse", "multi"),
        ("beams", "chase", "white"),
        ("cone", "rotate", "base"),
    ],
    "breakdown": [("off", "still", "base"), ("tunnel", "rotate", "base"), ("off", "still", "base")],
    "outro": [("off", "still", "base")],
}


RULE_SCREEN = {  # rotated per section; a real wall is often dark
    "intro": ["off", "ambient"],
    "groove": ["off", "figure", "equalizer", "off", "figure", "words"],
    "buildup": ["words", "figure"],
    "drop": ["psychedelic", "figure", "equalizer"],
    "breakdown": ["ambient", "off", "figure"],
    "outro": ["ambient", "off"],
}


RULE_FOG = {  # smoke lingers: long arcs. Clear air at the edges, a burst only as a drop lands
    "intro": "none",
    "groove": "light",
    "buildup": "medium",
    "drop": "heavy",
    "breakdown": "light",
    "outro": "none",
}


def apply_open_sky(d: Decision, n_before: int):
    """Outdoors the sky is the canvas: calm and building parts always aim up, grooves and drops every other time
    (the others still come down over the crowd, for contrast)."""
    if d.section in ("intro", "breakdown", "buildup", "outro") or n_before % 2 == 0:
        d.aim = "sky"


def apply_fog(d: Decision, fog: bool, last: Decision | None, final: bool):
    """`final`: the track's last phrase: stop firing (the haze lingers into whatever comes next)."""
    if fog:
        d.fog = "none" if final else RULE_FOG.get(d.section, "light")
        if d.section == "drop" and not (last and last.section == "drop"):
            d.fog = "burst"  # the moment it lands (the arc keeps bursts for the big drops)


def apply_screen(d: Decision, screen: bool, n_before: int):
    if screen:
        options = RULE_SCREEN.get(d.section, ["off"])
        d.screen = options[(n_before + d.phrase) % len(options)]


def apply_lasers(d: Decision, lasers: list | None, n_before: int):
    if not lasers:
        return
    options = RULE_LASERS.get(d.section, [("off", "still", "base")])
    d.laser_look, d.laser_move, d.laser_color = options[(n_before + d.phrase) % len(options)]


def apply_groups(d: Decision, groups: list[dict] | None, n_before: int):
    """Rule-based grouping for multi-group rigs (also the fallback for refused group answers)."""
    if not groups or len(groups) <= 1:
        return
    from amadeus.rig.groups import classes

    cls = classes(groups)
    names = cls if len(cls) >= 2 else [g["name"] for g in groups]
    options = RULE_GROUPING.get(d.section, ["per_group"])
    d.grouping = options[(n_before + d.phrase) % len(options)]
    d.featured = names[(d.phrase + n_before) % len(names)]
    if d.movement in PER_BEAT:
        d.movement2, d.formation2 = "sweep", "mirror"
    else:
        d.movement2, d.formation2 = ("step_on_beat" if d.intensity >= 2 else "circle"), "sync"
    layers = RULE_LAYERS.get(d.section, [("none", "low")])
    d.layer_split, d.base_glow = layers[(n_before * 2 + d.phrase) % len(layers)]


class RuleDirector:
    """Hand-written thresholds. Predictable, offline, and a baseline to compare the AI against."""

    name = "rules"

    def __init__(
        self,
        groups: list[dict] | None = None,
        lasers: list[dict] | None = None,
        screen: bool = False,
        style: Style | None = None,
        theme: str | None = None,
        fog: bool = False,
        outdoor: bool = False,
    ):
        self.groups = groups
        self.outdoor = outdoor  # an open-air stage: no ceiling, so the sky is used much more
        self.fog = fog  # the rig has a smoke machine
        self.lasers = lasers
        self.screen = screen
        self.style = style  # the genre's house style, if any
        self.theme = theme  # what the title is about (director/themes.py), if anything

    def decide(self, a: Analysis, i: int, history: list[Decision]) -> Decision:
        p = a.phrases[i]
        prev = a.phrases[i - 1] if i > 0 else None
        nxt = a.phrases[i + 1] if i + 1 < len(a.phrases) else None
        last = history[-1] if history else None
        pos = p.start / a.duration

        low_jump = p.low_pct - prev.low_pct if prev else 0
        if p.drop_score >= DROP_THRESHOLD:
            section = "drop"
        elif nxt and nxt.drop_score >= DROP_THRESHOLD:
            section = "buildup"
        elif pos < 0.04 and p.loudness_pct < 40:
            section = "intro"
        elif pos > 0.95 and p.loudness_slope_db < 0:
            section = "outro"
        elif p.kick_ratio < 0.5 or (p.low_pct < 25 and p.loudness_pct < 30):
            section = "breakdown"
        elif p.drop_score >= DROP_THRESHOLD or (
            p.low_pct > 70 and p.loudness_pct > 65 and (low_jump > 20 or (last and last.section == "drop"))
        ):
            section = "drop"
        elif nxt and (
            nxt.drop_score >= DROP_THRESHOLD
            or (nxt.low_pct - p.low_pct > 25 and (p.snare_trend > 0.3 or p.loudness_slope_db > 1.5))
        ):
            section = "buildup"
        else:
            section = "groove"

        palettes = list(self.style.palettes) if self.style else DEFAULT_PALETTES
        palette = last.palette if last and last.palette in palettes else palettes[0 if self.style else 1]
        if section in ("drop", "breakdown") and last and last.section != section:
            palette = palettes[(palettes.index(palette) + 1) % len(palettes)]

        variants = RULE_LOOKS[section]
        n_before = sum(1 for d in history if d.section == section)
        look = variants[n_before % len(variants)]
        intensity = 3 if section == "drop" else min(3, int(p.loudness_pct / 25))
        fx, style = RULE_BEAM_FX[section][n_before % len(RULE_BEAM_FX[section])]
        head_trigger = "kick" if look[2] in ("synth", "eighths") else "same"  # layer: heads hold the pulse
        d = Decision(
            i,
            p.start,
            p.end,
            section,
            palette,
            *look,
            beam_fx=fx,
            gobo_style=style,
            intensity=intensity,
            source=self.name,
            head_trigger=head_trigger,
        )
        if self.style:
            self.style.adjust(d, n_before)
        if self.outdoor:
            apply_open_sky(d, n_before)
        if self.theme == "stars":  # a starfield in the calm parts and as each drop lands
            first_drop = section == "drop" and not (last and last.section == "drop")
            twice = len(history) >= 2 and all(h.special == "stars" for h in history[-2:])
            if (section == "breakdown" or first_drop) and not twice:  # key moments: two phrases at most
                d.special = "stars"
        apply_groups(d, self.groups, n_before)
        apply_lasers(d, self.lasers, n_before)
        apply_screen(d, self.screen, n_before)
        apply_fog(d, self.fog, last, i == len(a.phrases) - 1)
        arc = song_arc(a)[i]
        laser_star(d, arc, self.lasers)
        apply_arc(d, arc, self.lasers, self.groups)
        return d
