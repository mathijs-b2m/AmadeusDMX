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
        k_next = count(db_times[k + 1], db_times[k + 2]) if k + 2 < len(db_times) else 0
        if k_after < 3 and not (k_after >= 2 and k_next >= 3):
            continue  # a drop has a running kick in its first bar (the first kick can hide under the bass)
        # the low end coming in decides; the kicks only a little (capped): the detector often misses the first
        # kicks of a drop under the returning bass, and counting them in full picks the bar after the drop
        jump = low_mean(db_times[k], db_times[k + 1]) - low_mean(db_times[k - 2], db_times[k])
        score = max(0.0, jump) + 1.0 * max(0.0, min(k_after, 3) - k_before)
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


BUILD_MIN_BARS, BUILD_MAX_BARS = 4, 16  # a build-up before a drop lasts this many bars
BUILD_SPLIT_BARS = 8  # a section before a drop longer than this holds more than the build: split it


def _split_builds(segments: list[tuple[int, int]], phrases, bars: np.ndarray) -> list[tuple[int, int]]:
    """The build-up before each drop as its own section. A build is the final rise into the drop: of 4, 6 … 16
    bars back from the drop, the stretch over which the tension (loudness and brightness) rises most steadily
    (its correlation with time; the bar right before the drop left out: often a breath). Only a clear rise."""
    z = (bars - bars.mean(0)) / (bars.std(0) + 1e-9)
    tension = z[:, 0] + z[:, 3]  # loudness + highs
    out = list(segments)
    for i in range(len(segments) - 1, 0, -1):
        if phrases[i].drop_score < DROP_THRESHOLD:
            continue
        b0, drop = out[i - 1][0], out[i][0]
        if drop - b0 <= BUILD_SPLIT_BARS:
            continue
        fits = {}
        for n in range(BUILD_MIN_BARS, BUILD_MAX_BARS + 1, 2):
            if drop - n < b0 + 4:
                break
            y = tension[drop - n : drop - 1]
            fits[n] = float(np.corrcoef(np.arange(len(y)), y)[0, 1]) if len(y) > 2 and y.std() > 0 else 0.0
        best = None
        if fits and max(fits.values()) >= BUILD_MIN_R:
            top = max(fits.values())
            n = max(k for k, r in fits.items() if r >= top - 0.05)  # the longest about as steady as the best
            y = tension[drop - n : drop - 1]
            low = drop - n + int(np.flatnonzero(y <= y.min() + 0.05)[-1])  # …from where it last was low
            n = max(BUILD_MIN_BARS, drop - low + (drop - low) % 2)  # whole two-bar steps back from the drop
            best = drop - n if drop - n >= b0 + 4 else None
        if best is not None:
            out[i - 1 : i] = [(b0, best), (best, drop)]
    return out


BUILD_MIN_R = 0.6  # a build: the tension rises at least this steadily (correlation with time)


SLAM_LOW_JUMP = 0.25  # the low end (0..1 over the track) of the two bars from here against the two before
SLAM_SEARCH_BARS = 6  # a phrase boundary this close to a slam moves onto it; farther away the phrase is split


def _slams(feats, fps, beat_times, db_times, kicks) -> list[int]:
    """The bars where a drop lands, wherever the phrase grid is: the kick starts RUNNING (on most beats of this
    bar and the next, after bars with at most half) and the low end jumps in with it.

    Songs don't keep a 4-bar grid from their first bar (a pop song's piano intro, a bar of silence before the
    drop), so the grid can put a boundary bars away from the drop, and a long phrase that only gets its beat
    halfway would count as a drop from its first, beatless bar."""
    low = np.maximum(feats["sub"], feats["bass"]).astype(float)
    lo, hi = np.percentile(low, [5, 95])
    low = np.clip((low - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    n = len(db_times) - 1
    on = np.zeros(n)  # per bar: the share of its beats with a kick
    lv = np.zeros(n)
    for k in range(n):
        t0, t1 = db_times[k], db_times[k + 1]
        beats = beat_times[(beat_times >= t0) & (beat_times < t1)]
        if len(beats) and len(kicks):
            on[k] = np.mean([np.any(np.abs(kicks - b) < 0.08) for b in beats])
        lv[k] = low[int(t0 * fps) : max(int(t1 * fps), int(t0 * fps) + 1)].mean()
    found: list[tuple[float, int]] = []
    for k in range(2, n - 1):
        running = on[k] >= 0.75 and on[k + 1] >= 0.75
        before = on[k - 2 : k].mean() <= 0.5
        jump = lv[k : k + 2].mean() - lv[k - 2 : k].mean()
        if running and before and jump >= SLAM_LOW_JUMP:
            found.append((jump + 0.5 * (on[k : k + 2].mean() - on[k - 2 : k].mean()), k))
    keep: list[int] = []
    for _, k in sorted(found, reverse=True):  # the clearest first; one per 8 bars
        if all(abs(k - j) >= 8 for j in keep):
            keep.append(k)
    return sorted(keep)


def _land_on_slams(segments: list[tuple[int, int]], slams: list[int]) -> list[tuple[int, int]]:
    """Phrase boundaries onto the slams: the nearest boundary moves there, or the phrase is split."""
    cuts = sorted({s for s, _ in segments} | {segments[-1][1]})
    for k in slams:
        if k in cuts:
            continue
        near = min(cuts[1:-1], key=lambda c: abs(c - k), default=None)
        if near is not None and abs(near - k) <= SLAM_SEARCH_BARS:
            i = cuts.index(near)
            if cuts[i - 1] + 2 <= k <= cuts[i + 1] - 2:  # both phrases keep two bars at least
                cuts[i] = k
                continue
        i = next(j for j in range(len(cuts) - 1) if cuts[j] < k < cuts[j + 1])
        if cuts[i] + 2 <= k <= cuts[i + 1] - 2:
            cuts.insert(i + 1, k)
    return list(zip(cuts[:-1], cuts[1:]))


def build_phrases(feats, fps, beat_times, downbeat_idx, onsets):
    db_times = beat_times[downbeat_idx]
    if len(db_times) < 3:
        db_times = beat_times[::4]
    bars = _bar_features(feats, fps, beat_times, db_times)
    segments = _segment_bars(bars)
    segments = _land_on_slams(segments, _slams(feats, fps, beat_times, db_times, onsets["kick"][0]))
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

    # The build-up: a long section before a drop holds more than the build (a chorus, then the build), and the
    # phrase before a drop is lit as the build-up. The build gets its own section, from where the tension last
    # dips before the drop.
    split = _split_builds(segments, phrases, bars)
    if split != segments:
        drops = {segments[i][0]: p.drop_score for i, p in enumerate(phrases) if p.drop_score >= DROP_THRESHOLD}
        segments = split
        phrases = _phrases_from(feats, fps, beat_times, db_times, bars, onsets, segments)
        for (b0, _), p in zip(segments, phrases):  # a drop stays a drop: next to its build its jump looks smaller
            if b0 in drops:
                p.drop_score = max(p.drop_score, drops[b0])

    # Then the exact beat: where the bar lines were guessed half a bar off (it happens in intros), the
    # drop slams in on another beat than the bar line. Move the drop there when that beat is clearly it.
    for i in range(1, len(phrases)):
        if phrases[i].drop_score < DROP_THRESHOLD:
            continue
        t = _drop_beat(feats, fps, beat_times, phrases[i].start)
        if t != phrases[i].start and phrases[i - 1].start < t < phrases[i].end:
            phrases[i - 1].end = t
            phrases[i].start = t
    _pickups(feats, fps, beat_times, phrases, onsets)
    return phrases


PICKUP_MAX_BEATS = 4  # an anacrusis is at most a bar
PICKUP_LEAN = 0.25  # a beat counts as the next section's when it is this much closer to it (share of their distance)
PICKUP_SECTIONS_APART = 1.2  # …and only when the two sections really sound different (z-score distance)
FILL_RATE = 2.5  # a fill: drum hits per beat this many times the section's usual rate…
FILL_MIN_PER_BEAT = 2.0  # …and at least this many per beat


def _pickups(feats, fps, beat_times, phrases, onsets) -> None:
    """Sections that start before their downbeat: a fill leading in, or the next part's sound (a vocal line, a
    melody) already starting a beat or a few early. Sets each phrase's pickup_beats / pickup_kind / pickup_start.

    Fill: the last beats before the boundary are dense with snare and accent hits compared with the section.
    Early: the last beats already sound like the next section (bands, brightness), and the beat before them
    still like this one."""
    cols = [
        feats["rms"],
        np.maximum(feats["sub"], feats["bass"]),
        feats["mid"],
        np.maximum(feats["high"], feats["air"]),
    ]
    z = np.stack([(c - c.mean()) / (c.std() + 1e-9) for c in cols], axis=1)

    def beat_vec(k):
        a, b = int(beat_times[k] * fps), int(beat_times[min(k + 1, len(beat_times) - 1)] * fps)
        return z[a : max(b, a + 1)].mean(axis=0)

    hits = np.sort(np.concatenate([onsets["snare"][0], onsets["accent"][0]]))

    def rate(t0, t1, beats):
        return float(((hits >= t0) & (hits < t1)).sum()) / max(beats, 1)

    for p in phrases:
        p.pickup_start = p.start
    for i in range(1, len(phrases)):
        p, prev = phrases[i], phrases[i - 1]
        k0 = int(np.searchsorted(beat_times, p.start - 0.05))  # the downbeat's beat
        first_prev = int(np.searchsorted(beat_times, prev.start - 0.05))
        if k0 - first_prev < 8 or k0 + 8 >= len(beat_times):
            continue
        period = float(np.median(np.diff(beat_times[max(0, k0 - 8) : k0 + 1])))
        # a fill: the run of dense beats right before the downbeat
        usual = rate(prev.start, beat_times[k0 - PICKUP_MAX_BEATS], k0 - PICKUP_MAX_BEATS - first_prev)
        n_fill = 0
        for k in range(1, PICKUP_MAX_BEATS + 1):
            r = rate(beat_times[k0 - k], beat_times[k0 - k + 1] if k > 1 else p.start, 1)
            if r >= FILL_MIN_PER_BEAT and r >= FILL_RATE * max(usual, 0.3):
                n_fill = k
            else:
                break
        if n_fill:
            p.pickup_beats, p.pickup_kind = n_fill, "fill"
            p.pickup_start = float(p.start - n_fill * period)
            continue
        # early: the last beats already sound like the next section
        before = np.mean([beat_vec(k) for k in range(first_prev, k0 - PICKUP_MAX_BEATS)], axis=0)
        after = np.mean([beat_vec(k) for k in range(k0, min(k0 + 16, len(beat_times) - 1))], axis=0)
        apart = float(np.linalg.norm(after - before))
        if apart < PICKUP_SECTIONS_APART:
            continue

        def lean(k, before=before, after=after, apart=apart):  # > 0: beat k sounds like the next section
            v = beat_vec(k)
            return (np.linalg.norm(v - before) - np.linalg.norm(v - after)) / apart

        n_early = 0
        for k in range(1, PICKUP_MAX_BEATS + 1):
            if lean(k0 - k) >= PICKUP_LEAN:
                n_early = k
            else:
                break
        if n_early and n_early < PICKUP_MAX_BEATS and lean(k0 - n_early - 1) < 0.0:  # (and it does start there)
            p.pickup_beats, p.pickup_kind = n_early, "early"
            p.pickup_start = float(p.start - n_early * period)


VOCAL_ON = 0.5  # the vocal (0..1 between its quiet and loud levels) sings in a beat above this…
VOCAL_OFF = 0.3  # …and pauses below this


def vocal_pickups(phrases, beat_times, downbeat_times, env: np.ndarray, env_fps: float) -> None:
    """Vocal lead-ins, from the separated vocals. A vocal line that comes in after a pause one to three beats
    before a downbeat ("'Cause you're a sky…") marks where a section really starts: a section boundary within two
    bars of that downbeat moves onto it (drops keep theirs: the beat decides those), and the line becomes the
    section's "early" pickup. A vocal over the same band barely changes the mix's sound, so the full mix can't
    see these."""
    if env is None or not len(env) or len(phrases) < 2 or len(downbeat_times) < 2:
        return
    lo, hi = np.percentile(env, [10, 90])
    norm = np.clip((env - lo) / max(hi - lo, 1e-9), 0, 1)
    n = len(beat_times) - 1
    level = np.zeros(n)
    for k in range(n):
        a, b = int(beat_times[k] * env_fps), int(beat_times[k + 1] * env_fps)
        level[k] = norm[a : max(b, a + 1)].mean()
    bar = float(np.median(np.diff(downbeat_times)))
    for k in range(2, n - 4):
        if not (level[k] > VOCAL_ON and level[k - 1] < VOCAL_OFF and level[k - 2] < VOCAL_OFF):
            continue  # not a line coming in after a pause
        if (level[k : k + 4] > VOCAL_ON).sum() < 2:
            continue  # a blip, not a line
        nxt = downbeat_times[downbeat_times > beat_times[k] + 0.05]
        if not len(nxt):
            continue
        down = float(nxt[0])
        m = int(round((down - beat_times[k]) / max(beat_times[k + 1] - beat_times[k], 1e-6)))
        if not 1 <= m <= 3:
            continue  # on the downbeat itself: no anacrusis
        i = min(range(1, len(phrases)), key=lambda j: abs(phrases[j].start - down))
        p, prev = phrases[i], phrases[i - 1]
        if abs(p.start - down) > 2 * bar + 0.05 or p.drop_score >= DROP_THRESHOLD or p.pickup_beats:
            continue
        if not (prev.start + 2 * bar - 0.05 <= down <= p.end - 2 * bar + 0.05):
            continue  # both sections keep two bars at least
        prev.end = p.start = down
        p.pickup_beats, p.pickup_kind, p.pickup_start = m, "early", float(beat_times[k])


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
