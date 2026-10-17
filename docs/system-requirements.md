# System requirements

What Amadeus DMX needs to run, and what we recommend for a smooth night with every feature on. The short
version is in the [README](../README.md#system-requirements).

## Mac

| | Minimum | Recommended |
|---|---|---|
| **Mac** | Any Mac with Apple Silicon (M1 or later) | M1 Pro / M2 or later; a Pro or Max chip for big rigs (50+ moving heads, lasers) shown in 3D |
| **macOS** | macOS 26 | macOS 26, kept up to date |
| **Memory** | 8 GB | 16 GB or more, especially with instrument analysis |
| **Free disk space** | 1 GB for the app and its engine | 5 GB plus about 50 MB per track you play with instrument analysis on |
| **Network** | Wi-Fi to a DMX node, or a USB DMX interface | **Wired Ethernet** to the DMX node (a USB-C Ethernet adapter is fine) |
| **Internet** | For installing, updates and the optional packs | During the show for the AI director (OpenAI) and Spotify tracks |

An Intel Mac can't run the app.

## Windows

| | Minimum | Recommended |
|---|---|---|
| **PC** | 64-bit (x64) processor, 4 cores | 6 cores or more |
| **Windows** | Windows 10 22H2 or Windows 11 | Windows 11, kept up to date |
| **Memory** | 8 GB | 16 GB or more, especially with instrument analysis |
| **Graphics** | DirectX 10 (feature level 10.0) | DirectX 11; an **NVIDIA GeForce GTX 16 / RTX 20 series or newer** with driver 580 or later for instrument analysis on the card |
| **Free disk space** | 1 GB for the app and its engine | 10 GB plus about 50 MB per track you play with instrument analysis on (the NVIDIA version of the pack is 4–5 GB) |
| **Network** | Wi-Fi to a DMX node, or a USB DMX interface | **Wired Ethernet** to the DMX node |
| **Internet** | For installing, updates and the optional packs | During the show for the AI director (OpenAI) and Spotify tracks |

Windows 11 on ARM PCs run the x64 app through Windows' emulation: slower, and so far only tried in a virtual
machine. Older NVIDIA cards (driver 528 or later) get an older version of the pack. On AMD or Intel
graphics, instrument analysis runs on the processor.

## What uses what

Measured on a MacBook Pro with an M3 Max (16 cores, 128 GB) on a 6:51 house track and the concert example rig
(60 moving heads, 10 lasers, an LED wall). Smaller machines take longer; the show itself stays light.

| Task | When | Time | Memory (peak) |
|---|---|---|---|
| **Analysing a track** (beats, bars, phrases, drops) | once per track, when it's loaded | 4.5 s | 1.6 GB |
| **Instrument analysis** (optional pack: separating and recognising the instruments) | once per track, beside the show | 16 s on the Mac's graphics | 4.7 GB |
| **The AI director** (OpenAI) | once per track, phrase by phrase | about 1.3 s per phrase, over the internet | small |
| **The show engine** (40 frames a second, 60 heads) | the whole show | about 10 % of one core | 0.9 GB |
| **The app and the 3D stage** | the whole show | 20–25 % of one core, about 10 % of the graphics | a few hundred MB |

- **Instrument analysis is the heavy part.** It runs in the background and only once per track (the result is
  kept), but it needs memory: with 8 GB, close other apps or leave the pack out. On a Windows PC without an
  NVIDIA card it runs on the processor, about **one to a few minutes per track** (3.5 minutes for a 3:25 track on
  4 cores). Tracks you prepare before the gig are ready at once.
- **The 3D stage is the next biggest.** On a smaller machine, or at a gig, switch **Settings › General ›
  Mode** to **Perform Only**: the lights run exactly the same, without drawing the stage.
- **A local AI director** (Ollama, instead of OpenAI) runs on your own computer: about 7–8 seconds per phrase on
  an M3 Max, and it needs the memory of the model on top. In a live show the rule-based plan plays until it's
  ready.

## DMX hardware

- **Art-Net or sACN nodes**: any node on the same network as the computer. Wired Ethernet keeps the timing
  steady; Wi-Fi works for a living room. A network switch between the computer and the node is fine.
- **USB DMX interfaces**: ENTTEC DMX USB Pro / Pro Mk2, DMXking ultraDMX, Eurolite USB-DMX512-PRO and other
  Pro-compatible interfaces (one universe each).
- **Fixtures**: any DMX fixture. About 2,400 are built in (the QLC+ and Open Fixture libraries), and the rest
  can be mapped by hand in the app.

## Amadeus Link (the DJ laptop)

Amadeus Link is small: it reads the DJ software and passes it on. Any Mac with Apple Silicon and macOS 26, or a
Windows 10 22H2 / 11 PC, that runs your DJ software runs Amadeus Link too. The DJ laptop and the lighting
computer need to be on the same network; a wired connection or a dedicated router is best at a gig.
