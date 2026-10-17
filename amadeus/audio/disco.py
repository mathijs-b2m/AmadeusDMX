"""Disco's sound, for the genre call: how much the track sounds like disco to EffNet-Discogs.

Disco's beat is house's (four to the floor, an open hat on every "and", 110–130 BPM), so the rhythm can't tell
them apart; the sound can: the bass guitar's octaves, strings and horns, a band's swing. EffNet-Discogs
(amadeus/audio/instruments.py) judges about two seconds of the mix at a time against 400 Discogs styles; the
disco family is Disco (Electronic and Funk / Soul), Euro-, Italo- and Nu-Disco and Boogie. Two facts:

- **disco**: the family's probability, on average over the track;
- **disco_lead**: the share of the track where it beats the families disco is mistaken for: funk and soul
  (Afrobeat, P.Funk, Jazz-Funk …) and house (Deep, Tech, Progressive …).

Measured over 75 cached tracks: disco (Chemise, Klein & M.B.O., I Coccodrilli) 0.39–0.76 and leading 0.64–0.98;
house 0.02–0.33, leading ≤ 0.18; afrobeat-funk 0.44 but leading 0.14; reggaeton, techno, hip-hop ≤ 0.02.

Judged once per file (~1 s) and cached; nothing without the models (`amadeus instruments --download`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from amadeus import paths

CACHE = paths.CACHE / "styles"
VERSION = 1
FAMILIES = {
    "disco": ("Electronic---Disco", "Electronic---Euro-Disco", "Electronic---Italo-Disco", "Electronic---Nu-Disco",
              "Funk / Soul---Disco", "Funk / Soul---Boogie"),
    "funk": ("Funk / Soul---Funk", "Funk / Soul---P.Funk", "Funk / Soul---Afrobeat", "Jazz---Afrobeat",
             "Jazz---Jazz-Funk", "Funk / Soul---Free Funk", "Funk / Soul---Soul"),
    "house": ("Electronic---House", "Electronic---Deep House", "Electronic---Tech House",
              "Electronic---Progressive House", "Electronic---Tropical House"),
}  # fmt: skip


def judge(styles: np.ndarray, names: list[str]) -> dict:
    """From the Discogs style probabilities per judgement ((n, 400)): {"disco", "disco_lead"}."""
    mass = np.stack([styles[:, [names.index(c) for c in fam]].sum(1) for fam in FAMILIES.values()])
    return {"disco": round(float(mass[0].mean()), 2), "disco_lead": round(float((mass.argmax(0) == 0).mean()), 2)}


def _cached(path: Path) -> Path:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:12]
    return CACHE / f"{path.stem}.{key}.json"


def facts(path: str | Path) -> dict:
    """{"disco", "disco_lead"} for the audio file, or {} without the models or the file."""
    from amadeus.audio import instruments

    path = Path(path)
    if not path.is_file() or not instruments.available():
        return {}
    cached = _cached(path)
    if cached.exists():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    import soundfile as sf

    try:
        y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 - an unreadable file: no disco facts
        return {}
    out = judge(instruments.judge(y.mean(axis=1), sr)["styles"], instruments.classes("effnet"))
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(out), encoding="utf-8")
    return out
