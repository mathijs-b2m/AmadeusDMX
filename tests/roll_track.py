"""A short track with a snare roll into a drop: groove, a build whose snare speeds up (quarters, eighths,
sixteenths, thirty-seconds) over a rising noise riser, a pause, the drop. Optionally a fill (a few quick
hits in its own rhythm) at the end of the groove, into the build. Written as audio, so the whole analysis
runs on it."""

from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 22050
START_S = 0.5
GROOVE_BARS, DROP_BARS = 16, 12
STEPS = ((4, 1), (2, 2), (1, 4), (1, 8))  # the build: (bars, snare hits per beat)
FILL = (0.31, 0.5, 1.0, 1.32, 1.5, 1.79, 2.07)  # a fill's hits, in beats from the groove's last bar's third beat


def make(
    path: Path,
    bpm: float = 128.0,
    steps=STEPS,
    pause_beats: float = 1.0,
    riser: bool = True,
    seed: int = 3,
    fill: bool = False,
) -> dict:
    """Write the track; returns its truth: the drop, the roll's step per beat (from its start), the pause, the
    roll's hits and the fill's."""
    import soundfile as sf
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    build_bars = sum(b for b, _ in steps)
    bars = GROOVE_BARS + build_bars + DROP_BARS + 2
    x = np.zeros(int((START_S + bars * 4 * beat + 1) * SR))

    def put(at: float, sig: np.ndarray, gain: float):
        i = int(round(at * SR))
        j = min(len(x), i + len(sig))
        x[i:j] += gain * sig[: j - i]

    tt = np.arange(int(0.3 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
    bt = np.arange(int(beat * 0.45 * SR)) / SR
    bass = np.sin(2 * np.pi * 55 * bt) * np.minimum(1, bt * 200) * np.exp(-bt * 4)
    ht = np.arange(int(0.03 * SR)) / SR
    hat = sosfilt(butter(4, 7000, "high", fs=SR, output="sos"), rng.standard_normal(len(ht))) * np.exp(-ht * 150)
    band = butter(4, (1200, 5000), "band", fs=SR, output="sos")
    sn_t = np.arange(int(0.07 * SR)) / SR
    riser_f = butter(2, 2500, "low", fs=SR, output="sos")

    drop = START_S + (GROOVE_BARS + build_bars) * 4 * beat
    truth = {
        "drop": drop,
        "build": START_S + GROOVE_BARS * 4 * beat,
        "steps": [],
        "pause": None,
        "hits": [],
        "fill": [],
    }
    for bar in range(GROOVE_BARS):  # groove: kick, offbeat bass, hats, a clap on 2 and 4
        for b in range(4):
            t = START_S + (bar * 4 + b) * beat
            put(t, kick, 0.8)
            put(t + beat / 2, bass, 0.3)
            put(t + beat / 2, hat, 0.15)
            if b % 2:
                put(t, sosfilt(band, rng.standard_normal(len(sn_t))) * np.exp(-sn_t * 45), 0.35)
    if fill:
        tom = np.sin(2 * np.pi * 900 * sn_t) * np.exp(-sn_t * 40)
        for f in FILL:
            t = truth["build"] - 2 * beat + f * beat * 0.9
            put(t, sosfilt(band, rng.standard_normal(len(sn_t))) * np.exp(-sn_t * 40) + 0.3 * tom, 0.4)
            truth["fill"].append(t)
    t_bar = truth["build"]
    k = 0
    for n_bars, div in steps:
        for _ in range(n_bars):
            for h in range(4 * div):
                t = t_bar + h * beat / div
                if t >= drop - pause_beats * beat - 1e-6:
                    break
                snare = sosfilt(band, rng.standard_normal(len(sn_t))) * np.exp(-sn_t * (45 + 8 * div))
                put(t, snare, 0.3 + 0.3 * k / build_bars)
                truth["hits"].append(t)
            truth["steps"] += [div] * 4
            if riser:
                seg = sosfilt(riser_f, rng.standard_normal(int(4 * beat * SR)))
                put(t_bar, seg * np.linspace(k / build_bars, (k + 1) / build_bars, len(seg)), 0.12)
            t_bar += 4 * beat
            k += 1
    if pause_beats:
        truth["pause"] = drop - pause_beats * beat
        i = int(truth["pause"] * SR)
        x[i : int(drop * SR)] *= np.linspace(1, 0, int(drop * SR) - i) ** 8  # tails die out
    for bar in range(DROP_BARS):  # the drop: loud kick and bass
        for b in range(4):
            t = drop + (bar * 4 + b) * beat
            put(t, kick, 1.0)
            put(t + beat / 2, bass, 0.6)
            put(t + beat / 2, hat, 0.2)
            if b % 2:
                put(t, sosfilt(band, rng.standard_normal(len(sn_t))) * np.exp(-sn_t * 45), 0.4)
    x /= np.max(np.abs(x)) * 1.1
    sf.write(path, x.astype(np.float32), SR, subtype="PCM_16")
    return truth
