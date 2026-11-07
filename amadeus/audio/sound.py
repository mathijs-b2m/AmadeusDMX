"""What a track sounds like to EffNet-Discogs (amadeus/audio/instruments.py), for the genre call: about two seconds
of the mix at a time against 400 Discogs styles, boiled down to what disco.py and hardcore.py need to know.

Judged once per file (~1 s) and cached; nothing without the models (`amadeus instruments --download`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from amadeus import paths
from amadeus.audio import disco, hardcore

CACHE = paths.CACHE / "styles"
VERSION = 2


def _cached(path: Path) -> Path:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:12]
    return CACHE / f"{path.stem}.{key}.json"


def facts(path: str | Path) -> dict:
    """The sound's facts for the audio file ({"disco", "disco_lead", "hardcore", …}), or {} without the models or
    the file."""
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
    except Exception:  # noqa: BLE001 - an unreadable file: no facts
        return {}
    styles, names = instruments.judge(y.mean(axis=1), sr)["styles"], instruments.classes("effnet")
    out = {**disco.judge(styles, names), **hardcore.judge(styles, names)}
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(out), encoding="utf-8")
    return out
