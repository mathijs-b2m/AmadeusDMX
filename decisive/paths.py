"""Where things live: the project folder (sets, fixtures, the web UI) and its cache.

Everything is resolved against the project root, so commands work from any directory.
`DECISIVE_ROOT` points elsewhere (e.g. a packaged app with its own data folder).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("DECISIVE_ROOT", Path(__file__).resolve().parent.parent))
CACHE = ROOT / ".cache"
CONFIG = ROOT / "config"  # your own sets (not in git)
EXAMPLES = ROOT / "examples"
FIXTURES = ROOT / "fixtures"
WEB = ROOT / "web"
ENV_FILE = ROOT / ".env"


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
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip().removeprefix("export ").strip(), v.strip().strip("'\""))
