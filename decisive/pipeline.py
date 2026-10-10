"""From a track to a show: analysis, the director's plan (cached), and the instrument separation."""

from __future__ import annotations

import os
import time
from pathlib import Path

from decisive import paths
from decisive.audio.analysis import analyze, cache_paths, readable_audio
from decisive.director import (
    MODEL,
    PROMPT_VERSION,
    OllamaDirector,
    OpenAIDirector,
    RuleDirector,
    direct,
    load_plan,
    save_plan,
)
from decisive.rig.groups import head_groups, laser_list, signature

CACHE = paths.CACHE


def pick_director(name: str, wav: Path | None = None, redo: bool = False, tempo: str | None = None) -> str:
    """The director to use: 'auto' is the Decisions API with a key, else the rules."""
    if name == "openai" and not os.environ.get("OPENAI_API_KEY"):
        if wav is not None and not redo and plan_path(wav, "openai", tempo).exists():
            return name  # an AI plan is already cached: no API calls needed
        raise SystemExit(
            "--director openai needs OPENAI_API_KEY: export it in this shell, or put "
            "OPENAI_API_KEY=sk-... in a .env file in the project folder"
        )
    if name == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        print(
            "OPENAI_API_KEY not set → using the rule-based director. "
            "Set the key (or pass --director openai) to let the Decisions API decide."
        )
        return "rules"
    return name


def normalize_director(director: str) -> str:
    """'ollama' is short for the default local decision model."""
    return "ollama:nimble" if director == "ollama" else director


def _file_tag(director: str) -> str:
    return director.replace(":", "-").replace("/", "-")


def plan_path(wav: Path, director: str, tempo: str | None = None, layout: str | None = None) -> Path:
    """Where a track's plan is cached. `layout`: the rig's group/laser/screen signature (None: a plain rig)."""
    director = normalize_director(director)
    base = cache_paths(readable_audio(wav, CACHE), CACHE, tempo)[0].name.removesuffix(".analysis.npz")
    suffix = f".{layout}" if layout else ""
    return CACHE / f"{base}.{_file_tag(director)}.v{PROMPT_VERSION}{suffix}.plan.json"


def get_plan(
    wav: Path, director: str, redo: bool, tempo: str | None = None, cancel=None, rig: dict | None = None, progress=None
):
    """Analysis + plan for a track. With a rig of several head groups, the director also decides how the
    groups work together (and the plan is cached per group layout)."""
    director = normalize_director(director)
    a = analyze(wav, CACHE, tempo=tempo)
    groups = head_groups(rig) if rig else []
    lasers = laser_list(rig) if rig else []
    screen = bool(rig and rig.get("screen"))
    layout = "-".join(
        x for x in (signature(groups), f"l{len(lasers)}" if lasers else None, "scr" if screen else None) if x
    )
    path = plan_path(wav, director, tempo, layout or None)
    if path.exists() and not redo:
        return a, load_plan(path)
    model = f" ({MODEL})" if director == "openai" else ""
    print(f"Directing {len(a.phrases)} phrases with the {director} director{model} …")
    base = plan_path(wav, director, tempo).name.split(f".{_file_tag(director)}.")[0]
    if director == "openai":
        d = OpenAIDirector(CACHE / f"{base}.decisions-cache.json", groups=groups, lasers=lasers, screen=screen)
    elif director.startswith("ollama"):
        model = director.split(":", 1)[1] if ":" in director else "nimble"
        cache = CACHE / f"{base}.{_file_tag(director)}.decisions-cache.json"
        d = OllamaDirector(cache, model, groups=groups, lasers=lasers, screen=screen)
    else:
        d = RuleDirector(groups, lasers, screen)
    plan = direct(a, d, cancel=cancel, progress=progress)
    save_plan(plan, path)
    print(f"Plan saved to {path}")
    return a, plan


def separate_now(wav: Path):
    """Offline (play/direct): separate the instruments first, in its own process; nothing is playing yet."""
    from decisive.audio import stems as stemlib

    if not stemlib.available():
        return
    src = readable_audio(wav, CACHE)
    if stemlib.load_notes(src) is not None:
        return
    print(f"Separating instruments of {wav.name} (once) …", flush=True)
    t0 = time.monotonic()
    stemlib.start_background(src).wait()
    print(f"  {'done' if stemlib.load_notes(src) is not None else 'not available'} in {time.monotonic() - t0:.0f} s")
