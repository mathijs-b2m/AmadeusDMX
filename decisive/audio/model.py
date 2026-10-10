"""What the analysis of a track holds: per-frame band energies, onsets, the beat grid and the phrases."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Phrase:
    index: int
    start: float
    end: float
    bars: int
    bpm: float
    loudness_pct: float  # mean loudness as a percentile of all bars in the set
    loudness_slope_db: float  # last bar minus first bar
    low_pct: float
    mid_pct: float
    high_pct: float
    kick_ratio: float  # fraction of beats with a kick on them
    hat_density: float  # hats per beat
    snare_density: float  # snares/claps per beat
    snare_trend: float  # snare density in the last quarter minus the first quarter
    brightness_trend: float  # centroid change in Hz, last bar vs first bar
    drop_score: float = 0.0  # how much this phrase starts like a drop (0..1); >= DROP_THRESHOLD = a drop
    stutter: float = 0.0  # 0..1: how strongly the synths are chopped/gated rhythmically (stutters, trance gates)
    lead_density: float = 0.0  # melody/lead note onsets per beat
    lead_presence: float = 0.0  # 0..1: how clearly a pitched lead is there (tonal, not noise)


@dataclass
class Analysis:
    path: str
    duration: float
    sr: int
    fps: float
    bpm: float
    # per-frame arrays (len = n_frames)
    bands_db: dict[str, np.ndarray]
    rms_db: np.ndarray
    # events: (times, strengths 0..1)
    onsets: dict[str, tuple[np.ndarray, np.ndarray]]
    beats: np.ndarray
    downbeats: np.ndarray  # indices into beats
    phrases: list[Phrase]
    # the melody / lead, per frame
    lead_pitch: np.ndarray | None = None  # 0..1: low → high (log-frequency centroid of the melodic range)
    lead_pc: np.ndarray | None = None  # pitch class 0..11 of the strongest note, -1 if unclear
    lead_tonal: np.ndarray | None = None  # 0..1: how much the melodic range is one clear pitch class
    stutter_gate: np.ndarray | None = None  # 0..1 per frame: the synth's on/off chopping, at full speed
    stutter_strength: np.ndarray | None = None  # 0..1 per frame: how clearly the synths are chopped right now
    # from the separated synth/melody instrument (Demucs "other"), if available: (times, strengths, pitch 0..1)
    synth_notes: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None

    def band_norm(self, name: str) -> np.ndarray:
        """Band energy scaled to 0..1 between the set's 10th and 97th percentile."""
        x = self.bands_db[name]
        lo, hi = np.percentile(x, [10, 97])
        return np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)


DROP_THRESHOLD = 0.6
