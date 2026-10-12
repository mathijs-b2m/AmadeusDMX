# Decisive Lightning ⚡

AI-directed sound-to-light for DJs. Tracks are analysed (beats, bars, phrases, drops, build-ups, synth stutters and riffs), a **decision model** designs a layered light show per musical phrase, and a real-time engine drives moving heads, pars, strobes and lasers over **Art-Net, sACN or a USB DMX interface**, beat-locked. It works on recorded tracks and **live in VirtualDJ**, following the mix as you play, on the DJ's computer or on a separate lighting computer.

There is a 3D visualiser in the browser and a native **Mac app** (`mac/`) with a Metal stage, a rig editor and a set-up assistant.

Your lighting is described in two parts: a **set** (your fixtures: what you own and how it's patched) and a **rig** (a venue: the stage and the trusses). You make a set once, make a rig per venue, and mount the set on it: automatically or by dragging fixtures onto the trusses. See [Sets and rigs](#sets-and-rigs).

```
                      ┌─────────────── per track, ahead of time ───────────────┐
 audio (WAV/MP3/M4A) ─► analysis ─────────► director ─────────────► plan per phrase
                        beats, bars,         decision model picks     section + palette +
                        phrases, drops,      section, palette and     look layers
                        stutters, riffs      look layers (+ safety
                                             nets: drops, variety…)
                      └────────────────────────────────────────────────────────┘
 position in the track ─► engine (40 fps) ─► DMX ─► node / USB ─► fixtures
 (audio clock, or VirtualDJ   kick pumps, beat-landed moves,      └► 3D browser visualiser
  via the DecisiveLink plugin) drop moment, kick-led light…   
```

**The AI chooses the look; it never triggers individual hits.** Choices are made once per phrase (4–16 bars). Everything time-critical (kick pumps, flashes, beat-locked head moves, the drop hit, synth stutters) comes from the analysis, so it's exact to the beat.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[openai]"         # add ",ml" for instrument separation (Demucs, ~2 GB), ",usb" for USB DMX
echo 'OPENAI_API_KEY=sk-...' > .env          # optional: only for the OpenAI decision model
.venv/bin/decisive play "track.mp3"          # the visualiser only: http://localhost:8080
.venv/bin/decisive setup                     # http://localhost:8080/setup.html: fixtures, node, decision model
.venv/bin/decisive play "track.mp3" --dmx    # … and the real lights
```

The first run starts with the examples (`examples/`): a showcase set of popular fixtures on a club rig, and
60 moving heads with lasers on a concert stage. Your own sets and rigs live in `config/` (not in git).

**Mac app:** `cd mac && ./build-app.sh --install` (see `mac/README.md`).

Open **http://localhost:8080** for the 3D visualiser (stage, the decision per phrase with confidences and the exact prompt, energy curve with ⚡ drops) and **/setup.html** for the setup page.

For VirtualDJ: see [Live in VirtualDJ](#live-in-virtualdj).

## Commands

| Command | What it does |
|---|---|
| `decisive play TRACK [--dmx [IP]] [--mute] [--start SEC] [--tempo half\|double] [--director …] [--style GENRE]` | Play a track with lights and visualiser (audio-clocked). Blackout on Ctrl+C |
| `decisive live [--dmx [IP]] [--director …] [--remote dj:NAME --code NNNN]` | Follow a VirtualDJ mix via the DecisiveLink plugin, on this computer or on a DJ laptop (Decisive Link) |
| `decisive setup` | Web setup page only (no show) |
| `decisive genre TRACK [GENRE\|auto]` | A track's genre (one word) and where it came from; set your own, or back to automatic |
| `decisive analyze TRACK [--tempo half\|double]` | Audio analysis only (cached in `.cache/`) |
| `decisive direct TRACK [--director …] [--style GENRE] [--redo]` | Build and print the show plan (`--style`: in another genre's house style) |
| `decisive library` | List fixture definitions; `decisive library beamz fuze` searches QLC+ and the Open Fixture Library too, `--add <key>` adds a result |
| `decisive patch MODEL[:COUNT] …` | Patch fixtures into the active set, assign addresses |
| `decisive discover [--write] [--readdress] [--sim]` | Find the Art-Net node (and RDM fixtures) on the network |
| `decisive test` | Hardware bring-up: each fixture on its own, then head orientation calibration |
| `decisive gobos FIXTURE` | Project the gobos one by one and name them |
| `decisive colors FIXTURE` | Show the colour wheel slot by slot and name the colours |
| `decisive motion FIXTURE [--axis pan\|tilt]` | Measure how fast a moving head really swings on the beat |
| `decisive simnode MODEL[:COUNT],…` | Simulated Net-2/5 with virtual (RDM) fixtures, decodes incoming DMX |
| `decisive set [NAME] [--new \| --copy-of SET]` | Your fixtures: list, switch or create sets |
| `decisive rig [NAME] [--template T] [--automount [--all]]` | The venue: list, switch or create rigs (templates: floor, stands, booth, club, stage); mount the set on it |
| `decisive monitor` | Watch VirtualDJ and the engine: CPU, memory, threads, GPU, crashes |
| `decisive probe [NAME] [--emit 127.0.0.1:9123]` | Other DJ software (Mixxx, djay Pro, …): list, watch and measure one, or pass it to the Decisive Link app |
| `decisive instruments [TRACK] [--download]` | The instrument models (non-commercial license) and a track's instruments over time |
| `decisive synctest make` / `listen` | A test track with beeps, and a listener: how far the show is from the music you hear |

(`decisive` = `.venv/bin/decisive`, or `python -m decisive`.) `--dmx` without an IP uses the node from the rig. Audio formats: WAV, MP3, FLAC, OGG, AIFF directly; M4A/AAC is decoded once with ffmpeg.

## Live in VirtualDJ

The **DecisiveLink** plugin (`vdj/`) runs as a master effect, leaves the audio untouched, and streams the mix state 25 times per second over UDP `127.0.0.1:9123`: per deck the file, position, play state, BPM, original BPM and volume (fader × crossfader), plus the master deck.

```bash
./vdj/build.sh --install                      # downloads the SDK headers, builds an arm64 bundle, installs it
.venv/bin/decisive live --dmx
```

Restart VirtualDJ, then enable **DecisiveLink** as a **master** effect. Works with VirtualDJ 8.5 Home (free) on Apple Silicon.

**DJ and lighting on different computers:** run the small **Decisive Link** app (`mac/`) next to VirtualDJ on the DJ's laptop; it shows a 4-digit code. On the lighting computer: `decisive live --dmx --remote auto --code 1234`, or *Start with a DJ Laptop…* in the Mac app. Deck state is clock-synced (a few ms) and tracks are fetched once over the network. See [docs/protocols.md](docs/protocols.md).

- **Every deck plays its own pre-analysed show** at exactly the position VirtualDJ reports, so seeks, loops, pitch changes and cuts are followed.
- **A new track** is analysed as soon as it's loaded (a few seconds) and gets an instant rule-based plan. The decision model's plan replaces it when ready.
- **Mixing:** brightness and colour blend by deck volume. The moving heads follow the dominant deck, switching only when the other deck is clearly louder (20% margin, no flapping).
- **Robustness:** mirrored decks (VirtualDJ reports non-existent decks as copies on master effects) are dropped. A deck that's "playing" but whose position doesn't move counts as stopped. No packets for 1 s → lights dark.
- The plugin keeps its VirtualDJ queries low (~230/s: only real decks; file, length and original BPM twice per second).

**Known VirtualDJ issue (not the plugin):** on macOS the VDJ interface can freeze after switching apps while audio keeps running. Workarounds from the VDJ forums: set the display to 60 Hz instead of ProMotion, avoid Stage Manager or toggle Full Screen/Windowed, try `experimentalUseMetal` or `skinFps` in VDJ's options.

## Is the show in sync?

`decisive synctest make` writes a test track (128 BPM, three minutes, with a build-up and two drops) to
`~/Music/Decisive Lightning/`, with a short 3.15 kHz beep on the downbeat of every fourth bar. Load it in the DJ
software, start the live show, play it, and run `decisive synctest listen`: the Mac's microphone hears each
beep, the show's feed says where the show was at that moment, and since each beep's place in the track is known
the difference is how far the show is from the music **as you hear it** (DJ software, its audio buffer,
speakers and room included), with the light lead (`artnet.lead_ms`) taken out. It prints each beep and then the
offset, its spread and any drift per minute. The analysis gets this track exactly (a test checks tempo, beats,
bar lines and drops), so an offset here is the live timing, not the analysis.

The live show also writes `.cache/live.log`: everything it prints with clock times, and at every phrase change
the position the DJ software reported next to the position the show plays.

## Other DJ software

Live mode also follows **Mixxx** and **djay Pro**: `decisive live --source mixxx` or `--source djay`, or
Start ▸ *Start Live Show (…)* in the Mac app. `decisive probe` lists the integrations and measures one.
djay is read from its window, which needs macOS's **Accessibility** permission: Decisive Lightning only
*reads* djay's deck labels with it, never clicks or types. What each integration does, needs and has been
tested on, and exactly what that permission is used for: [docs/dj-software.md](docs/dj-software.md).

## Genres and programs

Every track gets a **genre**, one word (cinematic, classical, ambient, edm, house, techno, trance, psytrance, hardstyle, dnb, dubstep, hiphop, rnb, pop, rock, metal, latin, funk, jazz), shown with the track in the app and the visualiser:

1. **your choice** (`decisive genre TRACK GENRE`, kept in `config/genres.json`);
2. the **Decisions API**, given the artist and title (from the file's tags, or its name), when there's a key and it is reasonably sure (30% with the artist known: torn between pop and edm for Coldplay is still far better than a tempo guess). A title alone ("Symphony") has to be very sure, and a beat-less genre (cinematic, classical, ambient) only counts when the audio has no groove either;
3. a **genre tag** in the file;
4. the **audio**, as the fallback: how much of the track grooves (the same rhythm bar after bar, in the low end or the highs). Club tracks groove for 55–100% of their length, film scores for ~15%; the tempo names the family.

### A house style per genre

Every genre has a **style sheet** ([decisive/director/style.py](decisive/director/style.py)), so tracks that share a genre look like one show instead of each getting its own random mood. A sheet says:
- which palettes the genre uses (techno: cool, ice and fire; hip-hop: gold and purple; rock: a white and amber `stage` look);
- which looks don't fit it (no spinning prisms or colour cycling in techno, no strobing light in jazz or ambient, no soft fades in hardstyle);
- what to use instead;
- a few lines describing the style.

A style is a **lean, not a rule**: the genre sets the colours, and the music of each part decides the moves, because a song is not one genre all the way through (a piano ballad part, then a mainstage drop).
- The **rule director** uses the genre's palettes everywhere. It swaps a look's misfits only in the grooves, the body of a genre; intros, breakdowns, buildups and drops follow their own music.
- The **decision models** get the genre's palettes as their colour choices. The rest of the style is a lean in the prompt, and every move and light stays open.

The song's arc and the drop rules have the last word. A style describes looks, not fixtures, so it works on any rig. Tracks without a genre are directed as before.

**The set's genre (live).** A genre guessed from the audio alone is noisy: one such track must not flip the style for one song. In a live set, a guessed track is lit in the set's style, and the app shows it as `POP → HOUSE`; a new genre takes over after **two tracks in a row**. A track whose genre is known (your choice, the Decisions API from its artist and title, its tag) keeps its own style: a Coldplay song in a techno set is still pop. A cinematic track plays its own program and leaves the set's genre alone. For a single track, `--style GENRE` lights it in another genre's style.

### Themes from the title

A title can carry a theme with a look of its own ([decisive/director/themes.py](decisive/director/themes.py)). A track about **stars** ("A Sky Full of Stars", "Starlight", "Galaxy") gives the director a **starfield** it switches on at the moments that carry the song: never more than two phrases in a row. The rules use it in the breakdowns and as each drop lands; the decision models get it as a question.

The starfield is subtle accents over the running show, not the whole rig. One set of small lights twinkles: the cells of one kind of pixel fixture, else pars, else every other head. Each star comes at its own random moment (never the rig stepping at once), comes up quickly, holds a moment and fades gently in star white; on a light that is already lit it is a white glint. About 1.5 new stars a second in calm parts and 3 in a drop, whatever the size of the rig.

A title about **lasers** makes the lasers the star of that track.

A genre can also have a **program**: a show of its own.

### The cinematic program

Film scores and trailer music have no beat grid to light. The cinematic program plays them **hit by hit**, with the rig played like an orchestra:

- every hit is found **where it really is** (spectral flux in nine bands, no grid; ~5 per second in a dense passage) and sorted into **voices** by its spectral fingerprint: booms, thuds, stabs, ticks…;
- **sections**: fixtures of one kind form a section (the four beams, the floor pixel bars, the two washes…; a big uniform rig is split by where its fixtures hang). Each section suits some parts: beams the stabs, floor lights and blinders the booms, pixel bars the ticks and the melody, washes a held pad. Powerful sections without a part are the **brass**: they join the strongest hits when the music is big;
- **the score**: every phrase, each voice gets a *lead* section and, when the music is big enough, an *answer*. The parts move to other sections from phrase to phrase. Quiet phrases are chamber music (a few soloists); the climax is tutti;
- **gestures**: a section plays its voice in one gesture for the whole phrase: a chase, mirrored pairs outside-in, odds against evens, steps along its pixels, or keys (the pitch picks the place). A run of hits plays the gesture through, and the next run is the answer: the other section, or the chase back the other way. Strong hits are played by the whole section, or by both sections together;
- **played notes**: a light is played the way a musician plays a note: hit at once (to one of three levels: soft, half, full), held for as long as the note sounds (until its instrument plays again, or it has died away), and let go gently. In between it never flickers along with the music. Slow things are smooth: long booms are let go slowly, and the low glow and the melody layer come and go in slow fades. No fixture is hit again within a third of a second;
- **impacts** (the biggest hits) play the whole rig, the strobes (within `max_flash_hz`) and the lasers, and the moving heads change picture (a cathedral of beams, a fan over the crowd, a cross, all on the DJ…). They move there in the dark just before, so the new picture lands on the hit;
- **the lows** glow on the floor in deep colours, on a few steps that change slowly;
- **room for the accents**, the light show's version of sidechaining. A rig often mixes a few very powerful lights (a 180,000 lm strobe, halogen sunstrips) with small ones (pixel cells, narrow beams), and when the big ones are on, the small ones' accents disappear. So every fixture gets a *power* from its real output (lumens, and how wide it spreads). Powerful sections leave the ticks and weak hits to small ones. While small fixtures play accents, the powerful ones step down (never to black) and come back after. An impact's flash and the first instant of a big fixture's own hit are left alone. A rig of equal fixtures is unaffected;
- **the melody**: when everything plays together legato, there are few hits to play, so a melody layer takes over. The notes of the separated melody instrument are played over the melody section (each held, then let go as the next one comes): low notes in the centre, high notes out to the sides. The pad section holds a steady glow, and the moving heads drift with the melody's contour. Percussive passages don't get it;
- between hits it's dark. Quiet passages play soft, the climax hard. The colours follow the arc: ice when calm, warm in the swells, fire at the climax. An answering section plays in the next colour of the palette.

## Decision models

Choose the decision model on the **setup page** (saved on selection, also in a running live show) or per run with `--director`.

| Model | `--director` | Speed (per phrase) | Notes |
|---|---|---|---|
| Rules | `rules` | instant | Hand-made looks per section, offline |
| OpenAI Decisions API (`gpt-6-luna`) | `openai` | ~1.3 s | Needs `OPENAI_API_KEY` (env or `.env`) |
| **nimble** (local, Ollama) | `ollama` / `ollama:nimble` | ~7–8 s on an M3 Max | Free, offline. Any Ollama model with the `decision` capability works (`ollama:<name>`) |

- **Same prompt, questions and safety nets for every model.** nimble uses Ollama's Jev-style `/v1/systemone` endpoint, which, like the Decisions API, returns probabilities per option. On a psytrance test track nimble agreed with OpenAI on the song structure for 87% of phrases and labelled all drops; it varies the moving heads less, which the variety rules correct using its own second choices.
- **Switching while live:** tracks that already have a plan from that model switch instantly (plans and answers are cached per model). A model that's still working stops at its next phrase, and the new one starts.
- **Caching:** answers are cached by prompt hash (`.cache/*.decisions-cache.json`), plans per track/model/version. Bump `PROMPT_VERSION` in `decisive/director/llm.py` after editing prompts or vocabulary.

### What the model decides per phrase

`section` (intro · groove · buildup · drop · breakdown · outro), `palette` (warm · cool · neon · fire · ice), `intensity` (4 levels) and these layers:

| Layer | Options |
|---|---|
| `par_base`: pars between hits | off · dim · full · fade |
| `par_accent`: pars on a hit | none · pulse · color_pop · chase · alternate · sparkle · melody |
| `trigger`: what a hit is | kick · backbeat · hats · accents · bars · eighths · sixteenths · roll · lead · synth |
| `head_trigger`: the heads' own hit | same · kick · … · synth (layering: e.g. heads on the kick, pars on a 1/8 synth riff) |
| `head_light` | steady · pulse · flick · beat · alternate · random (each head its own random kicks) · accents · breathe · off |
| `movement`: path | still · sweep · nod · circle · figure8 · step_on_beat · bounce · swing · ballyhoo · tilt_wave (a row tilting in a rolling wave; mirrored: from the centre out) |
| `formation` | sync · mirror · wave · fan · focus (shared point) · cross |
| `aim` | crowd · stage · sky |
| `head_color` | base · accent · white · cycle |
| `beam_fx` | **open (default)** · gobo · gobo_shake · gobo_spin · gobo_rotate · prism · prism_spin · frost (rare) |
| `gobo_style` | dots · shapes · rings · curves |
| `dynamics` | steady · rise (build-up) · impact (drop) |

The descriptions in `decisive/director/vocabulary.py` are sent to the model verbatim: they are its style guide.

### Safety nets (musical facts first)

The analysis can overrule the model where the music is unambiguous; changed phrases are marked `+guard`.

- **Drops:** a detected drop is always `drop` with `impact`, intensity ≥ High, moving heads (no still/nod/sweep), lights on. The phrase before a drop is a `buildup` with `rise`.
- **High energy keeps moving:** loud phrases with a running kick never get still or nodding heads.
- **Variety:** a path, formation, head light or head colour repeated three phrases in a row is replaced by the model's next most likely option; drops differ from the previous drop; drops and breakdowns change the palette.
- **No beat:** percussive triggers become `accents`.
- **Energetic moves stay energetic:** the tilt wave and randomly pulsing heads are for medium and intense moments; in intros, breakdowns, outros and quiet phrases they become a nod and a breathing light.
- **Crisp beam:** frost only in intros/breakdowns/outros and at most once per 4 phrases.
- **Hysteresis:** an unsure model (mean confidence < 0.35) in an unchanged section keeps the previous look. API errors or refusals fall back to the rules; the show never stops.

## The analysis

`decisive/audio/`, numpy/scipy only, cached per file:

- **Beats and tempo:** onset envelope (frames centred on their own time) → windowed autocorrelation → dynamic-programming beat tracker (follows tempo drift). A tempo the whole track fits much better (a comb over 80–180 BPM on the low end) makes it track again from there. Each beat is refined between frames and steadied by its neighbours. A track made at one tempo (most club music, also a mix held at one tempo) gets **one straight grid**: tempo and phase from where the low end, sub included, rises most on evenly spaced lines over the whole track, so on the kick, also where the off-beats are as loud. Finally the grid moves to where the beat is **heard**: the attack of the average hit on the beat, at sample precision. Downbeats (the bar lines) per 64-beat window, 4/4 assumed: by the music's structure first (drops, breaks, the kick or bass coming in or out start on the one, so the beat where the low end changes most marks the bar line), by the beats' accents only where the structure says nothing clear; with a steady four-on-the-floor kick the accents pick a beat almost by chance. On 24 club tracks the bar lines now sit on the drops in 23 (before: 14); Greyhound's drops were a beat late. Hip-hop is often detected at double tempo: use `--tempo half`.
- **Onsets:** kicks checked on every beat in the 100–200 Hz punch (lower bands are masked by offbeat bass), snares, hats, accents, melodic notes.
- **Phrases:** 4–16-bar segments at novelty peaks.
- **Drops:** first, wherever the phrase grid is, the bars where a drop lands: the kick starts **running** (on most beats of this bar and the next, after bars with at most half) and the low end jumps in with it. A phrase boundary within 6 bars moves onto that bar, or the phrase is split there. Songs don't keep a 4-bar grid from their first bar (a piano intro, a bar of silence before the drop), and a long phrase that only gets its beat halfway must not count as a drop from its beatless first bar. Then per phrase a `drop_score` (relative jump in loudness and low end, kick returning; the first drop of a track is often quieter than the last), and the boundary is fine-tuned to the **exact bar** where kick and low end come in.
- **Build-ups:** a long section before a drop often holds a chorus and then the build. The build gets its own section: of the 4 to 16 bars before the drop, the longest stretch over which the tension (loudness and brightness) rises about as steadily as the best one, starting from where it was last low (the breath bar right before the drop left out). That section is lit as the build-up, not the chorus before it.
- **Anacrusis (pickups):** a section can start before its downbeat. A **fill** is a burst of snare and accent hits in the last beats before the boundary. An **early** start is the last beats already sounding like the next section; once the instruments are separated, it can also be a **vocal line** that comes in after a pause one to three beats before a downbeat. A vocal lead-in also moves a nearby section boundary (within two bars, never a drop's) onto the downbeat it leads into. Plans are cached per set of section times, so a track whose sections change after separation gets a new plan.
- **Instruments (optional):** once a track is separated, its melodic part (Demucs "other": synths, piano, guitar, pads, strings together) is judged about once a second by the **MTG-Jamendo instrument classifier** (EffNet-Discogs, Music Technology Group, UPF; run with ONNX Runtime, Essentia's input step redone in numpy; ~1 s per track). Its 40 instruments are grouped into families: synth, keys (piano, electric piano, rhodes, keyboard), pad, guitar, voice, strings, organ, brass, bells. Each note gets its instrument: where one family clearly plays alone, the track teaches what it sounds like; every other note goes to the family it sounds closest to, among those heard around it. The decision models are told the instruments per phrase. **A new melody splits a phrase:** where the melodic part clearly changes on a 4-bar line inside a phrase (its sound, by the model's description, against the four bars before, plus a jump in register), while drums and energy stay the same, the phrase splits there and the director is told a new melody comes in (in Greyhound the high melody at 2:49). Install: `pip install onnxruntime`, then `decisive instruments --download` (two models, ~21 MB). **The models are CC BY-NC-SA 4.0: non-commercial use only** (a proprietary license is available from the MTG); they are not part of this repository. Without them everything works as before.
- **Synth stutters / gates:** fast regular chopping (1/8–1/32 notes) of the 250–2000 Hz range, as a per-frame gate signal and strength.
- **Synth riffs:** how tightly melodic notes sit on the 1/16 grid (vocals score ~0, arps ~0.8+).
- **Melody:** pitch contour, pitch class, tonality.

Measured: a click track within 3 ms of every click; six tracks within +2…+15 ms of Mixxx's beat grid (Mixxx
marks where its detector reacts, we where the hit is heard) and at Mixxx's tempo, against 42–49 ms early and up
to 0.7 % off before.

**Light lead:** the lights are rendered a little ahead of the music (`"artnet": {"lead_ms": 50}` in the set,
50 ms by default) for the time a light takes to show what it is sent and the DJ software's audio buffer. Tune it
on your rig by eye: lights late on the kick → raise it.

## The engine

`decisive/engine/` renders 40 frames per second from the plan and the analysis:

- **Pickups:** a section that leads in early has its look coming in on the pickup (about two thirds of the way by the downbeat, which lands it), and the moving heads move into its positions during the pickup so they arrive on the downbeat. A fill is played by the lights beat by beat, in the next section's accent colour, growing into the downbeat. Pickups into a drop leave the drop moment alone. The decision models are told about them.
- **The drop moment:** moving heads go dark two beats before a drop and already move to the drop's position, colour and gobo ("move in black"); everything is dark for the last half beat; on the downbeat a hard cut, a white flash and full intensity for one bar.
- **Beat-landed head moves:** bounce, swing and step-on-beat are sized from the fixture's **measured** motion (`decisive motion`): one beat per move if ≥ 30° fits, otherwise two beats (far bigger moves). Each move starts exactly its travel time before the landing beat. Pan/tilt targets go out 120 ms early and the fixture moves at its own speed; the motor model only predicts the real position (for the visualiser and timing).
- **Room limits (on by default):** moving-head beams stay off the ceiling (they only go up so far that they reach it at least the room's depth away, 4–10 m: in a living room that is about level) and never swing back past the rig towards the stage and the DJ (pointing steeply down is fine). Beams on the audience are fine: only laser audience scanning is not done. Switch either off per rig in the Venue settings (`stage.ceiling_guard`, `stage.back_guard`).
- **Geometry:** a stage model in metres; paths become beam directions (or a shared spot for focus/cross, the heads spread around it), then pan/tilt by inverse kinematics, choosing the solution closest to where the motors actually are. Calibration per head: `mount` (stand/floor/hang), `pan_home_deg`, `pan_invert`, `tilt_home_deg`, `tilt_invert`.
- **No flicker; the kick leads:** a light is played like a note: on at once, held, let go gently before the next hit. Hits closer than 0.3 s are held through, so no light ever blinks on and off faster than about 3 times a second. Fast triggers (`hats`, `eighths`, `sixteenths`, `roll`, `synth`) switch the lights on the kick, never per hi-hat or synth note; without a kick (a breakdown) kick-led light holds a steady middle level. White flashes land on the kick too.
- **A group plays the kicks in parts:** per phrase (and in grooves, build-ups and drops every 4 bars, so the show keeps moving with the music) the engine picks how a group (or a one-group rig) plays the kicks, left to right by position: all together, taking turns (odd/even), left against right, or a rotation through three or four sub-groups. Drops lean towards all together.
- **Rhythm and accents:** even with a few lights, some keep the rhythm (the kick) and some play the accents: about one light in three (heads and pars together, spread over the rig by position; of two lights one) flashes on the synth's **stabs**, exactly on the note, in the accent colour (white in the big drops), dark in between, like keys hit on a synthesizer. A stab is a synth note that clearly stands out from the notes around it or comes after a rest (not every note of a riff), at least 0.35 s apart. The roles shift every 4 bars; only in grooves, build-ups and drops. A single light plays both. The separated melodic part gives the best stabs; until a track is separated, the melody onsets stand in. With the instrument models installed (below), the accents follow **one instrument per phrase**: the most present one with the most stabs (the piano in a piano intro, the guitar in a guitar section, the synth in the drops), never jumping between them.
- **Kick breaks:** where the kick thins out or drops away inside the music (after a running kick, bars with two kicks or fewer that dip to one or none: often a filtered kick, a subtle build within a section), the kick-led lights stop pulsing, hold and build up to the kick's return. After a break of two bars or more there's a breath of darkness on the last half beat, then the return hits: everything full with a white flash, settling over one beat. A real drop keeps its own, bigger drop moment.
- **No strobing with the music:** nothing strobes along with synth stutters; the strobe fixtures flash on the beat into a drop and on the big hits in drops (always within `max_flash_hz`).
- **Heads never freeze:** `still` is a slow drift, and an upward aim under a low ceiling comes down below it with a swing it can still make (in a living room, "sky" would otherwise be clamped flat).
- **Beam effects** are mapped per fixture (`beam_fx` in the fixture JSON): gobos by style, rotation speed following the energy, mirrored heads rotating the opposite way.
- **Colour wheels:** colours snap to the nearest wheel slot; flashes become a dimmer bump instead of moving the wheel.

## Hardware

### Sets and rigs

- A **set** is your gear: the fixtures you own, their DMX mode and address, calibration, where the DMX goes (`config/sets/<name>.json`). Most people have one.
- Your **DMX devices** (Art-Net and sACN nodes, USB interfaces) live apart from the sets, in `config/devices.json`: each set up once (name, address, how it counts its universes). A set maps its universes onto them (`"dmx": {"1": {"device": "pocket", "output": 1}}`): replace a node or play somewhere with other controllers, and only that mapping changes. In the Mac app: *Show → DMX Devices & Output…* (⇧⌘D). Sets without a mapping keep their own `output`/`artnet` settings.
- A **rig** is a venue: the stage's size, trusses and towers, the LED wall, zones, and where each set's fixtures hang on it (`config/rigs/<name>.json`).
- A show runs with a set placed on a rig: the active ones (`config/active-set`, `config/active-rig`), or `--set NAME --rig NAME`. A running show keeps the ones it started with.

```bash
.venv/bin/decisive set                                  # your sets
.venv/bin/decisive rig                                  # your rigs, and which sets are mounted on them
.venv/bin/decisive rig rotterdam --template club --width 10 --screen   # a new rig from a template
.venv/bin/decisive rig --automount                      # mount the active set's fixtures on the active rig
.venv/bin/decisive play TRACK.mp3 --set mine --rig rotterdam --mute
```

**Mounting a set on a rig:** fixtures the rig has no place for yet wait on the floor in front of the stage. A rig without truss objects (generated test rigs, older rigs) first gets its structure back: fixtures hanging in a row become a truss, fixtures stacked at one spot a tower; a rig with no structure at all gets the usual one for its stage. **Auto-mount** then hangs them the way a lighting tech would start: lasers high at the back, moving heads under the trusses (some on the towers), strobes and blinders on the front, bars and pars on the floor, every model mirrored around the middle. In the Mac app's rig editor you can then drag any fixture, a ⇧-selection, or a whole group from the list onto a truss; a group hangs in a row. On a tower a fixture hangs off one of its four faces (front, back, left, right; the side you drag it off picks the face), its head pointing out; only on top of a tower does it stand. The same set can be mounted on as many rigs as you like; each rig remembers where it hangs. The file format and the rules are in [docs/rig-format.md](docs/rig-format.md).

Sets from before rigs existed (fixtures with positions and the stage in one file) are split into a set and a rig of the same name the first time you run the engine or the Mac app; nothing changes for the show.

**Test rigs:** `decisive set NAME --grid qlc:Martin/Martin-MAC-Encore-Performance.qxf:60 --rows 3 --width 16 --height 7` (or `--layout concert --lasers 10`) makes a set of many fixtures and a rig they hang on (Art-Net to 127.0.0.1 only, so a test rig never drives your real lights). Head motion for big rigs is simulated for all heads at once (60 heads: ~1.5 s on first load) and cached in `.cache/trajectories/`.

### Groups of heads (big rigs)

A rig with several groups of moving heads (overhead truss, back of the stage, front edge, side towers…) is not treated as one long line. `decisive/rig/groups.py` finds the groups (or takes `"group"` from the fixtures) and every head knows its place in its group and where its group is. The director gets the rig described in its prompt and four extra decisions per phrase (only for multi-group rigs; a one-group rig like a DJ booth is unchanged):

- **grouping**: *unison* (one big line), *per_group* (each group its own mirror/fan/wave/focus point), *split* (featured groups vs a counter-movement in a contrasting colour), *solo* (one part of the rig performs, the rest waits), *chase* (the light runs from group to group on the beat), *individual* (every head its own timing and path);
- **featured**: overhead / back / front / towers (who leads in split and solo);
- **movement2 / formation2**: the counter-movement for split.

**Layering** on top of that: per phrase the director picks which heads hold a soft **base** glow (low, medium or breathing, in the base colour) and which play the **accents** on the hits: every other head, the outer vs inner heads of each group, high vs low heads, or the featured groups vs the rest.

Towers fan out in height, waves span at most 4 beats, and safety nets keep drops from going solo and make the grouping and the featured part change regularly. Plans are cached per group layout (and per house style).

### Lasers

Multicolour DMX lasers (kind `laser`, e.g. `fixtures/laserworld/cs-1000rgb-mk3.json`) get their own decisions per phrase when the rig has them: **look** (off, beams, fan, tunnel, cone, wave), **movement** (still, scan, rotate, wave, chase) and **colour** (from the palette); their on/off rhythm follows the heads' light. **Safety: laser beams always stay above the audience**: every laser gets a minimum elevation so that each beam is at least 3 m high at the stage edge and keeps rising (from the back of the stage that is ~18° up); cones and tunnels are lifted so their lowest beam obeys it too. Audience scanning with lasers is not supported. The pattern numbers per shape depend on the laser model: check them once on the real laser (`"laser": {"patterns": …}` in the fixture file). Auto-mount puts lasers high at the back of the rig; `decisive set NAME --layout concert --grid MODEL:60 --lasers 10` (or the setup page) makes a concert test rig with lasers: on the front truss, at the back of the stage and on the towers.

### What's in a set and a rig

- **Set:** `artnet` (node IP, port, frame rate) or `output` (sACN, USB), `safety` (`master`, `max_flash_hz`), `director` (the decision model), and `fixtures`: id, library model, mode, universe, address and calibration.
- **Rig:** `stage` (width, ceiling, room depth, `eye_safety`), `trusses`, `screen` (an LED wall), `zones`, and `placements`: per set, per fixture, where it hangs (`x`, `y_m`, `z_m`, `mount`, `truss`, …).

The **setup page** (`/setup.html`) edits the active set on the active rig: pick the set and the rig (or make a new rig from a template and auto-mount the set on it), add fixtures from the library, modes, addresses, auto-address and layout, Identify (lights one fixture white for 2 s), find the node on the network, stage and safety, decision model. Saves with overlapping addresses are refused.

**Mobile setup** (`decisive setup --lan`, then open the printed `http://<mac-ip>:8080/m.html` on your phone): search a fixture across your library, the QLC+ library (~1,800 fixtures, Apache-2.0) and the Open Fixture Library (MIT); pick the DMX mode; get free start addresses (*easy to dial*: every address ends in 1, or *packed*) with what to set on the fixture's menu; add it to the rig. Existing fixtures keep their addresses. Or tap **📷 Photo**: photograph the fixture's label (type plate), or just the fixture. With `OPENAI_API_KEY`, `gpt-6-luna` looks at the photo and says what it is (brand, model, type, beam/spot/wash: read from the label, or recognised from the housing, lens and logo), then the Decisions API picks the matching entry among the closest library fixtures, with the photo; at ≥ 90 % from a label it opens the fixture straight away, from the looks alone it always asks you to confirm. Without a key, a local Ollama vision model (e.g. `gemma4`) reads the label and the text is searched (~10–30 s). Every step is logged in the setup terminal and `.cache/setup-events.log`; the last 20 photos are kept in `.cache/labels/`. The QLC+ library is fetched once as a sparse git checkout into `.cache/qlcplus` (~18 MB). `--lan` lets anyone on that network change the rig, so use it on a network you trust.

**Placement from a photo** (mobile page): *Light up the rig* gives every fixture its own colour for 2 minutes (dimmed; heads aim 30° above the audience, not into the camera; six colours per photo, more fixtures go in groups). Take a photo from the audience: the page finds the coloured light spots itself (exact positions), and `gpt-6-luna` says per colour what it is mounted on (floor, stand, truss, upside down), roughly how high, the distance between the outermost fixtures and any alignment problems. You get the photo with markers and a list of proposed changes (`x`, `mount`, `z_m`, `stage.width_m`) to tick and apply. Distances are measured from the fixtures' housing sizes (`physical.size_mm`, from QLC+/OFL), not guessed. A big glow (a par lighting the wall) is recognised as such. A different left-to-right order than the rig is flagged (usually a wrong address or mode). While the photo lights (or Identify) are on, a running show pauses its DMX output (`.cache/dmx-hold`).

**Exact placement from a 3D scan** (mobile page, *Or exact: a 3D scan*): *Light up for a scan* keeps the colours on for 10 minutes; scan the setup with an iPhone app such as Niantic Scaniverse (walk around it, include the floor and the wall behind), export a **point cloud (PLY)** — or a Gaussian-splat PLY — and upload it. Phone scans are in real metres with gravity along one axis, so `decisive/setup/pointcloud.py` finds the floor (up axis: y or z), the room's big surfaces (RANSAC), each fixture as the 3D centre of its colour (clusters close together, like the LEDs of one bar, are combined; light spilling on a wall or the floor is ignored), the stage frame (x along the line of fixtures, the audience on the side away from the wall), the ceiling height and the room depth in front. The page shows a top-down view with the fixtures; flip the audience side or tap a marker and then its real place to correct it, and apply exact `x`, `y_m`, `z_m`, `mount`, `stage.width_m`, `ceiling_m` and `room_depth_m`. The last 5 scans are kept in `.cache/scans/`.

### Fixture library (`fixtures/<manufacturer>/<model>.json`)

Every DMX mode from the manual, safe defaults for channels the engine doesn't drive (shutter open, prism off, no programs, strobe channel never driven), plus:

- **`motion`:** speed and acceleration per axis (measure with `decisive motion`).
- **`beam_fx`:** DMX values per beam effect, including rotation ranges.
- **`gobo_names` / `gobo_groups`:** name them with `decisive gobos` (the styles map the names to dots, shapes, rings, curves).
- **`color_wheel`:** slot colours (name them with `decisive colors`; `"verified": false` means guessed).

Included: **beamZ Fuze75B Beam** (12ch/10ch, measured motion, named gobos and colour wheel), **beamZ Fuze75S Spot** (13ch/11ch, colours and motion still estimated), **Ayra ComPar Kit 2** (4 RGB heads, 16/12/7/3ch), and conversions of popular fixtures from the QLC+ library (Sharpy, Pointe, MAC Aura, MAC Encore, Atomic 3000, …; see `THIRD_PARTY_NOTICES.md`).

### Real hardware checklist

1. Connect the Net-2/5 to the same network as the Mac. It can use DHCP on a home network; otherwise set the Mac to 2.x.x.x / 255.0.0.0 for the factory default 2.0.0.1.
2. Find it: setup page → *Find node*, or `decisive discover --write`. Note which Art-Net universe each output port uses (our Net-2/5 port 1 = universe 1).
3. Patch the fixtures (setup page or `decisive patch …`) and set the same mode and start address on each fixture's display. DMX chain order doesn't matter.
4. `decisive test`: every fixture on its own, then head orientation (calibration is saved).
5. Optionally `decisive motion`, `decisive gobos`, `decisive colors` per head model.
6. First show with `safety.master` at about 0.5.

Discovery also lists RDM fixtures and can re-address them over RDM (`--readdress`), but most budget fixtures (including the Fuze75 and ComPar) don't speak RDM, so patch them by hand. `decisive simnode` simulates a node with RDM fixtures for testing without hardware.

## Safety

- **Flash limit:** white flashes and the software strobe go through one timeline capped at `max_flash_hz` (3 Hz, the photosensitive-epilepsy guideline). Fixture strobe channels are never driven.
- **No fast strobe:** no light flashes faster than `max_flash_hz` (3 Hz, the photosensitive-epilepsy guideline); nothing chops along with the music. Warn an audience about strobe effects anyway.
- **Eye safety:** `stage.eye_safety` (off by default; turn on for lasers or very bright beams) keeps beams towards the audience out of eye height, and heads go dark while crossing that band.
- **High-output fixtures (alpha):** this is alpha software, not for a powerful rig in front of a real audience. Fixtures of risk group 2 or 3 (IEC 62471: `physical.risk_group` in the fixture file, from the manual or label) stay dark when the DMX goes to real lights; the visualiser still shows them. Without a rating a fixture counts as one when it packs a lot of light into a narrow beam (≥ 5,000 lm per beam and ≥ 200 lm per square degree: a Sharpy or a Pointe, not a Fuze, a Katana or a wash). Consumer lights play as usual, the audience included.
- **No single point:** focus and cross looks aim the heads around a spot about 1.5 m wide instead of all into one point, and the cinematic "all on the DJ" picture rings the light above the DJ's head.
- **Zones:** draw keep-out, keep-in and laser safety zones in the rig editor (Mac app). Keep-out zones are physical stops for the head motors: a beam never sweeps into them.
- **Laser guard:** the last step of every frame. A laser pattern that would enter a laser zone is raised, then shrunk, then blanked. With real lights, a set with lasers needs at least one laser zone or its lasers stay dark. This is a software layer on top of the laser's masking plate, scan-fail safety and E-stop, never a replacement.
- **`master`** scales every dimmer.

## Project layout

| Path | What's there |
|---|---|
| `decisive/` | The engine (Python): `audio/`, `director/`, `engine/`, `show/`, `rig/`, `library/`, `dmx/`, `setup/`, `web/`, `cli/`. See [docs/architecture.md](docs/architecture.md) |
| `web/` | Browser UI: 3D visualiser (`index.html`), setup page, mobile rig setup (`m.html`) |
| `mac/` | The Mac app and the Decisive Link app ([mac/README.md](mac/README.md)) |
| `vdj/` | The DecisiveLink VirtualDJ plugin (SDK headers downloaded at build time) |
| `fixtures/` | The fixture library |
| `examples/` | Example sets and rigs; your own go to `config/sets/` and `config/rigs/` |
| `tests/` | Golden-master and unit tests |
| `docs/` | [Architecture](docs/architecture.md), [sets and rigs](docs/rig-format.md), [protocols](docs/protocols.md), [DJ software](docs/dj-software.md) |

## Known limits

- Downbeats and phrases are heuristic (4/4 assumed); bar 1 can be a beat off in some tracks.
- Automatic half-time detection isn't reliable: use `--tempo half` for hip-hop.
- Drop and stutter thresholds were tuned on house, techno, psytrance and melodic techno; other genres may need adjusting.
- nimble is about 6× slower than OpenAI on this Mac (~2–4 minutes per track); in live mode the rule-based plan bridges the wait.
- djay Pro is read from its window: a djay update that renames its controls can break it. Without SYNC its position is less precise (up to ~70 ms).
- Mixxx must be started after the live show (it only looks for MIDI devices at start), unless the IAC bus is used.
- The Fuze75S colour wheel colours are still guesses until named with `decisive colors`.

## Contributing and license

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Decisive Lightning is MIT licensed
([LICENSE](LICENSE)); fixture definitions converted from QLC+ are Apache-2.0, see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Lighting can hurt people: strobes and flashes can trigger seizures, and lasers can blind. The safety
features here are aids, not guarantees; you are responsible for your rig and your audience.
