"""Which instruments play, by name, over time: the MTG-Jamendo instrument classifier from Essentia.

Two small ONNX models from the Music Technology Group (Universitat Pompeu Fabra), run with ONNX Runtime:
EffNet-Discogs (a sound description, plus 400 Discogs styles) and on top of it the MTG-Jamendo instrument
head (40 instruments: synthesizer, pad, piano, electric piano, rhodes, keyboard, organ, strings, voice, …). Each
judges about two seconds of audio; one judgement a second. Run on the separated melodic part (Demucs "other"),
it says per stretch of the track whether a synth or a piano is playing.

Essentia itself isn't needed: its input step (TensorflowInputMusiCNN: 16 kHz, 512-sample frames, hop 256,
96 Slaney mel bands up to 8 kHz, log10(1 + 10000·x)) is done here in numpy.

**License:** the MTG models are CC BY-NC-SA 4.0 (non-commercial; a proprietary license on request from the MTG).
They are not part of this repository: `decisive instruments --download` fetches them once into
~/.cache/decisive/models. Without them the analysis works as before.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import numpy as np

MODELS = Path.home() / ".cache" / "decisive" / "models"
BASE = "https://essentia.upf.edu/models/"
FILES = {
    "effnet": "feature-extractors/discogs-effnet/discogs-effnet-bsdynamic-1",
    "instrument": "classification-heads/mtg_jamendo_instrument/mtg_jamendo_instrument-discogs-effnet-1",
}
SR = 16000
FRAME, HOP, BANDS = 512, 256, 96
PATCH, PATCH_HOP = 128, 62  # frames per judgement (~2 s) and between judgements (~1 s)
MELODIC = ("synthesizer", "pad", "piano", "electricpiano", "rhodes", "keyboard", "organ", "strings", "voice",
           "guitar", "electricguitar", "acousticguitar", "brass", "bell", "sampler", "computer")  # fmt: skip


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return all((MODELS / f"{Path(f).name}.onnx").exists() for f in FILES.values())


def download() -> None:
    """Fetch the two models (~21 MB) and their descriptions into MODELS."""
    import urllib.request

    MODELS.mkdir(parents=True, exist_ok=True)
    for f in FILES.values():
        for ext in (".onnx", ".json"):
            dest = MODELS / f"{Path(f).name}{ext}"
            if not dest.exists():
                urllib.request.urlretrieve(BASE + f + ext, dest)


@cache
def _session(name: str):
    import onnxruntime as ort

    return ort.InferenceSession(str(MODELS / f"{Path(FILES[name]).name}.onnx"), providers=["CPUExecutionProvider"])


@cache
def classes(name: str) -> list[str]:
    return json.loads((MODELS / f"{Path(FILES[name]).name}.json").read_text())["classes"]


def _hz_to_mel(f):  # Slaney: linear below 1 kHz, logarithmic above
    f = np.asarray(f, float)
    return np.where(f < 1000, f * 3 / 200, 15 + np.log(np.maximum(f, 1e-9) / 1000) / (np.log(6.4) / 27))


def _mel_to_hz(m):
    m = np.asarray(m, float)
    return np.where(m < 15, m * 200 / 3, 1000 * np.exp((m - 15) * np.log(6.4) / 27))


@cache
def _filterbank() -> np.ndarray:
    """96 triangles on the Slaney mel scale, 0..8 kHz, each with unit area (Essentia's 'unit_tri')."""
    edges = _mel_to_hz(np.linspace(_hz_to_mel(0), _hz_to_mel(SR / 2), BANDS + 2))
    freqs = np.arange(FRAME // 2 + 1) * SR / FRAME
    fb = np.zeros((BANDS, len(freqs)))
    for b in range(BANDS):
        lo, mid, hi = edges[b : b + 3]
        up = (freqs - lo) / max(mid - lo, 1e-9)
        down = (hi - freqs) / max(hi - mid, 1e-9)
        fb[b] = np.maximum(0, np.minimum(up, down)) * 2 / max(hi - lo, 1e-9)
    return fb


def melspectrogram(y: np.ndarray, power: bool = True, window_norm: bool = False) -> np.ndarray:
    """(frames, 96) log-compressed mel bands of 16 kHz mono audio, as Essentia feeds the EffNet."""
    y = np.asarray(y, np.float32)
    pad = np.pad(y, (FRAME // 2, FRAME // 2))
    n = 1 + (len(pad) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    win = np.hanning(FRAME + 1)[:-1].astype(np.float32)  # periodic Hann
    if window_norm:
        win = win * 2 / win.sum()
    spec = np.abs(np.fft.rfft(pad[idx] * win, axis=1))
    if power:
        spec = spec**2
    mel = spec @ _filterbank().T
    return np.log10(1 + 10000 * mel).astype(np.float32)


def _resample(y: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return y
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr, SR)
    return resample_poly(y, SR // g, sr // g).astype(np.float32)


def judge(y: np.ndarray, sr: int, **mel_opts) -> dict:
    """Over the audio, about once a second: {"t": patch centres (s), "instruments": (n, 40) probabilities,
    "styles": (n, 400) Discogs style probabilities, "embeddings": (n, 1280)}."""
    m = melspectrogram(_resample(np.asarray(y, np.float32), sr), **mel_opts)
    if len(m) < PATCH:
        m = np.pad(m, ((0, PATCH - len(m)), (0, 0)))
    starts = np.arange(0, len(m) - PATCH + 1, PATCH_HOP)
    patches = np.stack([m[s : s + PATCH] for s in starts])
    styles, emb = [], []
    for k in range(0, len(patches), 64):
        a, e = _session("effnet").run(None, {"melspectrogram": patches[k : k + 64]})
        styles.append(a)
        emb.append(e)
    styles, emb = np.concatenate(styles), np.concatenate(emb)
    inst = _session("instrument").run(None, {"embeddings": emb})[0]
    return {"t": (starts + PATCH / 2) * HOP / SR, "instruments": inst, "styles": styles, "embeddings": emb}


# ------------------------------------------------------------------------------- families and notes

# What the lights care about: which kind of instrument plays. The classifier's 40 names in families (a family's
# probability: its most likely member).
FAMILIES = {
    "synth": ("synthesizer", "computer", "sampler"),
    "keys": ("piano", "electricpiano", "rhodes", "keyboard"),
    "pad": ("pad",),
    "guitar": ("guitar", "electricguitar", "acousticguitar", "classicalguitar"),
    "voice": ("voice",),
    "strings": ("strings", "violin", "viola", "cello", "orchestra"),
    "organ": ("organ", "pipeorgan", "accordion", "harmonica"),
    "brass": ("brass", "trumpet", "trombone", "horn", "saxophone"),
    "bells": ("bell", "harp"),
}
SURE = 0.35  # a family this likely, at least twice any other: it plays alone there (the track teaches its sound)
HEARD = 0.15  # a family at least this likely around a note may have played it
MIN_TAUGHT = 8  # notes needed to learn a family's sound in this track


def family_probs(judged: dict) -> np.ndarray:
    """(n, len(FAMILIES)): per judgement, each family's probability."""
    names = classes("instrument")
    inst = judged["instruments"]
    return np.stack([inst[:, [names.index(c) for c in members]].max(1) for members in FAMILIES.values()], axis=1)


def _fingerprint(mel: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """A note's sound, not its pitch: the shape of its spectrum over its first ~80 ms (cepstral coefficients 1-19
    of the log mel bands: the envelope, without the level), and how fast it dies away."""
    from scipy.fft import dct

    n = len(mel)
    out = []
    for f in frames:
        seg = mel[min(f, n - 1) : min(f + 5, n)]
        later = mel[min(f + 8, n - 1) : min(f + 16, n)]
        c = dct(seg.mean(0), norm="ortho")[1:20]
        decay = float(seg.sum(1).mean() - (later.sum(1).mean() if len(later) else 0.0)) / BANDS
        out.append(np.r_[c, decay])
    x = np.array(out)
    return (x - x.mean(0)) / (x.std(0) + 1e-6) if len(x) > 1 else x


def note_families(other: np.ndarray, sr: int, note_t: np.ndarray, judged: dict) -> np.ndarray:
    """Which family played each note (index into FAMILIES, -1: unknown).

    Where one family clearly plays alone (SURE, and twice any other), its notes are its own; from those the
    track teaches what each family sounds like here. Every other note goes to the family whose sound it is
    closest to, among the families heard around it."""
    note_t = np.asarray(note_t, float)
    if not len(note_t):
        return np.zeros(0, int)
    probs = family_probs(judged)
    k = np.clip(np.searchsorted(judged["t"], note_t), 0, len(judged["t"]) - 1)  # the judgement around each note
    p = probs[k]
    srt = np.sort(p, axis=1)
    alone = (srt[:, -1] >= SURE) & (srt[:, -1] >= 2 * srt[:, -2])
    fam = np.where(alone, p.argmax(1), -1)
    mel = melspectrogram(_resample(np.asarray(other, np.float32), sr))
    x = _fingerprint(mel, np.round(note_t * SR / HOP).astype(int))
    taught = [f for f in range(len(FAMILIES)) if (fam == f).sum() >= MIN_TAUGHT]
    if not taught:
        return np.where(p.max(1) >= HEARD, p.argmax(1), -1)
    centres = {f: x[fam == f].mean(0) for f in taught}
    for i in np.flatnonzero(fam < 0):
        heard = [f for f in taught if p[i, f] >= HEARD]
        if heard:
            fam[i] = min(heard, key=lambda f: float(np.linalg.norm(x[i] - centres[f])))
    return fam
