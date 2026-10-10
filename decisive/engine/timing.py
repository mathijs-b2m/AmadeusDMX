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

    def _stutter(self, t: float, calm: float) -> float:
        """Brightness that chops with the synth's stutter/gate where there is one, else `calm`."""
        f = self._frame(t)
        strength = float(self.chop[f])  # per bar, not flickering between chopping and calm
        chopped = 1.0 - self.stut_depth * (1.0 - float(self.stut_gate[f]))
        return calm * (1 - strength) + chopped * strength

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
        """Candidate flashes from the scenes that use them, thinned to at most max_hz."""
        cand = []
        for d in self.plan:
            if d.dynamics == "impact" or (d.dynamics == "rise" and d.par_accent != "none"):
                m = (self.acc_t >= d.start) & (self.acc_t < d.end) & (self.acc_s > 0.5)
                cand += list(zip(self.acc_t[m], self.acc_s[m]))
            if d.dynamics == "rise":  # snare-roll flashes, rate-limited below
                m = (self.snare_t >= d.start) & (self.snare_t < d.end)
                cand += [(t, 0.6 * s) for t, s in zip(self.snare_t[m], self.snare_s[m])]
            if d.dynamics == "impact" and d.intensity >= 3:
                m = (self.beats >= d.start) & (self.beats < d.end)
                cand += [(t, 1.0) for t in self.beats[m]]
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
