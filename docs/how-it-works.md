# How it works

The technical story behind the show: how a track is analysed, how the director chooses a look per phrase, and how the engine turns that into DMX, beat-exact. For the code map, see [architecture.md](architecture.md); for the command line, [command-line.md](command-line.md).

## Overview

Tracks are analysed (beats, bars, phrases, drops, build-ups, synth stutters and riffs), a **decision model** designs a layered light show per musical phrase, and a real-time engine drives moving heads, pars, strobes and lasers over **Art-Net, sACN or a USB DMX interface**, beat-locked. It works on recorded tracks and **live in VirtualDJ**, following the mix as you play, on the DJ's computer or on a separate lighting computer.

There is a 3D visualiser in the browser and a native **Mac app** (`mac/`) with a Metal stage, a rig editor and a set-up assistant.

Your lighting is described in two parts: a **set** (your fixtures: what you own and how it's patched) and a **rig** (a venue: the stage and the trusses). You make a set once, make a rig per venue, and mount the set on it: automatically or by dragging fixtures onto the trusses. See [Sets and rigs](command-line.md#sets-and-rigs).

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
  via the AmadeusLink plugin) drop moment, kick-led light…   
```

**The AI chooses the look; it never triggers individual hits.** Choices are made once per phrase (4–16 bars). Everything time-critical (kick pumps, flashes, beat-locked head moves, the drop hit, synth stutters) comes from the analysis, so it's exact to the beat.

## The show arc: a whole night

A track has its own arc (intro, build-up, drop, breakdown); a night has one too. The **show arc**
([amadeus/show/arc.py](../amadeus/show/arc.py)) treats a whole DJ set, wedding, birthday or Latin night, from
half an hour to twelve hours, as one curve with stages: a warm-up while the room fills, building the floor,
peaks, deeper breathers against fatigue, a finale and an outro.

- **Detected from the music, never a timetable.** How hot the mix runs (energy per phrase, and the tempo against
  the night's own warm-up tempo, half and double time folded together) is followed quickly and slowly, and each
  stage is scored by how well the music fits it. The clock only nudges: a warm-up belongs to the start, a finale
  to the end; in between the DJ's own path wins (peak early, dip, peak again).
- **Proportional.** Every time constant is a share of the show's length, so a one-hour set has the same shape
  as a ten-hour one.
- **Event types** (club, wedding, party, Latin) set those nudges, the stage names and the character: a wedding
  has a calm dinner and slow dances, fewer lasers and less smoke than a club.
- **Fewer lights, not dimmer ones.** A club night runs at full intensity; a warm-up is quieter because fewer
  groups play, the biggest groups and the special effects (lasers, strobes, blinders) stay in the box until the
  moments that earn them. With an empty floor, the warm-up is a cosy static wash with slow heads projecting
  gobos on the floor. Only real calm phases (a wedding dinner, the goodnight) dim.
- **A countdown is rare.** The LED wall's 3-2-1 DROP! is granted by the arc, not played into every drop: in a
  peak or the finale (a few minutes into the night), into a track's first main drop after a build or a
  breakdown, at most twice a night and well apart. The engine names that drop in the feed's hello
  (`countdown`); the walls on the Mac, Windows and in the browser only count into it. A track played on its own
  counts into its main drop.
- **Knobs** (all live, in every mode of the app): light groups in play, special effects, LED wall, smoke,
  movement, look changes, colour variety, responsiveness, drop size, flashes and intensity. The operator can
  take over any knob at any moment and give it back to the arc, force or hold a stage, pick the event type and
  change the show's length. The drop moment at full keeps its full response.

## Songs and club tracks

Pop and rock songs are not built like club tracks: a loud chorus is not a drop. Each track gets a **form**
([amadeus/audio/form.py](../amadeus/audio/form.py)): *song* or *club*, from the known genre, else from how much
of the loud parts are sung (songs sing through their choruses; club drops are instrumental). In a song every
phrase gets a part (intro, verse, pre-chorus, chorus, bridge, instrumental, outro), the directors light verses
and choruses instead of build-ups and drops, and the last chorus is the song's climax. A real drop inside a
song (the beat taken away before it, then the voice steps back) keeps its drop moment.

**Rock and metal play the band.** In a dense guitar mix the drums are hard to hear from the full mix, so with
the instrument packs installed the kit is taken from the separated drum stem
([amadeus/audio/drums.py](../amadeus/audio/drums.py)): kick and snare become two voices played by whole groups of
lights, the snare's light rings as long as its reverb, and the guitar's strums play the accent lights.

## Genres and programs

Every track gets a **genre**, one word (cinematic, classical, ambient, edm, house, techno, trance, psytrance, hardstyle, dnb, dubstep, hiphop, rnb, pop, rock, metal, reggaeton, latin, disco, funk, jazz), shown with the track in the app and the visualiser:

1. **your choice** (`amadeus genre TRACK GENRE`, kept in `config/genres.json`);
2. the **Decisions API**, given the artist and title (from the file's tags, or its name), when there's a key and it is reasonably sure (30% with the artist known: torn between pop and edm for Coldplay is still far better than a tempo guess). A title alone ("Symphony") has to be very sure, and a beat-less genre (cinematic, classical, ambient) only counts when the audio has no groove either;
3. a **genre tag** in the file;
4. the **audio**, as the fallback. Reggaeton first, by its **dembow**: the snare on the 16th before the second beat and on its "and" (3+3+2), where house and pop put theirs on the beat. Then **disco**, by its sound: its beat is house's, but the style model of the instrument recognition (EffNet-Discogs, with the models installed) hears the band, the strings and the bass guitar's octaves. Disco sounds like disco to it 0.39–0.76 on average and more like disco than like funk or house for most of the track; house stays under 0.33. Then how much of the track grooves (the same rhythm bar after bar, in the low end or the highs). Club tracks groove for 55–100% of their length, film scores for ~15%; the tempo names the family.

A Latin call from the Decisions API or a tag, on a track whose audio plays the dembow, becomes reggaeton. A funk or house call on a track that unmistakably sounds like disco becomes disco.

### A house style per genre

Every genre has a **style sheet** ([amadeus/director/style.py](../amadeus/director/style.py)), so tracks that share a genre look like one show instead of each getting its own random mood. A sheet says:
- which palettes the genre uses (techno: cool, ice and fire; hip-hop: gold and purple; rock: a white and amber `stage` look);
- which looks don't fit it (no spinning prisms or colour cycling in techno, no strobing light in jazz or ambient, no soft fades in hardstyle);
- what to use instead;
- a few lines describing the style;
- for a few genres, a beat or a look of its own: reggaeton's boom-tac, rock and metal's drum kit (kick and snare, see [Songs and club tracks](#songs-and-club-tracks)), disco's four-to-the-floor kick and its **mirror ball** in the break (the heads fanned over the crowd, circling slowly, their dots gobos turning).

A style is a **lean, not a rule**: the genre sets the colours, and the music of each part decides the moves, because a song is not one genre all the way through (a piano ballad part, then a mainstage drop).
- The **rule director** uses the genre's palettes everywhere. It swaps a look's misfits only in the grooves, the body of a genre; intros, breakdowns, buildups and drops follow their own music.
- The **decision models** get the genre's palettes as their colour choices. The rest of the style is a lean in the prompt, and every move and light stays open.

The song's arc and the drop rules have the last word. A style describes looks, not fixtures, so it works on any rig. Tracks without a genre are directed as before.

**The set's genre (live).** A genre guessed from the audio alone is noisy: one such track must not flip the style for one song. In a live set, a guessed track is lit in the set's style, and the app shows it as `POP → HOUSE`; a new genre takes over after **two tracks in a row**. A track whose genre is known (your choice, the Decisions API from its artist and title, its tag) keeps its own style: a Coldplay song in a techno set is still pop. A cinematic track plays its own program and leaves the set's genre alone. For a single track, `--style GENRE` lights it in another genre's style.

### Themes from the title

A title can carry a theme with a look of its own ([amadeus/director/themes.py](../amadeus/director/themes.py)). A track about **stars** ("A Sky Full of Stars", "Starlight", "Galaxy") gives the director a **starfield** it switches on at the moments that carry the song: never more than two phrases in a row. The rules use it in the breakdowns and as each drop lands; the decision models get it as a question.

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
- **Caching:** answers are cached by prompt hash (`.cache/*.decisions-cache.json`), plans per track/model/version. Bump `PROMPT_VERSION` in `amadeus/director/llm.py` after editing prompts or vocabulary.

### What the model decides per phrase

`section` (intro · groove · buildup · drop · breakdown · outro), `palette` (warm · cool · neon · fire · ice), `intensity` (4 levels) and these layers:

| Layer | Options |
|---|---|
| `par_base`: pars between hits | off · dim · full · fade |
| `par_accent`: pars on a hit | none · pulse · color_pop · chase · alternate · sparkle · melody |
| `trigger`: what a hit is | kick · backbeat · dembow · drums · hats · accents · bars · eighths · sixteenths · roll · lead · synth |
| `head_trigger`: the heads' own hit | same · kick · … · synth (layering: e.g. heads on the kick, pars on a 1/8 synth riff) |
| `head_light` | steady · pulse · flick · beat · alternate · random (each head its own random kicks) · accents · breathe · off |
| `movement`: path | still · sweep · nod · circle · figure8 · step_on_beat · bounce · swing · ballyhoo · tilt_wave (a row tilting in a rolling wave; mirrored: from the centre out) · pour (lit high at the ceiling, a fast fall to the floor, let go there, back up in the dark for the next beat; sync: a curtain, wave: a cascade, individual: each head on its own beat) |
| `formation` | sync · mirror · wave · fan (a bar whose cells tilt on their own, like the COLORado PXL Curve, bends into a curve) · focus (shared point) · cross |
| `aim` | crowd · stage · sky |
| `head_color` | base · accent · white · cycle |
| `beam_fx` | **open (default)** · gobo · gobo_shake · gobo_spin · gobo_rotate · prism · prism_spin · frost (rare) |
| `gobo_style` | dots · shapes · rings · curves |
| `dynamics` | steady · rise (build-up) · impact (drop) |

The descriptions in `amadeus/director/vocabulary.py` are sent to the model verbatim: they are its style guide.

**Zoom** isn't a decision of its own: it follows from these (`amadeus/engine/zoom.py`), set per phrase and never
moving with the beat. Beam and spot heads go tight when the music is big, the beams fly (sky, fast movement) or a
prism splits them, and open up into soft pools when it is calm; wash heads stay wide and gather into thick beams at
the peaks; fixed washes with a zoom stay wide, a little tighter at the peaks. A buildup focuses into its drop, an
accent layer or a featured group plays tighter than the rest, and "wide" is what the rig needs: neighbouring pools
overlapping evenly at the throw, one setting per fixture model.

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

`amadeus/audio/`, numpy/scipy only, cached per file:

- **Beats and tempo:** onset envelope (frames centred on their own time) → windowed autocorrelation → dynamic-programming beat tracker (follows tempo drift). A tempo the whole track fits much better (a comb over 80–180 BPM on the low end) makes it track again from there. Each beat is refined between frames and steadied by its neighbours. A track made at one tempo (most club music, also a mix held at one tempo) gets **one straight grid**: tempo and phase from where the low end, sub included, rises most on evenly spaced lines over the whole track, so on the kick, also where the off-beats are as loud. Finally the grid moves to where the beat is **heard**: the attack of the average hit on the beat, at sample precision. Downbeats (the bar lines) per 64-beat window, 4/4 assumed: by the music's structure first (drops, breaks, the kick or bass coming in or out start on the one, so the beat where the low end changes most marks the bar line), by the beats' accents only where the structure says nothing clear; with a steady four-on-the-floor kick the accents pick a beat almost by chance. On 24 club tracks the bar lines now sit on the drops in 23 (before: 14); Greyhound's drops were a beat late. Hip-hop is often detected at double tempo: use `--tempo half`.
- **Onsets:** kicks checked on every beat in the 100–200 Hz punch (lower bands are masked by offbeat bass), snares, hats, accents, melodic notes.
- **Phrases:** 4–16-bar segments at novelty peaks.
- **Drops:** first, wherever the phrase grid is, the bars where a drop lands: the kick starts **running** (on most beats of this bar and the next, after bars with at most half) and the low end jumps in with it. A phrase boundary within 6 bars moves onto that bar, or the phrase is split there. Songs don't keep a 4-bar grid from their first bar (a piano intro, a bar of silence before the drop), and a long phrase that only gets its beat halfway must not count as a drop from its beatless first bar. Then per phrase a `drop_score` (relative jump in loudness and low end, kick returning; the first drop of a track is often quieter than the last), and the boundary is fine-tuned to the **exact bar** where kick and low end come in.
- **Build-ups:** a long section before a drop often holds a chorus and then the build. The build gets its own section: of the 4 to 16 bars before the drop, the longest stretch over which the tension (loudness and brightness) rises about as steadily as the best one, starting from where it was last low (the breath bar right before the drop left out). That section is lit as the build-up, not the chorus before it.
- **Anacrusis (pickups):** a section can start before its downbeat. A **fill** is a burst of snare and accent hits in the last beats before the boundary. An **early** start is the last beats already sounding like the next section; once the instruments are separated, it can also be a **vocal line** that comes in after a pause one to three beats before a downbeat. A vocal lead-in also moves a nearby section boundary (within two bars, never a drop's) onto the downbeat it leads into. Plans are cached per set of section times, so a track whose sections change after separation gets a new plan.
- **Instruments (optional):** once a track is separated, its melodic part (Demucs "other": synths, piano, guitar, pads, strings together) is judged about once a second by the **MTG-Jamendo instrument classifier** (EffNet-Discogs, Music Technology Group, UPF; run with ONNX Runtime, Essentia's input step redone in numpy; ~1 s per track). Its 40 instruments are grouped into families: synth, keys (piano, electric piano, rhodes, keyboard), pad, guitar, voice, strings, organ, brass, bells. Each note gets its instrument: where one family clearly plays alone, the track teaches what it sounds like; every other note goes to the family it sounds closest to, among those heard around it. The decision models are told the instruments per phrase. **A new melody splits a phrase:** where the melodic part clearly changes on a 4-bar line inside a phrase (its sound, by the model's description, against the four bars before, plus a jump in register), while drums and energy stay the same, the phrase splits there and the director is told a new melody comes in (in Greyhound the high melody at 2:49). Install: `pip install onnxruntime`, then `amadeus instruments --download` (two models, ~21 MB). **The models are CC BY-NC-SA 4.0: non-commercial use only** (a proprietary license is available from the MTG); they are not part of this repository. Without them everything works as before.
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

`amadeus/engine/` renders 40 frames per second from the plan and the analysis:

- **Pickups:** a section that leads in early has its look coming in on the pickup (about two thirds of the way by the downbeat, which lands it), and the moving heads move into its positions during the pickup so they arrive on the downbeat. A fill is played by the lights beat by beat, in the next section's accent colour, growing into the downbeat. Pickups into a drop leave the drop moment alone. The decision models are told about them.
- **The drop moment:** moving heads go dark two beats before a drop and already move to the drop's position, colour and gobo ("move in black"); everything is dark for the last half beat, or for the music's own pause before the drop when it has one (found to within a few ms); on the downbeat a hard cut, a white flash and full intensity for one bar.
- **Snare rolls and fills:** the analysis hears the snare's own hits, to the millisecond, and where they form a roll into a drop: sixteenths all the way or speeding up step by step (quarter notes, eighths, sixteenths, thirty-seconds), even where it blurs into a buzz under the riser. Also a short fill into a phrase (a few quick hits in its own rhythm). A roll fills its beat grid with one drum's sound and is clearly faster than the groove before it, so a groove's kick, clap, hi-hats or percussion aren't one. The lights play the roll: short white flashes exactly on its hits with darkness in between, a quarter of the lights at first (the strobes first, the rest spread over the stage), half on the eighths, three quarters on the sixteenths, all of them on the thirty-seconds, each step brighter; the other lights dim so the flashes read. Within `max_flash_hz` the whole rig flashes together on the finest subdivision that fits (at 128 BPM: the quarter notes), so the build grows in lights and brightness. With `allow_fast_strobe` every hit flashes: on the fastest ones the lights take turns, each at most 10 flashes a second. `strobe_free` plays the roll as steps of steady light instead (and leaves a fill to the look).
- **Beat-landed head moves:** bounce, swing and step-on-beat are sized from the fixture's **measured** motion (`amadeus motion`): one beat per move if ≥ 30° fits, otherwise two beats (far bigger moves). Each move starts exactly its travel time before the landing beat. Pan/tilt targets go out 120 ms early and the fixture moves at its own speed; the motor model only predicts the real position (for the visualiser and timing).
- **Room limits (on by default):** moving-head beams stay off the ceiling (they only go up so far that they reach it at least the room's depth away, 4–10 m: in a living room that is about level) and never swing back past the rig towards the stage and the DJ (pointing steeply down is fine). Beams on the audience are fine: only laser audience scanning is not done. Switch either off per rig in the Venue settings (`stage.ceiling_guard`, `stage.back_guard`).
- **Geometry:** a stage model in metres; paths become beam directions (or a shared spot for focus/cross, the heads spread around it), then pan/tilt by inverse kinematics, choosing the solution closest to where the motors actually are. Calibration per head: `mount` (stand/floor/hang), `pan_home_deg`, `pan_invert`, `tilt_home_deg`, `tilt_invert`.
- **No flicker; the kick leads:** a light is played like a note: on at once, held, let go gently before the next hit. Hits closer than 0.3 s are held through, so no light ever blinks on and off faster than about 3 times a second. Fast triggers (`hats`, `eighths`, `sixteenths`, `roll`, `synth`) switch the lights on the kick, never per hi-hat or synth note; without a kick (a breakdown) kick-led light holds a steady middle level. White flashes land on the kick too.
- **A group plays the kicks in parts:** per phrase (and in grooves, build-ups and drops every 4 bars, so the show keeps moving with the music) the engine picks how a group (or a one-group rig) plays the kicks, left to right by position: all together, taking turns (odd/even), left against right, or a rotation through three or four sub-groups. Drops lean towards all together.
- **Rhythm and accents:** even with a few lights, some keep the rhythm (the kick) and some play the accents: about one light in three (heads and pars together, spread over the rig by position; of two lights one) flashes on the synth's **stabs**, exactly on the note, in the accent colour (white in the big drops), dark in between, like keys hit on a synthesizer. A stab is a synth note that clearly stands out from the notes around it or comes after a rest (not every note of a riff), at least 0.35 s apart. The roles shift every 4 bars; only in grooves, build-ups and drops. A single light plays both. The separated melodic part gives the best stabs; until a track is separated, the melody onsets stand in. With the instrument models installed (below), the accents follow **one instrument per phrase**: the most present one with the most stabs (the piano in a piano intro, the guitar in a guitar section, the synth in the drops), never jumping between them.
- **Kick breaks:** where the kick thins out or drops away inside the music (after a running kick, bars with two kicks or fewer that dip to one or none: often a filtered kick, a subtle build within a section), the kick-led lights stop pulsing, hold and build up to the kick's return. After a break of two bars or more there's a breath of darkness on the last half beat, then the return hits: everything full with a white flash, settling over one beat. A real drop keeps its own, bigger drop moment.
- **No strobing with the music:** nothing strobes along with synth stutters; the strobe fixtures flash on the beat into a drop (or on a snare roll's hits) and on the big hits in drops (always within `max_flash_hz`).
- **Heads never freeze:** `still` is a slow drift, and an upward aim under a low ceiling comes down below it with a swing it can still make (in a living room, "sky" would otherwise be clamped flat).
- **Beam effects** are mapped per fixture (`beam_fx` in the fixture JSON): gobos by style, rotation speed following the energy, mirrored heads rotating the opposite way.
- **Colour wheels:** colours snap to the nearest wheel slot; flashes become a dimmer bump instead of moving the wheel.

## Big rigs

### Groups of heads (big rigs)

A rig with several groups of moving heads (overhead truss, back of the stage, front edge, side towers…) is not treated as one long line. `amadeus/rig/groups.py` finds the groups (or takes `"group"` from the fixtures) and every head knows its place in its group and where its group is. The director gets the rig described in its prompt and four extra decisions per phrase (only for multi-group rigs; a one-group rig like a DJ booth is unchanged):

- **grouping**: *unison* (one big line), *per_group* (each group its own mirror/fan/wave/focus point), *split* (featured groups vs a counter-movement in a contrasting colour), *solo* (one part of the rig performs, the rest waits), *chase* (the light runs from group to group on the beat), *individual* (every head its own timing and path);
- **featured**: overhead / back / front / towers (who leads in split and solo);
- **movement2 / formation2**: the counter-movement for split.

**Layering** on top of that: per phrase the director picks which heads hold a soft **base** glow (low, medium or breathing, in the base colour) and which play the **accents** on the hits: every other head, the outer vs inner heads of each group, high vs low heads, or the featured groups vs the rest.

Towers fan out in height, waves span at most 4 beats, and safety nets keep drops from going solo and make the grouping and the featured part change regularly. Plans are cached per group layout (and per house style).

### Lasers

Multicolour DMX lasers (kind `laser`, e.g. `fixtures/laserworld/cs-1000rgb-mk3.json`) get their own decisions per phrase when the rig has them: **look** (off, beams, fan, tunnel, cone, wave), **movement** (still, scan, rotate, wave, chase) and **colour** (from the palette); their on/off rhythm follows the heads' light. **Safety: laser beams always stay above the audience**: every laser gets a minimum elevation so that each beam is at least 3 m high at the stage edge and keeps rising (from the back of the stage that is ~18° up); cones and tunnels are lifted so their lowest beam obeys it too. Audience scanning with lasers is not supported. The pattern numbers per shape depend on the laser model: check them once on the real laser (`"laser": {"patterns": …}` in the fixture file). Auto-mount puts lasers high at the back of the rig; `amadeus set NAME --layout concert --grid MODEL:60 --lasers 10` (or the setup page) makes a concert test rig with lasers: on the front truss, at the back of the stage and on the towers.

## Known limits

- Downbeats and phrases are heuristic (4/4 assumed); bar 1 can be a beat off in some tracks.
- Automatic half-time detection isn't reliable: use `--tempo half` for hip-hop.
- Drop and stutter thresholds were tuned on house, techno, psytrance and melodic techno; other genres may need adjusting.
- nimble is about 6× slower than OpenAI on this Mac (~2–4 minutes per track); in live mode the rule-based plan bridges the wait.
- djay Pro is read from its window: a djay update that renames its controls can break it. Without SYNC its position is less precise (up to ~70 ms).
- Mixxx must be started after the live show (it only looks for MIDI devices at start), unless the IAC bus is used.
- The Fuze75S colour wheel colours are still guesses until named with `amadeus colors`.
- UV, amber, lime and indigo emitters are not mixed into the show's colours yet (held dark). A UV-only fixture (a blacklight bar) does play: like the other bars and pars, always in UV.
- Windows is new: it is built and tested in CI, but hasn't been run on many real Windows machines yet, and the
  DJ software integrations on Windows are not verified ([dj-software.md](dj-software.md)).
