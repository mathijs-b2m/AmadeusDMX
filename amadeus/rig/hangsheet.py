"""The hang sheet: a set on a rig on paper, for the crew who hang it.

A set designed in the app has to be hung for real by someone on a ladder. This prints what they need, the way a
lighting designer's plot and paperwork would: a plan of the stage seen from above (the audience at the bottom),
per truss and tower a drawing and a table (which fixture goes where, measured from a named end, on which side,
which way it faces), the fixtures on the floor and on stands, the DMX patch to set on each fixture, and labels to
stick on the fixtures or their cases.

Every fixture gets a position label: its truss and its place along it counted from the stage-left end ("front
3"), so a label says where a fixture goes. Stage left and stage right are the performer's, facing the audience
(stage left is on your right when you stand in the audience); x = 0 is the stage-left edge. Distances are to the
fixture's clamp, in metres: being 10–20 cm off doesn't hurt the show, swapping two fixtures or turning one
round does.

`layout` gives the rows (what the tests check); `html` the printable page (one self-contained file).
"""

from __future__ import annotations

import datetime
import html as _html
import math

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry
from amadeus.rig import trusses as T
from amadeus.rig.automount import role

FLOOR = "floor"
SIDE_TEXT = {
    "under": "hanging under",
    "top": "standing on top",
    "front": "on the front face",
    "back": "on the back face",
}
ROLE_COLOR = {"head": "#2a5bd7", "laser": "#1a9e5c", "strobe": "#c9a400", "blinder": "#d9822b",
              "bar": "#8e44ad", "par": "#c0392b", "smoke": "#7f8c8d"}  # fmt: skip


def toward(dx: float, dy: float) -> str:
    """A direction on the stage in crew words (seen from above; +y is the audience, +x stage right)."""
    if math.hypot(dx, dy) < 1e-6:
        return "straight up"
    a = math.degrees(math.atan2(dx, dy))  # 0: the audience, 90: stage right
    names = ["the audience", "the audience, SR", "stage right", "upstage, SR",
             "upstage", "upstage, SL", "stage left", "the audience, SL"]  # fmt: skip
    return names[round(a / 45) % 8]


def _front(f: dict) -> tuple[float, float]:
    """The way a fixture's front faces (rot_deg 0: the audience), seen from above."""
    r = math.radians(f.get("rot_deg", 0.0))
    return -math.sin(r), math.cos(r)


def facing(f: dict, defn: dict, truss: dict | None) -> str:
    """Which way round it goes: a moving head's base front (where the show's pan starts from), else where its
    light points (and how far up)."""
    kind = defn.get("kind", "par")
    side = f.get("truss_side")
    if f.get("mount_roll_deg"):  # on a truss's face or a tower's: base against the truss, head out
        out = _front(f) if side != "back" else tuple(-v for v in _front(f))
        if truss and truss.get("vertical") and side in ("left", "right", "back", "front"):
            out = T.tower_normal(truss, side)
        return f"base on the truss, head out towards {toward(*out)}"
    if fxlib.is_moving(defn):
        return f"base front towards {toward(*_front(f))}"
    stat = "smoke" if kind == "smoke" else role(defn)
    az, el = f.get("aim") or geometry.STATIC_AIM.get(stat, (0.0, 80.0))
    if el >= 85:
        return "points straight up"
    if el <= -85:
        return "points straight down"
    d = geometry.direction(az - f.get("rot_deg", 0.0), el)
    verb = "blows" if kind == "smoke" else "points"
    tilt = f", {abs(el):.0f}° {'up' if el >= 0 else 'down'}" if abs(el) >= 3 else ""
    return f"{verb} at {toward(d[0], d[1])}{tilt}"


def _defn(f: dict) -> dict:
    try:
        return fxlib.get(f["fixture"])
    except (Exception, SystemExit):  # noqa: BLE001 - a missing definition still gets a row
        return {"manufacturer": "", "model": f.get("fixture", "?"), "kind": "par", "physical": {}, "modes": {}}


def _mode(f: dict, defn: dict) -> str:
    if f.get("mode"):
        return f["mode"]
    try:
        return fxlib.default_mode(defn)
    except (Exception, SystemExit):  # noqa: BLE001
        return ""


def _mode_text(r: dict) -> str:
    return r["mode"] if str(r["channels"]) in r["mode"] else f"{r['mode']} ({r['channels']} ch)"


def _channels(f: dict, defn: dict) -> int:
    try:
        return max(1, len(fxlib.channels(defn, _mode(f, defn))))
    except (Exception, SystemExit):  # noqa: BLE001 - an unknown mode: one channel
        return 1


def _ends(t: dict) -> tuple[str, str, int]:
    """For a straight truss or an arc: the end distances are measured from, the other end, and which way along
    the truss (+1: from its -u end) that is. Across the stage: from stage left; up and down the stage: from upstage."""
    L = t["length_m"]
    (ax, ay, _), (bx, by, _) = T.point(t, -L / 2), T.point(t, L / 2)
    if abs(bx - ax) >= abs(by - ay):
        return ("SL end", "SR end", 1 if bx > ax else -1)  # x grows towards stage right
    return ("upstage end", "downstage end", 1 if by > ay else -1)


def _clock(t: dict, u: float) -> str:
    """Where on a ring, as a clock seen from above with the audience at 6."""
    a = T.ring_angle(t, u)
    px, py = -math.cos(a), math.sin(a)  # on the page: stage left on the right, the audience at the bottom
    h = (math.degrees(math.atan2(px, -py)) / 30) % 12
    h = round(h * 2) / 2
    whole = int(h) or 12
    return f"{whole}{':30' if h % 1 else ''} o'clock"


def _where(f: dict, t: dict | None, W: float) -> tuple[float, str]:
    """(sort key, where it goes in words)."""
    if t is None:
        x = f.get("x", 0.5) * W
        y = f.get("y_m", 0.0)
        mount = f.get("mount", "floor")
        depth = (f"{-y:.2f} m upstage of the stage edge" if y < -0.05
                 else f"{y:.2f} m in front of the stage edge" if y > 0.05 else "on the stage edge")  # fmt: skip
        what = {"stand": f"on a stand, {f.get('z_m', 0):.1f} m high", "hang": f"hanging at {f.get('z_m', 0):.1f} m"}
        return x, f"{x:.2f} m from the SL edge, {depth}, {what.get(mount, 'on the floor')}"
    u = f.get("truss_pos_m", 0.0)
    side = f.get("truss_side", "under")
    if t.get("vertical"):
        if side == "top":
            return t["length_m"] + 1, "on top of the tower"
        face = toward(*T.tower_normal(t, side))
        return u, f"{u:.2f} m up from the base, on the face towards {face}"
    if T.is_full_ring(t):  # round from its front middle, one way round
        d = u % t["length_m"]
        return d, f"{d:.2f} m round from the front middle, going SR first ({_clock(t, u)}), {SIDE_TEXT.get(side, side)}"
    ref, _, sign = _ends(t)
    d = t["length_m"] / 2 + sign * u
    return d, f"{d:.2f} m from the {ref}, {SIDE_TEXT.get(side, side)}"


def layout(merged: dict) -> dict:
    """The sheet's rows: `structures` (each truss and tower with its fixtures in order from its reference end),
    `floor` (on the floor and on stands), `waiting` (not placed yet), `patch` (by universe and address)."""
    W = geometry.stage(merged)["width_m"]
    trusses = {t["id"]: t for t in merged.get("trusses", [])}
    by: dict[str, list] = {tid: [] for tid in trusses}
    floor, waiting, rows = [], [], []
    for f in merged.get("fixtures", []):
        defn = _defn(f)
        t = trusses.get(f.get("truss")) if not f.get("_unplaced") else None
        key, where = _where(f, t, W)
        row = {
            "id": f["id"],
            "model": f"{defn.get('manufacturer', '')} {defn.get('model', '')}".strip(),
            "role": role(defn) if defn.get("kind") != "smoke" else "smoke",
            "mode": _mode(f, defn),
            "universe": int(f.get("universe", 1)),
            "address": int(f["address"]) if fxlib.patched(f) else None,  # None: not given yet
            "channels": _channels(f, defn),
            "watts": int(defn.get("physical", {}).get("watts") or 0),
            "kg": float(defn.get("physical", {}).get("weight_kg") or 0),
            "where": where,
            "facing": facing(f, defn, t),
            "side": f.get("truss_side", ""),
            "pos": f.get("truss_pos_m", 0.0),
            "x_m": f.get("x", 0.5) * W,
            "y_m": f.get("y_m", 0.0),
            "_key": key,
        }
        rows.append(row)
        if f.get("_unplaced"):
            row["label"] = "—"
            waiting.append(row)
        elif t is not None:
            by[t["id"]].append(row)
        else:
            floor.append(row)
    structures = []
    for tid, t in trusses.items():
        fx = sorted(by[tid], key=lambda r: r["_key"])
        for n, r in enumerate(fx, 1):
            r["label"] = f"{tid} {n}"
        kind = "tower" if t.get("vertical") else "ring" if T.is_ring(t) else "truss"
        ends = _ends(t)[:2] if kind == "truss" or (kind == "ring" and not T.is_full_ring(t)) else None
        structures.append({"id": tid, "kind": kind, "truss": t, "fixtures": fx, "ends": ends,
                           "watts": sum(r["watts"] for r in fx), "kg": sum(r["kg"] for r in fx),
                           "kg_unknown": sum(1 for r in fx if not r["kg"])})  # fmt: skip
    # front to back, then the towers from stage left
    structures.sort(key=lambda s: (s["kind"] == "tower", -s["truss"].get("y_m", 0.0) if s["kind"] != "tower"
                                   else s["truss"].get("x_m", 0.0)))  # fmt: skip
    floor.sort(key=lambda r: (r["_key"], -r["y_m"]))
    for n, r in enumerate(floor, 1):
        r["label"] = f"{FLOOR} {n}"
    rows.sort(key=lambda r: (r["universe"], r["address"] or 513))  # no address yet: last
    return {"width_m": W, "structures": structures, "floor": floor, "waiting": waiting, "patch": rows}


def overloaded(merged: dict) -> dict[str, str]:
    """Light stands carrying more than they take (`max_kg`), as far as the fixtures' weights are known."""
    out = {}
    for st in layout(merged)["structures"]:
        limit = st["truss"].get("max_kg")
        if limit and st["kg"] > limit:
            out[st["id"]] = f"≈ {st['kg']:.0f} kg on it, it takes {limit:g} kg"
    return out


# ---- the page --------------------------------------------------------------------------------------------------


def _e(s) -> str:
    return _html.escape(str(s))


def _num(r: dict) -> str:
    """The number in a label ("front 3" → "3")."""
    return r["label"].rsplit(" ", 1)[-1]


def _plan_svg(merged: dict, lay: dict) -> str:
    """The stage from above, the audience at the bottom (stage left on the right, as on a lighting plot)."""
    W = lay["width_m"]
    pts: list[tuple[float, float]] = [(0.0, 0.0), (W, 0.0)]
    for t in merged.get("trusses", []):
        if T.is_ring(t):
            R = T.ring_radius(t)
            pts += [(t["x_m"] - R, t["y_m"] - R), (t["x_m"] + R, t["y_m"] + R)]
        elif t.get("vertical"):
            pts.append((t["x_m"], t["y_m"]))
        else:
            pts += [T.point(t, -t["length_m"] / 2)[:2], T.point(t, t["length_m"] / 2)[:2]]
    for f in merged.get("fixtures", []):
        pts.append((f.get("x", 0.5) * W, f.get("y_m", 0.0)))
    x0, x1 = min(p[0] for p in pts) - 0.6, max(p[0] for p in pts) + 0.6
    y0, y1 = min(p[1] for p in pts) - 0.6, max(max(p[1] for p in pts), 0.0) + 1.2
    VW, VH = 1000, 560
    s = min(VW / (x1 - x0), VH / (y1 - y0))

    def P(x: float, y: float) -> tuple[float, float]:
        return round((x1 - x) * s, 1), round((y - y0) * s, 1)

    out = [f'<svg viewBox="0 0 {round((x1 - x0) * s)} {round((y1 - y0) * s)}" class="plan">']
    a, b = P(W, y0 + 0.3), P(0, 0)
    out.append(f'<rect x="{a[0]}" y="{a[1]}" width="{b[0] - a[0]}" height="{b[1] - a[1]}" class="stage"/>')
    out.append(f'<text x="{(a[0] + b[0]) / 2}" y="{b[1] + 0.8 * s}" class="aud">AUDIENCE</text>')
    out.append(f'<text x="{b[0] - 4}" y="{a[1] + 16}" class="sl" text-anchor="end">STAGE LEFT ▸</text>')
    out.append(f'<text x="{a[0] + 4}" y="{a[1] + 16}" class="sl">◂ STAGE RIGHT</text>')
    for k, t in enumerate(merged.get("trusses", [])):
        if T.is_ring(t):
            L = t["length_m"]
            n = 48
            line = " ".join("{:.1f},{:.1f}".format(*P(*T.point(t, -L / 2 + L * k / n)[:2])) for k in range(n + 1))
            out.append(f'<polyline points="{line}" class="truss"/>')
            # by its upstage-most point (a full circle) or its stage-right end (an arc): not at the centre, which
            # rings often share
            lx, ly = P(
                *T.point(t, L / 2 if T.is_full_ring(t) else max(-L / 2, L / 2, key=lambda u: T.point(t, u)[0]))[:2]
            )
            ly -= 14
        elif t.get("vertical"):
            cx, cy = P(t["x_m"], t["y_m"])
            out.append(
                f'<rect x="{cx - 0.15 * s}" y="{cy - 0.15 * s}" width="{0.3 * s}" height="{0.3 * s}" class="tower"/>'
            )
            lx, ly = cx, cy - 0.15 * s - 30
        else:
            (ax, ay), (bx, by) = P(*T.point(t, -t["length_m"] / 2)[:2]), P(*T.point(t, t["length_m"] / 2)[:2])
            out.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" class="truss"/>')
            # at one end, alternating, so trusses above each other (at other heights) keep readable names
            left = (ax < bx) == (k % 2 == 0)
            lx, ly = (min(ax, bx) + 2, ay if ax < bx else by) if left else (max(ax, bx) - 2, by if ax < bx else ay)
            out.append(f'<text x="{lx}" y="{ly - 14}" class="tid" text-anchor="{"start" if left else "end"}">'
                       f'{_e(t["id"])} · {t["z_m"]:.1f} m</text>')  # fmt: skip
            continue
        out.append(f'<text x="{lx}" y="{ly}" class="tid" text-anchor="middle">{_e(t["id"])}</text>')
    labelled = {r["id"]: r for st in lay["structures"] for r in st["fixtures"]} | {r["id"]: r for r in lay["floor"]}
    on_floor = {r["id"] for r in lay["floor"]}
    for f in merged.get("fixtures", []):
        r = labelled.get(f["id"])
        if r is None:
            continue
        cx, cy = P(f.get("x", 0.5) * W, f.get("y_m", 0.0))
        if f.get("truss_side") == "top" and f.get(
            "truss"
        ):  # on top of a truss: drawn just behind it, apart from what hangs under
            cy -= 12
        col = ROLE_COLOR.get(r["role"], "#555")
        dot = (f'<rect x="{cx - 9}" y="{cy - 9}" width="18" height="18" rx="2" fill="{col}"/>' if f["id"] in on_floor
               else f'<circle cx="{cx}" cy="{cy}" r="9" fill="{col}"/>')  # fmt: skip
        out.append(f'{dot}<text x="{cx}" y="{cy + 3.5}" class="fn">{_e(_num(r))}</text>')
    out.append("</svg>")
    return "".join(out)


def _strip_svg(st: dict) -> str:
    """One truss or tower drawn on its own: the fixtures at their distance from the reference end."""
    t, fx = st["truss"], st["fixtures"]
    if st["kind"] == "ring":
        R = T.ring_radius(t)
        s = 120 / max(R, 0.5)
        out = [f'<svg viewBox="{-R * s - 40} {-R * s - 40} {2 * R * s + 80} {2 * R * s + 80}" class="ring">']
        L = t["length_m"]
        arc = [T.point(t, -L / 2 + L * k / 48) for k in range(49)]
        line = " ".join(f"{-(x - t['x_m']) * s:.1f},{(y - t['y_m']) * s:.1f}" for x, y, _ in arc)
        out.append(f'<polyline points="{line}" class="truss"/>')
        out.append(f'<text x="0" y="{R * s + 30}" class="aud">AUDIENCE</text>')
        for r in fx:
            x, y, _ = T.point(t, r["pos"])
            out_r = 1 + (
                22 / (R * s) if r["side"] == "top" else 0
            )  # on top: drawn just outside, apart from what hangs under
            cx, cy = -(x - t["x_m"]) * s * out_r, (y - t["y_m"]) * s * out_r
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="10" fill="{ROLE_COLOR.get(r["role"], "#555")}"/>'
                       f'<text x="{cx:.1f}" y="{cy + 3.5:.1f}" class="fn">{_e(_num(r))}</text>')  # fmt: skip
        return "".join(out) + "</svg>"
    L = t["length_m"]
    vertical = st["kind"] == "tower"
    S = 900 / max(L, 1.0) if not vertical else 260 / max(L, 1.0)
    if vertical:
        H = L * S + 60
        out = [f'<svg viewBox="0 0 360 {H:.0f}" class="tower-svg">',
               f'<rect x="150" y="30" width="24" height="{L * S:.1f}" class="tower"/>',
               f'<text x="162" y="{L * S + 52:.0f}" class="end">base (floor)</text>']  # fmt: skip
        for r in fx:
            d = L + 0.3 if r["side"] == "top" else r["_key"]
            y = 30 + (L - min(d, L)) * S if r["side"] != "top" else 14
            cx = 162 if r["side"] in ("top", "front", "back") else (126 if r["side"] == "left" else 198)
            out.append(f'<circle cx="{cx}" cy="{y:.1f}" r="10" fill="{ROLE_COLOR.get(r["role"], "#555")}"/>'
                       f'<text x="{cx}" y="{y + 3.5:.1f}" class="fn">{_e(_num(r))}</text>'
                       f'<text x="230" y="{y + 4:.1f}" class="dim">{_e(r["label"])}: '
                       f'{"top" if r["side"] == "top" else f"{d:.2f} m"}</text>')  # fmt: skip
        return "".join(out) + "</svg>"
    # seen from the audience: the reference end (stage left) on the right, measured from there
    ref, other = st["ends"]
    out = ['<svg viewBox="-60 0 1020 150" class="strip">',
           '<rect x="0" y="62" width="900" height="16" class="truss-box"/>',
           f'<text x="900" y="56" class="end r">{_e(ref)} · 0 m</text>',
           f'<text x="0" y="56" class="end">{_e(other)} · {L:.2f} m</text>']  # fmt: skip
    for r in fx:
        x = 900 - r["_key"] * S
        y = {"top": 46, "front": 70, "back": 70}.get(r["side"], 96)
        ring = ' class="face"' if r["side"] in ("front", "back") else ""
        out.append(f'<line x1="{x:.1f}" y1="78" x2="{x:.1f}" y2="128" class="tick"/>'
                   f'<text x="{x:.1f}" y="142" class="dim">{r["_key"]:.2f}</text>'
                   f'<circle cx="{x:.1f}" cy="{y}" r="10" fill="{ROLE_COLOR.get(r["role"], "#555")}"{ring}/>'
                   f'<text x="{x:.1f}" y="{y + 3.5}" class="fn">{_e(_num(r))}</text>')  # fmt: skip
    return "".join(out) + "</svg>"


def _dmx(r: dict) -> str:
    return f"U{r['universe']} · {r['address']}" if r["address"] else "no address yet"


def _table(rows: list[dict], with_label: bool = True) -> str:
    head = ("<tr>" + ("<th>Label</th>" if with_label else "") + "<th>Name</th><th>Model</th><th>Where</th>"
            "<th>Which way round</th><th>DMX</th><th>Mode</th></tr>")  # fmt: skip
    body = "".join(
        "<tr>"
        + (f'<td class="lbl">{_e(r["label"])}</td>' if with_label else "")
        + f"<td>{_e(r['id'])}</td><td>{_e(r['model'])}</td><td>{_e(r['where'])}</td><td>{_e(r['facing'])}</td>"
        f'<td class="dmx">{_dmx(r)}</td><td>{_e(_mode_text(r))}</td></tr>'
        for r in rows
    )
    return f"<table>{head}{body}</table>"


def _load(st: dict) -> str:
    parts = [f"{len(st['fixtures'])} fixtures"]
    us = sorted({r["universe"] for r in st["fixtures"]})
    parts.append(("DMX line" if len(us) == 1 else "DMX lines") + " " + ", ".join(f"U{u}" for u in us))
    if st["watts"]:
        parts.append(f"≈ {st['watts']} W")
    if st["kg"]:
        parts.append(f"≈ {st['kg']:.0f} kg" + (f" + {st['kg_unknown']} of unknown weight" if st["kg_unknown"] else ""))
    limit = st["truss"].get("max_kg")
    if limit:
        parts.append(f"takes {limit:g} kg" + (" — TOO HEAVY" if st["kg"] > limit else ""))
    return " · ".join(parts)


def _outputs(merged: dict) -> str:
    dmx = merged.get("dmx") or {}
    if not dmx:
        return ""
    items = "".join(
        f"<li>Universe {_e(u)} → {_e(d.get('device', '?'))}, output {_e(d.get('output', 1))}</li>"
        for u, d in sorted(dmx.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)
    )
    return f"<ul class='outs'>{items}</ul>"


CSS = """
@page { size: A4 landscape; margin: 12mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.35 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #111; background: #fff;
       margin: 0 auto; max-width: 1100px; padding: 16px; }
h1 { font-size: 20pt; margin: 0 0 2px; } h2 { font-size: 14pt; margin: 18px 0 4px; }
.sub { color: #555; margin: 0 0 10px; } .note { color: #444; font-size: 9.5pt; max-width: 75ch; }
section { break-before: page; } section.first { break-before: auto; }
table { border-collapse: collapse; width: 100%; margin-top: 6px; font-size: 9.5pt; }
th, td { border: 1px solid #bbb; padding: 3px 6px; text-align: left; vertical-align: top; }
th { background: #eee; } tr { break-inside: avoid; }
td.lbl { font-weight: 700; white-space: nowrap; } td.dmx { font-weight: 700; white-space: nowrap; }
svg { width: 100%; height: auto; display: block; }
svg.plan { max-height: 150mm; } svg.ring { max-width: 90mm; } svg.tower-svg { max-width: 110mm; }
.stage { fill: #f3f3f3; stroke: #999; } .truss { stroke: #444; stroke-width: 6; fill: none; }
.truss-box { fill: #ddd; stroke: #444; } .tower { fill: #ccc; stroke: #444; }
.tick { stroke: #999; stroke-dasharray: 3 3; }
text { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; }
.fn { fill: #fff; font-size: 10px; font-weight: 700; text-anchor: middle; }
.face { stroke: #000; stroke-width: 2; }
.tid { font-size: 13px; font-weight: 700; fill: #222; }
.aud, .end { font-size: 12px; fill: #555; text-anchor: middle; letter-spacing: 0.08em; }
.end { text-anchor: start; letter-spacing: 0; } .end.r { text-anchor: end; } .sl { font-size: 11px; fill: #777; }
.dim { font-size: 11px; fill: #333; text-anchor: middle; }
svg.tower-svg .dim { text-anchor: start; }
.legend span { display: inline-block; margin-right: 12px; font-size: 9.5pt; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px;
            vertical-align: -1px; }
.warn { border: 2px solid #c0392b; padding: 6px 10px; margin: 10px 0; }
.labels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4mm; }
.sticker { border: 1px dashed #888; padding: 3mm 4mm; height: 36mm; break-inside: avoid; overflow: hidden; }
.sticker b { font-size: 18pt; display: block; line-height: 1.1; } .sticker .d { font-size: 13pt; font-weight: 700; }
.sticker small { display: block; color: #333; font-size: 8.5pt; }
@media print { body { padding: 0; max-width: none; } .noprint { display: none; } }
"""


def html(merged: dict, set_name: str = "", rig_name: str = "") -> str:
    """The printable hang sheet: one HTML file (print it, or save it as PDF from the browser)."""
    lay = layout(merged)
    title = f"{set_name or 'Set'} on {rig_name or 'rig'}"
    today = datetime.date.today().isoformat()
    placed = sum(len(s["fixtures"]) for s in lay["structures"]) + len(lay["floor"])
    roles_used = sorted({r["role"] for r in lay["patch"]}, key=list(ROLE_COLOR).index)
    legend = "".join(f'<span><i style="background:{ROLE_COLOR[k]}"></i>{k}</span>' for k in roles_used)
    legend += "<span>● on a truss or tower · ■ on the floor or a stand · the number is its place on it</span>"
    p = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>Hang sheet: {_e(title)}</title>"
         f"<style>{CSS}</style></head><body>"]  # fmt: skip
    p.append(f"<section class='first'><h1>Hang sheet: {_e(title)}</h1>"
             f"<p class='sub'>{placed} fixtures to hang · {len(lay['structures'])} trusses and towers · {today}"
             "<span class='noprint'> · print it, or save it as PDF (⌘P)</span></p>")  # fmt: skip
    p.append("<p class='note'>Stage left (SL) and stage right (SR) are the performer's, facing the audience: "
             "standing in the audience, stage left is on your right. The plan is seen from above with the audience "
             "at the bottom; the truss drawings are seen from the audience. Distances are to the fixture's clamp, "
             "in metres from the named end of the truss. A label (“front 3”) is where a fixture goes: the truss and "
             "the place counted from that end. Its name (“top3”) is what the app calls it, for the DMX patch. "
             "Close is good enough: what matters is that every fixture is on the right truss, in the "
             "right order, the right way round, with its DMX address and mode set.</p>")  # fmt: skip
    if lay["waiting"]:
        p.append(
            f"<p class='warn'><b>{len(lay['waiting'])} fixtures aren't placed on this rig yet</b> "
            f"({_e(', '.join(r['id'] for r in lay['waiting']))}): place them in the rig editor first.</p>"
        )
    p.append(f"<p class='legend'>{legend}</p>{_plan_svg(merged, lay)}</section>")
    for st in lay["structures"]:
        if not st["fixtures"]:
            continue
        t = st["truss"]
        if st["kind"] == "tower":
            what = f"tower {t['length_m']:.1f} m high, at {t['x_m']:.2f} m from the SL edge"
        elif st["kind"] == "ring":
            what = (
                f"round truss Ø {T.ring_radius(t) * 2:.1f} m"
                + ("" if T.is_full_ring(t) else f", {T.ring_arc(t):.0f}° arc")
                + f", at {t['z_m']:.1f} m"
            )
        else:
            deck = float(merged.get("stage", {}).get("deck_m", 0.0))
            trim = (f"{t['z_m'] - deck:.1f} m above the stage ({t['z_m']:.1f} m above the hall floor)"
                    if deck > 0 and t["y_m"] < 0 else f"{t['z_m']:.1f} m")  # fmt: skip
            noun = {"bridge": "light bridge", "tbar": "T-bar stand"}.get(t.get("type", "")) if T.is_stand(t) else None
            what = f"{noun or 'truss'} {t['length_m']:.1f} m long, at {trim}, {abs(t['y_m']):.1f} m " + (
                "upstage of" if t["y_m"] < 0 else "in front of") + " the stage edge"  # fmt: skip
        p.append(f"<section><h2>{_e(st['id'])}</h2><p class='sub'>{_e(what)} · {_e(_load(st))}</p>")
        if st["kind"] == "truss":
            p.append("<p class='note'>Seen from the audience. Dots under the truss hang under it, dots on top "
                     "stand on it, outlined dots are on its front or back face.</p>")  # fmt: skip
        elif st["kind"] == "ring":
            start = (
                "its front middle (6 o'clock), going stage right first" if T.is_full_ring(t) else f"its {st['ends'][0]}"
            )
            p.append("<p class='note'>Seen from above, the audience at the bottom. Measured round the truss from "
                     f"{start}.</p>")  # fmt: skip
        p.append(_strip_svg(st) + _table(st["fixtures"]) + "</section>")
    if lay["floor"]:
        p.append("<section><h2>On the floor and on stands</h2><p class='sub'>"
                 f"{len(lay['floor'])} fixtures, measured from the stage-left edge and the front edge of the stage</p>"
                 + _table(lay["floor"]) + "</section>")  # fmt: skip
    p.append("<section><h2>DMX patch</h2><p class='sub'>Set each fixture to this address and mode before it goes up. "
             "The universe is the DMX line it is on.</p>" + _outputs(merged))  # fmt: skip
    p.append(
        "<table><tr><th>Universe</th><th>Address</th><th>Channels</th><th>Label</th><th>Name</th>"
        "<th>Model</th><th>Mode</th></tr>"
    )
    for r in lay["patch"]:
        a = r["address"]
        span = f"{a}–{a + r['channels'] - 1}" if a else "no start address yet"
        p.append(f"<tr><td class='dmx'>{r['universe']}</td><td class='dmx'>{a or '–'}</td>"
                 f"<td>{span}</td><td class='lbl'>{_e(r['label'])}</td><td>{_e(r['id'])}</td>"
                 f"<td>{_e(r['model'])}</td><td>{_e(_mode_text(r))}</td></tr>")  # fmt: skip
    p.append("</table></section>")
    stickers = [r for st in lay["structures"] for r in st["fixtures"]] + lay["floor"]
    if stickers:
        p.append("<section><h2>Labels</h2><p class='sub noprint'>Cut out, or print on 3 × 7 label sheets, and "
                 "stick one on each fixture (or its case) before the load-in.</p><div class='labels'>")  # fmt: skip
        for r in stickers:
            p.append(f"<div class='sticker'><b>{_e(r['label'])}</b><span class='d'>U{r['universe']} · {r['address']}"
                     f"</span> · {_e(r['mode'])}<small>{_e(r['id'])} · {_e(r['model'])}</small>"
                     f"<small>{_e(r['where'])}</small></div>")  # fmt: skip
        p.append("</div></section>")
    p.append("</body></html>")
    return "".join(p)


# ---- the check after hanging -----------------------------------------------------------------------------------
# Every fixture lit on its own, in the sheet's order: the crew sees whether the right one lights at its place. A
# moving head points its beam a known way: out in front of it, a little to its left, down when it hangs and up when
# it stands (CHECK_DIR, in the head's own frame). One that is turned round or mirrored puts its beam somewhere else,
# which the check says in words, and is put right in the app instead of on the ladder: mirrored → pan the other way
# (pan_invert), turned round → its pan home half a turn on. A head with its tilt the wrong way round looks like one
# turned round (the same beam), and the same fix puts it right.

CHECK_DIR = (0.45, 1.0, 0.8)  # to its left, in front of it, down (hanging) or up (standing)
FIXES = ("mirrored", "turned", "both")


def check_dir(fx: dict):
    """Where a moving head points its beam for the check (a unit vector in the world)."""
    import numpy as np

    left, ahead, z = CHECK_DIR
    fx_, fy = _front(fx)
    x, y = fx_ * ahead - fy * left, fy * ahead + fx_ * left  # its front, and its left (the front turned a quarter)
    d = np.array([x, y, -z if geometry.mount_up(fx)[2] < -0.5 else z])
    return d / np.linalg.norm(d)


def front_dir(fx: dict):
    """Straight out to the audience, a little down for a hanging head (a little up for one standing): the rig
    editor's test pose. World-fixed, so a head placed turned or mirrored in the app shows it at once."""
    import numpy as np

    d = np.array([0.0, 1.0, -0.25 if geometry.mount_up(fx)[2] < -0.5 else 0.25])
    return d / np.linalg.norm(d)


def front_aim(fx: dict, defn: dict) -> tuple[float, float]:
    """The pan and tilt (0..1, as DMX) of the front test pose."""
    phi, theta = geometry.ik(fx, defn, front_dir(fx), None)
    return geometry.to_dmx(fx, defn, phi, theta)


def check_aim(fx: dict, defn: dict) -> tuple[float, float]:
    """The check's pan and tilt (0..1, as DMX) for a moving head."""
    phi, theta = geometry.ik(fx, defn, check_dir(fx), None)
    return geometry.to_dmx(fx, defn, phi, theta)


def beam_words(d) -> str:
    return f"{'up' if d[2] > 0 else 'down'} towards {toward(float(d[0]), float(d[1]))}"


def _hung_wrong(fx: dict, what: str) -> dict:
    """The fixture as it really hangs when it is `what` (for saying where its beam goes then)."""
    wrong = {}
    if what in ("turned", "both"):
        wrong["rot_deg"] = fx.get("rot_deg", 0.0) + 180
    if what in ("mirrored", "both"):
        wrong["pan_invert"] = not fx.get("pan_invert", False)
    return {**fx, **wrong}


def check_steps(merged: dict) -> list[dict]:
    """The fixtures in the sheet's order (each truss from its reference end, then the floor), with what the crew
    should see: where it is, which way round, and for a moving head where its beam points, and where it points
    instead when the head is hung wrong (`faults`: the fix for each)."""
    lay = layout(merged)
    rows = [r for st in lay["structures"] for r in st["fixtures"]] + lay["floor"]
    by_id = {f["id"]: f for f in merged.get("fixtures", [])}
    steps = []
    for r in rows:
        f = by_id[r["id"]]
        defn = _defn(f)
        moving = fxlib.is_moving(defn)
        try:
            dark = fxlib.test_refusal(defn) or ""
        except (Exception, SystemExit):  # noqa: BLE001
            dark = "Its definition is missing."
        expect, faults = "", []
        if moving and not dark:
            f = {**f, "mode": _mode(f, defn)}
            aim = check_aim(f, defn)
            expect = f"Its beam points {beam_words(geometry.fk(f, defn, *aim))}."
            pans = bool(defn.get("physical", {}).get("pan_deg"))
            for what in FIXES if pans else ("turned",):  # a moving bar only tilts
                seen = beam_words(geometry.fk(_hung_wrong(f, what), defn, *aim))
                if seen != expect[len("Its beam points ") : -1] and all(x["seen"] != seen for x in faults):
                    faults.append({"fix": what, "seen": seen})
        steps.append({"id": r["id"], "label": r["label"], "model": r["model"], "where": r["where"],
                      "facing": r["facing"], "moving": moving, "expect": expect, "faults": faults, "dark": dark,
                      "dmx": f"U{r['universe']} · {r['address']}"})  # fmt: skip
    return steps


SEEN = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "back": (0.0, -1.0)}  # as the audience sees it (facing the stage)


def fix_front(fx: dict, defn: dict, seen: str) -> dict:
    """The rig editor's test sent the head straight out to the audience (front_aim), and the real beam went `seen`
    instead ("left" / "right" as the audience sees it, or "back" at the stage): the calibration under which that
    pose points where the real beam went, i.e. the head as it really stands. Its pan home a quarter or half a turn
    on (amadeus bringup asked the same), or for "back" without the pan for that its tilt the other way."""
    if seen not in SEEN:
        raise ValueError(f"seen: one of {', '.join(SEEN)}")
    aim = front_aim(fx, defn)
    P, _, ph, _ = geometry._ranges(fx, defn)
    options = [{"pan_home_deg": round(ph + d, 1)} for d in (90, -90, 180, -180) if P and 0 <= ph + d <= P]
    if seen == "back":
        options.append({"tilt_invert": not fx.get("tilt_invert", False)})
    want, best, score = SEEN[seen], None, 0.5  # at least ~60° the right way
    for o in options:
        d = geometry.fk({**fx, **o}, defn, *aim)
        flat = math.hypot(d[0], d[1]) or 1.0
        s = (d[0] * want[0] + d[1] * want[1]) / flat
        if s > score:
            best, score = o, s
    if best is None:
        raise ValueError(
            "No calibration of this head points that way: check it is placed standing or hanging as it really is"
        )
    return best


def fix(fx: dict, defn: dict, what: str) -> dict:
    """The calibration that puts a head right that the check found "mirrored" (its pan the other way), "turned"
    (turned round, or its tilt the wrong way) or "both". Returns the set's fields to change on the fixture."""
    if what not in FIXES:
        raise ValueError(f"fix: one of {', '.join(FIXES)}")
    P, _, ph, _ = geometry._ranges(fx, defn)
    out: dict = {}
    if what in ("mirrored", "both") and P:
        out["pan_invert"] = not fx.get("pan_invert", False)
    if what in ("turned", "both"):
        if P >= 360:  # its pan home half a turn on, whichever way stays in range
            out["pan_home_deg"] = round(ph + 180 if ph + 180 <= P else ph - 180, 1)
        else:  # not enough pan for that (or a moving bar): tilt the other way gives the same beam
            out["tilt_invert"] = not fx.get("tilt_invert", False)
    return out
