# Decisive Lightning for macOS

A native macOS app (SwiftUI + Metal) on top of the same Python engine the web UI uses. It sits side by side
with the web UI: nothing in `decisive/` or `web/` depends on it, and both share the sets, fixtures and cache.

```
mac/
  Package.swift
  Sources/DecisiveKit/         shared library: protocol, live feed, engine supervisor, setup API, sets, palettes
  Sources/DecisiveLightning/   the app, by feature
    App/                       the app, its state, the show mode, the keychain
    Main/                      the window: sidebar and toolbar
    Show/                      the show page: stage, now playing, decks, timeline, Perform board, director
    Rig/                       patch table and the rig editor (Editor/)
    Sets/ Engine/ Settings/    the other pages
    Wizard/                    "Set Up a Rig" assistant, one file per step
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

## Rig editor (Rig › Layout)

- **Trusses:** add box truss (quatro, 1–10 m) or towers, drag them, and set their height, length and
  rotation.
- **Fixtures on trusses:** fixtures snap onto the nearest truss while you drag them (25 cm steps; hold ⌥ to
  place freely). They move and turn with their truss. Drag one off a truss and it goes to the floor.
- **Placement:** the inspector sets mount (under / on top / floor), rotation and, for fixtures without
  motors, aim.
- **Add Fixtures:** searches our library, QLC+ and the Open Fixture Library. New fixtures are spread along
  the selected truss with free DMX addresses.
- **Zones (Zone button):** translucent rectangles or boxes that limit beams. They are stored in the set as
  `zones` and enforced by the engine (`decisive/engine/zones.py`):
  - **keep out** (blue): a physical stop for the head motors. A head never turns its beam into the zone
    (plus a margin): it slides along the edge or waits, and is never dimmed for it;
  - **keep in** (green): moving-head beams land only inside it;
  - **laser safety** (red): the laser guard raises or shrinks a pattern, or blanks the laser, so no
    modelled beam (plus margin) enters it.
  When DMX goes to real lights, a set with lasers needs a laser zone, or its lasers stay dark. This is a
  software guard on top of the laser's masking plate, scan safety and E-stop, never instead of them.
  For lasers, set their **Aim** (measured on the real laser) in the inspector.
- **Keys:** R rotates 15° (⇧R 90°), arrow keys nudge, ⌫ deletes, ⌘Z undoes, ⌘S saves into the set file.
- **Set file:** the editor writes plain positions the engine already understands (`x`, `y_m`, `z_m`,
  `rot_deg`, `aim`), plus `trusses` and each fixture's `truss` / `truss_pos_m`. Both visualisers draw
  the trusses.

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
open "build/Decisive Lightning.app" --args -section rig            # open on a page: show, rig, sets, engine
open "build/Decisive Lightning.app" --args -wizard YES             # open the wizard
open "build/Decisive Lightning.app" --args -play TRACK.mp3 -playFrom 120 -muted YES
open "build/Decisive Lightning.app" --args -section rig -rigMode layout -lastSet showcase
open "build/Decisive Lightning.app" --args -editorSelfTest COPY_OF_A_SET   # report in $TMPDIR/editor-selftest.txt
```
