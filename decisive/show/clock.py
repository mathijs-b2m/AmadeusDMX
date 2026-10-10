"""Where a track is right now: the audible position (audio playback), or the system clock (silent)."""

from __future__ import annotations

import threading
import time

import soundfile as sf


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
