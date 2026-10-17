"""Where things live: what ships (the package, the web UI, the fixture library, the examples) and your own data
(sets and rigs, settings, fixtures you added or calibrated, the cache).

In a checkout both are the project folder, so commands work from any directory. `AMADEUS_ROOT` points the shipped
part elsewhere (`DECISIVE_ROOT`, its name before the rename to Amadeus DMX, still works); `AMADEUS_DATA` puts your
data in a folder of its own: the Mac app ships the engine read-only inside the app and keeps your data in
~/Library/Application Support/Amadeus DMX, so an update never touches it; the Windows app ships it in the program
folder and keeps your data in %LOCALAPPDATA%\\Amadeus DMX. Paths are pathlib's: either system's separators work.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("AMADEUS_ROOT") or os.environ.get("DECISIVE_ROOT") or Path(__file__).resolve().parent.parent)
DATA = Path(os.environ.get("AMADEUS_DATA") or ROOT)
CACHE = DATA / ".cache"
CONFIG = DATA / "config"  # your own sets (not in git)
EXAMPLES = ROOT / "examples"
FIXTURES = ROOT / "fixtures"
USER_FIXTURES = DATA / "fixtures"  # added and calibrated fixtures; the same folder in a checkout
WEB = ROOT / "web"
ENV_FILE = DATA / ".env"


def ollama_host() -> str:
    """Where Ollama runs: OLLAMA_HOST (Ollama's own setting: "host", "host:port" or a URL), else this computer."""
    h = os.environ.get("OLLAMA_HOST", "").strip().rstrip("/")
    if not h:
        return "http://localhost:11434"
    if "://" in h:
        return h  # a URL: as given (a proxy may serve it on its own port)
    return "http://" + h + ("" if ":" in h else ":11434")


def load_dotenv(path: Path = ENV_FILE) -> None:
    """KEY=value lines from .env (if present) for variables not already set in the shell."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip().removeprefix("export ").strip(), v.strip().strip("'\""))
