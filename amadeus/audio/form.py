"""The song's form: is this a song (verses and choruses) or a club track (built around drops), and which part is
each phrase.

The drop detector (amadeus/audio/phrases.py) listens for what a drop does to the sound: the energy and the low end
jump and the kick runs. A rock or pop chorus after a quiet verse does exactly that, so on its own it hears drops
in the Goo Goo Dolls. What tells them apart is measured here, not guessed from the tempo:

- **the voice**: in a song somebody sings through the loud parts; a club drop is the instrumental release, the
  vocal (if any) lives in the breaks. From the separated vocals, as an absolute share of the mix (a club track's
  separated "vocals" are leftovers far under the mix).
- **the instruments**: a track led by synths all the way through is built for the club.
- **copies**: a produced club track repeats its drops bar for bar (the same harmony to the decimal); a song's
  choruses are played and sung again, never quite the same.
- **what a real drop needs**: inside a song a phrase stays a drop only when it is one (Coldplay's "A Sky Full of
  Stars" has one): the beat was taken away, and it slams back in as the voice steps back or after a pause or a
  roll.
  Otherwise its jump is a chorus coming in (`Phrase.lift` keeps how big).

The genre, when it is known (your choice, the Decisions API, a tag), decides the form; the audio decides when it
isn't. A club track keeps its analysis exactly as before. In a song every phrase gets its part: intro, verse,
prechorus, chorus, bridge, instrumental, drop or outro: from where the voice sings, how loud the phrase is next
to the song's other sung phrases, and which phrases share their harmony (a chorus comes back with its chords; a
bridge is the one part like nothing else).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from amadeus.audio.model import DROP_THRESHOLD, Analysis

SONG_GENRES = {"pop", "rock", "metal", "rnb", "hiphop", "latin", "funk", "jazz"}
CLUB_GENRES = {"edm", "house", "techno", "trance", "psytrance", "hardstyle", "dnb", "dubstep"}
KNOWN = {"you", "ai", "tag"}  # where a genre is known rather than guessed from the audio

SUNG = 0.25  # a phrase with a voice singing the lead this share of the time is sung
VOCAL_LOUD = 0.4  # a song: the voice sings at least this share of its loud phrases…
VOCAL_SHARE = 0.3  # …and of the whole track
SYNTH_LED = 0.6  # a track whose melodic part is a synth this share of the time is built for the club
COPIES = 0.004  # the loud parts repeat each other's harmony this closely (or closer): produced copies, a club track
DROP_VOCAL_BEFORE, DROP_VOCAL_AFTER = 0.45, 0.35  # a drop the voice steps back for: sung before, instrumental after
DROP_SUNG = 0.5  # a drop after a pause or a roll may keep a voice over it, up to this share
BEAT_GONE_KICK, BEAT_GONE_LOW = 0.35, 15  # the beat was taken away: the kick on at most this share of the beats,
# or the low end at most this percentile
VERSE_CHORUS_MIN = 8  # sung phrases this much apart in energy (percentile points): verses and choruses
BRIDGE_APART = 2.0  # a part whose harmony is this many times further from every other part than usual: the bridge


def _energy(p) -> float:
    return 0.55 * p.loudness_pct + 0.45 * p.low_pct


def _bar_rows(a: Analysis, p) -> np.ndarray:
    """The bar chroma rows of a phrase."""
    if a.bar_chroma is None or not len(a.bar_chroma):
        return np.zeros((0, 12))
    db = a.beats[a.downbeats][: len(a.bar_chroma)] if len(a.downbeats) else a.beats[::4][: len(a.bar_chroma)]
    m = (db >= p.start - 0.05) & (db < p.end - 0.05)
    return a.bar_chroma[m]


def _apart(x: np.ndarray, y: np.ndarray) -> float:
    """How different two stretches' harmony is: per bar of one, its best match in the other (0: the same)."""
    if not len(x) or not len(y):
        return float("nan")
    s = x @ y.T
    return float(1 - (s.max(axis=1).mean() + s.max(axis=0).mean()) / 2)


def _vocals(a: Analysis, path: Path) -> bool:
    """Per phrase the share a voice sings the lead (Phrase.vocal); False when the track isn't separated."""
    from amadeus.audio import stems as stemlib

    got = stemlib.vocal_presence(path) if path.exists() else None
    if got is None:
        return False
    sung, alive, fps = got
    for p in a.phrases:
        s = slice(int(p.start * fps), max(int(p.end * fps), int(p.start * fps) + 1))
        al = alive[s]
        p.vocal = round(float(sung[s][al].mean()), 2) if al.any() else 0.0
    return True


def _real_drop(a: Analysis, i: int, voiced: bool) -> bool:
    """Inside a song: is phrase i (a jump the detector calls a drop) a real drop? The beat was taken away before
    it, and the voice steps back as it slams in, or it comes after a pause or a roll (with at most a little voice
    over it). A voice resting over a running beat (Billie Jean's break) is no drop."""
    p, prev = a.phrases[i], a.phrases[i - 1]
    gone = prev.kick_ratio <= BEAT_GONE_KICK or prev.low_pct <= BEAT_GONE_LOW
    if not gone:
        return False
    if voiced and p.vocal <= DROP_VOCAL_AFTER and (prev.vocal >= DROP_VOCAL_BEFORE or prev.vocal < SUNG):
        return True
    k = int(np.searchsorted(a.beats, p.start - 0.05))
    rolled = a.roll is not None and len(a.roll) == len(a.beats) and bool((a.roll[max(0, k - 16) : k] > 0).any())
    paused = a.pauses is not None and len(a.pauses) and bool(np.any(np.abs(np.asarray(a.pauses)[:, 1] - p.start) < 0.5))
    return (rolled or paused) and (not voiced or p.vocal < DROP_SUNG)


def facts(a: Analysis, path: str | Path) -> dict:
    """What the audio says about the form. `song`: True (verses and choruses), False (a club track) or None (it
    can't tell: without separated vocals only produced copies give a club track away)."""
    ph = a.phrases
    if not ph:
        return {"song": None}
    voiced = _vocals(a, Path(path))
    mid = [p for p in ph if p.start > 0.05 * a.duration and p.end < 0.95 * a.duration] or ph
    level = np.percentile([p.loudness_pct for p in mid], 60)
    loud = [p for p in mid if p.loudness_pct >= level]
    out: dict = {}
    if len(loud) > 1 and a.bar_chroma is not None and len(a.bar_chroma):
        rows = [_bar_rows(a, p) for p in loud]
        d = [_apart(r, np.vstack([x for j, x in enumerate(rows) if j != k])) for k, r in enumerate(rows)]
        d = [x for x in d if x == x]
        if d:
            out["copies"] = round(float(np.mean(d)), 4)
    if a.instruments is not None:
        names = list(a.instruments["names"])
        top = np.asarray(a.instruments["probs"]).argmax(axis=1)
        for fam in ("synth", "guitar"):
            if fam in names:
                out[f"{fam}_led"] = round(float((top == names.index(fam)).mean()), 2)
    drops = [i for i, p in enumerate(ph) if i and p.drop_score >= DROP_THRESHOLD]
    if voiced:
        w = np.array([p.end - p.start for p in ph])
        out["vocal_share"] = round(float(np.sum(w * [p.vocal for p in ph]) / w.sum()), 2)
        out["vocal_loud"] = round(float(np.mean([p.vocal for p in loud])) if loud else 0.0, 2)
        # drops the voice steps back for: what a club track does
        out["instrumental_drops"] = sum(
            1 for i in drops if ph[i - 1].vocal >= DROP_VOCAL_BEFORE and ph[i].vocal <= DROP_VOCAL_AFTER
        )
    copied = out.get("copies", 1.0) <= COPIES
    if copied or out.get("synth_led", 0.0) >= SYNTH_LED:
        out["song"] = False
    elif voiced:
        out["song"] = bool(
            out["vocal_loud"] >= VOCAL_LOUD and out["vocal_share"] >= VOCAL_SHARE and not out["instrumental_drops"]
        )
    else:
        out["song"] = None
    return out


def decide(call, song: dict) -> str:
    """The form: the genre's when it is known, else the audio's."""
    if call.source in KNOWN:
        return "song" if call.genre in SONG_GENRES else "club" if call.genre in CLUB_GENRES else ""
    return {True: "song", False: "club"}.get(song.get("song"), "")


def apply(a: Analysis, call, song: dict) -> None:
    """Decide the form and, in a song, check its drops and name each phrase's part."""
    a.form = decide(call, song)
    a.form_facts = dict(song)
    if a.form != "song" or not a.phrases:
        return
    ph = a.phrases
    voiced = any(p.vocal >= 0 for p in ph)
    for i in range(1, len(ph)):
        if ph[i].drop_score >= DROP_THRESHOLD and not _real_drop(a, i, voiced):
            ph[i].lift, ph[i].drop_score = ph[i].drop_score, 0.0  # a chorus coming in, not a drop
    for p, part in zip(ph, parts(a, voiced)):
        p.part = part
    a.form_facts["parts"] = " ".join(p.part for p in ph)


def _choruses(a: Analysis, body: list[int]) -> tuple[list[int], float]:
    """Which of the sung phrases are choruses, and how much louder they are than the verses (percentile points).
    The sung phrases fall into a quieter and a louder group; a phrase near the line between them joins the group
    it shares its chords with (a quieter last chorus is still a chorus). The chords only break ties: within one
    key a verse and a chorus share most of their notes, so on their own they are too weak a clue."""
    ph = a.phrases
    e = np.array([_energy(ph[i]) for i in body])
    cut = float(e.mean())
    for _ in range(10):  # two means in one dimension
        hi, lo = e[e >= cut], e[e < cut]
        if not len(hi) or not len(lo):
            break
        cut = (hi.mean() + lo.mean()) / 2
    hi_set = [i for i, x in zip(body, e) if x >= cut]
    lo_set = [i for i, x in zip(body, e) if x < cut]
    if not hi_set or not lo_set:
        return [], 0.0
    contrast = float(np.mean([_energy(ph[i]) for i in hi_set]) - np.mean([_energy(ph[i]) for i in lo_set]))
    if contrast < VERSE_CHORUS_MIN:
        return [], contrast  # one level all through (a lot of rap): verses
    rows = {i: _bar_rows(a, ph[i]) for i in body}
    if a.bar_chroma is not None and all(len(r) for r in rows.values()):
        for i in body:
            if abs(_energy(ph[i]) - cut) >= contrast / 4:
                continue
            to_hi = np.nanmean([_apart(rows[i], rows[j]) for j in hi_set if j != i] or [np.nan])
            to_lo = np.nanmean([_apart(rows[i], rows[j]) for j in lo_set if j != i] or [np.nan])
            if to_hi < 0.8 * to_lo and i in lo_set:
                lo_set.remove(i)
                hi_set.append(i)
            elif to_lo < 0.8 * to_hi and i in hi_set:
                hi_set.remove(i)
                lo_set.append(i)
    return hi_set, contrast


def parts(a: Analysis, voiced: bool) -> list[str]:
    """Each phrase's part of the song."""
    ph = a.phrases
    n = len(ph)
    sung = [p.vocal >= SUNG if voiced else True for p in ph]
    out = [""] * n
    # the edges: before the voice (or a drop) comes in and after it has gone (without vocals: a quiet start, a
    # fading end)
    music = [s or p.drop_score >= DROP_THRESHOLD for s, p in zip(sung, ph)]
    if voiced and any(music):
        first, last = music.index(True), n - 1 - music[::-1].index(True)
        for i in range(n):
            if i < first and ph[i].start < 0.3 * a.duration:
                out[i] = "intro"
            elif i > last and ph[i].end > 0.7 * a.duration:
                out[i] = "outro"
    else:
        if n > 2 and ph[0].loudness_pct < 40:
            out[0] = "intro"
        if n > 2 and ph[-1].loudness_slope_db < 0 and ph[-1].start > 0.85 * a.duration:
            out[-1] = "outro"
    for i, p in enumerate(ph):
        if not out[i] and p.drop_score >= DROP_THRESHOLD:
            out[i] = "drop"
        elif not out[i] and not sung[i]:
            out[i] = "instrumental"
    body = [i for i in range(n) if not out[i]]
    if not body:
        return [x or "verse" for x in out]
    hi_set, contrast = _choruses(a, body)
    rows = {i: _bar_rows(a, ph[i]) for i in body}
    harmony = a.bar_chroma is not None and all(len(r) for r in rows.values())
    for i in body:
        out[i] = "chorus" if i in hi_set else "verse"
    choruses = sorted(hi_set)
    # the bridge: after the first chorus, the one part whose harmony is like nothing else in the song
    if harmony and len(body) >= 4 and choruses:
        near = {i: np.nanmin([_apart(rows[i], rows[j]) for j in body if j != i]) for i in body}
        usual = float(np.nanmedian(list(near.values())))
        late = [i for i in body if i > choruses[0] and near[i] > BRIDGE_APART * max(usual, 1e-3)]
        if late:
            out[max(late, key=lambda i: near[i])] = "bridge"
    # the pre-chorus: a verse's last stretch that climbs into the chorus
    for i in range(1, n - 1):
        between = out[i] == "verse" and out[i + 1] == "chorus" and out[i - 1] == "verse" and ph[i].bars <= 8
        if between and (ph[i].loudness_slope_db >= 1.5 or _energy(ph[i]) > _energy(ph[i - 1]) + contrast / 3):
            out[i] = "prechorus"
    return out
