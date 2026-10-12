"""A track's genre, in one word, so the show can be chosen by it ("cinematic" gets a program of its own).

From strong to weak:
1. your choice (`amadeus genre TRACK GENRE`, or the Mac app), kept in config/genres.json;
2. the Decisions API: given the artist and the title, it picks one of GENRES (it knows Boris Brejcha plays
   techno and Hans Zimmer writes film scores). Used when there is an OPENAI_API_KEY and it is confident
   (more so with a title alone), and a beat-less genre only when the audio has no groove either;
3. a genre tag in the file, when it maps onto a word we know;
4. the audio, as the fallback: how much of the track grooves (the same rhythm pattern bar after bar, in the
   low end or the highs) tells music made for a pulse from music that isn't (cinematic, ambient); for music
   with a groove the tempo gives the family.

The music facts behind the call are kept (`GenreCall.facts`) so the choice can be shown and checked.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from amadeus import paths
from amadeus.audio.model import Analysis

GENRES = {
    "cinematic": "film and game scores, trailer music, epic orchestral or hybrid: no steady groove, big dynamics",
    "classical": "classical music, orchestras, chamber music, opera, solo piano",
    "ambient": "atmospheric, beatless or nearly so, calm, chill-out, downtempo",
    "edm": "festival and mainstage EDM: big room, electro house, future bass, commercial dance",
    "house": "house, deep house, tech house, progressive house, disco house",
    "techno": "techno, minimal, melodic techno, high-tech minimal, industrial techno",
    "trance": "trance, uplifting, progressive trance: euphoric leads and long breakdowns",
    "psytrance": "psytrance, goa, full-on: rolling basslines, psychedelic",
    "hardstyle": "hardstyle, hardcore, hard dance, gabber: distorted kicks",
    "dnb": "drum and bass, jungle, liquid: breakbeats around 170 BPM",
    "dubstep": "dubstep, riddim, bass music: half-time, heavy wobble bass",
    "hiphop": "hip-hop, rap, trap, grime",
    "rnb": "R&B, soul, neo-soul",
    "pop": "pop songs: verses and choruses, vocal-led",
    "rock": "rock, indie, alternative, punk",
    "metal": "metal, heavy metal, metalcore",
    "latin": "latin, reggaeton, salsa, afrobeats, dancehall",
    "funk": "funk, disco, nu-disco, boogie",
    "jazz": "jazz, swing, blues",
}
MIN_CONFIDENCE = 0.3  # the model less sure than this (with the artist known): the fallbacks decide. Low on
# purpose: what it loses to is a tag or the audio's tempo family, and torn between pop and edm for Coldplay
# (0.39) it is still far better than "house" from 124 BPM
MIN_CONFIDENCE_TITLE_ONLY = 0.85  # no artist known: a title alone ("Symphony") is a weak clue
BEATLESS = {"cinematic", "classical", "ambient"}  # the model may only say these when the audio agrees
OVERRIDES = paths.CONFIG / "genres.json"
CACHE = paths.CACHE / "genres"
GROOVE_BAR_SIM = 0.5  # a bar whose rhythm shape matches the next bar this well grooves
CINEMATIC_GROOVE = 0.35  # less of the track grooves than this: not music made for a pulse (cinematic
# scores went to ~0.2, every club track tried ≥ 0.54)
TAG_WORDS = {  # words in a file's genre tag → our word (first match wins: specific words first)
    "soundtrack": "cinematic", "score": "cinematic", "cinematic": "cinematic", "trailer": "cinematic",
    "epic": "cinematic", "classical": "classical", "orchestra": "classical", "ambient": "ambient",
    "chill": "ambient", "downtempo": "ambient", "psy": "psytrance", "goa": "psytrance", "trance": "trance",
    "hardstyle": "hardstyle", "hardcore": "hardstyle", "hard dance": "hardstyle", "drum": "dnb", "dnb": "dnb",
    "d&b": "dnb", "jungle": "dnb", "dubstep": "dubstep", "bass music": "dubstep", "techno": "techno",
    "minimal": "techno", "big room": "edm", "electro house": "edm", "edm": "edm", "dance": "edm",
    "house": "house", "hip": "hiphop", "rap": "hiphop", "trap": "hiphop", "r&b": "rnb", "rnb": "rnb",
    "soul": "rnb", "metal": "metal", "rock": "rock", "indie": "rock", "punk": "rock", "reggaeton": "latin",
    "latin": "latin", "salsa": "latin", "afro": "latin", "dancehall": "latin", "funk": "funk", "disco": "funk",
    "jazz": "jazz", "blues": "jazz", "pop": "pop",
}  # fmt: skip


@dataclass
class GenreCall:
    genre: str
    source: str  # "you", "tag", "audio", "audio+ai"
    facts: dict = field(default_factory=dict)

    @property
    def program(self) -> str | None:
        """The show that has a program of its own for this genre, if any."""
        return self.genre if self.genre in PROGRAMS else None


PROGRAMS = {"cinematic": "every hit played by its own fixtures, exactly on time; booms on the big lights"}


# ---------------------------------------------------------------- the audio


def _bar_similarity(env: np.ndarray, frames: np.ndarray, beat_len: int) -> np.ndarray:
    """Per beat: how alike its shape is to the same beat one bar (4 beats) later."""
    shapes = np.array([env[s : s + beat_len] for s in frames if s + beat_len <= len(env)])
    if len(shapes) < 6:
        return np.zeros(0)
    shapes = shapes - shapes.mean(axis=1, keepdims=True)
    n = np.linalg.norm(shapes, axis=1) + 1e-9
    return np.sum(shapes[:-4] * shapes[4:], axis=1) / (n[:-4] * n[4:])


def facts(a: Analysis) -> dict:
    """What the genre call rests on: how much of the track grooves, the bass pump, tempo, melody."""
    frames = (a.beats * a.fps).astype(int)
    if len(frames) < 24:
        return {"groove": 0.0, "pump_db": 0.0, "bpm": round(a.bpm, 1), "tonal": 0.0, "hat_density": 0.0}
    beat_len = int(round(np.median(np.diff(frames))))
    low = np.maximum(a.bands_db["sub"], a.bands_db["bass"])
    sim_low, sim_high = _bar_similarity(low, frames, beat_len), _bar_similarity(a.bands_db["high"], frames, beat_len)
    n = min(len(sim_low), len(sim_high))
    loud = np.array([a.rms_db[s : s + beat_len].mean() for s in frames[:n]])
    pump = np.array([low[s : s + beat_len].max() - low[s : s + beat_len].min() for s in frames[:n]])
    # per 16 beats: does the low end or do the highs repeat bar after bar? (near-silent stretches don't count)
    floor = np.percentile(loud, 20) if n else 0.0
    counted = [
        max(np.median(sim_low[k : k + 16]), np.median(sim_high[k : k + 16])) > GROOVE_BAR_SIM
        for k in range(0, n - 15, 16)
        if np.mean(loud[k : k + 16]) > floor
    ]
    weights = np.array([p.end - p.start for p in a.phrases]) if a.phrases else np.ones(1)
    hats = np.array([p.hat_density for p in a.phrases]) if a.phrases else np.zeros(1)
    return {
        "groove": round(float(np.mean(counted)) if counted else 0.0, 2),
        "pump_db": round(float(np.median(pump)), 1),
        "bpm": round(float(a.bpm), 1),
        "tonal": round(float(np.mean(a.lead_tonal)) if a.lead_tonal is not None else 0.0, 2),
        "hat_density": round(float(np.sum(weights * hats) / weights.sum()), 2),
        "dynamics_db": round(float(np.percentile(a.rms_db, 95) - np.percentile(a.rms_db, 10)), 1),
    }


def from_audio(f: dict) -> str:
    if f["groove"] < CINEMATIC_GROOVE:
        if f["pump_db"] < 15 and f["tonal"] >= 0.6:
            return "cinematic" if f["dynamics_db"] >= 10 or f["hat_density"] >= 0.5 else "ambient"
        return "pop"
    bpm = f["bpm"]
    if bpm < 100:
        return "hiphop"
    if bpm < 128:
        return "house"
    if bpm < 136:
        return "techno"
    if bpm < 142:
        return "trance"
    if bpm < 151:
        return "psytrance"
    if bpm < 162:
        return "hardstyle"
    return "dnb"


# ---------------------------------------------------------------- tags, you, the model


def _key(a: Analysis) -> str:
    return Path(a.path).stem


def overrides() -> dict[str, str]:
    try:
        return json.loads(OVERRIDES.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def set_override(a: Analysis | str, genre: str | None):
    """Your genre for a track (None: back to automatic)."""
    if genre is not None and genre not in GENRES:
        raise SystemExit(f"Unknown genre '{genre}'. One of: {', '.join(GENRES)}")
    o = overrides()
    key = a if isinstance(a, str) else _key(a)
    if genre is None:
        o.pop(key, None)
    else:
        o[key] = genre
    OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES.write_text(json.dumps(o, indent=2, sort_keys=True) + "\n")


def tags(path: str | Path) -> dict:
    import soundfile as sf

    try:
        with sf.SoundFile(str(path)) as f:
            return f.copy_metadata()
    except Exception:  # noqa: BLE001 - any file: no tags is fine
        return {}


def from_tag(meta: dict) -> str | None:
    tag = (meta.get("genre") or "").lower()
    return next((ours for word, ours in TAG_WORDS.items() if word in tag), None) if tag else None


def artist_title(a: Analysis, meta: dict) -> tuple[str, str]:
    """The artist and the title: from the file's tags, else from its name ("Artist - Title")."""
    stem = re.sub(r"\.[0-9a-f]{8}\.decoded$", "", Path(a.path).stem)  # a decoded copy: the original's name
    guess_artist, _, guess_title = stem.partition(" - ")
    if not guess_title:
        guess_artist, guess_title = "", stem
    return meta.get("artist") or guess_artist, meta.get("title") or guess_title


def from_model(artist: str, title: str) -> tuple[str, float] | None:
    """Ask the Decisions API which genre a track is, from its artist and title only (cached per track).
    None without a key or on any failure."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    prompt = f"Artist: {artist or 'unknown'}\nTitle: {title}\nWhich genre is this track?"
    key = hashlib.sha1(json.dumps([prompt, list(GENRES)]).encode()).hexdigest()[:16]
    cached = CACHE / f"{key}.json"
    if cached.exists():
        c = json.loads(cached.read_text())
        return c["genre"], c["confidence"]
    try:
        from openai import OpenAI

        from amadeus.director.llm import MODEL

        q = {"type": "choice", "name": "genre", "instructions": "The genre of the track, from its artist and title.",
             "choices": [{"value": g, "description": d} for g, d in GENRES.items()]}  # fmt: skip
        r = OpenAI().decisions.create(model=MODEL, input=prompt, questions=[q])
        ans = next((x.model_dump() for x in r.answers if x.name == "genre"), {})
    except Exception as e:  # noqa: BLE001 - no genre from the model: the fallbacks decide
        print(f"  genre: the Decisions API didn't answer ({e.__class__.__name__}); using the fallback")
        return None
    genre, confidence = ans.get("choice"), float(ans.get("confidence", 0.0))
    if genre not in GENRES:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"genre": genre, "confidence": confidence, "artist": artist, "title": title}))
    return genre, confidence


def detect(a: Analysis, ask_model: bool = True) -> GenreCall:
    f = facts(a)
    you = overrides().get(_key(a))
    if you in GENRES:
        return GenreCall(you, "you", f)
    meta = tags(a.path)
    artist, title = artist_title(a, meta)
    named = from_model(artist, title) if ask_model else None
    if named:
        genre, confidence = named
        sure = confidence >= (MIN_CONFIDENCE if artist else MIN_CONFIDENCE_TITLE_ONLY)
        # a beat-less genre for a track that clearly grooves is a wrong guess (and would change the show)
        plausible = genre not in BEATLESS or f["groove"] < CINEMATIC_GROOVE
        if sure and plausible:
            return GenreCall(genre, "ai", {**f, "confidence": round(confidence, 2)})
    tagged = from_tag(meta)
    if tagged:
        return GenreCall(tagged, "tag", f)
    return GenreCall(from_audio(f), "audio", f)
