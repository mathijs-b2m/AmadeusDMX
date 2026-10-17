# Safety

Amadeus DMX is built to be safe by default. These are the layers, from the flash limit to the laser guard. How they sit in the code: [architecture.md](architecture.md#safety-layers).

- **Flash limit:** white flashes and the software strobe go through one timeline capped at `max_flash_hz` (3 Hz, the photosensitive-epilepsy guideline). Fixture strobe channels are never driven.
- **No fast strobe:** no light flashes faster than `max_flash_hz` (3 Hz, the photosensitive-epilepsy guideline); nothing chops along with the music. The one exception is opt-in: with `allow_fast_strobe` snare rolls and fills flash on every hit, each light at most 10 times a second. Warn an audience about strobe effects anyway.
- **Strobe-free:** `safety.strobe_free` (setup page: *Strobe-free*) leaves out every flash: the strobe fixtures stay dark, there are no white flashes on the big hits, and snare rolls build in steady steps. Only the single hit on a drop remains.
- **Eye safety:** `stage.eye_safety` (off by default; turn on for lasers or very bright beams) keeps beams towards the audience out of eye height, and heads go dark while crossing that band.
- **High-output fixtures (beta):** this is beta software, not for a powerful rig in front of a real audience. Fixtures of risk group 2 or 3 (IEC 62471: `physical.risk_group` in the fixture file, from the manual or label) stay dark when the DMX goes to real lights; the visualiser still shows them. Without a rating a fixture counts as one when it packs a lot of light into a narrow beam (≥ 5,000 lm per beam and ≥ 200 lm per square degree: a Sharpy or a Pointe, not a Fuze, a Katana or a wash). Consumer lights play as usual, the audience included.
- **No single point:** focus and cross looks aim the heads around a spot about 1.5 m wide instead of all into one point, and the cinematic "all on the DJ" picture rings the light above the DJ's head.
- **Zones:** draw keep-out, keep-in and laser safety zones in the rig editor (Mac app). Keep-out zones are physical stops for the head motors: a beam never sweeps into them.
- **Laser guard:** the last step of every frame. A laser pattern that would enter a laser zone is raised, then shrunk, then blanked. With real lights, a set with lasers needs at least one laser zone or its lasers stay dark. This is a software layer on top of the laser's masking plate, scan-fail safety and E-stop, never a replacement.
- **Brightness limiter:** for testing and setting up without eye strain, a ceiling on every light, shared by the show, the light test, Identify and the setup tools. It limits rather than scales (at 70 % a light at 50 % stays at 50 %) and is impossible to miss: the app shows it in its toolbar and a striped banner on every page, and it starts at 100 % each time the app opens.
- **Smoke:** `safety.max_fog` caps how much haze the show makes; bursts are sized to the machine's output and the room's volume.
- **`master`** scales every dimmer.

Lighting can hurt people: strobes and flashes can trigger seizures, and lasers can blind. The safety
features here are aids, not guarantees; you are responsible for your rig and your audience.
