"""The DMX trace: every value that goes out to the lights, as it changes: when, to which fixture, on which channel.

For finding out why a light did what it did. Switched on and off while the engine runs (the apps' Engine page, or
by hand: make or remove the flag file): while `.cache/dmx-trace` exists, every output (a show, the setup page's
Identify, Check Channels) writes what it really sends to `.cache/dmx-trace.log`, one line per channel that changed:

    14:03:07.412  U1.017  mh1    pan         127 → 131
    14:03:07.412  U1.018  mh1    pan_fine     12 → 200
    14:03:07.437  U1.021  mh1    dimmer        0 → 255

The time is the moment the frame was handed to the output (this computer's clock, to the millisecond), `U1.017` the
set's universe and DMX channel, then the fixture and its channel as the fixture's chart names it (a second cell or
head as `red #2`). A channel no fixture is patched on shows as `-`. The first frame after switching on lists every
channel that isn't 0 (`· → 131`); after that only changes, so a light that holds still writes nothing.

The lines are written off the light loop (a thread, ten times a second), so tracing doesn't move the frames it
reports. The file starts over at 32 MB (the lines before stay in `dmx-trace.log.1`).
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from collections import deque

from amadeus import paths

FLAG = paths.CACHE / "dmx-trace"
LOG = paths.CACHE / "dmx-trace.log"
MAX_BYTES = 32 << 20
CHECK_S = 0.5  # how often the flag file is looked at


class Trace:
    def __init__(self):
        self.names: dict[tuple[int, int], tuple[str, str]] = {}  # (universe, channel 1..512) → (fixture, channel)
        self.what = ""
        self.on = False
        self._widths = (1, 1)
        self._last: dict[int, bytes] = {}
        self._checked = -1e9
        self._pending: deque = deque()
        self._writing = threading.Lock()
        self._thread: threading.Thread | None = None

    def describe(self, rig: dict, what: str = ""):
        """Whose channels these are: the set's fixtures, so a line can name the fixture and its channel."""
        from amadeus.library import fixtures as fxlib

        self.what = what
        for fx in rig.get("fixtures", []):
            try:
                if not fxlib.patched(fx):
                    continue
                chans = fxlib.channels(fxlib.get(fx["fixture"]), fx["mode"])
            except (SystemExit, KeyError, TypeError):  # a fixture the library doesn't know: its channels stay "-"
                continue
            for i, c in enumerate(chans):
                head = c.get("head", 0)
                name = str(c.get("attr", "?")) + (f" #{head}" if head else "")
                self.names[(int(fx.get("universe", 1)), fx["address"] + i)] = (str(fx["id"]), name)
        if self.names:
            self._widths = tuple(min(24, max(len(n[k]) for n in self.names.values())) for k in (0, 1))

    def frame(self, universes: dict[int, bytes]):
        """A frame on its way out. Costs a clock read while the trace is off."""
        now = time.monotonic()
        if now - self._checked > CHECK_S:
            self._checked = now
            on = FLAG.exists()
            if on != self.on:
                self.on = on
                self._last.clear()  # switched on: the first frame says where every channel stands
                if on:
                    self._pending.append((time.time(), None, self.what))
        if not self.on:
            return
        t = time.time()
        for u, data in universes.items():
            data = bytes(data)
            was = self._last.get(u)
            if was == data:
                continue
            self._last[u] = data
            if was is None:
                changes = [(i, None, v) for i, v in enumerate(data) if v]
            else:
                was = was.ljust(len(data), b"\x00")
                changes = [(i, a, b) for i, (a, b) in enumerate(zip(was, data)) if a != b]
            if changes:
                self._pending.append((t, u, changes))
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="dmx-trace", daemon=True)
            self._thread.start()

    def _run(self):
        while True:
            time.sleep(0.1)
            self.flush()

    @staticmethod
    def _stamp(t: float) -> str:
        return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"

    def lines(self, t: float, universe: int | None, changes) -> list[str]:
        stamp = self._stamp(t)
        if universe is None:
            return [f"# {stamp}  trace on" + (f": {changes}" if changes else "")]
        wf, wc = self._widths
        out = []
        for i, a, b in changes:
            fid, chan = self.names.get((universe, i + 1), ("-", "-"))
            was = "·" if a is None else str(a)
            out.append(f"{stamp}  U{universe}.{i + 1:03d}  {fid:<{wf}}  {chan:<{wc}}  {was:>3} → {b:>3}")
        return out

    def flush(self):
        """Writes what is waiting. Never raises: a trace that can't be written must not stop the lights."""
        with self._writing:
            out = []
            while self._pending:
                out += self.lines(*self._pending.popleft())
            if not out:
                return
            try:
                LOG.parent.mkdir(parents=True, exist_ok=True)
                if LOG.exists() and LOG.stat().st_size > MAX_BYTES:
                    try:
                        os.replace(LOG, LOG.with_name(LOG.name + ".1"))
                    except OSError:  # held open by a reader (Windows): start over in place
                        LOG.write_text("", encoding="utf-8")
                with open(LOG, "a", encoding="utf-8") as f:  # append: a show and the setup page can share it
                    f.write("\n".join(out) + "\n")
            except OSError:
                pass


TRACE = Trace()
atexit.register(TRACE.flush)


def describe(rig: dict, output: str = ""):
    command = " ".join(sys.argv[1:2])
    TRACE.describe(rig, f"{output} (amadeus {command})" if command else output)


def frame(universes: dict[int, bytes]):
    TRACE.frame(universes)


def flush():
    TRACE.flush()
