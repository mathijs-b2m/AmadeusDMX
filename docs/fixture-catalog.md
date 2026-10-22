# Fixture catalogue

Any fixture works, not only the ones in `fixtures/`. Search covers four libraries at once: ours (checked
on real hardware), the QLC+ fixture library (~1,800, Apache-2.0), the Open Fixture Library (~650, MIT) and the
DMXControl DDF library (~900, of which ~700 in neither of the others, CC BY-SA 4.0: many DJ brands the others lack, such as Eurolite, Stairville
and lightmaXX). A fixture in none of them can be imported from its maker's GDTF file (below).
Adding a fixture copies its definition into `fixtures/<brand>/<model>.json`, where it is an ordinary library
fixture that can be checked and calibrated (`amadeus test`, `colors`, `gobos`, `motion`, `tools/twin.py`).

## The shadow catalogue

Every QLC+, OFL and DDF fixture, already converted to our format, ships in `fixtures/catalog/`
(`qlcplus.json.gz`, `ofl.json.gz`, `ddf.json.gz`; about 0.5 MB together). Searching and adding work offline and on the
first run, and a converter fix reaches every fixture at once. A fixture that is newer than the catalogue
is converted live from a downloaded library, as before.

```bash
python tools/build_catalog.py --refresh
```

rebuilds it from the latest libraries (`--only ddf` rebuilds one). The DDF file is its own data file under
CC BY-SA 4.0 (see `THIRD_PARTY_NOTICES.md`); a fixture copied from it into your library keeps its DDF ids,
authors and licence (`"ddf"`). Only DMXControl 3 files are read; a device the converter can't read yet (HSV
colour, a shorthand matrix) is left out, and a device that is also in QLC+ or the OFL is listed from there.

## Your own GDTF files

GDTF is what makers publish for new fixtures, but GDTF Share's terms don't allow passing its files on, so
none ship here. Use **Import GDTF…** when adding fixtures to a set (Mac and Windows), or
`amadeus library --gdtf FILE`: a `.gdtf` you downloaded from the maker's site or your own GDTF Share account
is converted on your computer into your fixtures (`amadeus/library/gdtf.py`), with the same safety rules as
the other converters. It never replaces a fixture of the same name from another library (it gets `-gdtf`).
Check it once on the real fixture, as with every converted fixture. `tests/test_catalog.py` fails when a converter changed and the
catalogue wasn't rebuilt. It also patches every mode and beam effect of every fixture, and checks the
safety rules below.

## What the converters do

Driven channels get their role (dimmer, colours, pan/tilt with fine, colour wheel, gobo and its rotation,
prism, frost, zoom). Every other channel gets a value that keeps the fixture quiet: shutter open, no programs, no
macros. OFL 16-bit channels are scaled to bytes, and an OFL alias follows the fixture it points to.
Moving heads get an estimated speed (measure it), brightness comes from the lumens or else the power.

### Gobos and zoom

A moving head's gobo wheel is driven on one channel: with a static and a rotating wheel, the rotating one
when a gobo rotation channel turns its gobos (then `gobo_rotate` really turns them), else the first; any
other wheel stays at its open hole, and the rotation channel stops (it used to get the wheel's values). The
open hole isn't counted as a gobo, also when a library calls it "White". A beam effect a mode can't play is
played as the nearest one it can: a rotating or shaking gobo as a still one, a turning prism as a still one,
else an open beam (`fixtures.beam_effect`); the 3D stage shows the same.

**What the gobos look like.** Nearly every QLC+ gobo points to a picture of it (about a thousand, shipped
rendered in `fixtures/catalog/gobos.json.gz`; `tools/build_gobos.py` rebuilds them), the Open Fixture
Library has pictures for some and names for the rest. Each gobo of a converted fixture keeps its picture
(`gobo_images`) and name (`gobo_names`). A gobo with only a name gets a pattern drawn from it ("Stars": dots,
"Spiral": a swirl; "Gobo 5": some pattern), so the 3D stage always has something to show.

**Interpreting them.** Each picture is read as one of the director's gobo styles (`amadeus/library/gobos.py`):
*rings* when the light depends on the distance from the centre only or the holes sit on one circle, *dots*
for many small round holes, tiny flakes or a fine texture, *shapes* for figures with straight edges, *curves*
for swirls, petals and waves. Pictures and words (animals, skylines, "Happy Birthday") are *figures*: on the
wheel, but the show never picks them by itself. A converted fixture without hand-made `gobo_groups` is
grouped by these styles, so a "rings" phrase really picks the rings.

**Zoom.** A zoom channel (QLC+ presets, OFL `Zoom` capabilities, with the lens's range) is played between
its tightest and widest end, by the music (`amadeus/engine/zoom.py`): beams tight at the peaks and soft when calm,
gobos opened up enough to read on the floor and walls, frost fully open; washes (heads without gobos, pars with a
zoom) wide, gathering at the peaks.

### Fixtures the show can't play: the DMX mapper

Some fixtures come through with nothing the show can play: effect lights with only program and rotation
channels, colour-macro-only modes, numbered emitters (`blue_1`, `blue_2`…), channels a library leaves
undefined. The Mac app's Set page marks such a model **Plays nothing**; its **Map Channels…** button (also
*Map DMX Channels…* on a fixture's menu) opens the DMX mapper (`amadeus/library/mapper.py`):

- every channel of the mode, with its name and what its value ranges do from QLC+ or the Open Fixture
  Library (pick a range to set it);
- per channel what the show plays on it (dimmer, red, green, blue, white, UV, cyan/magenta/yellow, the
  colour wheel, pan, tilt, their fine channels; a colour or dimmer optionally for one cell of a bar), or
  *hold at value* (programs off, a shutter open, a macro parked on a colour), or *keep* what the converter
  made of it (zoom);
- **Try on the Lights** sends the values as they are to one fixture of the set (the rest dark, a running
  show paused), so you can find out what a channel does; the channels that carry light (as the file has
  them, or as you map them) stay under the brightness limiter;
- what it is when the channels don't say (par, strobe, blinder, moving head); pan and tilt make a moving
  head, cells a bar.

It saves into your copy of the definition (`"mapped": {"modes": [...]}`), so every fixture of that model in
your sets plays by it. Lasers and smoke machines aren't mapped here.

**Check Channels** goes through the channels one by one on the real fixture: the channel being checked
sweeps slowly from 0 to 255 while the others keep the light on and the head in the middle, and you say what
the fixture does (turns, tilts, gets brighter, red, colours change, gobos change, strobes, starts programs,
nothing). A held channel is then set where the light is on and steady. On a colour wheel you show each
colour and name it, and put its values right. Finishing the check saves the fixture as checked.

### Fixtures without a brand: New Fixture

Cheap moving heads and pars are mostly the same few factory designs sold under many names, so a "brand" on
the box rarely finds anything in a library, but their DMX tables look alike. **New Fixture…** in Add
Fixtures makes one from a common layout (`amadeus/library/generic.py`): LED spot (9, 11 and 14 channels),
LED wash (9 and 14), 7R beam (16), LED par (8 and 3), or nothing known. You give it a brand (or none) and a
name, its type and how many channels it has (the manual says; the display often shows "9CH" or "d-11"), and
pick the layout closest to the manual's table; a layout with more channels is cut off, one with fewer gets
unknown channels added. It lands in your library (`"made": {"template", "checked": false}`) and plays at
once, but the Set page marks it **Not checked yet** until its channels have been checked on the fixture,
because manuals of these fixtures are often wrong (channels swapped, a fine channel missing, the wheel in
another order).

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
