"""The lightshow program: one track played as a show piece, switched on by hand (the night card's Lightshow,
`--director lightshow`). It is the cinematic program (amadeus/engine/cinematic.py: every hit at its exact time,
played as a note by its own fixtures) with three things of its own:

- **a build-up**: the track starts with one section of lights playing every hit, and every phrase with the
  music for it brings one more section in (amadeus/director/lightshow.py, `layers`), until the whole rig plays
  at the climax. A quiet part takes layers away again; the heads change pictures more often as it builds (at
  phrase starts, then every four bars, at the climax every two), and the strobes and lasers are kept for the
  impacts once the build is far enough;
- **a layered symphony**: every voice of the music has a seat, a section of its own for the whole track
  (booms on the floor lights and blinders, cymbals on the beams, ticks on the pixels…). A voice whose section
  hasn't joined yet is played by one that has, so the first section plays the whole song alone, and every
  section that joins takes its own instrument over. Call and response, tutti on the strong hits and the
  brass are as in the cinematic program, among the sections that play;
- **intense, and every hit played**: hits land brighter, a hit that finds its section's fixtures still busy is
  played by another section that plays (instead of being left out), and the sections that play keep a low
  glow between hits that grows with the build (not black between the notes, but never wobbling: it changes in
  slow ramps and dims with the music's bars, so silences are still dark).

The no-flicker rules stay: a fixture is never hit again within a third of a second, the strobes stay within
the set's max_flash_hz.
"""

from __future__ import annotations

import bisect

import numpy as np

from amadeus.director.lightshow import NAME, layers, ranks
from amadeus.engine.cinematic import (
    BIG_HIT,
    BIG_TRIM,
    GRID_HZ,
    HOLD_S,
    LONG_RING_S,
    MAX_HOLD_S,
    MAX_RELEASE_S,
    NOTE_SHARE,
    PRE_IMPACT_S,
    RELEASE_S,
    RETRIGGER_S,
    ROLES,
    SMALL,
    STRONG,
    WHITE,
    CinematicMixin,
)

LEVELS = (0.6, 0.8, 1.0)  # a hit goes straight to one of these: brighter than the cinematic program's
MOTIF_GAP_S = 0.5  # a pause this long ends a motif; the next one answers
ANSWER_FROM = 0.45  # from this loud a phrase (its rank) the voices get an answer section
BRASS_FROM = 0.5  # …and the powerful sections without a part join the strong hits
SPECIALS_FROM = 0.6  # the build this far: impacts on the whole rig, the strobes and the lasers
BED = (0.1, 0.3)  # the glow between hits: at the start of the build, and with every layer in
BED_RAMP_S = 0.8  # a section's glow comes and goes over this (a section joining fades in over about a beat)
BED_QUIET = 0.25  # the bars quieter than this (breath) let the glow go: silences stay dark
MOVE_BARS = ((0.99, 2), (0.5, 4))  # the build this far: the heads change pictures every this many bars
MIN_MOVE_S = 1.5  # but not more often than this
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
        super()._init_cinematic(rig)
        if self.program == NAME:
            self._ls_bed()

    # ---------------------------------------------------------------- the orchestra, seated

    def _ls_seats(self):
        """Every voice's own section, and the order the sections join in: the voices the opening plays most
        first, then the sections without a voice of their own (the powerful ones last)."""
        secs, n = self.cine_sections, len(self.cine_sections)
        self.ls_seats, used = {}, set()
        for role in ("low", "cymbal", "mid", "tick"):
            ranked = sorted(range(n), key=lambda s: -self._suits(secs[s], role))
            free = [s for s in ranked if s not in used] or ranked
            self.ls_seats[role] = free[0] if free else None
            used.update(free[:1])
        h = self.cine_hits
        opening = self.plan[min(2, len(self.plan) - 1)].end if self.plan else self.a.duration
        count = {r: 0 for r in ROLES}
        for t, v in zip(h.t, h.voice):
            if t < opening:
                count[self._role_of(int(v))] += 1
        order: list[int] = []
        for role in sorted(ROLES, key=lambda r: -count[r]):
            s = self.ls_seats[role]
            if s is not None and s not in order:
                order.append(s)
        order += sorted(set(range(n)) - set(order), key=lambda s: (secs[s]["big"], -len(secs[s]["units"])))
        self.ls_order = order
        self.ls_layers = layers(self.a, n)

    def _orchestrate(self, i: int) -> dict:
        if self.program != NAME:
            return super()._orchestrate(i)
        if not hasattr(self, "ls_order"):
            self._ls_seats()
        n = len(self.cine_sections)
        k = self.ls_layers[min(i, len(self.ls_layers) - 1)] if self.ls_layers else n
        active = self.ls_order[:k]
        rank = float(self.ls_ranks[min(i, len(self.ls_ranks) - 1)]) if len(self.ls_ranks) else 0.5
        secs = self.cine_sections
        parts: dict[str, tuple] = {}
        played: set[int] = set()
        for r, role in enumerate(ROLES):
            if not active:  # nothing but lasers and strobes: they play the impacts
                parts[role] = (None, None, "unison")
                continue
            seat = self.ls_seats.get(role)
            lead = seat if seat in active else active[r % len(active)]  # not in yet: played by one that is
            answer = None
            if rank >= ANSWER_FROM and len(active) > 1:
                at = active.index(lead)
                answer = active[(at + 1) % len(active)]
            played.update(x for x in (lead, answer) if x is not None)
            parts[role] = (lead, answer, self._gesture(secs[lead], role, i + 3 * r))
        small = [s for s in active if not secs[s]["big"]]
        brass = [s for s in active if secs[s]["big"] and s not in played] if rank >= BRASS_FROM else []
        melody = max(active, key=lambda s: self._suits(secs[s], "melody"), default=None)
        pads = sorted((s for s in active if s != melody), key=lambda s: -self._suits(secs[s], "pad"))
        return {"parts": parts, "small": small, "brass": brass, "melody": melody,
                "pad": pads[0] if pads else None, "rank": rank, "active": active,
                "build": (k - 1) / (n - 1) if n > 1 else 1.0}  # fmt: skip

    # ---------------------------------------------------------------- the hits

    def _cine_events(self):
        """As the cinematic program, but brighter, a busy section's hit is played by another that plays, and
        the impacts grow with the build."""
        if self.program != NAME:
            return super()._cine_events()
        h = self.cine_hits
        events: dict[str, list[tuple]] = {}
        last_hit: dict[str, float] = {}

        def free(ids, t):
            return all(t - last_hit.get(eid, -1e9) >= RETRIGGER_S for eid in ids)

        def play(ids, t, level, hold, fade, colour):
            for eid in ids:
                last_hit[eid] = t
                lv = snap(level * (1 - BIG_TRIM * self.cine_power.get(eid, 0.0)))
                events.setdefault(eid, []).append((t, lv, hold, fade, colour, False))

        motif = {r: [-1e9, -1, 0] for r in ROLES}
        max_hz = float(self.rig["safety"].get("max_flash_hz", 3.0))
        last_flash = -1e9
        self.cine_played = []
        members = [[i for u in s["units"] for i in u] for s in self.cine_sections]
        next_same = np.full(len(h), 1.0)
        last_of: dict[int, int] = {}
        for k in range(len(h) - 1, -1, -1):
            v = int(h.voice[k])
            if v in last_of:
                next_same[k] = float(h.t[last_of[v]] - h.t[k])
            last_of[v] = k
        for k in range(len(h)):
            t, s, voice = float(h.t[k]), float(h.strength[k]), int(h.voice[k])
            i, d = self.decision_at(t)
            cols = self._colours(d)
            score = self.cine_score[min(i, len(self.cine_score) - 1)]
            here = float(self.level[min(int(t * self.a.fps), len(self.level) - 1)])
            if h.impact[k]:
                specials = score["build"] >= SPECIALS_FROM
                flash = specials and t - last_flash >= 1.0 / max_hz
                ids = [eid for si in (range(len(members)) if specials else score["active"]) for eid in members[si]]
                for eid in ids:  # the sections that play, at once (the whole rig late in the build)
                    big = self.cine_power.get(eid, 0.0) >= SMALL
                    colour = WHITE if flash else cols[2 % len(cols)]
                    events.setdefault(eid, []).append((t, 1.0, 0.3 if big else 0.4, 0.4 if big else 0.9, colour, True))
                    last_hit[eid] = t
                if flash:
                    last_flash = t
                    for eid in self.cine_strobes:
                        events.setdefault(eid, []).append((t, 1.0, 0.05, 0.0, WHITE, True))
                if specials:
                    for eid in self.cine_lasers:
                        events.setdefault(eid, []).append((t, 1.0, 0.6, 0.0, cols[0], True))
                self.cine_played.append((t, 1.0))
                continue
            role = self._role_of(voice)
            lead, answer, gesture = score["parts"][role]
            if lead is None:
                continue
            last, m, step = motif[role]
            if t - last > MOTIF_GAP_S:
                m, step = m + 1, 0
            motif[role] = [t, m, step + 1]
            sec_i = answer if (answer is not None and m % 2 == 1) else lead
            sections = [sec_i]
            if s >= STRONG and answer is not None:
                sections = [lead, answer] + score["brass"]
            if s < BIG_HIT and self.cine_sections[sec_i]["big"] and score["small"]:
                sections = [max(score["small"], key=lambda x: self._suits(self.cine_sections[x], role))]
            # still busy (a fixture is hit at most every RETRIGGER_S): the other sections that play, in turn
            spill = [x for x in [answer, lead] + score["active"] if x is not None and x not in sections]
            level = s**0.4 * (0.7 + 0.3 * here) * (0.8 + 0.2 * score["build"])
            sounds = max(float(h.decay[k]), NOTE_SHARE * float(next_same[k]))
            hold = float(np.clip(sounds, HOLD_S[role], MAX_HOLD_S))
            fade = RELEASE_S[role]
            if role == "low" and h.decay[k] > LONG_RING_S:
                fade = min(float(h.decay[k]), MAX_RELEASE_S)
            played = False
            for si in sections + spill:
                if played and si in spill:
                    break
                sec = self.cine_sections[si]
                colour = cols[(ROLES.index(role) + (si == answer)) % len(cols)]
                if role == "tick":
                    colour = tuple(0.55 + 0.45 * c for c in colour)
                g = "unison" if s >= STRONG else gesture
                if si in spill and g in ("steps", "keys") and not sec["pixel"]:
                    g = "chase"
                pool = sec["segments"] if g in ("steps", "keys") else sec["units"]
                for option in self._members(sec, g, step, m, float(h.pitch[k])):
                    ids = [eid for o in option for eid in pool[o]]
                    if g == "unison":
                        ids = [eid for eid in ids if free([eid], t)]
                    if ids and free(ids, t):
                        play(ids, t, level, hold, fade, colour)
                        played = True
                        break
            if played:
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
        moves = sorted(moves)
        kept: list[float] = []
        for m in moves:
            if not kept or m - kept[-1] >= MIN_MOVE_S:
                kept.append(m)
        self.cine_moves = np.array(kept)

    def _pre_move(self, t: float) -> bool:
        if self.program != NAME:
            return super()._pre_move(t)
        q = bisect.bisect_right(self.ls_dark, t)  # only the impacts are moved to in the dark
        return q < len(self.ls_dark) and self.ls_dark[q] - t < PRE_IMPACT_S

    # ---------------------------------------------------------------- the glow between the hits

    def _ls_bed(self):
        """Per section, its glow over time: while it plays, at the build's level, ramped in and out."""
        grid = self._grid()
        bars = np.interp(grid, np.arange(len(self.breath)) / self.a.fps, self.breath)
        gate = np.clip(bars / BED_QUIET, 0, 1)
        step = 1 / (BED_RAMP_S * GRID_HZ)
        self.ls_beds = []
        for si in range(len(self.cine_sections)):
            want = np.zeros(len(grid))
            for i, d in enumerate(self.plan):
                score = self.cine_score[min(i, len(self.cine_score) - 1)]
                if si in score["active"]:
                    a, b = int(d.start * GRID_HZ), int(d.end * GRID_HZ)
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
        return out
