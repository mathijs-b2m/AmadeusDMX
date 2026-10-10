"""Spectral features: band energies, band-limited onsets per instrument, the lead line and synth stutters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import maximum_filter1d, median_filter

N_FFT = 2048


HOP = 512


BANDS = {  # name: (low Hz, high Hz) used for energy meters and the scene engine
    "sub": (20, 60),
    "bass": (60, 250),
    "mid": (250, 2000),
    "high": (2000, 6000),
    "air": (6000, 11000),
}


ONSET_BANDS = {  # band-limited spectral flux, one detector per "instrument"
    "kick": (100, 200),  # the kick's punch; lower bands get masked by sustained or offbeat bass
    "snare": (1000, 4000),
    "hat": (7000, 11000),
    "all": (35, 11000),
    "lead": (250, 3000),  # melody / synth lead / vocals: followed when there's no beat
}


def spectral_features(path: Path):
    info = sf.info(str(path))
    src_sr = info.samplerate
    factor = 2 if src_sr >= 44100 else 1
    sr = src_sr // factor
    lowpass = signal.firwin(101, 0.45 * sr, fs=src_sr) if factor > 1 else None
    zi = None

    freqs = np.fft.rfftfreq(N_FFT, 1 / sr)
    window = np.hanning(N_FFT).astype(np.float32)
    band_masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
    onset_masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in ONSET_BANDS.items()}

    out = {k: [] for k in [*BANDS, "rms", "centroid", "lead_cent", "synth", *(f"flux_{k}" for k in ONSET_BANDS)]}
    synth_band = (freqs >= 500) & (freqs < 5000)  # synth leads/pads, below the hi-hats
    chroma_rows = []
    mel = (freqs >= 110) & (freqs < 3500)  # where melodies live
    pc_of_bin = np.round(69 + 12 * np.log2(np.maximum(freqs[mel], 1) / 440)).astype(int) % 12
    to_chroma = np.zeros((mel.sum(), 12), dtype=np.float32)
    to_chroma[np.arange(mel.sum()), pc_of_bin] = 1
    lead_band = (freqs >= 250) & (freqs < 4000)
    log_f = np.log2(np.maximum(freqs[lead_band], 1)).astype(np.float32)
    carry = np.zeros(0, dtype=np.float32)
    prev_log = None

    for block in sf.blocks(str(path), blocksize=src_sr * 20, dtype="float32", always_2d=True):
        mono = block.mean(axis=1)
        if lowpass is not None:  # stateful FIR keeps block edges seamless
            if zi is None:
                zi = signal.lfilter_zi(lowpass, 1.0) * mono[0]
            mono, zi = signal.lfilter(lowpass, 1.0, mono, zi=zi)
            mono = mono[::factor]
        buf = np.concatenate([carry, mono.astype(np.float32)])
        n = (len(buf) - N_FFT) // HOP + 1
        if n <= 0:
            carry = buf
            continue
        frames = np.lib.stride_tricks.sliding_window_view(buf, N_FFT)[::HOP][:n]
        mag = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float32)
        carry = buf[n * HOP :]

        power = mag**2
        for k, m in band_masks.items():
            out[k].append(10 * np.log10(power[:, m].mean(axis=1) + 1e-10))
        out["rms"].append(10 * np.log10(power.mean(axis=1) + 1e-10))
        out["centroid"].append((mag * freqs).sum(axis=1) / (mag.sum(axis=1) + 1e-9))
        out["synth"].append(10 * np.log10(power[:, synth_band].mean(axis=1) + 1e-10))
        lm = power[:, lead_band]
        out["lead_cent"].append((lm * log_f).sum(axis=1) / (lm.sum(axis=1) + 1e-12))
        chroma_rows.append(power[:, mel] @ to_chroma)

        log_mag = np.log1p(100 * mag)
        first = log_mag[:1] if prev_log is None else prev_log
        diff = np.maximum(0, np.diff(np.vstack([first, log_mag]), axis=0))
        prev_log = log_mag[-1:]
        for k, m in onset_masks.items():
            out[f"flux_{k}"].append(diff[:, m].sum(axis=1))

    feats = {k: np.concatenate(v).astype(np.float32) for k, v in out.items()}
    feats["chroma"] = np.concatenate(chroma_rows).astype(np.float32)
    return feats, sr, info.duration


def normalize(env: np.ndarray) -> np.ndarray:
    return env / (np.percentile(env, 99.5) + 1e-9)


def pick_peaks(env: np.ndarray, fps: float, delta: float, min_gap: float):
    """Adaptive-threshold peak picking. Returns (times, strengths)."""
    env = normalize(env)
    local_max = env == maximum_filter1d(env, size=max(3, int(fps * 0.05)))
    threshold = median_filter(env, size=int(fps)) + delta
    idx = np.flatnonzero(local_max & (env > threshold))
    keep, last = [], -1e9
    for i in idx:
        if i - last >= min_gap * fps:
            keep.append(i)
            last = i
    keep = np.array(keep, dtype=int)
    return keep / fps, np.clip(env[keep], 0, 1).astype(np.float32)


def lead_features(feats, fps):
    """Pitch contour (0..1), pitch class and tonality of the melodic range, smoothed to ~0.15 s."""
    from scipy.ndimage import uniform_filter1d

    k = max(1, int(0.15 * fps))
    cent = uniform_filter1d(feats["lead_cent"], k)
    lo, hi = np.percentile(cent, [5, 95])
    pitch = np.clip((cent - lo) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)
    chroma = uniform_filter1d(feats["chroma"], k, axis=0)
    share = chroma.max(axis=1) / (chroma.sum(axis=1) + 1e-12)  # 1/12 = noise, ~0.3+ = a clear note
    tonal = np.clip((share - 1 / 12) / (0.35 - 1 / 12), 0, 1).astype(np.float32)
    pc = np.where(tonal > 0.3, chroma.argmax(axis=1), -1).astype(np.int8)
    return pitch, pc, tonal


def stutter_features(feats, fps):
    """Stutters / gates in the synths: fast, regular on-off of the 250-2000 Hz range (synth leads,
    under the hi-hats).

    gate: the synth loudness normalised to its last ~quarter second (0 = off, 1 = on), per frame.
    strength: how much of the synth's short-term loudness variation is one regular chop at 3.5-20 Hz
    (1/8 to 1/32 notes at club tempos), measured over sliding 1 s windows. Chops under sustained
    pads are only a few dB deep, so the depth threshold is low; the "one clear rate" test keeps
    ordinary grooves from counting.
    """
    from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d

    e = feats["mid"].astype(np.float64)
    w = max(3, int(0.25 * fps))
    lo, hi = minimum_filter1d(e, w), maximum_filter1d(e, w)
    gate = np.clip((e - lo) / np.maximum(hi - lo, 3.0), 0, 1).astype(np.float32)

    hp = e - uniform_filter1d(e, max(3, int(0.4 * fps)))  # keep only the fast part of the envelope
    win, hop = int(1.0 * fps), max(1, int(0.25 * fps))
    freqs = np.fft.rfftfreq(win, 1 / fps)
    chop = (freqs >= 3.5) & (freqs <= 20)
    rest = (freqs >= 0.5) & (freqs <= 20)
    window = np.hanning(win)
    centres, vals = [], []
    for s0 in range(0, max(1, len(hp) - win), hop):
        seg = hp[s0 : s0 + win]
        depth = seg.std()
        spec = np.abs(np.fft.rfft((seg - seg.mean()) * window)) ** 2
        peaky = spec[chop].max() / (spec[rest].sum() + 1e-9)  # one clear chop rate, not noise
        vals.append(np.clip((depth - 0.8) / 2.0, 0, 1) * np.clip((peaky - 0.2) / 0.25, 0, 1))
        centres.append(s0 + win // 2)
    strength = (np.interp(np.arange(len(hp)), centres, vals) if vals else np.zeros(len(hp))).astype(np.float32)
    return gate, strength
