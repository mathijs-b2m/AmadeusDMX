"""The sync test track: the analysis must get it exactly (tempo, beats, bar lines, drops), and the listener's
summary must turn beeps into an offset and a drift."""

import contextlib
import io
import json

import numpy as np

from amadeus.audio import analysis, genre
from amadeus.director.prompt import drop_scores
from amadeus.show import synctest


def test_the_analysis_gets_the_sync_track_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(genre, "from_model", lambda *a, **k: None)  # (no AI call for the genre)
    wav, side = synctest.make(tmp_path / "music")
    truth = json.loads(side.read_text())
    with contextlib.redirect_stdout(io.StringIO()):
        a = analysis.analyze(wav, cache_dir=tmp_path / "cache")
    assert abs(a.bpm - synctest.BPM) < 0.05
    beats = truth["first_beat"] + np.arange(synctest.BARS * 4) * 60 / synctest.BPM
    err = [float(np.min(np.abs(a.beats - t))) for t in beats[8:-8]]
    assert max(err) < 0.01  # every beat within 10 ms
    bars = a.beats[a.downbeats]
    assert all(np.min(np.abs(bars - t)) < 0.02 for t in beats[16:-16:4])  # the bar lines on the one
    drops = [p.start for p, s in zip(a.phrases, drop_scores(a)) if s >= 0.5]
    assert len(drops) == len(truth["drops"]) and np.allclose(drops, truth["drops"], atol=0.02)


def test_the_summary_reads_offset_and_drift():
    rows = [(t, t, -1.5 + 0.001 * t) for t in range(0, 120, 8)]  # 1.5 s behind, falling behind 60 ms a minute
    out = synctest.summary(rows)
    assert abs(out["offset_ms"] + 1440) < 60
    assert abs(out["drift_ms_per_min"] - 60) < 1
