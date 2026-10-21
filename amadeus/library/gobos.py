"""Gobos: what the patterns on a fixture's gobo wheel look like, and what kind of pattern each one is.

The pictures come from the fixture libraries: QLC+ draws about a thousand gobos (nearly every gobo of its
fixtures points to one), the Open Fixture Library about fifty. They ship rendered small in
fixtures/catalog/gobos.json.gz (tools/build_gobos.py): a picture is how much light the gobo lets through, white
where it is open, black where the metal blocks it, coloured for a glass gobo.

A gobo with only a name ("Stars", "Bubbles", "Gobo 5") gets a pattern drawn from its name: the visualiser
shows something of that kind, not the real thing.

Every gobo also gets a style, the director's word for its look (vocabulary.GOBO_STYLES: dots, shapes, rings,
curves): from the picture (tools/build_gobos.py measures it with `classify`) or else from the name. A fixture
without hand-made gobo_groups is grouped by these styles, so "rings" really picks the rings.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
import struct
import zlib
from functools import cache

import numpy as np

from amadeus import paths

CATALOG = paths.FIXTURES / "catalog" / "gobos.json.gz"
SIZE = 128  # pixels across a gobo picture
STYLES = ("dots", "shapes", "rings", "curves")  # vocabulary.GOBO_STYLES
FIGURE = "figure"  # a picture or words: on the wheel, never picked by style
BEAM_WHEELS = ("gobo", "gobo_shake", "gobo_rotate")  # the beam effects that put a gobo in the beam

# a gobo's name → (style, the pattern drawn for it); the first match wins
NAME_RULES = [
    (r"bubble|droplet|drop\b|dot|raster|grid|flake|snow|sparkl|stars\b|galax|confetti", "dots", "dots"),
    (r"break ?up|leaf|leaves|water|glass|cloud|ice|crack|splash|texture|fire|flame", "dots", "breakup"),
    (r"spiral|swirl|twirl|vortex|curl", "curves", "swirl"),
    (r"flower|petal|rose|daisy", "curves", "flower"),
    (r"wave|curve|organic|cone", "curves", "waves"),
    (r"ring|circle|tunnel|target|focus|eclipse|moon|crescent|orbit", "rings", "rings"),
    (r"star", "shapes", "star"),
    (r"triang|pyramid|prisma", "shapes", "triangle"),
    (r"square|rect|cube|box|diamond|kite", "shapes", "square"),
    (r"cross|plus|\bx\b", "shapes", "cross"),
    (r"line|bar|stripe|slash|beam|ray|fan|sun|burst", "shapes", "rays"),
]
# what a gobo known only by number looks like: a different pattern for each, in this order
GENERIC = ("dots", "triangle", "rings", "swirl", "star", "rays", "flower", "breakup", "square", "waves", "cross")
STYLE_OF = {p: s for _, s, p in NAME_RULES}


@cache
def catalog() -> dict[str, dict]:
    """Every rendered gobo: key ("qlc/ClayPaky/gobo00006", "ofl/biohazard") → {img (base64 PNG/JPEG), style, color}."""
    if not CATALOG.exists():
        return {}
    return json.loads(gzip.decompress(CATALOG.read_bytes()))


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def wheel(defn: dict, fx: str) -> list[str]:
    """The picture of each gobo the beam effect `fx` can put in the beam (in the order of its DMX values):
    a catalogue key, or "name/<name>" for a gobo known only by its name."""
    entry = defn.get("beam_fx", {}).get(fx, {})
    vals = next((v for v in entry.values() if isinstance(v, list)), None)
    if vals is None:
        return []
    images = defn.get("gobo_images", {}).get(fx) or defn.get("gobo_images", {}).get("gobo") or []
    names = defn.get("gobo_names") or []
    out = []
    for i in range(len(vals)):
        img = images[i] if i < len(images) else ""
        if img and img in catalog():
            out.append(img)
        else:
            out.append("name/" + (slug(names[i]) if i < len(names) and names[i] else f"gobo-{i + 1}"))
    return out


def name_rule(name: str) -> tuple[str, str] | None:
    """(style, pattern) for a gobo's name, None when the name doesn't say ("Gobo 5")."""
    n = name.lower().replace("_", " ").replace("-", " ")
    for rx, style, pattern in NAME_RULES:
        if re.search(rx, n):
            return style, pattern
    return None


def number(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else len(name)


def style(key: str) -> str:
    """The director's word for a gobo's look."""
    if key in catalog():
        return catalog()[key]["style"]
    name = key.removeprefix("name/")
    rule = name_rule(name)
    return rule[0] if rule else STYLE_OF[GENERIC[(number(name) - 1) % len(GENERIC)]]


def groups(defn: dict) -> dict[str, list[int]]:
    """The gobos of the "gobo" effect by style (1-based, like hand-made gobo_groups, which win). Pictures and words
    are in none: the show doesn't put "Happy Birthday" on the wall by itself."""
    own = {k: v for k, v in defn.get("gobo_groups", {}).items() if not k.startswith("_")}
    if own:
        return own
    out: dict[str, list[int]] = {}
    for i, key in enumerate(wheel(defn, "gobo")):
        out.setdefault(style(key), []).append(i + 1)
    out.pop(FIGURE, None)  # pictures and words: only when a wheel has nothing else (engine: every gobo)
    return out


def usable(defn: dict) -> list[int]:
    """The gobos of the "gobo" effect the show may pick when the style asked for isn't on the wheel (1-based): any
    but the pictures and words, unless that is all there is."""
    keys = wheel(defn, "gobo") or [""]
    if defn.get("gobo_groups"):
        return list(range(1, len(keys) + 1))
    some = [i + 1 for i, k in enumerate(keys) if style(k) != FIGURE]
    return some or list(range(1, len(keys) + 1))


def picture(key: str) -> str:
    """The picture as base64 (a PNG, or a JPEG for a glass gobo; for the visualisers): the catalogue's, or one
    drawn from the name."""
    if key in catalog():
        return catalog()[key]["img"]
    return base64.b64encode(drawn(key.removeprefix("name/"))).decode()


# ---------------------------------------------------------------- pictures drawn from a name


@cache
def drawn(name: str) -> bytes:
    rule = name_rule(name)
    pattern = rule[1] if rule else GENERIC[(number(name) - 1) % len(GENERIC)]
    return encode_png((pattern_image(pattern, number(name)) * 255).astype(np.uint8))


def pattern_image(pattern: str, seed: int = 1) -> np.ndarray:
    """A gobo of the given kind, SIZE × SIZE, 1 where light passes."""
    n = SIZE
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    r, a = np.hypot(x, y), np.arctan2(y, x)
    rng = np.random.default_rng(seed)
    if pattern == "dots":
        img = np.zeros((n, n), bool)
        step = 0.28
        for j, cy in enumerate(np.arange(-1, 1.01, step * 0.87)):
            for cx in np.arange(-1 + (j % 2) * step / 2, 1.01, step):
                img |= np.hypot(x - cx, y - cy) < step * 0.3
    elif pattern == "breakup":
        f = np.zeros((n, n))
        for k in range(1, 6):
            f += np.sin(x * k * 4.1 + rng.uniform(0, 6)) * np.sin(y * k * 3.7 + rng.uniform(0, 6)) / k
        img = f > 0.15
    elif pattern == "rings":
        img = np.sin(r * 22) > 0.1
    elif pattern == "swirl":
        img = np.sin(a * 3 + r * 9) > 0.2
    elif pattern == "flower":
        img = r < 0.45 + 0.4 * np.abs(np.cos(a * 3))
        img &= r > 0.12
    elif pattern == "waves":
        img = np.sin(y * 10 + np.sin(x * 4) * 2) > 0.3
    elif pattern == "star":
        k = np.cos(np.pi / 5) / np.cos((a % (2 * np.pi / 5)) - np.pi / 5)
        img = r < 0.85 * (0.42 + 0.58 * (k - np.cos(np.pi / 5)) / (1 - np.cos(np.pi / 5)))
    elif pattern == "triangle":
        k = np.cos(np.pi / 3) / np.cos(((a + np.pi / 2) % (2 * np.pi / 3)) - np.pi / 3)
        img = r < 0.8 * k
    elif pattern == "square":
        img = (np.abs(x) < 0.55) & (np.abs(y) < 0.55) & ~((np.abs(x) < 0.4) & (np.abs(y) < 0.4))
    elif pattern == "cross":
        img = (np.abs(x) < 0.14) | (np.abs(y) < 0.14)
    else:  # rays
        img = np.cos(a * 8) > 0.55
    return (img & (r < 0.97)).astype(np.float32)


def encode_png(a: np.ndarray) -> bytes:
    """A small PNG (8-bit grey, or RGB for an H × W × 3 array), without an imaging library."""
    h, w = a.shape[:2]
    colour = 2 if a.ndim == 3 else 0
    raw = b"".join(b"\0" + a[row].tobytes() for row in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    head = struct.pack(">IIBBBBB", w, h, 8, colour, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


# ---------------------------------------------------------------- what a picture shows (tools/build_gobos.py)


def features(t: np.ndarray) -> dict:
    """What `classify` measures in a gobo picture (transmission 0..1, square, grey)."""
    from scipy import ndimage

    n = t.shape[0]
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n * 2 - 1
    r = np.hypot(x, y)
    disc = r < 0.94
    disc_px = disc.sum()
    t = np.where(disc, t, 0.0)
    lit = t > 0.5
    # concentric: how much of the picture's light varies with the radius only
    rs, angles = np.linspace(0.04, 0.92, 32), np.linspace(-np.pi, np.pi, 128, endpoint=False)
    rr, aa = np.meshgrid(rs, angles, indexing="ij")
    polar = ndimage.map_coordinates(t, [(rr * np.sin(aa) + 1) * n / 2 - 0.5, (rr * np.cos(aa) + 1) * n / 2 - 0.5], order=1)
    concentric = 1 - polar.std(axis=1).mean() / (polar.std() + 1e-6)
    swings = int(np.sum(np.abs(np.diff(polar.mean(axis=1) > 0.5))))
    # the holes: how big, how round, where, and how far they reach from the centre outwards
    holes, _ = ndimage.label(lit)
    stats = []
    for k, sl in enumerate(ndimage.find_objects(holes)):
        m = holes[sl] == k + 1
        area = int(m.sum())
        if area < 6:
            continue
        hr = r[sl][m]
        if hr.min() > 0.86:  # a speck on the rim
            continue
        hy, hx = y[sl][m], x[sl][m]
        cy, cx = hy.mean(), hx.mean()
        reach = np.hypot(hy - cy, hx - cx).max() + 1 / n
        stats.append((area / disc_px, area * (2 / n) ** 2 / (np.pi * reach**2), np.hypot(cx, cy), np.ptp(hr)))
    a = np.array(stats).reshape(-1, 4)
    # edges: along a straight edge, the line through a point in the edge's direction stays on the edge; on a
    # curve it leaves it a few pixels on
    gy, gx = ndimage.sobel(t, 0), ndimage.sobel(t, 1)
    edge = (np.hypot(gx, gy) > 0.5) & (r < 0.88)
    rim = lit ^ ndimage.binary_erosion(lit)
    rim &= r < 0.88
    near = ndimage.binary_dilation(rim)
    jxx, jyy, jxy = (ndimage.gaussian_filter(v, 1.5) for v in (gx * gx, gy * gy, gx * gy))
    theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + np.pi / 2  # along the edge
    py, px = np.nonzero(rim)
    if len(py) > 4000:
        pick = np.linspace(0, len(py) - 1, 4000).astype(int)
        py, px = py[pick], px[pick]
    ty, tx = np.sin(theta[py, px]), np.cos(theta[py, px])
    hits = []
    for d in (5, 8, 11):
        for sgn in (1, -1):
            qy = np.clip(np.round(py + sgn * d * ty).astype(int), 0, n - 1)
            qx = np.clip(np.round(px + sgn * d * tx).astype(int), 0, n - 1)
            hits.append(near[qy, qx])
    straight = float(np.mean(hits)) if len(py) else 1.0

    # turned by a fraction of a circle, an abstract pattern looks the same; a picture (an animal, a skyline, text)
    # doesn't
    tc = t - t[disc].mean()
    norm = float((tc[disc] ** 2).sum()) + 1e-9
    turned = max(
        float((tc * ndimage.rotate(tc, 360 / k, reshape=False, order=1))[disc].sum()) / norm for k in (2, 3, 4, 5, 6, 8)
    )
    many = len(a) > 0
    return {
        "open": float(lit[disc].mean()),
        "concentric": float(concentric),
        "swings": swings,
        "holes": len(a),
        "hole": float(np.median(a[:, 0])) if many else 0.0,
        "round": float(np.median(a[:, 1])) if many else 0.0,
        "ring_spread": float(a[:, 2].std() / max(a[:, 2].mean(), 1e-3)) if many else 1.0,
        "ring_r": float(a[:, 2].mean()) if many else 0.0,
        "radial": float(np.median(a[:, 3])) if many else 0.0,
        "edges": float(edge.sum() / disc_px),
        "straight": straight,
        "symmetry": turned,
    }


def classify(t: np.ndarray, colour: bool = False) -> str:
    """The style of a gobo picture (transmission 0..1, square, grey; `colour`: a glass gobo): dots, shapes, rings,
    curves or figure.

    - rings: the light depends on the distance from the centre only (circles, a tunnel), or small holes sit on
      one circle (a ring of dots, a broken ring);
    - dots: many small round holes (dots, bubbles), many tiny ones (flakes, raster, stars) or a fine texture;
    - shapes: figures with straight edges (triangles, stars, bars, symbols);
    - curves: the rest: swirls, petals, waves, organic lines;
    - figure: a picture or words (an animal, a skyline, "Happy Birthday"): the show doesn't pick these itself.
    """
    f = features(t)
    scattered_dots = f["holes"] >= 5 and f["round"] > 0.55
    if not colour and f["symmetry"] < 0.3 and f["edges"] < 0.45 and f["holes"] <= 30 and not scattered_dots:
        return FIGURE
    if f["holes"] == 1 and f["round"] > 0.8 and f["hole"] < 0.3:  # one round hole: a beam reducer
        return "rings"
    if f["concentric"] > 0.75 and f["swings"] >= 2:
        return "rings"
    on_circle = f["ring_spread"] < 0.08 and f["ring_r"] > 0.3 and f["radial"] < 0.6 * f["ring_r"]
    if 3 <= f["holes"] <= 48 and on_circle:
        return "rings"
    if (f["holes"] >= 8 and f["round"] > 0.55 and f["hole"] < 0.03) or (f["holes"] >= 25 and f["hole"] < 0.008):
        return "dots"
    if f["edges"] > 0.5 and f["straight"] < 0.6:  # a fine texture
        return "dots"
    return "shapes" if f["straight"] > 0.66 else "curves"
