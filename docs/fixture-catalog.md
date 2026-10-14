# Fixture catalogue

Any fixture works, not only the ones in `fixtures/`. Search covers three libraries at once: ours (checked
on real hardware), the QLC+ fixture library (~1,800, Apache-2.0) and the Open Fixture Library (~650, MIT).
Adding a fixture copies its definition into `fixtures/<brand>/<model>.json`, where it is an ordinary library
fixture that can be checked and calibrated (`amadeus test`, `colors`, `gobos`, `motion`, `tools/twin.py`).

## The shadow catalogue

Every QLC+ and OFL fixture, already converted to our format, ships in `fixtures/catalog/`
(`qlcplus.json.gz`, `ofl.json.gz`; about 0.4 MB together). Searching and adding work offline and on the
first run, and a converter fix reaches every fixture at once. A fixture that is newer than the catalogue
is converted live from a downloaded library, as before.

```bash
python tools/build_catalog.py --refresh
```

rebuilds it from the latest libraries. `tests/test_catalog.py` fails when a converter changed and the
catalogue wasn't rebuilt. It also patches every mode and beam effect of every fixture, and checks the
safety rules below.

## What the converters do

Driven channels get their role (dimmer, colours, pan/tilt with fine, colour wheel, gobo, prism, frost,
zoom). Every other channel gets a value that keeps the fixture quiet: shutter open, no programs, no
macros. OFL 16-bit channels are scaled to bytes, and an OFL alias follows the fixture it points to.
Moving heads get an estimated speed (measure it), brightness comes from the lumens or else the power.

### Fixtures the show can't play: the DMX mapper

Some fixtures come through with nothing the show can play: effect lights with only program and rotation
channels, colour-macro-only modes, numbered emitters (`blue_1`, `blue_2`…), channels a library leaves
undefined. The Mac app's Set page marks such a model **Plays nothing**; its **Map Channels…** button (also
*Map DMX Channels…* on a fixture's menu) opens the DMX mapper (`amadeus/library/mapper.py`):

- every channel of the mode, with its name and what its value ranges do from QLC+ or the Open Fixture
  Library (pick a range to set it);
- per channel what the show plays on it (dimmer, red, green, blue, white, UV, cyan/magenta/yellow, pan,
  tilt, their fine channels; a colour or dimmer optionally for one cell of a bar), or *hold at value*
  (programs off, a shutter open, a macro parked on a colour), or *keep* what the converter made of it
  (a colour wheel, zoom);
- **Try on the Lights** sends the values as they are to one fixture of the set (the rest dark, a running
  show paused), so you can find out what a channel does;
- what it is when the channels don't say (par, strobe, blinder, moving head); pan and tilt make a moving
  head, cells a bar.

It saves into your copy of the definition (`"mapped": {"modes": [...]}`), so every fixture of that model in
your sets plays by it. Lasers and smoke machines aren't mapped here.

### Lasers: dark until mapped by hand

A converted laser is **inert**: every channel is held at its off value (a range called off, blackout or
no function, else 0), the director isn't told about it, and the visualisers draw it dark. To play a laser,
its channels have to be mapped by hand (`"laser"` in the fixture file, like
`fixtures/laserworld/cs-1000rgb-mk3.json`), so the laser guard knows what it draws.

On some lasers, DMX 0 on the mode channel means *sound active* and nothing on that channel switches it off
(six in the QLC+ library, e.g. the beamZ LS-3DRG). DMX can't keep those dark: they carry a `"warning"`,
shown when you add one and when a show loads it. Power such a laser from a switch you control.

### Smoke machines and hazers

A smoke machine is driven through its output channel (`"fog"`, with `"on_from"`: the first value that
makes smoke, so a pump switch that only starts at 128 still fires) and its fan (`"fog_fan"`). Timers,
auto programs and LED effects on it stay off. One whose output channel isn't recognisable stays inert.

`physical.fog` describes it: `type` (`fog` or `haze`), and optionally `m3_min` (output in m³ per minute,
from the manual), `max_burst_s` (how long it can fog before it reheats) and `rest_s` (how long it needs
to reheat after a full-length burst). Without `m3_min` the output is estimated from the power.

## Smoke in a show

The director picks a haze level per phrase: `none`, `light`, `medium`, `heavy`, or `burst` (a blast on
the downbeat of a big drop). The rules director keeps clear air in the intro, a light haze in grooves and
breakdowns, more for builds and drops, a burst as the main drop lands, and stops at the end. The AI
director chooses freely, guided by the same descriptions. The song's arc keeps bursts for the main drops.

`amadeus/engine/fog.py` plays it. It keeps a model of how hazy the room is: each machine fills it by its
output against the room's volume, and the room clears by itself. It fires the machines on the beat and
ahead of time (fog takes a while to spread), until the room gets there:

- A big fogger in a small room fires short, softer bursts and then rests. On the synthetic test track, a
  1500 W fogger fogs about 2 s in a 60 m³ bar and 8 s in a 600 m³ club.
- A small one in a big hall runs as long as it may (`max_burst_s`), reheats and runs again: a 400 W
  fogger fogs about 50 s of the same track in a 4,000 m³ hall.
- A hazer runs steadily at the output that holds the haze.

In a live set, each track starts in the haze the previous one left, not in a clear room.

What the rig says about the room (in `stage`), and the safety cap (in `safety`):

| Key | Default | |
|---|---|---|
| `stage.room_volume_m3` | (width_m + 4) × (room_depth_m + 3) × ceiling_m | the room's air |
| `stage.fog_clear_s` | 300 | how fast the room clears by itself (ventilation) |
| `safety.max_fog` | 0.7 | never hazier than this (0..1) |

Smoke can set off smoke detectors: check with the venue before you fog.
