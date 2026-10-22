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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from amadeus import paths
from amadeus.rig.importer.draft import Draft, Item

MODEL = "gpt-6-luna"
CACHE = paths.CACHE / "import"
KEY_NOTE = (
    "{name}: PDFs are read with AI, which needs your own OpenAI API key (Settings › OpenAI in the app, or "
    "OPENAI_API_KEY in .env); nothing was sent. MVR files and patch sheets (CSV, Excel) import without one"
)
DRAWING_WORDS = 40  # a page with fewer words than this is a drawing (not read as text)
PARALLEL = 4  # pages read with AI at the same time
SCALE = re.compile(r"(?:scale|schaal|ma(?:ß|ss)stab|échelle)\s*:?\s*1\s*:\s*(\d{2,4})\b", re.I)
HALL = re.compile(r"hall|zaal|audience|publiek|foh|f\.o\.h|balcon|dance ?floor|house", re.I)  # where it hangs


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
                    "number": {
                        "type": "string",
                        "description": "its fixture number or ID as printed (a #, ID, Fix, Unit or No column: #101 → "
                        "101); drawings label fixtures by it, so copy it for every row that has one; '' only when none",
                    },
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
    "work lights, interior lights, network gear and dimmer racks or packs themselves (the boxes, not the lights on "
    "them) as house_only "
    "(a moving light, strobe or blinder never is). Give the DMX modes the notes name (e.g. "
    "'AYRTON DIABLO S EXTENDED 56 CHANNEL' → type Diablo S, mode Extended, 56 channels). From the rider: the "
    "stage's total and usable width, its depth, the height from the stage floor to the grid, the stage's own "
    "height above the hall floor, and the hall's grid height above the hall floor. Use null for what isn't "
    "there; never invent rows."
)

PLAN = _obj(
    {
        "title": {"type": "string"},
        "purpose": {"type": "string", "enum": ["lighting", "building"]},
        "box": _obj({"x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"},
                     "y1": {"type": "number"}}),
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
                    "size": _nullable("number"),
                    "floor": {"type": "boolean", "description": "standing on the floor rather than hanging"},
                }
            ),
        },
    }
)  # fmt: skip
PLOT_SCHEMA = _obj({"plans": {"type": "array", "items": PLAN}})

PLOT_PROMPT = (
    "One page of a music venue's lighting drawings. List each plan on it (a drawing seen from above; a page can "
    "hold several, e.g. the stage roof and the stage truss); 3D views and photos are not plans: leave them out. "
    "{sizes}All positions are fractions of the whole page: x from its left edge, y from its top (0..1). Per "
    "plan: its title; its purpose: the lighting rig (fixtures on trusses, pipes or the floor, as hung for a "
    "show) or the building (the roof structure, rigging points, motors, work lights in the roof); the box it "
    "takes on the page (its drawing, without the title); whether it shows the stage, the hall (audience area) "
    "or both, and on which side of the plan the audience is (the side away from the stage, towards the front of "
    "house). The stage's front edge and its back edge (y, or x when the audience is left or right; on a hall "
    "plan without the stage: the hall's end wall at the stage as the front edge); the whole stage platform's "
    "two outer ends along the front edge (x, or y), not a riser on it; the two side walls of the audience "
    "floor where it meets the stage: the edges of the floor people stand on, inside any balconies or stairs, "
    "not the area the fixtures cover. Null for what isn't drawn. Then every lighting fixture symbol, moving "
    "heads, strobes, blinders and conventional lights alike: the label printed at it (a number such as 101 or "
    "#101, or a DMX address such as 2.169 or 1.34; dense trusses print them in a row above or below the "
    "symbols), the centre of the symbol, its size (the longer side of the symbol itself, as a fraction of the "
    "page's width; null when you can't tell), and whether it stands on the floor.{labels}"
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


def read(files: list[Path], client=None, progress=None) -> Draft:
    """Every PDF of an import together (a patch in one file, its drawings in another). `progress(text)` hears
    what is being read."""
    say = progress or (lambda text: None)
    d = Draft()
    if not has_key():
        for p in files:
            d.note("missing", KEY_NOTE.format(name=p.name))
        return d
    if client is None:
        from openai import OpenAI

        client = OpenAI()
    text, drawings = [], []
    printed: dict[tuple, float] = {}  # a plan's own "scale 1:100", read from its text (not by AI)
    for p in files:  # every page with text is read as text, and every page as a drawing (a CAD plan has text too)
        for pg in pages(p):
            drawings.append((p, pg["page"]))
            m = SCALE.search(pg["text"])
            if m:
                printed[(p, pg["page"])] = float(m.group(1))
            if not pg["drawing"]:
                text.append(f"--- {p.name}, page {pg['page']} ---\n{pg['text']}")
        d.note("ok", f"{p.name}: read with AI")
    if not text:
        d.note("missing", "No patch list in the PDFs: the fixtures can't be known from drawings alone")
        return d
    say("Reading the patch list and the rider with AI…")
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
        "ceiling_m": stage["grid_height_m"] + (stage.get("deck_height_m") or 0) if stage.get("grid_height_m") else None,
        "deck_m": stage.get("deck_height_m"),
    }
    sizes = ", ".join(f"{k.replace('_m', '').replace('_', ' ')} {v:g} m" for k, v in stage.items() if v)
    labels = sorted(by_key, key=lambda k: [int(n) if n.isdigit() else 0 for n in re.split(r"\D", k)])
    prompt = PLOT_PROMPT.format(
        sizes=f"The venue's rider gives: {sizes}. " if sizes else "",
        labels=f" The patch has these numbers and addresses, look for each: {', '.join(labels)}." if labels else "",
    )
    placed, done = 0, 0
    say(f"Looking for plans on {len(drawings)} pages with AI…")

    def ask_page(pn):  # a few at a time: each page is its own request
        nonlocal done
        url, w, h = page_pdf(*pn)
        content = [
            {"type": "input_text", "text": prompt},
            {"type": "input_file", "filename": f"{pn[0].stem}-page{pn[1]}.pdf", "file_data": url},
        ]
        plans = _ask(client, content, PLOT_SCHEMA, "plot").get("plans", [])
        done += 1
        say(f"Looking for plans with AI: {done} of {len(drawings)} pages read…")
        return url, w, h, plans

    with ThreadPoolExecutor(PARALLEL) as pool:
        answers = list(pool.map(ask_page, drawings))
    for (p, n), (url, w, h, plans) in zip(drawings, answers):
        if not plans:
            continue  # text, a 3D view or a photo: no plan on it
        page = base64.b64decode(url.split(",", 1)[1])
        for plan in plans:
            where = f"{p.name} page {n}" + (f" ({plan['title']})" if plan.get("title") else "")
            under = {"title": plan.get("title") or f"{p.stem} page {n}", "source": where, "pdf": page, "w": w, "h": h}
            got = place({**plan, "printed_scale": printed.get((p, n))}, w, h, stage, by_key, d, where, under,
                        len(d.underlays))  # fmt: skip
            if got:
                d.underlays.append(under)
            placed += got
    if drawings and not placed:
        d.note("check", "The drawings placed no fixtures (no labels matched the patch): they are auto-mounted")
    d.items += items
    return d


def fixtures(patch: dict, d: Draft) -> list[Item]:
    """An item per fixture of the patch; a run of dimmer channels is a light per channel."""
    modes = {m["type"].lower(): m for m in patch.get("modes", [])}
    items, house = [], []
    for row in patch.get("fixtures", []):
        brand = (row.get("manufacturer") or "").strip()
        kind = re.sub(r"\s+#?\d{1,3}$", "", row["type"].strip()) or row["type"].strip()  # "110V 7": unit 7 of 110V
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
        span = last - it.address + 1 if it.address and last > it.address else 0
        count = max(1, row.get("count") or 1)
        if span and it.channels and count > 1 and count * it.channels > span:
            count = max(1, span // it.channels)  # "1–152" read as 152 units: those are channels, of 3-channel units
        elif span and not it.channels:  # the range is the units side by side, else (a hazer "501 > 503") one's own
            it.channels = span // count if count > 1 and span % count == 0 and span // count >= 2 else span
        it.count = count
        items.append(it)
    if house:
        d.note("ok", f"Left out as house lights: {', '.join(sorted(set(house)))}")
    return items


def footprint_m(it: Item) -> float | None:
    """How big a fixture is seen from above (metres, its longer side), when the library knows the model."""
    from amadeus.library import catalog
    from amadeus.library import fixtures as fxlib
    from amadeus.rig.importer import resolve

    c = resolve.match(it.name, it.channels, it.mode)
    if c is None:
        return None
    try:
        d = catalog.definition(c.key) if c.key.startswith(catalog.REMOTE) else fxlib.get(c.key)
    except (OSError, KeyError, ValueError):
        return None
    size = d.get("physical", {}).get("size_mm")
    if not size or len(size) < 3 or d.get("kind") not in ("moving_head", "moving_bar"):
        return None  # only moving heads: drawn as their own footprint (conventionals get symbols of any size)
    return max(size[0], size[2]) / 1000


def symbol_scale(plot: dict, w: float, by_key: dict[str, Item]) -> float | None:
    """Metres per point from the fixture symbols: plans are drawn to scale, so a moving head's symbol is as big
    as the head. The median over the plan's heads (at least three), else None."""
    got = []
    for s in plot.get("symbols", []):
        it = by_key.get(label_key(s["label"]))
        size = s.get("size")
        if it is None or not size or size <= 0.003:
            continue
        m = footprint_m(it)
        if m:
            got.append(m / (size * w))
    if len(got) < 3:
        return None
    got.sort()
    return got[len(got) // 2]


def place(
    plot: dict,
    w: float,
    h: float,
    stage: dict,
    by_key: dict[str, Item],
    d: Draft,
    where: str,
    under: dict | None = None,
    index: int = 0,
) -> int:
    """Positions for the patch's fixtures from one plan; returns how many were placed. `under` gets the plan's
    two reference points (the stage's front edge at its ends) for the drawing under the rig (underlay.py), and
    each placed item its spot on the page."""
    if plot.get("purpose") == "building":
        d.note("ok", f"{where}: a plan of the building (roof, rigging), not of the lighting: not used for positions")
        return 0
    if plot.get("area") == "other" or not plot.get("symbols"):
        return 0
    aud = plot.get("audience", "bottom")

    def sl(x: float, y: float) -> float:  # page → points towards stage left (the performer's left)
        return {"bottom": x * w, "top": (1 - x) * w, "left": y * h, "right": (1 - y) * h}[aud]

    def out(x: float, y: float) -> float:  # page → points towards the audience
        return {"bottom": y * h, "top": (1 - y) * h, "left": (1 - x) * w, "right": x * w}[aud]

    width = stage.get("width_m") or stage.get("usable_width_m")
    found = [s for s in plot.get("symbols", []) if label_key(s["label"]) in by_key]
    # a plan of the hall: the patch hangs most of its fixtures there. What it calls the stage on it is a guess
    # (often the first rows of the hall): only its side walls count, and its first row hangs over the crowd
    hall_plan = sum(1 for s in found if HALL.search(by_key[label_key(s["label"])].where)) > 0.6 * max(1, len(found))
    refs, centre = [], None  # metres per point, from what the plan shows
    ends, walls = (plot.get("stage_end_a"), plot.get("stage_end_b")), (plot.get("wall_a"), plot.get("wall_b"))
    for a, b in (walls,) if hall_plan else (ends, walls):
        if a is not None and b is not None and abs(a - b) > 0.05:
            centre = centre if centre is not None else (sl(a, a) + sl(b, b)) / 2
            if width:
                refs.append(width / abs(sl(b, b) - sl(a, a)))
    front, back = plot.get("stage_edge"), plot.get("stage_back")
    if not hall_plan and stage.get("depth_m") and front is not None and back is not None and abs(front - back) > 0.03:
        refs.append(stage["depth_m"] / abs(out(front, front) - out(back, back)))
    by_symbols = symbol_scale(plot, w, by_key)
    agree = len(refs) >= 2 and max(refs) <= 1.15 * min(refs)
    paper = plot["printed_scale"] * 0.0254 / 72 if plot.get("printed_scale") else None  # 1:N on a page printed so
    others = refs + ([by_symbols] if by_symbols else [])
    if paper and any(abs(x / paper - 1) <= 0.2 for x in others):  # the printed scale, when something agrees
        scales, agree = [paper], True
    elif agree:  # two sizes the plan shows agree: they win (the AI judges symbol sizes less well)
        scales = refs
    elif by_symbols:  # else the fixtures drawn on it: plans are drawn to scale
        scales = [x for x in refs if abs(x / by_symbols - 1) <= 0.25] + [by_symbols]
        if len(scales) == 1:
            d.note("check", f"{where}: scaled by the size of its fixture symbols: check the distances")
    else:
        scales = refs
    if centre is None and scales:  # nothing drawn across the stage: the rig's middle is the fixtures' middle
        across = [sl(s["x"], s["y"]) for s in found]
        centre = (min(across) + max(across)) / 2 if across else None
    if not scales or centre is None:
        d.note("check", f"{where}: no scale (the stage's width and its ends on the drawing): not used for positions")
        return 0
    scales.sort()
    mid_k = len(scales) // 2
    scale = scales[mid_k] if len(scales) % 2 else (scales[mid_k - 1] + scales[mid_k]) / 2
    if not agree:
        d.note("check", f"{where}: its scale is uncertain (one size to go by, or sizes that don't agree): check the "
               "distances")  # fmt: skip
    edge = None if hall_plan else plot.get("stage_edge")
    edge_pt = out(edge, edge) if edge is not None else None
    depths = sorted(out(s["x"], s["y"]) for s in found)
    if (hall_plan or plot.get("area") == "hall") and depths and (edge_pt is None or depths[len(depths) // 5] < edge_pt):
        edge_pt = depths[0] - 1.5 / scale  # a hall plan: its fixtures are in front of the stage
        d.note("check", f"{where}: where the stage is isn't clear on this plan: its first row taken as 1.5 m out")
    elif edge_pt is None:
        edge_pt = 0.0
        d.note("check", f"{where}: the stage's front edge isn't drawn: taken as the top of the drawing")
    deck = stage.get("deck_height_m") or 0.0  # heights count from the hall floor; the stage stands this high
    grid = deck + (stage.get("grid_height_m") or 6.0)  # the stage's grid, above the stage
    hall = stage.get("hall_grid_height_m") or grid

    def metres(x: float, y: float) -> tuple[float, float]:  # (to stage right of the centre, to the audience)
        return (centre - sl(x, y)) * scale, (out(x, y) - edge_pt) * scale

    placed, unknown = 0, 0
    for s in plot.get("symbols", []):
        it = by_key.get(label_key(s["label"]))
        if it is None:
            unknown += 1
            continue
        sx, sy = metres(s["x"], s["y"])
        z = (deck if sy <= 0.5 else 0.0) if s["floor"] else (hall if sy > 0.5 else grid) - 0.6
        it.pos, it.hanging = (round(sx, 3), round(sy, 3), round(z, 3)), not s["floor"]
        it.page = (index, s["x"], s["y"])
        placed += 1
    if unknown:
        d.note("check", f"{where}: {unknown} symbols had a label that isn't in the patch")
    if placed and under is not None:

        def page_at(s_m: float, y_m: float) -> list[float]:  # rig (to stage right of the centre, out) → page
            a, o = centre - s_m / scale, edge_pt + y_m / scale
            x, y = {"bottom": (a / w, o / h), "top": (1 - a / w, 1 - o / h),
                    "left": (1 - o / w, a / h), "right": (o / w, 1 - a / h)}[aud]  # fmt: skip
            return [round(x, 5), round(y, 5)]

        W = float(width)
        under.update(a=page_at(-W / 2, 0.0), b=page_at(W / 2, 0.0), a_m=[0.0, 0.0], b_m=[W, 0.0])
        box = plot.get("box") or {}
        if all(isinstance(box.get(k), (int, float)) for k in ("x0", "y0", "x1", "y1")):
            x0, x1 = sorted((box["x0"], box["x1"]))
            y0, y1 = sorted((box["y0"], box["y1"]))
            if x1 - x0 > 0.05 and y1 - y0 > 0.05:
                under["crop"] = [round(max(0.0, x0), 4), round(max(0.0, y0), 4), round(min(1.0, x1), 4),
                                 round(min(1.0, y1), 4)]  # fmt: skip
    if placed:
        d.note("check", f"{where}: {placed} fixtures placed from the drawing (positions read by AI: check them; "
               "line the drawing up in the rig editor if they are off)")  # fmt: skip
    return placed
