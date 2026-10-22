# Architecture

Amadeus DMX has four parts that share one project folder: the **engine** (Python, `amadeus/`),
the **web UI** (`web/`), the **Mac app** (`mac/`) and the **Windows app** (`windows/`). The engine does all the
work; the front ends read its feed and edit the same set files.

```
 track ─► audio ─► director ─► plan per phrase ─┐
          analysis  (AI or rules)               ▼
 position (audio clock, VirtualDJ, ─────────► engine ─► DMX (Art-Net, sACN, USB)
  or a DJ laptop via Amadeus Link)            (40 fps)  └► feed ─► web visualiser / Mac app
```

## The engine, package by package

Dependencies point down this list only: `cli` uses everything, nothing uses `cli`, and `engine` never
imports `show`.

| Package | What it does |
|---|---|
| `cli/` | The `amadeus` command: one module per group of commands (`show`, `rig`, `hardware`). |
| `pipeline.py` | From a track to a show: analysis, the cached plan, instrument separation. |
| `show/` | Running a show. `player` (one track, audio-clocked), `live` (VirtualDJ), `vdj` (the plugin's packets), `link` (Amadeus Link: VirtualDJ on another computer), `sources` (other DJ software: one integration per DJ software behind a common `Source`, picked with `--source`; `probe` watches, measures, records and passes one on), `tracks` (a show per track, built in the background), `mixer` (several decks at once), `feed` (the WebSocket for the visualisers), `clock`, `monitor`, `arc` (the show arc: a whole night of one to ten hours, its stages detected from the music's heat in any order, with nudges by event type, and the operator's knobs: groups, specials, responsiveness, smoke, colour variety, intensity, flashes, applied to the mixed frame). |
| `engine/` | From time to fixture states. `engine` ties together `timing` (beats, bars, phrases, the flash timeline), `looks` (colours, levels, hits), `motion` (where heads point and a motor simulation of how they get there), `rings` (heads on a round truss playing it as a circle: crowns, cones, twisters, waves round it), `lasers` (shapes and the laser guard), `cinematic` (the cinematic program: a film score played hit by hit, the rig as an orchestra of sections with a score per phrase, lights played like notes (hit, hold, gentle release), the powerful lights making room for the small ones' accents, a melody layer for legato passages), `zones` (keep-out / keep-in / laser zones), `fog` (when smoke machines fire and how much, for the machine and the room), `rolls` (a snare roll into a drop, or a fill into a phrase, played as flashes on its hits, and the blackout for the pause before a drop), `realism` (what a fixture really shows, for the visualiser) and `state` (one element in one frame). |
| `director/` | Decides the look per phrase. `decision` (the `Decision` and plan files), `prompt` (each phrase in words, the questions), `arc` (the song's arc: main drops or a song's last chorus, lasers), `rules` (the offline director), `llm` (OpenAI Decisions API, Ollama), `cinematic` (the arc of a film-score track), `style` (a house style per genre, and a live set's genre), `themes` (a theme from the title, e.g. stars, with a special look), `vocabulary` (the answer space; its descriptions are the model's style guide), `plan` (directing a whole track). |
| `audio/` | Offline analysis. `model` (what an analysis holds), `features` (band energies, onsets, lead, stutters), `beats` (tempo and beat tracking), `phrases` (bars, phrases, drops), `form` (a song or a club track: from the voice, the instruments and the harmony; a song's parts, verse to chorus, and which of its jumps are real drops), `rolls` (the snare's hits at 5 ms, where they form a roll into a drop or a fill into a phrase (a filled beat grid, one drum's sound, denser than the groove), its steps, and the pause before a drop), `analysis` (the entry point and its cache), `stems` (instrument separation with Demucs, optional), `drums` (the kit from the separated drums: kick and snare, the snare's ring), `dembow` (reggaeton's boom-tac), `disco` (disco by its sound, from the EffNet-Discogs style model), `instruments` (which instrument plays, MTG-Jamendo), `genre` (one word per track: you, the Decisions API, a tag, or the audio: its form, then its groove and tempo), `hits` (every hit at its exact time, in voices, for the cinematic program). |
| `rig/` | Your gear and the venue. `store` (sets, rigs, placements, the active pair and the combined view the engine reads; see [rig-format.md](rig-format.md)), `manage` (making and changing sets and rigs), `templates` (rigs to start from), `automount` (hanging a set on a rig), `hangsheet` (the set on the rig on paper for the crew, and the check after hanging), `trusses` (where a fixture clamped to a truss ends up), `loader` (a set on a rig → elements), `geometry` (positions, pan/tilt ⇄ beam direction), `groups` (groups of heads), `grid` (generated test rigs). |
| `library/` | Fixture definitions. `fixtures` (our library, DMX patching), `catalog` (one search over ours, QLC+, the Open Fixture Library and the DMXControl DDF library), `shadow` (every QLC+ / OFL / DDF fixture already converted, shipped in `fixtures/catalog/`; see [fixture-catalog.md](fixture-catalog.md)), `qlc`, `ofl`, `ddf` (converters), `gdtf` (a user's own .gdtf, never shipped), `label` (recognise a fixture from a photo). |
| `dmx/` | Getting DMX out and finding hardware. `outputs` (Art-Net, sACN, USB interfaces), `artnet`, `rdm`, `discover`, `simnode` (a simulated node). |
| `setup/` | Calibrating real hardware by eye: `bringup` (`amadeus test`), `colors`, `gobos`, `motion`, and placing fixtures from a photo (`placement`) or a 3D scan (`pointcloud`). |
| `web/` | The HTTP server for the web UI and its JSON API, split by area (`rig`, `library`, `placement`). |
| `paths.py` | Where the project folder, cache, sets, rigs and examples are (`AMADEUS_ROOT` to point elsewhere; the Mac app sets it for the engines it starts). |

## Timing

Everything time-critical is precomputed. `Engine.render(t)` only reads arrays built when the show is
built (the beat grid, the flash timeline, the head trajectories), so seeking, loops and live playback
behave exactly like a recording. The director chooses once per phrase and never triggers a single hit.

The head trajectories are a motor simulation of every head at once (speed and acceleration measured per
fixture, keep-out zones as physical stops), cached in `.cache/trajectories/` by a hash of the track, the
plan, the rig and the engine's code.

## Safety layers

1. **Flashes:** one rate-limited timeline (`safety.max_flash_hz`); a snare roll's flashes keep to the same limit
   unless `safety.allow_fast_strobe` (then every hit, at most 10 Hz per light);
   `safety.strobe_free` leaves them all out. Fixture strobe channels are never driven.
2. **Zones:** keep-out zones stop the head motors before a beam reaches them.
3. **Laser guard** (`engine/lasers.py`), last in every frame: raises or shrinks a pattern, or blanks the
   laser, so no modelled beam enters a laser zone; with real lights and no laser zone, lasers stay dark.
   It is a software layer on top of the laser's own masking, scan-fail safety and E-stop, never instead.
4. **Brightness limiter** (`dmx/limiter.py`, applied in `library/fixtures.patch`, the last step before DMX):
   a ceiling on every light for testing and setting up without eye strain (`config/limiter.json`, shared by
   every process that sends DMX: the show, the light test, Identify, the setup tools). It limits, it doesn't
   scale: at 70 % a light at 50 % stays at 50 %, one at 100 % plays at 70 %, colours keep their hue; smoke
   isn't limited. The Mac app shows it in its toolbar and in a striped banner on every page, and starts at
   100 % each time it opens; the web setup page has it in its header. For a show it belongs at 100 %.

## The Mac app

`mac/Sources/AmadeusKit` is the shared library (the feed client, the engine supervisor, the setup API,
set files). `mac/Sources/AmadeusDMX` is the app, grouped by feature: `App`, `Main` (window,
sidebar, toolbar), `Show`, `Rig` (the rig editor, new rigs), `Sets` (the set page), `Engine`, `Settings`, `Wizard`, and
`Render` (the Metal stage). `mac/Sources/AmadeusLink` is the small app for the DJ's laptop.

## The Windows app

`windows/` ports both Mac apps to C#, WinUI 3 and Direct3D 11, file by file with the same names; the Swift code
is the spec ([windows/PORTING.md](../windows/PORTING.md)). It starts the same engine, bundled with its own
Python, and reads the same feed. Builds and installers: [windows/README.md](../windows/README.md).

The app starts the engine (`python -m amadeus live …`) and reads its feed; quitting stops the engine,
which blacks out the lights. See `docs/protocols.md` for what goes over the wire.

## Tests

`tests/test_golden.py` hashes all the DMX every example rig sends for a synthetic track
(`tests/synthetic.py`): refactors must leave it unchanged. Unit tests cover geometry, zones, the laser
guard, Amadeus Link's signatures, and sets and rigs (migration, saving, auto-mount on every rig template).
See `CONTRIBUTING.md`.
`tools/twin.py` checks the head motion the visualiser shows against a twin of one fixture driven only by
its DMX, and calibrates it against the real fixture ([fixture-twin.md](fixture-twin.md)).
The Mac app's rig editor has its own self-test (`-editorSelfTest`, see `mac/README.md`).
