# DJ software

Live mode follows a DJ's decks: which track each deck plays, where in it, how fast, and how loud. VirtualDJ
was first; other DJ software comes in through **integrations** (`decisive/show/sources/`), one per DJ
software, all behind the same `Source` interface. The engine and the Mac app's Start menu read the same
list (`decisive/show/sources/sources.json`).

```bash
decisive probe                         # the list, with what each integration has been tested on
decisive probe mixxx                   # watch one: decks, events, how well it keeps time
decisive live --source mixxx --dmx     # follow it (the Mac app: Start ▸ Start Live Show (Mixxx))
```

Accurate position matters most: every deck plays its own pre-analysed show at the position the DJ software
reports, so the lights can only be as precise as that position. A track the DJ software names but whose file
isn't on this computer is looked up in the music folders (`DECISIVE_MUSIC`, default `~/Music`).

## At a glance

| DJ software | How | Position (measured) | Needs | Status |
|---|---|---|---|---|
| **VirtualDJ** | our plugin (`vdj/`), UDP | exact, from VirtualDJ | the plugin as master effect | verified, live on a real rig |
| **Mixxx** | its official controller scripting, over a virtual MIDI port | p95 10 ms from Mixxx's playhead, 51 readings/s | the "Decisive Lightning" controller mapping (copied for you), `python-rtmidi` | verified, Mixxx 2.5.6 (macOS) |
| **djay Pro** | its window, read through macOS Accessibility, plus Ableton Link | on SYNC: within 6 ms (sd) of Link's beat; without SYNC: sd 12–17 ms, up to ~70 ms | the Accessibility permission, `pyobjc-framework-ApplicationServices`, `aalink` | verified, djay Pro 5.6.8 (macOS) |
| **Serato DJ Pro** | the protocol of its Serato Remote app (OSC over TCP, Bonjour) | exact, from Serato (per its protocol notes) | nothing in Serato | branch `integrations/serato`, tested against a simulated Serato only |
| **Engine DJ / Denon** | StageLinQ (community-documented) | exact, per the protocol | a Denon player on the network | not started: needs hardware |
| **rekordbox / Pioneer** | PRO DJ LINK (Beat Link, community-documented) | exact on CDJ-3000, beat-precise on older players | Pioneer players on the network | not started: needs hardware |
| **Traktor Pro** | no API; broadcast metadata, MIDI clock, Ableton Link | beat phase only, unless its controller files are modified | — | not started |

## VirtualDJ

See the README ("Live in VirtualDJ") and [protocols.md](protocols.md), sections 1 and 3.

## Mixxx

Mixxx's controller scripts can't open a network socket, but they speak MIDI. `decisive live --source mixxx`
creates a virtual MIDI device, **Decisive Lightning**, and copies a controller mapping of the same name into
Mixxx's controllers folder (`mixxx/` in this repository). In Mixxx: Preferences → Controllers → Decisive
Lightning → load the mapping "Decisive Lightning" → Enabled. Its script sends every deck's position,
length, speed, tempo, volume, loop state and the crossfader 50 times a second as SysEx. A script can't read
a track's title or file, so the track is found in Mixxx's own library (read only) by its exact length.

- Mixxx looks for MIDI devices only when it starts: start the live show first, then Mixxx. With macOS's
  IAC bus switched on (Audio MIDI Setup) and `--opt port="IAC Driver Bus 1"`, the order no longer matters.
- What you hear comes slightly after Mixxx's playhead (its audio buffer, ~10–25 ms): `--opt latency=15`
  (milliseconds, any integration) compensates.

## djay Pro

djay has no API, no plugin interface, and writes no playhead anywhere (its library only records which track
started, and when). What it does have is a window whose controls are labelled for VoiceOver: per deck the
title, artist, elapsed time, play button, tempo, line volume, and the crossfader. The integration reads those
labels, about 200 times a second, through the macOS Accessibility API.

- **Position:** the elapsed time shows whole seconds (rounded down) and djay redraws it about 10 times a
  second, so a change from 01:06 to 01:07 means the playhead crossed 67 s at most ~100 ms earlier. Of the last
  eight such ticks, the least late places the playhead. After a seek, the position is half a second
  uncertain until the next tick.
- **On SYNC:** a deck synced to Ableton Link plays its beats on Link's beats. Link knows nothing about tracks,
  only tempo and beat phase, so it can't say where in a track a deck is; but djay's own position says which
  beat it is, and Link says exactly when. Live mode locks the deck there (`PhaseLock` in
  `sources/base.py`); the fixed offset between the two (about 145 ms here, djay's audio latency) is learnt as
  it plays. Any DJ software that syncs to Link can use the same lock.
- **Files:** djay's library (`~/Music/djay/…/MediaLibrary.db`, read only) gives the file of a local track.
  djay only records a newly added file there once it *plays*, so a track loaded for the first time is looked
  up by its title in the folders of the tracks djay already knows (and the music folders): its show is
  prepared while it is still cued, as with VirtualDJ.
- **Streamed tracks (Spotify):** these have no file to analyse, but djay's library says exactly which recording
  each one is: its Spotify id, its ISRC (the recording's own code, the same on every service) and its length.
  When a Spotify track is loaded on a deck, live mode fetches a local copy of that same recording from YouTube
  (yt-dlp: `pip install -e '.[streamed]'`), found by its ISRC, usually the label's own "Artist - Topic"
  upload. The copy is taken only if its length matches Spotify's within a second (most match within 30 ms; an
  edit or a video with an intro is seconds off), then analysed and lit like a local file, at djay's playhead.
  Nothing is played from the copy: the audience hears djay's stream. Copies are kept in `.cache/streamed/`, at
  ~70 kbps (enough to analyse). YouTube is asked gently: only for tracks on a deck, one search or download at
  a time, 3 s apart; a track unloaded before its turn is skipped. A first fetch takes ~2–5 s, then the
  quick plan lights it within seconds. `--opt streamed=0` switches it off. Only fetch audio you may copy.

### The Accessibility permission

The first time the live show follows djay, macOS asks:

> "Decisive Lightning.app" would like to control this computer using accessibility features.

macOS uses the same wording for every app that asks for this permission, because the permission itself is
broad: an app that has it *can* read what other apps show and *can* click and type in them. Decisive
Lightning uses it to **read**, and only this:

- **Which app:** only djay Pro (an app whose bundle id starts with `com.algoriddim.djay`). No other app's
  window is opened.
- **What:** the text of djay's deck controls, by their VoiceOver labels ("Elapsed time, Deck 1" → `01:07`,
  "Play / Pause, Deck 1" → `Active`, …). No screenshots, no screen recording, no keystrokes.
- **Never:** it doesn't click, type, press buttons or change anything in djay or any other app. The code
  makes three kinds of Accessibility calls only: whether the permission is granted
  (`AXIsProcessTrustedWithOptions`), djay's window (`AXUIElementCreateApplication`) and an element's text or
  label (`AXUIElementCopyAttributeValue`). All of it is in `decisive/show/sources/djay.py`.
- **When:** only while a live show follows djay. Following VirtualDJ, Mixxx or another DJ software doesn't
  touch it.
- **Where it goes:** the deck state stays on this computer, as with VirtualDJ: into the light show and the
  visualiser feed (on a DJ laptop, `decisive probe djay --emit` passes it to the Decisive Link app).

Who gets the permission: macOS grants it to the app that started the engine. In the Mac app that is
**Decisive Lightning**; from the command line it is your terminal app (Terminal, iTerm, …). Every engine
that app starts then has it, so only grant it to an app that runs an engine folder you trust.

Switching it off (System Settings → Privacy & Security → Accessibility) only stops the djay integration: the
next live show with djay says the permission is missing; everything else works as before.

A Decisive Lightning you built yourself (`mac/build-app.sh`) is signed ad hoc, and macOS may see each new
build as a new app: if djay stops being followed after a rebuild, switch the app off and on again in that
list (or remove it with − and start the show again).

## Serato DJ Pro

Serato DJ Pro streams per-deck track changes, playhead, loops and mixer state to its **Serato Remote** app.
The integration poses as one (Bonjour `_SeratoIOSRemote._tcp`, OSC over TCP; wire format from
[serato-connect](https://github.com/chrisle/serato-connect)'s protocol notes, MIT). Serato connects by
itself; nothing is needed in Serato. On branch `integrations/serato`: tested against a simulated Serato
built from those notes, not yet against Serato itself. It uses the two fixed secrets that Serato's Remote app
uses (as published by serato-connect), which is a reason to look at it before it goes into `main`.

## Not started

- **Engine DJ / Denon (StageLinQ)** and **rekordbox / Pioneer (PRO DJ LINK)** give exact positions over the
  network by documented community protocols, but need the players on the network to build and test against.
- **Traktor Pro** has no API: broadcast metadata (title only), MIDI clock and Ableton Link give tempo and
  phase, not where in the track. A position needs a modified controller mapping inside Traktor's app bundle.

## Adding one

1. A module in `decisive/show/sources/` with a `Source` subclass that calls `self.received([...Deck...])`
   for every reading (`DeckBook` turns readings into decks and events: track loaded, started, stopped, seek,
   loop). Report `phase` on a deck when the DJ software is synced to Ableton Link.
2. An entry in `sources.json`: its module and class, what it needs, how good its position is
   (`exact`, `beat`, `metadata`) and what it has been verified on.
3. `decisive probe NAME` to see it work and measure it; `--record FILE` keeps a session for
   `--source replay --opt file=FILE`.
