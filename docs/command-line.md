# The engine from the command line

Everything the apps do can also be run from a terminal, from a source checkout. This is for developers and power users; most people want the [installers](https://github.com/mathijs-b2m/AmadeusDMX/releases/latest).

## Build from source

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[openai]"         # add ",ml" for instrument separation (Demucs, ~2 GB), ",usb" for USB DMX
echo 'OPENAI_API_KEY=sk-...' > .env          # optional: only for the OpenAI decision model
.venv/bin/amadeus play "track.mp3"          # the visualiser only: http://localhost:8080
.venv/bin/amadeus setup                     # http://localhost:8080/setup.html: fixtures, node, decision model
.venv/bin/amadeus play "track.mp3" --dmx    # … and the real lights
```

The first run starts with the examples (`examples/`): a showcase set of popular fixtures on a club rig, and
60 moving heads with lasers on a concert stage. Your own sets and rigs live in `config/` (not in git).

**Mac app:** `cd mac && ./build-app.sh --install` (see [mac/README.md](../mac/README.md), which also covers release builds, signing and updates).

**Windows app:** `cd windows && ./build.ps1` on Windows 10 22H2 or 11 (x64) with the .NET 10 SDK (see [windows/README.md](../windows/README.md)).

On Windows the commands below are the same, with `.venv\Scripts\amadeus` for `.venv/bin/amadeus`.

Open **http://localhost:8080** for the 3D visualiser (stage, the decision per phrase with confidences and the exact prompt, energy curve with ⚡ drops) and **/setup.html** for the setup page.

For VirtualDJ: see [Live in VirtualDJ](#live-in-virtualdj).

## Commands

| Command | What it does |
|---|---|
| `amadeus play TRACK [--dmx [IP]] [--mute] [--start SEC] [--tempo half\|double] [--director …] [--style GENRE]` | Play a track with lights and visualiser (audio-clocked). Blackout on Ctrl+C |
| `amadeus live [--dmx [IP]] [--director …] [--remote dj:NAME --code NNNN]` | Follow a VirtualDJ mix via the AmadeusLink plugin, on this computer or on a DJ laptop (Amadeus Link) |
| `amadeus setup` | Web setup page only (no show) |
| `amadeus genre TRACK [GENRE\|auto]` | A track's genre (one word) and where it came from; set your own, or back to automatic |
| `amadeus analyze TRACK [--tempo half\|double]` | Audio analysis only (cached in `.cache/`) |
| `amadeus direct TRACK [--director …] [--style GENRE] [--redo]` | Build and print the show plan (`--style`: in another genre's house style) |
| `amadeus library` | List fixture definitions; `amadeus library beamz fuze` searches QLC+ and the Open Fixture Library too, `--add <key>` adds a result |
| `amadeus patch MODEL[:COUNT] …` | Patch fixtures into the active set, assign addresses |
| `amadeus discover [--write] [--readdress] [--sim]` | Find the Art-Net node (and RDM fixtures) on the network |
| `amadeus test [--level 0.3]` | Hardware bring-up: each fixture on its own (smoke machines fire briefly), then head orientation calibration |
| `amadeus gobos FIXTURE` | Project the gobos one by one and name them |
| `amadeus colors FIXTURE` | Show the colour wheel slot by slot and name the colours |
| `amadeus motion FIXTURE [--axis pan\|tilt]` | Measure how fast a moving head really swings on the beat |
| `amadeus simnode MODEL[:COUNT],…` | Simulated Net-2/5 with virtual (RDM) fixtures, decodes incoming DMX |
| `amadeus set [NAME] [--new \| --copy-of SET]` | Your fixtures: list, switch or create sets |
| `amadeus rig [NAME] [--template T] [--automount [--all]] [--hang-sheet [FILE]]` | The venue: list, switch or create rigs (templates: floor, stands, booth, club, stage); mount the set on it; write the hang sheet for the crew |
| `amadeus monitor` | Watch VirtualDJ and the engine: CPU, memory, threads, GPU, crashes |
| `amadeus probe [NAME] [--emit 127.0.0.1:9123]` | Other DJ software (Mixxx, djay Pro, …): list, watch and measure one, or pass it to the Amadeus Link app |
| `amadeus packs [install NAME]` | The optional packs (instrument analysis, streamed tracks): list or install |
| `amadeus instruments [TRACK] [--download]` | The instrument models (non-commercial license) and a track's instruments over time |
| `amadeus synctest make` / `listen` | A test track with beeps, and a listener: how far the show is from the music you hear |

(`amadeus` = `.venv/bin/amadeus`, or `python -m amadeus`.) `--dmx` without an IP uses the node from the rig. Audio formats: WAV, MP3, FLAC, OGG, AIFF directly; M4A/AAC is decoded once with ffmpeg.

## Live in VirtualDJ

The **AmadeusLink** plugin (`vdj/`) runs as a master effect, leaves the audio untouched, and streams the mix state 25 times per second over UDP `127.0.0.1:9123`: per deck the file, position, play state, BPM, original BPM and volume (fader × crossfader), plus the master deck.

```bash
./vdj/build.sh --install                      # downloads the SDK headers, builds an arm64 bundle, installs it
.venv/bin/amadeus live --dmx
```

Restart VirtualDJ, then enable **AmadeusLink** as a **master** effect. Works with VirtualDJ 8.5 Home (free) on Apple Silicon.

**DJ and lighting on different computers:** run the small **Amadeus Link** app (`mac/`) next to VirtualDJ on the DJ's laptop; it shows a 4-digit code. On the lighting computer: `amadeus live --dmx --remote auto --code 1234`, or *Start with a DJ Laptop…* in the Mac app. Deck state is clock-synced (a few ms) and tracks are fetched once over the network. See [docs/protocols.md](protocols.md).

- **Every deck plays its own pre-analysed show** at exactly the position VirtualDJ reports, so seeks, loops, pitch changes and cuts are followed.
- **A new track** is analysed as soon as it's loaded (a few seconds) and gets an instant rule-based plan. The decision model's plan replaces it when ready.
- **Mixing:** brightness and colour blend by deck volume. The moving heads follow the dominant deck, switching only when the other deck is clearly louder (20% margin, no flapping).
- **Robustness:** mirrored decks (VirtualDJ reports non-existent decks as copies on master effects) are dropped. A deck that's "playing" but whose position doesn't move counts as stopped. No packets for 1 s → lights dark.
- The plugin keeps its VirtualDJ queries low (~230/s: only real decks; file, length and original BPM twice per second).

**Known VirtualDJ issue (not the plugin):** on macOS the VDJ interface can freeze after switching apps while audio keeps running. Workarounds from the VDJ forums: set the display to 60 Hz instead of ProMotion, avoid Stage Manager or toggle Full Screen/Windowed, try `experimentalUseMetal` or `skinFps` in VDJ's options.

## Is the show in sync?

`amadeus synctest make` writes a test track (128 BPM, three minutes, with a build-up and two drops) to
`~/Music/Amadeus DMX/`, with a short 3.15 kHz beep on the downbeat of every fourth bar. Load it in the DJ
software, start the live show, play it, and run `amadeus synctest listen`: the Mac's microphone hears each
beep, the show's feed says where the show was at that moment, and since each beep's place in the track is known
the difference is how far the show is from the music **as you hear it** (DJ software, its audio buffer,
speakers and room included), with the light lead (`artnet.lead_ms`) taken out. It prints each beep and then the
offset, its spread and any drift per minute. The analysis gets this track exactly (a test checks tempo, beats,
bar lines and drops), so an offset here is the live timing, not the analysis.

The live show also writes `.cache/live.log`: everything it prints with clock times, and at every phrase change
the position the DJ software reported next to the position the show plays.

## Other DJ software

Live mode also follows **Mixxx** and **djay Pro**: `amadeus live --source mixxx` or `--source djay`, or
Start ▸ *Start Live Show (…)* in the Mac app. `amadeus probe` lists the integrations and measures one.
djay is read from its window, which needs macOS's **Accessibility** permission: Amadeus DMX only
*reads* djay's deck labels with it, never clicks or types. What each integration does, needs and has been
tested on, and exactly what that permission is used for: [docs/dj-software.md](dj-software.md).

## Sets and rigs

- A **set** is your gear: the fixtures you own, their DMX mode and address, calibration, where the DMX goes (`config/sets/<name>.json`). Most people have one.
- Your **DMX devices** (Art-Net and sACN nodes, USB interfaces) live apart from the sets, in `config/devices.json`: each set up once (name, address, how it counts its universes). A set maps its universes onto them (`"dmx": {"1": {"device": "pocket", "output": 1}}`): replace a node or play somewhere with other controllers, and only that mapping changes. In the Mac app: *Show → DMX Devices & Output…* (⇧⌘D). Sets without a mapping keep their own `output`/`artnet` settings.
- A **rig** is a venue: the stage's size, trusses and towers, the LED wall, zones, and where each set's fixtures hang on it (`config/rigs/<name>.json`).
- A show runs with a set placed on a rig: the active ones (`config/active-set`, `config/active-rig`), or `--set NAME --rig NAME`. A running show keeps the ones it started with.

```bash
.venv/bin/amadeus set                                  # your sets
.venv/bin/amadeus rig                                  # your rigs, and which sets are mounted on them
.venv/bin/amadeus rig rotterdam --template club --width 10 --screen   # a new rig from a template
.venv/bin/amadeus rig --automount                      # mount the active set's fixtures on the active rig
.venv/bin/amadeus play TRACK.mp3 --set mine --rig rotterdam --mute
```

**Mounting a set on a rig:** fixtures the rig has no place for yet wait on the floor in front of the stage. A rig without truss objects (generated test rigs, older rigs) first gets its structure back: fixtures hanging in a row become a truss, fixtures stacked at one spot a tower; a rig with no structure at all gets the usual one for its stage. **Auto-mount** then hangs them the way a lighting tech would start: lasers high at the back, moving heads under the trusses (some on the towers), strobes and blinders on the front, bars and pars on the floor, every model mirrored around the middle. In the Mac app's rig editor you can then drag any fixture, a ⇧-selection, or a whole group from the list onto a truss; a group hangs in a row. On a tower a fixture hangs off one of its four faces (front, back, left, right; the side you drag it off picks the face), its head pointing out; only on top of a tower does it stand. The same set can be mounted on as many rigs as you like; each rig remembers where it hangs. The file format and the rules are in [docs/rig-format.md](rig-format.md).

**Hang sheet and check:** a set designed in the app has to be hung by someone on a ladder. The rig editor's
printer button (or `amadeus rig --hang-sheet`) prints a plot of the stage seen from above, per truss and tower
which fixture goes where (measured from a named end, which way it faces), the DMX patch to dial on each fixture,
and labels for the fixtures or their cases. After hanging, the check lights the fixtures one by one in the
sheet's order; a swapped pair or a head hung the wrong way round is put right in the app with one click. Stage
left is the performer's left (x = 0). See [rig-format.md](rig-format.md#hang-sheet).

Sets from before rigs existed (fixtures with positions and the stage in one file) are split into a set and a rig of the same name the first time you run the engine or the Mac app; nothing changes for the show.

**Test rigs:** `amadeus set NAME --grid qlc:Martin/Martin-MAC-Encore-Performance.qxf:60 --rows 3 --width 16 --height 7` (or `--layout concert --lasers 10`) makes a set of many fixtures and a rig they hang on (Art-Net to 127.0.0.1 only, so a test rig never drives your real lights). Head motion for big rigs is simulated for all heads at once (60 heads: ~1.5 s on first load) and cached in `.cache/trajectories/`.

## What's in a set and a rig

- **Set:** `artnet` (node IP, port, frame rate) or `output` (sACN, USB), `safety` (`master`, `max_flash_hz`), `director` (the decision model), and `fixtures`: id, library model, mode, universe, address and calibration.
- **Rig:** `stage` (width, ceiling, room depth, `eye_safety`), `trusses`, `screen` (an LED wall), `zones`, and `placements`: per set, per fixture, where it hangs (`x`, `y_m`, `z_m`, `mount`, `truss`, …).

The **setup page** (`/setup.html`) edits the active set on the active rig: pick the set and the rig (or make a new rig from a template and auto-mount the set on it), add fixtures from the library, modes, addresses, auto-address and layout, Identify (lights one fixture white for 2 s), find the node on the network, stage and safety, decision model. Saves with overlapping addresses are refused.

**Mobile setup** (`amadeus setup --lan`, then open the printed `http://<mac-ip>:8080/m.html` on your phone): search a fixture across your library, the QLC+ library (~1,800 fixtures, Apache-2.0) and the Open Fixture Library (MIT); pick the DMX mode; get free start addresses (*easy to dial*: every address ends in 1, or *packed*) with what to set on the fixture's menu; add it to the rig. Existing fixtures keep their addresses. Or tap **📷 Photo**: photograph the fixture's label (type plate), or just the fixture. With `OPENAI_API_KEY`, `gpt-6-luna` looks at the photo and says what it is (brand, model, type, beam/spot/wash: read from the label, or recognised from the housing, lens and logo), then the Decisions API picks the matching entry among the closest library fixtures, with the photo; at ≥ 90 % from a label it opens the fixture straight away, from the looks alone it always asks you to confirm. Without a key, a local Ollama vision model (e.g. `gemma4`) reads the label and the text is searched (~10–30 s). Every step is logged in the setup terminal and `.cache/setup-events.log`; the last 20 photos are kept in `.cache/labels/`. Every QLC+ and OFL fixture ships already converted (`fixtures/catalog/`), so this works offline. `--lan` lets anyone on that network change the rig, so use it on a network you trust.

**Placement from a photo** (mobile page): *Light up the rig* gives every fixture its own colour for 2 minutes (dimmed; heads aim 30° above the audience, not into the camera; six colours per photo, more fixtures go in groups). Take a photo from the audience: the page finds the coloured light spots itself (exact positions), and `gpt-6-luna` says per colour what it is mounted on (floor, stand, truss, upside down), roughly how high, the distance between the outermost fixtures and any alignment problems. You get the photo with markers and a list of proposed changes (`x`, `mount`, `z_m`, `stage.width_m`) to tick and apply. Distances are measured from the fixtures' housing sizes (`physical.size_mm`, from QLC+/OFL), not guessed. A big glow (a par lighting the wall) is recognised as such. A different left-to-right order than the rig is flagged (usually a wrong address or mode). While the photo lights (or Identify) are on, a running show pauses its DMX output (`.cache/dmx-hold`).

**Exact placement from a 3D scan** (mobile page, *Or exact: a 3D scan*): *Light up for a scan* keeps the colours on for 10 minutes; scan the setup with an iPhone app such as Niantic Scaniverse (walk around it, include the floor and the wall behind), export a **point cloud (PLY)** — or a Gaussian-splat PLY — and upload it. Phone scans are in real metres with gravity along one axis, so `amadeus/setup/pointcloud.py` finds the floor (up axis: y or z), the room's big surfaces (RANSAC), each fixture as the 3D centre of its colour (clusters close together, like the LEDs of one bar, are combined; light spilling on a wall or the floor is ignored), the stage frame (x along the line of fixtures, the audience on the side away from the wall), the ceiling height and the room depth in front. The page shows a top-down view with the fixtures; flip the audience side or tap a marker and then its real place to correct it, and apply exact `x`, `y_m`, `z_m`, `mount`, `stage.width_m`, `ceiling_m` and `room_depth_m`. The last 5 scans are kept in `.cache/scans/`.

## Fixture library (`fixtures/<manufacturer>/<model>.json`)

Every DMX mode from the manual, safe defaults for channels the engine doesn't drive (shutter open, prism off, no programs, strobe channel never driven), plus:

- **`motion`:** speed and acceleration per axis (measure with `amadeus motion`).
- **`beam_fx`:** DMX values per beam effect, including rotation ranges.
- **`gobo_names` / `gobo_groups`:** name them with `amadeus gobos` (the styles map the names to dots, shapes, rings, curves).
- **`color_wheel`:** slot colours (name them with `amadeus colors`; `"verified": false` means guessed).

Any fixture from the QLC+ library and the Open Fixture Library can be added: all of them ship already converted in `fixtures/catalog/`, so it works offline. A fixture the show can't play from its library file (only effect, macro or unnamed channels) is marked on the Mac app's Set page and mapped there by hand with the **DMX mapper**, trying each channel on the real fixture. Converted lasers stay dark until mapped by hand; smoke machines and hazers are played by the show, sized to the machine and the room. See [docs/fixture-catalog.md](fixture-catalog.md).

Included: **beamZ Fuze75B Beam** (12ch/10ch, measured motion, named gobos and colour wheel), **beamZ Fuze75S Spot** (13ch/11ch, colours and motion still estimated), **Ayra ComPar Kit 2** (4 RGB heads, 16/12/7/3ch), **Chauvet COLORado PXL Curve 12** (12 RGBW cells, each on its own tilt motor with its own zoom: waves and curves along the bar; 179/169/155/101/53/20ch, Single Control), and conversions of popular fixtures from the QLC+ library (Sharpy, Pointe, MAC Aura, MAC Encore, Atomic 3000, …; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)).

## Real hardware checklist

1. Connect the Net-2/5 to the same network as the Mac. It can use DHCP on a home network; otherwise set the Mac to 2.x.x.x / 255.0.0.0 for the factory default 2.0.0.1.
2. Find it: setup page → *Find node*, or `amadeus discover --write`. Note which Art-Net universe each output port uses (our Net-2/5 port 1 = universe 1).
3. Patch the fixtures (setup page or `amadeus patch …`) and set the same mode and start address on each fixture's display. DMX chain order doesn't matter.
4. `amadeus test`: every fixture on its own, then head orientation (calibration is saved). In the Mac app, each fixture on the Set page has a **Test** button: it stays lit (the rest of the set dark, a running show paused) until you switch it off, a minute at most, and says which universe, channels and output its DMX goes to. It also lights the emitters the show doesn't mix in (UV, amber).
5. Optionally `amadeus motion`, `amadeus gobos`, `amadeus colors` per head model.
6. First show with `safety.master` at about 0.5.

Discovery also lists RDM fixtures and can re-address them over RDM (`--readdress`), but most budget fixtures (including the Fuze75 and ComPar) don't speak RDM, so patch them by hand. `amadeus simnode` simulates a node with RDM fixtures for testing without hardware.
