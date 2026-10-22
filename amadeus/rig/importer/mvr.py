"""MVR (My Virtual Rig, DIN SPEC 15801): the scene file Vectorworks, Capture, grandMA3 and Depence exchange.

An .mvr is a zip with GeneralSceneDescription.xml (layers of fixtures, trusses and groups, each with a
transform in millimetres, right-handed, z up) and the fixtures' GDTF files. A fixture's GDTF names its
manufacturer, model and DMX modes, so its footprint is known; its patch is in `Addresses` (an absolute
address, or "universe.address").

The frame is a guess the report states: the usual drawing convention, origin at downstage centre on the stage
floor, +Y upstage (the audience at the bottom of the plan), so +X is stage left. GDTF models a fixture
hanging, its beam along its own -Z: a fixture turned upside down from that stands on the floor.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

from amadeus.rig.importer.draft import Draft, Item

OBJECTS = ("Fixture", "Truss", "GroupObject", "SceneObject", "Support", "VideoScreen", "Projector")


def _matrix(node: ET.Element | None) -> np.ndarray:
    """A 4×4 row-vector transform from a Matrix node ({u}{v}{w}{o}, o in mm → m)."""
    m = np.eye(4)
    text = node.findtext("Matrix") if node is not None else None
    if text:
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)]
        if len(nums) == 12:
            for r in range(4):
                m[r, :3] = nums[3 * r : 3 * r + 3]
            m[3, :3] /= 1000.0
    return m


def address(text: str) -> tuple[int, int]:
    """(universe, address) from "45" (absolute: 513 is universe 2's first) or "2.45"."""
    text = text.strip()
    if "." in text:
        u, a = text.split(".", 1)
        return int(u), int(a)
    n = int(text)
    return (n - 1) // 512 + 1, (n - 1) % 512 + 1


def gdtf_info(data: bytes) -> dict:
    """Manufacturer, model and the footprint of each DMX mode, from a GDTF file's description.xml."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("description.xml"))
    ft = root.find("FixtureType")
    if ft is None:
        return {}
    modes = {}
    for mode in ft.iter("DMXMode"):
        offsets = [int(o) for ch in mode.iter("DMXChannel") for o in (ch.get("Offset") or "").split(",") if o.strip()]
        modes[mode.get("Name", "")] = max(offsets, default=0)
    return {
        "manufacturer": ft.get("Manufacturer", ""),
        "model": ft.get("LongName") or ft.get("Name", ""),
        "modes": modes,
    }


def _spec_name(spec: str) -> str:
    """ "Martin@MAC Aura XB@v1.2.gdtf" → "Martin MAC Aura XB" (GDTF Share names files Manufacturer@Fixture@…)."""
    parts = Path(spec).stem.split("@") if spec.lower().endswith(".gdtf") else spec.split("@")
    return " ".join(p for p in parts[:2] if p and p.lower() != "custom")


def read(path: Path) -> Draft:
    d = Draft()
    with zipfile.ZipFile(path) as z:
        names = {Path(n).name.lower(): n for n in z.namelist()}
        root = ET.fromstring(z.read(names.get("generalscenedescription.xml", "GeneralSceneDescription.xml")))
        gdtf: dict[str, dict] = {}

        def info(spec: str) -> dict:
            if spec not in gdtf:
                key = spec.lower() if spec.lower().endswith(".gdtf") else spec.lower() + ".gdtf"
                try:
                    gdtf[spec] = gdtf_info(z.read(names[key])) if key in names else {}
                except (KeyError, zipfile.BadZipFile, ET.ParseError):
                    gdtf[spec] = {}
            return gdtf[spec]

        positions = {p.get("uuid", ""): p.get("name", "") for p in root.iter("Position")}

        def walk(node: ET.Element, parent: np.ndarray, layer: str) -> None:
            children = node.find("ChildList")
            for obj in children if children is not None else []:
                if obj.tag not in OBJECTS:
                    continue
                m = _matrix(obj) @ parent
                o, w = m[3, :3], m[2, :3]
                pos = (round(float(-o[0]), 3), round(float(-o[1]), 3), round(float(o[2]), 3))
                if obj.tag == "Fixture":
                    d.items.append(_fixture(obj, pos, w, layer, positions, info, path.name))
                elif obj.tag == "Truss" and abs(m[0, 2]) < 0.5:  # a horizontal one (towers are left to the rows)
                    u = m[0, :3] / (np.linalg.norm(m[0, :3]) or 1.0)
                    d.trusses.append(
                        {
                            "name": obj.get("name", "") or "truss",
                            "s": pos[0],
                            "y": pos[1],
                            "z": pos[2],
                            "dir": (round(float(-u[0]), 4), round(float(-u[1]), 4)),
                        }
                    )
                walk(obj, m, layer)

        for layer in root.iter("Layer"):
            walk(layer, _matrix(layer), layer.get("name", ""))
    if not d.items:
        d.note("missing", f"{path.name}: no fixtures in this MVR file")
        return d
    d.note(
        "check",
        f"{path.name}: read as drawn with the audience at the bottom of the plan (+Y upstage), the "
        "origin at downstage centre on the stage floor; turn the rig round in the editor if it came out the "
        "wrong way",
    )
    return d


def _fixture(obj, pos, w, layer, positions, info, fname) -> Item:
    spec, mode = obj.findtext("GDTFSpec") or "", obj.findtext("GDTFMode") or ""
    gi = info(spec) if spec else {}
    name = f"{gi['manufacturer']} {gi['model']}".strip() if gi.get("model") else _spec_name(spec) or obj.get("name", "")
    universe = addr = 0
    a = obj.find("Addresses/Address")
    if a is not None and (a.text or "").strip():
        try:
            universe, addr = address(a.text)
        except ValueError:
            pass
    label = (obj.findtext("FixtureID") or obj.findtext("UnitNumber") or "").strip()
    n = float(np.linalg.norm(w)) or 1.0
    beam = (w[0] / n, w[1] / n, -w[2] / n)  # its -Z, in the importer's frame (x and y turned round)
    return Item(
        name=name,
        label=label if label not in ("", "0") else "",
        mode=mode,
        channels=gi.get("modes", {}).get(mode, 0),
        universe=universe,
        address=addr,
        pos=pos,
        beam=(round(float(beam[0]), 4), round(float(beam[1]), 4), round(float(beam[2]), 4)),
        hanging=bool(w[2] > 0),
        where=positions.get((obj.findtext("Position") or "").strip(), "") or layer,
        source=f"{fname}: {obj.get('name', '') or name}",
    )
