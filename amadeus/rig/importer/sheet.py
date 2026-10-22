"""Patch sheets: a CSV or Excel export of a desk's patch, or the venue's own list.

The header row is found by its words (fixture/type, mode, universe, address/patch, id, position, quantity,
x/y/z), in any column order and in English or Dutch. Addresses come as "141" with a universe column, or as
"1.141", "1/141", "1:141" or "U1 141"; a range "1.013 > 1.019" is a run of dimmer channels for conventional
lights, else the fixture's footprint. A row with a quantity is that many fixtures, addressed one after the other.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from amadeus.rig.importer.draft import Draft, Item

COLUMNS = {  # column → the header words that name it (lower case, compared without punctuation)
    "name": (
        "fixture type",
        "fixture",
        "type",
        "model",
        "device",
        "instrument",
        "instrument type",
        "armatuur",
        "fixture name",
        "profile",
    ),
    "manufacturer": ("manufacturer", "brand", "make", "fabrikant", "merk"),
    "mode": ("mode", "dmx mode", "personality", "modus"),
    "universe": ("universe", "univ", "uni", "dmx universe", "line"),
    "address": ("address", "addr", "dmx", "dmx address", "patch", "start", "start address", "adres"),
    "label": ("id", "fixture id", "fid", "no", "nr", "number", "unit", "unit number", "channel"),
    "where": ("position", "location", "truss", "pos", "description", "hang", "positie", "omschrijving", "layer"),
    "count": ("qty", "quantity", "count", "amount", "aantal", "pcs"),
    "channels": ("channels", "ch", "chans", "footprint", "kanalen", "dmx footprint"),
    "x": ("x", "x m", "pos x", "position x"),
    "y": ("y", "y m", "pos y", "position y"),
    "z": ("z", "z m", "pos z", "position z", "height", "hoogte"),
}
CONVENTIONAL = re.compile(r"dimmer|\bpar ?64\b|\bpc\b|fresnel|profile|source ?4|\bcyc|\bbalk|non ?dim", re.I)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(text).lower().replace("#", "id")).strip()


def header(row: list[str]) -> dict[str, int]:
    """Which column is which, from a header row; empty when this isn't one."""
    found = {}
    for i, cell in enumerate(row):
        k = _key(cell)
        for col, words in COLUMNS.items():
            if col not in found and k in words:
                found[col] = i
                break
    return found if "name" in found and len(found) >= 2 else {}


def patch(text: str) -> tuple[int, int, int]:
    """(universe, address, last address) from a patch cell; universe 0 when the cell has none."""
    text = text.strip()
    nums = re.findall(r"(?:u\s*)?(\d+)\s*[./: ]\s*(\d+)|(\d+)", text, re.I)
    pairs = [(int(a), int(b)) if a else (0, int(c)) for a, b, c in nums]
    if not pairs:
        return 0, 0, 0
    (u, a), (u2, b) = pairs[0], pairs[-1]
    if len(pairs) == 1 or (u2 and u2 != u):
        return u, a, a
    return u, a, b


def _number(text: str) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(text))
    return float(m.group(0).replace(",", ".")) if m else None


def rows_csv(data: bytes) -> list[list[list[str]]]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(csv.reader(io.StringIO(text), dialect))]


def rows_xlsx(data: bytes) -> list[list[list[str]]]:
    """Every sheet's rows, read straight from the workbook's XML (no Excel library needed)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        out = []
        for name in sheets:
            rows = []
            for r in ET.fromstring(z.read(name)).iter(f"{{{ns['m']}}}row"):
                row: list[str] = []
                for c in r.findall("m:c", ns):
                    col = 0
                    for ch in re.match(r"[A-Z]+", c.get("r", "A")).group(0):
                        col = col * 26 + ord(ch) - 64
                    v = c.find("m:v", ns)
                    if c.get("t") == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif c.get("t") == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                    else:
                        val = v.text if v is not None and v.text else ""
                    row += [""] * (col - 1 - len(row)) + [val]
                rows.append(row)
            out.append(rows)
    return out


def read(path: Path) -> Draft:
    d = Draft()
    data = path.read_bytes()
    tables = rows_xlsx(data) if path.suffix.lower() in (".xlsx", ".xlsm") else rows_csv(data)
    for rows in tables:
        cols: dict[str, int] = {}
        for n, row in enumerate(rows, 1):
            if not cols:
                cols = header(row)
                continue
            cell = {c: (row[i].strip() if i < len(row) else "") for c, i in cols.items()}
            if not cell["name"] or header(row):
                continue
            item = Item(name=f"{cell.get('manufacturer', '')} {cell['name']}".strip(), source=f"{path.name}: row {n}")
            item.label, item.mode, item.where = cell.get("label", ""), cell.get("mode", ""), cell.get("where", "")
            u, a, last = patch(cell.get("address", ""))
            if cell.get("universe"):
                u = int(_number(cell["universe"]) or 0) or u
            item.universe, item.address = (u or 1, a) if a else (0, 0)
            if cell.get("channels"):
                item.channels = int(_number(cell["channels"]) or 0)
            if last > a:  # a range: dimmers one per channel, else the fixture's footprint
                if CONVENTIONAL.search(item.name):
                    item.count, item.channels = last - a + 1, 1
                else:
                    item.channels = item.channels or last - a + 1
            if cell.get("count"):
                item.count = max(1, int(_number(cell["count"]) or 1))
            xyz = [_number(cell[k]) if cell.get(k) else None for k in ("x", "y", "z")]
            if None not in xyz:
                item.pos = (xyz[0], xyz[1], xyz[2])  # metres, stage right of the centre line / to the audience / up
            d.items.append(item)
    if not d.items:
        d.note(
            "missing",
            f"{path.name}: no patch table found (a header row naming at least the fixture type and "
            "its address or mode)",
        )
    return d
