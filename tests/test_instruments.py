"""Instruments: the mel input the MTG models expect, and accent lights that follow one instrument per phrase."""

from dataclasses import replace

import numpy as np

from amadeus.audio import instruments as I
from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


def test_the_mel_bands_are_essentias():
    fb = I._filterbank()
    assert fb.shape == (I.BANDS, I.FRAME // 2 + 1)
    hz = np.arange(I.FRAME // 2 + 1) * I.SR / I.FRAME
    area = fb.sum(1) * (hz[1] - hz[0])
    assert np.allclose(area[5:-5], 1.0, atol=0.15)  # unit area (Essentia's "unit_tri")
    m = I.melspectrogram(np.zeros(I.SR, np.float32))
    assert m.shape[1] == I.BANDS and np.allclose(m, 0)  # log10(1 + 10000·0)


def test_accent_lights_follow_one_instrument_per_phrase():
    a = synthetic_analysis()
    t = np.sort(np.random.default_rng(3).uniform(1, a.duration - 1, 600))
    s = np.random.default_rng(4).uniform(0.2, 1.0, len(t))
    a = replace(a, synth_notes=(t, s, np.zeros(len(t))))
    fam = (np.sin(t / 3) > 0).astype(np.int8)  # two instruments taking turns every few seconds
    jt = np.arange(0, a.duration, 1.0)
    probs = np.zeros((len(jt), 2), np.float32)
    plan = direct(a, RuleDirector(), verbose=False)
    for d in plan:  # the second instrument is the clearly present one in odd phrases
        m = (jt >= d.start) & (jt < d.end)
        probs[m, d.phrase % 2] = 0.7
        probs[m, 1 - d.phrase % 2] = 0.2
    a.instruments = {"t": jt, "probs": probs, "names": ["keys", "synth"], "note_family": fam}
    e = Engine(a, plan, load_rig("tests/sets/small.json"))
    for i, d in enumerate(plan):
        if not e.accent_family[i]:
            continue
        stabs = e.stab_t[(e.stab_t >= d.start) & (e.stab_t < d.end)]
        mine = fam[np.searchsorted(t, stabs)]
        assert len(set(mine.tolist())) == 1  # one instrument in a phrase
        assert e.accent_family[i] == ["keys", "synth"][d.phrase % 2]  # the one that's present


def test_a_new_melody_inside_a_phrase_splits_it():
    from amadeus.audio.analysis import _split_on_melody

    a = synthetic_analysis()
    bars = a.beats[a.downbeats]
    bar = float(np.median(np.diff(bars)))
    long = max(a.phrases, key=lambda p: p.end - p.start)
    assert (long.end - long.start) / bar >= 8
    change = long.start + 4 * bar  # four bars in: a new sound, an octave up
    jt = np.arange(0, a.duration, 1.0)
    rng = np.random.default_rng(5)
    base, other = rng.normal(size=1280), rng.normal(size=1280)
    sound = np.array([(other if t >= change and t < long.end else base) + 0.05 * rng.normal(size=1280) for t in jt])
    nt = np.arange(0.5, a.duration, 0.25)
    pitch = np.where((nt >= change) & (nt < long.end), 0.8, 0.3)
    a.synth_notes = (nt, np.ones(len(nt)), pitch)
    a.instruments = {"t": jt, "probs": np.zeros((len(jt), 2)), "names": ["keys", "synth"],
                     "note_family": np.zeros(len(nt), int), "sound": sound}  # fmt: skip
    before = len(a.phrases)
    _split_on_melody(a)
    new = [p for p in a.phrases if p.melody_change]
    assert len(a.phrases) == before + 1 and len(new) == 1
    assert abs(new[0].start - change) < 0.05  # on the bar line where it comes in
    assert [p.index for p in a.phrases] == list(range(len(a.phrases)))
