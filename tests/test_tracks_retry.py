"""A track that can't be prepared isn't tried again for every packet (it once filled the log many times a second)."""

from amadeus.show import tracks


class Pool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append(args)


def test_a_failed_track_waits_before_trying_again(monkeypatch):
    ts = tracks.TrackShows.__new__(tracks.TrackShows)  # no engine: only the queueing
    import threading

    ts.lock, ts.shows, ts.pending, ts.failed, ts.pool = threading.Lock(), {}, set(), {}, Pool()
    now = [100.0]
    monkeypatch.setattr(tracks.time, "monotonic", lambda: now[0])
    ts.get("/x.webm")
    assert len(ts.pool.jobs) == 1  # the first time: prepared
    ts.pending.discard("/x.webm")
    ts.failed["/x.webm"] = now[0]  # and it failed
    for _ in range(50):  # 50 packets later: not again
        ts.get("/x.webm")
    assert len(ts.pool.jobs) == 1
    now[0] += tracks.RETRY_S
    ts.get("/x.webm")
    assert len(ts.pool.jobs) == 2  # half a minute later: once more
