"""A house style per genre, and the genre of a set: so tracks that share a genre look like one show.

Every track is directed on its own; without a style two techno tracks in a row could get a sunset palette
and a disco ball. A **style sheet** per genre says what fits: the palettes, what doesn't belong (a fading
wash in hardstyle, a spinning prism in techno), what to use instead, and a few lines for the decision model.

A style is a lean, not a rule: the genre sets the COLOURS, the music of each part decides the moves. A song
is not one genre all the way through (a pop song's piano ballad, then a mainstage drop):

- The rule director uses the genre's palettes everywhere, and swaps a look's misfits only in the grooves (the
  body of a genre); intros, breakdowns, buildups and drops follow their own music.
- The decision models get the genre's palettes as the only colour answers, and the rest of the style in the
  prompt as a lean, with every option still open.

Nothing here knows a rig: a style talks about looks (palettes, movement, light), the rig plays them.

The **set's genre** smooths the per-track call in a live set where it is a guess: a genre from the audio
alone (a tempo family) is noisy, and one such track must not flip the style for one song; it is lit in the
set's genre, and a new genre takes over after two tracks in a row. A track whose genre is known (your
choice, the Decisions API from its artist and title, its tag) is lit in its own style: a Coldplay song in a
techno set is still pop. A genre with a program of its own (cinematic) plays that program and leaves the
set's genre alone.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from decisive.director.vocabulary import DEFAULT_PALETTES, PALETTES

SWITCH_AFTER = 2  # a different genre this many tracks in a row becomes the set's genre
KNOWN = {"you", "ai", "tag"}  # where a genre is known, not guessed from the audio: the track keeps its own style


@dataclass(frozen=True)
class Style:
    genre: str
    text: str  # the house style in words, for the decision models
    palettes: tuple[str, ...]  # the colours of the genre, the most typical first
    avoid: dict[str, frozenset] = field(default_factory=dict)  # per layer: options that don't fit
    prefer: dict[str, tuple] = field(default_factory=dict)  # per layer: what to use instead (taken in turn)

    def allows(self, layer: str, value: str) -> bool:
        return value not in self.avoid.get(layer, ())

    def adjust(self, d, k: int) -> bool:
        """The genre's colours for decision `d`, and in a groove its misfits swapped for what fits (k: rotates
        the choice). True if changed."""
        changed = False
        if d.palette not in self.palettes:
            d.palette, changed = self.palettes[k % len(self.palettes)], True
        if d.section != "groove":
            return changed  # intros, breakdowns, buildups and drops: their own music decides
        for layer, bad in self.avoid.items():
            if getattr(d, layer, None) in bad:
                fits = [v for v in self.prefer.get(layer, ()) if v not in bad]
                if fits:
                    setattr(d, layer, fits[(k + d.phrase) % len(fits)])
                    changed = True
        return changed


def _style(genre, text, palettes, avoid=None, prefer=None) -> Style:
    return Style(
        genre,
        text,
        tuple(palettes),
        {k: frozenset(v) for k, v in (avoid or {}).items()},
        {k: tuple(v) for k, v in (prefer or {}).items()},
    )


# Calm genres share their restraint: no strobing light, no per-beat head moves.
_CALM_AVOID = {"head_light": {"flick", "beat", "stutter", "random"},
               "movement": {"bounce", "ballyhoo", "step_on_beat", "tilt_wave"},
               "par_accent": {"stutter", "chase"}, "beam_fx": {"prism_spin", "gobo_spin", "gobo_shake"}}  # fmt: skip
_CALM_PREFER = {"head_light": ("breathe", "steady"), "movement": ("sweep", "still", "circle"),
                "par_accent": ("none", "pulse"), "beam_fx": ("open", "gobo_rotate")}  # fmt: skip

STYLES: dict[str, Style] = {
    s.genre: s
    for s in [
        _style(
            "techno",
            "Techno: dark, minimal and hypnotic. Mostly white and cold colours with few colour changes; straight "
            "beams cutting through the dark, sharp pulses on the kick, repetitive movement that builds tension. "
            "Little decoration: no rotating prisms, no colour cycling.",
            ["cool", "ice", "fire"],
            {
                "par_base": {"fade", "full"},
                "par_accent": {"color_pop", "sparkle", "melody"},
                "movement": {"figure8", "swing", "ballyhoo"},
                "head_color": {"cycle"},
                "beam_fx": {"prism_spin", "prism", "frost", "gobo_spin"},
            },
            {
                "par_base": ("off", "dim"),
                "par_accent": ("pulse", "chase", "stutter"),
                "movement": ("sweep", "step_on_beat", "nod"),
                "head_color": ("white", "base"),
                "beam_fx": ("open", "gobo_shake"),
            },
        ),  # fmt: skip
        _style(
            "house",
            "House: warm, groovy and soulful. Warm colours, swinging, rounded movement on the groove, colour pops "
            "on the hits; it dances rather than hits hard.",
            ["warm", "neon", "gold", "cool"],
            {"movement": {"ballyhoo", "nod"}, "head_light": {"stutter"}, "par_base": {"off"}},
            {
                "movement": ("swing", "figure8", "circle"),
                "head_light": ("pulse", "steady"),
                "par_base": ("dim", "full"),
            },
        ),  # fmt: skip
        _style(
            "edm",
            "Mainstage EDM: big, bright and euphoric. Saturated colours, everything on the drops (ballyhoo, "
            "prisms, the whole rig), clear builds with rising light; rarely still.",
            ["neon", "fire", "cool", "warm"],
            {"par_base": {"fade"}, "movement": {"still", "nod"}},
            {"par_base": ("dim", "off"), "movement": ("circle", "bounce", "ballyhoo")},
        ),  # fmt: skip
        _style(
            "trance",
            "Trance: euphoric and wide. Cool and icy colours, wide fans and waves of beams, the sky in the long "
            "breakdowns, flowing movement; lasers and long builds.",
            ["cool", "ice", "neon"],
            {"movement": {"bounce", "ballyhoo"}, "par_base": {"off"}},
            {"movement": ("sweep", "circle", "figure8"), "par_base": ("dim", "fade")},
        ),  # fmt: skip
        _style(
            "psytrance",
            "Psytrance: psychedelic and rolling. Bright colours, rotating patterns and circles, chases that "
            "follow the rolling bassline.",
            ["neon", "cool", "fire"],
            {"par_base": {"full"}, "movement": {"still", "nod"}},
            {"par_base": ("dim", "off"), "movement": ("circle", "figure8", "sweep")},
        ),  # fmt: skip
        _style(
            "hardstyle",
            "Hardstyle: hard and aggressive. Red, white and ice; hard flicks and pulses on the distorted kick, "
            "fast punchy moves, dark between the hits. No soft fades.",
            ["fire", "ice", "neon"],
            {"par_base": {"fade", "full"}, "movement": {"figure8", "swing", "still"}, "head_light": {"breathe"}},
            {
                "par_base": ("off", "dim"),
                "movement": ("bounce", "step_on_beat", "ballyhoo"),
                "head_light": ("flick", "beat", "pulse"),
            },
        ),  # fmt: skip
        _style(
            "dnb",
            "Drum and bass: fast and nervous. Quick chases on the breakbeat, the backbeat hits hard, sharp "
            "short moves; cool and fiery colours.",
            ["cool", "fire", "neon"],
            {"movement": {"figure8", "swing"}, "par_base": {"fade"}},
            {"movement": ("step_on_beat", "bounce", "sweep"), "par_base": ("off", "dim")},
        ),  # fmt: skip
        _style(
            "dubstep",
            "Dubstep and bass music: heavy half-time weight. Hits on the backbeat, light that stutters with the "
            "wobble, dark between the hits; fiery and neon colours.",
            ["fire", "neon", "cool"],
            {"movement": {"figure8", "swing", "circle"}, "par_base": {"fade", "full"}},
            {"movement": ("bounce", "nod", "step_on_beat"), "par_base": ("off", "dim")},
        ),  # fmt: skip
        _style(
            "hiphop",
            "Hip-hop: punchy and cool. Gold and purple, light on the artist (focus on the stage), hits on the "
            "backbeat; the moving heads support, they don't perform.",
            ["gold", "warm", "neon"],
            {"movement": {"ballyhoo", "figure8"}, "beam_fx": {"prism_spin", "gobo_spin", "frost"}},
            {"movement": ("nod", "bounce", "sweep"), "beam_fx": ("open", "gobo")},
        ),  # fmt: skip
        _style(
            "rnb",
            "R&B and soul: smooth and warm. Gold and warm colours, soft fades, slow sweeping movement; nothing harsh.",
            ["gold", "warm", "cool"],
            {"head_light": {"flick", "stutter"}, "par_accent": {"stutter", "sparkle"}, "movement": {"ballyhoo"}},
            {"head_light": ("breathe", "steady"), "par_accent": ("pulse", "color_pop"), "movement": ("sweep", "swing")},
        ),  # fmt: skip
        _style(
            "pop",
            "Pop: bright and colourful, led by the song. Big colour on the choruses, the verses calmer; light "
            "that sings along rather than hammers.",
            ["neon", "warm", "gold", "cool"],
            {"par_base": {"off"}, "head_light": {"stutter"}},
            {"par_base": ("dim", "full"), "head_light": ("pulse", "steady")},
        ),  # fmt: skip
        _style(
            "rock",
            "Rock: white and amber, like a concert. Punch on the snare and the big hits, light on the stage and "
            "the band, little movement and few colours; no disco patterns.",
            ["stage", "fire", "ice"],
            {
                "par_accent": {"sparkle", "melody"},
                "movement": {"figure8", "ballyhoo", "circle"},
                "head_color": {"cycle"},
                "beam_fx": {"gobo_spin", "prism_spin", "frost"},
            },
            {
                "par_accent": ("pulse", "alternate"),
                "movement": ("sweep", "nod", "still"),
                "head_color": ("white", "base"),
                "beam_fx": ("open", "gobo"),
            },
        ),  # fmt: skip
        _style(
            "metal",
            "Metal: hard white and red. Fast flicks on the double kick, punches on the snare, light on the stage; "
            "no soft colours, no disco patterns.",
            ["fire", "stage", "ice"],
            {
                "par_base": {"fade"},
                "par_accent": {"sparkle", "melody"},
                "movement": {"figure8", "swing"},
                "head_color": {"cycle"},
                "beam_fx": {"gobo_spin", "prism_spin", "frost"},
            },
            {
                "par_base": ("off", "dim"),
                "par_accent": ("pulse", "alternate"),
                "movement": ("bounce", "nod"),
                "head_color": ("white", "base"),
                "beam_fx": ("open",),
            },
        ),  # fmt: skip
        _style(
            "latin",
            "Latin and afro: warm, colourful and swinging. Warm and gold colours, rounded swinging movement, "
            "colour pops on the rhythm.",
            ["warm", "gold", "neon"],
            {"movement": {"nod", "ballyhoo"}, "par_base": {"off"}},
            {"movement": ("swing", "figure8", "circle"), "par_base": ("dim", "full")},
        ),  # fmt: skip
        _style(
            "funk",
            "Funk and disco: glitter and groove. Gold and neon, swinging movement, colour pops and chases, dots "
            "and prisms like a mirror ball.",
            ["gold", "neon", "warm"],
            {"movement": {"nod", "still"}, "par_base": {"off"}},
            {"movement": ("swing", "circle", "bounce"), "par_base": ("dim", "full")},
        ),  # fmt: skip
        _style(
            "jazz",
            "Jazz and blues: intimate and warm. Gold and warm colours, light on the stage, slow and calm; no "
            "strobing light, no per-beat moves.",
            ["gold", "warm", "cool"],
            {**_CALM_AVOID, "dynamics": {"impact"}},
            {**_CALM_PREFER, "dynamics": ("steady",)},
        ),  # fmt: skip
        _style(
            "ambient",
            "Ambient: atmosphere. Cold and soft colours, slow fades, beams to the sky moving slowly; no strobing "
            "light, no per-beat moves.",
            ["ice", "cool", "warm"],
            {**_CALM_AVOID, "par_base": {"off"}, "dynamics": {"impact"}},
            {**_CALM_PREFER, "par_base": ("fade", "dim"), "dynamics": ("steady",)},
        ),  # fmt: skip
        _style(
            "classical",
            "Classical: like a concert hall. Warm and gold light on the stage, slow swells with the music, "
            "calm movement; no strobing light, no per-beat moves.",
            ["gold", "warm", "ice"],
            {**_CALM_AVOID, "par_base": {"off"}},
            {**_CALM_PREFER, "par_base": ("fade", "dim")},
        ),  # fmt: skip
    ]
}


def style_for(genre: str | None) -> Style | None:
    """The style sheet of a genre (None: no genre, or a genre with a program of its own)."""
    return STYLES.get(genre or "")


def check() -> list[str]:
    """Problems in the style sheets (unknown palettes or options): for the tests."""
    from decisive.director.decision import Decision
    from decisive.director.vocabulary import LAYERS

    options = {name: {v for v, _ in opts} for name, opts, _ in LAYERS}
    known = {f.name for f in Decision.__dataclass_fields__.values()}
    out = []
    for s in STYLES.values():
        out += [f"{s.genre}: palette {p}" for p in s.palettes if p not in PALETTES]
        for table in (s.avoid, s.prefer):
            for layer, values in table.items():
                if layer not in known:
                    out.append(f"{s.genre}: layer {layer}")
                out += [f"{s.genre}: {layer}={v}" for v in values if layer in options and v not in options[layer]]
        for layer, bad in s.avoid.items():
            if layer in options and not options[layer] - bad:
                out.append(f"{s.genre}: nothing left for {layer}")
    return out


class SetGenre:
    """The genre a live set is in, from the tracks as they come: a new genre takes over only after
    SWITCH_AFTER tracks in a row. A known genre (you, the Decisions API, a tag) is the track's own style; only
    a guess from the audio follows the set."""

    def __init__(self):
        self.current: str | None = None
        self.recent: list[str] = []  # the genres of the tracks so far, in order
        self.decided: dict[str, str] = {}  # file → the genre its style follows
        self.lock = threading.Lock()

    def genre_for(self, file: str, genre: str, source: str = "") -> str:
        """The genre whose style track `file` gets (decided once per track)."""
        with self.lock:
            if file in self.decided:
                return self.decided[file]
            if genre not in STYLES:  # no genre, or a program of its own: the set's genre stays
                self.decided[file] = genre
                return genre
            self.recent.append(genre)
            if self.current is None or self.recent[-SWITCH_AFTER:] == [genre] * SWITCH_AFTER:
                if self.current not in (None, genre):
                    print(f"  ⇄ the set is {genre} now (was {self.current})")
                self.current = genre
            out = genre if source in KNOWN else self.current
            if out != genre:
                print(f"  ♫ {file.rsplit('/', 1)[-1]}: {genre}, played in the set's {out} style")
            self.decided[file] = out
            return out


__all__ = ["DEFAULT_PALETTES", "STYLES", "SetGenre", "Style", "check", "style_for"]
