# Fixture twin

The visualiser draws where the engine *thinks* a moving head points: its own motor model of the fixture.
The real fixture only gets DMX. When the two disagree (a head that turns less far, or later, than the
visualiser shows), `tools/twin.py` finds out by how much, one fixture at a time.

The twin is a second model of one fixture that, like the real one, only gets DMX. It decodes the bytes
itself and moves with its own motors: what a full DMX sweep really turns (the range), top speed,
acceleration, braking, the delay from DMX to motion, firmware smoothing and the speed channel. You
calibrate those numbers against the real fixture by eye; then the twin tells you where the engine's
prediction is off, and **Apply** copies its range and speed into the engine's model of the fixture.

## Offline: the synthetic track

```bash
python tools/twin.py check fuze1 --bpm 145 --fit
```

The engine plays the synthetic test track, its DMX drives the twin, and the twin is compared with what
the visualiser would draw: the gap in degrees, the range (how far from home the twin stands for the angle
the visualiser shows, measured while both stand still) and the delay (how much later the twin moves).
Range and speed are told apart: a motor too slow to finish its moves shows up as late and as smaller
moves, not as a smaller range. `--fit` finds the engine motion numbers that best predict the twin,
`--apply` writes them (only when clearly better than the twin's own numbers).

An uncalibrated twin starts from the engine's own numbers (with the engine's 120 ms lead as its delay):
it then matches the visualiser within a couple of degrees, which shows the engine's prediction is
consistent with the DMX it sends. Any gap on the real fixture comes from those numbers.

## Live: next to the real fixture

The twin sits between the engine and the node, so it sees exactly the DMX the fixture gets:

```bash
python tools/twin.py live fuze1
```

```bash
decisive live --artnet 127.0.0.1
```

It listens on 127.0.0.1:6454 and relays every packet to the set's node (`--forward IP` for another one,
`--forward ''` for no relay), reads the running show's visualiser feed, and serves a page at
http://127.0.0.1:8790 with the DMX target, the visualiser's prediction and the twin side by side, live.
From the Mac app: point the set's Art-Net output at 127.0.0.1 for the session and start the twin with
`--forward` and your node's IP.

The show then sends to this computer, which it counts as "not real lights": risk group 2/3 fixtures are
not darkened and the laser guard doesn't insist on laser zones. Calibrate a set without lasers.

### Calibrating

The page's test patterns drive the fixture itself (the show's DMX is dropped while one runs):

1. **Range.** Hold, then set tilt to 90 (or pan to 180). Change the twin's range until the real head
   points exactly level (or exactly backwards): the DMX follows the range, so the head moves as you edit.
2. **Speed.** Marker: the head goes back and forth and is lit only while the *twin* says it stands still.
   A light streak while moving: the twin is too fast. Dark after stopping: too slow. Top speed with big
   moves (180°), acceleration and braking with small ones (20–40°), the delay last.
3. **Check.** Swing on beat at your usual tempo: does the real head turn back early, like the twin?

**Save twin** keeps the profile in the fixture's library file (`"twin"`). **Apply to engine** also writes
its range into `physical` and its speed into `motion`, and rescales the set's `pan_home_deg` /
`tilt_home_deg` so home stays on the same DMX value. Restart the show afterwards.
