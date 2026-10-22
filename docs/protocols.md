# Protocols

Three small protocols connect the pieces. All of them are JSON; none needs a library to speak.

## 1. VirtualDJ → engine: the AmadeusLink plugin

`vdj/AmadeusLink.cpp`, loaded in VirtualDJ as a **master effect** (it never touches the audio). About 25
times a second it sends one UDP datagram to `127.0.0.1:9123`:

```json
{"t": 81234, "master": 1,
 "decks": [{"deck": 1, "file": "/Music/track.mp3", "pos": 61.42, "len": 412.0, "play": 1,
            "bpm": 128.0, "bpm0": 126.0, "vol": 0.83}]}
```

| Field | Meaning |
|---|---|
| `t` | milliseconds since the plugin started |
| `master` | the master deck |
| `pos`, `len` | position and length in seconds |
| `play` | 1 while playing |
| `bpm`, `bpm0` | current and original tempo (their ratio is the playback speed) |
| `vol` | fader × crossfader, 0..1 |
| `app` | the DJ software, when it isn't VirtualDJ (Amadeus Link's own djay Pro and Mixxx readers, `amadeus probe --emit`) |
| `title`, `artist`, `id` | what the DJ software knows about the track, when it knows it (not VirtualDJ's plugin) |
| `phase` | beat phase 0..1 from Ableton Link, for a deck synced to it (`amadeus probe --emit`) |
| `sync` | 1: the deck is synced to Ableton Link but carries no phase (Amadeus Link has no Link code): the lighting computer joins the Link session on the network and reads the beat itself (`amadeus/show/link.py`) |

On Windows the plugin is a DLL built from the same source (`vdj/build.ps1`), sending the same packets; `file`
is then a Windows path (`C:\\Music\\track.mp3`, JSON-escaped), in UTF-8 like everything here.

The receiver (`amadeus/show/vdj.py`) extrapolates each deck's position between packets, drops mirrored
decks (VirtualDJ reports copies of real decks to master effects) and treats a deck whose position stops
moving as stopped.

## 2. Engine → visualisers: the feed

A WebSocket on `ws://127.0.0.1:8765` (`--ws-port`), served by `amadeus/show/feed.py`. The web
visualiser and the Mac app both read it.

**`hello`**, on connect and whenever the track (or the deck the heads follow) changes:

```json
{"type": "hello", "track": "Deck 1: track.mp3", "duration": 412.0, "bpm": 128.0, "director": "openai",
 "fixtures": [{"id": "sharpy1", "kind": "head", "pos": [2.1, -1.5, 4.0], "fixture": "sharpy1", "...": "..."}],
 "stage": {"width_m": 12, "...": "..."}, "trusses": [], "zones": [], "plan": [{"section": "drop", "...": "..."}],
 "energy": [0.12, "..."], "max_flash_hz": 3.0, "screen": true,
 "gobos": [{"key": "qlc/ClayPaky/gobo00006", "img": "iVBORw0…", "style": "rings"}]}
```

`gobos` are the pictures on the heads' gobo wheels (base64: a grey PNG for a metal gobo, a JPEG for a glass
one; light passes where it is light), with their style (`dots`, `shapes`, `rings`, `curves`, or `figure` for a
picture or words). Frames point into this list.

**`frame`**, 40 times a second (the rig's `artnet.fps`):

| Field | Meaning |
|---|---|
| `t`, `phrase`, `bp` | track position, phrase index, beat position (beat + phase) |
| `fx` | per element: `[dimmer, r, g, b, white, pan, tilt]` as the fixture really shows it |
| `beam` | per element: the beam effect the head really plays (`open`, `gobo`, `prism`, …; what its mode can't play, the nearest it can) or null |
| `gobo` | only when a gobo is in a beam: per element `[picture, next picture, slide 0..1, turns per second (± direction), shakes per second, prism 0/1]` or null; pictures index the hello's `gobos`, -1 is the wheel's open hole, slide is how far the wheel has turned from one to the next |
| `zoom` | only when a light has a zoom (a head, or a wash par): per element 0 (tightest) .. 1 (widest), as far as the zoom motor has got, or null |
| `dirs` | per element: the head's beam direction (unit vector), computed back from its DMX pan/tilt |
| `lz` | per element: the beams a laser draws, `[dx, dy, dz, r, g, b, brightness]` each |
| `bands` | spectrum meters, 0..1 |
| `decks` | live mode: each deck's track, volume, play state and preparation progress |
| `link` | Amadeus Link: the link's health (offset, jitter, lost packets) |
| `guard` | what the laser guard did this frame (laser id → note) |
| `arc` | live mode: the show arc (below) |
| `limit` | only while the brightness limiter is on: its ceiling, 0.05..1 (the lights get at most this; `fx` shows the show unlimited) |

**The show arc** (`amadeus/show/arc.py`, live mode): the night as a whole. `arc` in every frame holds the
night's `length` and `elapsed` seconds (null until the music first plays), the `event` type (`club`,
`wedding`, `party`, `latin`) and the `stages` named for it, the `stage` the music is in and whether the
operator `locked` it, the music's `heat` (0..1) and `trend`, the tempo (`bpm`, `base_bpm`: tonight's warm-up
tempo), every knob's value in `values` (0..1; in play: `groups`, `specials`, `screen`, `smoke`; character:
`movement`, `changes`, `colour`; reaction: `response`, `drops`, `flashes`; level: `intensity`), the knobs the
operator holds (`manual`), how many light `groups` the rig has and how many are `playing`, and the shape the
plans are played in (`movement_level` 0 calm / 1 moderate / 2 as directed, `hold`: phrases a look is held).
The LED wall is drawn by the visualisers: they dim it by `values.screen`, below 0.5 show only calm colour, at 0
nothing. Before the first track there is no `hello`, but lite status frames with `arc` still
come (so the night can be set up before the music).

**Client → engine.** Clients may send JSON on the same socket. `{"type": "arc", …}` with any of: `knob`
(`{name: value}`: the operator takes the knob over), `auto` (a knob's name, or `"all"`: back to the arc),
`stage` (force a stage), `lock` (bool), `length_s`, `event`, `reset` (`true`: a new night) and `enabled`.
The engine remembers it in `config/show-arc.json`; a night continues over an engine restart unless the
music has been silent for two hours.

**Lite clients** connect to `ws://…/lite` and get a `frame` with `"lite": true` and only the small fields
(`t`, `phrase`, `bp`, `decks`, `link`, `guard`), 5 times a second. The Mac app uses this in Perform mode.
The full frames are only built while a full client is connected.

## 3. DJ laptop → lighting computer: Amadeus Link (v1)

The Amadeus Link app (`mac/Sources/AmadeusLink/`, on Windows `windows/AmadeusLink/`) on the DJ's laptop
receives the plugin's packets (as the engine would), advertises itself with Bonjour (`_amadeuslink._tcp`,
TCP port 7123) and shows a 4-digit code. The engine (`amadeus live --remote dj:NAME --code 1234`,
`amadeus/show/link.py`) pairs with it. It finds the DJ laptop with macOS's `dns-sd`; where there is none
(Windows without Apple's Bonjour service), with the `zeroconf` package, which speaks multicast DNS itself.

**Pairing** (JSON lines over TCP):

```
→ {"hello": "amadeus", "v": 1, "nonce": c}           c, s: 16 random bytes, hex
← {"v": 1, "name": "DJ laptop", "nonce": s}
→ {"proof": HMAC(code, "pair" s c), "udp": <port>}
← {"ok": true, "session": id}                          or {"ok": false, "error": …} and close
```

The session key is `HMAC(code, "key" s c)` (HMAC-SHA256). The connection stays open as a keepalive
(`{"ping": n}` → `{"pong": n}`); when it drops, the engine pairs again by itself.

**Deck state** (UDP, ~25 per second): `<json> "|" <first 16 bytes of HMAC(key, json), hex>` with
`json = {"s": seq, "ts": <sender clock, ns>, "d": <the plugin's packet>}`. Late or duplicate sequence
numbers are dropped.

**Clock sync:** the offset between the two clocks is the smallest `arrival − sent` over the last 8
seconds (NTP-style: the fastest packets queued least), so network jitter cancels out; deck positions are
extrapolated from the moment they were sent.

**Tracks** (one TCP connection per file): `→ {"file": path, "session": id, "auth": HMAC(key, "file" path)}`,
`← {"ok": true, "size": n, "mtime": t, "sha256": h}` followed by `n` bytes. Only files the plugin has
reported are served. The engine checks the SHA-256 and caches the file in `.cache/remote/`.

The code protects against accidental and casual misuse on a shared network (a wrong code can't pair, and
packets can't be forged without the key); it is not meant to stand up to an attacker who can watch the
pairing.

## 4. Other DJ software: integrations

`amadeus/show/sources/` holds one integration per DJ software. Each one is a `Source`: it fills `decks`
(track file, position at a moment, tempo, volume, plus title/artist when known) and derives the same events
for all of them (`track_loaded`, `playback_started`, `playback_stopped`, `seek`, `loop`). Live mode follows
one with `amadeus live --source NAME [--opt key=value …]`.

`amadeus probe NAME` shows what an integration sees and how well it keeps time (readings per second, the
longest gap, and the drift between what a reading says and where the previous one predicted the deck would
be). `--emit 127.0.0.1:9123` passes it on as the AmadeusLink plugin's packets (section 1), so on a DJ
laptop the Amadeus Link app (section 3) carries any DJ software to the lighting computer unchanged.
`--record FILE` keeps the readings for `--source replay --opt file=FILE`.

A deck of DJ software synced to Ableton Link also carries `phase` (its beat phase, 0..1, also in the plugin
format that `--emit` sends): live mode then locks that deck to Link's beat (`sources/base.py`, `PhaseLock`):
the DJ software's own position picks the beat, Link gives the exact moment, and the fixed offset between
the two is learnt as it plays.

A track that the DJ software only names (artist, title, length) or reports with a path from another
computer is looked up in the music folders (`AMADEUS_MUSIC`, folders separated by `:`, on Windows by `;`,
default the Music folder).

## 5. App → engine: starting and stopping

An app runs the engine as a child process, `python -m amadeus live …` (or `play`, `setup`, …), in the engine
folder, with:

| Variable | Meaning |
|---|---|
| `AMADEUS_ROOT` | the engine folder (package, web UI, fixtures; read only) |
| `AMADEUS_DATA` | your data: sets, rigs, settings, packs, the cache (macOS `~/Library/Application Support/Amadeus DMX`, Windows `%LOCALAPPDATA%\Amadeus DMX`) |
| `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8` | its output line by line, in UTF-8 (on Windows the engine switches a pipe to UTF-8 itself as well) |
| `AMADEUS_FFMPEG` | optional: the ffmpeg to decode with (the Windows app may ship `bin\ffmpeg.exe` in the engine folder instead) |
| `AMADEUS_STOP_ON_EOF` | `1`: stop when stdin closes (the default on Windows when stdin is a pipe); `0`: never |

**Stopping** always ends in the engine's Ctrl+C path: the show blacks out, ends its sACN streams and closes its
ports before the process exits (`amadeus/shutdown.py`). macOS: SIGINT (the Mac app's `Process.interrupt`).
Windows: close the engine's stdin (the app keeps it a pipe while the engine runs; if the app dies, the pipe
closes too), or `CTRL_BREAK_EVENT` to an engine started with `CREATE_NEW_PROCESS_GROUP`. Only the first
request is acted on. Wait a few seconds before ending the process the hard way: that skips the blackout.

**Ports**, all on this computer unless said: UDP 9123 (the VirtualDJ plugin, 127.0.0.1), HTTP 8080 (the web
UI; `amadeus setup --lan` on every interface), WebSocket 8765 (the feed, 127.0.0.1), and out to the network:
Art-Net UDP 6454, sACN UDP 5568 (multicast 239.255.x.y), Amadeus Link TCP 7123 + a UDP port of the engine's
own, Bonjour UDP 5353. Windows Defender Firewall asks the first time a program listens on the network (`setup
--lan`, Amadeus Link's UDP, discovering Art-Net nodes on 6454): allow it on private networks.
