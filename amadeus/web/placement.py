"""Where the fixtures are: from a photo of the lit rig, or exactly from a 3D scan (PLY) of the room."""

from __future__ import annotations

import json
import time
from pathlib import Path

from amadeus import paths
from amadeus.library import fixtures as fxlib
from amadeus.web.events import event, save_photo

SCANS = paths.CACHE / "scans"
KEEP_SCANS = 5
MAX_SCAN_BYTES = 2_000_000_000
MAX_LIGHT_S = 900.0


def lights(req):
    """{"on": true, "batch": 0}: light every fixture in its own colour for the photo (or the scan)."""
    from amadeus.setup import placement

    b = req.body()
    rig = req.show.load()
    if not b.get("on", True):
        placement.lights_off()
        event(f"{req.client} placement: lights off")
        return {"ok": True}
    lit = placement.light_up(rig, int(b.get("batch", 0)), min(float(b.get("seconds", placement.HOLD_S)), MAX_LIGHT_S))
    event(f"{req.client} placement: lights on {', '.join(a['fixture'] + '=' + a['colour'] for a in lit)}")
    return {"lit": lit, "batches": max(a["batch"] for a in placement.assignments(rig)) + 1}


def analyze_photo(req):
    """{"image", "blobs", "batch"}: where each fixture is, its mount, height and alignment → a proposal."""
    from amadeus.setup import placement

    b = req.body()
    rig = req.show.load()
    batch = int(b.get("batch", 0))
    lit = [a for a in placement.assignments(rig) if a["batch"] == batch]
    saved = save_photo(b["image"])
    spots = {k: (round(v["x"], 2), round(v["y"], 2), v["n"]) for k, v in b.get("blobs", {}).items()}
    event(f"{req.client} placement photo -> {saved}; light spots: {spots}")
    seen = placement.analyse(b["image"], lit, rig)
    event(f"  vision: {json.dumps(seen)[:600]}")
    prop = placement.propose(rig, lit, b.get("blobs", {}), seen)
    event(f"  proposal: {json.dumps(prop['changes'])[:400]} missing={prop['missing']}")
    return prop


def apply(req):
    """{"changes": [...]}: write the accepted changes into the rig."""
    from amadeus.setup import placement

    b = req.body()
    rig = req.show.load()
    placement.apply(rig, b["changes"])
    problems = fxlib.validate(rig)
    if not problems:
        req.show.save(rig)
    event(f"{req.client} placement: applied {len(b['changes'])} changes")
    return {"saved": not problems, "problems": problems}


def upload_scan(req):
    """Raw PLY body (e.g. a Scaniverse export), streamed to disk (scans can be 100+ MB), then analysed."""
    n = int(req.headers.get("Content-Length", 0))
    if n <= 0 or n > MAX_SCAN_BYTES:
        return {"error": "empty or too large upload"}, 400
    SCANS.mkdir(parents=True, exist_ok=True)
    path = SCANS / f"{time.strftime('%Y%m%d-%H%M%S')}.ply"
    with open(path, "wb") as f:
        left = n
        while left:
            chunk = req.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            f.write(chunk)
            left -= len(chunk)
    for old in sorted(SCANS.glob("*.ply"))[:-KEEP_SCANS]:
        old.unlink()
    event(f"{req.client} scan {n / 1e6:.1f} MB ({req.headers.get('X-Filename', '?')}) -> {path}")
    return _scan_result(req, path, False, None, int(req.headers.get("X-Batch", 0)))


def redo_scan(req):
    """{"scan", "flip", "moves"}: again, with the audience on the other side or markers moved."""
    b = req.body()
    path = SCANS / Path(b["scan"]).name
    return _scan_result(req, path, bool(b.get("flip")), b.get("moves") or None, int(b.get("batch", 0)))


def _scan_result(req, path: Path, flip: bool, moves, batch: int) -> dict:
    from amadeus.setup import placement, pointcloud

    rig = req.show.load()
    lit = [a for a in placement.assignments(rig) if a["batch"] == batch]
    t0 = time.monotonic()
    scan = pointcloud.analyse(path, rig, lit, flip=flip, moves=moves)
    changes = pointcloud.propose(rig, scan)
    found = "; ".join(
        f"{f['fixture']} "
        + (f"({f['x_m']}, {f['y_m']}, {f['z_m']}) {f['points']} pts" if f.get("x_m") is not None else "not found")
        for f in scan["fixtures"]
    )
    event(
        f"  scan: {scan['points']} points, up {scan['up_axis']}, ceiling {scan['ceiling_m']} m, depth "
        f"{scan['room_depth_m']} m, flip={flip}, {time.monotonic() - t0:.1f} s; {found}"
    )
    missing = [f["fixture"] for f in scan["fixtures"] if f.get("x_m") is None]
    return {**scan, "scan": path.name, "changes": changes, "missing": missing}


GET: dict = {}
POST = {
    "/api/placement/lights": lights,
    "/api/placement/analyze": analyze_photo,
    "/api/placement/apply": apply,
    "/api/scan": upload_scan,
    "/api/scan/redo": redo_scan,
}
