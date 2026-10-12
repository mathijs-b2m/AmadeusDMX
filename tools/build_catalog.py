"""Rebuild the shadow catalogue (fixtures/catalog/): every QLC+ and Open Fixture Library fixture, converted.

    python tools/build_catalog.py            convert from the downloaded libraries (downloads them if missing)
    python tools/build_catalog.py --refresh  fetch the latest libraries first

Run it after changing a converter (tests/test_catalog.py fails until you do) or to pick up new fixtures.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from amadeus.library import ofl, qlc, shadow  # noqa: E402


def build_qlc(refresh: bool) -> int:
    if refresh and qlc.REPO_DIR.exists():
        subprocess.run(["git", "-C", str(qlc.REPO_DIR), "pull", "-q", "--depth", "1"], check=True)
    qlc.ensure_downloaded()
    qlc.index.cache_clear()
    (qlc.QLC_DIR / "index.json").unlink(missing_ok=True)
    commit = subprocess.run(
        ["git", "-C", str(qlc.REPO_DIR), "log", "-1", "--format=%H %cs"], capture_output=True, text=True, check=True
    ).stdout.split()
    out = {}
    for item in qlc.index():
        out[item["key"]] = {"index": item, "defn": qlc.convert(item["key"].removeprefix("qlc:"))}
    upstream = {"repo": qlc.REPO_URL, "commit": commit[0], "date": commit[1], "license": "Apache-2.0"}
    shadow.write("qlc", upstream, qlc.CONVERTER_VERSION, out)
    return len(out)


def build_ofl(refresh: bool) -> int:
    if refresh:
        shutil.rmtree(ofl.OFL_DIR, ignore_errors=True)
    ofl.ensure_downloaded()
    ofl.index.cache_clear()
    ofl.INDEX.unlink(missing_ok=True)
    out = {}
    for item in ofl.index():
        out[item["key"]] = {"index": item, "defn": ofl.convert(*item["key"].removeprefix("ofl:").split("/", 1))}
    fetched = time.strftime("%Y-%m-%d", time.gmtime((ofl.OFL_DIR / "fixtures").stat().st_mtime))
    upstream = {"url": "https://open-fixture-library.org", "fetched": fetched, "license": "MIT"}
    shadow.write("ofl", upstream, ofl.CONVERTER_VERSION, out)
    return len(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--refresh", action="store_true", help="fetch the latest QLC+ and OFL libraries first")
    args = p.parse_args()
    for name, build in (("QLC+", build_qlc), ("Open Fixture Library", build_ofl)):
        n = build(args.refresh)
        print(f"{name}: {n} fixtures converted")
    for f in shadow.FILES.values():
        path = shadow.CATALOG_DIR / f
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
