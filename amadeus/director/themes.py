"""Themes from a track's title: a song about stars gets a starfield at its key moments.

A title is a strong hint for the show ("A Sky Full of Stars", "Starlight", "Galaxy"). A theme gives the
director a **special** look it can switch on per phrase (the `special` decision): not all the time, at the
moments that carry the song. The engine plays it (amadeus/engine/looks.py); it works on any rig.

- **stars**: a starfield over the show: subtle accents, not the whole rig. A set of small lights (pixel cells,
  else pars, else every other head) twinkles, each star at its own random moment: up quickly, held a moment,
  fading gently, in star white. A few at a time in calm parts, more in a drop; the rest of the show plays on.

(A title about lasers has its own rule: the lasers are the star of that track, see director/prompt.py.)
"""

from __future__ import annotations

import re
from pathlib import Path

THEMES = {
    "stars": re.compile(
        r"\b(stars?|starry|starlight|stardust|starfield|galax(?:y|ies)|cosmos|cosmic|constellations?|"
        r"supernova|milky way|night sky|shooting star)\b",
        re.I,
    ),
}


def theme_of(path: str | Path) -> str | None:
    """The theme a track's title is about (None: none we have a special look for)."""
    title = Path(str(path)).stem
    title = title.split(" - ", 1)[-1] if " - " in title else title  # "Artist - Title": the title only
    return next((name for name, rx in THEMES.items() if rx.search(title)), None)
