# Amadeus DMX for Windows

Native Windows ports of the Mac apps (WinUI 3 + Direct3D 11) on top of the same Python engine: **Amadeus DMX**
and **Amadeus Link**, the DJ laptop's companion. How the port is built, and the Mac → Windows mapping:
[PORTING.md](PORTING.md).

```
windows/
  build.ps1              builds both apps into build\ (and the installers)
  bundle-engine.ps1      puts the engine and its own Python beside the app (a release)
  installer/             Inno Setup scripts (AmadeusDMX.iss, AmadeusLink.iss, common.iss), signing, the update feeds
```

## Build and install

```powershell
./build.ps1                       # build\AmadeusDMX\AmadeusDMX.exe, running the engine from this checkout (its .venv)
./build.ps1 -Release              # the app people download: the engine and its own Python beside the exe
./build.ps1 -Release -Installer   # … and build\AmadeusDMX-Setup-<version>.exe, build\AmadeusLink-Setup-<version>.exe
./build.ps1 -Installer -NoBuild   # only the installers, from what's in build\ (release.yml signs the apps in between)
```

Needs Windows 10 22H2 or 11 (x64), PowerShell 7 and the .NET 10 SDK; `-Release` also uv
(`winget install astral-sh.uv`), `-Installer` Inno Setup 6 (`winget install JRSoftware.InnoSetup`). `-Version 1.2.3`
sets the version people see (default `0.1.<commits>`); the build number is always the commit count, so every
later build is newer (what the updater compares). The VirtualDJ plugin goes in when `vdj\build\AmadeusLink.dll`
is there (`vdj\build.ps1`).

Each build writes an `appsettings.json` beside the exe, which the app reads and never writes:

| Key | When |
|---|---|
| `AmadeusEngineRoot` | a development build: the checkout it runs the engine from |
| `UpdateFeedUrl`, `UpdatePublicEdKey` | a release with `$env:FEED_URL` (see [Updates](#updates)) |

## Releases

A release needs nothing installed: `bundle-engine.ps1` puts a standalone Python (python-build-standalone, via uv,
the same version as the Mac app's) with `requirements-app.txt` in `runtime\`, and the engine (package, web UI,
fixtures, examples, Mixxx mapping, VirtualDJ plugin) in `engine\`, compiled once (the program folder is never
written to). `$env:FFMPEG_EXE` adds that ffmpeg as `engine\bin\ffmpeg.exe`. The optional packs (instrument
analysis, streamed tracks) are not inside: as on the Mac they go into an environment of their own in your data
folder.

**Instrument analysis and the graphics card.** PyTorch from PyPI runs on the processor on Windows: Demucs takes
one to a few minutes a track (a 3:25 track: 3.5 minutes on 4 emulated x64 cores), beside the show. With an NVIDIA
card (seen with `nvidia-smi`, which comes with the driver) the pack installs PyTorch's CUDA build from
download.pytorch.org instead: `cu130` with driver 580 or newer and a GeForce 16/20 or later, else `cu126` (driver
528+, older cards; not RTX 50, which needs the newer driver). The CUDA libraries are inside it, so the pack grows
from about 1 GB to about 4–5 GB (a 1.9–2.5 GB download). Settings › General › Optional packs says which one it
will install. When the card can't separate a track (out of memory, a driver too old for the build) that track
goes to the processor, and the background process's last line names the device it ran on. Not used:
torch-directml (any DirectX 12 card) has no wheels past Python 3.12 / torch 2.4; AMD has no Windows build of
PyTorch for Python 3.14 on PyPI or PyTorch's index; Intel's XPU build (Arc, Core Ultra; 1.4 GB with its
runtime) is untried, so only on request: `amadeus packs install instruments --torch xpu`. The instrument models
(ONNX) stay on the processor: a track takes about a second there, and onnxruntime-directml (1.24) would replace
onnxruntime 1.31. **Unverified:** the CUDA and XPU builds on real hardware, and how long a track takes on them
(the VM has no GPU).

The installer puts the app in `C:\Program Files\Amadeus DMX` for everyone (asks for admin), or, chosen in its
first dialog, in `%LOCALAPPDATA%\Programs\Amadeus DMX` for you alone. It adds a Start menu entry and, if you
like, a desktop icon, closes a running app before an upgrade, and replaces `engine\` and `runtime\` whole.

**On GitHub:** push a tag (`git tag v0.3.0 && git push origin v0.3.0`). `.github/workflows/release.yml` builds
the Mac and the Windows apps side by side; once both are done, one **draft** release carries the disk images,
the installers, every update feed and one `SHA256SUMS.txt`; you publish it on GitHub. Actions › Release ›
*Run workflow* makes the same builds as workflow artifacts only.

## Signing and SmartScreen

There is no Windows certificate yet, so a release is **unsigned** (the workflow warns). Then SmartScreen stops
the downloaded installer: *Windows protected your PC* › *More info* › *Run anyway*, and the browser may call it
uncommon. The app itself then runs normally. Signed, the warning goes away once the certificate has reputation
(at once for Azure Trusted Signing and EV certificates, after enough downloads for others). Smart App Control,
where it's on, may refuse unsigned programs altogether.

release.yml signs the apps (`AmadeusDMX.exe`, `AmadeusLink.exe`), the engine's `python.exe` / `pythonw.exe`
and venv launchers, then the installers, with the first that is set up:

| Secrets | Signing |
|---|---|
| `WINDOWS_SIGN_ENDPOINT`, `WINDOWS_SIGN_ACCOUNT`, `WINDOWS_SIGN_PROFILE`, `WINDOWS_SIGN_TENANT_ID`, `WINDOWS_SIGN_CLIENT_ID`, `WINDOWS_SIGN_CLIENT_SECRET` | **Azure Trusted Signing** (`azure/trusted-signing-action`): the endpoint (e.g. `https://weu.codesigning.azure.net/`), the account and certificate profile, and an app registration with the *Trusted Signing Certificate Profile Signer* role |
| `WINDOWS_PFX_BASE64`, `WINDOWS_PFX_PASSWORD` | a code-signing certificate (`base64 -i cert.pfx`) with signtool (`installer/sign.ps1`) |

A self-signed certificate (like the Mac's `release-keys.sh` one) does nothing for SmartScreen. The uninstaller
Inno Setup writes is not signed (it isn't downloaded, so SmartScreen never sees it).

## Updates

Both apps update themselves with [NetSparkleUpdater](https://github.com/NetSparkleUpdater/NetSparkle), which
reads Sparkle's feed format, signed with **the same update key** as the Mac apps (`SPARKLE_PRIVATE_KEY`, public
half `mac/Resources/sparkle-public-key.txt`):

- **The feeds** are `appcast-windows.xml` (Amadeus DMX) and `appcast-link-windows.xml` (Amadeus Link) on the newest
  published GitHub release (`releases/latest/download/…`), each with a `.signature` of its own (NetSparkle's
  strict mode). release.yml makes them with `installer/appcast.py`, which checks every signature against the
  public key before writing it. The enclosure is the installer (`sparkle:os="windows"`); `sparkle:version` is
  the build number, `sparkle:shortVersionString` the version.
- An update runs the new installer silently (`/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART`) once the app has quit.
- As on the Mac: opt-in, never during a show, prereleases don't reach people, and your data is never touched.

Development builds have no feed and don't update. To try the feeds locally:

```bash
uv run windows/installer/appcast.py --key-file ~/.amadeus-release/sparkle-private-key.txt feed \
  build/AmadeusDMX-Setup-0.3.0.exe -o build/appcast-windows.xml --version 0.3.0 --build 412 \
  --url-prefix https://github.com/OWNER/REPO/releases/download/v0.3.0/
uv run windows/installer/appcast.py verify build/appcast-windows.xml build/appcast-windows.xml.signature
```

## Amadeus Link and the DJ software

Link passes VirtualDJ on through its plugin (UDP 127.0.0.1:9123; *Install* in Link's window copies
`vdj\AmadeusLink.dll` into `Documents\VirtualDJ\Plugins64\SoundEffect`), and reads djay Pro and Mixxx itself.
What they read becomes the plugin's packets (`AmadeusKit/DJ`, tested on a Mac against the engine's values and its
receiver); the Windows parts are in `AmadeusLink/DJ`.

- **djay Pro for Windows:** its window through UI Automation (`UiaWindow.cs`), read-only: djay's own top-level
  window (by its program's name, or a Store frame titled "djay…"), the deck controls by the engine's Narrator
  labels ("Elapsed time, Deck 1", …), their values through UI Automation's get calls only. No permission needed.
  Its library: `Music\djay\djay Media Library\MediaLibrary.db` (or the macOS bundle name), read only.
  **Not verified on Windows yet:** that djay for Windows labels its controls exactly as on macOS.
- **Mixxx:** Link copies the mapping (`mixxx\` beside the exe) into `%LOCALAPPDATA%\Mixxx\controllers` and reads
  the script's SysEx from a MIDI port called **Amadeus DMX** with WinMM. Windows has no CoreMIDI-style virtual
  ports, so Link uses, in this order: a port of that name that is already there (`Amadeus DMX`,
  `Amadeus DMX 1`, `… group 1`); else a **Windows MIDI Services basic loopback** it makes itself; else it says to
  make one in loopMIDI (with a link to it). Start Mixxx after the port exists.

### Windows MIDI Services (findings, October 2026)

- The API is `Windows.Devices.Midi2`. Its metadata was locked in *In-box Preview 11*; Windows carries it from
  Windows 11 25H2 (24H2 is not supported). There is no package on nuget.org and no prebuilt .NET projection:
  the preview NuGet (GitHub releases) has only the `.winmd` and an app-local DLL under a go-live licence. Link calls it through WinRT's ABI by hand
  (`MidiServices.cs`, interface ids from that `.winmd`) and uses only the copy Windows itself has.
- A **basic loopback** (`MidiBasicLoopbackManager.CreateTransientLoopback`) is one MIDI 1.0-style endpoint:
  Microsoft's sample says it "shows up in the MIDI 1.0 port list that older applications see", so WinMM programs
  (Mixxx through PortMidi, and Link) see an input and an output of its name, and several programs can open it
  at once. It is *transient*: it lasts until the MIDI service or Windows restarts, so Link leaves it there (Mixxx
  keeps its port when Link restarts) and makes it again only when `DoesLoopbackExist` says it's gone.
- **But the basic loopback transport isn't in the box yet:** it comes with the separate preview *Windows MIDI
  Services Transports* installer (with the RTP-MIDI, Network MIDI 2.0 and BLE transports). Without it,
  `IsTransportAvailable` is false and Link falls back to loopMIDI. (A MIDI 2.0 loopback *pair*, A/B, would need
  Mixxx on one side and Link on the other; Link doesn't make those.)
- **Not verified on Windows yet:** the WinMM names a basic loopback gets ("new style" names: the endpoint's name,
  " group N" only when ports would share one, at most 31 characters), and that its loopback reaches WinMM inputs.

## Your data

Sets, rigs, settings, `.env`, fixtures you added or calibrated, the packs and the cache live in
`%LOCALAPPDATA%\Amadeus DMX` (not roaming: the cache is big). Installing, updating or uninstalling never touches
it; delete that folder yourself to start over.

## Windows Firewall

An install for everyone adds these rules (inbound, from the local subnet only), replaced on every upgrade and
removed by the uninstaller:

| Rule | Program | Allows |
|---|---|---|
| `Amadeus DMX engine` | `runtime\python.exe`, `runtime\pythonw.exe` | UDP: Art-Net replies (6454), sACN (5568), Ableton Link (20808), Amadeus Link's deck state |
| `Amadeus Link` | `AmadeusLink.exe` | TCP 7123 (pairing, tracks), UDP 9123 (the VirtualDJ plugin) |

The visualiser feed (8765) and the setup service (8181) listen on 127.0.0.1 only and need no rule. An install
for you alone can't add rules: Windows asks the first time the engine or Link listens (allow *Private
networks*, and *Public* too if the gig network is one). Cancel that prompt, or allow Private only on a network
Windows calls Public, and Windows writes inbound *Block* rules for the program. Both apps look for those
(`AmadeusKit/Firewall.cs`, through HNetCfg.FwPolicy2): Amadeus Link says lighting computers can't pair, and
Amadeus DMX, paired with a DJ laptop, says the decks are kept out. Each offers *Allow…*: after Windows's
administrator prompt it replaces the program's inbound rules with the rules above.

## Uninstall

Settings › Apps › Installed apps › Amadeus DMX (or Amadeus Link) › *Uninstall*. It removes the program folder,
the shortcuts and the firewall rules; your data folder stays.
