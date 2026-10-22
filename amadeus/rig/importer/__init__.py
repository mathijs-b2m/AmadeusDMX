"""Build a set and a rig from a venue's documents: an MVR scene, patch sheets (CSV, Excel), PDFs.

`build(files, name)` reads every file into one draft (`draft.Item` per fixture), finds each type in the library
(`resolve`), hangs what has a position (`layout`), auto-mounts the rest, and checks the result. It returns the
set, the rig and a report: what was assumed, what was guessed and should be checked, what is missing. Nothing
is saved until `save`. MVR files and patch sheets need no AI and no account; PDFs (patch lists, riders, light
plots) are read with AI and need the user's own OpenAI API key (`pdf`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry, store
from amadeus.rig.automount import automount
from amadeus.rig.importer import layout, mvr, pdf, resolve, sheet
from amadeus.rig.importer.draft import Draft, Note

READERS = {
    ".mvr": mvr.read,
    ".csv": sheet.read,
    ".tsv": sheet.read,
    ".txt": sheet.read,
    ".xlsx": sheet.read,
    ".xlsm": sheet.read,
}


@dataclass
class Result:
    set_doc: dict
    rig_doc: dict
    notes: list[Note] = field(default_factory=list)

    def report(self) -> list[dict]:
        return [{"level": n.level, "text": n.text, "ids": n.ids} for n in self.notes]


def read(files: list[Path], client=None) -> Draft:
    """Every file into one draft; the PDFs together (a patch in one, its drawings in another)."""
    draft = Draft()
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    if pdfs:
        try:
            draft.merge(pdf.read(pdfs, client))
        except (OSError, ValueError, KeyError) as e:
            draft.note("missing", f"{', '.join(p.name for p in pdfs)}: couldn't be read ({e})")
    for p in files:
        if p in pdfs:
            continue
        reader = READERS.get(p.suffix.lower())
        if reader is None:
            draft.note("missing", f"{p.name}: can't read this kind of file (MVR, PDF, CSV and Excel can be read)")
            continue
        try:
            draft.merge(reader(p))
        except (OSError, ValueError, KeyError) as e:
            draft.note("missing", f"{p.name}: couldn't be read ({e})")
    return draft


def build(files: list[Path], name: str, client=None) -> Result:
    draft = read(files, client)
    if not draft.items:
        return Result({"fixtures": []}, {"trusses": [], "placements": {}}, draft.notes)
    choices = resolve.resolve(draft)
    set_doc, rig_doc = layout.build(draft, choices, name)
    by_id = {f["id"]: i for i, f in enumerate(set_doc["fixtures"])}
    for c in {id(c): c for c in choices.values()}.values():
        who = [f["id"] for f in set_doc["fixtures"] if choices[by_id[f["id"]]] is c]
        model = fxlib.get(c.key)
        text = f"{len(who)} × {model['manufacturer']} {model['model']}, mode {c.mode} ({c.footprint} ch)"
        draft.note("ok" if c.sure else "check", text + (f": {c.why}" if c.why else ""), who)
    if any(it.pos for it in draft.items) and not draft.stage.get("width_m"):
        st = rig_doc["stage"]
        draft.note(
            "check",
            f"Stage {st['width_m']:g} m wide and the room {st['room_depth_m']:g} m deep, judged from "
            "where the fixtures hang (the documents don't give it): set the real size in the rig editor",
        )
    merged = store.compose(set_doc, rig_doc, name)
    waiting = [f["id"] for f in merged["fixtures"] if f.get("_unplaced")]
    if waiting:
        had_trusses = bool(rig_doc["trusses"])
        places = automount(merged, waiting)
        rig_doc["trusses"] = merged["trusses"]
        rig_doc["placements"][name].update(places)
        where = "on the trusses found" if had_trusses else "on a standard structure for the stage"
        draft.note(
            "check",
            f"{len(waiting)} fixtures had no position in the documents: auto-mounted {where}; "
            "move them where they really hang",
            waiting,
        )
    if not any(it.address for it in draft.items):
        draft.note("missing", "No DMX patch in the documents: give the fixtures their addresses on the Set page")
    draft.notes += checks(store.compose(set_doc, rig_doc, name))
    return Result(set_doc, rig_doc, draft.notes)


def checks(merged: dict) -> list[Note]:
    """What a person should look at in the result: patch problems, fixtures left over, fixed lights that point
    out of the room (at a side wall, or up at the ceiling from under a truss)."""
    out = [Note("missing", p) for p in fxlib.validate(merged)]
    out += [Note("check", p) for p in fxlib.overlaps(merged)]
    left = [f["id"] for f in merged["fixtures"] if f.get("_unplaced")]
    if left:
        out.append(Note("missing", f"{len(left)} fixtures have no place on the rig", left))
    W = merged["stage"]["width_m"]
    wall, up = [], []
    for f in merged["fixtures"]:
        kind = fxlib.get(f["fixture"])["kind"]
        if kind in ("moving_head", "moving_bar", "smoke", "laser") or f.get("_unplaced"):
            continue
        d = geometry.static_dir(f, kind)
        x = f.get("x", 0.5) * W
        if abs(d[0]) > 0.5 and (x - W / 2) * d[0] > 0 and abs(x - W / 2) > W / 4:
            wall.append(f["id"])
        if f.get("mount") == "hang" and math.degrees(math.asin(max(-1.0, min(1.0, d[2])))) > 20:
            up.append(f["id"])
    if wall:
        out.append(Note("check", f"{len(wall)} fixed lights near the sides point out at the wall", wall))
    if up:
        out.append(Note("check", f"{len(up)} hanging fixed lights point up at the ceiling", up))
    return out


def save(result: Result, name: str) -> None:
    """Write the set and the rig as `name` (both)."""
    store.sets.save(name, result.set_doc)
    store.rigs.save(name, result.rig_doc)
