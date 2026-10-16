"""The finite answer space the director chooses from.

A look is built from independent layers (what the pars do between hits, what
they do on a hit, what counts as a hit, how the heads light, move and colour,
and the energy curve). Each entry is (value, description); the descriptions
are sent to the Decisions API verbatim, so they double as the model's style guide.
"""

SECTIONS = [
    ("intro", "Sparse start of a track or of the set: thin low end, elements entering one by one."),
    ("groove", "Steady main groove: kick and bass running, no big change in tension."),
    (
        "buildup",
        "Tension rising towards a drop: loudness or brightness climbing, snare rolls, "
        "kick or bass often filtered out or removed.",
    ),
    (
        "drop",
        "The release: full kick and heavy bass come back at high energy, typically right after a buildup or breakdown.",
    ),
    ("breakdown", "Kick and/or bass gone, atmospheric or melodic, clearly lower energy."),
    ("outro", "Elements leaving and energy falling: the track ends or is being mixed out."),
    # the parts of a song (a track with verses and choruses: rock, pop, a singer-songwriter, hip-hop)
    ("verse", "A song's verse: the singer tells the story over the band, the quieter sung part between choruses."),
    ("chorus", "A song's chorus: the hook everybody sings, the big, open part (bigger than a verse, not a drop)."),
    ("bridge", "A song's bridge: the one part unlike the others, late in the song, before the last chorus."),
]
SONG_SECTIONS = ("verse", "chorus", "bridge")

PALETTES = {  # value: (description, RGB colours 0..1). Colour 0 = base, colour 2 = accent.
    "warm": (
        "Amber, orange and deep red. Groovy, house, sunset.",
        [(1.0, 0.45, 0.0), (1.0, 0.15, 0.0), (0.9, 0.0, 0.05), (1.0, 0.7, 0.2)],
    ),
    "cool": (
        "Blue, cyan and violet. Deep, hypnotic, techno.",
        [(0.0, 0.3, 1.0), (0.0, 0.8, 1.0), (0.45, 0.0, 1.0), (0.1, 0.1, 0.9)],
    ),
    "neon": (
        "Magenta, lime and cyan. Playful, high-energy, euphoric.",
        [(1.0, 0.0, 0.8), (0.4, 1.0, 0.0), (0.0, 1.0, 0.9), (0.8, 0.0, 1.0)],
    ),
    "fire": (
        "Red, orange and white. Aggressive, hard, peak-time.",
        [(1.0, 0.0, 0.0), (1.0, 0.35, 0.0), (1.0, 0.9, 0.7), (0.8, 0.05, 0.0)],
    ),
    "ice": (
        "White, pale cyan and blue. Clean, minimal, cold.",
        [(0.85, 0.95, 1.0), (0.3, 0.8, 1.0), (0.1, 0.35, 1.0), (1.0, 1.0, 1.0)],
    ),
    # only offered when a genre's style asks for them (amadeus/director/style.py)
    "gold": (
        "Gold, amber and deep purple. Classy, warm, hip-hop, soul, funk.",
        [(1.0, 0.65, 0.1), (0.55, 0.0, 0.9), (1.0, 0.85, 0.45), (0.9, 0.3, 0.6)],
    ),
    "disco": (
        "Hot pink, violet, gold and turquoise. Glitter: a lit-up dance floor, disco.",
        [(1.0, 0.0, 0.55), (0.55, 0.0, 1.0), (1.0, 0.7, 0.05), (0.0, 0.85, 0.8)],
    ),
    "stage": (
        "Warm white, amber and deep blue. A concert stage: rock, live bands.",
        [(1.0, 0.85, 0.65), (1.0, 0.55, 0.1), (0.1, 0.2, 0.9), (1.0, 1.0, 1.0)],
    ),
}
DEFAULT_PALETTES = ["warm", "cool", "neon", "fire", "ice"]  # without a style

PAR_BASE = [
    ("off", "Pars dark between hits: punchy, high contrast."),
    ("dim", "Pars glow softly in the base colour between hits."),
    ("full", "Pars stay bright in the base colour; hits change the colour rather than the brightness."),
    ("fade", "Pars slowly cross-fade through the palette: calm, no hard edges."),
]

PAR_ACCENT = [
    ("none", "Pars don't react to hits: a static or fading look."),
    ("pulse", "On with each kick, held, let go: the pars play the kick, all together or taking turns."),
    ("color_pop", "On each hit the pars jump to the accent colour and fade back to the base colour."),
    ("chase", "Each hit lights the next par in the accent colour: light runs across the stage."),
    ("alternate", "Odd and even pars swap on each hit: ping-pong."),
    ("sparkle", "Each hit flashes one random par in the accent colour: sparse, glittery."),
    (
        "melody",
        "Pars play the melody: each lead note lights the par matching its pitch (low notes left, high "
        "notes right) in a colour for that note, fading out slowly. Best with the 'lead' trigger in "
        "quiet, beat-less parts.",
    ),
]

TRIGGERS = [
    ("kick", "Every kick drum (four to the floor): the main pulse, and what leads the lights on and off."),
    ("backbeat", "Snares and claps, usually beats 2 and 4: a looser, bouncier feel."),
    (
        "dembow",
        "Boom-tac, for reggaeton: the rig plays kick and snare as two voices, whole groups each: some on the "
        "kick (boom, its 1/8 runs too) in the base colour, the others on the snare's dembow (tac) in the accent "
        "colour. Where the beat drops out for a moment the light pauses, and the beat's return hits on all.",
    ),
    (
        "drums",
        "The drum kit, for rock and metal: the rig plays kick and snare as two voices, whole groups each: some on "
        "the kick in the base colour, the others on the snare in the accent colour, ringing out with its reverb; "
        "a few lights flash on the guitar's strums.",
    ),
    ("hats", "Hi-hats: an energetic groove; the lights still switch on the kick (never blinking per hat)."),
    ("accents", "Only big hits and impacts: sparse and dramatic."),
    ("bars", "Only the first beat of each bar: slow and stately."),
    ("eighths", "Driving 1/8 notes in the music; the lights switch on the kick (never faster)."),
    ("sixteenths", "A 1/16 rattle in the music; the lights switch on the kick (never faster)."),
    (
        "roll",
        "A buildup snare roll in the music; the lights switch on the kick (never faster). For buildups.",
    ),
    ("lead", "The notes of the melody / synth lead / vocal: for quiet parts without a beat."),
    (
        "synth",
        "A steady synth riff / arpeggio in the music; the lights switch on the kick (never blinking per note).",
    ),
]

HEAD_LIGHT = [
    ("steady", "Beams stay on: the movement is the show."),
    ("pulse", "Beams pulse with the kick, dimmed to full: all heads together or split into parts taking turns."),
    (
        "flick",
        "Beams are dark while the head moves and snap on when it lands, every beat: move, on, move, "
        "off... Sharp and very rhythmic; best with bounce, swing or step_on_beat.",
    ),
    ("beat", "Beams on with the kick, held, then off: a punchy on/off rhythm, the group split into parts."),
    ("alternate", "Heads take turns per kick (left, right, left...): call and response."),
    (
        "random",
        "Every head lights on its own random kicks: a restless rig, each head its own rhythm. Great while "
        "the heads do a tilt wave; for energetic parts, not for calm ones.",
    ),
    ("accents", "Beams mostly dim, flaring up on big hits."),
    (
        "breathe",
        "Beam brightness follows the loudness of the melody and pads: breathing with the music. "
        "For quiet, melodic parts.",
    ),
    ("off", "Moving heads dark: the pars carry the look."),
]

MOVEMENTS = [  # the path; how heads relate to each other is the formation
    ("still", "Hold a position, drifting slowly (heads never freeze)."),
    ("sweep", "Side-to-side sweep; slow in calm parts, faster as the energy rises."),
    ("nod", "Up-and-down movement; slow in calm parts, faster as the energy rises."),
    ("circle", "Smooth circles; one per two bars when calm, one per bar or faster at high energy."),
    ("figure8", "Figure-of-eight loops; the tempo follows the energy."),
    ("step_on_beat", "Jump to a new spot on every beat: sharp and rhythmic, works well with steady light."),
    ("bounce", "Snap up and down on every beat: fast and punchy."),
    ("swing", "Snap left and right on every beat: fast and punchy."),
    ("ballyhoo", "Fast, wide, unpredictable movement. Peaks only."),
    (
        "tilt_wave",
        "A row of heads tilting up and down in a wave that rolls over the row, each head a step behind its "
        "neighbour (mirror: from the centre out). One wave per bar, faster at the peaks. A classic for energetic "
        "grooves and drops, with the light steady or pulsing at random; not for calm parts.",
    ),
]

FORMATIONS = [
    ("sync", "All heads do exactly the same: parallel beams, clean and unified."),
    ("mirror", "Left and right heads mirror each other: symmetrical."),
    ("wave", "Same movement, each head a beat later: a rolling wave."),
    ("fan", "Heads spread out in a fan: wide coverage."),
    ("focus", "All beams meet in one shared, moving point: powerful and intimate."),
    ("cross", "Beams cross in the middle in an X: dramatic."),
]

AIMS = [
    ("crowd", "Over the dance floor, angled down onto the crowd (never at eye height)."),
    ("stage", "Back onto the stage and DJ area: framing the DJ."),
    ("sky", "Up into the air and the ceiling: airy, for intros, breakdowns and buildups."),
]

HEAD_COLOR = [
    ("base", "Same colour as the pars' base: one unified colour."),
    ("accent", "The accent colour: contrast between heads and pars."),
    ("white", "Open white beams: crisp, cut through the colour."),
    ("cycle", "A new palette colour every bar."),
]

BEAM_FX = [  # what the moving heads' beam itself looks like (gobo wheel, prism, frost)
    ("open", "Plain open beam, no pattern: the sharpest, brightest shaft of light. The DEFAULT for most of the show."),
    ("gobo", "A static gobo pattern: textured beam and patterns on surfaces; changes every four bars."),
    ("gobo_shake", "A shaking gobo: nervous, energetic texture for driving grooves."),
    ("gobo_spin", "The gobo wheel scrolls through all patterns: busy and hypnotic, for long grooves."),
    (
        "gobo_rotate",
        "One gobo pattern (of the chosen style) rotating in place: a turning, kaleidoscopic beam. "
        "Great for breakdowns and builds; speed follows the energy.",
    ),
    ("prism", "A 3-facet prism splits each beam into three: fuller, more beams in the air."),
    (
        "prism_spin",
        "A rotating prism: three beams twisting around each other (mirrored heads turn opposite ways). "
        "For peaks and drops.",
    ),
    (
        "frost",
        "Frost filter: diffuses the beam into a soft, wide wash. RARE exception: it removes the crisp beam "
        "these fixtures are for. At most a single soft moment in an intro or breakdown.",
    ),
]

GOBO_STYLES = [  # only used when the beam effect is a gobo; the engine rotates within the style
    ("dots", "Dots, raster and flakes: breaks the beam into sparkling aerial texture."),
    ("shapes", "Triangles and half-circles: bold graphic shapes on walls and floor."),
    ("rings", "Rings and circles: hypnotic, tunnel-like."),
    ("curves", "Curved, organic lines: smooth and flowing."),
]

DYNAMICS = [
    ("steady", "Even energy through the phrase."),
    ("rise", "Brightness and tension climb through the phrase and beams tilt up: for buildups."),
    ("impact", "White flash accents on big hits and beats: for drops and peaks only."),
]

GROUPINGS = [  # only asked when the rig has several groups of heads (overhead, back, front, towers, ...)
    (
        "unison",
        "All heads act as ONE big line across the whole stage: one mirror, one fan, one wave over all "
        "of them. Massive and unified; the classic big-moment look.",
    ),
    (
        "per_group",
        "Every group does the same movement, but each group as its own unit: its own mirror, fan, "
        "wave or focus point (e.g. each truss focuses its own spot). Structured and architectural.",
    ),
    (
        "split",
        "Two roles: the FEATURED groups do the movement and formation, all other groups do the "
        "counter-movement (movement2/formation2) in a contrasting colour. Depth and contrast.",
    ),
    (
        "solo",
        "Only the FEATURED groups perform; all other heads are dimmed and still. Sparse, focused; great "
        "for intros, breakdowns and to reveal parts of the rig one by one.",
    ),
    (
        "chase",
        "The light runs from group to group on the beat (one group lit at a time, in turn across the "
        "rig) while the heads move per group. Rhythmic, energetic, for grooves and builds.",
    ),
    (
        "individual",
        "Every head moves on its own path (same kind of movement, but each with its own timing "
        "and offset): organic, busy, alive. Great with circle, figure8, ballyhoo or sweep.",
    ),
]

LAYER_SPLITS = [  # layering: which heads carry a dim base layer and which play the accents (multi-group rigs)
    ("none", "No layering: every head plays the same light."),
    (
        "alternate",
        "Every other head in each group holds a soft base glow; the heads in between play the accents. "
        "A carpet of light with hits popping out of it.",
    ),
    (
        "inner_outer",
        "The outer heads of each group hold the base glow; the inner heads play the accents: "
        "a frame with a punchy centre.",
    ),
    (
        "high_low",
        "The high heads (truss, tops of the towers) hold the base glow over the room; the low heads "
        "(floor rows, bottoms of the towers) play the accents. Depth from top to bottom.",
    ),
    ("featured", "The FEATURED groups play the accents; all other groups hold the base glow."),
]

BASE_GLOWS = [
    ("low", "The base layer glows faintly: a subtle carpet, accents stand out strongly."),
    ("medium", "The base layer clearly lights the air: fuller, still leaves room for the accents."),
    ("breathe", "The base layer breathes with the melody and pads: alive but soft."),
]

LASER_LOOKS = [  # only asked when the rig has lasers; lasers always stay ABOVE the audience
    ("off", "Lasers off: save them for the moments that matter (most of an intro, breakdowns, quiet grooves)."),
    ("beams", "A few sharp single beams cutting through the air over the crowd."),
    ("fan", "A dense fan of dozens of beams opening up from each laser: the classic laser fan."),
    (
        "sheet",
        "A flat sheet of beams just above the heads, reaching out over the whole room (liquid sky). "
        "Huge, immersive; for drops and peaks.",
    ),
    ("tunnel", "A hollow cone (tunnel) of light reaching out over the room: hypnotic, for breakdowns and builds."),
    ("cone", "A narrow, dense cone of beams: intense, for peaks."),
    ("wave", "A fan whose beams ripple up and down like a wave on water above the crowd."),
]

LASER_MOVES = [
    ("still", "The laser shape holds still."),
    ("scan", "The shape sweeps left and right over the room with the music."),
    ("rotate", "The shape rotates around its axis (fans spin, tunnels and cones turn); speed follows the energy."),
    ("wave", "The shape rises and falls, always staying above the audience."),
    ("pulse", "Fans and cones open wide on the beat and close in between: breathing with the kick."),
    ("ripple", "The beams of each fan light up one after another, running across the fan on the beat."),
    ("chase", "The lasers fire one after another across the rig, on the beat."),
    (
        "melody",
        "The lasers PLAY the synth melody/riff note for note: every note fires the beams, higher notes "
        "sit higher in the fan, louder notes open it wider. Perfect when a synth line is the hook "
        "(especially laser-like zaps and arps).",
    ),
]

LASER_COLORS = [
    ("base", "All beams in the palette's base colour."),
    ("accent", "All beams in the palette's accent colour."),
    ("white", "White beams: crisp and bright."),
    ("cycle", "One palette colour at a time, changing every bar."),
    ("multi", "The palette's colours spread across the beams of each fan: a gradient (e.g. violet, magenta, blue)."),
    (
        "rainbow",
        "Every beam a different colour (red, yellow, green, cyan, blue, magenta): full multicolour, "
        "the most spectacular; for peaks.",
    ),
]

FOG_LEVELS = [  # smoke machines / hazers (only asked when the rig has one): beams need haze to be seen
    ("none", "No smoke: let the room clear. Intros, outros, and a deliberately clean, crisp moment."),
    ("light", "A thin haze: beams just visible. The default for grooves and calm parts."),
    ("medium", "Clearly hazy: beams stand in the air. Builds and busy parts."),
    (
        "heavy",
        "Thick haze: big beam looks, drops and peaks. Not for long stretches: the crowd still wants to see the DJ.",
    ),
    (
        "burst",
        "A blast of smoke exactly on the downbeat of this phrase, then heavy: the moment a big drop "
        "lands. Rare: a few times per track at most.",
    ),
]


SCREEN_MODES = [  # the LED wall behind the DJ (only asked when the rig has one); a real wall is often dark
    ("off", "Wall dark: the lights carry the show (often the best choice: the wall keeps its impact)."),
    ("ambient", "Dim, slow, soft colour movement in the palette: atmosphere without stealing the show."),
    (
        "figure",
        "A playful outlined character on the beat: a runner, a dancer, a jumping crowd, a pong game. "
        "Fun to watch, light-hearted; great for grooves and builds.",
    ),
    ("words", "Big words: the track title per bar, and a countdown into a drop. Bold and graphic."),
    ("equalizer", "Classic spectrum bars bouncing with the music: simple and direct."),
    ("psychedelic", "Full-screen psychedelic MilkDrop visuals: maximum, for the biggest moments only."),
]

INTENSITY_LEVELS = [
    ("Subtle", "Low brightness, gentle. Quiet or sparse music."),
    ("Medium", "Clearly present but leaves headroom."),
    ("High", "Bright and punchy, most of a dancefloor groove."),
    ("Maximum", "Everything at full. The biggest moments of the set only."),
]

HEAD_TRIGGERS = [("same", "The same hits as the pars.")] + [(v, d) for v, d in TRIGGERS if v != "lead"]

# Look layers in question order: (field name, options, question shown to the model)
SPECIALS = [  # a theme's own look (only offered when the track's title has the theme)
    ("off", "No special look: the layers above are the show."),
    (
        "stars",
        "A STARFIELD over the look: a set of small lights (pixel cells, pars) twinkles here and there in star "
        "white, each star on its own; subtle accents, the rest of the look plays on. A few stars in calm parts, "
        "more in a drop. For the moments that carry a song about stars, not all the time.",
    ),
]

LAYERS = [
    ("par_base", PAR_BASE, "What should the pars do BETWEEN hits?"),
    ("par_accent", PAR_ACCENT, "What should the pars do ON a hit?"),
    ("trigger", TRIGGERS, "Which part of the music counts as a hit for the pars and heads?"),
    ("head_light", HEAD_LIGHT, "How should the moving heads' light behave?"),
    ("movement", MOVEMENTS, "Which path should the moving heads follow?"),
    ("formation", FORMATIONS, "How should the moving heads move relative to each other?"),
    ("aim", AIMS, "Where should the moving heads' beams go?"),
    ("head_color", HEAD_COLOR, "Which colour should the moving heads use?"),
    ("dynamics", DYNAMICS, "What energy curve should the lighting follow during the phrase?"),
    (
        "beam_fx",
        BEAM_FX,
        "What should the moving heads' beams look like? Default to an open beam; pick a gobo, "
        "prism or frost only when this part of the music calls for it.",
    ),
    ("gobo_style", GOBO_STYLES, "IF the beam uses a gobo: which kind of pattern fits? (Ignored for other beams.)"),
    (
        "head_trigger",
        HEAD_TRIGGERS,
        "What should the moving heads' light pulse on? It can differ from the pars: "
        "layering works great, e.g. heads on the kick (1/4) while the pars follow a "
        "1/8 synth riff, or the other way round.",
    ),
]
