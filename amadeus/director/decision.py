"""One decision per phrase: the section and the layered look, and plan files (a list of them)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from amadeus.director.vocabulary import (
    LAYERS,
)

LAYER_NAMES = [name for name, _, _ in LAYERS]


GROUP_NAMES = [
    "grouping",
    "featured",
    "movement2",
    "formation2",  # only for rigs with several head groups
    "layer_split",
    "base_glow",
]


LASER_NAMES = ["laser_look", "laser_move", "laser_color"]  # only for rigs with lasers


SCREEN_NAMES = ["screen"]  # only for rigs with an LED wall


FOG_NAMES = ["fog"]  # only for rigs with a smoke machine


SPECIAL_NAMES = ["special"]  # only for tracks with a theme in their title (director/themes.py)


@dataclass
class Decision:
    phrase: int
    start: float
    end: float
    section: str
    palette: str
    par_base: str
    par_accent: str
    trigger: str
    head_light: str
    movement: str
    formation: str
    aim: str
    head_color: str
    dynamics: str
    beam_fx: str
    gobo_style: str
    intensity: int  # 0..3
    source: str  # "openai", "rules" or "openai+hold"
    confidence: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, dict[str, float]] = field(default_factory=dict)
    prompt: str = ""
    drop_score: float = 0.0  # from the analysis: how much this phrase starts like a drop (0..1)
    head_trigger: str = "same"  # what the heads' light pulses on ("same" = the pars' trigger)
    # Rigs with several groups of heads (overhead, back, front, towers): how the groups relate.
    grouping: str = "unison"  # unison | per_group | split | solo | chase | individual
    featured: str = ""  # group class (or group) that leads in split / solo
    movement2: str = "still"  # the other groups' movement in split
    formation2: str = "sync"  # ... and formation
    layer_split: str = "none"  # layering: which heads hold a dim base layer, which play the accents
    base_glow: str = "low"  # how the base layer shines
    # Lasers (always above the audience)
    laser_look: str = "off"  # off | beams | fan | tunnel | cone | wave
    laser_move: str = "still"  # still | scan | rotate | wave | chase
    laser_color: str = "base"  # base | accent | white | cycle (palette colours)
    screen: str = "off"  # LED wall: off | ambient | figure | words | equalizer | psychedelic
    special: str = "off"  # a theme's own look, switched on at key moments: off | stars
    fog: str = "none"  # smoke machines: none | light | medium | heavy | burst (engine/fog.py plays it)

    def look(self) -> tuple:
        return tuple(getattr(self, n) for n in LAYER_NAMES)

    def summary(self) -> str:
        pars = f"pars {self.par_base}" + ("" if self.par_accent == "none" else f"+{self.par_accent}@{self.trigger}")
        heads = f"heads {self.head_light}/{self.movement}/{self.formation}/{self.aim}/{self.head_color}/{self.beam_fx}"
        if self.beam_fx in ("gobo", "gobo_shake", "gobo_rotate"):
            heads += f":{self.gobo_style}"
        dyn = "" if self.dynamics == "steady" else f" {self.dynamics}"
        grp = ""
        if self.layer_split != "none":
            grp += f" layers:{self.layer_split}/{self.base_glow}"
        if self.laser_look != "off":
            grp += f" laser:{self.laser_look}/{self.laser_move}/{self.laser_color}"
        if self.screen != "off":
            grp += f" wall:{self.screen}"
        if self.special != "off":
            grp += f" ✦{self.special}"
        if self.grouping != "unison":
            grp = (
                f" [{self.grouping}"
                + (f": {self.featured}" if self.grouping in ("split", "solo") else "")
                + (f" / rest {self.movement2}+{self.formation2}" if self.grouping == "split" else "")
                + "]"
            )
        return f"{pars:<28} {heads:<56} {self.palette:<5}{dyn}{grp}"


def save_plan(decisions: list[Decision], path: Path):
    path.write_text(json.dumps([asdict(d) for d in decisions], indent=1))


LAYER_DEFAULTS = {
    "par_base": "dim",
    "par_accent": "pulse",
    "trigger": "kick",
    "head_light": "steady",
    "movement": "sweep",
    "formation": "mirror",
    "aim": "crowd",
    "head_color": "base",
    "dynamics": "steady",
    "beam_fx": "open",
    "gobo_style": "dots",
}


def load_plan(path: Path) -> list[Decision]:
    """Load a saved plan; fields added in later versions get neutral defaults."""
    names = {f.name for f in fields(Decision)}
    return [
        Decision(**{**LAYER_DEFAULTS, **{k: v for k, v in d.items() if k in names}})
        for d in json.loads(path.read_text())
    ]


def fmt_time(t: float) -> str:
    """Seconds as m:ss."""
    return f"{int(t // 60)}:{int(t % 60):02d}"
