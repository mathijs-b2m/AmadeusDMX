# Third-party notices

Decisive Lightning is MIT licensed (see `LICENSE`). It includes or uses the following.

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

**Butterchurn** and **Butterchurn presets** (MIT, © 2013-2018 Jordan Berg), `web/vendor/`: the LED wall's
MilkDrop-style visuals in the web visualiser. License texts: `licenses/butterchurn-MIT.txt`,
`licenses/butterchurn-presets-MIT.txt`.

## Downloaded when used (not in this repository)

- **QLC+ fixture library** (Apache-2.0): fetched as a sparse git checkout into `.cache/qlcplus` when you
  search it (`decisive library …`, the setup pages).
- **Open Fixture Library** (MIT, https://open-fixture-library.org): fetched into `.cache/ofl` when you
  search it.
- **VirtualDJ SDK headers** (© Atomix Productions): downloaded by `vdj/build.sh` from virtualdj.com to build
  the DecisiveLink plugin; not redistributable, so not included.
- **Python packages** (`pyproject.toml`): numpy, scipy (BSD), soundfile, sounddevice, websockets, pyserial
  (BSD / MIT); optional openai (Apache-2.0), demucs (MIT), beat-this (MIT), torch / torchaudio (BSD).
