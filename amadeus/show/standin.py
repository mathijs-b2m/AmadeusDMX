"""A stand-in show for a track that plays before it is prepared: a steady groove on the deck's tempo.

A track loaded late (or a streamed track whose copy is still on its way) can start playing before even its first
analysis is done. Instead of dark lights, the deck plays a simple show built from what the DJ software already
knows: the tempo. No audio is read. It is a plain groove (kick on every beat, 8-bar phrases, no
drops), planned by the rule director for the rig like any other show, so the lights land on the beat and the
heads move. As soon as the track's own show is ready, the deck switches to it (live.py crossfades).
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from amadeus.audio.model import Analysis, Phrase

NAME = "tempo"  # the "director" the deck status reports while the stand-in plays
FPS = 46.875
BARS = 8  # per phrase
DEFAULT_BPM = 120.0  # the DJ software doesn't say the tempo (rare)
LOOP_PHRASES = 4  # the groove repeats after this many phrases


def track_bpm(deck) -> float:
    """The track's own tempo (positions are in track seconds, so the grid uses the unpitched tempo)."""
    if deck.bpm0 > 1:
        return deck.bpm0
    if deck.bpm > 1:
        return deck.bpm / (deck.speed or 1.0)
    return DEFAULT_BPM


def groove_analysis(bpm: float, duration: float) -> Analysis:
    """An analysis of a steady groove: beats from 0 at `bpm`, a kick on every beat, every phrase alike."""
    beat = 60.0 / bpm
    n_beats = max(round(duration / beat), BARS * 4)
    duration = n_beats * beat
    n = int(duration * FPS) + 1
    t = np.arange(n) / FPS
    beats = np.arange(n_beats) * beat
    downbeats = np.arange(0, n_beats, 4)
    pulse = np.exp(-(t % beat) / 0.08)  # the kick: band energy jumps on the beat and decays
    bands = {
        "sub": -30 + 8 * pulse,
        "bass": -28 + 7 * pulse,
        "mid": np.full(n, -24.0) + 0.5 * np.sin(t),  # a little life, so band_norm isn't flat
        "high": -30 + 2 * ((t % (beat / 2)) < 0.03),
        "air": np.full(n, -40.0) + 0.5 * np.cos(t),
    }
    bands = {k: v.astype(np.float32) for k, v in bands.items()}
    eighths = np.sort(np.concatenate([beats, beats + beat / 2]))

    def events(times, strength):
        return np.asarray(times, float), np.full(len(times), strength, np.float32)

    onsets = {
        "kick": events(beats, 1.0),
        "snare": events(beats[1::2], 0.6),
        "hat": events(eighths, 0.4),
        "accent": events(beats[downbeats], 0.7),
        "lead": events([], 0.0),
    }
    step = BARS * 4 * beat
    phrases = [
        Phrase(
            index=i,
            start=round(i * step, 3),
            end=round(min((i + 1) * step, duration), 3),
            bars=BARS,
            bpm=bpm,
            loudness_pct=60,
            loudness_slope_db=0.0,
            low_pct=65,
            mid_pct=55,
            high_pct=50,
            kick_ratio=1.0,
            hat_density=2.0,
            snare_density=0.5,
            snare_trend=0.0,
            brightness_trend=0.0,
        )
        for i in range(int(np.ceil(n_beats / (BARS * 4))))
    ]
    return Analysis(
        path=f"{NAME}.wav",
        duration=duration,
        sr=24000,
        fps=FPS,
        bpm=bpm,
        bands_db=bands,
        rms_db=(bands["bass"] + 3).astype(np.float32),
        onsets=onsets,
        beats=beats,
        downbeats=downbeats,
        phrases=phrases,
    )


def build(rig: dict, bpm: float, duration: float, style_genre: str = "", real_output: bool = False) -> tuple:
    """(analysis, plan, engine, NAME): the stand-in show, in the same form as TrackShows' shows."""
    from amadeus.director import RuleDirector, direct
    from amadeus.director.style import style_for
    from amadeus.engine import Engine
    from amadeus.rig.groups import has_smoke, head_groups, laser_list

    a = groove_analysis(bpm, duration)
    style = style_for(style_genre) if style_genre else None
    a.style = style.genre if style else ""
    d = RuleDirector(
        head_groups(rig),
        laser_list(rig),
        bool(rig.get("screen")),
        style,
        None,
        has_smoke(rig),
        bool(rig.get("stage", {}).get("outdoor")),
    )
    plan = direct(a, d, verbose=False)
    engine = Engine(a, plan, rig, real_output=real_output, fog_carry=True)
    return a, plan, engine, NAME


class StandIns:
    """Stand-in shows per deck and tempo, built in a thread of their own (the pool may be busy preparing tracks).

    A stand-in is a short groove (LOOP_PHRASES phrases) played round and round: the loop is a whole number of
    phrases on the beat grid, so wrapping keeps the beat, and it builds in a fraction of a second whatever the
    track's length."""

    def __init__(self, rig: dict, real_output: bool = False, style_genre=lambda: ""):
        self.rig, self.real_output, self.style_genre = rig, real_output, style_genre
        self.shows: dict[tuple, tuple] = {}  # (deck, bpm, the set's style) → show (an engine per deck: it keeps state)
        self.building: set[tuple] = set()
        self.said: set[tuple] = set()  # (deck, file, bpm) already logged
        self.lock = threading.Lock()

    def get(self, deck):
        """The stand-in show for this deck's tempo (None while it is being built). Ask early, as soon as an
        unprepared track is on a deck, so it is there when the DJ presses play."""
        bpm = round(track_bpm(deck), 1)
        key = (deck.deck, bpm, self.style_genre())
        with self.lock:
            show = self.shows.get(key)
            if show is None and key not in self.building:
                self.building.add(key)
                threading.Thread(target=self._build, args=(key,), daemon=True).start()
        if show is not None and deck.play and (deck.deck, deck.file, bpm) not in self.said:
            self.said.add((deck.deck, deck.file, bpm))
            name = Path(deck.file).name if deck.file else f"deck {deck.deck}"
            print(f"  ♩ {name}: not prepared yet, a groove on its {bpm:.1f} BPM meanwhile", flush=True)
        return show

    @staticmethod
    def position(show, pos: float) -> float:
        """Where in the looped groove a track position falls."""
        return min(max(pos, 0.0) % show[0].duration, show[0].duration - 0.05)

    def _build(self, key: tuple):
        _, bpm, style = key
        try:
            show = build(self.rig, bpm, LOOP_PHRASES * BARS * 4 * 60.0 / bpm, style, self.real_output)
            with self.lock:
                self.shows[key] = show
        except BaseException as e:  # noqa: BLE001 - a stand-in must never stop the show
            print(f"  ⚠ no stand-in show at {bpm:.1f} BPM: {e}")
        finally:
            with self.lock:
                self.building.discard(key)
