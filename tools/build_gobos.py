"""Rebuild the gobo pictures (fixtures/catalog/gobos.json.gz) from the QLC+ and Open Fixture Library gobos.

    pip install resvg-py pillow           (only for this tool: the show reads the finished catalogue)
    python tools/build_gobos.py           render from the downloaded libraries (fetches their gobos if missing)
    python tools/build_gobos.py --sheet out.png    also draw a contact sheet: every gobo under its style

Each picture is rendered at amadeus.library.gobos.SIZE pixels, as the light it lets through (a 16-grey PNG, a JPEG for a glass gobo): what a library draws
transparent or white passes the light, black blocks it, a glass gobo keeps its colours. Its style (dots, shapes,
rings, curves) is measured from the picture (gobos.classify).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from amadeus.library import gobos, ofl, qlc  # noqa: E402

OPEN = {"qlc/Others/open"}  # the open hole: not a gobo


def qlc_dir(given: str | None) -> Path:
    if given:
        return Path(given)
    qlc.ensure_downloaded()
    gdir = qlc.REPO_DIR / "resources" / "gobos"
    if not gdir.exists():
        subprocess.run(
            ["git", "-C", str(qlc.REPO_DIR), "sparse-checkout", "set", "resources/fixtures", "resources/gobos"],
            check=True,
        )
    return gdir


def ofl_dir(given: str | None) -> Path:
    if given:
        return Path(given)
    gdir = ofl.OFL_DIR / "resources" / "gobos"
    if not gdir.exists():
        print("Downloading the Open Fixture Library gobos …")
        data = urllib.request.urlopen(ofl.OFL_TARBALL, timeout=120).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                parts = m.name.split("/", 1)
                if len(parts) == 2 and parts[1].startswith("resources/gobos/"):
                    m.name = parts[1]
                    tar.extract(m, ofl.OFL_DIR, filter="data")
    return gdir


def render(path: Path, size: int):
    """The picture as RGBA, size × size."""
    import resvg_py
    from PIL import Image

    if path.suffix == ".svg":
        txt = path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"<svg\b[^>]*>", txt)
        tag = re.sub(r"\s(width|height)=\"[^\"]*\"", "", m.group(0)).replace("<svg", f'<svg width="{size}" height="{size}"', 1)
        if "viewBox" not in tag:  # sized only by width/height: keep their box
            w = re.search(r'\swidth="([\d.]+)', m.group(0))
            h = re.search(r'\sheight="([\d.]+)', m.group(0))
            if w and h:
                tag = tag.replace("<svg", f'<svg viewBox="0 0 {w.group(1)} {h.group(1)}"', 1)
        png = bytes(resvg_py.svg_to_bytes(svg_string=txt[: m.start()] + tag + txt[m.end() :]))
        im = Image.open(io.BytesIO(png))
    else:
        im = Image.open(path)
    return im.convert("RGBA").resize((size, size), Image.LANCZOS)


def transmission(im) -> tuple[np.ndarray, bool]:
    """Light let through, 0..1 (H × W, or H × W × 3 for a coloured glass gobo), and whether it is coloured."""
    from scipy import ndimage

    a = np.asarray(im, dtype=np.float32) / 255
    alpha = a[..., 3:]
    # transparent passes the light, except around the drawing: what is transparent from the picture's edge on is
    # outside the gobo (its metal rim)
    # (or white, around a picture drawn on white): from the corners in, as far as the rim
    rgb = a[..., :3] * alpha + (1 - alpha)
    n = rgb.shape[0]
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    light = (rgb.mean(axis=2) > 0.5) & (np.hypot(x, y) > 0.8)
    clear, _ = ndimage.label(light)
    corners = {clear[0, 0], clear[0, -1], clear[-1, 0], clear[-1, -1]} - {0}
    rgb = np.where(np.isin(clear, list(corners))[..., None], 0.0, rgb)
    rgb *= (np.hypot(x, y) < 0.98)[..., None]  # the lens is round
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    coloured = float(np.mean(chroma > 0.15)) > 0.05
    return (rgb if coloured else rgb.mean(axis=2)), coloured


def picture_b64(t: np.ndarray) -> str:
    """Small: a metal gobo as a 16-grey PNG, a glass gobo as a JPEG."""
    from PIL import Image

    im = Image.fromarray((np.clip(t, 0, 1) * 255).astype(np.uint8), "RGB" if t.ndim == 3 else "L")
    buf = io.BytesIO()
    if t.ndim == 3:
        im.save(buf, "JPEG", quality=80, optimize=True)
    else:
        im.quantize(16, dither=Image.Dither.NONE).save(buf, "PNG", optimize=True, bits=4)
    return base64.b64encode(buf.getvalue()).decode()


def sources(qdir: Path, odir: Path):
    for p in sorted(qdir.rglob("*")):
        if p.suffix in (".svg", ".png"):
            yield f"qlc/{p.relative_to(qdir).with_suffix('').as_posix()}", p
    for p in sorted(odir.glob("*")):
        if p.suffix in (".svg", ".png"):
            yield f"ofl/{p.stem}", p


def sheet(entries: dict, out: str):
    from PIL import Image, ImageDraw

    w, cols = 48, 24
    rows = sum(-(-sum(1 for e in entries.values() if e["style"] == s) // cols) + 1 for s in (*gobos.STYLES, gobos.FIGURE))
    img = Image.new("RGB", (w * cols, rows * w), (40, 0, 40))
    d = ImageDraw.Draw(img)
    row = 0
    for s in (*gobos.STYLES, gobos.FIGURE):
        d.text((4, row * w + 16), s.upper(), fill="white")
        row += 1
        keys = [k for k, e in entries.items() if e["style"] == s]
        for i, k in enumerate(keys):
            pic = Image.open(io.BytesIO(base64.b64decode(entries[k]["img"]))).convert("RGB").resize((w - 2, w - 2))
            img.paste(pic, (i % cols * w, (row + i // cols) * w))
        row += -(-len(keys) // cols)
    img.save(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--qlc", help="a QLC+ resources/gobos folder (default: the downloaded library)")
    p.add_argument("--ofl", help="an Open Fixture Library resources/gobos folder (default: the downloaded library)")
    p.add_argument("--sheet", help="also write a contact sheet of every gobo by style")
    args = p.parse_args()
    entries = {}
    for key, path in sources(qlc_dir(args.qlc), ofl_dir(args.ofl)):
        if key in OPEN:
            continue
        try:
            t, coloured = transmission(render(path, gobos.SIZE))
        except Exception as e:  # noqa: BLE001 (a broken picture in a library: leave it out)
            print(f"  skipped {key}: {e}")
            continue
        grey = t.mean(axis=2) if coloured else t
        entries[key] = {"img": picture_b64(t), "style": gobos.classify(grey, coloured), **({"color": True} if coloured else {})}
    gobos.CATALOG.write_bytes(gzip.compress(json.dumps(entries, separators=(",", ":")).encode(), 9, mtime=0))
    counts = {s: sum(1 for e in entries.values() if e["style"] == s) for s in (*gobos.STYLES, gobos.FIGURE)}
    print(f"{len(entries)} gobos → {gobos.CATALOG.relative_to(ROOT)} ({gobos.CATALOG.stat().st_size // 1024} KB): {counts}")
    if args.sheet:
        sheet(entries, args.sheet)


if __name__ == "__main__":
    main()
