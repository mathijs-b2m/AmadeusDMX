# More fixture sources: what we can ship, what users can import

Investigated 2026-10-21. Today the shipped catalogue (`fixtures/catalog/`) holds 1,781 QLC+ and 657 OFL
fixtures. Five more libraries were checked for format, access and, above all, whether their files may be
converted into the catalogue we ship, or only converted on the user's machine from a file they downloaded.
This isn't legal advice: where a licence is unclear, ask the source before shipping.

| Source | Size | Format | Licence | Ship in the catalogue? | Status here |
|---|---|---|---|---|---|
| DMXControl DDF library | 2,733 files, 1,505 devices | DDF XML (DMXControl 3: one file per mode; DMXControl 2: older XML) | CC BY-SA 4.0 on every file | **Yes**, as its own CC BY-SA data file, with credit | shipped: `fixtures/catalog/ddf.json.gz` (DMXControl 3 files) |
| GDTF Share | ~9,900 devices, 1,234 brands (123 with maker files) | GDTF zip (`description.xml`, DIN SPEC 15800) | terms: personal reference only, no derivative works, no commercial use without a licence | **No**: the user converts their own files | Import GDTF… (Mac, Windows), `amadeus library --gdtf` |
| Avolites personalities | ~22,000 entries | `.d4` XML | no licence shown: Avolites' copyright | No: import a user's file | not started (QLC+'s Apache-2.0 D4 parser could be ported) |
| FreeStyler forum | ~600 topics | `.pff` archive (text `.fxt` + gobo images) | none given (stock phpBB terms) | No | not started; no format spec or parser exists |
| ChamSys MagicQ | 30,000–50,000 heads | `heads.all`, undocumented and binary | "licensed not sold and may not be duplicated" | No | not practical |

## DMXControl DDF: the one we can ship

- **Access.** A public JSON API with no account: `https://ddf.api.dmxc.org/v0/ddfs` lists every file in one
  call (vendor, model, mode, author, licence, DMXControl version, parent), and `/v0/ddfs/{id}/file` returns
  the XML. There is no git repository.
- **What's new.** Matched by name against what we ship, 1,240 of the 1,505 devices aren't in QLC+ or the
  OFL. That over-counts, because names are spelled differently (`LED PAR-56` against `LED PAR-56 RGB`).
  About 550 are DJ brands: Eurolite 144, Stairville 99, ADJ 92, Showtec 61, lightmaXX 57, Cameo 35,
  Varytec 35. Of the 1,240, 725 have a DMXControl 3 file, which is what the converter reads today.
- **Licence.**
  - Every file carries `CC-BY-SA-4.0`.
  - The upload checkbox's link points at CC BY 4.0. BY-SA is the stricter of the two, so following it
    covers both.
  - The 793 old DMXControl 2 files were bulk-uploaded under a "DMXC2-DDF-Archive" account. Whether their
    authors agreed to the licence isn't documented.
  - Shipping means:
    - it becomes its own catalogue file, `fixtures/catalog/ddf.json.gz`, marked CC BY-SA 4.0. The app code
      stays MIT.
    - each fixture keeps its DDF ids and authors (the converter already writes them).
    - the source and licence go into `THIRD_PARTY_NOTICES.md`, with the licence text in `licenses/`.
    - a user's copy of a converted fixture stays CC BY-SA, and the copy says so.
  - Worth a short note to the DMXControl team before the first release that includes it.
- **The format.** `<functions>` says what each channel does: `<position><pan/><tilt/>`, `<dimmer>`,
  `<rgb><red/>…</rgb>` (or `<r/><g/><b/><w/>`), `<strobe>`, `<shutter>`, `<colorwheel>` with
  `<step val="#hex">`, `<gobowheel>` with shake ranges, `<prism>`, `<frost>`, `<zoom>`, `<ptspeed>`,
  `<fog>`, `<matrix>` per cell, and `<raw name="…">` for everything else. Channels count from 0.
- **Safety.** DDFs have no fixture category, so:
  - lasers are found by their words, in the model or channel names: laser, ILDA, X-axis, Y-axis, pattern
    size, drawing.
  - a fixture with nothing the show can dim (only macros, patterns or a wheel, like the ADJ Stinger or the
    beamZ Pandora) is kept dark.
  - `<fog>` makes it a smoke machine that fires only its output.
- **Tried on 154 random DMXControl 3 files.**
  - 151 converted and passed the same patch checks `tests/test_catalog.py` runs on every shipped fixture:
    87 pars, 49 moving heads, 8 pixel bars, 3 smoke machines, 3 lasers and 1 moving bar.
  - The 3 it refuses use HSV colour or a shorthand `<matrix columns=… whiteoffset=…/>` that it doesn't
    read yet.

## GDTF: import the user's own file

- **Terms.**
  - GDTF Share's terms allow downloads "for your personal reference" only, and forbid derivative works
    and commercial use without a licence.
  - The API needs an account. Its docs ask that you send your own customers to sign up for themselves, so
    a shared CI account pulling the whole library goes against them.
  - PrismDMX, another MIT project, reached the same conclusion and ships no GDTF files.
- **How it would work here.**
  - The user picks a `.gdtf` they have, from the manufacturer's site or their own GDTF Share account.
  - It's converted on their machine (`gdtf.add_file`) into their fixtures. Nothing from GDTF enters the
    repo or the app bundle.
- **Optional next step: search GDTF Share in the app.** The user signs in with their own account.
  - Login is `POST /apis/public/login.php`, with a session cookie that lasts 2 hours.
  - `getList.php` returns every fixture: rid, manufacturer, revision, maker or user upload, rating, modes.
  - `downloadFile.php?rid=` returns the file.
  - Maker uploads would be listed first.
- **The format.**
  - `DMXChannel Offset="1,2"` means coarse, then fine.
  - `DMXFrom="128/1"` gives a value with its byte count. The converter scales every value to the
    channel's bytes, then to 8 bits.
  - `ChannelFunction` and `ChannelSet` give the ranges. `Wheel/Slot` gives colours as CIE xyY, which the
    converter turns into sRGB.
  - Each `GeometryReference` with a `Break` is one cell of a pixel bar.
  - A `Laser` geometry makes the fixture a laser, which stays dark. `Fog`/`Haze` attributes make it a
    smoke machine.
  - Only the first colour wheel, gobo wheel, prism and frost are played.
- **Tested on** 6 test fixtures from BlenderDMX and python-gdtf: RGB pars, an RGBW/RGBA par, a beam head with
  two gobo wheels, a wash head and a 16-bit RGB tube. Real manufacturer files still need trying.

## Not pursued

- **Avolites `.d4`.** Worth doing later as a user-import format: QLC+'s `avolitesd4parser.cpp` is
  Apache-2.0. Its own maintainer calls the result rough.
- **FreeStyler `.pff`.** Small and scattered, with no format spec.
- **ChamSys.** Proprietary and undocumented.
- QLC+ won't add GDTF import: the maintainer says it is planned for a closed-source package. OFL has a
  GDTF *import* plugin (GDTF 1.0, everything comes in as "Other"); we convert directly instead.

## Done, and what's next

Done (2026-10-22): the DDF catalogue ships: 900 devices, 714 of them in neither QLC+ nor the OFL, 11 left out
as unreadable (`tools/build_catalog.py --only ddf`, searched after QLC+ and the OFL,
notices and licence text in place), and **Import GDTF…** converts a user's own `.gdtf` on the Mac and Windows
apps' Add Fixtures sheet (`POST /api/fixture/gdtf`) and on the command line.

Next, if wanted:

1. Add DMXControl 2 files (793) and HSV / shorthand matrices.
2. Search GDTF Share in the app with the user's own account (described above).
3. A short note to the DMXControl team about the shipped DDF catalogue, before the first release with it.
