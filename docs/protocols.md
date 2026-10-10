# Protocols

Three small protocols connect the pieces. All of them are JSON; none needs a library to speak.

## 1. VirtualDJ → engine: the DecisiveLink plugin

`vdj/DecisiveLink.cpp`, loaded in VirtualDJ as a **master effect** (it never touches the audio). About 25
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

The receiver (`decisive/show/vdj.py`) extrapolates each deck's position between packets, drops mirrored
decks (VirtualDJ reports copies of real decks to master effects) and treats a deck whose position stops
moving as stopped.

## 2. Engine → visualisers: the feed

A WebSocket on `ws://127.0.0.1:8765` (`--ws-port`), served by `decisive/show/feed.py`. The web
visualiser and the Mac app both read it.

**`hello`**, on connect and whenever the track (or the deck the heads follow) changes:

```json
{"type": "hello", "track": "Deck 1: track.mp3", "duration": 412.0, "bpm": 128.0, "director": "openai",
 "fixtures": [{"id": "sharpy1", "kind": "head", "pos": [2.1, -1.5, 4.0], "fixture": "sharpy1", "...": "..."}],
 "stage": {"width_m": 12, "...": "..."}, "trusses": [], "zones": [], "plan": [{"section": "drop", "...": "..."}],
 "energy": [0.12, "..."], "max_flash_hz": 3.0, "screen": true}
```

**`frame`**, 40 times a second (the rig's `artnet.fps`):

| Field | Meaning |
|---|---|
| `t`, `phrase`, `bp` | track position, phrase index, beat position (beat + phase) |
| `fx` | per element: `[dimmer, r, g, b, white, pan, tilt]` as the fixture really shows it |
| `beam` | per element: the head's beam effect (`open`, `gobo`, `prism`, …) or null |
| `dirs` | per element: the head's beam direction (unit vector), computed back from its DMX pan/tilt |
| `lz` | per element: the beams a laser draws, `[dx, dy, dz, r, g, b, brightness]` each |
| `bands` | spectrum meters, 0..1 |
| `decks` | live mode: each deck's track, volume, play state and preparation progress |
| `link` | Decisive Link: the link's health (offset, jitter, lost packets) |
| `guard` | what the laser guard did this frame (laser id → note) |

**Lite clients** connect to `ws://…/lite` and get a `frame` with `"lite": true` and only the small fields
(`t`, `phrase`, `bp`, `decks`, `link`, `guard`), 5 times a second. The Mac app uses this in Perform mode.
The full frames are only built while a full client is connected.

## 3. DJ laptop → lighting computer: Decisive Link (v1)

The Decisive Link app (`mac/Sources/DecisiveLink/`) on the DJ's laptop receives the plugin's packets
(as the engine would), advertises itself with Bonjour (`_decisivelink._tcp`, TCP port 7123) and shows a
4-digit code. The engine (`decisive live --remote dj:NAME --code 1234`, `decisive/show/link.py`) pairs
with it.

**Pairing** (JSON lines over TCP):

```
→ {"hello": "decisive", "v": 1, "nonce": c}           c, s: 16 random bytes, hex
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
