"""The musical clock: beats, bars, phrases, the flash timeline and the bar-by-bar envelopes."""

from __future__ import annotations

import bisect
import math

import numpy as np

from decisive.director import Decision


def _decay(times: np.ndarray, strengths: np.ndarray, t: float, tau: float) -> float:
    """Envelope of the most recent events before t, exponentially decaying."""
    i = bisect.bisect_right(times, t)
    best = 0.0
    for j in range(max(0, i - 3), i):
        best = max(best, float(strengths[j]) * math.exp(-(t - times[j]) / tau))
    return best


FLASH_SNAP_S = 0.1  # a big accent this close to a kick flashes with it (further off: no flash)
MIN_GAP_S = 0.3  # hits closer together than this are held through: a light never flickers faster
NO_KICK_S = 2.0  # no kick for this long (a breakdown): kick-led light holds a steady middle level
STAB_GAP_S = 0.35  # accent lights: stabs at least this far apart (no flicker)
STAB_STANDOUT = 1.4  # a stab: a synth note this much stronger than the notes around it…
STAB_REST_S = 0.2  # …or one that comes after a rest this long
STAB_HOLD_S, STAB_RELEASE_S = 0.06, 0.16  # the flash: on at once, held a moment, let go quickly but softly
BREAK_MAX_BARS = 8  # a kick break builds over at most this many bars (the ones before the kick returns)
BREAK_FROM, BREAK_TO = 0.35, 0.85  # kick break: kick-led light holds, building from this level to that


def _release(dt: float, level: float, hold: float, release: float) -> float:
    """Held at `level` for `hold`, then let go gently (a soft curve) over `release`."""
    if dt < hold:
        return level
    if dt < hold + release:
        return level * 0.5 * (1 + math.cos(math.pi * (dt - hold) / release))
    return 0.0


def note_env(times: np.ndarray, strengths: np.ndarray, t: float) -> tuple[float, int]:
    """A light played like a note on each hit: on at once (to a clear, quantised level), held, then released
    gently before the next hit. Hits closer than MIN_GAP_S are held through instead of flickering.
    Returns (level 0..1, index of the hit it plays: -1 before the first)."""
    i = bisect.bisect_right(times, t)
    if i == 0:
        return 0.0, -1
    last = float(times[i - 1])
    gap = float(times[i]) - last if i < len(times) else 0.5
    level = round((0.6 + 0.4 * min(1.0, float(strengths[i - 1]))) * 5) / 5
    if gap < MIN_GAP_S:
        return level, i - 1
    return _release(t - last, level, min(0.4 * gap, 0.6), min(0.5 * gap, 0.8)), i - 1


def stab_env(times: np.ndarray, strengths: np.ndarray, t: float) -> float:
    """A stab played on a key: full at once (two levels), held a moment, let go quickly but softly."""
    i = bisect.bisect_right(times, t)
    if i == 0:
        return 0.0
    level = 1.0 if float(strengths[i - 1]) >= 0.5 else 0.7
    return _release(t - float(times[i - 1]), level, STAB_HOLD_S, STAB_RELEASE_S)


def pick_stabs(times: np.ndarray, strengths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The synth notes that are hits, not the run of a riff: clearly stronger than the notes around them
    (±2 s) or after a rest; at least STAB_GAP_S apart (the stronger one wins). Strengths: 0..1 by standout."""
    times, strengths = np.asarray(times, float), np.asarray(strengths, float)
    if len(times) < 2:
        return np.zeros(0), np.zeros(0)
    lo, hi = np.searchsorted(times, times - 2.0), np.searchsorted(times, times + 2.0)
    local = np.array([np.median(strengths[a:b]) for a, b in zip(lo, hi)])
    standout = strengths / np.maximum(local, 1e-3)
    rest = np.r_[np.inf, np.diff(times)] >= STAB_REST_S
    cand = np.flatnonzero((standout >= STAB_STANDOUT) | (rest & (standout >= 1.0)))
    chosen: list[int] = []
    for k in cand[np.argsort(-standout[cand], kind="stable")]:  # strongest first, then keep the spacing
        j = bisect.bisect_left([times[c] for c in chosen], times[k]) if chosen else 0
        near = [chosen[x] for x in (j - 1, j) if 0 <= x < len(chosen)]
        if all(abs(times[c] - times[k]) >= STAB_GAP_S for c in near):
            chosen.insert(j, k)
    idx = np.array(sorted(chosen), dtype=int)
    return times[idx], np.clip((standout[idx] - 1.0) / 1.0, 0.0, 1.0)


def _ease(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(max(x, 0.0), 1.0))


class TimingMixin:
    """Beat, bar and phrase lookups for the engine."""

    def _bar_ramp(
        self, x: np.ndarray, deadband: float = 0.0, snap: float | None = None, relative_bars: int | None = None
    ) -> np.ndarray:
        """Per-frame signal → one level per bar (its mean), ramped linearly from each bar's level to the next
        across the bar. Changes smaller than `deadband` are ignored (no fiddling); with `snap` the levels
        become 0 or 1 (on/off per bar) and the change happens as a straight fade over the bar's first beat."""
        fps = self.a.fps
        n = len(x)
        bars = self.downbeat_times if len(self.downbeat_times) > 1 else np.arange(0, n / fps, 2.0)
        edges = np.clip((np.asarray(bars) * fps).astype(int), 0, n)
        edges = np.unique(np.concatenate([[0], edges, [n]]))
        raw = [float(x[a:b].mean()) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])]
        if relative_bars:  # loudness (dB) relative to the bars around it: quiet bar 0 .. loud bar 1
            r = np.array(raw)
            rel = []
            for k in range(len(r)):
                win = r[max(0, k - relative_bars) : k + relative_bars + 1]
                lo, hi = float(win.min()), float(win.max())
                rel.append((r[k] - lo) / max(hi - lo, 3.0))
            raw = rel
        levels = []
        for v in raw:
            if snap is not None:
                v = 1.0 if v >= snap else 0.0
            if levels and abs(v - levels[-1]) < deadband:
                v = levels[-1]
            levels.append(v)
        out = np.empty(n, np.float32)
        for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
            cur, nxt = levels[k], levels[min(k + 1, len(levels) - 1)]
            if b <= a:
                continue
            if snap is None:  # glide to the next bar's level across this bar
                out[a:b] = np.linspace(cur, nxt, b - a, endpoint=False)
            else:  # hold; switch with a straight one-beat fade at the start of the next bar
                prev = levels[k - 1] if k > 0 else cur
                beat = max(1, (b - a) // 4)
                out[a:b] = cur
                out[a : a + beat] = np.linspace(prev, cur, min(beat, b - a), endpoint=False)
        return out

    @staticmethod
    def _local_envelope(db: np.ndarray, fps: float, window_s: float = 8.0) -> np.ndarray:
        """Loudness normalised to its surroundings (~8 s): quiet passages still get a full 0..1 'breath'."""
        from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d

        x = uniform_filter1d(db, max(1, int(0.12 * fps)))
        w = max(3, int(window_s * fps))
        lo, hi = minimum_filter1d(x, w), maximum_filter1d(x, w)
        return np.clip((x - lo) / np.maximum(hi - lo, 3.0), 0, 1).astype(np.float32)

    def _kick_breaks(self) -> list[tuple[float, float, bool]]:
        """Where the kick drops out inside the music: (start, end, kick_returns) on bar lines. After a running
        kick (two bars with 3+ kicks), a stretch of bars with at most two kicks that dips to one or none: the
        kick thinning out (filtered away) and gone, a classic techno/house build within a section. Steady two
        kicks a bar (half time) is a groove, not a break; a long stretch counts with its last BREAK_MAX_BARS."""
        bars = self.downbeat_times
        if len(bars) < 4 or not len(self.kick_t):
            return []
        counts = [int(((self.kick_t >= b0 - 0.05) & (self.kick_t < b1 - 0.05)).sum()) for b0, b1 in zip(bars, bars[1:])]
        out, k = [], 2
        while k < len(counts):
            if counts[k] <= 2 and counts[k - 1] >= 3 and counts[k - 2] >= 3:
                e = k
                while e < len(counts) and counts[e] <= 2:
                    e += 1
                if min(counts[k:e]) <= 1:
                    start = max(k, e - BREAK_MAX_BARS)
                    returns = e < len(counts)
                    out.append((float(bars[start]), float(bars[min(e, len(bars) - 1)]), returns))
                k = e
            k += 1
        return out

    def _frame(self, t: float) -> int:
        return min(max(int(t * self.a.fps), 0), len(self.lead_pitch) - 1)

    # ------------------------------------------------------------ timeline helpers

    def decision_at(self, t: float) -> tuple[int, Decision]:
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        return i, self.plan[i]

    def beat_info(self, t: float):
        i = bisect.bisect_right(self.beats, t) - 1
        if i < 0 or i + 1 >= len(self.beats):
            return max(i, 0), 0.0, 0.47
        period = self.beats[i + 1] - self.beats[i]
        return i, (t - self.beats[i]) / period, period

    def bar_info(self, t: float):
        i = bisect.bisect_right(self.downbeat_times, t) - 1
        return max(i, 0)

    def _flash_timeline(self, max_hz: float):
        """White flashes from the scenes that use them: on the kick (a big accent is snapped to the kick it lands
        with; one between kicks would make the light peak twice a beat), thinned to at most max_hz."""
        cand = []
        kicks = self.kick_t if len(self.kick_t) else self.beats
        for d in self.plan:
            if d.dynamics == "impact" or (d.dynamics == "rise" and d.par_accent != "none"):
                m = (self.acc_t >= d.start) & (self.acc_t < d.end) & (self.acc_s > 0.5)
                for t, s in zip(self.acc_t[m], self.acc_s[m]):
                    k = int(np.argmin(np.abs(kicks - t))) if len(kicks) else -1
                    if k >= 0 and abs(kicks[k] - t) <= FLASH_SNAP_S:
                        cand.append((float(kicks[k]), float(s)))
            if d.dynamics == "impact" and d.intensity >= 3:
                m = (kicks >= d.start) & (kicks < d.end)
                cand += [(float(t), 1.0) for t in kicks[m]]
        cand.sort()
        out_t, out_s, last = [], [], -1e9
        for t, s in cand:
            if t - last >= 1.0 / max_hz:
                out_t.append(t)
                out_s.append(s)
                last = t
        return np.array(out_t), np.array(out_s)

    # ------------------------------------------------------------ head motion, vectorised
    # The targets are computed for a whole phrase at once and the motor simulation steps all heads together:
    # the cost hardly depends on the number of heads (60 heads: ~1 s).

    def _beat_info_v(self, ts: np.ndarray):
        b = self.beats
        i = np.searchsorted(b, ts, side="right") - 1
        ok = (i >= 0) & (i + 1 < len(b))
        ic = np.clip(i, 0, max(len(b) - 2, 0))
        if len(b) >= 2:
            period = np.where(ok, b[ic + 1] - b[ic], 0.47)
            phase = np.where(ok, (ts - b[ic]) / np.where(ok, period, 1.0), 0.0)
        else:
            period, phase = np.full(len(ts), 0.47), np.zeros(len(ts))
        return np.where(ok, i, np.maximum(i, 0)), phase, period
