"""Rock plays the drum kit: the kick and the snare as two voices by whole groups, the snare ringing out with its
reverb, read from the separated drums; the guitar's strums on the accent lights."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import drums
from amadeus.director import RuleDirector, direct
from amadeus.director.style import style_for
from amadeus.engine import Engine
from amadeus.engine import looks as L
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_reggaeton import flicker

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
SR = 22050
BPM = 100.0


def drum_track(reverb: float, bars: int = 24, seed: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A rock beat as a separated drum part: kick on 1 and 3, snare on 2 and 4 (its reverb rings `reverb` s),
    hi-hats on the 8ths, a guitar's bleed nowhere. → (audio, kick times, snare times)"""
    rng = np.random.default_rng(seed)
    beat = 60 / BPM
    n = int((bars * 4 * beat + 2) * SR)
    x = np.zeros(n, np.float32)

    def hit(t0, sound):
        a = int(t0 * SR)
        m = min(len(sound), n - a)
        x[a : a + m] += sound[:m]

    tt = np.arange(int(1.5 * SR)) / SR
    kick = np.sin(2 * np.pi * 55 * tt) * np.exp(-tt / 0.12) + 0.3 * rng.normal(0, 1, len(tt)) * np.exp(-tt / 0.005)
    noise = rng.normal(0, 1, len(tt))
    snare = 0.6 * np.sin(2 * np.pi * 200 * tt) * np.exp(-tt / 0.05) + 0.5 * noise * np.exp(-tt / 0.04)
    snare += 0.3 * rng.normal(0, 1, len(tt)) * np.exp(-tt / max(reverb / 3, 0.01))  # the reverb's tail
    hat = np.diff(rng.normal(0, 1, int(0.05 * SR) + 1)) * np.exp(-np.arange(int(0.05 * SR)) / SR / 0.01) * 0.05
    beats = 1.0 + np.arange(bars * 4) * beat
    kicks, snares = beats[0::2], beats[1::2]
    for t0 in kicks:
        hit(t0, kick.astype(np.float32))
    for t0 in snares:
        hit(t0, snare.astype(np.float32))
    for t0 in np.sort(np.concatenate([beats, beats + beat / 2])):
        hit(t0, hat.astype(np.float32))
    return x, kicks, snares


def test_the_kick_and_the_snare_are_told_apart_in_the_drums():
    x, kicks, snares = drum_track(reverb=0.6)
    kit = drums.detect(x, SR)
    assert kit.source == "stem"
    for want, got in ((kicks, kit.kick_t), (snares, kit.snare_t)):
        assert abs(len(got) - len(want)) <= 1
        assert np.median(np.min(np.abs(got[:, None] - want[None, :]), axis=1)) < 0.03  # on the hits
    assert np.min(np.abs(kit.kick_t[:, None] - snares[None, :])) > 0.2  # no snare taken for a kick


def test_the_snare_rings_as_long_as_its_reverb():
    dry, wet = (drums.detect(drum_track(reverb=r)[0], SR) for r in (0.05, 0.8))
    assert np.median(wet.snare_ring) > np.median(dry.snare_ring) + 0.2


def test_one_wide_cluster_is_no_kit():
    rng = np.random.default_rng(1)
    d = rng.normal(0, 8, 400)  # cymbals over everything: the hits don't fall into kicks and snares
    assert drums._split(d, np.full(400, -10.0) + rng.normal(0, 1, 400)) is None
    two = np.concatenate([rng.normal(-18, 3, 200), rng.normal(7, 3, 200)])
    assert -12 < drums._split(two, np.full(400, -10.0) + rng.normal(0, 1, 400)) < 1


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis(bpm=BPM)


def _plan(a, rig, genre):
    return direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), style_for(genre)),
                  verbose=False)  # fmt: skip


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_rock_plays_the_kit(track, path):
    a, rig = track, load_rig(path)
    plan = _plan(a, rig, "rock")
    body = [d for d in plan if d.section in ("groove", "verse", "chorus", "drop") and d.trigger != "accents"]
    assert body and all(d.trigger == "drums" for d in body)
    e = Engine(a, plan, rig)
    assert e.kit.source == "mix"  # (no separated drums here: the analysis' own kick and snare)
    # two voices, and still no flicker: no more fast on-off cycles than the same track lit as pop
    assert flicker(e, rig, a) <= flicker(Engine(a, _plan(a, rig, "pop"), rig), rig, a)
    lights = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    if len(lights) < 2:
        return
    d = max((d for d in body if d.par_accent != "none"), key=lambda d: d.end - d.start)
    voices = {i: e._voice(d, i) for i in lights}
    assert set(voices.values()) == {"boom", "tac"}  # the kick and the snare, by whole groups
    guitar = e._accent_players(d, d.start + 1)
    kick = next((i for i in lights if voices[i] == "boom" and i not in guitar), None)
    snare = next((i for i in lights if voices[i] == "tac" and i not in guitar), None)
    if kick is None or snare is None:
        return

    def at(pid, times):  # the light's level just after these hits, in the phrase
        times = times[(times > d.start + 1) & (times < d.end - 1)]
        return np.mean([e.render(float(x) + 0.1)[1][pid].dimmer for x in times])

    alone = e.kit.kick_t[np.min(np.abs(e.kit.kick_t[:, None] - e.kit.snare_t[None, :]), axis=1) > 0.15]
    assert at(kick, alone) > 2 * at(snare, alone)  # the kick's groups play the kick …
    assert at(snare, e.kit.snare_t) > 1.5 * at(snare, alone)  # … the snare's the snare


def _kit_engine(track):
    rig = load_rig(SETS[0])
    plan = _plan(track, rig, "rock")
    e = Engine(track, plan, rig)
    d = max((d for d in plan if d.trigger == "drums" and d.par_accent != "none"), key=lambda d: d.end - d.start)
    return e, d


def test_the_snare_light_rings_with_the_snare(track):
    e, d = _kit_engine(track)
    s = e.kit.snare_t[(e.kit.snare_t > d.start + 2) & (e.kit.snare_t < d.end - 2)][0]
    e.kit.snare_ring[:] = 0.15
    short = e._kit_voices(float(s) + 0.3)[1]
    e.kit.snare_ring[:] = 0.6
    long = e._kit_voices(float(s) + 0.3)[1]
    assert long > short + 0.3  # a big reverb keeps its light up longer


def test_where_the_drums_rest_the_light_holds(track):
    e, d = _kit_engine(track)
    a0, a1 = d.start + 2, d.start + 8  # the drums stop for six seconds
    k = e.kit
    keep_k, keep_s = (k.kick_t < a0) | (k.kick_t >= a1), (k.snare_t < a0) | (k.snare_t >= a1)
    e.kit = drums.Kit(k.kick_t[keep_k], k.kick_s[keep_k], k.snare_t[keep_s], k.snare_s[keep_s], k.snare_ring[keep_s])
    assert e._kit_voices(a0 + 3)[:2] == (L.KIT_HOLD, L.KIT_HOLD)  # steady, not dark
