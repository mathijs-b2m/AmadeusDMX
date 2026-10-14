"""Scene engine: turns (time, decisions, analysis) into fixture states and DMX.

The engine is stateless with respect to time: `render(t)` only reads
precomputed arrays, so seeking and real-time playback behave identically.
All white flashes and strobe hits go through one precomputed, rate-limited
flash timeline (see `safety.max_flash_hz`).

The work is split by concern: `timing` (beats, bars, phrases), `looks` (colours,
levels, hits), `motion` (where heads point and how their motors get there) and
`lasers` (shapes and the laser guard). `Engine` ties them together.
"""

from __future__ import annotations

import numpy as np

from amadeus.audio.model import DROP_THRESHOLD, Analysis
from amadeus.director import Decision
from amadeus.engine import zones
from amadeus.engine.cinematic import CinematicMixin
from amadeus.engine.fog import FogMixin
from amadeus.engine.lasers import LasersMixin
from amadeus.engine.looks import DROP_DARK_FROM, XFADE, LooksMixin
from amadeus.engine.motion import DMX_LEAD_S, MOTION_FPS, MotionMixin
from amadeus.engine.state import State
from amadeus.engine.timing import TimingMixin, _ease, note_env, pick_stabs
from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry

PICKUP_LEAD = 0.65  # a section that leads in early: how far its look has come in by the downbeat (which lands it)


class Engine(TimingMixin, LooksMixin, MotionMixin, LasersMixin, CinematicMixin, FogMixin):
    def __init__(
        self, analysis: Analysis, plan: list[Decision], rig: dict, real_output: bool = False, fog_carry: bool = False
    ):
        """`real_output`: the DMX goes to real lights, so the laser guard insists on laser zones. `fog_carry`: a
        track in a live set: the room is already hazy from the one before (engine/fog.py)."""
        self.a = analysis
        self.real_output = real_output
        self.fog_carry = fog_carry
        self.colour_variety: float | None = None  # the show arc's knob, set live (looks.py); None: as designed
        self.drop_strength: float | None = None  # … how big drops land (looks.py, _drop_moment); None: full
        self.plan = plan
        self.rig = rig
        self.starts = [d.start for d in plan]
        self.pars = sorted([e for e in rig["elements"] if e["kind"] == "par"], key=lambda e: e["x"])
        self.heads = sorted([e for e in rig["elements"] if e["kind"] == "head"], key=lambda e: e["x"])
        defs = {f["id"]: fxlib.get(f["fixture"]) for f in rig["fixtures"]}
        self.wheels = {e["id"]: defs[e["fixture"]] for e in rig["elements"] if fxlib.has_wheel(defs[e["fixture"]])}
        self.order = {f["id"]: i for i, f in enumerate(self.pars)}
        self.beats = analysis.beats
        self.downbeat_times = analysis.beats[analysis.downbeats] if len(analysis.downbeats) else analysis.beats[::4]
        self.downbeat_s = np.ones(len(self.downbeat_times), dtype=np.float32)
        # subdivisions of the beat grid: exact 1/8 and 1/16 notes (accent slightly on the beat itself)
        b = analysis.beats
        if len(b) > 1:
            steps = np.diff(b)
            self.eighth_t = np.sort(np.concatenate([b, b[:-1] + steps / 2]))
            self.sixteenth_t = np.sort(np.concatenate([b, *(b[:-1] + steps * q / 4 for q in (1, 2, 3))]))
        else:
            self.eighth_t = self.sixteenth_t = b
        on_beat = lambda ts: np.where(np.isin(ts, b), 1.0, 0.75).astype(np.float32)  # noqa: E731
        self.eighth_s, self.sixteenth_s = on_beat(self.eighth_t), on_beat(self.sixteenth_t)
        # synth riff: melodic onsets snapped onto the 1/16 grid; off-grid notes (vocals, loose notes) dropped
        lt, ls = analysis.onsets.get("lead", (np.zeros(0), np.zeros(0)))
        if len(lt) and len(self.sixteenth_t):
            k = np.clip(np.searchsorted(self.sixteenth_t, lt), 1, len(self.sixteenth_t) - 1)
            near = np.where(np.abs(self.sixteenth_t[k - 1] - lt) < np.abs(self.sixteenth_t[k] - lt), k - 1, k)
            ok = np.abs(self.sixteenth_t[near] - lt) < 0.02  # only notes that really sit on the grid
            snapped, idx = np.unique(self.sixteenth_t[near[ok]], return_index=True)
            self.synth_t, self.synth_s = snapped, np.asarray(ls)[ok][idx].astype(np.float32)
        else:
            self.synth_t, self.synth_s = np.zeros(0), np.zeros(0, np.float32)
        self.kick_t, self.kick_s = analysis.onsets["kick"]
        self.snare_t, self.snare_s = analysis.onsets["snare"]
        self.hat_t, self.hat_s = analysis.onsets["hat"]
        self.acc_t, self.acc_s = analysis.onsets["accent"]
        self.lead_t, self.lead_s = analysis.onsets.get("lead", (np.zeros(0), np.zeros(0)))
        n = len(analysis.rms_db)
        self.lead_pitch = analysis.lead_pitch if analysis.lead_pitch is not None else np.full(n, 0.5, np.float32)
        self.lead_pc = analysis.lead_pc if analysis.lead_pc is not None else np.full(n, -1, np.int8)
        self.stut_gate = analysis.stutter_gate if analysis.stutter_gate is not None else np.zeros(n, np.float32)
        self.stut_str = analysis.stutter_strength if analysis.stutter_strength is not None else np.zeros(n, np.float32)
        self.lead_env = self._local_envelope(
            np.maximum(analysis.bands_db["mid"], analysis.bands_db["high"]), analysis.fps
        )
        # Light doesn't follow the volume syllable by syllable: an operator rides the fader per bar, in
        # straight lines. breath: the loudness per bar, ramped linearly from bar to bar.
        self.breath = self._bar_ramp(
            np.maximum(analysis.bands_db["mid"], analysis.bands_db["high"]), deadband=0.08, relative_bars=8
        )
        self.kick_breaks = self._kick_breaks()  # where the kick drops out: hold, build, hit on its return
        self.low = np.maximum(analysis.band_norm("sub"), analysis.band_norm("bass"))
        self.level = analysis.band_norm("mid") * 0.5 + self.low * 0.5
        self.flash_t, self.flash_s = self._flash_timeline(rig["safety"]["max_flash_hz"])
        self.stage = geometry.stage(rig)
        fixtures = {f["id"]: f for f in rig["fixtures"]}
        self.head_pos = [np.array(geometry.position(rig, e, fixtures[e["fixture"]])) for e in self.heads]
        self.zones = zones.Zones(rig)  # where beams may (not) go: drawn in the rig editor
        self.head_fx = [(fixtures[e["fixture"]], fxlib.get(fixtures[e["fixture"]]["fixture"])) for e in self.heads]
        self._init_high_risk(rig, fixtures)
        self._init_groups(rig)
        self._init_lasers(rig, fixtures)
        self._init_fog(rig, fixtures)
        # synth/melody notes for the lasers to play: from the separated synth instrument when available
        if analysis.synth_notes is not None and len(analysis.synth_notes[0]):
            self.syn_t, self.syn_s, self.syn_p = (np.asarray(x, float) for x in analysis.synth_notes)
        else:  # fallback: the band-based melody onsets, pitch from the lead contour
            lt, ls = analysis.onsets.get("lead", (np.zeros(0), np.zeros(0)))
            self.syn_t, self.syn_s = np.asarray(lt, float), np.asarray(ls, float)
            lp = analysis.lead_pitch if analysis.lead_pitch is not None else np.zeros(1)
            self.syn_p = np.array([float(lp[min(int(x * analysis.fps), len(lp) - 1)]) for x in lt])
        self.stab_t, self.stab_s = pick_stabs(self.syn_t, self.syn_s)  # the synth's key hits, for accent lights
        self.accent_family: list[str] = [""] * len(plan)  # per phrase: the instrument the accent lights follow
        self._stabs_per_instrument(analysis)
        self.gobo_groups = [
            {k: v for k, v in defn.get("gobo_groups", {}).items() if not k.startswith("_")} for _, defn in self.head_fx
        ]
        self.gobo_all = [
            list(range(1, len(defn.get("beam_fx", {}).get("gobo", {}).get("gobo", [0])) + 1))
            for _, defn in self.head_fx
        ]
        self.drop_idx = {i for i, d in enumerate(plan) if getattr(d, "drop_score", 0) >= DROP_THRESHOLD}
        on = analysis.onsets
        self.fill_t = np.sort(np.concatenate([on["snare"][0], on["accent"][0]])) if on else np.zeros(0)  # fill hits
        self.drops = [plan[i].start for i in sorted(self.drop_idx)]
        self.goals: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._reach_uv = (1.0, 1.0)
        self.move_beats: dict[int, tuple[int, int]] = {}
        self.move_travel: dict[int, tuple[float, float]] = {}
        self.reach_uv = [self._reach(j) for j in range(len(self.heads))]
        self._move_beats = (1, 1)
        self._move_travel = (0.9, 0.9)
        # a program of its own for the genre (cinematic: every hit played by its own fixtures)
        self.program = (
            "cinematic" if getattr(analysis, "genre", "") == "cinematic" and analysis.hits is not None else ""
        )
        if self.program == "cinematic":
            self._init_cinematic(rig)
        self.traj = self._cached_trajectories()
        self._share_motors()
        self.traj_n = len(next(iter(self.traj.values()))[0]) if self.traj else 2

    def _init_groups(self, rig: dict):
        """Each head's place: its group (overhead, back, front, tower ...), index and count in the group."""
        from amadeus.rig.groups import head_groups

        self.groups = head_groups(rig)
        self.multi = len(self.groups) > 1
        self._z_median = float(np.median([p[2] for p in self.head_pos])) if self.head_pos else 0.0
        idx = {e["id"]: j for j, e in enumerate(self.heads)}
        n = len(self.heads)
        self.hgroup = [
            {"g": 0, "k": j, "m": n, "cls": "all", "name": "all", "kind": "row", "gside": 0.0} for j in range(n)
        ]
        self.group_centre, self.group_width = [], []
        for gi, g in enumerate(self.groups):
            P = np.array([self.head_pos[idx[h]] for h in g["ids"] if h in idx]) if g["ids"] else np.zeros((1, 3))
            self.group_centre.append(P.mean(0))
            self.group_width.append(float(np.ptp(P[:, 0])) if len(P) > 1 else 0.0)
            for k, hid in enumerate(g["ids"]):
                if hid in idx:
                    self.hgroup[idx[hid]] = {
                        "g": gi,
                        "k": k,
                        "m": len(g["ids"]),
                        "cls": g["cls"],
                        "name": g["name"],
                        "kind": g["kind"],
                        "gside": g["side"],
                    }

    # ------------------------------------------------------------ public

    def render(self, t: float) -> tuple[int, dict[str, State]]:
        i, d = self.decision_at(t)
        if self.program == "cinematic":
            return i, self._finish(self._cinematic_scene(t), t)
        states = self._scene(d, t)
        big = self.drop_strength is None or self.drop_strength >= DROP_DARK_FROM  # (small drops: no moving in black)
        ahead = self._drop_ahead(i, t) if big else None
        if ahead is not None:  # heads take the drop's colour/gobo/prism while dark, so the wheels are ready
            drop_look = self._scene(self.plan[ahead], t)
            for e in self.heads:
                s = drop_look[e["id"]]
                s.dimmer, s.white = 0.0, 0.0
                states[e["id"]] = s
        states = self._pickup(i, t, states)
        if i > 0 and t - d.start < XFADE and i not in self.drop_idx and not self._led_in(i):  # drops: a hard cut
            prev = self._scene(self.plan[i - 1], t)
            k = _ease((t - d.start) / XFADE)
            states = {fid: prev[fid].blend(s, k) for fid, s in states.items()}
        self._kick_return(t, states)
        self._drop_moment(t, states)
        return i, self._finish(states, t)

    def _pickup_of(self, i: int):
        """Phrase i's anacrusis (it starts before its downbeat), if it has one the lights act on: not into a
        drop (the drop moment has its own timing)."""
        if not 0 < i < len(self.plan) or i in self.drop_idx or i >= len(self.a.phrases):
            return None
        p = self.a.phrases[i]
        return p if getattr(p, "pickup_beats", 0) and p.pickup_start < self.plan[i].start else None

    def _led_in(self, i: int) -> bool:
        p = self._pickup_of(i)
        return p is not None and p.pickup_kind == "early"

    def _pickup(self, i: int, t: float, states: dict[str, State]) -> dict[str, State]:
        """The next section starts before its downbeat: a vocal or melody leading in brings its look in early
        (about two thirds there by the downbeat, which lands it); a fill is played by the lights, beat by beat,
        in the next section's accent colour, growing into the downbeat."""
        p = self._pickup_of(i + 1)
        if p is None or not p.pickup_start <= t < self.plan[i + 1].start:
            return states
        nxt = self.plan[i + 1]
        progress = (t - p.pickup_start) / max(nxt.start - p.pickup_start, 1e-6)
        if p.pickup_kind == "early":
            ahead = self._scene(nxt, t)
            k = PICKUP_LEAD * _ease(progress)
            return {fid: s.blend(ahead[fid], k) for fid, s in states.items()}
        hits = self.fill_t[(self.fill_t >= p.pickup_start - 0.02) & (self.fill_t <= t)]
        if not len(hits):
            return states
        beats = self.beats[self.beats >= p.pickup_start - 0.02]  # the fill on the beats (not snare by snare)
        v = note_env(beats, np.ones(len(beats)), t)[0] * (0.55 + 0.45 * progress)
        cols = self._colours(nxt)
        accent = cols[2 % len(cols)]
        for e in self.pars + self.heads:
            s = states[e["id"]]
            if v > s.dimmer:
                s.dimmer = v
                s.r, s.g, s.b = accent
        return states

    def _init_high_risk(self, rig: dict, fixtures: dict):
        """Risk group 2 and 3 fixtures (fixtures.high_risk) stay dark when the DMX goes to real lights: this is
        alpha software, not for a powerful rig in front of an audience. The visualiser still shows them."""
        risky = sorted({f["id"] for f in fixtures.values() if fxlib.high_risk(fxlib.get(f["fixture"]))})
        self.dark_high_risk = [e["id"] for e in rig["elements"] if e["fixture"] in risky] if self.real_output else []
        if self.dark_high_risk:
            notes = self.__dict__.setdefault("guard_notes", {})
            for eid in self.dark_high_risk:
                notes[eid] = "dark: risk group 2/3 fixture (not driven by this alpha version)"
            print(
                f"  ⚠ {', '.join(risky)}: risk group 2/3, stays dark with real lights in this alpha version", flush=True
            )

    def _finish(self, states: dict[str, State], t: float) -> dict[str, State]:
        """What every look gets last: the heads' real and target positions, dark while crossing the eye band,
        colours the wheels can make, the smoke machines, and the laser guard."""
        self._fog(states, t)
        f = t * MOTION_FPS
        i0 = int(min(max(f, 0), self.traj_n - 2))
        k = min(max(f - i0, 0.0), 1.0)
        fl = (t + DMX_LEAD_S) * MOTION_FPS
        g0 = int(min(max(fl, 0), self.traj_n - 2))
        gk = min(max(fl - g0, 0.0), 1.0)
        for j, (eid, (pan, tilt)) in enumerate(self.traj.items()):
            s = states[eid]
            s.pan = float(pan[i0] + (pan[i0 + 1] - pan[i0]) * k)  # where the head actually is (predicted)
            s.tilt = float(tilt[i0] + (tilt[i0 + 1] - tilt[i0]) * k)
            gp, gt = self.goals[eid]  # where we tell it to go, a little early
            s.dmx_pan = float(gp[g0] + (gp[g0 + 1] - gp[g0]) * gk)
            s.dmx_tilt = float(gt[g0] + (gt[g0 + 1] - gt[g0]) * gk)
            # Targets are eye-safe, but the path between them may cross the audience's eye band
            # (e.g. sky → crowd). Like "blackout by movement" on real heads: dark while crossing.
            fx, defn = self.head_fx[j]
            if geometry.in_eye_band(geometry.fk(fx, defn, s.pan, s.tilt), self.head_pos[j][2], self.stage):
                s.dimmer, s.white = 0.0, 0.0
        for eid in self.dark_high_risk:  # risk group 2/3 with real lights: dark (alpha software)
            states[eid].dimmer, states[eid].white = 0.0, 0.0
        for eid, defn in self.wheels.items():  # show only colours the wheel can actually make
            s = states[eid]
            # A mechanical wheel can't follow 70 ms white flashes: those become a dimmer bump instead.
            slot = fxlib.nearest_slot(defn, (s.r, s.g, s.b))
            s.r, s.g, s.b = slot["rgb"]
            s.dimmer, s.white = max(s.dimmer, s.white), 0.0
        if self.lasers:  # the very last word: nothing after this may light a laser again
            self._laser_guard(states, t)
        return states

    def dmx(self, states: dict[str, State]) -> dict[int, bytearray]:
        """Patch element states into one 512-byte buffer per universe."""
        unis: dict[int, bytearray] = {}
        for f in self.rig["fixtures"]:
            fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
        return unis
