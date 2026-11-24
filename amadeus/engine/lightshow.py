"""The lightshow program: one track played as a show piece, switched on by hand (the Lightshow switch, Play a
Track as Lightshow, `--director lightshow`). It is the cinematic program (amadeus/engine/cinematic.py: every
hit at its exact time, played by its own fixtures), turned all the way up, and it plays **the band**:

- **the drums lead**: every kick and every snare of the drummer (amadeus/audio/drums.py: from the separated
  drums, where the guitars don't mask them) is a hit of whole families at full level. The kick has its side of
  the line-up and its colour, the snare the other side, white once the music is loud, held for as long as it
  rings. At a climax both drums hit all of it (when the set's flash limit leaves room for that), with the
  strobes. A drum hit always gets its lights: it is placed first, and the other parts play around it;
- **the guitar runs**: the notes of the separated melodic part (a riff, a solo) run over their families block
  by block, a family a motif; a chord that rings is played by all of them at once. While the drummer doesn't
  play, the drums' families play the guitar too;
- **everything else** the analysis found (shouts, cymbals, the bass: amadeus/audio/hits.py) is played as in the
  cinematic program, by the family of its voice; the strong ones by every family of the line-up at once, white,
  with the strobes; the impacts by the strobes, the lasers and the line-up, and by the whole rig when it plays
  or a phrase starts on them. A climax that arrives starts on an impact of its own: its first drum hit;
- **every light gets its turn**: the rig is played in **families**, one per fixture model however many trusses
  it hangs on (all the PARs, all the Auras…), each split into a few blocks left to right for its gestures; a rig
  of one or two models splits them into interleaved halves or thirds, so it has groups to vary too;
- **a build-up that is played**: the song starts with half of the families (amadeus/director/lightshow.py,
  `layers`) and every loud phrase brings more. What builds is how hard they play: the glow between the hits,
  white and the strobes, how often the heads move and how fast they sway. How much of the rig plays depends
  on its size: a handful of lights all play all the time and their families swap instruments instead, a
  big rig has the room to let groups sit out (a line-up there is two fifths of its lights at least);
- **layers and turns**: a phrase is played in **passages** of a few bars with a line-up of their own. It starts
  with half of the families it may use and adds a layer per passage; when it can't add any, another part of
  the families takes over, keeping some of the ones before. The whole rig plays only at the climaxes: a drop
  hits with all of it, thins out and builds back to it;
- **hits you see**: a hit is short and hard (hit, a short hold, a quick release), at full level, and it has let
  go before the same light is hit again: every hit is a new flash, not a light that stays on. The line-up glows
  between the hits (ramped, and dark in silences); whoever isn't in the line-up stays dark;
- **heads in pictures that fit the room**: the heads change picture at the phrases and every two bars, every
  bar once it has built, on the drummer's kick, and sway around a picture with the music's pulse, wider and
  faster as it gets louder. Every picture is checked from where each head hangs: a head the ceiling or the
  back-wall guard would have to bend takes a picture that works from its place, and a picture most heads
  can't do is left out (a cathedral of beams under a low ceiling, beams back over the stage from a stage truss).

Flashes stay within the set's limits: a fixture is hit at most `max_flash_hz` times a second, the strobes too
(those faster with allow_fast_strobe, never with strobe_free).
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from amadeus.audio import drums
from amadeus.director.lightshow import CLIMAX, NAME, builds, layers, passages, ranks
from amadeus.engine.cinematic import (
    BEAM_DEG,
    BIG_HIT,
    BIG_TRIM,
    GRID_HZ,
    MELODY_SEGMENTS,
    PRE_IMPACT_S,
    ROLES,
    SMALL,
    VERSION,
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
SPECIALS_FROM = 0.3  # the build this far: the strobes on the strong hits, impacts on the whole rig, lasers…
DRUM_HIT = 0.35  # …and at a climax, the strobes on every kick and snare this strong too
HOLD_S = (0.12, 0.45)  # a hit is held for half the time until its instrument plays again, within this…
RELEASE_S = 0.2  # …and let go this fast (the booms: twice as slow)
KICK_NOTE = (0.16, 0.24)  # a kick: held this long, let go over this (a punch, down again before the snare)
SNARE_HOLD_S = (0.12, 0.3)  # a snare is held for as long as it rings, within this
DIP_S = 0.06  # a hit has let go this long before the same light is hit again: every hit is seen
MIN_NOTE = (0.05, 0.08)  # …and a note cut short for that keeps this hold and this release at least
# how much of the rig a line-up has at least, by the rig's size: a handful of lights all play all the time, a
# big rig has the room to let groups sit out (and families differ in size: it counts lights, not families)
SMALL_RIG, BIG_RIG = 8, 60  # lights
LINEUP_LIGHTS = (1.0, 0.4)  # the share of them in a line-up: a small rig, a big one (in between: in between)
NEAR_S = 0.06  # two parts this close play one sound: the drums' hit stands, then the guitar's
MOTIF_NOTES = 8  # a run of the guitar moves on to its next family after this many notes
GUITAR_CHORD = (0.75, 0.25)  # a note this strong (against the ones around it) that rings this long: a chord
NOTE_LOCAL_S = 8.0  # a guitar note's strength: against the strong notes within this
OPENS_NEAR_S = 0.5  # a climax arrives on the drum hit this close to its phrase's start
FAST_HZ = 10.0  # with allow_fast_strobe, the strobes may flash this often
BED = (0.25, 0.35)  # the glow between hits: at the start of the build, and at its top
BED_RAMP_S = 0.6
BED_QUIET = (0.05, 0.15)  # bars as quiet as this (breath) are dark, the glow is all there from this: silences stay dark
MOVE_BARS = ((0.75, 1), (0.0, 2))  # the build this far: the heads change pictures every this many bars
MIN_MOVE_S = 1.5  # but not more often than this
MOVE_SNAP_S = 0.3  # a change of picture lands on the drummer's kick this close to it
PULSE_S = (0.3, 1.2)  # the music's pulse: the time between two kicks, when within this
SWAY_PULSES = (8.0, 4.0, 2.0)  # the heads sway once per this many pulses: a quiet phrase, a loud one, a climax
SWAY_DEG = (14.0, 16.0)  # how far they sway to the sides at most (as SWAY), and lift with the melody
SWAY_QUIET = 0.35  # the share of it in the quietest phrase
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
            self.ls_build = builds(self.a)
            self.ls_kit = drums.kit(self.a)
            self.duck_depth, self.own_attack_s = DUCK_DEPTH, OWN_ATTACK_S
            safety = rig["safety"]
            hz = 0.0 if safety.get("strobe_free") else float(safety.get("max_flash_hz", 4.0))
            if safety.get("allow_fast_strobe") and not safety.get("strobe_free"):
                hz = max(hz, FAST_HZ)
            self.ls_hz = hz  # the strobes; a light plays notes, at most max_flash_hz of them a second
            slow = float(safety.get("max_flash_hz", 4.0))
            self.ls_retrigger = 1.0 / slow if hz > 0 and slow > 0 else 0.5
            kt, st = np.asarray(self.ls_kit.kick_t, float), np.asarray(self.ls_kit.snare_t, float)
            gaps = np.diff(kt)
            gaps = gaps[(gaps >= PULSE_S[0]) & (gaps <= PULSE_S[1])]
            beats = np.diff(np.asarray(self.a.beats, float)) if len(self.a.beats) > 1 else np.zeros(0)
            self.ls_pulse = float(np.median(gaps)) if len(gaps) >= 8 else float(np.median(beats)) if len(beats) else 0.5
            # both drums on the same lights: only when the flash limit lets a light play the kick and the snare
            apart = np.abs(st[:, None] - kt[None, :]).min(axis=1) if len(st) and len(kt) else np.zeros(0)
            self.ls_both = not len(apart) or float(np.percentile(apart, 10)) >= self.ls_retrigger
        super()._init_cinematic(rig)
        if self.program == NAME:
            self._ls_bed()
            self._ls_sway()

    @property
    def CINE_VERSION(self):  # (the heads' cached trajectories: they follow the drummer too)
        if getattr(self, "program", "") != NAME:
            return VERSION
        k = self.ls_kit
        return [VERSION, len(k.kick_t), round(float(np.sum(k.kick_t)), 2), len(k.snare_t)]

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
        sizes = [sum(len(u) for u in s["units"]) for s in secs]
        lights = sum(sizes)
        self.ls_share = float(np.interp(lights, (SMALL_RIG, BIG_RIG), LINEUP_LIGHTS))
        # nobody sits out: a handful of lights, or a rig that can't miss even its smallest family
        self.ls_all_in = lights <= SMALL_RIG or lights - min(sizes, default=0) < self.ls_share * lights
        self.ls_layers = [n] * len(self.a.phrases) if self.ls_all_in else layers(self.a, n)

    def _orchestrate(self, i: int) -> dict:
        """Phrase i's score with every family it may use; `_ls_passages` plays it in line-ups of those."""
        if self.program != NAME:
            return super()._orchestrate(i)
        if not hasattr(self, "ls_order"):
            self._ls_seats()
        k = self.ls_layers[min(i, len(self.ls_layers) - 1)] if self.ls_layers else len(self.cine_sections)
        return self._ls_score(i, self.ls_order[:k], k)

    def _ls_score(self, i: int, active: list[int], top: int, turn: int = 0) -> dict:
        """The score of a line-up in phrase i, `top` families being what the phrase may use: who plays the kick,
        the snare, the guitar and the other voices. On a rig where nobody sits out, the families swap instruments
        from passage to passage (`turn`) instead."""
        n = len(self.cine_sections)
        rank = float(self.ls_ranks[min(i, len(self.ls_ranks) - 1)]) if len(self.ls_ranks) else 0.5
        build = float(self.ls_build[min(i, len(self.ls_build) - 1)]) if len(self.ls_build) else 1.0
        secs = self.cine_sections
        seats = self.ls_seats
        if self.ls_all_in and n > 1:
            order = [self.ls_order[(turn + q) % n] for q in range(n)]
            seats = {r: [s for q, s in enumerate(order) if ("low", "mid", "cymbal", "tick")[q % 4] == r] for r in ROLES}
        parts: dict[str, list[tuple[int, str]]] = {}
        for r, role in enumerate(ROLES):
            seated = [s for s in seats.get(role, []) if s in active]
            if not seated and active:  # not in yet: played by a family that is
                seated = [active[r % len(active)]]
            parts[role] = [(s, self._gesture(secs[s], role, i + 3 * r + q)) for q, s in enumerate(seated)]
        here = {r: [s for s in seats.get(r, []) if s in active] for r in ROLES}
        loud, climax = rank >= TOGETHER_FROM, rank >= CLIMAX
        kick, snare, guitar = list(here["low"]), list(here["mid"]), here["tick"] + here["cymbal"]
        if loud:  # the drums take half of the line-up each
            kick, snare = kick + here["tick"], snare + here["cymbal"]
        for side, other in ((kick, snare), (snare, kick)):  # a drum without a family of its own in the line-up
            if not side:
                spare = [s for s in active if s not in other]
                side += spare[: max(1, len(spare) // 2)] if not other else spare
            if not side:  # the other drum has them all: it gives up half, or (one family) they share it
                side += [other.pop()] if len(other) > 1 else other
        if climax and self.ls_both:  # …and at a climax all of it, both
            kick = snare = list(active)
        if not guitar:
            guitar = [s for s in active if s not in kick and s not in snare] or list(active)
        melody = max(active, key=lambda s: self._suits(secs[s], "melody"), default=None)
        pads = sorted((s for s in active if s != melody), key=lambda s: -self._suits(secs[s], "pad"))
        return {"parts": parts, "small": [s for s in active if not secs[s]["big"]], "melody": melody,
                "pad": pads[0] if pads else None, "rank": rank, "active": active, "full": len(active) >= n,
                "build": build, "loud": loud, "climax": climax, "kick": kick, "snare": snare,
                "guitar": [(s, self._gesture(secs[s], "tick", i + q)) for q, s in enumerate(guitar)]}  # fmt: skip

    def _ls_passages(self):
        """The line-ups: every PASSAGE_BARS bars of a phrase a score of its own. A passage with more families
        than the one before it in the phrase keeps those and adds to them (a layer); otherwise the line-up moves
        on through the families that have joined, by half of itself: some stay, the others take over."""
        bars = np.asarray(self.downbeat_times, float)
        self.ls_times: list[float] = []
        self.ls_scores: list[dict] = []
        joined = turn = before = 0
        size = [sum(len(u) for u in s["units"]) for s in self.cine_sections]
        for i, d in enumerate(self.plan):
            phrase = self.cine_score[min(i, len(self.cine_score) - 1)]
            top = len(phrase["active"])
            joined = max(joined, top)
            pool = self.ls_order[:joined]
            inside = bars[(bars > d.start + 1e-3) & (bars < d.end)]
            starts = [d.start, *(float(b) for b in inside[PASSAGE_BARS - 1 :: PASSAGE_BARS])]
            climax = phrase["rank"] >= CLIMAX
            opens = climax and d.section == "drop" and (i == 0 or self.plan[i - 1].section != "drop")
            sizes = [top] * len(starts) if self.ls_all_in else passages(top, len(starts), climax, opens)
            for j, (t, k) in enumerate(zip(starts, sizes)):
                if not pool:
                    self.ls_times.append(t)
                    self.ls_scores.append(phrase)
                    continue
                if not (j and k > before):
                    turn += max(1, k // 2)
                before = k
                lineup = [pool[(turn + q) % len(pool)] for q in range(k)]
                for s_ in pool[turn % len(pool) :] + pool[: turn % len(pool)]:  # a few small families: not enough
                    if sum(size[x] for x in lineup) >= self.ls_share * sum(size):
                        break
                    if s_ not in lineup:
                        lineup.append(s_)
                self.ls_times.append(t)
                self.ls_scores.append(self._ls_score(i, lineup, top, turn))
        kit = self.ls_kit
        for q, score in enumerate(self.ls_scores):  # a drum that doesn't play here: its families play the guitar
            a, b = self.ls_times[q], self.ls_times[q + 1] if q + 1 < len(self.ls_times) else float(self.a.duration)
            if "kick" not in score:
                continue
            idle = [
                side for side, ts in (("kick", kit.kick_t), ("snare", kit.snare_t)) if not np.any((ts >= a) & (ts < b))
            ]
            extra = [s_ for side in idle for s_ in score[side] if s_ not in {g for g, _ in score["guitar"]}]
            if extra:
                extra = list(dict.fromkeys(extra))
                more = [(s_, self._gesture(self.cine_sections[s_], "tick", q + j)) for j, s_ in enumerate(extra)]
                self.ls_scores[q] = {**score, "guitar": score["guitar"] + more}

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

    def _ls_cues(self) -> dict[str, list[tuple]]:
        """What there is to play, per part, each in time order, as (time, strength, how long it sounds, pitch, role):
        the impacts, the drums (the kit's kicks and snares), the guitar's notes, and the rest of the hits (by
        their voice). A sound two parts found is played once: by the impact, else the drum, else the guitar."""
        h, kit = self.cine_hits, self.ls_kit
        ht = np.asarray(h.t, float)
        impacts = [(float(ht[k]), 1.0, 0.25, 0.5, "impact") for k in np.flatnonzero(h.impact)]
        taken = np.array(sorted(c[0] for c in impacts))

        def near(t, ts=None):
            ts = taken if ts is None else ts
            if not len(ts):
                return False
            k = int(np.searchsorted(ts, t))
            return any(abs(ts[x] - t) < NEAR_S for x in (k - 1, k) if 0 <= x < len(ts))

        hit = sorted(
            [(float(t), float(v), float(self.ls_pulse), 0.0, "kick") for t, v in zip(kit.kick_t, kit.kick_s)]
            + [
                (float(t), float(v), float(r), 0.5, "snare")
                for t, v, r in zip(kit.snare_t, kit.snare_s, kit.snare_ring)
            ]
        )
        hit = [c for c in hit if not near(c[0])]
        # a climax arrives on an impact of its own: the drum hit its phrase starts on
        for i, d in enumerate(self.plan):
            r = self.ls_ranks
            if i < len(r) and r[i] >= CLIMAX and (i == 0 or r[i - 1] < CLIMAX) and hit:
                k = min(range(len(hit)), key=lambda q: abs(hit[q][0] - d.start))
                if abs(hit[k][0] - d.start) <= OPENS_NEAR_S:
                    impacts.append((hit[k][0], 1.0, 0.25, 0.5, "impact"))
                    del hit[k]
        impacts.sort()
        taken = np.array(sorted([c[0] for c in impacts] + [c[0] for c in hit]))

        guitar = []
        notes = self.a.synth_notes
        if notes is not None and len(notes[0]):
            nt, ns, npitch = (np.asarray(x, float) for x in notes)
            if len(npitch):
                lo, hi = np.percentile(npitch, 5), np.percentile(npitch, 95)
                npitch = np.clip((npitch - lo) / max(hi - lo, 1e-6), 0, 1)
            a_, b_ = np.searchsorted(nt, nt - NOTE_LOCAL_S), np.searchsorted(nt, nt + NOTE_LOCAL_S)
            ref = np.array([np.percentile(ns[x:y], 90) for x, y in zip(a_, b_)])  # the strong notes around it
            rel = np.clip(ns / np.maximum(ref, 1e-6), 0, 1)
            nxt = np.r_[np.diff(nt), 1.0]
            last = -1e9
            for t, v, g, pch in zip(nt, rel, nxt, npitch):
                if t - last >= NEAR_S and not near(float(t)):
                    guitar.append((float(t), float(v), float(g), float(pch), "guitar"))
                    last = t
            taken = np.array(sorted(list(taken) + [c[0] for c in guitar]))

        next_same = np.full(len(h), 1.0)  # per hit: time until its voice plays again
        last_of: dict[int, int] = {}
        for k in range(len(h) - 1, -1, -1):
            v = int(h.voice[k])
            if v in last_of:
                next_same[k] = float(ht[last_of[v]] - ht[k])
            last_of[v] = k
        strong, rest = [], []
        for k in np.flatnonzero(~np.asarray(h.impact, bool)):
            if near(float(ht[k])):
                continue  # the drummer or the guitar plays this one
            c = (float(ht[k]), float(h.strength[k]), max(float(h.decay[k]), float(next_same[k])), float(h.pitch[k]),
                 self._role_of(int(h.voice[k])))  # fmt: skip
            (strong if c[1] >= STRONG else rest).append(c)
        return {"impact": impacts, "drums": hit, "strong": strong, "guitar": guitar, "rest": rest}

    def _cine_events(self):
        """Every cue → which lights flash, how bright, in what colour (see the module's description). The parts
        are placed in order of importance (the impacts, the drums, the strong hits, the guitar, the rest): a
        light is free for a hit when nothing was placed on it within the flash limit, before or after."""
        if self.program != NAME:
            return super()._cine_events()
        self._ls_passages()
        cues = self._ls_cues()
        events: dict[str, list[tuple]] = {}
        busy: dict[str, list[float]] = {}
        gap = self.ls_retrigger - 1e-6

        def free(eid, t):
            b = busy.get(eid)
            if not b:
                return True
            k = bisect.bisect_left(b, t)
            return (k == 0 or t - b[k - 1] >= gap) and (k == len(b) or b[k] - t >= gap)

        def play(ids, t, level, hold, fade, colour, impact=False, trim=BIG_TRIM):
            for eid in ids:
                bisect.insort(busy.setdefault(eid, []), t)
                lv = 1.0 if impact else snap(level * (1 - trim * self.cine_power.get(eid, 0.0)))
                events.setdefault(eid, []).append((t, lv, hold, fade, colour, impact))

        strobed: list[float] = []
        self.cine_played = []
        members = [[i for u in s["units"] for i in u] for s in self.cine_sections]

        def strobe(t):
            if self.ls_hz <= 0:
                return
            k = bisect.bisect_left(strobed, t)
            period = 1.0 / self.ls_hz - 1e-6
            if (k == 0 or t - strobed[k - 1] >= period) and (k == len(strobed) or strobed[k] - t >= period):
                strobed.insert(k, t)
                for eid in self.cine_strobes:
                    events.setdefault(eid, []).append((t, 1.0, 0.05, 0.0, WHITE, True))

        def at(t):
            i, d = self.decision_at(t)
            return d, self._colours(d), self._score_at(t, i)

        for t, *_ in cues["impact"]:
            d, cols, score = at(t)
            specials = score["build"] >= SPECIALS_FROM
            whole = specials and (score["full"] or t - d.start < OPENS_S)
            pool = range(len(members)) if whole else score["active"]
            ids = [eid for si in pool for eid in members[si] if free(eid, t)]
            play(ids, t, 1.0, 0.25, 0.5, WHITE if specials else cols[2 % len(cols)], impact=True)
            if specials:
                strobe(t)
                for eid in self.cine_lasers:
                    if free(eid, t):
                        bisect.insort(busy.setdefault(eid, []), t)
                        events.setdefault(eid, []).append((t, 1.0, 0.6, 0.0, cols[0], True))
            self.cine_played.append((t, 1.0))

        for t, s, sounds, _, drum in cues["drums"]:  # the drummer: whole families, full
            d, cols, score = at(t)
            ids = [eid for si in score[drum] for eid in members[si] if free(eid, t)]
            if not ids:
                continue
            if drum == "kick":
                hold, fade, colour = *KICK_NOTE, cols[0]
            else:  # white once it's loud, and held for as long as it rings
                hold, fade = float(np.clip(sounds, *SNARE_HOLD_S)), RELEASE_S
                colour = WHITE if score["loud"] else cols[2 % len(cols)]
            play(ids, t, 0.85 + 0.3 * s, hold, fade, colour, trim=0.0)  # (the powerful lights too: full)
            if score["climax"] and score["build"] >= SPECIALS_FROM and s >= DRUM_HIT:
                strobe(t)  # the climax: the strobes play the drums
            self.cine_played.append((t, 1.0))

        for t, _s, sounds, _, role in cues["strong"]:  # every family that plays, at once, white
            d, cols, score = at(t)
            specials = score["build"] >= SPECIALS_FROM
            ids = [eid for si in score["active"] for eid in members[si] if free(eid, t)]
            if ids:
                hold = float(np.clip(0.5 * sounds, *HOLD_S))
                fade = RELEASE_S * (2 if role == "low" else 1)
                play(ids, t, 1.0, hold, fade, WHITE if specials else cols[1 % len(cols)])
                self.cine_played.append((t, 1.0))
            if specials:
                strobe(t)

        def gesture(si, g, step, m, pitch, t, level, hold, fade, colour) -> bool:
            """A family's next step of a gesture, on lights that are free; whether it was played."""
            sec = self.cine_sections[si]
            g = g if sec["pixel"] or g not in ("steps", "keys") else "chase"
            pool = sec["segments"] if g in ("steps", "keys") else sec["units"]
            for option in self._members(sec, g, step, m, pitch):
                ids = [eid for o in option for eid in pool[o]]
                if ids and all(free(eid, t) for eid in ids):
                    play(ids, t, level, hold, fade, colour)
                    return True
            return False

        last, m, step = -1e9, -1, 0
        for t, s, sounds, pitch, _ in cues["guitar"]:  # the guitar: a run over its families, a chord by all
            d, cols, score = at(t)
            fams = score["guitar"]
            if not fams:
                continue
            if t - last > MOTIF_GAP_S or step >= MOTIF_NOTES:
                m, step = m + 1, 0
            last, step = t, step + 1
            hold = float(np.clip(0.5 * sounds, *HOLD_S))
            colour = cols[1 % len(cols)]
            if s >= GUITAR_CHORD[0] and sounds >= GUITAR_CHORD[1]:
                ids = [eid for si, _ in fams for eid in members[si] if free(eid, t)]
                if ids:
                    play(ids, t, 1.0, hold, RELEASE_S, colour)
                    self.cine_played.append((t, 1.0))
                continue
            own = [fams[m % len(fams)]]
            spill = [(si, "chase") for si in score["active"] if si != own[0][0]]
            level = 0.7 + 0.3 * s
            for si, g in own + spill:
                if gesture(si, g, step - 1, m, pitch, t, level, hold, RELEASE_S, colour):
                    self.cine_played.append((t, level))
                    break

        motif = {r: [-1e9, -1, 0] for r in ROLES}
        for t, s, sounds, pitch, role in cues["rest"]:
            d, cols, score = at(t)
            seated = score["parts"][role]
            if not seated:
                continue
            last, m, step = motif[role]
            if t - last > MOTIF_GAP_S:
                m, step = m + 1, 0
            motif[role] = [t, m, step + 1]
            hold = float(np.clip(0.5 * sounds, *HOLD_S))
            fade = RELEASE_S * (2 if role == "low" else 1)
            # the instrument's families: together when the music is loud, else taking turns motif by motif
            playing = seated if score["loud"] else [seated[m % len(seated)]]
            if s < BIG_HIT and score["small"]:  # a weak hit: the powerful families leave it to the small ones
                playing = [x for x in playing if not self.cine_sections[x[0]]["big"]] or [
                    (score["small"][m % len(score["small"])], "chase")
                ]
            spill = [(si, "chase") for si in score["active"] if si not in {x[0] for x in playing}]
            level = s**0.3
            any_played = False
            for q, (si, g) in enumerate(playing + spill):
                if any_played and q >= len(playing):
                    break
                colour = cols[(ROLES.index(role) + q) % len(cols)]
                any_played |= gesture(si, g, step, m, pitch, t, level, hold, fade, colour)
            if any_played:
                self.cine_played.append((t, level))

        self.cine_played.sort()
        self.cine_events = {}
        for eid, ev in events.items():
            ev.sort(key=lambda e: e[0])
            for k in range(len(ev) - 1):  # let go before the next hit on this light: every hit is a new flash
                t0, lv, hold, fade, colour, impact = ev[k]
                room = ev[k + 1][0] - t0 - DIP_S
                if hold + fade > room > 0 and fade > 0:
                    fade = min(fade, max(MIN_NOTE[1], 0.4 * room))
                    ev[k] = (t0, lv, max(MIN_NOTE[0], min(hold, room - fade)), fade, colour, impact)
            self.cine_events[eid] = (np.array([e[0] for e in ev]), ev)
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
        kicks = np.asarray(self.ls_kit.kick_t, float)
        fixed = set(impacts)

        def on_the_kick(m):  # the bar lines of the analysis can be off the drummer's: his kick is the cue
            if m in fixed or not len(kicks):
                return m
            k = kicks[int(np.argmin(np.abs(kicks - m)))]
            return float(k) if abs(k - m) <= MOVE_SNAP_S else m

        kept: list[float] = []
        for m in sorted({on_the_kick(m) for m in moves}):
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
        """Per family, its glow over time: while it is in the line-up, at the build's level, ramped in and out."""
        grid = self._grid()
        bars = np.interp(grid, np.arange(len(self.breath)) / self.a.fps, self.breath)
        gate = np.clip((bars - BED_QUIET[0]) / (BED_QUIET[1] - BED_QUIET[0]), 0, 1)
        step = 1 / (BED_RAMP_S * GRID_HZ)
        self.ls_beds = []
        for si in range(len(self.cine_sections)):
            want = np.zeros(len(grid))
            for q, score in enumerate(self.ls_scores):
                if si in score["active"]:
                    a = int(self.ls_times[q] * GRID_HZ)
                    b = int(self.ls_times[q + 1] * GRID_HZ) if q + 1 < len(self.ls_times) else len(grid)
                    want[a:b] = BED[0] + (BED[1] - BED[0]) * score["build"]
            y, out = 0.0, np.zeros(len(grid))
            for k, v in enumerate(want):  # a slow ramp: never wobbling with the music
                y += float(np.clip(v - y, -step * BED[1], step * BED[1]))
                out[k] = y
            self.ls_beds.append(out * gate)

    def _ls_sway(self):
        """How the heads sway around their picture over time: how far (wider as the music gets louder) and where
        in the swing they are (once per a few of the music's pulses, faster as it gets louder)."""
        grid = self._grid()
        amp, rate = np.zeros(len(grid)), np.zeros(len(grid))
        for i, d in enumerate(self.plan):
            rank = float(self.ls_ranks[min(i, len(self.ls_ranks) - 1)]) if len(self.ls_ranks) else 0.5
            pulses = SWAY_PULSES[2] if rank >= CLIMAX else SWAY_PULSES[1] if rank >= TOGETHER_FROM else SWAY_PULSES[0]
            a, b = int(d.start * GRID_HZ), min(int(d.end * GRID_HZ), len(grid))
            amp[a:b] = SWAY_QUIET + (1 - SWAY_QUIET) * rank
            rate[a:b] = 1.0 / (pulses * self.ls_pulse)
        w = GRID_HZ  # a second from one phrase's sway to the next
        self.ls_sway_amp = np.convolve(amp, np.ones(w) / w, mode="same")
        self.ls_sway_turns = np.cumsum(rate) / GRID_HZ

    def _cinematic_head_dirs(self, ts: np.ndarray, j: int) -> np.ndarray:
        if self.program != NAME:
            return super()._cinematic_head_dirs(ts, j)
        q = np.searchsorted(self.cine_moves, ts + PRE_IMPACT_S, side="right")  # already at the coming picture
        az = np.array([self.cine_pictures[k % len(self.cine_pictures)][j][0] for k in q])
        el = np.array([self.cine_pictures[k % len(self.cine_pictures)][j][1] for k in q])
        grid = np.arange(len(self.cine_fill)) / GRID_HZ
        fill = np.maximum(np.interp(ts, grid, self.cine_fill), SWAY_QUIET)
        contour = np.interp(ts, grid, self.cine_contour)
        amp = np.maximum(np.interp(ts, grid, self.ls_sway_amp[: len(grid)]), fill)
        turns = np.interp(ts, grid, self.ls_sway_turns[: len(grid)])
        az = az + amp * SWAY_DEG[0] * np.sin(2 * np.pi * turns + j * 0.9)
        el = el + fill * SWAY_DEG[1] * (contour - 0.5)
        out = self._direction_v(az, el)
        head_pos = self.head_pos[j]
        if self.zones.heads:
            out = self.zones.filter(head_pos, out)
        out = self._room_safe_v(out, j)  # off the ceiling, not back at the DJ, not into the rig
        return self._eye_safe_v(out, head_pos[2])

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
