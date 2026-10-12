"""Sets, rigs, and a set placed on a rig.

- A **set** is your lighting gear: the fixtures you own (model, DMX mode and address, calibration), where the
  DMX goes (a node or a USB interface), safety and the decision model. Most people have one or two.
  `config/sets/<name>.json`
- A **rig** is the structure at a venue: the stage's size, trusses and towers, the LED wall, the zones.
  `config/rigs/<name>.json`
- A rig remembers where each set's fixtures are mounted on it: `placements.<set>.<fixture id>`.

A show runs with one rig and one set (`config/active-rig`, `config/active-set`). The engine reads them as one
combined dict, the shape a set file always had (fixtures with their positions, the stage, trusses, zones…),
so nothing downstream needs to know they are two files. Saving that dict splits it back.

Fixtures a rig has no place for yet stand in a row on the floor at the front of the stage until they are
mounted (in the Mac app's rig editor, or with `amadeus rig --automount`).
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from amadeus import paths

SETS_DIR = paths.CONFIG / "sets"
RIGS_DIR = paths.CONFIG / "rigs"
ACTIVE_SET = paths.CONFIG / "active-set"
ACTIVE_RIG = paths.CONFIG / "active-rig"
LEGACY_RIG_FILE = paths.CONFIG / "rig.json"
EXAMPLES = paths.EXAMPLES
FIRST = "showcase"  # what a fresh checkout starts with

# what belongs to the rig (the venue) rather than the set (the gear)
RIG_KEYS = ("stage", "trusses", "zones", "screen")
# a fixture's fields that say where it is on a rig (everything else is the gear: model, patch, calibration)
PLACEMENT_KEYS = (
    "x", "y_m", "z_m", "mount", "rot_deg", "aim", "truss", "truss_pos_m", "truss_side", "mount_roll_deg",
    "reverse", "width", "group",
)  # fmt: skip
UNPLACED = "_unplaced"  # a fixture not mounted on this rig yet: the waiting spot it was given


def safe_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not n:
        raise ValueError("empty name")
    return n


# ---------------------------------------------------------------- files


class _Kind:
    """Sets or rigs: a folder of JSON files and the name of the active one."""

    def __init__(self, folder: Path, active_file: Path, noun: str):
        self.folder, self.active_file, self.noun = folder, active_file, noun

    def names(self) -> list[str]:
        _prepare()
        return sorted(p.stem for p in self.folder.glob("*.json"))

    def path(self, name: str | None = None) -> Path:
        _prepare()
        return self.folder / f"{name or self.active()}.json"

    def active(self) -> str:
        _prepare()
        name = self.active_file.read_text().strip() if self.active_file.exists() else ""
        available = self.names()
        if name not in available:
            name = FIRST if FIRST in available else (available[0] if available else FIRST)
        return name

    def switch(self, name: str):
        if name not in self.names():
            raise SystemExit(f"No {self.noun} '{name}'. {self.noun.capitalize()}s: {', '.join(self.names())}")
        self.active_file.write_text(name + "\n")

    def load(self, name: str | None = None) -> dict:
        p = self.path(name)
        return json.loads(p.read_text()) if p.exists() else {}

    def save(self, name: str, doc: dict) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        p = self.path(safe_name(name))
        p.write_text(json.dumps(doc, indent=2) + "\n")
        return p

    def delete(self, name: str):
        if len(self.names()) <= 1:
            raise SystemExit(f"Can't delete the only {self.noun}")
        self.path(name).unlink(missing_ok=True)
        if self.active() == name:
            self.switch(self.names()[0])

    def rename(self, old: str, new: str) -> str:
        new = safe_name(new)
        if new in self.names():
            raise SystemExit(f"A {self.noun} '{new}' already exists")
        self.path(old).rename(self.path(new))
        if self.active_file.exists() and self.active_file.read_text().strip() == old:
            self.active_file.write_text(new + "\n")
        return new


sets = _Kind(SETS_DIR, ACTIVE_SET, "set")
rigs = _Kind(RIGS_DIR, ACTIVE_RIG, "rig")


# ---------------------------------------------------------------- a set on a rig


def compose(set_doc: dict, rig_doc: dict, set_name: str) -> dict:
    """The set placed on the rig: one dict in the shape the engine reads."""
    out = {k: copy.deepcopy(v) for k, v in set_doc.items() if k not in RIG_KEYS}
    for k in RIG_KEYS:
        if k in rig_doc:
            out[k] = copy.deepcopy(rig_doc[k])
    places = rig_doc.get("placements", {}).get(set_name, {})
    fixtures = out.setdefault("fixtures", [])
    waiting = [f for f in fixtures if f["id"] not in places]
    for f in fixtures:
        for k in PLACEMENT_KEYS:
            f.pop(k, None)
        f.update(copy.deepcopy(places.get(f["id"], {})))
    for f, spot in zip(waiting, waiting_row(len(waiting))):
        f.update(spot)
        f[UNPLACED] = dict(spot)
    _onto_tower_faces(out)
    return out


def _onto_tower_faces(rig: dict):
    """Fixtures placed on a tower before towers had faces stood in front of it: they hang off its front face
    now (only on top of a tower does a fixture stand)."""
    from amadeus.rig import geometry, trusses

    towers = {t["id"]: t for t in rig.get("trusses", []) if t.get("vertical")}
    width = geometry.stage(rig)["width_m"]
    for f in rig.get("fixtures", []):
        t = towers.get(f.get("truss"))
        if t and f.get("truss_side") not in trusses.TOWER_SIDES:
            trusses.place(f, t, f.get("truss_pos_m", t["length_m"] - 0.3), width, "front")


def waiting_row(n: int) -> list[dict]:
    """Where fixtures stand before they are mounted: on the floor along the front edge of the stage."""
    return [{"x": round((k + 1) / (n + 1), 4), "y_m": -0.3, "z_m": 0.25, "mount": "floor"} for k in range(n)]


def split(merged: dict, set_name: str, rig_doc: dict) -> tuple[dict, dict]:
    """A combined dict back into the set and the rig (whose other sets' placements are kept)."""
    set_doc = {k: copy.deepcopy(v) for k, v in merged.items() if k not in RIG_KEYS and not k.startswith("_")}
    fixtures = merged.get("fixtures", [])
    set_doc["fixtures"] = [
        {k: copy.deepcopy(v) for k, v in f.items() if k not in PLACEMENT_KEYS and not k.startswith("_")}
        for f in fixtures
    ]
    rig = copy.deepcopy(rig_doc)
    for k in RIG_KEYS:
        if k in merged:
            rig[k] = copy.deepcopy(merged[k])
        else:
            rig.pop(k, None)
    places = {}
    for f in fixtures:
        spot = {key: copy.deepcopy(f[key]) for key in PLACEMENT_KEYS if key in f}
        if not spot or spot == f.get(UNPLACED):  # still waiting where it was put: not mounted
            continue
        places[f["id"]] = spot
    all_places = rig.setdefault("placements", {})
    if places:
        all_places[set_name] = places
    else:
        all_places.pop(set_name, None)
    if not all_places:
        rig.pop("placements")
    return set_doc, rig


@dataclass(frozen=True)
class Selection:
    """The show's rig and set. `file`: an old-style combined file instead (tests, `--rig FILE`)."""

    rig: str = ""
    set: str = ""
    file: Path | None = None

    @property
    def label(self) -> str:
        return self.file.stem if self.file else f"{self.set} on {self.rig}"

    @property
    def paths(self) -> list[Path]:
        return [self.file] if self.file else [sets.path(self.set), rigs.path(self.rig)]

    def load(self) -> dict:
        """The combined dict (raw: not yet expanded into elements; see rig.loader)."""
        if self.file:
            return json.loads(self.file.read_text())
        return compose(sets.load(self.set), rigs.load(self.rig), self.set)

    def save(self, merged: dict):
        if self.file:
            self.file.write_text(json.dumps(merged, indent=2) + "\n")
            return
        set_doc, rig_doc = split(merged, self.set, rigs.load(self.rig))
        sets.save(self.set, set_doc)
        rigs.save(self.rig, rig_doc)

    def mtime(self) -> float:
        return max((p.stat().st_mtime for p in self.paths if p.exists()), default=0.0)

    def placed(self) -> tuple[int, int]:
        """(mounted, all) fixtures of the set on the rig."""
        if self.file:
            n = len(self.load().get("fixtures", []))
            return n, n
        ids = {f["id"] for f in sets.load(self.set).get("fixtures", [])}
        places = rigs.load(self.rig).get("placements", {}).get(self.set, {})
        return len(ids & set(places)), len(ids)


def current(rig: str | None = None, set_name: str | None = None) -> Selection:
    """The given rig and set, else the active ones. A path to a .json file means an old combined file."""
    if rig and (rig.endswith(".json") or "/" in rig):
        return Selection(file=Path(rig))
    for kind, name in ((rigs, rig), (sets, set_name)):
        if name and safe_name(name) not in kind.names():
            raise SystemExit(f"No {kind.noun} '{name}'. {kind.noun.capitalize()}s: {', '.join(kind.names())}")
    return Selection(
        rig=safe_name(rig) if rig else rigs.active(), set=safe_name(set_name) if set_name else sets.active()
    )


# ---------------------------------------------------------------- summaries


def set_info() -> list[dict]:
    from amadeus.dmx import outputs

    out, active = [], sets.active()
    for n in sets.names():
        doc = sets.load(n)
        models: dict[str, int] = {}
        for f in doc.get("fixtures", []):
            models[f["fixture"]] = models.get(f["fixture"], 0) + 1
        out.append(
            {
                "name": n,
                "active": n == active,
                "fixtures": len(doc.get("fixtures", [])),
                "summary": ", ".join(f"{c}× {k.split('/')[-1]}" for k, c in models.items()),
                "artnet": doc.get("artnet", {}).get("ip"),
                "output": outputs.describe(doc),
                "description": doc.get("description", ""),
            }
        )
    return out


def rig_info() -> list[dict]:
    out, active = [], rigs.active()
    for n in rigs.names():
        doc = rigs.load(n)
        st = doc.get("stage", {})
        trusses = doc.get("trusses", [])
        out.append(
            {
                "name": n,
                "active": n == active,
                "description": doc.get("description", ""),
                "width_m": st.get("width_m"),
                "trusses": sum(1 for t in trusses if not t.get("vertical")),
                "towers": sum(1 for t in trusses if t.get("vertical")),
                "screen": bool(doc.get("screen")),
                "zones": len(doc.get("zones", [])),
                "sets": sorted(doc.get("placements", {})),
            }
        )
    return out


# ---------------------------------------------------------------- first run and old files


def _prepare():
    """Make sure there is something to work with: migrate old files, or start from the examples."""
    if getattr(_prepare, "done", False):
        return
    _prepare.done = True
    if not SETS_DIR.exists() and LEGACY_RIG_FILE.exists():  # the very first format: one config/rig.json
        SETS_DIR.mkdir(parents=True)
        shutil.move(str(LEGACY_RIG_FILE), SETS_DIR / "home.json")
        ACTIVE_SET.write_text("home\n")
    for p in sorted(SETS_DIR.glob("*.json")):
        migrate_set_file(p)
    for kind, folder in ((sets, "sets"), (rigs, "rigs")):
        if not any(kind.folder.glob("*.json")) and (EXAMPLES / folder).exists():
            kind.folder.mkdir(parents=True, exist_ok=True)
            for example in (EXAMPLES / folder).glob("*.json"):
                if not (kind.folder / example.name).exists():
                    shutil.copy(example, kind.folder / example.name)
            if not kind.active_file.exists() and (kind.folder / f"{FIRST}.json").exists():
                kind.active_file.write_text(FIRST + "\n")
    if not ACTIVE_RIG.exists() and ACTIVE_SET.exists():  # migrated: the rig that came out of the active set
        name = ACTIVE_SET.read_text().strip()
        if (RIGS_DIR / f"{name}.json").exists():
            ACTIVE_RIG.write_text(name + "\n")


def is_combined(doc: dict) -> bool:
    """An old set file: the gear and the venue in one (stage, trusses, positions…)."""
    return any(k in doc for k in RIG_KEYS) or any(k in f for f in doc.get("fixtures", []) for k in PLACEMENT_KEYS)


def migrate_set_file(p: Path) -> bool:
    """Split an old combined set file into a set and a rig of the same name (the rig keeps where the set's
    fixtures were). An existing rig of that name gets the placements added."""
    try:
        doc = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not is_combined(doc):
        return False
    rig_path = RIGS_DIR / p.name
    rig_doc = json.loads(rig_path.read_text()) if rig_path.exists() else {"description": doc.get("description", "")}
    for f in doc.get("fixtures", []):
        f.pop(UNPLACED, None)
    set_doc, rig_doc = split(doc, p.stem, rig_doc)
    RIGS_DIR.mkdir(parents=True, exist_ok=True)
    rig_path.write_text(json.dumps(rig_doc, indent=2) + "\n")
    p.write_text(json.dumps(set_doc, indent=2) + "\n")
    print(f"  ⇢ set '{p.stem}' split into the set (fixtures, patch) and the rig '{p.stem}' (stage, trusses, positions)")
    return True
