# Third-party notices

Amadeus DMX is MIT licensed (see `LICENSE`). It includes or uses the following.

## Included in this repository

**QLC+ fixture definitions** (Apache License 2.0, https://github.com/mcallegari/qlcplus, © the QLC+ authors).
These fixture files were converted from the QLC+ fixture library into this project's format and modified
(channel roles mapped, safe defaults added, laser channels mapped by hand); each file names its source in
`"source"`. The license text is in `licenses/Apache-2.0.txt`.

  - `fixtures/beamz/sb200-stage-blinder.json`
  - `fixtures/chauvet/colorband-pix-m.json`
  - `fixtures/chauvet/intimidator-spot-375z-irc.json`
  - `fixtures/cameo/flat-pro-18.json`
  - `fixtures/cameo/pixbar-600-pro.json`
  - `fixtures/laserworld/cs-1000rgb-mk3.json`
  - `fixtures/martin/atomic-3000-led.json`
  - `fixtures/claypaky/sharpy.json`
  - `fixtures/dts/katana.json`
  - `fixtures/robe/pointe.json`
  - `fixtures/showtec/sunstrip-active.json`
  - `fixtures/martin/mac-encore-performance.json`
  - `fixtures/martin/mac-aura.json`

**The fixture catalogue** (`fixtures/catalog/`): every fixture of the QLC+ fixture library
(`qlcplus.json.gz`, Apache License 2.0, © the QLC+ authors, license text in `licenses/Apache-2.0.txt`) and of
the Open Fixture Library (`ofl.json.gz`, MIT, © 2017 Florian & Felix Edelmann and the Open Fixture Library contributors, license text in
`licenses/open-fixture-library-MIT.txt`), converted into this project's format and modified (channel roles
mapped, safe defaults added, lasers kept dark, smoke machines' output channels mapped). Each file records the
upstream version it was built from (`"upstream"`); `tools/build_catalog.py` rebuilds it.

**Gobo pictures** (`fixtures/catalog/gobos.json.gz`): the gobo images of the QLC+ fixture library
(`resources/gobos/`, Apache License 2.0, © the QLC+ authors) and of the Open Fixture Library
(`resources/gobos/`, MIT, © the Open Fixture Library contributors), rendered small and modified (as the light
each lets through, outside the gobo dark); `tools/build_gobos.py` rebuilds them.

**Butterchurn** and **Butterchurn presets** (MIT, © 2013-2018 Jordan Berg), `web/vendor/`: the LED wall's
MilkDrop-style visuals in the web visualiser. License texts: `licenses/butterchurn-MIT.txt`,
`licenses/butterchurn-presets-MIT.txt`.

## Downloaded when used (not in this repository)

- **QLC+ fixture library** (Apache-2.0) and **Open Fixture Library** (MIT, https://open-fixture-library.org):
  the original libraries, fetched into `.cache/qlcplus` and `.cache/ofl` only to rebuild the catalogue or to
  add a fixture newer than it.
- **VirtualDJ SDK headers** (© Atomix Productions): downloaded by `vdj/build.sh` from virtualdj.com to build
  the AmadeusLink plugin; not redistributable, so not included.
- **Python packages** (`pyproject.toml`): numpy, scipy (BSD), soundfile, sounddevice, websockets, pyserial
  (BSD / MIT), pypdf (BSD); optional openai (Apache-2.0), demucs (MIT), beat-this (MIT), torch / torchaudio (BSD). The apps'
  built-in Python also has aalink (GPL-3.0-or-later, as PyPI lists it; it wraps Ableton Link), on macOS
  python-rtmidi (MIT) and pyobjc (MIT), on Windows comtypes (MIT), zeroconf (LGPL-2.1-or-later, unmodified, as its
  own package) and ifaddr (MIT). Windows decodes M4A with its own Media Foundation, so no FFmpeg is shipped
  unless the Windows build is given one (`FFMPEG_EXE`): then that build's license applies (use an LGPL build).
