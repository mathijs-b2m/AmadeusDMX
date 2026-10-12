"""The shadow catalogue: every QLC+ and Open Fixture Library fixture, already converted to our format.

Shipped in fixtures/catalog/ (one compressed file per source), so searching and adding a fixture work offline
and on the first run, and a converter fix reaches every fixture at once. `tools/build_catalog.py` rebuilds it
from the libraries (needs the internet); a fixture that isn't in it yet is converted live, as before.

These are converted, not checked on real hardware: a fixture someone adds is copied into fixtures/<brand>/
like before, where it can be checked and calibrated (`decisive test`, `colors`, `gobos`, tools/twin.py).
"""

from __future__ import annotations

import gzip
import json
from functools import cache

from decisive import paths

CATALOG_DIR = paths.FIXTURES / "catalog"
FILES = {"qlc": "qlcplus.json.gz", "ofl": "ofl.json.gz"}


@cache
def load(source: str) -> dict:
    """{"converter": version, "upstream": {...}, "fixtures": {key: {"index": {...}, "defn": {...}}}}, or {}."""
    path = CATALOG_DIR / FILES[source]
    if not path.exists():
        return {}
    return json.loads(gzip.decompress(path.read_bytes()))


def index(source: str) -> list[dict] | None:
    """The source's search entries (as qlc.index / ofl.index give them), None without a catalogue."""
    data = load(source)
    return [f["index"] for f in data["fixtures"].values()] if data else None


def get(key: str) -> dict | None:
    """'qlc:Brand/File.qxf' or 'ofl:brand/model' → its converted definition (a copy), None if not in it."""
    source = key.split(":", 1)[0]
    if source not in FILES:
        return None
    entry = load(source).get("fixtures", {}).get(key)
    return json.loads(json.dumps(entry["defn"])) if entry else None


def write(source: str, upstream: dict, converter: int, fixtures: dict[str, dict]):
    """Save a source's catalogue: sorted and with a fixed timestamp, so a rebuild only differs where a fixture
    really changed."""
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"converter": converter, "upstream": upstream, "fixtures": dict(sorted(fixtures.items()))}
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    (CATALOG_DIR / FILES[source]).write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    load.cache_clear()
