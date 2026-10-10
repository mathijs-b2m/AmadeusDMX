"""A synthetic track: an analysis with a typical club structure, generated without audio.

Tests use it so they run anywhere, with no music files and no analysis pass.
"""

from __future__ import annotations

import numpy as np

from decisive.audio.model import Analysis, Phrase

# (section shape, loudness %, low %, kick ratio, drop score) per 8-bar phrase
SHAPE = [
    ("intro", 20, 30, 0.9, 0.0),
    ("groove", 55, 60, 1.0, 0.1),
    ("buildup", 60, 40, 0.6, 0.2),
    ("drop", 95, 95, 1.0, 0.9),
    ("drop", 90, 90, 1.0, 0.3),
    ("breakdown", 25, 15, 0.1, 0.0),
    ("buildup", 65, 45, 0.7, 0.2),
    ("drop", 97, 96, 1.0, 0.95),
    ("outro", 30, 40, 0.9, 0.0),
]


def synthetic_analysis(bpm: float = 128.0, seed: int = 7) -> Analysis:
    rng = np.random.default_rng(seed)
    fps, beat = 46.875, 60.0 / bpm
    bars_per_phrase = 8
    n_beats = len(SHAPE) * bars_per_phrase * 4
    duration = n_beats * beat + 2.0
    n = int(duration * fps)
    beats = np.arange(n_beats) * beat + 0.5
    downbeats = np.arange(0, n_beats, 4)

    # per-frame loudness follows the phrase shape, with a beat pulse on top
    t = np.arange(n) / fps
    phrase_of = np.clip(((t - 0.5) / (beat * 4 * bars_per_phrase)).astype(int), 0, len(SHAPE) - 1)
    loud = np.array([s[1] for s in SHAPE], float)[phrase_of]
    low = np.array([s[2] for s in SHAPE], float)[phrase_of]
    pulse = np.exp(-((t - 0.5) % beat) / 0.08)
    bands = {
        "sub": -40 + low * 0.3 + pulse * 6 + rng.normal(0, 0.5, n),
        "bass": -38 + low * 0.3 + pulse * 5 + rng.normal(0, 0.5, n),
        "mid": -35 + loud * 0.25 + rng.normal(0, 0.8, n),
        "high": -42 + loud * 0.2 + rng.normal(0, 0.8, n),
        "air": -50 + loud * 0.15 + rng.normal(0, 0.8, n),
    }
    bands = {k: v.astype(np.float32) for k, v in bands.items()}
    rms = (np.maximum(bands["bass"], bands["mid"]) + 3).astype(np.float32)

    def events(times, keep, strength=0.8):
        times = np.asarray(times, float)[keep]
        return times, np.full(len(times), strength, np.float32) * rng.uniform(0.7, 1.0, len(times)).astype(np.float32)

    kick_on = np.array([rng.random() < SHAPE[min(i // 32, len(SHAPE) - 1)][3] for i in range(n_beats)])
    eighths = np.sort(np.concatenate([beats, beats + beat / 2]))
    onsets = {
        "kick": events(beats, kick_on, 1.0),
        "snare": events(beats, (np.arange(n_beats) % 2 == 1)),
        "hat": events(eighths, np.ones(len(eighths), bool), 0.6),
        "accent": events(beats[downbeats], np.ones(len(downbeats), bool)),
        "lead": events(beats + beat / 4, rng.random(n_beats) < 0.5, 0.7),
    }

    phrases = []
    for i, (_, loud_pct, lo, kr, ds) in enumerate(SHAPE):
        start = 0.5 + i * bars_per_phrase * 4 * beat
        phrases.append(
            Phrase(
                index=i,
                start=round(start, 3),
                end=round(start + bars_per_phrase * 4 * beat, 3),
                bars=bars_per_phrase,
                bpm=bpm,
                loudness_pct=loud_pct,
                loudness_slope_db=1.0 if SHAPE[i][0] == "buildup" else -0.5,
                low_pct=lo,
                mid_pct=loud_pct,
                high_pct=loud_pct * 0.8,
                kick_ratio=kr,
                hat_density=2.0,
                snare_density=0.5,
                snare_trend=0.6 if SHAPE[i][0] == "buildup" else 0.0,
                brightness_trend=200.0 if SHAPE[i][0] == "buildup" else 0.0,
                drop_score=ds,
                stutter=0.4 if SHAPE[i][0] == "breakdown" else 0.05,
                lead_density=1.0,
                lead_presence=0.6,
            )
        )

    gate = ((t * bpm / 60 * 4) % 1 < 0.5).astype(np.float32)
    return Analysis(
        path="synthetic.wav",
        duration=duration,
        sr=24000,
        fps=fps,
        bpm=bpm,
        bands_db=bands,
        rms_db=rms,
        onsets=onsets,
        beats=beats,
        downbeats=downbeats,
        phrases=phrases,
        lead_pitch=(0.5 + 0.4 * np.sin(t / 3)).astype(np.float32),
        lead_pc=((t / beat).astype(int) % 12).astype(np.int8),
        lead_tonal=np.full(n, 0.6, np.float32),
        stutter_gate=gate,
        stutter_strength=np.where(phrase_of == 5, 0.7, 0.05).astype(np.float32),
    )
