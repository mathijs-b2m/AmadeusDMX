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

1. **Make a set**: add your fixtures (the Set page, `decisive set NAME --new` + `decisive patch …`, or the setup page).
2. **Make a rig**: from a template (an empty room, two stands, a truss over the booth, a club, a concert stage),
   then move and add trusses in the rig editor (`decisive rig NAME --template club`).
3. **Place the set on the rig**: auto-mount (`decisive rig --automount`, or *Auto-Mount* in the rig editor), or
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
Art-Net to `artnet.ip`); see `decisive/dmx/outputs.py`.

## The rig file

```json
{
  "description": "Club Rotterdam",
  "stage": {"width_m": 10, "ceiling_m": 7, "room_depth_m": 15, "eye_safety": false},
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
placement fields too. Fixtures on a truss are positioned by `decisive/rig/trusses.py`; the Mac editor uses the
same rules.

Zones (`avoid`, `keep_in`, `laser_out`) are explained in `mac/README.md` and `decisive/engine/zones.py`.

## The combined view

The engine reads one dict: the set's keys, the rig's `stage`, `trusses`, `zones` and `screen`, and each fixture
with its placement fields merged in (`decisive/rig/store.py`, `compose`). This is also what `GET /api/rig`
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

`decisive/rig/automount.py`, in this order:

1. **Lasers** on top of the back-most high truss, in the middle; else high on the towers (never below 2 m);
   else on stands at the back.
2. **Moving heads** under the overhead trusses (front first, in proportion to their length) or on top of low
   trusses; a fifth on the towers when there are any (the same number on each), stacked from the top; what
   doesn't fit goes on tripods behind the booth.
3. **Strobes** on the front face of the front truss, in the middle; **blinders** on its outer ends.
4. **Bars** on the floor along the front edge; **pars** on the floor at the back, uplighting.

Every row is symmetric and each model is mirrored around the middle. Fixtures that are already mounted keep
their place, and their room on a truss is left free.

## Setup API

The setup pages and the Mac app use these (all JSON; `?rig=…&set=…` picks a pair other than the active one):

| Request | Does |
|---|---|
| `GET /api/sets` (or `/api/rigs`) | the sets, the rigs, the active ones, the rig templates |
| `POST /api/sets` | `{"active"}` switch · `{"name", "copy"\|"grid"}` create · `{"rename", "to"}` · `{"delete"}` |
| `POST /api/rigs` | `{"active"}` switch · `{"name", "template", "width", "height", "depth", "screen"\|"copy"}` create · `{"rename", "to"}` · `{"delete"}` |
| `GET /api/rig`, `POST /api/rig` | the set on the rig, combined (see above) |
| `POST /api/automount` | `{"ids"?, "all"?}` mount and save; with `"rig": <combined dict>` only compute the placements |
