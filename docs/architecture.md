# Architecture

Decisive Lightning has three parts that share one project folder: the **engine** (Python, `decisive/`),
the **web UI** (`web/`) and the **Mac app** (`mac/`). The engine does all the work; both front ends read
its feed and edit the same set files.

```
 track ─► audio ─► director ─► plan per phrase ─┐
          analysis  (AI or rules)               ▼
 position (audio clock, VirtualDJ, ─────────► engine ─► DMX (Art-Net, sACN, USB)
  or a DJ laptop via Decisive Link)            (40 fps)  └► feed ─► web visualiser / Mac app
```

## The engine, package by package

Dependencies point down this list only: `cli` uses everything, nothing uses `cli`, and `engine` never
imports `show`.

| Package | What it does |
|---|---|
| `cli/` | The `decisive` command: one module per group of commands (`show`, `rig`, `hardware`). |
| `pipeline.py` | From a track to a show: analysis, the cached plan, instrument separation. |
| `show/` | Running a show. `player` (one track, audio-clocked), `live` (VirtualDJ), `vdj` (the plugin's packets), `link` (Decisive Link: VirtualDJ on another computer), `tracks` (a show per track, built in the background), `mixer` (several decks at once), `feed` (the WebSocket for the visualisers), `clock`, `monitor`. |
| `engine/` | From time to fixture states. `engine` ties together `timing` (beats, bars, phrases, the flash timeline), `looks` (colours, levels, hits), `motion` (where heads point and a motor simulation of how they get there), `lasers` (shapes and the laser guard), `cinematic` (the cinematic program: a film score played hit by hit, the rig as an orchestra of sections with a score per phrase, lights played like notes (hit, hold, gentle release), the powerful lights making room for the small ones' accents, a melody layer for legato passages), `zones` (keep-out / keep-in / laser zones), `realism` (what a fixture really shows, for the visualiser) and `state` (one element in one frame). |
| `director/` | Decides the look per phrase. `decision` (the `Decision` and plan files), `prompt` (each phrase in words, the questions), `arc` (the song's arc: main drops, lasers), `rules` (the offline director), `llm` (OpenAI Decisions API, Ollama), `cinematic` (the arc of a film-score track), `style` (a house style per genre, and a live set's genre), `vocabulary` (the answer space; its descriptions are the model's style guide), `plan` (directing a whole track). |
| `audio/` | Offline analysis. `model` (what an analysis holds), `features` (band energies, onsets, lead, stutters), `beats` (tempo and beat tracking), `phrases` (bars, phrases, drops), `analysis` (the entry point and its cache), `stems` (instrument separation with Demucs, optional), `genre` (one word per track: you, the Decisions API, a tag, or the audio's groove), `hits` (every hit at its exact time, in voices, for the cinematic program). |
| `rig/` | Your gear and the venue. `store` (sets, rigs, placements, the active pair and the combined view the engine reads; see [rig-format.md](rig-format.md)), `manage` (making and changing sets and rigs), `templates` (rigs to start from), `automount` (hanging a set on a rig), `trusses` (where a fixture clamped to a truss ends up), `loader` (a set on a rig → elements), `geometry` (positions, pan/tilt ⇄ beam direction), `groups` (groups of heads), `grid` (generated test rigs). |
| `library/` | Fixture definitions. `fixtures` (our library, DMX patching), `catalog` (one search over ours, QLC+ and the Open Fixture Library), `qlc`, `ofl` (converters), `label` (recognise a fixture from a photo). |
| `dmx/` | Getting DMX out and finding hardware. `outputs` (Art-Net, sACN, USB interfaces), `artnet`, `rdm`, `discover`, `simnode` (a simulated node). |
| `setup/` | Calibrating real hardware by eye: `bringup` (`decisive test`), `colors`, `gobos`, `motion`, and placing fixtures from a photo (`placement`) or a 3D scan (`pointcloud`). |
| `web/` | The HTTP server for the web UI and its JSON API, split by area (`rig`, `library`, `placement`). |
| `paths.py` | Where the project folder, cache, sets, rigs and examples are (`DECISIVE_ROOT` to point elsewhere; the Mac app sets it for the engines it starts). |

## Timing

Everything time-critical is precomputed. `Engine.render(t)` only reads arrays built when the show is
built (the beat grid, the flash timeline, the head trajectories), so seeking, loops and live playback
behave exactly like a recording. The director chooses once per phrase and never triggers a single hit.

The head trajectories are a motor simulation of every head at once (speed and acceleration measured per
fixture, keep-out zones as physical stops), cached in `.cache/trajectories/` by a hash of the track, the
plan, the rig and the engine's code.

## Safety layers

1. **Flashes:** one rate-limited timeline (`safety.max_flash_hz`); fixture strobe channels are never driven.
2. **Zones:** keep-out zones stop the head motors before a beam reaches them.
3. **Laser guard** (`engine/lasers.py`), last in every frame: raises or shrinks a pattern, or blanks the
   laser, so no modelled beam enters a laser zone; with real lights and no laser zone, lasers stay dark.
   It is a software layer on top of the laser's own masking, scan-fail safety and E-stop, never instead.

## The Mac app

`mac/Sources/DecisiveKit` is the shared library (the feed client, the engine supervisor, the setup API,
set files). `mac/Sources/DecisiveLightning` is the app, grouped by feature: `App`, `Main` (window,
sidebar, toolbar), `Show`, `Rig` (the rig editor, new rigs), `Sets` (the set page), `Engine`, `Settings`, `Wizard`, and
`Render` (the Metal stage). `mac/Sources/DecisiveLink` is the small app for the DJ's laptop.

The app starts the engine (`python -m decisive live …`) and reads its feed; quitting stops the engine,
which blacks out the lights. See `docs/protocols.md` for what goes over the wire.

## Tests

`tests/test_golden.py` hashes all the DMX every example rig sends for a synthetic track
(`tests/synthetic.py`): refactors must leave it unchanged. Unit tests cover geometry, zones, the laser
guard, Decisive Link's signatures, and sets and rigs (migration, saving, auto-mount on every rig template).
See `CONTRIBUTING.md`. The Mac app's rig editor has its own self-test (`-editorSelfTest`, see `mac/README.md`).
