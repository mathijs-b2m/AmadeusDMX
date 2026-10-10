"""Bars, phrases and drops: where the music changes, and how much each phrase starts like a drop."""

from __future__ import annotations

import numpy as np

from decisive.audio.model import DROP_THRESHOLD, Phrase


def _bar_features(feats, fps, beat_times, downbeat_times):
    rows = []
    for a, b in zip(downbeat_times[:-1], downbeat_times[1:]):
        s, e = int(a * fps), max(int(b * fps), int(a * fps) + 1)
        rows.append(
            [
                feats["rms"][s:e].mean(),
                np.maximum(feats["sub"][s:e], feats["bass"][s:e]).mean(),
                feats["mid"][s:e].mean(),
                np.maximum(feats["high"][s:e], feats["air"][s:e]).mean(),
                feats["centroid"][s:e].mean(),
            ]
        )
    return np.array(rows)


def _segment_bars(bar_feats: np.ndarray) -> list[tuple[int, int]]:
    """Cut bars into phrases at 4-bar-aligned novelty peaks, 4..16 bars long."""
    n = len(bar_feats)
    if n < 8:
        return [(0, n)]
    z = (bar_feats[:, :4] - bar_feats[:, :4].mean(0)) / (bar_feats[:, :4].std(0) + 1e-9)
    novelty = np.zeros(n)
    for k in range(4, n - 3):
        novelty[k] = np.linalg.norm(z[k - 4 : k].mean(0) - z[k : k + 4].mean(0))
    thr = np.percentile(novelty[novelty > 0], 75) if np.any(novelty > 0) else 1
    cuts, start = [0], 0
    while start < n:
        options = [start + L for L in (4, 8, 12, 16) if start + L < n]
        if not options:
            break
        strong = [c for c in options if novelty[c] >= thr]
        if strong:
            nxt = strong[0]
        else:
            nxt = start + 8 if start + 8 < n else options[-1]
        if n - nxt < 4:  # don't leave a stub at the end
            break
        cuts.append(nxt)
        start = nxt
    cuts.append(n)
    return list(zip(cuts[:-1], cuts[1:]))


def _density(times: np.ndarray, a: float, b: float, beats_in_span: int) -> float:
    return float(((times >= a) & (times < b)).sum()) / max(beats_in_span, 1)


def drop_score(p: Phrase, prev: Phrase | None) -> float:
    """How much a phrase *starts* like a drop: energy and low end jump up and the kick comes back.

    Relative to the previous phrase on purpose: the first drop of a track is often much
    quieter than its final drop, so absolute loudness alone misses it.
    """
    if prev is None:
        return 0.0
    clip = lambda x: max(0.0, min(1.0, x))  # noqa: E731
    score = (
        0.4 * clip((p.loudness_pct - prev.loudness_pct) / 40)
        + 0.4 * clip((p.low_pct - prev.low_pct) / 40)
        + 0.2 * clip((p.kick_ratio - prev.kick_ratio) / 0.4)
    )
    if p.loudness_pct < 50 or p.low_pct < 50:
        score *= 0.5  # a jump into something still quiet is a re-entry, not a drop
    if p.kick_ratio < 0.6:
        score *= 0.6  # drops have a running kick
    return round(score, 2)


def _drop_bar(feats, fps, db_times, kicks, k0: int) -> int:
    """The bar a drop really lands on, searched around a 4-bar-grid boundary k0.

    That's the bar where the kick is running and the low end jumps compared with the two
    bars before it; the novelty grid alone can be a bar or two off. One exception overrules it:
    an unmistakable slam AT a bar line (after a breath of near-silence the low end jumps in on the
    downbeat) within two bars; the kick detector can miss kicks under the returning bass, so that
    bar may not look like "a bar with a running kick" yet it is where everybody hears the drop.
    """
    low = np.maximum(feats["sub"], feats["bass"])

    def low_mean(t0, t1):
        return float(low[int(t0 * fps) : max(int(t1 * fps), int(t0 * fps) + 1)].mean())

    def count(t0, t1):
        return int(((kicks >= t0) & (kicks < t1)).sum())

    best, best_score = k0, -1.0
    for k in range(max(2, k0 - 6), min(len(db_times) - 1, k0 + 5)):
        k_after, k_before = count(db_times[k], db_times[k + 1]), count(db_times[k - 2], db_times[k]) / 2
        if k_after < 3:
            continue  # a drop has a running kick in its first bar
        score = max(0.0, low_mean(db_times[k], db_times[k + 1]) - low_mean(db_times[k - 2], db_times[k])) + 2.5 * max(
            0.0, k_after - k_before
        )
        if score > best_score:
            best, best_score = k, score

    # The slam at the bar line, on the low end scaled 0..1 over the track.
    lo, hi = np.percentile(low, [5, 95])
    norm = np.clip((low - lo) / max(hi - lo, 1e-9), 0.0, 1.0)

    def edge(k):
        beat = (db_times[min(k + 1, len(db_times) - 1)] - db_times[k]) / 4 or 0.5
        a, b = int((db_times[k] - beat) * fps), int(db_times[k] * fps)
        c = int((db_times[k] + beat) * fps)
        return float(norm[b : max(c, b + 1)].mean() - norm[max(a, 0) : max(b, a + 1)].mean())

    best_edge = edge(best)
    slams = [
        (edge(k), k)
        for k in range(max(2, best - 2), min(len(db_times) - 1, best + 3))
        if count(db_times[k] - 0.07, db_times[k + 1] - 0.07) >= 1
    ]
    e, k = max(slams, default=(0.0, best))
    if e >= DROP_SLAM and e - best_edge >= 0.25:
        return k
    return best


DROP_SLAM = 0.35  # low end (0..1 over the track) jumping in this much at a bar line: unmistakably the drop


def _phrases_from(feats, fps, beat_times, db_times, bars, onsets, segments) -> list[Phrase]:
    pct = lambda col, v: float((bars[:, col] < v).mean() * 100)  # noqa: E731
    phrases = []
    kicks = onsets["kick"][0]
    for i, (b0, b1) in enumerate(segments):
        t0, t1 = db_times[b0], db_times[min(b1, len(db_times) - 1)]
        in_span = beat_times[(beat_times >= t0) & (beat_times < t1)]
        nb = len(in_span)
        kick_hits = sum(np.any(np.abs(kicks - bt) < 0.08) for bt in in_span) if len(kicks) else 0
        quarter = (t1 - t0) / 4
        seg = bars[b0:b1]
        phrases.append(
            Phrase(
                index=i,
                start=float(t0),
                end=float(t1),
                bars=int(b1 - b0),
                bpm=round(60 / float(np.mean(np.diff(in_span))), 1) if nb > 2 else 0.0,
                loudness_pct=round(pct(0, seg[:, 0].mean()), 1),
                loudness_slope_db=round(float(seg[-1, 0] - seg[0, 0]), 1),
                low_pct=round(pct(1, seg[:, 1].mean()), 1),
                mid_pct=round(pct(2, seg[:, 2].mean()), 1),
                high_pct=round(pct(3, seg[:, 3].mean()), 1),
                kick_ratio=round(float(kick_hits) / max(nb, 1), 2),
                hat_density=round(_density(onsets["hat"][0], t0, t1, nb), 2),
                snare_density=round(_density(onsets["snare"][0], t0, t1, nb), 2),
                snare_trend=round(
                    _density(onsets["snare"][0], t1 - quarter, t1, nb // 4)
                    - _density(onsets["snare"][0], t0, t0 + quarter, nb // 4),
                    2,
                ),
                brightness_trend=round(float(seg[-1, 4] - seg[0, 4]), 0),
                lead_density=round(_density(onsets["lead"][0], t0, t1, nb), 2) if "lead" in onsets else 0.0,
                stutter=round(
                    float(feats["stutter_strength"][int(t0 * fps) : max(int(t1 * fps), int(t0 * fps) + 1)].mean()), 2
                )
                if "stutter_strength" in feats
                else 0.0,
                lead_presence=round(
                    float(feats["lead_tonal"][int(t0 * fps) : max(int(t1 * fps), int(t0 * fps) + 1)].mean()), 2
                )
                if "lead_tonal" in feats
                else 0.0,
            )
        )
    for i, ph in enumerate(phrases):
        ph.drop_score = drop_score(ph, phrases[i - 1] if i else None)
    return phrases


def build_phrases(feats, fps, beat_times, downbeat_idx, onsets):
    db_times = beat_times[downbeat_idx]
    if len(db_times) < 3:
        db_times = beat_times[::4]
    bars = _bar_features(feats, fps, beat_times, db_times)
    segments = _segment_bars(bars)
    phrases = _phrases_from(feats, fps, beat_times, db_times, bars, onsets, segments)

    # Drops: move each drop's boundary onto the bar it really lands on, then recompute the features
    # so the drop phrase and the buildup before it describe the right bars.
    moved = False
    for i in range(1, len(segments)):
        if phrases[i].drop_score < DROP_THRESHOLD:
            continue
        k = _drop_bar(feats, fps, db_times, onsets["kick"][0], segments[i][0])
        if k != segments[i][0] and segments[i - 1][0] + 1 < k < segments[i][1] - 1:
            segments[i - 1] = (segments[i - 1][0], k)
            segments[i] = (k, segments[i][1])
            moved = True
    if moved:
        phrases = _phrases_from(feats, fps, beat_times, db_times, bars, onsets, segments)

    # Then the exact beat: where the bar lines were guessed half a bar off (it happens in intros), the
    # drop slams in on another beat than the bar line. Move the drop there when that beat is clearly it.
    for i in range(1, len(phrases)):
        if phrases[i].drop_score < DROP_THRESHOLD:
            continue
        t = _drop_beat(feats, fps, beat_times, phrases[i].start)
        if t != phrases[i].start and phrases[i - 1].start < t < phrases[i].end:
            phrases[i - 1].end = t
            phrases[i].start = t
    return phrases


def _drop_beat(feats, fps, beat_times, t_bar: float) -> float:
    """Where the drop really hits when the bar lines were guessed half a bar off: the beat 2 beats before or
    after the bar line, if its jump in low end + loudness is big and at least twice the jump at the bar line."""
    low = np.maximum(feats["sub"], feats["bass"]).astype(float)
    loud = feats["rms"].astype(float)

    def norm(x):
        lo, hi = np.percentile(x, [5, 95])
        return np.clip((x - lo) / max(hi - lo, 1e-9), 0.0, 1.0)

    low, loud = norm(low), norm(loud)
    k0 = int(np.argmin(np.abs(beat_times - t_bar)))

    def jump(k):
        if k < 1 or k + 1 >= len(beat_times):
            return -1.0
        a, b, c = (int(beat_times[j] * fps) for j in (k - 1, k, k + 1))
        cur = low[b : max(c, b + 1)].mean() + loud[b : max(c, b + 1)].mean()
        prev = low[a : max(b, a + 1)].mean() + loud[a : max(b, a + 1)].mean()
        return float(cur - prev)

    def accent(k):  # how much beats k, k+4, k+8, k+12 stand out among the 16 beats from k
        vals = []
        for j in range(k, min(k + 16, len(beat_times) - 1)):
            a, b = int(beat_times[j] * fps), int(beat_times[j + 1] * fps)
            vals.append(low[a : max(b, a + 1)].mean() + loud[a : max(b, a + 1)].mean())
        v = np.array(vals)
        return float(v[0::4].mean() - v.mean()) if len(v) >= 8 else 0.0

    # Only a half-bar error (the bar line guessed 2 beats off) is considered; a beat or so before a drop is
    # often loud with risers and rolls, so a 1-beat shift would mostly be wrong.
    base = jump(k0)
    best = max((k for k in (k0 - 2, k0 + 2) if 1 <= k < len(beat_times) - 1), key=jump, default=k0)
    if jump(best) >= DROP_BEAT_JUMP and jump(best) >= 2 * max(base, 0.05):
        # ... and the music after it must confirm that bar phase: its "one" beats (every 4th from here)
        # clearly stronger than the beats in between, more so than from the old bar line.
        new_acc, old_acc = accent(best), accent(k0)
        if new_acc > 0.05 and new_acc > old_acc + 0.04:
            return float(beat_times[best])
    return t_bar


DROP_BEAT_JUMP = 0.5  # low end + loudness (each 0..1 over the track) jumping this much from one beat to the next
