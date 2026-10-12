"""`amadeus probe NAME`: watch a DJ software integration, measure it, record it, or pass it on.

Every second one line per deck (track, position, tempo, volume) and every event as it happens; at the end,
how well the source keeps time:

  readings/s   how often it reports
  gap max      the longest silence between two readings
  drift        per reading: where the deck is minus where the previous reading said it would be by now
               (seeks and loops excluded). Small = a steady, trustworthy playhead.

--emit HOST:PORT sends the decks on in the AmadeusLink plugin's format (25 per second): to
127.0.0.1:9123 on a DJ laptop, the Amadeus Link app carries any DJ software to the lighting computer
exactly as it carries VirtualDJ. --record FILE keeps every reading for `--source replay --opt file=FILE`.
"""

from __future__ import annotations

import json
import signal
import socket
import statistics
import time
from pathlib import Path

from amadeus.show.sources import SOURCES, Source, open_source

EMIT_HZ = 25


def plugin_packet(src: Source, now: float, t0: float) -> dict:
    """The decks as the AmadeusLink plugin would send them (positions extrapolated to `now`)."""
    return {
        "t": int((now - t0) * 1000),
        "app": src.label,  # which DJ software (the VirtualDJ plugin sends none: the Link app assumes VirtualDJ)
        "master": src.master,
        "decks": [
            {
                "deck": d.deck,
                "file": d.file,
                "pos": round(d.now(now), 4),
                "len": d.length,
                "play": int(d.play),
                "bpm": d.bpm,
                "bpm0": d.bpm0,
                "vol": round(d.vol, 4),
                **({"title": d.title} if d.title else {}),
                **({"artist": d.artist} if d.artist else {}),
                **({"id": d.track_id} if d.track_id else {}),
                **({"phase": round(d.phase_at(now), 4)} if d.phase is not None else {}),
            }
            for d in sorted(src.decks.values(), key=lambda d: d.deck)
        ],
    }


class Stats:
    def __init__(self):
        self.times: list[float] = []
        self.drift: list[float] = []  # seconds
        self.prev: dict = {}

    def reading(self, src: Source, now: float, seeks: set[int]):
        self.times.append(now)
        for d in src.decks.values():
            old = self.prev.get(d.deck)
            if old and old.play and d.play and d.deck not in seeks and d.received > old.received:
                self.drift.append(d.pos - old.now(d.received))
            self.prev[d.deck] = d

    def summary(self) -> str:
        if len(self.times) < 2:
            return "no readings"
        span = self.times[-1] - self.times[0]
        gaps = [b - a for a, b in zip(self.times, self.times[1:])]
        out = f"{len(self.times) / span:.1f} readings/s, gap max {max(gaps) * 1000:.0f} ms"
        if self.drift:
            ad = sorted(abs(x) * 1000 for x in self.drift)
            out += (
                f", drift median {statistics.median(ad):.1f} ms, p95 {ad[int(0.95 * (len(ad) - 1))]:.1f} ms, "
                f"max {ad[-1]:.1f} ms over {len(ad)} readings"
            )
        return out


def run(name: str, opts: dict, seconds: float = 0.0, emit: str | None = None, record: Path | None = None):
    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)  # `kill`: stop the same way as Ctrl+C, with the summary
    src = open_source(name, **opts)
    print(f"Probing {src.name} ({SOURCES[name].position} position){' – Ctrl+C to stop' if not seconds else ''}")
    out = None
    if emit:
        host, _, port = emit.rpartition(":")
        out = (socket.socket(socket.AF_INET, socket.SOCK_DGRAM), (host or "127.0.0.1", int(port)))
        print(f"Sending the decks to {out[1][0]}:{out[1][1]} in the AmadeusLink plugin's format")
    rec = open(record, "w") if record else None  # noqa: SIM115  (closed below, with the source)
    stats, t0 = Stats(), time.monotonic()
    seen_packets, shown, next_emit, last_event = 0, 0.0, t0, 0
    try:
        while not seconds or time.monotonic() - t0 < seconds:
            now = time.monotonic()
            seeks = set()
            for e in [e for e in list(src.events) if e.n > last_event]:
                last_event = e.n
                print(f"  ⚑ deck {e.deck} {e.kind} {json.dumps(e.data)}", flush=True)
                if e.kind in ("seek", "loop", "track_loaded"):
                    seeks.add(e.deck)
            if src.packets != seen_packets:
                seen_packets = src.packets
                stats.reading(src, src.last, seeks)
                if rec:
                    rec.write(
                        json.dumps({**plugin_packet(src, src.last, t0), "t": round(src.last - t0, 4), "at": src.last})
                        + "\n"
                    )
            if out and now >= next_emit:
                next_emit += 1 / EMIT_HZ
                if src.alive():
                    out[0].sendto(json.dumps(plugin_packet(src, now, t0)).encode(), out[1])
            if now - shown >= 1.0:
                shown = now
                _show(src, now)
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        src.close()
        if rec:
            rec.close()
    print(f"\n{src.name}: {stats.summary()}", flush=True)
    return stats


def _show(src: Source, now: float):
    if not src.alive():
        print(f"  {time.strftime('%H:%M:%S')} {src.label}: nothing received", flush=True)
        return
    for d in sorted(src.decks.values(), key=lambda d: d.deck):
        what = f"{d.artist} – {d.title}" if d.title else (Path(d.file).name if d.file else "?")
        local = "" if d.file else "  (not found on this computer)"
        print(
            f"  {time.strftime('%H:%M:%S')} deck {d.deck} {'▶' if d.play else '■'} {d.now(now):7.2f}/{d.length:.0f}s "
            f"{d.bpm:6.2f} bpm ×{d.speed:.3f} vol {d.vol:.2f}  {what}{local}",
            flush=True,
        )
