// Decisive Lightning: every deck's state, 50 times a second, as SysEx to the "Decisive Lightning" MIDI port.
//
//   F0 7D 44 4C 01 01 deck flags pos[5] samples[5] rate[3] ratio[4] bpm[4] vol[2] seq[2] F7   a deck
//   F0 7D 44 4C 01 02 xfader[2] F7                                                            the crossfader
//
// Numbers are unsigned, big-endian, 7 bits per byte. flags: 1 play, 2 loaded, 4 loop, 8/16 orientation
// (0 left, 1 centre, 2 right). pos: milliseconds + 2^30 (a deck can stand before the track's start).
// samples: the track's length in samples (all channels), rate: its sample rate; together they identify the
// track in Mixxx's library. ratio: playback speed × 1e6 + 2^27. bpm × 1000. vol, xfader: 0..16383.

var DecisiveLightning = {};

DecisiveLightning.DECKS = 4;
DecisiveLightning.seq = 0;

DecisiveLightning.u7 = function (value, bytes) {
    var out = [];
    value = Math.max(0, Math.round(value));
    for (var i = bytes - 1; i >= 0; i--) {
        out.push(Math.floor(value / Math.pow(128, i)) % 128);
    }
    return out;
};

DecisiveLightning.send = function (body) {
    var msg = [0xF0, 0x7D, 0x44, 0x4C, 0x01].concat(body, [0xF7]);
    midi.sendSysexMsg(msg, msg.length);
};

DecisiveLightning.deck = function (n) {
    var g = "[Channel" + n + "]";
    var loaded = engine.getValue(g, "track_loaded");
    if (!loaded) {
        return;
    }
    var u7 = DecisiveLightning.u7;
    var flags = (engine.getValue(g, "play") ? 1 : 0) | 2 | (engine.getValue(g, "loop_enabled") ? 4 : 0) |
        (engine.getValue(g, "orientation") << 3);
    var pos = engine.getValue(g, "playposition") * engine.getValue(g, "duration") * 1000;
    DecisiveLightning.seq = (DecisiveLightning.seq + 1) % 16384;
    DecisiveLightning.send([0x01, n, flags].concat(
        u7(pos + 1073741824, 5),
        u7(engine.getValue(g, "track_samples"), 5),
        u7(engine.getValue(g, "track_samplerate"), 3),
        u7(engine.getValue(g, "rate_ratio") * 1e6 + 134217728, 4),
        u7(engine.getValue(g, "bpm") * 1000, 4),
        u7(engine.getValue(g, "volume") * 16383, 2),
        u7(DecisiveLightning.seq, 2)
    ));
};

DecisiveLightning.tick = function () {
    for (var n = 1; n <= DecisiveLightning.DECKS; n++) {
        DecisiveLightning.deck(n);
    }
    DecisiveLightning.send([0x02].concat(DecisiveLightning.u7((engine.getValue("[Master]", "crossfader") + 1) / 2 * 16383, 2)));
};

DecisiveLightning.init = function () {
    var decks = engine.getValue("[App]", "num_decks") || engine.getValue("[Master]", "num_decks");
    DecisiveLightning.DECKS = Math.min(Math.max(decks, 2), 4);
    DecisiveLightning.connections = [];
    for (var n = 1; n <= DecisiveLightning.DECKS; n++) {
        ["play", "track_loaded", "loop_enabled"].forEach(function (key) {  // these right away, not on the next tick
            DecisiveLightning.connections.push(engine.makeConnection("[Channel" + n + "]", key,
                function (value, group) { DecisiveLightning.deck(parseInt(group.substring(8), 10)); }));
        });
    }
    DecisiveLightning.timer = engine.beginTimer(20, DecisiveLightning.tick);
};

DecisiveLightning.shutdown = function () {
    engine.stopTimer(DecisiveLightning.timer);
    DecisiveLightning.connections.forEach(function (c) { c.disconnect(); });
};
