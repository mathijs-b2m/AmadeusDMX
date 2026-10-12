"""Separate a track into its instruments (drums, bass, vocals, other = synths/melody) with Demucs.

Trained source separation hears what the hand-made band filters can't: the synth riff without the
hi-hats, the kick under the bass, whether a sound is a voice. Each track is separated once (about 15 s
for a 6-minute track on an Apple GPU) and cached as mono 22 kHz float16 (~65 MB per track).

Optional: without PyTorch/Demucs installed, `stems()` returns None and the analysis works as before.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from amadeus import paths

# Once the model is on disk, load it offline: no internet check at a gig (and no Hub warning). This must be
# set before the Hugging Face library is imported (Demucs imports it), so it happens when this module loads.
_HUB_MODEL = Path(os.environ.get("HF_HOME", Path.home() / ".cache/huggingface")) / "hub" / "models--adefossez--HTDemucs"
if _HUB_MODEL.exists():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

STEM_SR = 22050
NAMES = ("drums", "bass", "vocals", "other")
STEMS_DIR = paths.CACHE / "stems"
_separator = None


def available() -> bool:
    try:
        import demucs.api  # noqa: F401
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def _key(path: Path) -> str:
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|htdemucs".encode()).hexdigest()[:12]


def stems(path: str | Path, verbose: bool = True) -> dict[str, np.ndarray] | None:
    """{name: mono float32 at STEM_SR} for the track, separated and cached on first use."""
    path = Path(path)
    out = STEMS_DIR / f"{path.stem}.{_key(path)}"
    if all((out / f"{n}.npy").exists() for n in NAMES):
        return {n: np.load(out / f"{n}.npy").astype(np.float32) for n in NAMES}
    if not available():
        return None
    import soundfile as sf
    import torch
    from scipy.signal import resample_poly

    global _separator
    if _separator is None:
        from demucs.api import Separator

        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        _separator = Separator(model="htdemucs", device=device, progress=False)
    if verbose:
        print(f"  separating instruments of {path.name} …", flush=True)
    wav, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != _separator.samplerate:
        wav = resample_poly(wav, _separator.samplerate, sr, axis=0).astype(np.float32)
    _, parts = _separator.separate_tensor(torch.from_numpy(wav.T.copy()), _separator.samplerate)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in NAMES:
        mono = parts[name].mean(0).cpu().numpy()
        mono = resample_poly(mono, STEM_SR, _separator.samplerate).astype(np.float32)
        np.save(out / f"{name}.npy", mono.astype(np.float16))
        result[name] = mono
    return result


def notes(x: np.ndarray, sr: int = STEM_SR, band=(150.0, 8000.0)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Note onsets in one instrument: (times s, strengths 0..1, pitch 0..1 = where the note's energy sits,
    low to high within the track's range). Spectral flux with an adaptive threshold."""
    from scipy.signal import find_peaks, stft

    hop = 256
    f, t, Z = stft(x.astype(np.float32), sr, nperseg=1024, noverlap=1024 - hop)
    S = np.log1p(np.abs(Z) * 50)
    m = (f >= band[0]) & (f <= band[1])
    Sm_ = S[m]
    flux = np.maximum(np.diff(Sm_, axis=1), 0).sum(0)
    scale = np.percentile(flux, 99) + 1e-9
    flux = (flux - np.median(flux)) / scale
    level = Sm_.sum(0)[1:]
    gate = level > np.percentile(level, 20)  # ignore "notes" in near-silence (separation residue)
    thr = np.convolve(flux, np.ones(31) / 31, "same") + 0.08
    pk, props = find_peaks(np.where(gate, flux, 0), height=thr, distance=int(0.07 * sr / hop))
    times = t[1:][pk]
    strength = (
        np.clip(props["peak_heights"] / max(float(np.percentile(props["peak_heights"], 95)), 1e-9), 0, 1)
        if len(pk)
        else np.zeros(0)
    )
    # pitch: spectral centroid of the 120 ms after the onset, scaled over the track
    fm = f[m]
    Sm = S[m]  # once: indexing S[m] per note would copy the whole spectrum each time (minutes for a long set)
    cents = []
    for p in pk:
        seg = Sm[:, p + 1 : p + 1 + max(1, int(0.12 * sr / hop))]
        e = seg.sum(1)
        cents.append(float((fm * e).sum() / (e.sum() + 1e-9)))
    cents = np.array(cents)
    if len(cents):
        lo, hi = np.percentile(cents, [5, 95])
        pitch = np.clip((cents - lo) / max(hi - lo, 1e-9), 0, 1)
    else:
        pitch = np.zeros(0)
    return times.astype(np.float32), strength.astype(np.float32), pitch.astype(np.float32)


# ---------------------------------------------------------------- background separation


def _dir(path: Path) -> Path:
    return STEMS_DIR / f"{path.stem}.{_key(path)}"


def cached_part(path: str | Path, name: str) -> np.ndarray | None:
    """One separated instrument (float32, STEM_SR) if the track has been separated already; never separates."""
    f = _dir(Path(path)) / f"{name}.npy"
    return np.load(f).astype(np.float32) if f.exists() and load_notes(path) is not None else None


VOCAL_ENV_HOP = 1024  # the vocal envelope: one value per this many samples (~46 ms)


def vocal_envelope(path: str | Path) -> tuple[np.ndarray, float] | None:
    """The separated vocal's loudness (dB) over time and its frame rate, if the track has been separated
    (computed once, cached next to the parts)."""
    d = _dir(Path(path))
    f = d / "vocal_env.npz"
    if f.exists():
        z = np.load(f)
        return z["env"], float(z["fps"])
    v = cached_part(path, "vocals")
    if v is None:
        return None
    n = len(v) // VOCAL_ENV_HOP
    frames = v[: n * VOCAL_ENV_HOP].reshape(n, VOCAL_ENV_HOP)
    env = (10 * np.log10((frames**2).mean(axis=1) + 1e-10)).astype(np.float32)
    fps = STEM_SR / VOCAL_ENV_HOP
    np.savez_compressed(f, env=env, fps=fps)
    return env, fps


def load_notes(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """The synth/melody notes of a track if it has been separated already (cheap), else None."""
    f = _dir(Path(path)) / "notes.npz"
    if not f.exists():
        return None
    z = np.load(f)
    return z["t"], z["s"], z["p"]


INSTRUMENTS_VERSION = 2


def load_instruments(path: str | Path) -> dict | None:
    """Which instrument family plays, over time and per synth note (amadeus/audio/instruments.py), if the track
    has been separated and the instrument models are installed; computed once (~1 s), cached next to the parts.
    {"t": judgement times, "probs": (n, families), "names": family names, "note_family": per note (-1: unknown),
    "sound": (n, 1280) the melodic part's sound description per judgement}"""
    from amadeus.audio import instruments

    d = _dir(Path(path))
    f = d / "instruments.npz"
    if f.exists():
        z = np.load(f, allow_pickle=False)
        if int(z["version"]) == INSTRUMENTS_VERSION:
            return {k: (list(z[k]) if k == "names" else z[k]) for k in ("t", "probs", "names", "note_family", "sound")}
    notes = load_notes(path)
    if notes is None or not instruments.available():
        return None
    other = cached_part(path, "other")
    judged = instruments.judge(other, STEM_SR)
    fam = instruments.note_families(other, STEM_SR, notes[0], judged)
    out = {"t": judged["t"].astype(np.float32), "probs": instruments.family_probs(judged).astype(np.float32),
           "names": list(instruments.FAMILIES), "note_family": fam.astype(np.int8),
           "sound": judged["embeddings"].astype(np.float16)}  # fmt: skip
    np.savez_compressed(f, version=INSTRUMENTS_VERSION, **{k: np.asarray(v) for k, v in out.items()})
    return out


def separate_and_save(path: str | Path, verbose: bool = True) -> tuple | None:
    """Separate (or load the cached parts), find the synth notes and store them next to the parts."""
    path = Path(path)
    parts = stems(path, verbose)
    if parts is None:
        return None
    t, s, p = notes(parts["other"])
    np.savez(_dir(path) / "notes.npz", t=t, s=s, p=p)
    return t, s, p


def _lock(path: Path) -> Path:
    return STEMS_DIR / f"{path.stem}.{_key(path)}.lock"


def running(path: str | Path) -> int | None:
    """PID of a separation of this track that is still running (e.g. started by an earlier live session)."""
    lock = _lock(Path(path))
    try:
        pid = int(lock.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def start_background(path: str | Path):
    """Separate a track in its own process (own memory, no competition with the light loop); returns the
    Popen. The result appears as notes.npz; poll the process or `load_notes`."""
    import subprocess
    import sys

    path = Path(path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "amadeus.audio.stems", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        cwd=paths.ROOT,  # the package is importable from the project folder
    )
    STEMS_DIR.mkdir(parents=True, exist_ok=True)
    _lock(path).write_text(str(proc.pid))
    return proc


if __name__ == "__main__":  # python -m amadeus.audio.stems TRACK: separate it (used as a background process)
    import sys
    import time

    os.nice(5)  # be kind to a running show
    t0 = time.time()
    try:
        res = separate_and_save(sys.argv[1], verbose=False)
    finally:
        _lock(Path(sys.argv[1])).unlink(missing_ok=True)
    print(f"{'separated' if res else 'not available'} in {time.time() - t0:.0f} s", flush=True)
