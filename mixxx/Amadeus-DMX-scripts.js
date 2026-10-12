// Amadeus DMX: every deck's state, 50 times a second, as SysEx to the "Amadeus DMX" MIDI port.
//
//   F0 7D 44 4C 01 01 deck flags pos[5] samples[5] rate[3] ratio[4] bpm[4] vol[2] seq[2] F7   a deck
//   F0 7D 44 4C 01 02 xfader[2] F7                                                            the crossfader
//
// Numbers are unsigned, big-endian, 7 bits per byte. flags: 1 play, 2 loaded, 4 loop, 8/16 orientation
// (0 left, 1 centre, 2 right). pos: milliseconds + 2^30 (a deck can stand before the track's start).
// samples: the track's length in samples (all channels), rate: its sample rate; together they identify the
// track in Mixxx's library. ratio: playback speed × 1e6 + 2^27. bpm × 1000. vol, xfader: 0..16383.

var AmadeusDMX = {};

AmadeusDMX.DECKS = 4;
AmadeusDMX.seq = 0;

AmadeusDMX.u7 = function (value, bytes) {
    var out = [];
    value = Math.max(0, Math.round(value));
    for (var i = bytes - 1; i >= 0; i--) {
        out.push(Math.floor(value / Math.pow(128, i)) % 128);
    }
    return out;
};

AmadeusDMX.send = function (body) {
    var msg = [0xF0, 0x7D, 0x44, 0x4C, 0x01].concat(body, [0xF7]);
    midi.sendSysexMsg(msg, msg.length);
};

AmadeusDMX.deck = function (n) {
    var g = "[Channel" + n + "]";
    var loaded = engine.getValue(g, "track_loaded");
    if (!loaded) {
        return;
    }
    var u7 = AmadeusDMX.u7;
    var flags = (engine.getValue(g, "play") ? 1 : 0) | 2 | (engine.getValue(g, "loop_enabled") ? 4 : 0) |
        (engine.getValue(g, "orientation") << 3);
    var pos = engine.getValue(g, "playposition") * engine.getValue(g, "duration") * 1000;
    AmadeusDMX.seq = (AmadeusDMX.seq + 1) % 16384;
    AmadeusDMX.send([0x01, n, flags].concat(
        u7(pos + 1073741824, 5),
        u7(engine.getValue(g, "track_samples"), 5),
        u7(engine.getValue(g, "track_samplerate"), 3),
        u7(engine.getValue(g, "rate_ratio") * 1e6 + 134217728, 4),
        u7(engine.getValue(g, "bpm") * 1000, 4),
        u7(engine.getValue(g, "volume") * 16383, 2),
        u7(AmadeusDMX.seq, 2)
    ));
};

AmadeusDMX.tick = function () {
    for (var n = 1; n <= AmadeusDMX.DECKS; n++) {
        AmadeusDMX.deck(n);
    }
    AmadeusDMX.send([0x02].concat(AmadeusDMX.u7((engine.getValue("[Master]", "crossfader") + 1) / 2 * 16383, 2)));
};

AmadeusDMX.init = function () {
    var decks = engine.getValue("[App]", "num_decks") || engine.getValue("[Master]", "num_decks");
    AmadeusDMX.DECKS = Math.min(Math.max(decks, 2), 4);
    AmadeusDMX.connections = [];
    for (var n = 1; n <= AmadeusDMX.DECKS; n++) {
        ["play", "track_loaded", "loop_enabled"].forEach(function (key) {  // these right away, not on the next tick
            AmadeusDMX.connections.push(engine.makeConnection("[Channel" + n + "]", key,
                function (value, group) { AmadeusDMX.deck(parseInt(group.substring(8), 10)); }));
        });
    }
    AmadeusDMX.timer = engine.beginTimer(20, AmadeusDMX.tick);
};

AmadeusDMX.shutdown = function () {
    engine.stopTimer(AmadeusDMX.timer);
    AmadeusDMX.connections.forEach(function (c) { c.disconnect(); });
};
