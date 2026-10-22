"""PDFs a venue sends: patch lists, light plots and the technical rider, read with AI (your own OpenAI key).

Every page of every PDF is read. Pages with text (patch lists, riders) go together as their text, laid out in
columns as on the page; pages that are drawings (hardly any text) go one by one as that page. Two kinds of
request (the Responses API, answers in a fixed JSON form):

- the text: every patched fixture (its number, type, where, universe, address, a range), the modes the notes
  name ("EXTENDED 56 CHANNEL"), the stage's size and heights, and rows that are house lights;
- each drawing: a plan or a 3D view, where the audience is, the stage's front edge and its ends (or the room's
  side walls) for the scale, every fixture symbol with its label and place, the trusses as lines.

The patch is what the fixtures are; a drawing only places them: a symbol is matched to its row by number
("#101", "101") or by address ("2.169", "1.34"). Answers are cached, so importing again costs nothing.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
from pathlib import Path

from amadeus import paths
from amadeus.rig.importer.draft import Draft, Item

MODEL = "gpt-6-luna"
CACHE = paths.CACHE / "import"
KEY_NOTE = (
    "{name}: PDFs are read with AI, which needs your own OpenAI API key (Settings › OpenAI in the app, or "
    "OPENAI_API_KEY in .env); nothing was sent. MVR files and patch sheets (CSV, Excel) import without one"
)
DRAWING_WORDS = 40  # a page with fewer words than this is a drawing


def has_key() -> bool:
    paths.load_dotenv()
    return bool(os.environ.get("OPENAI_API_KEY"))


def pages(path: Path) -> list[dict]:
    """Per page: its text (in columns as laid out) and whether it is a drawing."""
    from pypdf import PdfReader

    out = []
    for n, page in enumerate(PdfReader(path).pages, 1):
        text = page.extract_text(extraction_mode="layout") or ""
        out.append({"page": n, "text": text, "drawing": len(re.findall(r"[A-Za-z]{2,}", text)) < DRAWING_WORDS})
    return out


# ------------------------------------------------------------------ the requests


def _nullable(t: str) -> dict:
    return {"type": [t, "null"]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


TEXT_SCHEMA = _obj(
    {
        "fixtures": {
            "type": "array",
            "items": _obj(
                {
                    "number": {"type": "string", "description": "its id or number in the list (#101 → 101), or ''"},
                    "type": {"type": "string", "description": "the fixture type as written"},
                    "manufacturer": {"type": "string", "description": "the brand, when the text says it, else ''"},
                    "where": {"type": "string", "description": "the position/description column"},
                    "universe": _nullable("integer"),
                    "address": _nullable("integer"),
                    "last_address": _nullable("integer"),
                    "per_channel": {
                        "type": "boolean",
                        "description": "an address range that is a run of dimmer channels, one conventional light "
                        "on each (not one fixture's channels)",
                    },
                    "count": {"type": "integer", "description": "identical units the row stands for, usually 1"},
                    "house_only": {
                        "type": "boolean",
                        "description": "house or work lights, interior lights, network gear: not for a show",
                    },
                }
            ),
        },
        "modes": {
            "type": "array",
            "items": _obj({"type": {"type": "string"}, "mode": {"type": "string"}, "channels": _nullable("integer")}),
        },
        "stage": _obj(
            {
                "width_m": _nullable("number"),
                "usable_width_m": _nullable("number"),
                "depth_m": _nullable("number"),
                "grid_height_m": _nullable("number"),
                "deck_height_m": _nullable("number"),
                "hall_grid_height_m": _nullable("number"),
            }
        ),
    }
)

TEXT_PROMPT = (
    "Pages from a music venue's documents (a DMX patch list and/or the technical rider). List every patched "
    "lighting fixture, one entry per row of the patch (a row with an address range such as '1.013 > 1.019' "
    "stays one entry with last_address 19; say whether such a range is a run of dimmer channels, one "
    "conventional light per channel, or the channels of one fixture). Addresses written 'u.aaa' are "
    "universe.address. Notes printed beside a table are notes, not part of the rows next to them. Mark house and "
    "work lights, interior lights and network gear as house_only "
    "(a moving light, strobe or blinder never is). Give the DMX modes the notes name (e.g. "
    "'AYRTON DIABLO S EXTENDED 56 CHANNEL' → type Diablo S, mode Extended, 56 channels). From the rider: the "
    "stage's total and usable width, its depth, the height from the stage floor to the grid, the stage's own "
    "height above the hall floor, and the hall's grid height above the hall floor. Use null for what isn't "
    "there; never invent rows."
)

PLAN = _obj(
    {
        "title": {"type": "string"},
        "area": {"type": "string", "enum": ["stage", "hall", "both", "other"]},
        "audience": {"type": "string", "enum": ["bottom", "top", "left", "right"]},
        "stage_edge": _nullable("number"),
        "stage_back": _nullable("number"),
        "stage_end_a": _nullable("number"),
        "stage_end_b": _nullable("number"),
        "wall_a": _nullable("number"),
        "wall_b": _nullable("number"),
        "symbols": {
            "type": "array",
            "items": _obj(
                {
                    "label": {"type": "string", "description": "the number or address printed at the symbol"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "floor": {"type": "boolean", "description": "standing on the floor rather than hanging"},
                }
            ),
        },
        "trusses": {
            "type": "array",
            "items": _obj(
                {
                    "label": {"type": "string"},
                    "x1": {"type": "number"},
                    "y1": {"type": "number"},
                    "x2": {"type": "number"},
                    "y2": {"type": "number"},
                }
            ),
        },
    }
)
PLOT_SCHEMA = _obj({"plans": {"type": "array", "items": PLAN}})

PLOT_PROMPT = (
    "One page of a music venue's lighting drawings. List each plan on it (a drawing seen from above; a page can "
    "hold several, e.g. the stage roof and the stage truss); 3D views and photos are not plans: leave them out. "
    "{sizes}All positions are fractions of the whole page: x from its left edge, y from its top (0..1). Per "
    "plan: its title, whether it shows the stage, the hall (audience area) or both, and on which side of the "
    "plan the audience is (the side away from the stage, towards the front of house). The stage's front edge "
    "and its back edge (y, or x when the audience is left or right; on a hall plan without the stage: the "
    "hall's end wall at the stage as the front edge); the whole stage platform's two outer ends along the "
    "front edge (x, or y), not a riser on it; the two side walls of the audience floor where it meets the "
    "stage: the edges of the floor people stand on, inside any balconies or stairs, not the area the fixtures "
    "cover; the printed scale (100 for 1:100). Null for what isn't drawn. Then every lighting fixture symbol, "
    "moving heads, strobes, blinders and conventional lights alike: the label printed at it (a number such as "
    "101 or #101, or a DMX address such as 2.169 or 1.34; dense trusses print them in a row above or below the "
    "symbols), the centre of the symbol, and whether it stands on the floor. And each truss or pipe they hang "
    "on, as a line from end to end.{labels}"
)


def _ask(client, content: list[dict], schema: dict, name: str) -> dict:
    key = hashlib.sha1(json.dumps([MODEL, name, content, schema], sort_keys=True).encode()).hexdigest()
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    r = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
    )
    answer = json.loads(r.output_text)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(answer), encoding="utf-8")
    return answer


def page_pdf(path: Path, n: int) -> tuple[str, float, float]:
    """Page `n` alone as a PDF (a data URL), and its width and height in points."""
    from pypdf import PdfReader, PdfWriter

    page = PdfReader(path).pages[n - 1]
    w = PdfWriter()
    w.add_page(page)
    buf = io.BytesIO()
    w.write(buf)
    url = "data:application/pdf;base64," + base64.b64encode(buf.getvalue()).decode()
    return url, float(page.mediabox.width), float(page.mediabox.height)


# ------------------------------------------------------------------ into the draft


def label_key(text: str) -> str:
    """ "#101" → "101", "2.169" → "2.169", "1. 034" → "1.34" (an address keeps its universe, without zeros)."""
    t = re.split(r"[/,;]| - ", text.strip())[0].strip().lstrip("#").replace(" ", "")  # "6.301 / 6.305": its start
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,3})", t)
    if m:
        return f"{int(m.group(1))}.{int(m.group(2))}"
    return re.sub(r"[^0-9a-z]", "", t.lower())


def read(files: list[Path], client=None) -> Draft:
    """Every PDF of an import together (a patch in one file, its drawings in another)."""
    d = Draft()
    if not has_key():
        for p in files:
            d.note("missing", KEY_NOTE.format(name=p.name))
        return d
    if client is None:
        from openai import OpenAI

        client = OpenAI()
    text, drawings = [], []
    for p in files:
        for pg in pages(p):
            if pg["drawing"]:
                drawings.append((p, pg["page"]))
            else:
                text.append(f"--- {p.name}, page {pg['page']} ---\n{pg['text']}")
        d.note("ok", f"{p.name}: read with AI")
    if not text:
        d.note("missing", "No patch list in the PDFs: the fixtures can't be known from drawings alone")
        return d
    patch = _ask(
        client, [{"type": "input_text", "text": TEXT_PROMPT + "\n\n" + "\n\n".join(text)}], TEXT_SCHEMA, "patch"
    )
    items = fixtures(patch, d)
    by_key: dict[str, Item] = {}
    for it in items:
        for key in (it.label, f"{it.universe}.{it.address}" if it.address else ""):
            if key:
                by_key.setdefault(key, it)
    stage = patch.get("stage") or {}
    d.stage = {
        "width_m": stage.get("width_m") or stage.get("usable_width_m"),
        "depth_m": stage.get("depth_m"),
        "ceiling_m": stage.get("grid_height_m"),
    }
    sizes = ", ".join(f"{k.replace('_m', '').replace('_', ' ')} {v:g} m" for k, v in stage.items() if v)
    labels = sorted(by_key, key=lambda k: [int(n) if n.isdigit() else 0 for n in re.split(r"\D", k)])
    prompt = PLOT_PROMPT.format(
        sizes=f"The venue's rider gives: {sizes}. " if sizes else "",
        labels=f" The patch has these numbers and addresses, look for each: {', '.join(labels)}." if labels else "",
    )
    placed = 0
    for p, n in drawings:
        url, w, h = page_pdf(p, n)
        content = [
            {"type": "input_text", "text": prompt},
            {"type": "input_file", "filename": f"{p.stem}-page{n}.pdf", "file_data": url},
        ]
        plans = _ask(client, content, PLOT_SCHEMA, "plot").get("plans", [])
        if not plans:
            d.note("ok", f"{p.name} page {n}: no plan (a view or other drawing): not used for positions")
        for plan in plans:
            where = f"{p.name} page {n}" + (f" ({plan['title']})" if plan.get("title") else "")
            placed += place(plan, w, h, stage, by_key, d, where)
    if drawings and not placed:
        d.note("check", "The drawings placed no fixtures (no labels matched the patch): they are auto-mounted")
    d.items += items
    return d


def fixtures(patch: dict, d: Draft) -> list[Item]:
    """An item per fixture of the patch; a run of dimmer channels is a light per channel."""
    modes = {m["type"].lower(): m for m in patch.get("modes", [])}
    items, house = [], []
    for row in patch.get("fixtures", []):
        brand, kind = (row.get("manufacturer") or "").strip(), row["type"].strip()
        name = kind if not brand or kind.lower().startswith(brand.lower()) else f"{brand} {kind}"
        if row.get("house_only"):
            house.append(name)
            continue
        it = Item(name=name, label=label_key(row.get("number") or ""), where=row.get("where") or "", source="PDF")
        if row.get("address"):
            it.universe, it.address = row.get("universe") or 1, row["address"]
        m = modes.get(row["type"].lower())
        if m:
            it.mode, it.channels = m["mode"], m.get("channels") or 0
        last = row.get("last_address") or 0
        if it.address and last > it.address and row.get("per_channel"):
            for k in range(last - it.address + 1):
                items.append(Item(**{**it.__dict__, "address": it.address + k, "channels": 1, "label": ""}))
            continue
        if it.address and last > it.address:
            it.channels = it.channels or last - it.address + 1
        it.count = max(1, row.get("count") or 1)
        items.append(it)
    if house:
        d.note("ok", f"Left out as house lights: {', '.join(sorted(set(house)))}")
    return items


def place(plot: dict, w: float, h: float, stage: dict, by_key: dict[str, Item], d: Draft, where: str) -> int:
    """Positions for the patch's fixtures from one plan; returns how many were placed."""
    if plot.get("area") == "other" or not plot.get("symbols"):
        return 0
    aud = plot.get("audience", "bottom")

    def sl(x: float, y: float) -> float:  # page → points towards stage left (the performer's left)
        return {"bottom": x * w, "top": (1 - x) * w, "left": y * h, "right": (1 - y) * h}[aud]

    def out(x: float, y: float) -> float:  # page → points towards the audience
        return {"bottom": y * h, "top": (1 - y) * h, "left": (1 - x) * w, "right": x * w}[aud]

    width = stage.get("width_m") or stage.get("usable_width_m")
    scales, centre = [], None  # metres per point, from what the drawing gives: the median is taken
    ends, walls = (plot.get("stage_end_a"), plot.get("stage_end_b")), (plot.get("wall_a"), plot.get("wall_b"))
    for a, b in (ends, walls):
        if a is not None and b is not None and abs(a - b) > 0.05:
            centre = centre if centre is not None else (sl(a, a) + sl(b, b)) / 2
            if width:
                scales.append(width / abs(sl(b, b) - sl(a, a)))
    front, back = plot.get("stage_edge"), plot.get("stage_back")
    if stage.get("depth_m") and front is not None and back is not None and abs(front - back) > 0.03:
        scales.append(stage["depth_m"] / abs(out(front, front) - out(back, back)))
    if not scales or centre is None:
        d.note("check", f"{where}: no scale (the stage's width and its ends on the drawing): not used for positions")
        return 0
    scales.sort()
    scale = (
        scales[len(scales) // 2] if len(scales) % 2 else sum(scales[len(scales) // 2 - 1 : len(scales) // 2 + 1]) / 2
    )
    if len(scales) == 1 or max(scales) > 1.3 * min(scales):
        d.note(
            "check",
            f"{where}: its scale is uncertain (one size to go by, or sizes that don't agree): check the distances",
        )
    edge = plot.get("stage_edge")
    edge_pt = out(edge, edge) if edge is not None else None
    found = [s for s in plot.get("symbols", []) if label_key(s["label"]) in by_key]
    depths = sorted(out(s["x"], s["y"]) for s in found)
    if plot.get("area") == "hall" and depths and (edge_pt is None or depths[len(depths) // 5] < edge_pt):
        edge_pt = depths[0] - 1.5 / scale  # a hall plan: its fixtures are in front of the stage
        d.note("check", f"{where}: where the stage is isn't clear on this plan: its first row taken as 1.5 m out")
    elif edge_pt is None:
        edge_pt = 0.0
        d.note("check", f"{where}: the stage's front edge isn't drawn: taken as the top of the drawing")
    grid = stage.get("grid_height_m") or 6.0
    deck = stage.get("deck_height_m") or 0.0
    hall = (stage.get("hall_grid_height_m") or grid + deck) - deck

    def metres(x: float, y: float) -> tuple[float, float]:  # (to stage right of the centre, to the audience)
        return (centre - sl(x, y)) * scale, (out(x, y) - edge_pt) * scale

    placed, unknown = 0, 0
    for s in plot.get("symbols", []):
        it = by_key.get(label_key(s["label"]))
        if it is None:
            unknown += 1
            continue
        sx, sy = metres(s["x"], s["y"])
        z = 0.0 if s["floor"] else (hall if sy > 0.5 else grid) - 0.6
        it.pos, it.hanging = (round(sx, 3), round(sy, 3), round(z, 3)), not s["floor"]
        placed += 1
    if unknown:
        d.note("check", f"{where}: {unknown} symbols had a label that isn't in the patch")
    for t in plot.get("trusses", []):
        (ax, ay), (bx, by) = metres(t["x1"], t["y1"]), metres(t["x2"], t["y2"])
        n = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        if n > 1.0:
            z = (hall if (ay + by) / 2 > 0.5 else grid) - 0.2
            d.trusses.append(
                {
                    "name": t["label"] or "truss",
                    "s": round((ax + bx) / 2, 3),
                    "y": round((ay + by) / 2, 3),
                    "z": round(z, 3),
                    "dir": ((bx - ax) / n, (by - ay) / n),
                }
            )
    if placed:
        d.note("check", f"{where}: {placed} fixtures placed from the drawing (positions read by AI: check them)")
    return placed
