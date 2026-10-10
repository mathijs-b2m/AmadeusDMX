# Decisive Lightning for macOS

A native macOS app (SwiftUI + Metal) on top of the same Python engine the web UI uses. It sits side by side
with the web UI: nothing in `decisive/` or `web/` depends on it, and both share the sets, rigs, fixtures and
cache.

The pages: **Show** (the stage and the music), **Rig** (the venue and where your fixtures hang on it),
**Set** (your fixtures and their patch) and **Engine** (the log). The toolbar shows the set on the rig the show
runs with ("showcase on club"); most people have one set and a rig per venue. See
[docs/rig-format.md](../docs/rig-format.md).

```
mac/
  Package.swift
  Sources/DecisiveKit/         shared library: protocol, live feed, engine supervisor, setup API, sets, palettes
  Sources/DecisiveLightning/   the app, by feature
    App/                       the app, its state, the show mode, the keychain
    Main/                      the window: sidebar and toolbar
    Show/                      the show page: stage, now playing, decks, timeline, Perform board, director
    Rig/                       the rig page: the rig editor (Editor/), New Rig and "mount the set?" sheets
    Sets/                      the set page: your fixtures, their patch, adding fixtures
    Engine/ Settings/          the other pages
    Wizard/                    the set-up assistant (set → rig → mount), one file per step
    Render/                    Metal stage (beams, lasers, LED wall, bloom), the LED wall's scenes
    Shared/                    small helpers used across views
  Sources/DecisiveLink/        the DJ laptop's companion app (Decisive Link)
  build-app.sh                 builds "Decisive Lightning.app" (and a .dmg)
  tools/make-icon.swift        draws the app icon
```

## Build and install

```bash
./build-app.sh              # build/Decisive Lightning.app
./build-app.sh --install    # … and copy it to ~/Applications
./build-app.sh --dmg        # … and build/DecisiveLightning.dmg
```

Needs Xcode 26 (Swift 6.2+) and macOS 26. You can also open `Package.swift` in Xcode and run the
`DecisiveLightning` scheme.

## How it works

- **Engine:** the app runs `python -m decisive live …` (or `play`) from the engine folder's `.venv`. It reads
  the same WebSocket feed as the web visualiser (`ws://127.0.0.1:8765`). Quitting the app stops the engine
  cleanly, so the lights black out.
- **Already running:** if `decisive live` is already running from a terminal, the app attaches to it
  ("Watching") instead of starting a second engine.
- **Setup service:** for the wizard, the app runs `decisive setup --port 8181` in the background and uses its
  `/api/*`, the same API the web setup page uses.
- **OpenAI key:** stored in the Keychain and passed to the engine as `OPENAI_API_KEY`. A `.env` in the engine
  folder works too.
- **Engine folder:** baked in at build time (`DLEngineRoot` in Info.plist). If it moves, choose it in
  Settings › General.

## Set up: a set, a rig, the set on the rig

The set-up assistant (first launch, or *New Set…*) follows the three steps: your **fixtures** and where the DMX
goes (the set), the **rig** (a new one from a template, or one you have), and how the set goes on it
(**auto-mount**, or by hand in the rig editor). Later:

- **Set page:** every fixture you own, grouped by model, with its patch and where it hangs on the current rig.
  *Add Fixtures…* searches our library, QLC+ and the Open Fixture Library and gives free addresses; then the app
  offers to mount the new ones. Right-click to identify fixtures on the real rig, mount them, or remove them.
  The set's name is a menu for the rare second set (new, duplicate, rename, delete).
- **New Rig…** (the toolbar menu, or the rig's name in the editor): templates with a sketch of each (an empty
  room, two stands, a truss over the booth, a club, a concert stage), sized with sliders. Choosing a rig the set
  doesn't hang on yet asks: *Auto-Mount* or *I'll place them myself*.

## Rig editor (the Rig page)

- **The set on this rig:** with nothing selected, the inspector shows how much of the set is mounted and lists
  it by model. Fixtures without a place wait on the floor in front of the stage. **Drag a group** (or one
  fixture) from the list onto a truss: a group hangs in a row, 60 cm apart (more for long bars), on a free
  stretch of the truss. Click a group to select all of it. **Auto-Mount** (toolbar or inspector) hangs what's
  waiting, re-mounts the selection, or re-mounts everything: one undoable step, saved with ⌘S.
- **Selecting several:** ⇧-click adds fixtures, ⌘A selects every fixture. Drag one of them and the rest come
  along: onto a truss they hang in a row, on the floor they keep their spacing. The inspector then sets their
  side of the truss for all of them, auto-mounts or unmounts them.
- **Trusses:** add box truss (quatro, 1–10 m) or towers, drag them, and set their height, length and
  rotation. **Venue:** stage width, ceiling, room depth and the LED wall, in the inspector.
- **Fixtures on trusses:** fixtures snap onto the nearest truss while you drag them (25 cm steps; hold ⌥ to
  place freely), onto its front or back face when you drag across it. They move and turn with their truss.
  Drag one off a truss and it goes to the floor.
- **Placement:** the inspector sets the truss side (under / front / top / back), mount, rotation and, for
  fixtures without motors, aim.
- **Zones (Zone button):** translucent rectangles or boxes that limit beams. They belong to the rig and are
  enforced by the engine (`decisive/engine/zones.py`):
  - **keep out** (blue): a physical stop for the head motors. A head never turns its beam into the zone
    (plus a margin): it slides along the edge or waits, and is never dimmed for it;
  - **keep in** (green): moving-head beams land only inside it;
  - **laser safety** (red): the laser guard raises or shrinks a pattern, or blanks the laser, so no
    modelled beam (plus margin) enters it.
  When DMX goes to real lights, a set with lasers needs a laser zone, or its lasers stay dark. This is a
  software guard on top of the laser's masking plate, scan safety and E-stop, never instead of them.
  For lasers, set their **Aim** (measured on the real laser) in the inspector.
- **Keys:** R rotates 15° (⇧R 90°), arrow keys nudge, ⌫ unmounts fixtures (back to waiting; they stay in the
  set) or deletes a truss or zone, ⌘Z undoes, ⌘S saves.
- **Saving** goes through the engine's setup API: the rig file gets the trusses, stage, zones and where the
  set hangs; the set file gets any fixtures you added. The editor rereads the files when they change
  elsewhere, unless it has unsaved changes.

## Decisive Link (VirtualDJ on another computer)

When the DJ and the lighting operator use different computers:

1. **The DJ's laptop** runs VirtualDJ with the DecisiveLink plugin as usual, plus **Decisive Link.app**
   (a small window and a menu bar icon, from `build/DecisiveLink.dmg`). Switched on, it advertises itself with Bonjour and shows a
   4-digit code.
2. **The lighting computer**: Start ▸ **Start with a DJ Laptop…** lists the nearby DJs; pick one and type
   the code. From the command line: `decisive live --remote auto --code 1234` (or `--remote HOST:7123`).

What travels over the network (protocol in [docs/protocols.md](../docs/protocols.md)):
- **Deck state:** 25 times a second, stamped with the DJ laptop's clock and signed with a key derived
  from the code. The engine estimates the clock offset from the fastest packets, NTP-style, so network
  jitter cancels out. Measured on one Mac with 0–40 ms of simulated delay: position spread 4 ms.
- **Tracks:** each track VirtualDJ loads is fetched once, checksummed and cached, and analysed as
  usual. Only tracks VirtualDJ has loaded are served, and only to a paired computer.

Use a cable or a dedicated 5 GHz network at a gig. The deck card shows the link's jitter and lost
packets, and macOS asks once to allow incoming connections on both computers.

## Developer launch arguments

```bash
open "build/Decisive Lightning.app" --args -section rig            # open on a page: show, rig, set, engine
open "build/Decisive Lightning.app" --args -wizard YES             # open the wizard
open "build/Decisive Lightning.app" --args -play TRACK.mp3 -playFrom 120 -muted YES
open "build/Decisive Lightning.app" --args -section rig -lastSet showcase -lastRig club   # a set on a rig
open "build/Decisive Lightning.app" --args -engineRoot /path/to/a/copy    # another engine folder (a sandbox)
open "build/Decisive Lightning.app" --args -editorSelfTest NAME   # the set NAME on the rig NAME (copies: it saves!)
                                                                   # report in $TMPDIR/editor-selftest.txt
```
