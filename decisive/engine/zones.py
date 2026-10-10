"""Zones: where beams may (not) go. Drawn in the rig editor, stored in the set as `zones`.

    avoid      artistic: moving-head beams stay off it (a wall, the set, the LED wall, a VIP corner).
               A beam that would land on it slides to its nearest edge (plus `margin_deg`); a head whose
               beam crosses it on the way between two positions goes dark (like blackout-by-movement).
    keep_in    artistic: moving-head beams land only inside it; outside, they are pulled back to its edge.
    laser_out  safety: no laser beam may enter it, `margin_deg` included (see laser_guard in engine.py).
               A software guard on top of the laser's masking plate, scan safety and E-stop: never instead.

A zone is a rectangle (`size` [width, height], turned by `rot_deg`, tilted back by `tilt_deg`: 0 = upright
facing the audience, 90 = flat) or a box (`size` [width, depth, height], turned by `rot_deg`).
Same maths as mac/Sources/DecisiveKit/RigModel.swift (Zone).
"""

from __future__ import annotations

import math

import numpy as np

from decisive.rig import geometry


class Zone:
    def __init__(self, z: dict):
        self.id, self.name = z["id"], z.get("name", z["id"])
        self.kind, self.shape = z.get("kind", "avoid"), z.get("shape", "rect")
        self.c = np.array(z.get("center", [0, 0, 2]), dtype=float)
        size = list(z.get("size", [2, 2, 2])) + [1.0, 1.0, 1.0]
        self.margin = math.radians(float(z.get("margin_deg", 5 if self.kind == "laser_out" else 2)))
        r, t = math.radians(z.get("rot_deg", 0.0)), math.radians(z.get("tilt_deg", 0.0))
        self.u = np.array([math.cos(r), math.sin(r), 0.0])
        if self.shape == "box":
            self.v, self.n = np.array([-math.sin(r), math.cos(r), 0.0]), np.array([0.0, 0.0, 1.0])
            self.half = np.array(size[:3], dtype=float) / 2
        else:
            facing = np.array([-math.sin(r), math.cos(r), 0.0])
            self.n = facing * math.cos(t) + np.array([0.0, 0.0, 1.0]) * math.sin(t)
            self.v = np.array([0.0, 0.0, 1.0]) * math.cos(t) - facing * math.sin(t)
            self.half = np.array([size[0] / 2, size[1] / 2, 0.0])
        self.applies = z.get("applies", "auto")

    def faces(self) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
        """(centre, axis a, axis b, normal) per flat face, with half sizes in `self` order."""
        if self.shape != "box":
            return [(self.c, self.u * self.half[0], self.v * self.half[1], self.n)]
        U, V, N = self.u * self.half[0], self.v * self.half[1], self.n * self.half[2]
        return (
            [(self.c + s * N, U, V, s * self.n) for s in (-1, 1)]
            + [(self.c + s * V, U, N, s * self.v) for s in (-1, 1)]
            + [(self.c + s * U, V, N, s * self.u) for s in (-1, 1)]
        )

    def hit(self, o: np.ndarray, d: np.ndarray, grow=0.0) -> np.ndarray:
        """Distance along each ray (rows of d, shape (M, 3)) to where it enters the zone; inf = misses.
        `grow`: metres added around the zone (per ray, e.g. the margin at that distance)."""
        o = np.broadcast_to(np.asarray(o, dtype=float), d.shape)
        g = np.broadcast_to(np.asarray(grow, dtype=float), (len(d),))
        if self.shape == "box":
            p = o - self.c
            lo = np.stack([p @ self.u, p @ self.v, p @ self.n], axis=1)
            dd = np.stack([d @ self.u, d @ self.v, d @ self.n], axis=1)
            half = self.half[None, :] + g[:, None]
            with np.errstate(divide="ignore", invalid="ignore"):
                a = (-half - lo) / dd
                b = (half - lo) / dd
            par = np.abs(dd) < 1e-12
            inside = np.abs(lo) <= half
            a = np.where(par, np.where(inside, -np.inf, np.inf), a)
            b = np.where(par, np.where(inside, np.inf, -np.inf), b)
            t0 = np.minimum(a, b).max(axis=1)
            t1 = np.maximum(a, b).min(axis=1)
            ok = (t0 <= t1) & (t1 >= 0)
            return np.where(ok, np.maximum(t0, 0.0), np.inf)
        den = d @ self.n
        with np.errstate(divide="ignore", invalid="ignore"):
            t = ((self.c - o) * self.n).sum(axis=1) / den
        q = o + d * t[:, None] - self.c
        ok = (
            (np.abs(den) > 1e-12)
            & (t > 0)
            & (np.abs(q @ self.u) <= self.half[0] + g)
            & (np.abs(q @ self.v) <= self.half[1] + g)
        )
        return np.where(ok, t, np.inf)


def room_length(pos: np.ndarray, d: np.ndarray, st: dict) -> np.ndarray:
    """How far each beam travels before a room surface (floor, ceiling, the far walls), at most 40 m."""
    W, depth, ceil = st["width_m"], st.get("room_depth_m", 6.0), st["ceiling_m"]
    t = np.full(len(d), 40.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        for k, lim_lo, lim_hi in ((2, 0.0, ceil), (1, -40.0, depth), (0, -2.0, W + 2.0)):
            lo = (lim_lo - pos[k]) / d[:, k]
            hi = (lim_hi - pos[k]) / d[:, k]
            for cand in (lo, hi):
                t = np.where((cand > 1e-6) & (cand < t), cand, t)
    return t


def room_length_many(pos: np.ndarray, d: np.ndarray, st: dict) -> np.ndarray:
    """room_length for many beams, each from its own position (pos (N, 3))."""
    W, depth, ceil = st["width_m"], st.get("room_depth_m", 6.0), st["ceiling_m"]
    t = np.full(len(d), 40.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        for k, lim_lo, lim_hi in ((2, 0.0, ceil), (1, -40.0, depth), (0, -2.0, W + 2.0)):
            for lim in (lim_lo, lim_hi):
                cand = (lim - pos[:, k]) / d[:, k]
                t = np.where((cand > 1e-6) & (cand < t), cand, t)
    return t


class Zones:
    def __init__(self, rig: dict):
        zs = [Zone(z) for z in rig.get("zones", []) if z.get("enabled", True)]
        self.avoid = [z for z in zs if z.kind == "avoid" and z.applies in ("auto", "heads", "all")]
        self.keep_in = [z for z in zs if z.kind == "keep_in" and z.applies in ("auto", "heads", "all")]
        self.laser_out = [z for z in zs if z.kind == "laser_out"]
        self.stage = geometry.stage(rig)
        # rectangles as arrays, to test many beams against all of them at once (the motor model's hot path)
        rects = [z for z in self.avoid if z.shape != "box"]
        self._boxes = [z for z in self.avoid if z.shape == "box"]
        if rects:
            self._rc = np.array([z.c for z in rects])
            self._ru = np.array([z.u for z in rects])
            self._rv = np.array([z.v for z in rects])
            self._rn = np.array([z.n for z in rects])
            self._rh = np.array([z.half[:2] for z in rects])
            self._rm = np.array([math.tan(z.margin) for z in rects])
        else:
            self._rc = None

    @property
    def heads(self) -> bool:
        return bool(self.avoid or self.keep_in)

    # ---------------------------------------------------------------- moving heads

    def _inside(self, z: Zone, pos, d) -> np.ndarray:
        """Does each beam land inside keep-in zone z?"""
        land = pos + d * room_length(pos, d, self.stage)[:, None]
        q = land - z.c
        loc = np.stack([q @ z.u, q @ z.v, q @ z.n], axis=1)
        return (np.abs(loc) <= z.half + 1e-6).all(axis=1)

    def _clear(self, pos, d) -> np.ndarray:
        """Beams that miss every avoid zone (before they reach a room surface)."""
        L = room_length(pos, d, self.stage)
        ok = np.ones(len(d), dtype=bool)
        for z in self.avoid:
            ok &= ~(z.hit(pos, d) < L)
        return ok

    def filter(self, pos, d: np.ndarray) -> np.ndarray:
        """Target directions (M, 3) for a head at `pos`: into keep-in zones, off avoid zones."""
        if not self.heads:
            return d
        pos = np.asarray(pos, dtype=float)
        d = np.array(d, dtype=float, copy=True)
        for z in self.keep_in:
            out = ~self._inside(z, pos, d)
            if not out.any():
                continue
            # a point surely inside: the zone's centre on the floor if it reaches the floor, else its centre
            safe_pt = z.c.copy()
            if z.c[2] - z.half[2] <= 0.05:
                safe_pt[2] = 0.02
            safe = safe_pt - pos
            safe /= np.linalg.norm(safe)
            d0 = d[out]
            lo, hi = np.zeros(len(d0)), np.ones(len(d0))
            for _ in range(14):  # the least turn towards the safe point that lands inside
                mid = (lo + hi) / 2
                cand = d0 * (1 - mid[:, None]) + safe * mid[:, None]
                cand /= np.linalg.norm(cand, axis=1, keepdims=True)
                ins = self._inside(z, pos, cand)
                hi, lo = np.where(ins, mid, hi), np.where(ins, lo, mid)
            cand = d0 * (1 - hi[:, None]) + safe * hi[:, None]
            d[out] = cand / np.linalg.norm(cand, axis=1, keepdims=True)
        for _ in range(3):  # avoid zones: off over the nearest edge that really clears (a push can meet the next)
            blocked = ~self._clear(pos, d)
            if not blocked.any():
                break
            for z in self.avoid:
                idx = np.flatnonzero(blocked & (z.hit(pos, d) < room_length(pos, d, self.stage)))
                if not len(idx):
                    continue
                dz = d[idx]
                best_d, best_turn = dz.copy(), np.full(len(idx), np.inf)
                fallback, fb_turn = dz.copy(), np.full(len(idx), np.inf)
                for c, A, B, N in z.faces():
                    den = dz @ N
                    with np.errstate(divide="ignore", invalid="ignore"):
                        tf = ((c - pos) @ N) / den
                    q = pos + dz * tf[:, None] - c
                    a2, b2 = A @ A, B @ B
                    sa, sb = (q @ A) / a2, (q @ B) / b2
                    on = (tf > 0) & (np.abs(sa) <= 1 + 1e-6) & (np.abs(sb) <= 1 + 1e-6)
                    if not on.any():
                        continue
                    m = np.where(on, tf, 0) * math.tan(z.margin)
                    la, lb = math.sqrt(a2), math.sqrt(b2)
                    for ka, kb in ((1, None), (-1, None), (None, 1), (None, -1)):  # the four edges
                        na = np.full(len(idx), ka * (1 + 0.0)) if ka is not None else sa
                        nb = np.full(len(idx), kb * (1 + 0.0)) if kb is not None else sb
                        if ka is not None:
                            na = ka * (1 + m / la)
                        else:
                            nb = kb * (1 + m / lb)
                        tgt = c + A * na[:, None] + B * nb[:, None]
                        nd = tgt - pos
                        nd /= np.linalg.norm(nd, axis=1, keepdims=True)
                        turn = np.arccos(np.clip((nd * dz).sum(1), -1, 1))
                        good = on & self._clear(pos, nd)
                        better = good & (turn < best_turn)
                        best_d[better], best_turn[better] = nd[better], turn[better]
                        fb = on & (turn < fb_turn)
                        fallback[fb], fb_turn[fb] = nd[fb], turn[fb]
                solved = np.isfinite(best_turn)
                d[idx] = np.where(solved[:, None], best_d, fallback)
        return d

    def blocked(self, pos: np.ndarray, d: np.ndarray) -> np.ndarray:
        """For many heads at once (pos (N, 3), d (N, 3)): would this beam come into an avoid zone, its margin
        included? The motor model treats that as a physical stop: the head never points there."""
        if not self.avoid:
            return np.zeros(len(d), dtype=bool)
        L = room_length_many(pos, d, self.stage)
        out = np.zeros(len(d), dtype=bool)
        if self._rc is not None:  # every rectangle at once: (beams, zones)
            rel = self._rc[None, :, :] - pos[:, None, :]  # (M, Z, 3)
            den = d @ self._rn.T  # (M, Z)
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (rel * self._rn[None]).sum(-1) / den
            with np.errstate(invalid="ignore"):  # a beam parallel to a rectangle: inf × 0
                q = d[:, None, :] * t[..., None] - rel  # hit point relative to each centre
                g = np.linalg.norm(rel, axis=-1) * self._rm[None]  # the margin, as metres there
                a = np.abs((q * self._ru[None]).sum(-1))
                b = np.abs((q * self._rv[None]).sum(-1))
                hit = (
                    (np.abs(den) > 1e-12)
                    & (t > 0)
                    & (t < L[:, None])
                    & (a <= self._rh[None, :, 0] + g)
                    & (b <= self._rh[None, :, 1] + g)
                )
            out |= hit.any(axis=1)
        for z in self._boxes:
            dist = np.linalg.norm(z.c - pos, axis=1)
            out |= z.hit(pos, d, grow=dist * math.tan(z.margin)) < L
        return out

    def crossing(self, pos, d: np.ndarray) -> np.ndarray:
        """True where a head's actual beam hits an avoid zone (it goes dark while crossing)."""
        if not self.avoid:
            return np.zeros(len(d), dtype=bool)
        L = room_length(np.asarray(pos, dtype=float), d, self.stage)
        hit = np.zeros(len(d), dtype=bool)
        for z in self.avoid:
            hit |= z.hit(pos, d) < L
        return hit

    # ---------------------------------------------------------------- lasers

    def laser_violation(self, pos, dirs: np.ndarray, extra_margin_deg: float = 0.0) -> str | None:
        """The first laser_out zone any beam (or its margin cone) would enter, else None."""
        if not self.laser_out or not len(dirs):
            return None
        pos = np.asarray(pos, dtype=float)
        for z in self.laser_out:
            m = z.margin + math.radians(extra_margin_deg)
            rays = [dirs]
            # the margin: each beam also tilted by m up, down and sideways (the worst case of the model's error)
            up = np.array([0.0, 0.0, 1.0])
            side = np.cross(dirs, up)
            side /= np.linalg.norm(side, axis=1, keepdims=True) + 1e-9
            vert = np.cross(side, dirs)
            for w in (side, -side, vert, -vert):
                r = dirs * math.cos(m) + w * math.sin(m)
                rays.append(r / np.linalg.norm(r, axis=1, keepdims=True))
            R = np.concatenate(rays)
            if np.isfinite(z.hit(pos, R)).any() and (z.hit(pos, R) < room_length(pos, R, self.stage)).any():
                return z.name
        return None
