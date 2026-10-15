// The LED wall behind the DJ. Like a real one it is often dark: the director picks per phrase what it shows
// (decision.screen): off | ambient | figure | words | equalizer | psychedelic.
//
//  - figure: playful outlined characters on the beat (a runner, a dancer, a jumping crowd, pong)
//  - words: the track title one word per beat
//  - equalizer: classic spectrum bars
//  - psychedelic: Butterchurn (MilkDrop in WebGL, MIT), only for the biggest moments
//  - ambient: dim, slow colour in the palette
// Into a drop the wall counts down 4-3-2-1 and shouts DROP!.
//
// The browser doesn't have the music, so everything runs on the show's own beat position (frame.bp) and
// spectrum bands; Butterchurn gets a synthetic signal made from those bands.
"use strict";

const Screen = (() => {
  const W = 640, H = 360, SAMPLES = 1024, SR = 44100;
  const TONES = [{f: 48, k: 1.0}, {f: 110, k: 0.9}, {f: 700, k: 0.6}, {f: 3200, k: 0.45}, {f: 9000, k: 0.3}];
  const FIGURES = ["runner", "dancer", "crowd", "pong"];
  const RULES = {  // for plans made before the director chose wall modes (same idea as RULE_SCREEN)
    intro: ["off", "ambient"], groove: ["off", "figure", "equalizer", "off", "figure", "words"],
    buildup: ["words", "figure"], drop: ["psychedelic", "figure", "equalizer"],
    breakdown: ["ambient", "off", "figure"], outro: ["ambient", "off"],
  };

  // ---------------------------------------------------------------- Butterchurn (psychedelic)
  let viz = null, bcCanvas = null, presets = null, names = [], phase = TONES.map(() => 0), bcFailed = false;
  let bcPhrase = -1;
  const td = new Uint8Array(SAMPLES);

  function initButterchurn() {
    if (viz || bcFailed) return !!viz;
    try {
      const bc = window.butterchurn?.default || window.butterchurn;
      const presetLib = window.butterchurnPresets?.default || window.butterchurnPresets;
      bcCanvas = document.createElement("canvas");
      bcCanvas.width = W; bcCanvas.height = H;
      const audio = new (window.AudioContext || window.webkitAudioContext)();  // required, never played
      viz = bc.createVisualizer(audio, bcCanvas, {width: W, height: H, pixelRatio: 1, textureRatio: 1});
      presets = {...presetLib.getPresets(), ...(window.butterchurnPresetsExtra?.getPresets?.() || {})};
      names = Object.keys(presets).sort();
      viz.loadPreset(presets[names[0]], 0);
    } catch (e) {
      console.warn("psychedelic visuals unavailable:", e);
      bcFailed = true;
    }
    return !!viz;
  }

  function synth(bands, dt) {
    // 1024 samples of a waveform whose spectrum matches the bands (0..1 each)
    td.fill(128);
    const amps = TONES.map((t, i) => (bands[i] || 0) * t.k);
    for (let n = 0; n < SAMPLES; n++) {
      let v = 0;
      for (let i = 0; i < TONES.length; i++) v += amps[i] * Math.sin(phase[i] + 2 * Math.PI * TONES[i].f * n / SR);
      v += (Math.random() - 0.5) * 0.25 * (amps[3] + amps[4]);   // some hiss for the hi-hats
      td[n] = Math.max(0, Math.min(255, 128 + v * 38));
    }
    TONES.forEach((t, i) => { phase[i] = (phase[i] + 2 * Math.PI * t.f * dt) % (2 * Math.PI); });
  }

  function psychedelic(f, d, dt) {
    if (!initButterchurn()) return null;
    if (f.phrase !== bcPhrase) {
      bcPhrase = f.phrase;
      viz.loadPreset(presets[names[hash(f.phrase, 7) % names.length]], d?.section === "drop" ? 0.4 : 2.5);
    }
    synth(f.bands || [], dt);
    viz.render({audioLevels: {timeByteArray: td, timeByteArrayL: td, timeByteArrayR: td}});
    return bcCanvas;
  }

  // ---------------------------------------------------------------- the 2D scenes
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d");
  let eq = new Array(16).fill(0), caps = new Array(16).fill(0), amb = 0;

  function hash(n, salt = 0) { return Math.abs(((n + 1) * 2654435761 + salt * 40503) % 4294967296); }
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, k) => a + (b - a) * k;
  const css = c => `rgb(${c.map(v => Math.round(clamp(v) * 255)).join(",")})`;
  function colours(d) {
    const pal = (typeof PALETTES !== "undefined" && PALETTES[d?.palette]) || [[1, 0.3, 0.8], [0.2, 0.7, 1]];
    // brighten towards white a little: outlines must read on a dark wall
    return pal.map(c => { const m = Math.max(...c, 0.01); return c.map(v => clamp(0.25 + 0.75 * v / m)); });
  }

  function neon(col, width) {
    g.strokeStyle = css(col); g.fillStyle = css(col); g.lineWidth = width;
    g.lineCap = "round"; g.lineJoin = "round";
    g.shadowColor = css(col); g.shadowBlur = width * 2.2;
  }

  // a stick figure: hip at (x, y), size s (about its height), angles in radians, 0 = hanging straight down,
  // positive = towards +x. pose: {lean, arms: [[shoulder, elbow], [shoulder, elbow]], legs: [[hip, knee], ...]}
  function figure(x, y, s, p) {
    const seg = (x0, y0, a, len) => [x0 + len * Math.sin(a), y0 + len * Math.cos(a)];
    const limb = (x0, y0, [a1, a2], len) => {
      const [x1, y1] = seg(x0, y0, a1, len), [x2, y2] = seg(x1, y1, a1 + a2, len);
      g.moveTo(x0, y0); g.lineTo(x1, y1); g.lineTo(x2, y2);
    };
    const lean = p.lean || 0;
    const nx = x + Math.sin(lean) * s * 0.42, ny = y - Math.cos(lean) * s * 0.42;  // neck
    const r = s * 0.11;
    g.beginPath();
    g.moveTo(x, y); g.lineTo(nx, ny);
    for (const a of p.arms) limb(nx - Math.sin(lean) * s * 0.04, ny + s * 0.04, a, s * 0.21);
    for (const l of p.legs) limb(x, y, l, s * 0.26);
    g.stroke();
    g.beginPath();
    const hx = nx + Math.sin(lean + (p.head || 0)) * r * 1.25, hy = ny - Math.cos(lean + (p.head || 0)) * r * 1.25;
    g.arc(hx, hy, r, 0, Math.PI * 2);
    g.stroke();
    return [hx, hy, r];
  }

  // the runner: runs over a scrolling city, jumps the hurdles that come by on the bar
  function runner(f, d, cols, bp, bass) {
    const s = 150, gy = 300, drop = d?.section === "drop";
    const scroll = bp * (drop ? 90 : 60);
    neon(cols[1 % cols.length], 2);
    g.globalAlpha = 0.45;
    g.beginPath();  // skyline, slower (parallax)
    for (let i = -1; i < 12; i++) {
      const x = i * 70 - (scroll * 0.3) % 70, h = 40 + (hash(i + Math.floor(scroll * 0.3 / 70)) % 90);
      g.moveTo(x, gy); g.lineTo(x, gy - h); g.lineTo(x + 52, gy - h); g.lineTo(x + 52, gy);
    }
    g.stroke();
    g.globalAlpha = 1;
    neon(cols[0], 3);
    g.beginPath(); g.moveTo(0, gy); g.lineTo(W, gy); g.stroke();
    // a hurdle every bar, arriving at the runner (x = 230) on the downbeat
    const bar = bp / 4, hx = 230 + (Math.ceil(bar) - bar) * 4 * (drop ? 90 : 60);
    g.beginPath(); g.moveTo(hx, gy); g.lineTo(hx, gy - 38); g.moveTo(hx - 14, gy - 38); g.lineTo(hx + 14, gy - 38);
    g.stroke();
    // the jump: half a beat either side of the downbeat
    const fromDown = ((bp + 0.5) % 4) - 0.5, jump = Math.abs(fromDown) < 0.5 ? Math.cos(fromDown * Math.PI) : 0;
    const w = bp * Math.PI;  // one stride per 2 beats: a footfall on every beat
    const pose = jump > 0.05 ? {
      lean: 0.35, arms: [[-2.4, 0.3], [2.6, -0.2]], legs: [[1.3, -1.9], [-0.4, -1.2]],
    } : {
      lean: drop ? 0.35 : 0.22,
      arms: [[-0.9 * Math.sin(w), 1.5], [0.9 * Math.sin(w), 1.5]],
      legs: [[0.75 * Math.sin(w), -0.2 - 1.1 * Math.max(0, Math.sin(w + 1.2))],
             [-0.75 * Math.sin(w), -0.2 - 1.1 * Math.max(0, -Math.sin(w + 1.2))]],
    };
    const y = gy - s * 0.5 - Math.abs(Math.cos(w)) * 6 - jump * 70;
    neon(cols[0], 5);
    const [hx2, hy2, r] = figure(230, y, s, pose);
    if (drop || bass > 0.7) {  // speed lines and a drop of sweat: going all out
      g.lineWidth = 2; g.beginPath();
      for (let i = 0; i < 4; i++) { const ly = y - 40 + i * 22; g.moveTo(150 - i * 12, ly); g.lineTo(110 - i * 20, ly); }
      g.stroke();
      const t = (bp % 1);
      g.beginPath(); g.arc(hx2 - r - 6 - t * 20, hy2 - r + t * 25, 3, 0, 7); g.fill();
    }
  }

  // the dancer: a new move on every beat; on a drop it jumps with its arms in the air
  const MOVES = {
    down: [[-0.25, 0.2], [0.25, -0.2]], up: [[-2.6, 0], [2.6, 0]], hips: [[-0.9, 1.9], [0.9, -1.9]],
    disco: [[-0.5, 1.5], [2.75, 0]], disco2: [[-2.75, 0], [0.5, -1.5]], robot: [[-1.57, -1.57], [1.57, 1.57]],
    robot2: [[-1.57, 1.57], [1.57, -1.57]], clap: [[-2.9, 0.6], [2.9, -0.6]], point: [[-0.3, 0.2], [1.6, 0]],
  };
  const ROUTINES = [["disco", "down", "disco", "down"], ["robot", "robot2", "robot", "robot2"],
                    ["hips", "clap", "hips", "clap"], ["point", "disco2", "point", "up"],
                    ["up", "down", "up", "clap"]];
  let fromPose = MOVES.down, lastBeat = -1;
  function dancer(f, d, cols, bp, bass) {
    const beat = Math.floor(bp), u = bp - beat, drop = d?.section === "drop";
    const routine = ROUTINES[hash(Math.floor(beat / 8), 3) % ROUTINES.length];
    const want = drop && beat % 4 === 0 ? MOVES.up : MOVES[routine[beat % 4]];
    if (beat !== lastBeat) { fromPose = MOVES[routine[(beat + 3) % 4]]; lastBeat = beat; }
    const k = clamp(u / 0.18);  // snap into the move just after the beat
    const arms = want.map((a, i) => a.map((v, j) => lerp(fromPose[i][j], v, k)));
    const dip = Math.sin(u * Math.PI);  // knees pump on every beat
    const hop = drop && beat % 4 === 0 ? Math.sin(u * Math.PI) * 60 : 0;
    const legs = hop ? [[-0.6, 1.4], [0.6, -1.4]] : [[-0.25 - 0.25 * dip, 0.5 * dip], [0.25 + 0.25 * dip, -0.5 * dip]];
    // dance floor: tiles lighting up with the beat
    for (let i = 0; i < 8; i++) {
      const on = (hash(i + beat * 8, 1) % 3) === 0;
      neon(cols[i % cols.length], 2);
      g.globalAlpha = on ? 0.55 : 0.12;
      const x0 = 320 + (i - 4) * 70, x1 = x0 + 70;
      g.beginPath(); g.moveTo(x0 + (x0 - 320) * 0.4, 345); g.lineTo(x1 + (x1 - 320) * 0.4, 345);
      g.lineTo(x1, 300); g.lineTo(x0, 300); g.closePath(); g.stroke();
    }
    g.globalAlpha = 1;
    neon(cols[0], 6);
    figure(320, 205 - dip * 8 - hop, 190, {lean: 0, head: 0.15 * Math.sin(bp * Math.PI), arms, legs});
    if (hop) { neon(cols[1 % cols.length], 4); g.font = "bold 46px system-ui"; g.fillText("!", 395, 70 - hop * 0.3); }
  }

  // the crowd: a row of little people jumping (a wave in the groove, all together on a drop), one crowd surfer
  function crowd(f, d, cols, bp, bass, phraseFrac) {
    const n = 11, drop = d?.section === "drop", hands = drop || (d?.intensity ?? 1) >= 2;
    for (let i = 0; i < n; i++) {
      const x = 40 + i * (560 / (n - 1)), s = 105 + (hash(i, 5) % 25);
      const u = drop ? bp % 1 : (bp - i * 0.12) % 1;
      const jump = Math.max(0, Math.sin(u * Math.PI)) * (drop ? 40 : 14 + 22 * bass);
      const wave = hands ? 0.25 * Math.sin(bp * Math.PI + i) : 0;
      neon(cols[i % cols.length], 3);
      const y = 345 - s * 0.5 - jump;
      figure(x, y, s, {
        lean: 0, arms: hands ? [[-2.7 + wave, 0], [2.7 + wave, 0]] : [[-0.3, 0.4], [0.3, -0.4]],
        legs: jump > 4 ? [[-0.5, 0.6], [0.5, -0.6]] : [[-0.2, 0], [0.2, 0]],
      });
    }
    if (hands) {  // crowd surfer: lying on the raised hands, carried across during the phrase
      const x = 20 + phraseFrac * 600, y = 128 + 4 * Math.sin(bp * Math.PI);
      neon(cols[0], 4);
      g.save(); g.translate(x, y); g.rotate(-Math.PI / 2);
      figure(0, 0, 80, {lean: 0, arms: [[-2.9, 0], [2.6, 0.3]],
                        legs: [[-0.25 + 0.3 * Math.sin(bp * 2), 0.3], [0.25, 0]]});
      g.restore();
    }
  }

  // pong: the ball reaches a bat on every beat; on a drop it splits into three
  function pong(f, d, cols, bp) {
    const drop = d?.section === "drop", tri = v => 1 - Math.abs(((v % 2) + 2) % 2 - 1);
    neon(cols[0], 3);
    g.setLineDash([10, 14]); g.beginPath(); g.moveTo(320, 10); g.lineTo(320, 350); g.stroke(); g.setLineDash([]);
    g.font = "bold 54px ui-monospace, monospace"; g.textAlign = "center";
    g.fillText(String(Math.floor(bp / 4) % 100), 250, 70);
    g.fillText(String(Math.floor(bp / 7) % 100), 390, 70);
    const balls = drop ? [0, 0.33, 0.66] : [0];
    let yL = 180, yR = 180;
    balls.forEach((o, i) => {
      const x = 52 + tri(bp + o) * 536, y = 20 + tri(bp * 0.37 + o * 1.7 + 0.3) * 320;
      neon(cols[i % cols.length], 3);
      g.fillRect(x - 8, y - 8, 16, 16);
      if (x < 320) yL = y; else yR = y;
    });
    neon(cols[0], 3);
    g.fillRect(28, yL - 40, 12, 80);
    g.fillRect(600, yR - 40, 12, 80);
  }

  function cleanTitle(track) {
    return (track || "").replace(/^Deck \w+:\s*/, "").replace(/\.[a-z0-9]{2,4}$/i, "")
      .replace(/^\d+\s*[-_.]\s*/, "").replace(/[\[(].*?[\])]/g, "").replace(/[_]+/g, " ").trim();
  }

  // words: the title, one word per beat, popping in
  function words(f, d, cols, bp) {
    const ws = cleanTitle(S?.track).split(/\s+|\s*-\s*/).filter(Boolean);
    if (!ws.length) return;
    const beat = Math.floor(bp), u = bp - beat, w = ws[beat % ws.length].toUpperCase();
    const size = Math.min(170, 1000 / Math.max(3, w.length)) * (1 + 0.25 * Math.max(0, 1 - u * 4));
    neon(cols[beat % cols.length], 5);
    g.font = `900 ${size}px system-ui`; g.textAlign = "center"; g.textBaseline = "middle";
    g.strokeText(w, 320, 180);
    if (u < 0.15) { g.globalAlpha = 0.6; g.fillText(w, 320, 180); g.globalAlpha = 1; }
  }

  function equalizer(f, d, cols, dt) {
    const b = f.bands || [];
    for (let i = 0; i < eq.length; i++) {
      const pos = i / (eq.length - 1) * Math.max(b.length - 1, 1), j = Math.floor(pos), k = pos - j;
      const v = clamp(lerp(b[j] || 0, b[j + 1] ?? b[j] ?? 0, k) * (0.85 + 0.3 * Math.sin(i * 2.3 + performance.now() / 180)));
      eq[i] = v > eq[i] ? v : eq[i] - dt * 2.2;
      caps[i] = Math.max(eq[i], caps[i] - dt * 0.6);
    }
    const bw = W / eq.length;
    eq.forEach((v, i) => {
      neon(cols[Math.floor(i / eq.length * cols.length)], 3);
      const h = v * 300, x = i * bw + 6;
      for (let y = 340; y > 340 - h; y -= 16) g.strokeRect(x, y - 12, bw - 12, 10);
      g.fillRect(x, 330 - caps[i] * 300 - 8, bw - 12, 4);
    });
  }

  function ambient(f, d, cols, dt) {
    amb += dt * 0.15;
    g.shadowBlur = 0;
    cols.forEach((c, i) => {
      const x = 320 + 230 * Math.sin(amb * (0.7 + i * 0.23) + i * 2), y = 180 + 110 * Math.cos(amb * (0.5 + i * 0.17) + i);
      const r = g.createRadialGradient(x, y, 0, x, y, 260);
      r.addColorStop(0, `rgba(${c.map(v => Math.round(v * 255)).join(",")},0.5)`); r.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = r; g.fillRect(0, 0, W, H);
    });
  }

  // 4-3-2-1 into a drop, then DROP!
  function countdown(f, d, cols, bp) {
    const plan = S?.plan || [], next = plan[f.phrase + 1], spb = 60 / (S?.bpm || 120);
    let text = null, u = 0;
    if (next && next.section === "drop" && d?.section !== "drop") {
      const left = (next.start - f.t) / spb;
      if (left > 0 && left <= 4) { text = String(Math.ceil(left)); u = 1 - (left % 1 || 1); }
    }
    if (d?.section === "drop" && f.t - d.start < spb * 2) { text = "DROP!"; u = (f.t - d.start) / (spb * 2); }
    if (!text) return false;
    g.fillStyle = "rgba(0,0,0,0.85)"; g.shadowBlur = 0; g.fillRect(0, 0, W, H);
    neon(cols[0], 7);
    g.font = `900 ${text.length > 1 ? 150 : 230 * (1.3 - 0.3 * u)}px system-ui`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.strokeText(text, 320, 185);
    return true;
  }

  // ---------------------------------------------------------------- what to show, with fades
  let S = null;  // the show (hello message)
  let cur = {mode: "off", scene: null}, fade = 0, level = 0;

  const force = new URLSearchParams(location.search).get("wall");  // ?wall=runner etc.: try out one scene

  function wanted(f, d) {
    if (force) return {mode: FIGURES.includes(force) ? "figure" : force, scene: force};
    let mode = d?.screen;
    if (!mode) { const opts = RULES[d?.section] || ["off"]; mode = opts[hash(f.phrase, 2) % opts.length]; }
    const scene = mode === "figure" ? FIGURES[hash(f.phrase, 9) % FIGURES.length] : mode;
    return {mode, scene};
  }

  // called every frame; returns {canvas, level, tint} (or null for a rig without a wall)
  function update(f, show_, dt) {
    if (!f || !show_?.screen) return null;
    S = show_;
    const d = show_.plan?.[f.phrase];
    const want = wanted(f, d);
    // the show arc's LED wall knob (live mode): dimmer, below half only calm colour, at zero off
    const wall = !force && f.arc?.on ? (f.arc.values?.screen ?? 1) : 1;
    if (wall < 0.03) want.mode = want.scene = "off";
    else if (wall < 0.5 && want.mode !== "off") want.mode = want.scene = "ambient";
    const nextDrop = show_.plan?.[f.phrase + 1]?.section === "drop" && d?.section !== "drop";
    const beatsLeft = nextDrop ? (show_.plan[f.phrase + 1].start - f.t) * (show_.bpm || 120) / 60 : 99;
    if (want.mode === "off" && beatsLeft <= 4.5 && wall >= 0.5) want.mode = want.scene = "words";  // a dark wall wakes up to count in
    const shout = wall >= 0.5 && d?.section === "drop" && cur.mode !== "off" && cur.mode !== "psychedelic"
      && (f.t - d.start) * (show_.bpm || 120) / 60 < 2;
    if (shout) fade = 1;  // DROP! at full strength; the drop's own scene comes after it
    else if (want.scene !== cur.scene) {
      fade = Math.max(0, fade - dt * 5);
      if (fade === 0) cur = want;
    } else fade = Math.min(1, fade + dt * (d?.section === "drop" ? 6 : 1.5));

    const bp = f.bp ?? f.t * (show_.bpm || 120) / 60;
    const bands = f.bands || [], bass = clamp(((bands[0] || 0) + (bands[1] || 0)) / 2);
    const cols = colours(d);
    let canvas = cv, tint = false, target;
    if (cur.mode === "psychedelic") {
      canvas = psychedelic(f, d, dt) || cv; tint = true;
      // brightness follows the rig (dark in the blackout before a drop)
      const fx = f.fx || [];
      const mean = fx.length ? fx.reduce((t, x) => t + Math.min(1, x[0] + x[4]), 0) / fx.length : 0;
      target = mean < 0.01 ? 0.05 : Math.min(1, 0.3 + 1.4 * mean);
    } else {
      g.save();
      g.shadowBlur = 0; g.globalAlpha = 1;
      // a short trail behind moving lines, its fade set per 1/60 s: as short at any refresh rate
      const fadeShare = cur.scene === "words" ? 0.8 : 0.45;
      g.fillStyle = `rgba(0,0,0,${1 - Math.pow(1 - fadeShare, Math.max(dt, 1 / 240) * 60)})`;
      g.fillRect(0, 0, W, H);
      const phraseFrac = d ? clamp((f.t - d.start) / Math.max(d.end - d.start, 1)) : 0;
      if (!(cur.mode !== "off" && countdown(f, d, cols, bp))) {
        if (cur.scene === "runner") runner(f, d, cols, bp, bass);
        else if (cur.scene === "dancer") dancer(f, d, cols, bp, bass);
        else if (cur.scene === "crowd") crowd(f, d, cols, bp, bass, phraseFrac);
        else if (cur.scene === "pong") pong(f, d, cols, bp);
        else if (cur.scene === "words") words(f, d, cols, bp);
        else if (cur.scene === "equalizer") equalizer(f, d, cols, dt);
        else if (cur.scene === "ambient") ambient(f, d, cols, dt);
      }
      g.restore();
      target = cur.mode === "off" ? 0 : cur.mode === "ambient" ? 0.4 : 0.95;
    }
    level += (target * Math.min(1, wall * 2) * fade - level) * Math.min(1, dt * 10);
    return {canvas, level, tint};
  }

  return {update};
})();
