"""Where a track is right now: the audible position (audio playback), or the system clock (silent)."""

from __future__ import annotations

import threading
import time

import soundfile as sf

LEAD_MS = 50  # default light lead: what a beat grid ~50 ms early used to give, and the rig was judged by


def light_lead(rig: dict) -> float:
    """How much earlier than the music the lights are rendered (seconds): the time a light takes to show what
    it is sent (Art-Net, the fixture's own processing) and the DJ software's audio buffer, together.
    `"artnet": {"lead_ms": …}` in the rig sets it; the beat grid itself is where the music is heard."""
    return float(rig.get("artnet", {}).get("lead_ms", LEAD_MS)) / 1000


class AudioClock:
    """Plays the file and reports the song position that is audible *right now*."""

    def __init__(self, path: str, start: float):
        import sounddevice as sd

        self.file = sf.SoundFile(path)
        self.sr = self.file.samplerate
        self.start = start
        self.file.seek(int(start * self.sr))
        self.frames_done = 0
        self.anchor: tuple[int, float] | None = None
        self.finished = threading.Event()
        self.stream = sd.OutputStream(
            samplerate=self.sr,
            channels=self.file.channels,
            dtype="float32",
            blocksize=1024,
            callback=self._callback,
            finished_callback=self.finished.set,
        )

    def _callback(self, outdata, frames, t, status):
        import sounddevice as sd

        data = self.file.read(frames, dtype="float32", always_2d=True)
        outdata[: len(data)] = data
        self.anchor = (self.frames_done, t.outputBufferDacTime)
        self.frames_done += len(data)
        if len(data) < frames:
            outdata[len(data) :] = 0
            raise sd.CallbackStop

    def begin(self):
        self.stream.start()

    def now(self) -> float:
        if self.anchor is None:
            return self.start
        f0, dac = self.anchor
        return self.start + f0 / self.sr + (self.stream.time - dac)

    def stop(self):
        self.stream.stop()
        self.stream.close()


class WallClock:
    """Silent mode: same timeline, driven by the system clock."""

    def __init__(self, start: float):
        self.start = start
        self.finished = threading.Event()
        self.t0 = time.monotonic()

    def begin(self):
        self.t0 = time.monotonic()

    def now(self) -> float:
        return self.start + time.monotonic() - self.t0

    def stop(self):
        pass
