"""The setup API's event log: printed, and appended to .cache/setup-events.log (to debug the phone flow)."""

from __future__ import annotations

import base64
import time

from amadeus import paths

EVENT_LOG = paths.CACHE / "setup-events.log"
LABEL_DIR = paths.CACHE / "labels"
KEEP_PHOTOS = 20


def event(text: str):
    line = f"{time.strftime('%H:%M:%S')} {text}"
    print(line, flush=True)
    try:
        with EVENT_LOG.open("a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def save_photo(data_url: str) -> str:
    """Keep the last photos (what the phone actually sent) for checking recognition problems."""
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    path = LABEL_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
    for old in sorted(LABEL_DIR.glob("*.jpg"))[:-KEEP_PHOTOS]:
        old.unlink()
    return str(path)
