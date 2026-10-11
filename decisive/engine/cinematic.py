"""The cinematic program: a film-score track played hit by hit, the rig played like an orchestra.

Every hit the analysis found (decisive/audio/hits.py) is played at its exact time:

- **the orchestra**: fixtures of one kind form a **section** (the four Sharpys, the pixel bars on the floor,
  the two washes…; a big uniform rig is split by where its fixtures hang). Each section is suited to some
  parts: beams to the stabs and cymbals, floor lights and blinders to the booms, pixel bars to the ticks
  and the melody, washes to a held pad;
- **the score**: per phrase the program orchestrates. Every voice of the music (booms, stabs, ticks…) gets
  a *lead* section and, when the music is big enough, an *answer* section, and the parts move to other
  sections from phrase to phrase. Quiet phrases are chamber music (a few soloists), the climax is tutti;
- **the brass**: powerful sections without a part of their own (a halogen sunstrip) join the strongest hits
  when the music is big;
- **gestures**: a section plays a voice in a gesture that is kept for the phrase: a chase over its
  fixtures, mirrored pairs outside-in, odds against evens, steps along its pixels, or keys (the pitch picks
  the place). A run of hits (a *motif*) plays the gesture through; the next motif is the answer: the other
  section, or the chase back the other way. Strong hits are played by the whole section, both sections when
  the music is big;
- **played notes**: a light is played the way a musician plays a note. It is hit (at once, to one of a few
  levels: soft, half, full), held for as long as the note sounds (until its instrument plays again, or it
  has died away), and let go gently. It never flickers along with the music in between. Slow things are
  smooth: long booms are let go slowly, the low glow and the melody layer come and go with slow fades.
  A fixture is never hit again within a third of a second;
- **impacts** (the biggest hits) are played by the whole rig, the strobes and the lasers, and the moving
  heads are already in a new picture when they land: they move there in the dark just before;
- **the lows**: the sustained low end glows on the floor in deep colours, on a few steps that change slowly;
- **room for the accents** (a light show's sidechain): a rig mixes very powerful lights (a 180,000 lm strobe,
  a halogen sunstrip) with small ones (pixel cells, a narrow beam). Each fixture gets a *power* from its real
  output (lumens, how wide it spreads). The powerful sections leave the weak hits to small ones, and while
  small fixtures play accents the powerful ones step down (never to black) and come back after;
- **the melody**: when everything plays together legato there are few hits, so the melody takes over: its
  notes step over the melody section (low notes in the centre, high ones out to the sides) while the pad
  section holds a steady glow and the heads drift with the melody's contour;
- between hits it's dark: silences are black.

Colours come from the cinematic director's arc (decisive/director/cinematic.py): ice when calm, warm when
it swells, fire at the climax; an answer plays in the next colour of the palette. Flashes and strobes stay
within the set's max_flash_hz.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from decisive.engine import motion
from decisive.engine.state import State
from decisive.library import fixtures as fxlib
from decisive.rig import geometry

VERSION = 3  # bump when the program changes what the heads do (their trajectories are cached)
RETRIGGER_S = 0.33  # a fixture is not hit again within this (no flicker faster than ~3 Hz)
PRE_IMPACT_S = 0.5  # heads move to their next picture this long before an impact, in the dark
WHITE = (1.0, 1.0, 1.0)
GRID_HZ = 100  # the slow layers (glow, room, melody) are sampled this often

# played notes
# a note is played like a musician plays it: hit (at once), held as long as it sounds, and let go gently
LEVELS = (0.45, 0.7, 1.0)  # soft, half, full: a hit goes straight to one of these
HOLD_S = {"low": 0.45, "mid": 0.35, "cymbal": 0.3, "tick": 0.22}  # the shortest hold per voice
MAX_HOLD_S = 1.2
NOTE_SHARE = 0.6  # a note is held for this share of the time until its instrument plays again
RELEASE_S = {"low": 0.7, "mid": 0.45, "cymbal": 0.5, "tick": 0.3}  # and let go over this
LONG_RING_S = 0.8  # a boom that rings longer than this is let go slower…
MAX_RELEASE_S = 2.0  # …up to this
LOW_STEPS = (0.0, 0.15, 0.3, 0.45)  # the floor's glow under the sustained low end
SLOW_S = 1.5  # how long a slow layer takes to change a step
MIN_STEP_S = 2.0  # and how long it holds one at least

# the orchestra
ROLES = ("low", "cymbal", "mid", "tick")
MOTIF_GAP_S = 0.7  # a pause this long ends a motif; the next one answers
STRONG = 0.8  # hits this strong are played by the whole section
MAX_SECTION = 8  # a uniform section bigger than this is split by where its fixtures hang
BEAM_DEG = 6.0  # heads this narrow are beams (stabs, cymbals); wider ones are washes and spots

# room for the accents
POWER_SPAN = 4.0  # a fixture this many times the rig's typical output counts as fully powerful
SMALL = 0.5  # fixtures below this power play the accents the big ones make room for
BIG_TRIM = 0.3  # the powerful lights play their ordinary hits this much lower
BIG_HIT = 0.6  # …and only hits at least this strong: the small ones play the rest
DUCK_DEPTH = 0.6  # how far a fully powerful fixture steps down under accents (never to black)
DUCK_HOLD_S = 0.45  # it stays down this long after the last accent…
DUCK_RETURN_S = 0.3  # …and comes back over this
DUCK_LOOKAHEAD_S = 0.04  # already down when the accent lands
OWN_ATTACK_S = 0.09  # a big fixture's own hit isn't ducked in its first instant
IMPACT_KEEP_S = 0.15  # nor an impact's flash

# the melody layer
FILL_WINDOW_S = 1.5  # how far back the show looks at how busy it is
FILL_RATE = 3.0  # hits per second (at full loudness) that make a passage busy enough without the melody
MELODY_ON, MELODY_OFF = 0.4, 0.2  # the melody layer comes in above this, leaves below that
MELODY_LEVEL = 0.55
MELODY_HOLD_S = 1.2  # a note held longer than this is let go
MELODY_RELEASE_S = 0.35
MELODY_SEGMENTS = 8
PAD_LEVEL = 0.3


def snap(v: float) -> float:
    """A level → the nearest step (above the softest one)."""
    return min(LEVELS, key=lambda s: abs(s - v))


def envelope(t: float, t0: float, level: float, hold: float, release: float) -> float:
    """A played note: hit at `level` at once, held for `hold`, then let go gently over `release` (a soft
    curve: slow at first, slow at the end); no release is a snap off."""
    dt = t - t0
    if dt < 0:
        return 0.0
    if dt < hold:
        return level
    if release > 0 and dt < hold + release:
        return level * 0.5 * (1 + math.cos(math.pi * (dt - hold) / release))
    return 0.0


def stepped(x: np.ndarray, steps: tuple, ramp_s: float = SLOW_S, min_s: float = MIN_STEP_S) -> np.ndarray:
    """A slow layer: `x` (on the grid) → the nearest of `steps`, changed only when clearly off and after
    holding at least `min_s`, and moved from step to step in a straight line over `ramp_s`."""
    steps = np.asarray(steps, float)
    gap = float(np.min(np.diff(steps))) if len(steps) > 1 else 1.0
    out, cur, since = np.zeros(len(x)), 0, 1e9
    for k, v in enumerate(x):
        since += 1 / GRID_HZ
        if abs(v - steps[cur]) > 0.75 * gap and since >= min_s:
            cur, since = int(np.argmin(np.abs(steps - v))), 0.0
        out[k] = steps[cur]
    rate = (float(steps.max() - steps.min()) or 1.0) / (ramp_s * GRID_HZ)
    y = np.zeros(len(out))
    for k in range(len(out)):  # the ramp
        prev = y[k - 1] if k else out[0]
        y[k] = prev + float(np.clip(out[k] - prev, -rate, rate))
    return y


class CinematicMixin:
    """Mixed into the Engine; active when the analysis has hits and the genre's program is cinematic."""

    CINE_VERSION = VERSION

    # ---------------------------------------------------------------- the orchestra

    def _init_cinematic(self, rig: dict):
        self.cine_hits = self.a.hits
        elements = rig["elements"]
        self.cine_strobes = [e["id"] for e in elements if e["kind"] == "strobe"]
        self.cine_lasers = [e["id"] for e in elements if e["kind"] == "laser"]
        self.cine_heads = [e["id"] for e in self.heads]
        self.cine_power = self._cine_power(rig)
        self.cine_sections = self._cine_sections(rig)
        self.cine_floor = {i for s in self.cine_sections if s["floor"] for u in s["units"] for i in u}
        if not self.cine_floor:  # no floor lights: the low end glows on the booms' first section
            best = max(self.cine_sections, key=lambda s: self._suits(s, "low"), default=None)
            self.cine_floor = {i for u in best["units"] for i in u} if best else set()
        self.cine_score = [self._orchestrate(i) for i in range(len(self.plan))]
        self._cine_events()
        self._cine_room()
        self._cine_glow()
        self._cine_melody()
        self._cine_pictures()

    def _cine_power(self, rig: dict) -> dict[str, float]:
        """Per element 0..1: how powerful its fixture is against the rest of the rig (0 = typical or less).

        What masks the other lights is how much light a fixture throws into the room: its lumens, a little
        less for a narrow beam (it lights a line, not the room). Without data, a guess by kind."""
        guess = {"strobe": 50000, "blinder": 20000, "head": 5000, "par": 2500}
        flood = {}
        for f in rig["fixtures"]:
            phys = fxlib.get(f["fixture"]).get("physical", {})
            lm = phys.get("lumens")
            kind = next((e["kind"] for e in rig["elements"] if e["fixture"] == f["id"]), "par")
            if kind == "laser":
                continue
            beam = float(phys.get("beam_deg_max") or phys.get("beam_deg") or 25)
            flood[f["id"]] = float(lm) * min(1.0, beam / 20) ** 0.5 if lm else guess.get(kind, 2500)
        if not flood:
            return {}
        typical = float(np.median(list(flood.values())))
        power = {fid: float(np.clip(math.log(v / typical) / math.log(POWER_SPAN), 0, 1)) for fid, v in flood.items()}
        return {e["id"]: power[e["fixture"]] for e in rig["elements"] if e["fixture"] in power}

    def _cine_sections(self, rig: dict) -> list[dict]:
        """The rig's sections: fixtures of one kind (split by position when there are many), each a list of
        units (one fixture: its elements, left to right) and of segments (its pixels in a few blocks)."""
        by_fixture: dict[str, list[dict]] = {}
        for e in rig["elements"]:
            if e["kind"] not in ("laser", "strobe"):
                by_fixture.setdefault(e["fixture"], []).append(e)
        groups: dict[tuple, list[dict]] = {}
        for f in rig["fixtures"]:
            if f["id"] in by_fixture:
                groups.setdefault((f["fixture"],), []).append(f)
        split: list[list[dict]] = []
        for fs in groups.values():
            if len(fs) <= MAX_SECTION:
                split.append(fs)
                continue
            parts: dict[tuple, list[dict]] = {}  # by where they hang: height, depth
            for f in fs:
                parts.setdefault((round(float(f.get("z_m", 1.0))), round(float(f.get("y_m", 0.0)))), []).append(f)
            split += list(parts.values())
        sections = []
        for fs in split:
            fs = sorted(fs, key=lambda f: np.mean([e["x"] for e in by_fixture[f["id"]]]))
            units = [[e["id"] for e in sorted(by_fixture[f["id"]], key=lambda e: e["x"])] for f in fs]
            cells = sorted([e for f in fs for e in by_fixture[f["id"]]], key=lambda e: e["x"])
            n_seg = min(MELODY_SEGMENTS, len(cells))
            segments = [[e["id"] for e in part] for part in np.array_split(np.array(cells, dtype=object), n_seg)]
            phys = fxlib.get(fs[0]["fixture"]).get("physical", {})
            kind = by_fixture[fs[0]["id"]][0]["kind"]
            sections.append({
                "name": fs[0]["fixture"].split("/")[-1],
                "units": units,
                "segments": segments,
                "kind": kind,
                "pixel": len(cells) > len(fs),
                "floor": float(np.mean([f.get("z_m", 1.0) for f in fs])) < 1.2 and kind != "head",
                "beam": kind == "head" and float(phys.get("beam_deg") or 25) <= BEAM_DEG,
                "big": max(self.cine_power.get(i, 0.0) for u in units for i in u) >= SMALL,
            })  # fmt: skip
        return sections

    @staticmethod
    def _suits(s: dict, part: str) -> float:
        """How well a section suits a part of the score (higher is better)."""
        head, wash = s["kind"] == "head", s["kind"] == "head" and not s["beam"]
        score = {
            "low": 3 * (s["kind"] == "blinder") + 2 * s["floor"] + (s["kind"] == "par") - 2 * s["beam"],
            "mid": 2 * wash + s["pixel"] + s["floor"],
            "cymbal": 3 * s["beam"] + head,
            "tick": 2 * s["pixel"] - 3 * s["big"] + s["beam"],
            "melody": 3 * s["pixel"] + head - s["big"],
            "pad": 3 * wash + head - 2 * s["pixel"],
        }[part]
        return float(score) + 0.1 * len(s["units"])  # a bigger section plays more

    def _orchestrate(self, i: int) -> dict:
        """Phrase i's score: per voice a lead and an answer section and a gesture, the melody and pad sections."""
        p = self.a.phrases[i] if i < len(self.a.phrases) else None
        loud = np.array([q.loudness_pct for q in self.a.phrases]) if self.a.phrases else np.zeros(1)
        rank = float(np.mean(loud <= p.loudness_pct)) if p is not None else 0.5
        n = len(self.cine_sections)
        used: set[int] = set()
        parts: dict[str, tuple] = {}
        for r, role in enumerate(ROLES):
            ranked = sorted(range(n), key=lambda s: -self._suits(self.cine_sections[s], role))
            if not ranked:  # nothing but lasers and strobes: they play the impacts
                parts[role] = (None, None, "unison")
                continue
            best = self._suits(self.cine_sections[ranked[0]], role) if ranked else 0
            good = [s for s in ranked if self._suits(self.cine_sections[s], role) >= best - 1.2] or ranked
            good = good[i % len(good) :] + good[: i % len(good)]  # the parts move round from phrase to phrase
            free = [s for s in good if s not in used] or good
            lead = free[0] if free else None
            # an answer when the music is big enough: from rank 0.35 for the booms and cymbals, 0.6 for the rest
            wants = rank >= (0.35 if role in ("low", "cymbal") else 0.6)
            answer = next((s for s in free[1:] + good if s != lead), None) if wants else None
            if lead is not None:
                used.add(lead)
            if answer is not None:
                used.add(answer)
            sec = self.cine_sections[lead] if lead is not None else None
            parts[role] = (lead, answer, self._gesture(sec, role, i + 3 * r))
        small = [s for s in range(n) if not self.cine_sections[s]["big"]]
        rot = sorted(range(n), key=lambda s: -self._suits(self.cine_sections[s], "melody"))
        melody = rot[(i // 2) % min(2, len(rot))] if rot else None
        pads = [s for s in sorted(range(n), key=lambda s: -self._suits(self.cine_sections[s], "pad")) if s != melody]
        # the brass: powerful sections without a part, for the strongest hits when the music is big
        brass = [s for s in range(n) if self.cine_sections[s]["big"] and s not in used] if rank >= 0.6 else []
        return {"parts": parts, "small": small, "brass": brass, "melody": melody,
                "pad": pads[0] if pads else None, "rank": rank}  # fmt: skip

    @staticmethod
    def _gesture(sec: dict | None, role: str, seed: int) -> str:
        if sec is None:
            return "unison"
        n = len(sec["units"])
        if sec["pixel"] and role in ("tick", "mid"):
            menu = ["keys", "steps"] if role == "tick" else ["steps", "chase", "pairs"]
        elif n == 1:
            menu = ["unison"]
        elif n == 2:
            menu = ["alternate", "unison"]
        else:
            menu = ["chase", "pairs", "alternate"]
        return menu[seed % len(menu)]

    @staticmethod
    def _members(sec: dict, gesture: str, k: int, motif: int, pitch: float) -> list[list[int]]:
        """The ways a section can play step k of a motif in a gesture: a list of options (each a list of
        member indices) to try in turn, the first whose fixtures are free wins."""
        n = len(sec["segments"] if gesture in ("steps", "keys") else sec["units"])
        back = motif % 2 == 1  # every other motif goes the other way
        if gesture == "unison":
            return [list(range(n))]
        if gesture in ("chase", "steps"):
            order = [(k + j) % n for j in range(n)]
            return [[n - 1 - o] if back else [o] for o in order]
        if gesture == "pairs":
            half = (n + 1) // 2
            opts = []
            for j in range(half):
                a = (k + j) % half
                a = half - 1 - a if back else a  # outside-in, then inside-out
                opts.append(sorted({a, n - 1 - a}))
            return opts
        if gesture == "alternate":
            return [[m for m in range(n) if m % 2 == (k + j) % 2] for j in range(2)]
        if gesture == "keys":  # the pitch picks the place: low in the centre, high out to the sides
            half = (n + 1) // 2
            j = int(round(pitch * (half - 1)))
            opts = []
            for dj in (0, 1, -1, 2, -2):
                jj = j + dj
                if 0 <= jj < half:
                    opts.append(sorted({half - 1 - jj, n - half + jj}))
            return opts
        return [[0]]

    def _role_of(self, voice: int) -> str:
        n = int(self.cine_hits.voice.max()) + 1 if len(self.cine_hits) else 1
        q = voice / max(n - 1, 1)  # 0 = the lowest voice, 1 = the highest
        return "low" if q < 0.25 else "mid" if q < 0.5 else "cymbal" if q < 0.75 else "tick"

    # ---------------------------------------------------------------- the hits

    def _cine_events(self):
        """Every hit → which elements light, how bright, how long, in what colour.

        An event is (time, level, hold, fade, colour, impact): on at `level` for `hold`, then off or a fade."""
        h = self.cine_hits
        events: dict[str, list[tuple]] = {}
        last_hit: dict[str, float] = {}  # element → when it was last hit

        def free(ids, t):
            return all(t - last_hit.get(eid, -1e9) >= RETRIGGER_S for eid in ids)

        def play(ids, t, level, hold, fade, colour):
            for eid in ids:
                last_hit[eid] = t
                lv = snap(level * (1 - BIG_TRIM * self.cine_power.get(eid, 0.0)))
                events.setdefault(eid, []).append((t, lv, hold, fade, colour, False))

        motif = {r: [-1e9, -1, 0] for r in ROLES}  # per voice: last hit, motif number, step in the motif
        max_hz = float(self.rig["safety"].get("max_flash_hz", 3.0))
        last_flash = -1e9
        self.cine_played = []  # (time, level) of every hit the show played: how busy it is
        everything = [i for s in self.cine_sections for u in s["units"] for i in u]
        next_same = np.full(len(h), 1.0)  # per hit: time until its voice plays again
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
            here = float(self.level[min(int(t * self.a.fps), len(self.level) - 1)])
            if h.impact[k]:
                flash = t - last_flash >= 1.0 / max_hz
                for eid in everything:  # all at once; the powerful ones let go first
                    big = self.cine_power.get(eid, 0.0) >= SMALL
                    colour = WHITE if flash else cols[2 % len(cols)]
                    events.setdefault(eid, []).append((t, 1.0, 0.3 if big else 0.4, 0.4 if big else 0.9, colour, True))
                    last_hit[eid] = t
                if flash:
                    last_flash = t
                    for eid in self.cine_strobes:
                        events.setdefault(eid, []).append((t, 1.0, 0.05, 0.0, WHITE, True))
                for eid in self.cine_lasers:
                    events.setdefault(eid, []).append((t, 1.0, 0.6, 0.0, cols[0], True))
                self.cine_played.append((t, 1.0))
                continue
            role = self._role_of(voice)
            score = self.cine_score[min(i, len(self.cine_score) - 1)]
            lead, answer, gesture = score["parts"][role]
            if lead is None:
                continue
            last, m, step = motif[role]
            if t - last > MOTIF_GAP_S:
                m, step = m + 1, 0
            motif[role] = [t, m, step + 1]
            # call and response: the motifs take turns between the lead and the answer section
            sec_i = answer if (answer is not None and m % 2 == 1) else lead
            sections = [sec_i]
            if s >= STRONG and answer is not None:
                sections = [lead, answer] + score["brass"]  # a strong hit: both sections together, and the brass
            # space: a powerful section leaves the weak hits to a small one
            if s < BIG_HIT and self.cine_sections[sec_i]["big"] and score["small"]:
                alt = sorted(score["small"], key=lambda x: -self._suits(self.cine_sections[x], role))[0]
                sections = [alt]
            level = s**0.5 * (0.55 + 0.45 * here) * (0.85 + 0.05 * d.intensity)
            # held as long as the note sounds: until the same instrument plays again (or it has died away)
            sounds = max(float(h.decay[k]), NOTE_SHARE * float(next_same[k]))
            hold = float(np.clip(sounds, HOLD_S[role], MAX_HOLD_S))
            fade = RELEASE_S[role]
            if role == "low" and h.decay[k] > LONG_RING_S:  # a long boom is let go slower
                fade = min(float(h.decay[k]), MAX_RELEASE_S)
            played = False
            for si in sections:
                sec = self.cine_sections[si]
                colour = cols[(ROLES.index(role) + (si == answer)) % len(cols)]
                if role == "tick":
                    colour = tuple(0.55 + 0.45 * c for c in colour)
                g = "unison" if s >= STRONG else gesture
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
        self.cine_events = {
            eid: (np.array([e[0] for e in ev]), ev) for eid, ev in events.items()
        }  # times (sorted: hits are in order) and the events
        # moments the heads hit a new picture: impacts, and the start of every phrase
        moves = sorted({float(t) for t in h.t[h.impact]} | {d.start for d in self.plan[1:]})
        self.cine_moves = np.array([m for k, m in enumerate(moves) if k == 0 or m - moves[k - 1] > 2.0])

    # ---------------------------------------------------------------- the slow layers

    def _grid(self) -> np.ndarray:
        return np.arange(0, self.a.duration + 1, 1 / GRID_HZ)

    def _at(self, arr: np.ndarray, t: float) -> float:
        return float(arr[min(max(int(t * GRID_HZ), 0), len(arr) - 1)])

    def _cine_room(self):
        """When the powerful lights step down for the small ones' accents: down (at once) a moment before an
        accent, held while accents keep coming, back up in a short ramp after."""
        grid = self._grid()
        on = np.zeros(len(grid), bool)
        for eid, (_, items) in self.cine_events.items():
            if self.cine_power.get(eid, 1.0) >= SMALL:
                continue
            for t0, _, hold, _r, _c, impact in items:
                if not impact:  # everything plays an impact together: nothing to make room for
                    a = max(0, int((t0 - DUCK_LOOKAHEAD_S) * GRID_HZ))
                    on[a : min(len(grid), int((t0 + max(hold, DUCK_HOLD_S)) * GRID_HZ))] = True
        room, y, up = np.zeros(len(grid)), 0.0, 1 / (DUCK_RETURN_S * GRID_HZ)
        for k, v in enumerate(on):
            y = 1.0 if v else max(0.0, y - up)
            room[k] = y
        self.cine_room = room

    def _cine_glow(self):
        """The floor's glow under the sustained low end: a few steps, changing slowly."""
        h = self.cine_hits
        grid = self._grid()
        low = np.interp(grid, np.arange(len(h.low)) / h.fps, h.low) ** 1.6
        low = np.convolve(low, np.ones(2 * GRID_HZ) / (2 * GRID_HZ), mode="same")  # a passage, not a rumble
        intensity = np.array([0.6 + 0.4 * min(self.decision_at(float(t))[1].intensity, 3) / 3 for t in grid[::GRID_HZ]])
        low = low * np.repeat(intensity, GRID_HZ)[: len(grid)]
        self.cine_lowglow = stepped(low * max(LOW_STEPS) / max(float(low.max()), 1e-6) * 1.2, LOW_STEPS)

    def _cine_melody(self):
        """The notes of the melody, and when the melody layer plays (`cine_fill`, 0..1, with slow fades): in
        loud passages where the hits leave room for it."""
        a = self.a
        if a.synth_notes is not None and len(a.synth_notes[0]):
            nt, ns, npitch = (np.asarray(x, float) for x in a.synth_notes)
        else:  # no separated melody: the lead's pitch, a note every 0.3 s
            nt = np.arange(0, a.duration, 0.3)
            fr = np.minimum((nt * a.fps).astype(int), len(self.level) - 1)
            lead = a.lead_pitch if a.lead_pitch is not None else np.full(len(self.level), 0.5)
            npitch = np.asarray(lead, float)[np.minimum(fr, len(lead) - 1)]
            ns = self.level[fr].astype(float)
        if len(npitch):
            lo, hi = np.percentile(npitch, 5), np.percentile(npitch, 95)
            npitch = np.clip((npitch - lo) / max(hi - lo, 1e-6), 0, 1)
        self.cine_notes = (nt, ns, npitch)

        grid = self._grid()
        loud = np.interp(grid, np.arange(len(self.level)) / a.fps, self.level)
        played = np.zeros(len(grid))
        for t0, lv in self.cine_played:
            played[min(int(t0 * GRID_HZ), len(grid) - 1)] += lv
        w = int(FILL_WINDOW_S * GRID_HZ)
        rate = np.convolve(played, np.ones(w) / FILL_WINDOW_S, mode="full")[: len(grid)]  # hits/s, looking back
        gate = np.clip((loud - 0.2) / 0.3, 0, 1)  # quiet passages are allowed to be dark
        want = gate * np.clip(1 - rate / np.maximum(FILL_RATE * loud, 0.3), 0, 1)
        want = np.convolve(want, np.ones(GRID_HZ) / GRID_HZ, mode="same")  # a passage, not a moment
        state, cur = np.zeros(len(grid)), 0.0
        for k, v in enumerate(want):  # in above MELODY_ON, out below MELODY_OFF
            cur = 1.0 if v > MELODY_ON else 0.0 if v < MELODY_OFF else cur
            state[k] = cur
        self.cine_fill = stepped(state, (0.0, 1.0), ramp_s=0.8)
        # the melody's contour, smoothed: where the heads drift
        idx = np.clip(np.searchsorted(nt, grid, side="right") - 1, 0, max(len(nt) - 1, 0))
        contour = npitch[idx] if len(nt) else np.full(len(grid), 0.5)
        self.cine_contour = np.convolve(contour, np.ones(GRID_HZ) / GRID_HZ, mode="same")

    def _fill_at(self, t: float) -> float:
        return self._at(self.cine_fill, t)

    def _melody_now(self, t: float, sec: dict) -> dict[str, float]:
        """The melody section's elements the notes light now (0..1): the current note held, the one before
        let go gently, and a note held too long let go too."""
        nt, ns, npitch = self.cine_notes
        k = bisect.bisect_right(nt, t) - 1
        if k < 0:
            return {}
        pool = sec["segments"] if sec["pixel"] else sec["units"]

        def keys(n):
            opts = self._members({"segments": pool, "units": pool}, "keys", 0, 0, float(npitch[n]))
            return [eid for o in opts[0] for eid in pool[o]] if opts else []

        out: dict[str, float] = {}
        if k > 0:  # the note before, let go
            v = envelope(t, nt[k], 1.0, 0.0, MELODY_RELEASE_S)
            for eid in keys(k - 1):
                out[eid] = v
        for eid in keys(k):
            out[eid] = envelope(t, nt[k], 1.0, MELODY_HOLD_S, MELODY_RELEASE_S)
        return {eid: v for eid, v in out.items() if v > 0}

    # ---------------------------------------------------------------- the light, frame by frame

    def _cinematic_scene(self, t: float) -> dict[str, State]:
        i, d = self.decision_at(t)
        cols = self._colours(d)
        score = self.cine_score[min(i, len(self.cine_score) - 1)]
        before_impact = len(self.cine_moves) and self._pre_move(t)
        room = self._at(self.cine_room, t)
        glow = self._at(self.cine_lowglow, t)
        fill = self._fill_at(t)
        layer: dict[str, tuple[float, tuple]] = {}  # the held layers: melody and pad
        if fill > 0:
            if score["pad"] is not None:
                pad = self.cine_sections[score["pad"]]
                for u in pad["units"]:
                    for eid in u:
                        layer[eid] = (PAD_LEVEL * fill, cols[0])
            if score["melody"] is not None:
                mcol = tuple(0.7 * c + 0.3 for c in cols[1 % len(cols)])
                for eid, v in self._melody_now(t, self.cine_sections[score["melody"]]).items():
                    layer[eid] = (MELODY_LEVEL * fill * v, mcol)
        out: dict[str, State] = {}
        for e in self.rig["elements"]:
            eid = e["id"]
            power = self.cine_power.get(eid, 0.0)
            duck = 1 - DUCK_DEPTH * power * room  # the powerful lights step down for the small ones' accents
            dim, col = 0.0, cols[0]
            if eid in self.cine_floor and glow > 0:  # the lows glow on the floor
                dim = glow * duck
            if eid in layer:
                v, c = layer[eid]
                v *= 1 - 0.5 * power * room
                if v > dim:
                    dim, col = v, c
            ev = self.cine_events.get(eid)
            if ev is not None:
                times, items = ev
                q = bisect.bisect_right(times, t)
                for k in range(max(0, q - 4), q):  # the last few hits still on
                    t0, level, hold, fade, c, impact = items[k]
                    v = envelope(t, t0, level, hold, fade)
                    if power and t - t0 > (IMPACT_KEEP_S if impact else OWN_ATTACK_S):
                        v *= duck  # it steps down; its own hit (and an impact's flash) lands first
                    if v > dim:
                        dim, col = v, c
            s = State(dimmer=min(1.0, dim), r=col[0], g=col[1], b=col[2])
            if e["kind"] == "head" and before_impact:
                s.dimmer = 0.0  # moving to the next picture in the dark
            if e["kind"] == "strobe":
                s.white = s.dimmer
            if e["kind"] == "laser":
                s.fx, s.lcolor, s.size, s.phase = ("fan" if s.dimmer > 0.05 else "off"), "base", 0.8, -1.0
            out[eid] = s
        return out

    def _pre_move(self, t: float) -> bool:
        q = bisect.bisect_right(self.cine_moves, t)
        return q < len(self.cine_moves) and self.cine_moves[q] - t < PRE_IMPACT_S

    # ---------------------------------------------------------------- the heads: pictures

    def _cine_pictures(self):
        """A list of strong, still pictures (each a direction per head) the heads change between."""
        n = len(self.heads)
        if not n:
            self.cine_pictures = []
            return
        centre = np.mean([p[0] for p in self.head_pos])
        span = max(np.ptp([p[0] for p in self.head_pos]) / 2, 0.5)
        side = [float(np.clip((p[0] - centre) / span, -1, 1)) for p in self.head_pos]
        stage_point = np.array([self.stage["width_m"] / 2, -0.5, 2.6])  # over the DJ's head, not in their face
        pics = []
        pics.append([(0.0, 78.0)] * n)  # a cathedral: every beam straight up
        pics.append([(s_ * 38, 12.0) for s_ in side])  # a fan over the crowd
        pics.append([(-s_ * 28, -18.0) for s_ in side])  # crossing into the crowd
        focus = []
        dj_z = np.mean([p[2] for p in self.head_pos])
        for p, s_ in zip(self.head_pos, side):  # all on the DJ: a ring of light around them, not one spot
            spot = motion.focus_spread(stage_point, stage_point - p, s_, p[2] - dj_z)[0]
            v = spot - p
            focus.append(
                (math.degrees(math.atan2(v[0], v[1])), math.degrees(math.asin(v[2] / (np.linalg.norm(v) + 1e-9))))
            )
        pics.append(focus)
        pics.append([(s_ * 50, -32.0) for s_ in side])  # wide, down onto the floor
        pics.append([(180.0 - s_ * 20, 25.0) for s_ in side])  # back, over the stage
        self.cine_pictures = pics

    def _cinematic_head_dirs(self, ts: np.ndarray, j: int) -> np.ndarray:
        """Head j's target over time: a picture held until the next move (impacts, phrase starts), reached in
        the dark just before it."""
        q = np.searchsorted(self.cine_moves, ts + PRE_IMPACT_S, side="right")  # already at the coming picture
        az = np.array([self.cine_pictures[k % len(self.cine_pictures)][j][0] for k in q])
        el = np.array([self.cine_pictures[k % len(self.cine_pictures)][j][1] for k in q])
        # the picture always drifts a little (heads never freeze); in melodic passages more: swaying slowly,
        # lifting with the melody
        grid = np.arange(len(self.cine_fill)) / GRID_HZ
        fill = np.maximum(np.interp(ts, grid, self.cine_fill), 0.35)
        contour = np.interp(ts, grid, self.cine_contour)
        az = az + fill * 14.0 * np.sin(2 * np.pi * ts / 7.0 + j * 0.9)
        el = el + fill * 16.0 * (contour - 0.5)
        out = self._direction_v(az, el)
        head_pos = self.head_pos[j]
        if self.zones.heads:
            out = self.zones.filter(head_pos, out)
        out = geometry.room_safe_v(out, head_pos, self.stage)  # off the ceiling, not back at the DJ
        return self._eye_safe_v(out, head_pos[2])
