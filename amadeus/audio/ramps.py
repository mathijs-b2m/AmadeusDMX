"""Tempo changes inside a track: a run of hits that speeds up (or slows down) away from the beat grid.

A track made at one tempo gets one straight grid (`beats.constant_grid`), and where it isn't, the tracker keeps its
beats near a tempo estimated over many seconds. Neither follows a part that changes its tempo as it goes: the
accelerating build of Headhunterz' "Rate Reducer" (hits 0.79 s apart at 56 s, 0.14 s at 79 s, out of a 150 BPM
track) got a straight 125 BPM grid, its loudness called it a climax, and the show played a drop at 125 over a
build that sped up under it.

**Finding one.** The hits (onset peaks of the whole spectrum) are linked into chains, each hit to the next one whose
gap is within RATIO of the gap before it (a ramp changes its pace a few percent per hit; noise doesn't keep a
pace). The best chains are tried longest first; one is a ramp when it

- has MIN_HITS hits over MIN_S seconds,
- changes its pace smoothly and one way only (the log gaps on a curve, within FIT_SPREAD, its slope one sign),
- changes it by at least MIN_CHANGE from its first gap to its last,
- mostly runs off the grid there (at most OFF_GRID of its hits on a beat or half a beat): a grid that already
  follows it needs nothing,
- and the grid's own beats go quiet under it (their hits under GRID_LIVE of the ramp's): where the kick keeps
  running, the ramp is a layer over the beat (a delay's echoes slowing down over Mau P's "Metro", 22 of 22 kicks
  still there), and the beat is what the lights play.

On 458 cached tracks, 3 have one: "Rate Reducer", the accelerating intro of Jebroer's "Flitsmeister" and a build in
Outsiders' "Lotje" remix; the layers it left out score 0.51–1.43 (the ramps 0.13–0.33).

**Splicing it in.** The grid's beats over the ramp are replaced by its hits, thinned where they come faster than
MIN_BEAT_S (a roll at the top: every second hit, every fourth…), so a beat stays something a light can play. The
bars outside keep their phase; in the ramp a bar is every fourth beat from its first hit."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from amadeus.audio.features import pick_peaks

RATIO = 0.13  # a gap within this (log) of the one before: the same pace, changing
MAX_GAP_S = 1.6  # hits further apart are no pulse
MIN_HITS, MIN_S = 12, 5.0
MIN_CHANGE = 1.3  # first gap against last: a ramp changes its tempo at least this much
FIT_SPREAD = 0.06  # the log gaps' spread around their curve (a pulse, not scattered hits)
GRID_LIVE = 0.5  # the grid's hits under the ramp at least this strong against the ramp's: the beat still runs
OFF_GRID = 0.45  # at most this share of a ramp's hits on a beat or half a beat of the grid
ON_GRID = 0.08  # …within this share of a beat
CARRY = 0.25  # a found ramp runs on through hits within this share of the gap it predicts (its top gets ragged)
MIN_GAP_S = 0.1  # …down to hits this close together
CARRY_SHARE = 0.5  # …for at most this share of its own length
MIN_BEAT_S = 0.3  # a ramp's beats are at least this far apart (faster hits: every second one, …)
EDGE_S = 0.5  # the grid's beats this share of a beat from the ramp's ends give way to it


@dataclass
class Ramp:
    start: float  # its first hit
    end: float  # its last hit
    bpm_from: float
    bpm_to: float
    beats: np.ndarray  # the hits it plays as beats


def _chains(t: np.ndarray, s: np.ndarray) -> list[list[int]]:
    """The hits linked into chains of a steady or steadily changing pace, best first (indices into t)."""
    n = len(t)
    # every pair (i, j) of hits that can follow each other, j after i
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if t[j] - t[i] <= MAX_GAP_S]
    into: dict[int, list[int]] = {}
    for k, (i, j) in enumerate(pairs):
        into.setdefault(j, []).append(k)
    score = np.zeros(len(pairs))
    back = np.full(len(pairs), -1)
    for k, (i, j) in enumerate(pairs):  # pairs come ordered by i, so every pair into i is scored already
        gap = t[j] - t[i]
        score[k] = s[i] + s[j]
        for q in into.get(i, ()):
            h = pairs[q][0]
            r = abs(np.log(gap / (t[i] - t[h])))
            if r <= RATIO and score[q] + s[j] - 2 * r > score[k]:
                score[k], back[k] = score[q] + s[j] - 2 * r, q
    out, used = [], np.zeros(n, bool)
    for k in np.argsort(-score):
        chain, q = [], int(k)
        while q >= 0:
            chain.append(pairs[q][1])
            if back[q] < 0:
                chain.append(pairs[q][0])
            q = int(back[q])
        chain = chain[::-1]
        if len(chain) < MIN_HITS or used[chain].any():
            continue
        used[chain] = True
        out.append(chain)
    return out


def _on_grid(times: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Per time: is it on a beat or half a beat of the grid?"""
    if len(grid) < 2:
        return np.zeros(len(times), bool)
    i = np.clip(np.searchsorted(grid, times) - 1, 0, len(grid) - 2)
    period = grid[i + 1] - grid[i]
    pos = (times - grid[i]) / period
    return np.minimum(np.abs(pos * 2 - np.round(pos * 2)) / 2, 1.0) < ON_GRID


def _trim(hits: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """A chain without its ends that are on the grid already (the steady beats a ramp starts or ends from)."""
    on = _on_grid(hits, grid)
    a, b = 0, len(hits)
    while b - a > MIN_HITS and on[a] and on[a + 1]:
        a += 1
    while b - a > MIN_HITS and on[b - 1] and on[b - 2]:
        b -= 1
    return hits[a:b]


def _carried(hits: np.ndarray, t: np.ndarray) -> np.ndarray:
    """A build run on past where its chain broke: the hits each one near where its pace says the next one comes
    (the last gaps, getting shorter as over the last eight). The top of an accelerating build is ragged, the hits
    too close for a chain to keep its pace exactly ("Rate Reducer" runs on from 75 s to its roll at 79 s)."""
    out, until = list(hits), hits[-1] + CARRY_SHARE * (hits[-1] - hits[0])
    while True:
        g = np.diff(out[-9:])
        trend = float(np.polyfit(np.arange(len(g)), np.log(g), 1)[0])
        gap = float(np.exp(np.mean(np.log(g[-3:])) + 2 * trend))
        if trend >= 0 or gap < MIN_GAP_S or out[-1] + gap > until:
            break
        j = int(np.argmin(np.abs(t - (out[-1] + gap))))
        if abs(t[j] - (out[-1] + gap)) > CARRY * gap or t[j] <= out[-1]:
            break
        out.append(float(t[j]))
    return np.asarray(out)


def _grid_live(t: np.ndarray, s: np.ndarray, grid: np.ndarray, start: float, end: float) -> float:
    """How strong the grid's beats in [start, end] are hit (0 where no hit is on a beat), on average."""
    g = grid[(grid >= start) & (grid <= end)]
    if len(g) < 2:
        return 0.0
    reach = ON_GRID * float(np.median(np.diff(g)))
    j = np.clip(np.searchsorted(t, g), 1, len(t) - 1)
    near = np.where(np.abs(t[j] - g) < np.abs(t[j - 1] - g), j, j - 1)
    return float(np.where(np.abs(t[near] - g) < reach, s[near], 0.0).mean())


def _ramp(chain: np.ndarray, t: np.ndarray, s: np.ndarray, grid: np.ndarray) -> Ramp | None:
    """The chain (indices into the hits t, strengths s) as a ramp, or None when it isn't one."""
    hits = _trim(t[chain], grid)
    if len(hits) < MIN_HITS or hits[-1] - hits[0] < MIN_S:
        return None
    gaps = np.diff(hits)
    mid = (hits[:-1] + hits[1:]) / 2
    curve = np.polyfit(mid, np.log(gaps), 2)
    fit = np.polyval(curve, mid)
    if np.std(np.log(gaps) - fit) > FIT_SPREAD:
        return None
    slope = np.polyval(np.polyder(curve), mid)
    if not ((slope < 0).all() or (slope > 0).all()):  # one way only
        return None
    first, last = float(np.exp(fit[0])), float(np.exp(fit[-1]))
    if max(first, last) / min(first, last) < MIN_CHANGE:
        return None
    if _on_grid(hits, grid).mean() > OFF_GRID:
        return None
    strength = float(s[np.isin(t, hits)].mean())
    if _grid_live(t, s, grid, hits[0], hits[-1]) >= GRID_LIVE * strength:
        return None
    chain_hits = hits
    if last < first:  # speeding up: on through its ragged top
        hits = _carried(hits, t)
    beats, stride, k = [], 1, 0
    while k < len(hits):  # every hit a beat while they are far enough apart, then every second one, …
        beats.append(hits[k])
        while k + stride < len(hits) and hits[k + stride] - hits[k] < MIN_BEAT_S:
            stride *= 2
        k += stride
    last = float(np.median(np.diff(hits[-4:]))) if len(hits) > len(chain_hits) else last
    return Ramp(float(hits[0]), float(hits[-1]), 60 / first, 60 / last, np.asarray(beats))


def find(flux: np.ndarray, fps: float, grid: np.ndarray) -> list[Ramp]:
    """The tempo ramps in a track, in time order (`flux`: the whole spectrum's onset strength per frame; `grid`:
    the beat times found so far)."""
    t, s = pick_peaks(flux, fps, delta=0.1, min_gap=0.05)
    out = []
    s = s.astype(float)
    for chain in _chains(t, s):
        r = _ramp(np.asarray(chain), t, s, grid)
        if r is not None and not any(r.start < o.end and o.start < r.end for o in out):
            out.append(r)
    return sorted(out, key=lambda r: r.start)


def splice(grid: np.ndarray, bars: np.ndarray, ramps: list[Ramp]) -> tuple[np.ndarray, np.ndarray]:
    """The beat grid (times) and its bar lines (times) with the ramps in it: the grid's beats over a ramp make way
    for its own, a bar every fourth of them; the bars outside keep their phase."""
    beats, lines = np.asarray(grid, float), np.asarray(bars, float)
    for r in ramps:
        period = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.5
        lo, hi = r.start - EDGE_S * period, r.end + EDGE_S * period
        beats = np.sort(np.concatenate([beats[(beats < lo) | (beats > hi)], r.beats]))
        lines = np.sort(np.concatenate([lines[(lines < lo) | (lines > hi)], r.beats[::4]]))
    return beats, lines


def share(ramps: list[Ramp], start: float, end: float) -> float:
    """How much of [start, end) a ramp plays: + speeding up, − slowing down (−1..1)."""
    if end <= start:
        return 0.0
    out = 0.0
    for r in ramps:
        overlap = max(0.0, min(end, r.end) - max(start, r.start)) / (end - start)
        out += overlap if r.bpm_to > r.bpm_from else -overlap
    return float(np.clip(out, -1.0, 1.0))


RAMP_PART = 0.5  # a phrase this much in a ramp is that ramp's part


def section(p, section: str) -> str:
    """The section of a phrase in a tempo ramp, whatever its loudness says: speeding up builds (a loud one is no
    climax: the music is still getting somewhere), slowing down winds down (`section`: what was made of it so far)."""
    if p.ramp >= RAMP_PART:
        return "buildup"
    if p.ramp <= -RAMP_PART and section not in ("intro", "outro"):
        return "breakdown"
    return section
