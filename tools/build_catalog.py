"""Rebuild the shadow catalogue (fixtures/catalog/): every QLC+, Open Fixture Library and DMXControl DDF fixture,
converted.

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
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from amadeus.library import ddf, ofl, qlc, shadow  # noqa: E402


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


def build_ddf(refresh: bool) -> int:
    """DMXControl 3 files, a device's files merged into one fixture; CC BY-SA 4.0, so its own file with credit.
    Devices also in QLC+ or the OFL stay in (search lists the first source); ones it can't read are left out."""
    items = ddf.listing(refresh)
    with ThreadPoolExecutor(4) as pool:  # a few at a time: the server answers slowly, and it's a volunteer project's
        list(pool.map(ddf.file, [f["id"] for files in ddf.devices(items).values() for f in files]))
    out, skipped = {}, 0
    for device_id, files in ddf.devices(items).items():
        try:
            defn = ddf.convert([ddf.file(f["id"]) for f in files], [f.get("mode") or "" for f in files])
        except (ValueError, ET.ParseError):
            skipped += 1
            continue
        key = f"ddf:{ddf.slug(defn['manufacturer'], defn['model'])}"
        if key in out:
            key = f"{key}-{device_id}"
        index = {
            "key": key,
            "manufacturer": defn["manufacturer"],
            "model": defn["model"],
            "kind": defn["kind"],
            "modes": {m: len(c) for m, c in defn["modes"].items()},
        }
        out[key] = {"index": index, "defn": defn}
    upstream = {
        "url": "https://ddf-library.dmxcontrol.de",
        "api": ddf.API,
        "fetched": time.strftime("%Y-%m-%d", time.gmtime((ddf.CACHE_DIR / "ddfs.json").stat().st_mtime)),
        "license": "CC-BY-SA-4.0",
        "skipped": skipped,
    }
    shadow.write("ddf", upstream, ddf.CONVERTER_VERSION, out)
    return len(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--refresh", action="store_true", help="fetch the latest libraries first")
    p.add_argument("--only", choices=["qlc", "ofl", "ddf"], help="rebuild one source's file")
    args = p.parse_args()
    builds = {
        "qlc": ("QLC+", build_qlc),
        "ofl": ("Open Fixture Library", build_ofl),
        "ddf": ("DMXControl DDF", build_ddf),
    }
    for source, (name, build) in builds.items():
        if args.only and source != args.only:
            continue
        n = build(args.refresh)
        print(f"{name}: {n} fixtures converted")
    for f in shadow.FILES.values():
        path = shadow.CATALOG_DIR / f
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
