# Sets, rigs and placements

Two kinds of files describe your lighting, because they change for different reasons:

| | What it is | How many | File |
|---|---|---|---|
| **Set** | Your gear: the fixtures you own, their DMX mode and address, calibration, where the DMX goes, safety, the decision model | usually one (two while you try things) | `config/sets/<name>.json` |
| **Rig** | A venue: the stage's size, trusses and towers, the LED wall, zones, and where each set's fixtures hang on it | one per venue | `config/rigs/<name>.json` |

A show runs with one set placed on one rig. The active ones are named in `config/active-set` and
`config/active-rig`; commands take `--set NAME` and `--rig NAME` to pick others. A fresh checkout starts with
copies of `examples/sets` and `examples/rigs`. `config/` is not in git: it is yours.

The usual flow (the Mac app's set-up assistant does exactly this):

1. **Make a set**: add your fixtures (the Set page, `amadeus set NAME --new` + `amadeus patch …`, or the setup page).
2. **Make a rig**: from a template (an empty room, two stands, a truss over the booth, a club, a concert stage,
   a round truss),
   then move and add trusses in the rig editor (`amadeus rig NAME --template club`).
3. **Place the set on the rig**: auto-mount (`amadeus rig --automount`, or *Auto-Mount* in the rig editor), or
   drag fixtures onto the trusses: one by one, or a whole group at once.

Mount the same set on another rig and the first rig keeps its placements: each rig remembers, per set, where
every fixture hangs.

## The set file

```json
{
  "description": "My gear",
  "artnet": {"ip": "2.0.0.10", "port": 6454, "fps": 40},
  "output": {"type": "sacn"},
  "safety": {"max_flash_hz": 3, "master": 1.0, "allow_fast_strobe": false},
  "director": "openai",
  "fixtures": [
    {"id": "fuze1", "fixture": "beamz/fuze75b-beam", "mode": "12ch", "universe": 1, "address": 1,
     "pan_invert": true, "pan_home_deg": 360}
  ]
}
```

Per fixture: `id`, `fixture` (the library key, `fixtures/<brand>/<model>.json`), `mode`, `universe`, `address`,
and calibration (`pan_invert`, `tilt_invert`, `pan_home_deg`, `tilt_home_deg`, …). `output` is optional (absent:
Art-Net to `artnet.ip`); see `amadeus/dmx/outputs.py`. `safety.allow_fast_strobe` lets snare rolls and fills flash on
every hit, faster than `max_flash_hz` (each light at most 10 Hz, the lights taking turns); `safety.strobe_free` leaves out every
flash (`amadeus/engine/rolls.py`). `safety.max_fog` (0..1, default 0.7) caps how hazy smoke
machines make the room ([fixture-catalog.md](fixture-catalog.md)).

## The rig file

```json
{
  "description": "Club Rotterdam",
  "stage": {"width_m": 10, "ceiling_m": 7, "room_depth_m": 15, "eye_safety": false,
            "room_volume_m3": 1800, "fog_clear_s": 300},
  "trusses": [
    {"id": "front", "type": "quatro", "length_m": 8.5, "x_m": 5, "y_m": -1.0, "z_m": 4.5},
    {"id": "towerL", "type": "quatro", "length_m": 4, "x_m": 0.3, "y_m": -1.0, "z_m": 2, "vertical": true}
  ],
  "screen": {"width_m": 5.5},
  "zones": [],
  "placements": {
    "my-set": {
      "fuze1": {"truss": "front", "truss_pos_m": -2.4, "truss_side": "under", "mount": "hang",
                "x": 0.26, "y_m": -1.0, "z_m": 4.08}
    }
  }
}
```

`stage.outdoor: true` is an open-air stage: there is no ceiling (`ceiling_m` and the ceiling guard are ignored),
the sky aim goes higher and wider, the directors aim at the sky far more often (the AI is told it is an outdoor
show), and smoke clears in about a minute instead of five. Indoors nothing changes: the ceiling guard keeps
beams off the ceiling.

**Round truss.** A truss with `"shape": "circle"` hangs flat as a full circle, or as an arc of `arc_deg` (180: a
half circle), `diameter_m` across; `x_m`/`y_m` are the circle's centre and the middle of an arc faces the audience
(turned by `rot_deg`). Round truss is sold in a few sizes: the editor offers Ø 2, 3, 4, 5, 6 and 8 m (any other
diameter works). Its `length_m` is the length round the arc and follows the diameter and the arc. A fixture's
`truss_pos_m` is measured round the arc from its middle, to the right seen from the audience; it is turned with the
arc, so its front faces out of the circle, and the truss's `front` face is the outside, `back` the inside.

```json
{"id": "ring", "type": "quatro", "shape": "circle", "diameter_m": 4, "arc_deg": 360, "x_m": 5, "y_m": -2.6, "z_m": 4.5}
```

Moving heads on a ring play it as a circle (`amadeus/engine/rings.py`): they are a group of their own (`ring`),
and the formations take its shape: `fan` is a crown of beams out of the circle, twisting with the movement;
`focus` a cone of beams to one point; `cross` a twisted hourglass; `wave` (and the tilt wave) runs round the ring.
`sync` and `mirror` stay as they are. Pars on a full ring chase round it. Auto-mount spreads fixtures evenly round a
full circle; strobes and blinders stay on a straight truss when there is one.

**Where a truss's heads play.** A horizontal truss can say where the moving heads on it aim: `"aim": "audience"`
(out towards the crowd, never back at the stage: a director's aim at the stage becomes the crowd, and a ring's crown
stays in front of it) or `"aim": "down"` (onto the crowd under it: the director's crowd and stage aims become
straight down, a ring's crown hangs down all round it; an aim at the sky still goes up). Without `aim` it is
automatic: a truss whose centre is at least 1 m in front of the stage edge hangs over the crowd and plays down, any
other plays wherever the director aims. The rig editor sets it per truss (Lights › Aim).

Coordinates are metres: `x` across the stage (a fixture's `x` is a fraction of `stage.width_m`, a truss's `x_m`
is metres), `y` towards the audience (0 = the stage's front edge, the back is negative), `z` height.

A placement's fields: `x`, `y_m`, `z_m`, `mount` (`hang`, `stand`, `floor`), `rot_deg` (turned counter-clockwise
seen from above), `aim` (`[azimuth°, elevation°]`, fixtures without motors), and on a truss `truss`,
`truss_pos_m` (from its centre along it; from its base for a tower), `truss_side` (`under`, `top`, `front`,
`back`) and `mount_roll_deg` (90 on the front face, 270 on the back). A tower has four faces, `front`, `back`,
`left` and `right`: a fixture there hangs off the face (`mount: hang`, `mount_roll_deg: 90`, `rot_deg` turning it
to that face), its base against the truss and its head pointing out; only on `top` of a tower does a fixture
stand. Tower fixtures from before tower faces stood in front of it; they are moved onto the front face when the
rig is loaded. `reverse`, `width` and `group` are
placement fields too. Fixtures on a truss are positioned by `amadeus/rig/trusses.py`; the Mac editor uses the
same rules.

**DMX output.** A set says where its universes go with `"dmx"`: per universe a device from `config/devices.json`
and which of its outputs (`{"1": {"device": "pocket", "output": 1}}`); the devices themselves (`type` artnet,
sacn or enttec_pro, `ip`, `udp_port`, `first_universe`, `outputs`, `priority`, USB `port`/`serial`) are kept apart
from the sets, see `amadeus/dmx/devices.py`. Without `"dmx"` a set uses its own `"output"`/`"artnet"` blocks
(`amadeus/dmx/outputs.py`; an Art-Net output may have a `universe_offset`).

`"artnet": {"lead_ms": 50}`: how far ahead of the music the lights are rendered (default 50 ms), for the time
your lights take to show what they are sent and the DJ software's audio buffer. The beat grid is where the music
is heard; this is the only place the rig's own delay goes.

Zones (`avoid`, `keep_in`, `laser_out`) are explained in `mac/README.md` and `amadeus/engine/zones.py`.

## The combined view

The engine reads one dict: the set's keys, the rig's `stage`, `trusses`, `zones` and `screen`, and each fixture
with its placement fields merged in (`amadeus/rig/store.py`, `compose`). This is also what `GET /api/rig`
returns and `POST /api/rig` takes; saving splits it back into the two files (`split`), keeping the rig's
placements for other sets.

A fixture the rig has no placement for **waits**: it stands in a row on the floor along the front of the stage,
and carries `"_unplaced": {…its waiting spot…}`. If it is saved still standing exactly there, it stays
unmounted; moved anywhere else, that becomes its placement. The engine runs a show with waiting fixtures too
(they light from where they stand).

An old-style file that holds both (fixtures with positions *and* the stage, as sets were before rigs) is
still accepted as `--rig path/to/file.json`; files like that in `config/sets` are split into a set and a rig
of the same name the first time the engine or the Mac app runs.

## Auto-mount

`amadeus/rig/automount.py`, in this order:

1. **Lasers** on top of the back-most high truss, in the middle; else high on the towers (never below 2 m);
   else on stands at the back.
2. **Moving heads** under the overhead trusses (front first, in proportion to their length) or on top of low
   trusses; a fifth on the towers when there are any (the same number on each), stacked from the top; what
   doesn't fit goes on tripods behind the booth.
3. **Strobes** on the front face of the front truss, in the middle; **blinders** on its outer ends.
4. **Bars** on the floor along the front edge; **pars** on the floor at the back, uplighting.

Every row is symmetric and each model is mirrored around the middle. Each model's fixtures take its spots in name
order along the rig, the hang sheet's order (top1 at the first place from stage left, top2 at the next), so names
count along a truss like the places do; *Auto-Mount › Put in Name Order* does the same for a rig mounted before,
on the spots its fixtures already take. Fixtures that are already mounted keep
their place, and their room on a truss is left free.

## Import from a venue's documents

`amadeus rig NAME --import FILE…` builds a set and a rig `NAME` from what a venue sends (`amadeus/rig/importer/`):

- **MVR** (Vectorworks, Capture, grandMA3, Depence): every fixture with its position, the way it hangs and
  points, its GDTF type and mode, and its patch; the drawn trusses. Read as drawn with the audience at the
  bottom of the plan (+Y upstage), the origin at downstage centre on the stage floor.
- **Patch sheets** (CSV, Excel): a header row naming at least the fixture type and its address; mode, universe,
  id, position, quantity and x/y/z columns are used when they are there. "1.141", "1/141", "U1 141" and dimmer
  ranges ("1.013 > 1.019": one conventional light per channel) are understood.

Each type is found in the libraries (ours, QLC+, the Open Fixture Library); a match must name the same model
numbers, and its mode is the one as long as the document's footprint (or the spacing of the patch). Nothing
close: a conventional light plays on one dimmer channel, anything else is made from a generic template.
Hanging fixtures go on the drawn trusses, else on trusses found from their rows; fixtures without a position
are auto-mounted. The report says what was assumed (the frame, the stage size), what is a guess to check (a
near match, a mode the documents don't name, fixed lights pointing at a wall or the ceiling) and what is
missing (no patch).

- **PDFs** (patch lists, the technical rider, light plots) are read with AI and need **your own OpenAI API key**
  (Settings › OpenAI in the app, or `OPENAI_API_KEY` in `.env`); without one nothing is sent and the report
  says so. Every page of every PDF is read: the text pages together (every patched fixture, the modes the notes
  name, the stage's size and heights, house lights left out), each drawing on its own (its plans, the audience
  side, the stage's edges or the hall's walls for the scale, every fixture symbol and its label, the trusses).
  The patch says what the fixtures are; a plan places them, matched by number or address. The scale of a plan
  comes from the sizes the rider gives (the median of what agrees); a plan that doesn't show the stage, like a
  hall plot, gets a rough scale and the report asks to check it. Answers are cached (`.cache/import`), so
  importing the same files again costs nothing.

## Hang sheet

A set designed in the app still has to be hung for real. The hang sheet (`amadeus/rig/hangsheet.py`) is the paperwork for
the crew, one printable HTML page: a plan of the stage from above (the audience at the bottom), per truss and tower a
drawing and a table (which fixture goes where, measured from a named end, on which side, which way round), the
fixtures on the floor and on stands, the DMX patch to set on each fixture, and labels to stick on them. A fixture's
label is where it goes: its truss and its place counted from the stage-left end (`front 3`). Stage left is the
performer's left (x = 0); distances are to the clamp, and being 10–20 cm off doesn't matter: the order along the
truss, the way round and the address do. In the Mac app: the printer button in the rig editor (it prints the layout
as it is, saved or not); on the command line: `amadeus rig --hang-sheet [FILE]`.

**The check after hanging** (the checklist button in the rig editor) lights the fixtures one by one in the sheet's
order and selects each in the view. A moving head points its beam a known way: out in front of it and a little to
its left, down when it hangs (`hangsheet.check_dir`). What the crew sees wrong is put right in the app instead of on
the ladder: the light at another fixture's place swaps the two (their placements trade, their patch and calibration
stay), a beam elsewhere says the head pans the other way (`pan_invert`) or is turned round (its `pan_home_deg` half a
turn on; a head whose tilt is the wrong way round gives the same beam, and the same fix). Undo and Save as usual.

## Setup API

The setup pages and the Mac app use these (all JSON; `?rig=…&set=…` picks a pair other than the active one):

| Request | Does |
|---|---|
| `GET /api/sets` (or `/api/rigs`) | the sets, the rigs, the active ones, the rig templates |
| `POST /api/sets` | `{"active"}` switch · `{"name", "copy"\|"grid"}` create · `{"rename", "to"}` · `{"delete"}` |
| `POST /api/rigs` | `{"active"}` switch · `{"name", "template", "width", "height", "depth", "screen"\|"copy"}` create · `{"rename", "to"}` · `{"delete"}` |
| `GET /api/rig`, `POST /api/rig` | the set on the rig, combined (see above) |
| `GET /api/hangsheet`, `POST /api/hangsheet` | the hang sheet (HTML) of the pair; posted `{"rig": <combined dict>, "names": [set, rig]}`: of that layout |
| `POST /api/hangcheck`, `POST /api/hangcheck/fix` | the check after hanging for `{"rig": <combined dict>}`, step by step; the calibration that puts a head right (`"fixture"`, `"fix"`: `mirrored`, `turned`, `both`) |
| `POST /api/automount` | `{"ids"?, "all"?}` mount and save; with `"rig": <combined dict>` only compute the placements |
