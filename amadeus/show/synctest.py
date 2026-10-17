"""Sync test: a track with beeps at known moments, and a listener that hears them and says how far the show is
from the music you hear.

`amadeus synctest make` writes the track (128 BPM, three minutes: intro, groove, a build-up, a drop, a breakdown,
a second build-up and drop) and next to it the exact times of its beeps and drops. A short, pure 3.15 kHz beep sits
on the downbeat of every fourth bar: nothing else in the track sounds there (no hi-hats; the build-up's noise is
low-passed), so the microphone finds it in the room even with the music loud.

`amadeus synctest listen` runs while you play that track in the DJ software with the live show running (or
`amadeus play` it). It hears each beep through the Mac's microphone, notes the moment, and reads where the show
was at that moment from the engine's feed. Each beep's place in the track is known, so the difference is the
show's offset from the music as heard: through the DJ software, its audio buffer, the speakers and the room.
Over the minutes the offsets also show drift (a slope), not just a fixed delay.

The show renders a little ahead of the music on purpose (the light lead, `artnet.lead_ms`, about 50 ms): the
fixtures need that long to show it. The listener reports the music the show is lighting, the lead taken out.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import numpy as np

BPM = 128.0
SR = 44100
START_S = 0.5  # the first beat (a little silence first: DJ software trims nothing)
BARS = 96
BEEP_HZ = 3150.0
BEEP_S = 0.06
BEEP_EVERY_BARS = 4
DROPS_AT_BARS = (32, 80)
NAME = "Amadeus - Sync Test 128"
HOLD_BLOCKS = 6  # the tone must hold this many blocks (~35 ms of the 60 ms beep)
OUTLIER_S = 0.25  # a beep this far from the others' median offset was another sound (the summary leaves it out)


def _sections(bar: int) -> str:
    if bar < 16:
        return "intro"
    if bar < 24:
        return "groove"
    if bar < 32 or 72 <= bar < 80:
        return "build"
    if bar < 64 or bar >= 80:
        return "drop"
    return "breakdown"


def make(out_dir: Path) -> tuple[Path, Path]:
    """Write the test track and its sidecar (the beeps' and drops' exact times, in seconds)."""
    import soundfile as sf
    from scipy.signal import butter, sosfilt

    beat = 60.0 / BPM
    n = int((START_S + BARS * 4 * beat + 2.0) * SR)
    x = np.zeros(n)
    rng = np.random.default_rng(7)

    def put(at: float, sig: np.ndarray, gain: float):
        i = int(round(at * SR))
        j = min(n, i + len(sig))
        x[i:j] += gain * sig[: j - i]

    tt = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 9)
    bass_t = np.arange(int(beat * 0.45 * SR)) / SR
    bass = np.sin(2 * np.pi * 55 * bass_t) * np.minimum(1, bass_t * 200) * np.exp(-bass_t * 4)
    stab_t = np.arange(int(0.22 * SR)) / SR
    stab = sum(np.sin(2 * np.pi * f * stab_t) for f in (220, 277.2, 329.6, 440)) * np.exp(-stab_t * 14) / 4
    pad_t = np.arange(int(4 * beat * SR)) / SR
    pad = sum(np.sin(2 * np.pi * f * pad_t) for f in (110, 164.8, 220)) / 3 * np.sin(np.pi * pad_t / pad_t[-1])
    low = butter(4, 1800, "low", fs=SR, output="sos")

    beeps, drops = [], []
    for bar in range(BARS):
        sec = _sections(bar)
        t_bar = START_S + bar * 4 * beat
        if bar in DROPS_AT_BARS:
            drops.append(t_bar)
        if sec in ("intro", "breakdown"):
            put(t_bar, pad, 0.25)
        for b in range(4):
            t = t_bar + b * beat
            if sec != "build" and sec != "breakdown":
                put(t, kick, 0.9)
            if sec in ("groove", "drop"):
                put(t + beat / 2, bass, 0.45)
            if sec == "drop" and b in (1, 3):
                put(t + beat * 0.75, stab, 0.5)
        if sec == "build":  # a rising low-passed noise and a snare roll that speeds up
            k = bar - (24 if bar < 32 else 72)
            seg = sosfilt(low, rng.standard_normal(int(4 * beat * SR)))
            put(t_bar, seg * np.linspace(k / 8, (k + 1) / 8, len(seg)), 0.25)
            hits = 4 if k < 4 else 8 if k < 6 else 16
            snare = sosfilt(low, rng.standard_normal(int(0.08 * SR))) * np.exp(-np.arange(int(0.08 * SR)) / SR * 40)
            for h in range(hits):
                put(t_bar + h * 4 * beat / hits, snare, 0.3 + 0.4 * k / 8)
        if bar % BEEP_EVERY_BARS == 0:
            bt = np.arange(int(BEEP_S * SR)) / SR
            beep = np.sin(2 * np.pi * BEEP_HZ * bt) * np.minimum(1, np.minimum(bt, BEEP_S - bt) * 2000)
            put(t_bar, beep, 0.5)
            beeps.append(t_bar)
    x /= np.max(np.abs(x)) * 1.12
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / f"{NAME}.wav"
    sf.write(wav, np.stack([x, x], axis=1).astype(np.float32), SR, subtype="PCM_16")
    side = out_dir / f"{NAME}.json"
    side.write_text(
        json.dumps({"bpm": BPM, "first_beat": START_S, "beeps": beeps, "drops": drops}, indent=1), encoding="utf-8"
    )
    return wav, side


# ------------------------------------------------------------------------------------------- listening


class _Ears:
    """The microphone: the moments (time.monotonic) a 3.15 kHz beep starts."""

    BLOCK = 256  # ~6 ms at 44.1 kHz

    def __init__(self):
        import sounddevice as sd

        self.onsets: list[float] = []
        self.level: list[float] = []  # the beep band's level per block (for the threshold)
        self.floor = None
        self.last = -1.0
        self.run: list | None = None  # the tone now sounding: [when it started, blocks so far]
        w = np.hanning(self.BLOCK)
        k = np.arange(self.BLOCK)
        self.probe = w * np.exp(-2j * np.pi * BEEP_HZ * k / SR)  # one DFT bin at the beep's pitch
        self.near = [w * np.exp(-2j * np.pi * f * k / SR) for f in (BEEP_HZ * 0.8, BEEP_HZ * 1.25)]
        self.stream = sd.InputStream(samplerate=SR, channels=1, blocksize=self.BLOCK, callback=self._cb)

    def _cb(self, data, frames, info, status):
        now = time.monotonic()
        heard = now - (self.stream.time - info.inputBufferAdcTime)  # when this block's first sample came in
        x = data[:, 0]
        e = abs(np.dot(x, self.probe))
        side = max(abs(np.dot(x, n)) for n in self.near)
        self.floor = e if self.floor is None else 0.995 * self.floor + 0.005 * min(e, self.floor * 3)
        tone = e / (side + 1e-9) > 6 and e > 8 * (self.floor or 1e-9)
        if not tone:
            self.run = None
            return
        if self.run is None:  # the tone starts in this block: place it to the sample with the band's envelope
            env = np.abs(np.convolve(x, np.exp(-2j * np.pi * BEEP_HZ * np.arange(64) / SR), "same"))
            self.run = [heard + int(np.argmax(env > 0.3 * env.max())) / SR, 0]
        self.run[1] += 1
        # a beep holds its pitch for 60 ms: a short burst there (a snare, a stab's overtone) is not one
        if self.run[1] == HOLD_BLOCKS and self.run[0] - self.last > 1.0:
            self.last = self.run[0]
            self.onsets.append(self.last)

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()


async def _feed(url: str, seen: list, stop: threading.Event):
    """The show's position over time: (time.monotonic, t) from the engine's lite feed."""
    from websockets.asyncio.client import connect

    while not stop.is_set():
        try:
            async with connect(url) as ws:
                while not stop.is_set():
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                    if msg.get("type") == "frame" and "t" in msg:
                        seen.append((time.monotonic(), float(msg["t"])))
        except Exception:  # no show yet, or the connection closed: try again
            await asyncio.sleep(0.5)


def _show_at(seen: list, when: float) -> float | None:
    """Where the show was at `when`: a straight line through the feed's frames around it (a few per second)."""
    pts = [(w, t) for w, t in seen if abs(w - when) < 1.5]
    if len(pts) < 3:
        return None
    w, t = np.array(pts).T
    if np.ptp(t) > 3.0:  # a jump (seek, another track) inside the window
        return None
    slope, icept = np.polyfit(w - when, t, 1)
    return float(icept)


def listen(sidecar: Path, seconds: float, ws_port: int, lead_s: float) -> dict:
    beeps = np.array(json.loads(sidecar.read_text(encoding="utf-8"))["beeps"])
    spacing = float(np.median(np.diff(beeps)))
    seen: list = []
    stop = threading.Event()
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=lambda: loop.run_until_complete(_feed(f"ws://127.0.0.1:{ws_port}/lite", seen, stop)))
    th.daemon = True
    th.start()
    rows = []
    print(f"Listening for {seconds:.0f} s: play '{NAME}' now (the show running). Ctrl+C stops early.", flush=True)
    t0 = time.monotonic()
    done = 0
    try:
        with _Ears() as ears:
            while time.monotonic() - t0 < seconds:
                time.sleep(0.25)
                while done < len(ears.onsets):
                    heard = ears.onsets[done]
                    done += 1
                    time.sleep(max(0.0, heard + 1.6 - time.monotonic()))  # the feed after the beep, too
                    show = _show_at(seen, heard)
                    if show is None:
                        print("  beep heard, but no show position around it (is the show running?)", flush=True)
                        continue
                    music = show - lead_s  # the music the show was lighting
                    k = int(np.argmin(np.abs(beeps - music)))
                    off = music - beeps[k]  # > 0: the show is ahead of what you hear; < 0: behind
                    if abs(off) > spacing / 2:
                        continue
                    rows.append((heard - t0, float(beeps[k]), off))
                    word = "ahead" if off > 0 else "behind"
                    print(f"  beep {beeps[k]:6.2f}s  show {abs(off) * 1000:5.0f} ms {word}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return summary(rows)


def summary(rows: list[tuple[float, float, float]]) -> dict:
    """Offset (median, spread) and drift (a slope over the minutes) from (when, beep, offset) rows."""
    if len(rows) < 2:
        return {"beeps": len(rows)}
    when, _, off = np.array(rows).T
    keep = np.abs(off - np.median(off)) <= OUTLIER_S  # a sound taken for a beep: not a measurement
    when, off = when[keep], off[keep]
    out = {
        "beeps": int(keep.sum()),
        "ignored": int((~keep).sum()),
        "offset_ms": round(float(np.median(off)) * 1000, 1),
        "spread_ms": round(float(np.percentile(off, 90) - np.percentile(off, 10)) * 1000, 1),
    }
    if np.ptp(when) > 20:
        out["drift_ms_per_min"] = round(float(np.polyfit(when / 60, off * 1000, 1)[0]), 1)
    return out
