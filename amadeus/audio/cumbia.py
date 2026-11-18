"""Cumbia, heard: its sound for the genre call, and the two voices its lights dance to.

**Sound.** Cumbia's tempo is hip-hop's and reggaeton's (85–105 BPM) and it is sung, so the beat and the form can't
call it (the audio made "La Colegiala" pop and "Cumbia Sobre El Mar" hip-hop). EffNet-Discogs hears the accordion or
the organ, the güiro and the bass on the beat: over 277 cached tracks the three cumbias (Rodolfo Aicardi's classic,
Quantic's nu-cumbia, Yerba Brava's cumbia villera) had 0.25–1.0 of their mass in FAMILY and led RIVALS 36–78% of the
time; everything else stayed under 0.18 and under 0.12 lead (Max Pizzolante's tropical pop 0.17 at 0.11, reggaeton
≤ 0.08). Vallenato is a rival: Bad Bunny's "Después de la Playa" plays one in its middle.

**Voices.** The dance is in the swing between the beat and its "and": the bass (and the kick, where there is one)
on the beat, the boom; the güiro's scrape, the llamador and the off-beat bass on the "and", the cha. Both are played
on every beat and every "and" where the swing runs (enough of them heard around it), on the hit itself where one is
heard: the swing never stops, so the lights keep dancing where the onset detector misses a hit.
"""

from __future__ import annotations

import numpy as np

from amadeus.audio.dembow import BOOM_RISE, _low_end, _typical_kick
from amadeus.audio.dembow import boom as dembow_boom
from amadeus.audio.model import Analysis

FAMILY = ("Latin---Cumbia", "Latin---Porro")
RIVALS = ("Latin---Reggaeton", "Latin---Vallenato", "Latin---Salsa", "Latin---Merengue", "Latin---Son",
          "Latin---Son Montuno", "Latin---Samba", "Latin---Bossanova", "Latin---Guaracha", "Latin---Cubano",
          "Latin---Afro-Cuban", "Latin---Rumba", "Latin---Forró", "Latin---Tango", "Latin---Norteño",
          "Latin---Ranchera", "Latin---Tejano", "Latin---Mariachi", "Latin---Cha-Cha", "Latin---Mambo",
          "Reggae---Dancehall", "Reggae---Reggae", "Reggae---Ska", "Reggae---Soca", "Hip Hop---Trap",
          "Electronic---Moombahton", "Funk / Soul---Afrobeat", "Electronic---Tropical House")  # fmt: skip

SOUND, LEAD = 0.2, 0.3  # this much in the family, leading its rivals this share of the time: it sounds like cumbia
HINT, HINT_LEAD = 0.12, 0.2  # a Latin call (the model, a tag) on a track that sounds like cumbia at least this much
BPM = (70, 130)  # cumbia's beat (the tracker can count its 8ths: twice this)

HIT_TOL_S = 0.05  # a hit this close to the beat (the boom) or its "and" (the cha) plays it
WINDOW = 4  # the swing runs where …
RUNS_SHARE = 0.3  # … this share of the beats this many beats around have a boom or a cha heard on them
FILL = 0.6  # the strength of a beat or an "and" the swing plays where no hit was heard
QUIET_PCT = 15  # (and the music is there: louder than the track's quietest this many percent)


def heard(f: dict, hint: bool = False) -> bool:
    """Does the track sound like cumbia? `hint`: a Latin call says so already, a little of the sound will do."""
    lo, lead = (HINT, HINT_LEAD) if hint else (SOUND, LEAD)
    bpm = f.get("bpm", 100.0)
    bpm = bpm / 2 if bpm > BPM[1] else bpm
    return f.get("cumbia", 0.0) >= lo and f.get("cumbia_lead", 0.0) >= lead and BPM[0] <= bpm <= BPM[1]


def judge(styles: np.ndarray, names: list[str]) -> dict:
    """From the Discogs style probabilities per judgement ((n, 400)): {"cumbia", "cumbia_lead"}."""
    mass = styles[:, [names.index(c) for c in FAMILY]].sum(1)
    rivals = styles[:, [names.index(c) for c in RIVALS if c in names]].sum(1)
    return {"cumbia": round(float(mass.mean()), 2), "cumbia_lead": round(float((mass > rivals).mean()), 2)}


def _heard_on(grid: np.ndarray, t: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per grid point the strongest hit within HIT_TOL_S of it: (its time, NaN where none; its strength)."""
    at, strength = np.full(len(grid), np.nan), np.zeros(len(grid))
    if not len(t):
        return at, strength
    j = np.searchsorted(t, grid)
    for k, g in enumerate(grid):
        near = [x for x in (j[k] - 1, j[k]) if 0 <= x < len(t) and abs(t[x] - g) <= HIT_TOL_S]
        if near:
            x = max(near, key=lambda x: s[x])
            at[k], strength[k] = t[x], float(s[x])
    return at, strength


def voices(a: Analysis) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Cumbia's two voices, (boom times, strengths, cha times, strengths): the boom on every beat and the cha on every
    "and" wherever the swing runs, at the hit's own time and strength where one is heard, else on the grid at FILL.
    The boom is heard as the kick and the bass on the beat (dembow's boom, without its off-beat 8ths); the cha as the
    hats' and the snare's hits on the "and" (the güiro, the llamador), or the bass's rise there."""
    b = a.beats
    empty = np.zeros(0), np.zeros(0, np.float32)
    if len(b) < 8:
        return (*empty, *empty)
    beats, mids = b[:-1], (b[:-1] + b[1:]) / 2
    bt, bs = dembow_boom(a)
    boom_at, boom_s = _heard_on(beats, bt, bs)
    t = np.concatenate([a.onsets.get(k, empty)[0] for k in ("hat", "snare")])
    s = np.concatenate([a.onsets.get(k, empty)[1] for k in ("hat", "snare")])
    order = np.argsort(t)
    cha_at, cha_s = _heard_on(mids, t[order], s[order])
    rise, level = _low_end(a)
    ref_rise, ref_level = _typical_kick(a, rise, level)
    for k, m in enumerate(mids):  # an off-beat bass note is a cha too (cumbia villera's bass plays the "and")
        if np.isnan(cha_at[k]) and rise(m) >= BOOM_RISE * ref_rise and level(m) >= ref_level - 12:
            cha_at[k], cha_s[k] = m, min(1.0, rise(m) / ref_rise)
    heard = ~np.isnan(boom_at) | ~np.isnan(cha_at)
    box = np.ones(2 * WINDOW + 1)
    share = np.convolve(heard.astype(float), box, "same") / np.convolve(np.ones(len(heard)), box, "same")
    frames = np.clip((beats * a.fps).astype(int), 0, len(a.rms_db) - 1)
    runs = (share >= RUNS_SHARE) & (a.rms_db[frames] > np.percentile(a.rms_db, QUIET_PCT))

    def played(grid, at, strength):
        times = np.where(np.isnan(at), grid, at)[runs]
        return times, np.clip(np.where(np.isnan(at), FILL, np.maximum(strength, FILL))[runs], 0, 1).astype(np.float32)

    return (*played(beats, boom_at, boom_s), *played(mids, cha_at, cha_s))
