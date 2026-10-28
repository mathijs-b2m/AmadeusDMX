"""`amadeus mcp`: your own AI assistant (Claude Desktop, ChatGPT, Claude Code, Codex…) works on your sets and rigs.

A Model Context Protocol server on stdin/stdout: one JSON-RPC message per line. The tools do what the setup pages
and the apps do, through the same handlers (amadeus/web), so whatever an assistant saves is checked the same way:
a set with addresses out of range is refused, overlapping channels come back as warnings. Before every change the
sets and rigs are copied aside (.cache/assistant-undo), and `undo_last_change` puts the last copy back.

What it can't do on purpose: delete or rename sets and rigs, light fixtures, or touch a running show. A show that
is running keeps the set it started with; changes are there the next time it starts.

The guide the assistant gets (`instructions`, and the `read_guide` tool) is guide.md next to this file.
"""

from __future__ import annotations

import contextlib
import copy
import json
import shutil
import sys
import time
from pathlib import Path

from amadeus import paths

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")  # the newest first
GUIDE = Path(__file__).with_name("guide.md")
UNDO_DIR = paths.CACHE / "assistant-undo"
KEEP_UNDO = 30


class _Req:
    """What a web route handler gets (amadeus/web/server.py Handler), for a call that doesn't come over HTTP."""

    fixed = None
    client = "assistant"
    command = "POST"

    def __init__(self, body: dict | None = None, query: dict | None = None, show=None):
        self._body, self.query, self._show = body or {}, query or {}, show

    def body(self):
        return copy.deepcopy(self._body)

    @property
    def show(self):
        from amadeus.rig import store

        return self._show or store.current()


def _show(a: dict):
    """The set on the rig a call names (`set`, `rig`), else the active ones."""
    from amadeus.rig import store

    return store.current(a.get("rig") or None, a.get("set") or None)


def _ok(result):
    """A handler's result: (obj, status) on an error, or the obj."""
    obj, status = result if isinstance(result, tuple) else (result, 200)
    if status >= 400:
        raise ValueError(obj.get("error", obj) if isinstance(obj, dict) else obj)
    return obj


# ---------------------------------------------------------------- undo


@contextlib.contextmanager
def _change(what: str):
    """Around a change: the sets and rigs as they were before it, kept for undo_last_change (the last KEEP_UNDO).
    A change that fails (or saves nothing: `kept.discard()`) leaves no copy."""
    dest = _keep_copy(what)
    try:
        yield _Kept(dest)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise


class _Kept:
    def __init__(self, path: Path):
        self.path = path

    def discard(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def made_fixtures(self, before: set[Path]):
        """Fixture files the change made (`before`: _fixture_files() then): undo takes them away again."""
        new = sorted(str(p) for p in _fixture_files() - before)
        (self.path / "fixtures.json").write_text(json.dumps(new), encoding="utf-8")
        return new


def _fixture_files() -> set[Path]:
    """Your fixture definitions (where fixtures.save writes)."""
    from amadeus.library import fixtures as fxlib

    folder = fxlib.USER_DIR or fxlib.LIB_DIR
    return set(folder.glob("*/*.json"))


def _keep_copy(what: str) -> Path:
    from amadeus.rig import store

    store.sets.names()  # (a first run makes the folders from the examples first)
    dest = UNDO_DIR / f"{time.time_ns():020d}"  # in order, however quickly changes follow
    dest.mkdir(parents=True)
    for src in (store.SETS_DIR, store.RIGS_DIR):
        if src.exists():
            shutil.copytree(src, dest / src.name)
    for f in (store.ACTIVE_SET, store.ACTIVE_RIG):
        if f.exists():
            shutil.copy(f, dest / f.name)
    (dest / "what.txt").write_text(what + "\n", encoding="utf-8")
    for old in sorted(p for p in UNDO_DIR.iterdir() if p.is_dir())[:-KEEP_UNDO]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def undo_last_change(a: dict) -> dict:
    """Put the sets and rigs back as they were before the assistant's last change."""
    from amadeus.rig import store

    copies = sorted(p for p in UNDO_DIR.iterdir() if p.is_dir()) if UNDO_DIR.exists() else []
    if not copies:
        raise ValueError("Nothing to undo: the assistant hasn't changed anything yet.")
    last = copies[-1]
    for dst in (store.SETS_DIR, store.RIGS_DIR):  # one that wasn't there before wasn't copied: it goes
        shutil.rmtree(dst, ignore_errors=True)
        if (last / dst.name).exists():
            shutil.copytree(last / dst.name, dst)
    for f in (store.ACTIVE_SET, store.ACTIVE_RIG):
        if (last / f.name).exists():
            shutil.copy(last / f.name, f)
        else:
            f.unlink(missing_ok=True)
    if (last / "fixtures.json").exists():  # fixtures it made
        from amadeus.library import fixtures as fxlib

        for f in json.loads((last / "fixtures.json").read_text(encoding="utf-8")):
            Path(f).unlink(missing_ok=True)
        fxlib.library.cache_clear()
    what = (last / "what.txt").read_text(encoding="utf-8").strip() if (last / "what.txt").exists() else ""
    shutil.rmtree(last)
    return {"undone": what, "more_to_undo": len(copies) - 1}


# ---------------------------------------------------------------- tools


def read_guide(a: dict) -> dict:
    return {"guide": GUIDE.read_text(encoding="utf-8")}


def list_sets_and_rigs(a: dict) -> dict:
    from amadeus.web import rig

    return rig.list_sets(_Req())


def get_show(a: dict) -> dict:
    show = _show(a)
    return {"set": show.set, "rig": show.rig, "show": show.load()}


def save_show(a: dict) -> dict:
    from amadeus.web import rig

    show = _show(a)
    doc = a["show"]
    if not isinstance(doc, dict) or not isinstance(doc.get("fixtures"), list):
        raise ValueError("show: the combined dict get_show returns (with its fixtures list)")
    with _change(f"save_show ({show.label})") as kept:
        result = _ok(rig.save_rig(_Req(doc, show=show)))
        if not result["saved"]:
            kept.discard()
    return {"set": show.set, "rig": show.rig, **result}


def create_set(a: dict) -> dict:
    from amadeus.rig import manage, store

    with _change(f"create_set {a['name']}"):
        name = manage.new_set(a["name"], copy_of=a.get("copy_of") or None)
        if a.get("make_active", True):
            store.sets.switch(name)
    return {"created": name, "active": store.sets.active()}


def create_rig(a: dict) -> dict:
    from amadeus.rig import manage, store

    with _change(f"create_rig {a['name']}"):
        name = manage.new_rig(a["name"], a.get("template", "booth"), float(a.get("width_m", 8)),
                              float(a.get("truss_height_m", 4.5)), float(a.get("room_depth_m", 15)),
                              bool(a.get("screen")), copy_of=a.get("copy_of") or None)  # fmt: skip
        if a.get("make_active", True):
            store.rigs.switch(name)
    return {"created": name, "active": store.rigs.active()}


def place_set_on_rig(a: dict) -> dict:
    from amadeus.rig import manage, store

    set_name, rig_name = store.safe_name(a["set"]), store.safe_name(a["rig"])
    show = store.current(rig_name, set_name)
    with _change(f"place_set_on_rig {set_name} on {rig_name}"):
        doc = store.rigs.load(rig_name)
        doc.setdefault("placements", {}).setdefault(set_name, {})
        store.rigs.save(rig_name, doc)
        places = manage.mount(show) if a.get("automount", True) else {}
    placed, total = show.placed()
    return {"set": set_name, "rig": rig_name, "mounted_now": sorted(places), "mounted": placed, "fixtures": total}


def make_active(a: dict) -> dict:
    from amadeus.rig import store

    if not a.get("set") and not a.get("rig"):
        raise ValueError("Name a set, a rig or both.")
    with _change(f"make_active {a.get('set') or ''} {a.get('rig') or ''}".strip()):
        if a.get("set"):
            store.sets.switch(store.safe_name(a["set"]))
        if a.get("rig"):
            store.rigs.switch(store.safe_name(a["rig"]))
    return {"active": {"set": store.sets.active(), "rig": store.rigs.active()}}


def search_fixtures(a: dict) -> dict:
    from amadeus.library import catalog

    return {"results": catalog.search(a["query"], int(a.get("limit", 15)))}


def fixture_details(a: dict) -> dict:
    from amadeus.library import catalog

    return catalog.details(a["key"])


def add_fixtures(a: dict) -> dict:
    """Fixtures of one model added to a set (and mounted on the rig): at the given addresses, else free ones."""
    from amadeus.library import catalog
    from amadeus.library import fixtures as fxlib
    from amadeus.rig import manage, store

    show = _show(a)
    key, universe = a["key"], int(a.get("universe", 1))
    info = catalog.details(key)
    mode = a.get("mode") or info["default_mode"]
    if mode not in info["modes"]:
        raise ValueError(f"{key} has no mode '{mode}'. Modes: {', '.join(info['modes'])}")
    merged = show.load()
    addresses = [int(x) for x in a.get("addresses") or []]
    if not addresses:
        free = catalog.suggest_addresses(merged, len(info["modes"][mode]), int(a.get("count", 1)), universe)
        addresses = free.get("easy" if a.get("easy_addresses", True) else "packed") or []
        if len(addresses) < int(a.get("count", 1)):
            raise ValueError(f"Not enough free channels on universe {universe}: try another universe.")
    with _change(f"add_fixtures {len(addresses)}× {key} to {show.label}"):
        new = catalog.add_to_rig(merged, key, mode, addresses, universe)
        for f in new:  # not mounted yet: they wait at the front until mounted (below, or by hand)
            for k in store.PLACEMENT_KEYS:
                f.pop(k, None)
        problems = fxlib.validate(merged)
        if problems:
            raise ValueError("; ".join(problems))
        show.save(merged)
        mounted = manage.mount(show, [f["id"] for f in new]) if a.get("mount", True) else {}
    return {
        "added": [{k: f[k] for k in ("id", "fixture", "mode", "universe", "address")} for f in new],
        "mounted": sorted(mounted),
        "warnings": fxlib.overlaps(show.load()),
    }


def create_fixture(a: dict) -> dict:
    """A fixture the library doesn't have, made from the DMX chart in its manual (library/generic.py from_chart)."""
    from amadeus.library import catalog, generic

    before = _fixture_files()
    with _change(f"create_fixture {a.get('manufacturer', '')} {a.get('model', '')}".strip()) as kept:
        made = generic.from_chart(
            str(a.get("manufacturer", "")), str(a.get("model", "")), str(a.get("type", "")),
            list(a.get("channels") or []), str(a.get("mode", "")), a.get("colour_wheel") or None,
            a.get("physical") or {}, str(a.get("source", "")), a.get("ring_colour") or None,
        )  # fmt: skip
        if "problems" in made:
            raise ValueError("Not made: " + "; ".join(made["problems"]))
        kept.made_fixtures(before)
    return {**made, "checked": False, "details": catalog.details(made["key"])}


def import_fixture_file(a: dict) -> dict:
    """A fixture file the user has into their library: GDTF (.gdtf), QLC+ (.qxf, also what the Open Fixture
    Library exports)."""
    from amadeus.library import catalog, qlc

    path = Path(str(a["path"])).expanduser()
    if not path.is_file():
        raise ValueError(f"No file at {path}")
    suffix = path.suffix.lower()
    if suffix == ".gdtf":
        try:
            from amadeus.library import gdtf
        except ImportError:
            raise ValueError(
                "GDTF files can't be read by this version yet: ask the maker or the Open Fixture "
                "Library for a QLC+ file (.qxf), or make the fixture from its DMX chart"
            ) from None
        add = gdtf.add_file
    elif suffix == ".qxf":
        add = qlc.add_file
    else:
        raise ValueError(f"{path.name}: a .gdtf or .qxf file, please")
    before = _fixture_files()
    with _change(f"import_fixture_file {path.name}") as kept:
        key = add(path)
        kept.made_fixtures(before)
    return {"key": key, "details": catalog.details(key)}


def automount(a: dict) -> dict:
    from amadeus.rig import manage

    show = _show(a)
    with _change(f"automount {show.label}"):
        places = manage.mount(show, a.get("ids") or None, everything=bool(a.get("all")))
    return {"set": show.set, "rig": show.rig, "mounted": places}


def check_show(a: dict) -> dict:
    """What would stop the set from saving, channel overlaps, fixtures not mounted, fixtures that stay dark."""
    from amadeus.dmx import outputs
    from amadeus.library import fixtures as fxlib
    from amadeus.rig import store

    show = _show(a)
    merged = show.load()
    dark, missing = {}, []
    for f in merged.get("fixtures", []):
        try:
            why = fxlib.test_refusal(fxlib.get(f["fixture"]))
        except (Exception, SystemExit):  # noqa: BLE001 - a definition that isn't there
            missing.append(f["id"])
            continue
        if why:
            dark[f["id"]] = why
    return {
        "set": show.set,
        "rig": show.rig,
        "problems": fxlib.validate(merged) + outputs.validate(merged),
        "overlaps": fxlib.overlaps(merged),
        "not_mounted": [f["id"] for f in merged.get("fixtures", []) if f.get(store.UNPLACED)],
        "not_patched": [f["id"] for f in merged.get("fixtures", []) if not fxlib.patched(f)],
        "unknown_fixture_definition": missing,
        "stays_dark": dark,
    }


def write_hang_sheet(a: dict) -> dict:
    from amadeus.rig import hangsheet

    show = _show(a)
    path = Path(a.get("path") or paths.DATA / f"hang-sheet-{show.set}-{show.rig}.html").expanduser()
    path.write_text(hangsheet.html(show.load(), show.set, show.rig), encoding="utf-8")
    return {"written": str(path)}


from amadeus.library.mapper import ROLES as _ROLES  # noqa: E402 - the roles a chart's channel can have

_PAIR = {
    "set": {"type": "string", "description": "a set's name (default: the active set)"},
    "rig": {"type": "string", "description": "a rig's name (default: the active rig)"},
}


def _schema(props: dict | None = None, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props or {}, "required": list(required), "additionalProperties": False}


# name: (function, read only, description, input schema)
TOOLS = {
    "read_guide": (read_guide, True, "How sets, rigs and placements fit together, the coordinates, the conventions "
                   "and the way to work. Read it before the first change.", _schema()),
    "list_sets_and_rigs": (list_sets_and_rigs, True, "The sets (your gear), the rigs (venues), which are active, "
                           "which sets are placed on which rigs, and the rig templates.", _schema()),
    "get_show": (get_show, True, "A set placed on a rig, as one combined dict: the set's fixtures with where each "
                 "hangs, the stage, trusses, zones and screen. Edit it and give it to save_show.", _schema(_PAIR)),
    "save_show": (save_show, False, "Save a combined dict (from get_show, edited). It is checked first: nothing is "
                  "saved when there are problems. Overlapping DMX channels come back as warnings.",
                  _schema({**_PAIR, "show": {"type": "object", "description": "the combined dict"}}, ("show",))),
    "create_set": (create_set, False, "A new set: empty, or a copy of another (copy_of). Becomes the active set "
                   "unless make_active is false.", _schema({
                       "name": {"type": "string"}, "copy_of": {"type": "string"},
                       "make_active": {"type": "boolean", "default": True}}, ("name",))),
    "create_rig": (create_rig, False, "A new rig (a venue) from a template, or a copy of another (copy_of). "
                   "Becomes the active rig unless make_active is false.", _schema({
                       "name": {"type": "string"},
                       "template": {"type": "string", "enum": ["floor", "stands", "booth", "club", "stage", "ring"]},
                       "width_m": {"type": "number", "description": "stage width (default 8)"},
                       "truss_height_m": {"type": "number", "description": "default 4.5"},
                       "room_depth_m": {"type": "number", "description": "room in front of the stage (default 15)"},
                       "screen": {"type": "boolean", "description": "an LED wall behind the DJ"},
                       "copy_of": {"type": "string"}, "make_active": {"type": "boolean", "default": True}},
                       ("name",))),
    "place_set_on_rig": (place_set_on_rig, False, "Put a set on a rig, and auto-mount its fixtures there (unless "
                         "automount is false).", _schema({
                             "set": {"type": "string"}, "rig": {"type": "string"},
                             "automount": {"type": "boolean", "default": True}}, ("set", "rig"))),
    "make_active": (make_active, False, "Make a set and/or a rig the active one (what the apps open and a show "
                    "plays).", _schema(_PAIR)),
    "search_fixtures": (search_fixtures, True, "Search the fixture library: ours, the QLC+ library and the Open "
                        "Fixture Library, by brand and model words.", _schema({
                            "query": {"type": "string"}, "limit": {"type": "integer", "default": 15}}, ("query",))),
    "fixture_details": (fixture_details, True, "A fixture's kind, DMX modes (channel by channel), colour wheel and "
                        "gobos, by its key from search_fixtures.", _schema({"key": {"type": "string"}}, ("key",))),
    "add_fixtures": (add_fixtures, False, "Add fixtures of one model to a set, at the given start addresses or on "
                     "free ones (count), and auto-mount them on the rig (unless mount is false).", _schema({
                         **_PAIR, "key": {"type": "string", "description": "from search_fixtures"},
                         "mode": {"type": "string", "description": "a DMX mode (default: the fixture's default)"},
                         "count": {"type": "integer", "default": 1},
                         "addresses": {"type": "array", "items": {"type": "integer"},
                                       "description": "start addresses, one per fixture (default: free ones)"},
                         "universe": {"type": "integer", "default": 1},
                         "easy_addresses": {"type": "boolean", "default": True,
                                            "description": "free addresses ending in 1 (1, 11, 21…), else packed"},
                         "mount": {"type": "boolean", "default": True}}, ("key",))),
    "create_fixture": (create_fixture, False, "Make a fixture the library doesn't have, from the DMX chart in "
                       "its manual: every channel of the mode in the chart's order, each played by the show (a "
                       "role) or held at a value (shutter open, no strobe, gobo open, programs off). Only from the "
                       "real chart of that exact model, never from a lookalike. It is marked not checked until "
                       "the channel check on the real fixture.", _schema({
                           "manufacturer": {"type": "string"},
                           "model": {"type": "string", "description": "exactly as the maker names it"},
                           "type": {"type": "string", "enum": ["spot", "wash", "beam", "par", "bar", "strobe",
                                                               "blinder"]},
                           "mode": {"type": "string", "description": "the mode's name in the chart (default: "
                                    "\"<channels>ch\")"},
                           "channels": {"type": "array", "items": {"type": "object", "properties": {
                               "name": {"type": "string", "description": "as the chart names it"},
                               "role": {"type": "string", "enum": [r["role"] for r in _ROLES] + ["hold"],
                                        "description": "what the show plays on it, or hold"},
                               "value": {"type": "integer", "minimum": 0, "maximum": 255,
                                         "description": "hold: the value it stays at (from the chart)"},
                               "cell": {"type": "integer", "description": "a bar: which cell (1…)"},
                               "ranges": {"type": "array", "items": {"type": "array"},
                                          "description": "the chart's ranges: [[from, to, what it does], …]"},
                           }, "required": ["name", "role"]}},
                           "colour_wheel": {"type": "array", "description": "the colour wheel's slots, open first",
                                            "items": {"type": "object", "properties": {
                                                "name": {"type": "string"}, "from": {"type": "integer"},
                                                "to": {"type": "integer"},
                                                "rgb": {"type": "array", "items": {"type": "number"}}}}},
                           "ring_colour": {"type": "array", "description": "a ring_color channel's colours (an LED "
                                           "ring or strip round the lens), \"off\" with rgb [0,0,0] among them",
                                           "items": {"type": "object", "properties": {
                                               "name": {"type": "string"}, "from": {"type": "integer"},
                                               "to": {"type": "integer"},
                                               "rgb": {"type": "array", "items": {"type": "number"}}}}},
                           "physical": {"type": "object", "properties": {
                               "watts": {"type": "number"}, "beam_deg": {"type": "number"},
                               "beam_deg_max": {"type": "number"}, "pan_deg": {"type": "number"},
                               "tilt_deg": {"type": "number"}}},
                           "source": {"type": "string", "description": "where the chart is from: the manual's "
                                      "name and page, or its web address"},
                       }, ("manufacturer", "model", "type", "channels", "source"))),
    "import_fixture_file": (import_fixture_file, False, "Add a fixture file the user has to their library: GDTF "
                            "(.gdtf) or QLC+ (.qxf, also what the Open Fixture Library editor exports). Returns "
                            "its key and modes.", _schema({"path": {"type": "string", "description": "the file "
                                                                    "on this computer"}}, ("path",))),
    "automount": (automount, False, "Auto-mount the set's fixtures on the rig: the ones not mounted yet, the "
                  "given ids, or all (re-mount every one).", _schema({
                      **_PAIR, "ids": {"type": "array", "items": {"type": "string"}},
                      "all": {"type": "boolean", "default": False}})),
    "check_show": (check_show, True, "What is wrong or unfinished: problems that block saving, DMX overlaps, "
                   "fixtures not mounted or without an address, unknown definitions, fixtures the show keeps dark.",
                   _schema(_PAIR)),
    "write_hang_sheet": (write_hang_sheet, False, "Write the hang sheet (the crew's paperwork: where every fixture "
                         "hangs, its address, labels) as a printable HTML file; returns its path.", _schema({
                             **_PAIR, "path": {"type": "string", "description": "default: in the data folder"}})),
    "undo_last_change": (undo_last_change, False, "Put the sets and rigs back as they were before the last change "
                         "made through these tools (call again to go further back).", _schema()),
}  # fmt: skip


def tool_list() -> list[dict]:
    return [
        {
            "name": name,
            "description": desc,
            "inputSchema": schema,
            "annotations": {"readOnlyHint": ro, "destructiveHint": False, "openWorldHint": False},
        }
        for name, (_, ro, desc, schema) in TOOLS.items()
    ]


def call(name: str, arguments: dict) -> dict:
    """A tools/call result: the tool's answer as JSON text, or the error as text with isError."""
    if name not in TOOLS:
        raise KeyError(name)
    try:
        out = TOOLS[name][0](arguments or {})
        return {"content": [{"type": "text", "text": json.dumps(out, indent=1, ensure_ascii=False)}]}
    except (Exception, SystemExit) as e:  # noqa: BLE001 - the assistant reads what went wrong and tries again
        msg = str(e) if isinstance(e, (SystemExit, ValueError)) else f"{e.__class__.__name__}: {e}"
        return {"content": [{"type": "text", "text": msg}], "isError": True}


# ---------------------------------------------------------------- the protocol


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, its answer out (None for a notification)."""
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:  # notifications (initialized, cancelled): nothing to answer
        return None
    try:
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "amadeus-dmx", "title": "Amadeus DMX", "version": _version()},
                "instructions": GUIDE.read_text(encoding="utf-8"),
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tool_list()}
        elif method == "tools/call":
            try:
                result = call(params.get("name", ""), params.get("arguments") or {})
            except KeyError:
                return _error(mid, -32602, f"Unknown tool: {params.get('name')}")
        else:
            return _error(mid, -32601, f"Method not found: {method}")
    except Exception as e:  # noqa: BLE001 - the server keeps going
        return _error(mid, -32603, f"{e.__class__.__name__}: {e}")
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("amadeus-dmx")
    except Exception:  # noqa: BLE001 - not installed as a package (the apps run it from source)
        return "0"


def serve(stdin=None, stdout=None):
    """Read messages from stdin until it closes, answer on stdout. Everything else the engine prints goes to
    stderr: stdout is the conversation."""
    stdin = stdin or sys.stdin.buffer
    out = stdout or sys.stdout.buffer
    sys.stdout = sys.stderr
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = _error(None, -32700, "Parse error")
        else:
            if isinstance(msg, list):  # a batch (2025-03-26)
                reply = [r for r in (handle(m) for m in msg) if r] or None
            else:
                reply = handle(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()
