# Amadeus DMX for macOS

A native macOS app (SwiftUI + Metal) on top of the same Python engine the web UI uses. It sits side by side
with the web UI: nothing in `amadeus/` or `web/` depends on it, and both share the sets, rigs, fixtures and
cache.

The pages: **Show** (the stage and the music), **Rig** (the venue and where your fixtures hang on it),
**Set** (your fixtures and their patch) and **Engine** (the log). The toolbar shows the set on the rig the show
runs with ("showcase on club"); most people have one set and a rig per venue. See
[docs/rig-format.md](../docs/rig-format.md).

```
mac/
  Package.swift
  Sources/AmadeusKit/          shared library: protocol, live feed, engine supervisor, setup API, sets, palettes
  Sources/AmadeusDMX/          the app, by feature
    App/                       the app, its state, the show mode, the keychain
    Main/                      the window: sidebar and toolbar
    Show/                      the show page: stage, now playing, decks, timeline, Perform board, director
    Rig/                       the rig page: the rig editor (Editor/), New Rig and "mount the set?" sheets
    Sets/                      the set page: your fixtures, their patch, adding fixtures
    Engine/ Settings/          the other pages
    Wizard/                    the set-up assistant (set → rig → mount), one file per step
    Render/                    Metal stage (beams, lasers, LED wall, bloom), the LED wall's scenes
    Shared/                    small helpers used across views
  Sources/AmadeusLink/         the DJ laptop's companion app (Amadeus Link)
  build-app.sh                 builds "Amadeus DMX.app" (and a .dmg)
  Resources/AppIcon.icns       the app icon (the Amadeus DMX logo; docs/logo/ has the artwork)
```

## Build and install

```bash
./build-app.sh              # build/Amadeus DMX.app, running the engine from this checkout (its .venv)
./build-app.sh --install    # … and copy it to ~/Applications, as "Amadeus DMX (dev)"
./build-app.sh --dmg        # … and build/AmadeusDMX.dmg and build/AmadeusLink.dmg
./build-app.sh --release --dmg   # the app people download: the engine and its own Python inside
```

Needs Xcode 26 (Swift 6.2+) and macOS 26; `--release` also needs uv (`brew install uv`). You can also open
`Package.swift` in Xcode and run the `AmadeusDMX` scheme.

## Releases

A release app needs nothing installed: `bundle-engine.sh` puts a standalone Python (python-build-standalone,
via uv) with `requirements-app.txt` in `Contents/Resources/runtime`, and the engine (package, web UI, fixtures,
examples, Mixxx mapping, VirtualDJ plugin) in `Contents/Resources/engine`, compiled and signed. About 220 MB
in the app, about 110 MB as a disk image. Not inside, as optional packs (Settings › General, or
`amadeus packs install NAME`): instrument analysis (torch, Demucs and the instrument models, ~1 GB) and streamed
tracks (yt-dlp). The app's Python is never written to: packs go into an environment of their own on top of it
(`python/` in your data folder), which the app then runs the engine with.

Your data stays out of the app, in `~/Library/Application Support/Amadeus DMX` (sets, rigs, settings, `.env`,
fixtures you added or calibrated, the cache), so replacing the app never touches it. The engine finds both
through `AMADEUS_ROOT` and `AMADEUS_DATA` (`amadeus/paths.py`).

**On GitHub:** push a tag (`git tag v0.2.0 && git push origin v0.2.0`). `.github/workflows/release.yml` runs
the checks, builds both apps and makes a **draft** release with the disk images and their SHA-256 sums; you
publish it on GitHub. Actions › Release › *Run workflow* makes the same build as a workflow artifact only.

The apps are signed with a certificate of our own (`release-keys.sh` makes it), not an Apple Developer ID, so
macOS stops the first launch of a downloaded copy: open it once, then System Settings › Privacy & Security ›
*Open Anyway*. Because every release carries the same signature, macOS keeps the permissions you gave it
(Accessibility for djay, the local network) across updates.

## Updates

Both apps update themselves with [Sparkle](https://sparkle-project.org) (`Sources/AmadeusKit/Updates.swift`):

- **Opt-in.** On the second launch Sparkle asks whether to check automatically. Amadeus DMX: Settings › General ›
  Updates changes it, adds "download and install by themselves", and *Check Now* (also in the app menu).
  Amadeus Link: *Check for updates* and *Check Now* at the bottom of its menu.
- **Never during a show.** No background check while the lights run (Amadeus Link: while a lighting computer is
  connected); an update you install then waits until that's over. One downloaded by itself is installed when
  you quit.
- **Only ours.** The app installs an update only if it is signed with the release key (its public half is
  `Resources/sparkle-public-key.txt`) and carries the same code signature as the app itself.
- **The feeds** are `appcast.xml` (Amadeus DMX) and `appcast-link.xml` (Amadeus Link) on the newest published
  GitHub release (`releases/latest/download/…`); release.yml makes them. Publishing the draft release is what makes an
  update reach people. Prereleases (`v0.3.0-beta.1`) don't reach them.
- Your data (sets, rigs, settings, packs) is outside the app, so an update never touches it.

Development builds have no feed and don't update.

### The release keys

`./release-keys.sh` makes them once, in `~/.amadeus-release`: the signing certificate (`signing.p12`, its
password) and the update key (`sparkle-private-key.txt`). **They must stay the same for every release**: keep a
copy in a password manager. Lost, the apps out there can't update to anything signed with new ones (people
download the next version by hand, once). For GitHub, put them in Settings › Secrets › Actions:

| Secret | Value |
|---|---|
| `SIGNING_P12_BASE64` | `base64 < ~/.amadeus-release/signing.p12` |
| `SIGNING_P12_PASSWORD` | `~/.amadeus-release/signing-password.txt` |
| `SPARKLE_PRIVATE_KEY` | `~/.amadeus-release/sparkle-private-key.txt` |

Without them a release is signed ad hoc and has no feed. A local `./build-app.sh --release` signs with the
certificate in `~/.amadeus-release` when it's there; `FEED_URL=…` gives it a feed (for testing updates).

## How it works

- **Engine:** the app runs `python -m amadeus live …` (or `play`) with the engine's Python (the app's own, or a checkout's `.venv`). It reads
  the same WebSocket feed as the web visualiser (`ws://127.0.0.1:8765`). Quitting the app stops the engine
  cleanly, so the lights black out.
- **Already running:** if `amadeus live` is already running from a terminal, the app attaches to it
  ("Watching") instead of starting a second engine.
- **Setup service:** for the wizard, the app runs `amadeus setup --port 8181` in the background and uses its
  `/api/*`, the same API the web setup page uses.
- **OpenAI key:** stored in the Keychain and passed to the engine as `OPENAI_API_KEY`. A `.env` in the engine
  folder works too.
- **Engine folder:** a release has the engine inside (see [Releases](#releases)). A development build has the
  checkout baked in (`AmadeusEngineRoot` in Info.plist); if it moves, choose it in Settings › General, which
  also switches a release to a checkout and back.

## Set up: a set, a rig, the set on the rig

The set-up assistant (first launch, or *New Set…*) follows the three steps: your **fixtures** and where the DMX
goes (the set), the **rig** (a new one from a template, or one you have), and how the set goes on it
(**auto-mount**, or by hand in the rig editor). After that, three pages, each about one thing:

- **Sets:** a list of your sets of fixtures. Pick one to see every fixture, grouped by model, with its DMX
  patch and mode. *Add Fixtures…* searches our library, QLC+ and the Open Fixture Library and gives free
  addresses; right-click to identify fixtures on the real lights or remove them; the set's name is a menu to
  duplicate, rename or delete it. **Select a fixture** to edit it on the right: its name (renaming keeps where it
  hangs on your rigs), DMX mode, universe and start address (checked against the 512 channels and the other
  fixtures, with *Next Free*), and for moving heads invert pan / tilt. Select several to give them one mode or
  universe, or *Patch in a Row* from an address. Every change is saved at once. Nothing about rigs here.
- **Rigs:** a list of your rigs (venues). Pick one to edit its structure in 3D. **On this rig** chooses what you
  edit: *the rig alone*, or one of the sets placed on it (where its fixtures hang). **Place a Set** puts another
  set on this rig, auto-mounted or to place by hand: that is the only place auto-mount is offered. *Take Off…*
  removes a set from the rig. **New Rig…** (the big button under the list, the + by "Rigs", or File › New Rig… ⌥⌘N) offers templates with a sketch of each (an empty room,
  two stands, a truss over the booth, a club, a concert stage), sized with sliders.
- **Show:** the toolbar picker lists the **combinations**: the sets placed on rigs. A show runs one of those;
  there is no picking a set and a rig that were never put together.
- **Decision model:** next to it, **Rules** or **AI** says who decides the show: the rules (instant, offline) or an
  AI model (OpenAI, or a local one through Ollama). It belongs to the set, and a running live show follows a
  change: the rules' quick plan plays until the AI's plan is ready.

## Rig editor (the Rigs page)

- **The set on this rig:** with nothing selected, the inspector shows how much of the set is mounted and lists
  it by model. Fixtures without a place wait on the floor in front of the stage. **Drag a group** (or one
  fixture) from the list onto a truss: a group hangs in a row, 60 cm apart (more for long bars), on a free
  stretch of the truss. Click a group to select all of it. **Auto-Mount** (toolbar or inspector) hangs what's
  waiting, re-mounts the selection, or re-mounts everything: one undoable step, saved with ⌘S.
- **Stands:** a fixture standing in the air (not on a truss) has its own tripod stand, part of the fixture:
  click the stand or the fixture to select it, and the stand moves with it. Only real trusses and towers (from
  the Truss menu or the Draw Truss / Place Tower tools) are selected and moved as trusses.
- **Picking:** what the pointer is over lights up a little, so you see what a click will pick. A click picks a
  fixture only right on it; on a truss between its fixtures it picks the truss. The tolerance is about 1.5° of
  the view (at least 30 cm), so a truss is as easy to pick from far away as up close.
- **Selecting several:** ⇧-click adds fixtures, ⌘A selects every fixture. Drag one of them and the rest come
  along: onto a truss they hang in a row, on the floor they keep their spacing. The inspector then sets their
  side of the truss for all of them, auto-mounts or unmounts them.
- **Building trusses:** the toolbar's tools build the rig like a construction game. **Draw Truss** (T): drag
  on the floor; the truss stretches from where you pressed, in ½ m lengths and 15° turns (⌥: free), at the
  height set next to the tool. **Place Tower**: click on the floor (its height next to the tool). A selected
  truss shows **handles** at its ends: drag one to stretch or turn it while the other end stays put; a tower's
  handle on top makes it taller or shorter. ⌥↑ / ⌥↓ raise or lower the selected truss by 25 cm, Esc goes back
  to selecting. The Truss menu still adds ready-made lengths; the inspector has exact values. **Venue:**
  stage width, ceiling, room depth and the LED wall, in the inspector.
- **Fixtures on trusses:** fixtures snap onto the nearest truss while you drag them (25 cm steps; hold ⌥ to
  place freely), onto its front or back face when you drag across it. They move and turn with their truss.
  Drag one off a truss and it goes to the floor.
- **Placement:** the inspector sets the truss side (under / front / top / back), mount, rotation and, for
  fixtures without motors, aim.
- **Zones (Zone button):** translucent rectangles or boxes that limit beams. They belong to the rig and are
  enforced by the engine (`amadeus/engine/zones.py`):
  - **keep out** (blue): a physical stop for the head motors. A head never turns its beam into the zone
    (plus a margin): it slides along the edge or waits, and is never dimmed for it;
  - **keep in** (green): moving-head beams land only inside it;
  - **laser safety** (red): the laser guard raises or shrinks a pattern, or blanks the laser, so no
    modelled beam (plus margin) enters it.
  When DMX goes to real lights, a set with lasers needs a laser zone, or its lasers stay dark. This is a
  software guard on top of the laser's masking plate, scan safety and E-stop, never instead of them.
  For lasers, set their **Aim** (measured on the real laser) in the inspector.
- **Keys:** R rotates 15° (⇧R 90°), arrow keys nudge (on a truss: ← → slide along it, ↑ ↓ go round it: under → front → top → back, or round a tower's faces), ⌫ unmounts fixtures (back to waiting; they stay in the
  set) or deletes a truss or zone, ⌘Z undoes, ⌘S saves.
- **Saving** goes through the engine's setup API: the rig file gets the trusses, stage, zones and where the
  set hangs; the set file gets any fixtures you added. The editor rereads the files when they change
  elsewhere, unless it has unsaved changes.

## DMX devices and output (Show → DMX Devices & Output…, ⇧⌘D)

Your DMX controllers are kept apart from the sets: an Art-Net node, an sACN node or multicast, a USB DMX
interface, each set up once (name, address, its number of outputs and whether its first output is universe 0
or 1). **Search** finds Art-Net nodes on the network and USB interfaces on this Mac; add them with one click,
or by hand. For the selected set the window lists its universes (with how many fixtures each) and where each
goes: a device and its output, showing the universe that goes out on the wire. Save writes your devices
(`config/devices.json`) and the set's mapping; a running show uses it from its next start. The sidebar's
output line and the Set page's *DMX output* open the window too.

## Performance: the lights first

The 3D stage is by far the heaviest part of the app. Measured during a live show on a 60-head rig, the light
engine took about 10% of one core; the 3D stage about 35% of a core plus its GPU work and the window server's
compositing of it. That is several times what the lights themselves cost.

- **Show modes** (Show menu): *Perform + Visualise*, *Perform Only* (the lights, no 3D stage: the computer's
  power goes to the show) and *Visualise Only* (no DMX).
- **Power meter:** while a show runs, the sidebar's engine panel shows the light engine and the 3D stage side by
  side: CPU use and the stage's GPU load (measured per process every 2 s, no admin rights needed).
- **Warning:** with the lights on and the 3D stage open, the panel warns when the stage takes clearly more
  than the lights (over twice), or the Mac is on battery, in Low Power Mode or getting hot, and offers
  *Perform Only* in one click. On a laptop or a smaller Mac, use Perform Only for a gig.
- **Frame rate and resolution:** a running show changes 40 times a second, so the stage draws 40 frames a
  second, and 60 only while the camera moves. The scene renders at a share of the window's pixels that adapts
  to the GPU: when a frame takes more than 9 ms the resolution goes down (to half at most; beams and bloom are
  soft, so it barely shows), and back up when there is room. A 60-head rig on a Retina screen is where this
  matters.
- **Idle:** with nothing changing (no show frames, no camera move, no input), the 3D stage draws 4 frames a
  second instead of 60, so an open window with no show costs next to nothing.

## Other DJ software (Mixxx, djay Pro)

Start ▸ **Start Live Show (…)** lists every DJ software the engine can follow (from the engine's own list);
the Start button and ⌘R then use the last one chosen. What each needs:
[docs/dj-software.md](../docs/dj-software.md).

- **Mixxx:** start the show first, then Mixxx; in Mixxx, enable the "Amadeus DMX" controller once.
- **djay Pro:** macOS asks once to allow **Amadeus DMX** to "control this computer using
  accessibility features". That is macOS's wording for any app with this permission. Amadeus DMX
  uses it only to *read* djay's deck labels (track, elapsed time, play, tempo, volumes), only djay's, and
  only while a show follows djay: it never clicks or types anywhere. Allow it in System Settings → Privacy &
  Security → Accessibility, then start the show again; switching it off only stops following djay. The
  permission belongs to the app and covers the engine it starts. A self-built app may need it switched off
  and on again after a rebuild (ad-hoc signature). Details: [docs/dj-software.md](../docs/dj-software.md#the-accessibility-permission).

## Amadeus Link (the DJ's laptop)

When the DJ and the lighting operator use different computers:

1. **The DJ's laptop** runs the DJ software plus **Amadeus Link.app** (a small window and a menu bar icon, from
   `build/AmadeusLink.dmg`). In its menu, pick the DJ software:
   - **VirtualDJ:** Link carries the AmadeusLink plugin: *Install* puts it in VirtualDJ's plugin folder (and
     *Update* replaces an older one); restart VirtualDJ and switch it on as master effect.
   - **djay Pro:** Link reads djay's window itself, like the engine does (`Sources/AmadeusLink/DJ/Djay.swift`):
     it needs the **Accessibility** permission for Amadeus Link (its menu opens the setting). A deck on SYNC
     is marked so, and the lighting computer reads the exact beat from **Ableton Link** on the network itself
     (it needs aalink there; both computers on the same network).
   - **Mixxx:** Link creates the MIDI device "Amadeus DMX" and puts the "Amadeus DMX" mapping in Mixxx's
     controllers folder (`Sources/AmadeusLink/DJ/Mixxx.swift`). In Mixxx: Preferences › Controllers ›
     Amadeus DMX, mapping "Amadeus DMX", enabled. **Start Mixxx after Amadeus Link**: Mixxx looks for MIDI
     devices only when it starts.

   **Spotify** tracks in djay Pro and VirtualDJ have no file to send: Link says which recording a deck streams
   (from djay's library, VirtualDJ's database), and the lighting computer fetches a copy itself when its
   Settings › Integrations › Streamed tracks is on ([docs/dj-software.md](../docs/dj-software.md)).

   Switched on, Link advertises itself with Bonjour and shows a 4-digit code. Don't run a live show of
   Amadeus DMX on the DJ laptop as well: it takes VirtualDJ's port (UDP 9123), and Link says so until it's free.
2. **The lighting computer**: Start ▸ **Start with a DJ Laptop…** lists the nearby DJs; pick one and type
   the code. From the command line: `amadeus live --remote auto --code 1234` (or `--remote HOST:7123`).

Link's djay Pro and Mixxx readers are ports of the engine's (`amadeus/show/sources/djay.py`, `mixxx.py`);
`swift test` checks them against the values the engine's own code gives.

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
open "build/Amadeus DMX.app" --args -section rig            # open on a page: show, rig, set, engine
open "build/Amadeus DMX.app" --args -wizard YES             # open the wizard
open "build/Amadeus DMX.app" --args -play TRACK.mp3 -playFrom 120 -muted YES
open "build/Amadeus DMX.app" --args -section rig -lastSet showcase -lastRig club   # a set on a rig
open "build/Amadeus DMX.app" --args -section rig -lastRig concert -editSet concert60  # the rig editor with that set
open "build/Amadeus DMX.app" --args -engineRoot /path/to/a/copy    # another engine folder (a sandbox)
open "build/Amadeus DMX.app" --args -editorSelfTest NAME   # the set NAME on the rig NAME (copies: it saves!)
                                                                   # report in $TMPDIR/editor-selftest.txt
```
