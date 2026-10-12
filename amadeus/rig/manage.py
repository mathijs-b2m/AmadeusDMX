"""Making and changing sets and rigs: what the command line, the setup pages and the Mac app all do."""

from __future__ import annotations

import copy

from amadeus.rig import store, templates


def new_set(name: str, copy_of: str | None = None, generated: dict | None = None, rig: str | None = None) -> str:
    """A new set: empty (with the current set's node and safety), a copy of another (it is placed on every rig
    the original is placed on), or `generated` (a test rig from rig.grid: its positions become `rig`)."""
    name = store.safe_name(name)
    if name in store.sets.names():
        raise SystemExit(f"A set '{name}' already exists")
    if generated is not None:
        rig_name = store.safe_name(rig or name)
        rig_doc = (
            store.rigs.load(rig_name)
            if rig_name in store.rigs.names()
            else {"description": generated.get("description", "")}
        )
        set_doc, rig_doc = store.split(generated, name, rig_doc)
        store.sets.save(name, set_doc)
        store.rigs.save(rig_name, rig_doc)
        return name
    if copy_of:
        doc = store.sets.load(store.safe_name(copy_of))
        doc["description"] = f"copy of {copy_of}"
        store.sets.save(name, doc)
        for r in store.rigs.names():
            rig_doc = store.rigs.load(r)
            places = rig_doc.get("placements", {})
            if copy_of in places:
                places[name] = copy.deepcopy(places[copy_of])
                store.rigs.save(r, rig_doc)
        return name
    current = store.sets.load() if store.sets.names() else {}
    store.sets.save(name, {
        "description": "",
        "artnet": current.get("artnet", {"ip": "127.0.0.1", "port": 6454, "fps": 40}),
        "safety": current.get("safety", {"max_flash_hz": 3, "master": 1.0}),
        "director": current.get("director", "rules"),
        "fixtures": [],
    })  # fmt: skip
    return name


def new_rig(name: str, template: str = "booth", width: float = 8.0, height: float = 4.5, depth: float = 15.0,
            screen: bool = False, copy_of: str | None = None) -> str:  # fmt: skip
    """A new rig from a template (see rig.templates), or a copy of another rig (with its placements)."""
    name = store.safe_name(name)
    if name in store.rigs.names():
        raise SystemExit(f"A rig '{name}' already exists")
    if copy_of:
        doc = store.rigs.load(store.safe_name(copy_of))
        doc["description"] = f"copy of {copy_of}"
    else:
        doc = templates.rig(template, width, height, depth, screen)
    store.rigs.save(name, doc)
    return name


def mount(show: store.Selection, ids: list[str] | None = None, everything: bool = False) -> dict[str, dict]:
    """Auto-mount the set's fixtures on the rig: `ids`, else the ones not mounted yet (all, with `everything`).
    Saves, and returns the new placements."""
    from amadeus.rig.automount import automount

    merged = show.load()
    if ids is None:
        ids = [f["id"] for f in merged.get("fixtures", []) if everything or f.get(store.UNPLACED)]
    for f in merged["fixtures"]:  # fixtures being re-mounted don't take up room
        if f["id"] in ids:
            f[store.UNPLACED] = True
    places = automount(merged, ids)
    for f in merged["fixtures"]:
        if f["id"] in places:
            for k in store.PLACEMENT_KEYS:
                f.pop(k, None)
            f.pop(store.UNPLACED, None)
            f.update(places[f["id"]])
    show.save(merged)
    return places
