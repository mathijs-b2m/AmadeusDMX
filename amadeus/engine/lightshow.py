"""The lightshow program: one track played as a show piece, switched on by hand (the Lightshow switch, Play a
Track as Lightshow, `--director lightshow`). It is the cinematic program (amadeus/engine/cinematic.py: every
hit at its exact time, played by its own fixtures), turned all the way up:

- **every light gets its turn**: the rig is played in **families**, one per fixture model however many trusses
  it hangs on (all the PARs, all the Auras…), each split into a few blocks left to right for its gestures; a rig
  of one or two models splits them into interleaved halves or thirds, so it has groups to vary too. Every family
  gets an instrument of the music (booms on the floor lights, cymbals on the beams…; with more
  families than instruments, an instrument gets several, and they play it together);
- **a build-up**: one family starts with every hit, and every loud phrase brings the next one in
  (amadeus/director/lightshow.py, `layers`). A quiet part takes families away. An instrument whose family isn't
  playing is played by one that is;
- **layers and turns**: a phrase is played in **passages** of a few bars with a line-up of their own. It starts
  with half of the families it may use and adds a layer per passage; when it can't add any, another part of
  the families takes over, keeping some of the ones before. The whole rig plays only at the climaxes: a drop
  hits with all of it, thins out and builds back to it;
- **flashing**: hits are short and hard (hit, a short hold, a quick release), at full level. Strong hits are
  played by every family of the line-up at once, white, with the strobes, and while the whole rig plays the
  strobes hit every kick and snare as well; the snare rolls into the drops flash on their hits. The impacts hit
  the strobes, the lasers and the line-up, and the whole rig when it plays or a phrase starts on them. A busy
  family's hit goes to another family instead of being left out. The line-up glows between the hits (ramped,
  and dark in silences), in a quiet phrase only one family of it; whoever isn't in the line-up stays dark;
- **heads in pictures that fit the room**: the heads change picture at the phrases and, as it builds, every
  two bars, then every bar. Every picture is checked from where each head hangs: a head the ceiling or the
  back-wall guard would have to bend takes a picture that works from its place, and a picture most heads
  can't do is left out (a cathedral of beams under a low ceiling, beams back over the stage from a stage truss).

Flashes stay within the set's limits: a fixture is hit at most `max_flash_hz` times a second (faster only with
allow_fast_strobe, never with strobe_free), the strobes too.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from amadeus.director.lightshow import CLIMAX, NAME, layers, passages, ranks
from amadeus.engine.cinematic import (
    BEAM_DEG,
    BIG_HIT,
    BIG_TRIM,
    GRID_HZ,
    MELODY_SEGMENTS,
    PRE_IMPACT_S,
    ROLES,
    SMALL,
    WHITE,
    CinematicMixin,
)
from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry

LEVELS = (0.7, 0.85, 1.0)  # a hit goes straight to one of these
BLOCKS = 8  # a family is played in at most this many blocks, left to right
MIN_FAMILIES = 3  # a rig of fewer models than this splits them, interleaved: three groups to vary at least
PASSAGE_BARS = 4  # the line-up changes every this many bars
OPENS_S = 1.0  # an impact this close to a phrase's start hits the whole rig, whatever the line-up
MOTIF_GAP_S = 0.5  # a pause this long ends a motif; the next one answers
TOGETHER_FROM = 0.5  # from this loud a phrase (its rank) an instrument's families play every hit together
STRONG = 0.7  # hits this strong are played by every family that plays, white, with the strobes
SPECIALS_FROM = 0.34  # the build this far: the strobes on the strong hits, impacts on the whole rig, lasers…
DRUM_HIT = 0.35  # …and while the whole rig plays, the strobes on every kick and snare this strong too
HOLD_S = (0.12, 0.45)  # a hit is held for half the time until its instrument plays again, within this…
RELEASE_S = 0.2  # …and let go this fast (the booms: twice as slow)
FAST_HZ = 10.0  # with allow_fast_strobe, a fixture may be hit this often
BED = (0.15, 0.45)  # the glow between hits: at the start of the build, and at its top
BED_RAMP_S = 0.6
BED_QUIET = 0.25  # the bars quieter than this (breath) let the glow go: silences stay dark
MOVE_BARS = ((0.99, 1), (0.5, 2))  # the build this far: the heads change pictures every this many bars
MIN_MOVE_S = 1.5  # but not more often than this
FIT_DEG = 15.0  # a picture the room's guards bend more than this for a head doesn't fit it
FIT_SHARE = 0.5  # a picture that fits fewer heads than this is left out
SWAY = (
    (0.0, 0.0),
    (-14.0, 8.0),
    (14.0, 8.0),
)  # where the heads drift around a picture (cinematic.py): it fits there too
CEILING_NEAR_M = 20.0  # a beam on the ceiling closer than this doesn't fit either (beams stay off the ceiling)
DUCK_DEPTH = 0.3  # the powerful lights step down less for the small ones' accents than in the cinematic program…
OWN_ATTACK_S = 0.3  # …and only after their own hit has been held a moment (not a blip)


def snap(v: float) -> float:
    return min(LEVELS, key=lambda s: abs(s - v))


class LightshowMixin(CinematicMixin):
    """Mixed into the Engine before the cinematic program; active when the plan comes from the lightshow
    director (and the analysis has hits). For any other program every method is the cinematic one."""

    def _init_cinematic(self, rig: dict):
        if self.program == NAME:
            self.ls_ranks = ranks(self.a)
            self.duck_depth, self.own_attack_s = DUCK_DEPTH, OWN_ATTACK_S
            safety = rig["safety"]
            hz = 0.0 if safety.get("strobe_free") else float(safety.get("max_flash_hz", 4.0))
            if safety.get("allow_fast_strobe") and not safety.get("strobe_free"):
                hz = max(hz, FAST_HZ)
            self.ls_hz = hz
            self.ls_retrigger = 1.0 / hz if hz > 0 else 0.5
        super()._init_cinematic(rig)
        if self.program == NAME:
            self._ls_bed()

    # ---------------------------------------------------------------- the families

    def _cine_sections(self, rig: dict) -> list[dict]:
        """One family per fixture model, its fixtures in a few blocks left to right (each block a unit). With
        fewer models than MIN_FAMILIES, a model is split into interleaved families, each across the whole rig."""
        if self.program != NAME:
            return super()._cine_sections(rig)
        by_fixture: dict[str, list[dict]] = {}
        for e in rig["elements"]:
            if e["kind"] not in ("laser", "strobe", "blinder", "smoke", "inert") and not e.get("uplight"):
                by_fixture.setdefault(e["fixture"], []).append(e)
        models: dict[str, list[dict]] = {}
        for f in rig["fixtures"]:
            if f["id"] in by_fixture:
                models.setdefault(f["fixture"], []).append(f)
        sections = []
        split = math.ceil(MIN_FAMILIES / max(len(models), 1))
        groups = []
        for model, fs in models.items():
            fs = sorted(fs, key=lambda f: np.mean([e["x"] for e in by_fixture[f["id"]]]))
            parts = min(split, len(fs))
            groups += [(model, fs[p::parts]) for p in range(parts)]
        for model, fs in groups:
            blocks = np.array_split(np.arange(len(fs)), min(BLOCKS, len(fs)))
            units = [
                [e["id"] for k in b for e in sorted(by_fixture[fs[k]["id"]], key=lambda e: e["x"])] for b in blocks
            ]
            cells = sorted([e for f in fs for e in by_fixture[f["id"]]], key=lambda e: e["x"])
            n_seg = min(MELODY_SEGMENTS, len(cells))
            segments = [[e["id"] for e in part] for part in np.array_split(np.array(cells, dtype=object), n_seg)]
            phys = fxlib.get(model).get("physical", {})
            kind = by_fixture[fs[0]["id"]][0]["kind"]
            sections.append({
                "name": model.split("/")[-1],
                "units": units,
                "segments": segments,
                "kind": kind,
                "pixel": len(cells) > len(fs),
                "floor": float(np.mean([f.get("z_m", 1.0) for f in fs])) < 1.2 and kind != "head",
                "beam": kind == "head" and float(phys.get("beam_deg") or 25) <= BEAM_DEG,
                "big": max(self.cine_power.get(i, 0.0) for u in units for i in u) >= SMALL,
            })  # fmt: skip
        return sections

    def _ls_seats(self):
        """Every instrument's families (each family plays one), and the order the families join in: the
        instruments the opening plays most first, then the rest (the powerful ones last)."""
        secs, n = self.cine_sections, len(self.cine_sections)
        seat_of: dict[int, str] = {}
        for role in ("low", "cymbal", "mid", "tick"):  # every instrument one family first…
            free = sorted((s for s in range(n) if s not in seat_of), key=lambda s: -self._suits(secs[s], role))
            if free:
                seat_of[free[0]] = role
        for s in range(n):  # …then every other family the instrument it suits best
            if s not in seat_of:
                seat_of[s] = max(ROLES, key=lambda r: self._suits(secs[s], r))
        self.ls_seats = {r: [s for s in range(n) if seat_of[s] == r] for r in ROLES}
        h = self.cine_hits
        opening = self.plan[min(2, len(self.plan) - 1)].end if self.plan else self.a.duration
        count = {r: 0 for r in ROLES}
        for t, v in zip(h.t, h.voice):
            if t < opening:
                count[self._role_of(int(v))] += 1
        first = [self.ls_seats[r][0] for r in sorted(ROLES, key=lambda r: -count[r]) if self.ls_seats[r]]
        rest = sorted(set(range(n)) - set(first), key=lambda s: (secs[s]["big"], -len(secs[s]["units"])))
        self.ls_order = first + rest
        self.ls_layers = layers(self.a, n)

    def _orchestrate(self, i: int) -> dict:
        """Phrase i's score with every family it may use; `_ls_passages` plays it in line-ups of those."""
        if self.program != NAME:
            return super()._orchestrate(i)
        if not hasattr(self, "ls_order"):
            self._ls_seats()
        k = self.ls_layers[min(i, len(self.ls_layers) - 1)] if self.ls_layers else len(self.cine_sections)
        return self._ls_score(i, self.ls_order[:k], k)

    def _ls_score(self, i: int, active: list[int], top: int) -> dict:
        """The score of a line-up in phrase i, `top` families being what the phrase may use."""
        n = len(self.cine_sections)
        rank = float(self.ls_ranks[min(i, len(self.ls_ranks) - 1)]) if len(self.ls_ranks) else 0.5
        secs = self.cine_sections
        parts: dict[str, list[tuple[int, str]]] = {}
        for r, role in enumerate(ROLES):
            seated = [s for s in self.ls_seats.get(role, []) if s in active]
            if not seated and active:  # not in yet: played by a family that is
                seated = [active[r % len(active)]]
            parts[role] = [(s, self._gesture(secs[s], role, i + 3 * r + q)) for q, s in enumerate(seated)]
        melody = max(active, key=lambda s: self._suits(secs[s], "melody"), default=None)
        pads = sorted((s for s in active if s != melody), key=lambda s: -self._suits(secs[s], "pad"))
        return {"parts": parts, "small": [s for s in active if not secs[s]["big"]], "melody": melody,
                "pad": pads[0] if pads else None, "rank": rank, "active": active, "full": len(active) >= n,
                "build": (top - 1) / (n - 1) if n > 1 else 1.0}  # fmt: skip

    def _ls_passages(self):
        """The line-ups: every PASSAGE_BARS bars of a phrase a score of its own. A passage with more families
        than the one before it in the phrase keeps those and adds to them (a layer); otherwise the line-up moves
        on through the families that have joined, by half of itself: some stay, the others take over."""
        bars = np.asarray(self.downbeat_times, float)
        self.ls_times: list[float] = []
        self.ls_scores: list[dict] = []
        joined = turn = before = 0
        for i, d in enumerate(self.plan):
            phrase = self.cine_score[min(i, len(self.cine_score) - 1)]
            top = len(phrase["active"])
            joined = max(joined, top)
            pool = self.ls_order[:joined]
            inside = bars[(bars > d.start + 1e-3) & (bars < d.end)]
            starts = [d.start, *(float(b) for b in inside[PASSAGE_BARS - 1 :: PASSAGE_BARS])]
            climax = phrase["rank"] >= CLIMAX
            opens = climax and d.section == "drop" and (i == 0 or self.plan[i - 1].section != "drop")
            for j, (t, k) in enumerate(zip(starts, passages(top, len(starts), climax, opens))):
                if not pool:
                    self.ls_times.append(t)
                    self.ls_scores.append(phrase)
                    continue
                if not (j and k > before):
                    turn += max(1, k // 2)
                before = k
                self.ls_times.append(t)
                self.ls_scores.append(self._ls_score(i, [pool[(turn + q) % len(pool)] for q in range(k)], top))

    def _score_at(self, t: float, i: int) -> dict:
        if self.program != NAME:
            return super()._score_at(t, i)
        return self.ls_scores[max(bisect.bisect_right(self.ls_times, t) - 1, 0)]

    def _floor_now(self, score: dict) -> set:
        """The low glow: only on the floor lights of the line-up."""
        if self.program != NAME:
            return super()._floor_now(score)
        playing = {eid for si in score["active"] for u in self.cine_sections[si]["units"] for eid in u}
        return self.cine_floor & playing

    # ---------------------------------------------------------------- the hits

    def _cine_events(self):
        """Every hit → which blocks flash, how bright, in what colour (see the module's description)."""
        if self.program != NAME:
            return super()._cine_events()
        self._ls_passages()
        h = self.cine_hits
        events: dict[str, list[tuple]] = {}
        last_hit: dict[str, float] = {}
        gap = self.ls_retrigger

        def free(ids, t):
            return all(t - last_hit.get(eid, -1e9) >= gap for eid in ids)

        def play(ids, t, level, hold, fade, colour, impact=False):
            for eid in ids:
                last_hit[eid] = t
                lv = 1.0 if impact else snap(level * (1 - BIG_TRIM * self.cine_power.get(eid, 0.0)))
                events.setdefault(eid, []).append((t, lv, hold, fade, colour, impact))

        motif = {r: [-1e9, -1, 0] for r in ROLES}
        last_strobe = -1e9
        self.cine_played = []
        members = [[i for u in s["units"] for i in u] for s in self.cine_sections]
        next_same = np.full(len(h), 1.0)
        last_of: dict[int, int] = {}
        for k in range(len(h) - 1, -1, -1):
            v = int(h.voice[k])
            if v in last_of:
                next_same[k] = float(h.t[last_of[v]] - h.t[k])
            last_of[v] = k

        def strobe(t):
            nonlocal last_strobe
            if self.ls_hz > 0 and t - last_strobe >= 1.0 / self.ls_hz:
                last_strobe = t
                for eid in self.cine_strobes:
                    events.setdefault(eid, []).append((t, 1.0, 0.05, 0.0, WHITE, True))

        for k in range(len(h)):
            t, s, voice = float(h.t[k]), float(h.strength[k]), int(h.voice[k])
            i, d = self.decision_at(t)
            cols = self._colours(d)
            score = self._score_at(t, i)
            specials = score["build"] >= SPECIALS_FROM
            if h.impact[k]:
                whole = specials and (score["full"] or t - d.start < OPENS_S)
                pool = range(len(members)) if whole else score["active"]
                ids = [eid for si in pool for eid in members[si] if free([eid], t)]
                play(ids, t, 1.0, 0.25, 0.5, WHITE if specials else cols[2 % len(cols)], impact=True)
                if specials:
                    strobe(t)
                    for eid in self.cine_lasers:
                        if free([eid], t):
                            last_hit[eid] = t
                            events.setdefault(eid, []).append((t, 1.0, 0.6, 0.0, cols[0], True))
                self.cine_played.append((t, 1.0))
                continue
            role = self._role_of(voice)
            seated = score["parts"][role]
            if not seated:
                continue
            last, m, step = motif[role]
            if t - last > MOTIF_GAP_S:
                m, step = m + 1, 0
            motif[role] = [t, m, step + 1]
            if score["full"] and role in ("low", "mid") and s >= DRUM_HIT:
                strobe(t)  # the whole rig in: the strobes play the drums
            sounds = max(float(h.decay[k]), float(next_same[k]))
            hold = float(np.clip(0.5 * sounds, *HOLD_S))
            fade = RELEASE_S * (2 if role == "low" else 1)
            if s >= STRONG:  # every family that plays, at once, white
                ids = [eid for si in score["active"] for eid in members[si] if free([eid], t)]
                if ids:
                    play(ids, t, 1.0, hold, fade, WHITE if specials else cols[1 % len(cols)])
                    self.cine_played.append((t, 1.0))
                if specials:
                    strobe(t)
                continue
            # the instrument's families: together when the music is loud, else taking turns motif by motif
            playing = seated if score["rank"] >= TOGETHER_FROM else [seated[m % len(seated)]]
            if s < BIG_HIT and score["small"]:  # a weak hit: the powerful families leave it to the small ones
                playing = [x for x in playing if not self.cine_sections[x[0]]["big"]] or [
                    (score["small"][m % len(score["small"])], "chase")
                ]
            spill = [(si, "chase") for si in score["active"] if si not in {x[0] for x in playing}]
            level = s**0.3
            any_played = False
            for q, (si, gesture) in enumerate(playing + spill):
                if any_played and q >= len(playing):
                    break
                sec = self.cine_sections[si]
                colour = cols[(ROLES.index(role) + q) % len(cols)]
                g = gesture if sec["pixel"] or gesture not in ("steps", "keys") else "chase"
                pool = sec["segments"] if g in ("steps", "keys") else sec["units"]
                for option in self._members(sec, g, step, m, float(h.pitch[k])):
                    ids = [eid for o in option for eid in pool[o]]
                    if ids and free(ids, t):
                        play(ids, t, level, hold, fade, colour)
                        any_played = True
                        break
            if any_played:
                self.cine_played.append((t, level))
        self.cine_events = {eid: (np.array([e[0] for e in ev]), ev) for eid, ev in events.items()}
        self._ls_moves()

    def _ls_moves(self):
        """When the heads change pictures: impacts (moved to in the dark), phrase starts, and as it builds every
        few bars, on the bar line (moved to while lit)."""
        h = self.cine_hits
        impacts = sorted(float(t) for t in h.t[h.impact])
        self.ls_dark = np.array([m for k, m in enumerate(impacts) if k == 0 or m - impacts[k - 1] > 2.0])
        moves = set(impacts) | {d.start for d in self.plan[1:]}
        bars = np.asarray(self.downbeat_times, float)
        for i, d in enumerate(self.plan):
            build = self.cine_score[min(i, len(self.cine_score) - 1)]["build"]
            every = next((n for at, n in MOVE_BARS if build >= at), 0)
            if every:
                inside = bars[(bars >= d.start) & (bars < d.end)]
                moves |= {float(b) for b in inside[every::every]}
        kept: list[float] = []
        for m in sorted(moves):
            if not kept or m - kept[-1] >= MIN_MOVE_S:
                kept.append(m)
        self.cine_moves = np.array(kept)

    def _pre_move(self, t: float) -> bool:
        if self.program != NAME:
            return super()._pre_move(t)
        q = bisect.bisect_right(self.ls_dark, t)  # only the impacts are moved to in the dark
        return q < len(self.ls_dark) and self.ls_dark[q] - t < PRE_IMPACT_S

    # ---------------------------------------------------------------- the heads: pictures that fit the room

    def _cine_pictures(self):
        super()._cine_pictures()
        if self.program != NAME or not self.heads:
            return
        n = len(self.heads)
        centre = np.mean([p[0] for p in self.head_pos])
        span = max(np.ptp([p[0] for p in self.head_pos]) / 2, 0.5)
        side = [float(np.clip((p[0] - centre) / span, -1, 1)) for p in self.head_pos]
        alt = [1.0 if j % 2 else -1.0 for j in range(n)]
        candidates = list(self.cine_pictures) + [
            [(s_ * 25, -15.0) for s_ in side],  # a V into the crowd
            [(a_ * 22, -28.0) for a_ in alt],  # crossing, odds against evens
            [(-s_ * 15, -45.0) for s_ in side],  # steep, crossing in front
            [(0.0, -20.0)] * n,  # all straight out, onto the crowd
        ]
        always = [(s_ * 35, -35.0) for s_ in side]  # down onto the floor ahead: fits any head
        fitted = []
        for pic in candidates:
            good = [all(self._ls_fits(j, az + daz, el + del_) for daz, del_ in SWAY) for j, (az, el) in enumerate(pic)]
            if np.mean(good) < FIT_SHARE:
                continue  # most heads can't do it here
            fitted.append([p if ok else always[j] for j, (p, ok) in enumerate(zip(pic, good))])
        self.cine_pictures = fitted or [always]

    def _ls_fits(self, j: int, az: float, el: float) -> bool:
        """Whether head j can play this direction as it is: the room's guards don't bend it much, and it doesn't
        light the ceiling close by."""
        want = self._direction_v(np.array([az]), np.array([el]))
        got = self._room_safe_v(want, j)
        if self.zones.heads:
            got = self.zones.filter(self.head_pos[j], got)
        bent = math.degrees(math.acos(float(np.clip(want[0] @ got[0], -1, 1))))
        if bent > FIT_DEG:
            return False
        _, length, surface = geometry.beam_end(self.head_pos[j], got[0], self.stage, max_len=40.0)
        return not (surface == "ceiling" and length < CEILING_NEAR_M)

    # ---------------------------------------------------------------- the glow between the hits

    def _ls_bed(self):
        """Per family, its glow over time: while it is in the line-up, at the build's level, ramped in and out.
        In a quiet phrase only the family that holds the line-up together glows (its pad, or its melody alone)."""
        grid = self._grid()
        bars = np.interp(grid, np.arange(len(self.breath)) / self.a.fps, self.breath)
        gate = np.clip(bars / BED_QUIET, 0, 1)
        step = 1 / (BED_RAMP_S * GRID_HZ)
        self.ls_beds = []
        for si in range(len(self.cine_sections)):
            want = np.zeros(len(grid))
            for q, score in enumerate(self.ls_scores):
                holds = score["melody"] if score["pad"] is None else score["pad"]
                if si == holds or (si in score["active"] and score["rank"] >= TOGETHER_FROM):
                    a = int(self.ls_times[q] * GRID_HZ)
                    b = int(self.ls_times[q + 1] * GRID_HZ) if q + 1 < len(self.ls_times) else len(grid)
                    want[a:b] = BED[0] + (BED[1] - BED[0]) * score["build"]
            y, out = 0.0, np.zeros(len(grid))
            for k, v in enumerate(want):  # a slow ramp: never wobbling with the music
                y += float(np.clip(v - y, -step * BED[1], step * BED[1]))
                out[k] = y
            self.ls_beds.append(out * gate)

    def _cinematic_scene(self, t: float):
        out = super()._cinematic_scene(t)
        if self.program != NAME:
            return out
        i, d = self.decision_at(t)
        base = self._colours(d)[0]
        dark = self._pre_move(t)
        for si, sec in enumerate(self.cine_sections):
            bed = self._at(self.ls_beds[si], t)
            if bed <= 0.01:
                continue
            for u in sec["units"]:
                for eid in u:
                    s = out.get(eid)
                    if s is None or (dark and eid in self.cine_heads):
                        continue
                    if s.dimmer < bed:  # (not ducked under the small ones' accents: it would chop)
                        s.dimmer, s.r, s.g, s.b = bed, *base
        self._roll(t, out)  # a snare roll into a drop: flashes on its hits
        return out
