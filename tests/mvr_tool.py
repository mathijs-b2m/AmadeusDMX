"""Write an MVR file from one of our sets on a rig (for the importer's tests): every fixture with its transform,
GDTF spec name and patch, the trusses as Truss objects, as Vectorworks would draw it (+Y upstage, origin at
downstage centre, millimetres)."""

from __future__ import annotations

import io
import math
import uuid
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry, store


def _basis(beam: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """u, v, w for a fixture whose beam (its -w) points along `beam`."""
    w = -beam / np.linalg.norm(beam)
    up = np.array([0.0, 0.0, 1.0]) if abs(w[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(up, w)
    u /= np.linalg.norm(u)
    return u, np.cross(w, u), w


def _matrix(u, v, w, o) -> str:
    return "".join("{" + ",".join(f"{c:.6f}" for c in vec) + "}" for vec in (u, v, w, o))


def mvr_bytes(set_doc: dict, rig_doc: dict, name: str, gdtf: dict[str, bytes] | None = None) -> bytes:
    merged = store.compose(set_doc, rig_doc, name)
    W = merged["stage"]["width_m"]
    root = ET.Element("GeneralSceneDescription", verMajor="1", verMinor="6")
    layer = ET.SubElement(
        ET.SubElement(ET.SubElement(root, "Scene"), "Layers"), "Layer", name="Lights", uuid=str(uuid.uuid4())
    )
    kids = ET.SubElement(layer, "ChildList")

    def to_mvr(x, y, z):  # rig frame (x from stage left) → MVR (mm, +X stage left, +Y upstage)
        return np.array([-(x - W / 2) * 1000, -y * 1000, z * 1000])

    for t in merged["trusses"]:
        if t.get("vertical"):
            continue
        r = math.radians(t.get("rot_deg", 0.0))
        u = np.array([-math.cos(r), -math.sin(r), 0.0])
        o = to_mvr(t["x_m"], t["y_m"], t["z_m"])
        n = ET.SubElement(kids, "Truss", name=t["id"], uuid=str(uuid.uuid4()))
        ET.SubElement(n, "Matrix").text = _matrix(u, np.cross([0, 0, 1], u), [0, 0, 1], o)
    for f in merged["fixtures"]:
        d = fxlib.get(f["fixture"])
        if d["kind"] in ("moving_head", "moving_bar"):
            beam = np.array([0.0, 0.0, -1.0 if f.get("mount") == "hang" else 1.0])
        else:
            bx, by, bz = geometry.static_dir(f, d["kind"])
            beam = np.array([-bx, -by, bz])
        u, v, w = _basis(beam)
        n = ET.SubElement(kids, "Fixture", name=f["id"], uuid=str(uuid.uuid4()))
        ET.SubElement(n, "Matrix").text = _matrix(u, v, w, to_mvr(f["x"] * W, f["y_m"], f["z_m"]))
        spec = f"{d['manufacturer']}@{d['model']}"
        ET.SubElement(n, "GDTFSpec").text = spec + (".gdtf" if gdtf and spec in gdtf else "")
        ET.SubElement(n, "GDTFMode").text = f["mode"]
        ET.SubElement(n, "FixtureID").text = "".join(c for c in f["id"] if c.isdigit())
        ET.SubElement(ET.SubElement(n, "Addresses"), "Address", attrib={"break": "0"}).text = str(
            (f["universe"] - 1) * 512 + f["address"]
        )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("GeneralSceneDescription.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        for spec, data in (gdtf or {}).items():
            z.writestr(spec + ".gdtf", data)
    return out.getvalue()


def gdtf_bytes(manufacturer: str, model: str, modes: dict[str, int]) -> bytes:
    """A minimal GDTF file: the fixture type and its DMX modes with that many channels."""
    root = ET.Element("GDTF", DataVersion="1.2")
    ft = ET.SubElement(root, "FixtureType", Manufacturer=manufacturer, Name=model, LongName=model)
    dm = ET.SubElement(ft, "DMXModes")
    for name, n in modes.items():
        chs = ET.SubElement(ET.SubElement(dm, "DMXMode", Name=name), "DMXChannels")
        for k in range(1, n + 1):
            ET.SubElement(chs, "DMXChannel", Offset=str(k))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("description.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return out.getvalue()
