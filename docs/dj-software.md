# DJ software

Live mode follows a DJ's decks: which track each deck plays, where in it, how fast, and how loud. VirtualDJ
was first; other DJ software comes in through **integrations** (`amadeus/show/sources/`), one per DJ
software, all behind the same `Source` interface. The engine and the Mac app's Start menu read the same
list (`amadeus/show/sources/sources.json`).

```bash
amadeus probe                         # the list, with what each integration has been tested on
amadeus probe mixxx                   # watch one: decks, events, how well it keeps time
amadeus live --source mixxx --dmx     # follow it (the Mac app: Start ▸ Start Live Show (Mixxx))
```

Accurate position matters most: every deck plays its own pre-analysed show at the position the DJ software
reports, so the lights can only be as precise as that position. A track the DJ software names but whose file
isn't on this computer is looked up in the music folders (`AMADEUS_MUSIC`, default `~/Music`; on Windows
the Music folder Windows knows, and `;` between folders). For Windows, see [On Windows](#on-windows).

## At a glance

| DJ software | How | Position (measured) | Needs | Status |
|---|---|---|---|---|
| **VirtualDJ** | our plugin (`vdj/`), UDP | exact, from VirtualDJ | the plugin as master effect | verified, live on a real rig |
| **Mixxx** | its official controller scripting, over a virtual MIDI port | p95 10 ms from Mixxx's playhead, 51 readings/s | the "Amadeus DMX" controller mapping (copied for you), `python-rtmidi` | verified, Mixxx 2.5.6 (macOS) |
| **djay Pro** | its window, read through macOS Accessibility, plus Ableton Link | on SYNC: within 6 ms (sd) of Link's beat; without SYNC: sd 12–17 ms, up to ~70 ms | the Accessibility permission, `pyobjc-framework-ApplicationServices`, `aalink` | verified, djay Pro 5.6.8 (macOS) |
| **Serato DJ Pro** | the protocol of its Serato Remote app (OSC over TCP, Bonjour) | exact, from Serato (per its protocol notes) | nothing in Serato | branch `integrations/serato`, tested against a simulated Serato only |
| **Engine DJ / Denon** | StageLinQ (community-documented) | exact, per the protocol | a Denon player on the network | not started: needs hardware |
| **rekordbox / Pioneer** | PRO DJ LINK (Beat Link, community-documented) | exact on CDJ-3000, beat-precise on older players | Pioneer players on the network | not started: needs hardware |
| **Traktor Pro** | no API; broadcast metadata, MIDI clock, Ableton Link | beat phase only, unless its controller files are modified | — | not started |

## VirtualDJ

See [command-line.md](command-line.md#live-in-virtualdj), the [Mac setup guide](mac-setup.md#6-connect-your-dj-software) and [protocols.md](protocols.md), sections 1 and 3.

## Mixxx

Mixxx's controller scripts can't open a network socket, but they speak MIDI. `amadeus live --source mixxx`
creates a virtual MIDI device, **Amadeus DMX**, and copies a controller mapping of the same name into
Mixxx's controllers folder (`mixxx/` in this repository). In Mixxx: Preferences → Controllers → Amadeus
DMX → load the mapping "Amadeus DMX" → Enabled. Its script sends every deck's position,
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
- **Streamed tracks (Spotify), off by default:** these have no file to analyse, but djay's library says exactly which recording
  each one is: its Spotify id, its ISRC (the recording's own code, the same on every service) and its length.
  When a Spotify track is loaded on a deck, live mode fetches a local copy of that same recording from YouTube
  (yt-dlp: `pip install -e '.[streamed]'`), found by its ISRC, usually the label's own "Artist - Topic"
  upload. The copy is taken only if its length matches Spotify's within a second (most match within 30 ms; an
  edit or a video with an intro is seconds off), then analysed and lit like a local file, at djay's playhead.
  Nothing is played from the copy: the audience hears djay's stream. Copies are kept in `.cache/streamed/`, at
  ~70 kbps (enough to analyse). YouTube is asked gently: only for tracks on a deck, one search or download at
  a time, 3 s apart; a track unloaded before its turn is skipped. A first fetch takes ~2–5 s, then the
  quick plan lights it within seconds.

  It needs an internet connection during the show: a track is fetched when it is loaded on a deck. Offline,
  streamed tracks stay dark (a copy fetched before still lights; a fetch that failed for want of a connection
  is tried again 30 s later). Preparing a playlist's tracks before the gig (preloading) is for a later version.

  It downloads from YouTube, which YouTube's terms don't allow and which copyright law may not allow where you
  are: it is off until you switch it on, in the Mac app (Settings ▸ Integrations ▸ Streamed tracks: "Light
  streamed tracks") or with `--opt streamed=1`. One switch for every DJ software: the app saves it in
  `config/integrations.json` (`{"streamed": {"on": true}}`; djay's own `{"djay": {"streamed": true}}` from
  before still counts).

- **VirtualDJ** reports a streamed track as `netsearch://` + a service + its id (`netsearch://sp…`: Spotify).
  Its database (`~/Library/Application Support/VirtualDJ/database.xml`) names it: artist, title and length,
  but no ISRC, so the copy is found by artist and title, its length checked (a length VirtualDJ only guessed,
  a whole number of seconds before it has played the stream, isn't used). `amadeus/show/vdj.py`.
- **Through Amadeus Link** (djay Pro or VirtualDJ on a DJ laptop): Link reads which recording a deck streams
  (djay's library, VirtualDJ's database) and sends it along (`"stream"` in the packet, `"file": ""`); the
  lighting computer fetches the copy itself, when its own switch is on. Nothing is downloaded on the DJ laptop.
- Copies are M4A (AAC): macOS decodes them itself (`afconvert`); ffmpeg is used when it's there (also
  Homebrew's, which an app's PATH doesn't include), and only needed for the few videos that only come as WebM.

### The Accessibility permission

The first time the live show follows djay, macOS asks:

> "Amadeus DMX.app" would like to control this computer using accessibility features.

macOS uses the same wording for every app that asks for this permission, because the permission itself is
broad: an app that has it *can* read what other apps show and *can* click and type in them. Amadeus
DMX uses it to **read**, and only this:

- **Which app:** only djay Pro (an app whose bundle id starts with `com.algoriddim.djay`). No other app's
  window is opened.
- **What:** the text of djay's deck controls, by their VoiceOver labels ("Elapsed time, Deck 1" → `01:07`,
  "Play / Pause, Deck 1" → `Active`, …). No screenshots, no screen recording, no keystrokes.
- **Never:** it doesn't click, type, press buttons or change anything in djay or any other app. The code
  makes three kinds of Accessibility calls only: whether the permission is granted
  (`AXIsProcessTrustedWithOptions`), djay's window (`AXUIElementCreateApplication`) and an element's text or
  label (`AXUIElementCopyAttributeValue`). All of it is in `amadeus/show/sources/djay.py`.
- **When:** only while a live show follows djay. Following VirtualDJ, Mixxx or another DJ software doesn't
  touch it.
- **Where it goes:** the deck state stays on this computer, as with VirtualDJ: into the light show and the
  visualiser feed. On a separate DJ laptop, the Amadeus Link app reads djay the same way (its own reader,
  `mac/Sources/AmadeusLink/DJ/Djay.swift`, with the same three kinds of calls) and passes the decks on; then
  Amadeus Link is the app that needs the permission.

Who gets the permission: macOS grants it to the app that started the engine. In the Mac app that is
**Amadeus DMX**; from the command line it is your terminal app (Terminal, iTerm, …). Every engine
that app starts then has it, so only grant it to an app that runs an engine folder you trust.

Switching it off (System Settings → Privacy & Security → Accessibility) only stops the djay integration: the
next live show with djay says the permission is missing; everything else works as before.

An Amadeus DMX you built yourself (`mac/build-app.sh`) is signed ad hoc, and macOS may see each new
build as a new app: if djay stops being followed after a rebuild, switch the app off and on again in that
list (or remove it with − and start the show again).

## On Windows

The same three integrations, built for Windows and **not yet verified on Windows** (`sources.json` says so in
each entry's `"windows"` block, which the engine applies there and the Windows app can show).

| DJ software | How on Windows | Where it reads |
|---|---|---|
| **VirtualDJ** | the same plugin as a 64-bit DLL: `vdj\build.ps1` (Visual Studio's C++ tools) builds `vdj\build\AmadeusLink.dll`; `-Install` copies it into `Documents\VirtualDJ\Plugins64\SoundEffect` | streamed tracks: `database.xml` in VirtualDJ's home, `Documents\VirtualDJ` (also when Documents moved into OneDrive), else `%LOCALAPPDATA%\VirtualDJ` or `%APPDATA%\VirtualDJ` |
| **Mixxx** | the same mapping and script, over an existing MIDI port called **Amadeus DMX** (WinMM, through ctypes) | the mapping is copied into `%LOCALAPPDATA%\Mixxx\controllers`; the library is `%LOCALAPPDATA%\Mixxx\mixxxdb.sqlite` |
| **djay Pro for Windows** | its window through UI Automation (what Narrator reads), `comtypes`; plus Ableton Link (`aalink`) | `Music\djay\djay Media Library\MediaLibrary.db` (or the macOS bundle name), read only |

### Mixxx's MIDI port

Windows has no way for a program to make a MIDI port of its own on the fly (python-rtmidi's virtual ports
are macOS and Linux only), so the engine opens a port that is already there, by its name, and says how to get
one when there is none:

- **Windows MIDI Services** (in the box from Windows 11 24H2, with the service and its SDK runtime): a *basic
  loopback* endpoint (`MidiBasicLoopbackManager` in the SDK, or MIDI Settings ▸ loopbacks) named
  `Amadeus DMX` gives one input and one output port of that name; what Mixxx sends to the output arrives on
  the input. Its WinMM names are the "new style" names: the endpoint's name, with ` group N` added only when
  ports would otherwise share a name, at most 31 characters. Programs using WinMM (Mixxx through PortMidi,
  and this integration) see these ports, and several programs can open the same port at once. A *paired*
  loopback (A/B) works too, Mixxx on one side and `--opt port="…"` naming the other.
- **loopMIDI** (Tobias Erichsen, free): make a port called `Amadeus DMX`; it loops back the same way.

The engine matches the name exactly or with what Windows adds at the end (`Amadeus DMX 1`, `Amadeus DMX
group 1`). The port must exist before Mixxx starts (Mixxx looks for devices only then); unlike on macOS, the
engine can start after Mixxx. Not verified yet: whether every WinMM name variant of a basic loopback is as
above on a given Windows build.

### djay Pro for Windows and UI Automation

djay Pro for Windows is built from the same code as the Mac version; its controls carry Narrator labels, and
the integration looks for the same words (shared constants in `djay.py`: "Elapsed time, Deck 1", "Play /
Pause, Deck 1", "Crossfader", …). A value comes from the control's Value pattern (the text, as on macOS),
else its Toggle pattern (play and sync: `Active`), its RangeValue pattern (faders as a percentage) or its
text. Whether djay for Windows labels every control exactly as on macOS is not verified yet; if it doesn't,
the show says that djay's window shows no deck controls it knows, and nothing else happens.

The same promise as on macOS, with three kinds of calls, all read-only: find djay's top-level window (by its
title, or its program's name), find its deck controls by their labels (inside the "Decks" group when there
is one), read their values. Nothing is clicked, typed or changed, no other window is read, and no permission
is asked for: UI Automation needs none for a program running as the same user (it can't read a program
running as administrator). Settings and caches of djay itself (`%LOCALAPPDATA%\Packages\…algoriddim…`) are
not read.

### Decoding

M4A copies (and any file libsndfile can't read) are decoded with ffmpeg when there is one (`AMADEUS_FFMPEG`,
then `bin\ffmpeg.exe` next to the engine, which the Windows app may ship, then the PATH), else with Windows'
own Media Foundation (AAC, ALAC, WMA, …; WebM/Opus only with Microsoft's Web Media Extensions). No package to
install for either.

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

1. A module in `amadeus/show/sources/` with a `Source` subclass that calls `self.received([...Deck...])`
   for every reading (`DeckBook` turns readings into decks and events: track loaded, started, stopped, seek,
   loop). Report `phase` on a deck when the DJ software is synced to Ableton Link.
2. An entry in `sources.json`: its module and class, what it needs, how good its position is
   (`exact`, `beat`, `metadata`) and what it has been verified on.
3. `amadeus probe NAME` to see it work and measure it; `--record FILE` keeps a session for
   `--source replay --opt file=FILE`.
