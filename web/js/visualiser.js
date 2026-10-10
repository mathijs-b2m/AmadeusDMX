const PALETTES = {
  warm: [[1,.45,0],[1,.15,0],[.9,0,.05],[1,.7,.2]],
  cool: [[0,.3,1],[0,.8,1],[.45,0,1],[.1,.1,.9]],
  neon: [[1,0,.8],[.4,1,0],[0,1,.9],[.8,0,1]],
  fire: [[1,0,0],[1,.35,0],[1,.9,.7],[.8,.05,0]],
  ice:  [[.85,.95,1],[.3,.8,1],[.1,.35,1],[1,1,1]],
};
const SECTIONS = ["intro","groove","buildup","drop","breakdown","outro"];
const BANDS = ["sub","bass","mid","high","air"];
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = t => `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,"0")}`;
const rgb = (c, a=1) => `rgba(${c.map(v => Math.round(Math.min(1, v) * 255)).join(",")},${a})`;

let show = null, frame = null, shownPhrase = -1;

// ---------- static UI
$("meters").innerHTML = BANDS.map(b => `<div class="meter"><div class="tube"><b id="m-${b}"></b></div><span>${b}</span></div>`).join("");
$("legend").innerHTML = SECTIONS.map(s => `<span><i style="background:var(--${s})"></i>${s}</span>`).join("");

function onHello(msg) {
  show = msg;
  // how big the rig is: the camera, floor grid and back wall follow (a DJ booth or a 16 m truss grid)
  const ps = msg.fixtures.map(f => f.pos);
  show.ext = {top: Math.max(2, ...ps.map(p => p[2])), back: Math.min(-1, ...ps.map(p => p[1])) - 1.5};
  $("waiting").style.display = "none";
  $("track").textContent = msg.track;
  $("bpm").textContent = `${msg.bpm} BPM`;
  const dir = $("director");
  dir.textContent = msg.director === "openai" ? "Decisions API · gpt-6-luna" : "rule-based director";
  dir.className = "badge " + msg.director;
  const tl = $("timeline");
  tl.querySelectorAll(".seg").forEach(e => e.remove());
  msg.plan.forEach((d, i) => {
    const seg = document.createElement("div");
    seg.className = "seg"; seg.id = `seg-${i}`;
    seg.style.flex = `${d.end - d.start} 0 0`;
    seg.style.background = `var(--${d.section})`;
    seg.title = `${fmt(d.start)}  ${d.section}${(d.drop_score || 0) >= 0.6 ? " ⚡ drop" : ""} · pars ${d.par_base} + ${d.par_accent} on ${d.trigger} · heads ${d.head_light} / ${d.movement} / ${d.formation} / ${d.aim} / ${d.head_color} / ${d.beam_fx} · ${d.dynamics} · ${d.palette}`;
    tl.insertBefore(seg, $("playhead"));
  });
  // a leading gap before the first phrase
  const lead = document.createElement("div");
  lead.className = "seg"; lead.style.flex = `${msg.plan[0]?.start || 0} 0 0`; lead.style.background = "var(--line)";
  tl.insertBefore(lead, tl.firstChild);
  const tail = msg.duration - (msg.plan.at(-1)?.end || msg.duration);
  if (tail > 0) { const t = document.createElement("div"); t.className = "seg"; t.style.flex = `${tail} 0 0`; t.style.background = "var(--line)"; tl.insertBefore(t, $("playhead")); }
  shownPhrase = -1;
  drawEnergy();
}

function drawEnergy() {
  const c = $("energy"), r = c.getBoundingClientRect();
  c.width = r.width * devicePixelRatio; c.height = r.height * devicePixelRatio;
  const g = c.getContext("2d"), W = c.width, H = c.height, e = show.energy || [];
  g.clearRect(0, 0, W, H);
  // loudness as a filled curve
  g.beginPath(); g.moveTo(0, H);
  e.forEach((v, i) => g.lineTo(i / (e.length - 1) * W, H - v * H * 0.9));
  g.lineTo(W, H); g.closePath();
  g.fillStyle = "rgba(255,255,255,0.18)"; g.fill();
  g.strokeStyle = "rgba(255,255,255,0.55)"; g.lineWidth = devicePixelRatio; g.stroke();
  // ⚡ at detected drops
  g.font = `${13 * devicePixelRatio}px system-ui`; g.textAlign = "center";
  show.plan.filter(d => (d.drop_score || 0) >= 0.6).forEach(d => {
    const x = d.start / show.duration * W;
    g.fillStyle = "#fff"; g.fillRect(x - devicePixelRatio, 0, 2 * devicePixelRatio, H);
    g.fillText("⚡", x + 9 * devicePixelRatio, 15 * devicePixelRatio);
  });
}
addEventListener("resize", () => show && drawEnergy());

function showDecision(i) {
  const d = show.plan[i];
  document.querySelectorAll(".seg.active").forEach(e => e.classList.remove("active"));
  $(`seg-${i}`)?.classList.add("active");
  const c = k => d.confidence?.[k] != null ? `<span class="conf">${Math.round(d.confidence[k] * 100)}%</span>` : "";
  $("d-section").innerHTML = `<span style="color:var(--${d.section})">●</span> ${d.section}${c("section")}`;
  const LAYERS = ["par_base", "par_accent", "trigger", "head_light", "movement", "formation", "aim", "head_color", "beam_fx", "gobo_style", "dynamics", "head_trigger"];
  LAYERS.forEach(k => $(`d-${k}`).innerHTML = String(d[k]).replaceAll("_", " ") + c(k));
  $("d-palette").innerHTML = `${d.palette}<span class="swatches">${(PALETTES[d.palette] || []).map(x => `<i style="background:${rgb(x)}"></i>`).join("")}</span>${c("palette")}`;
  $("d-intensity").innerHTML = `<span class="pip">${[0,1,2,3].map(k => `<i class="${k <= d.intensity ? "on" : ""}"></i>`).join("")}</span>${c("intensity")}`;
  $("d-source").textContent = { openai: "Decisions API", "openai+hold": "API (unsure → held previous look)", rules: "rule-based" }[d.source] || d.source;
  const probs = Object.entries(d.probabilities?.par_accent || {}).sort((a, b) => b[1] - a[1]);
  $("probs").innerHTML = probs.length
    ? `<div class="note" style="margin:0 0 6px">How sure: pars on a hit</div>` + probs.map(([k, p]) =>
        `<div class="prob"><span>${k.replace("_", " ")}</span><span class="bar"><b style="width:${p * 100}%"></b></span><span class="n">${Math.round(p * 100)}%</span></div>`).join("")
    : `<div class="note" id="rulesNote">${rulesNote()}</div>`;
  $("prompt").textContent = d.prompt || "(rule-based: no prompt)";
}

// ---------- stage rendering
const cv = $("stage"), ctx = cv.getContext("2d");
function resize() { const r = cv.getBoundingClientRect(); cv.width = r.width * devicePixelRatio; cv.height = r.height * devicePixelRatio; }
addEventListener("resize", resize); resize();

function colourOf(f) { // [dim, r, g, b, white, pan, tilt]
  const [dim, r, g, b, w] = f;
  return { c: [r + w, g + w, b + w], dim: Math.min(1, dim) };
}

// Perspective view from the audience. World: x across the stage, y towards the audience, z up (metres).
function camera(W, H) {
  const st = show.stage, cx = st.width_m / 2, ext = show.ext || {top: 2, back: -2.5};
  const f = W * 1.05;
  // Fit the room: its height (floor → ceiling, or the rig) and width must fit this canvas. Small rigs keep
  // the classic view (9.5 m away, eye height 2.2 m); a 16 m truss grid moves the camera back and up.
  const roomH = Math.max(ext.top + 1, Math.min(st.ceiling_m || 4.5, ext.top + 4));
  const tz = Math.max(1.3, roomH * 0.5);
  const distH = (roomH - tz + 0.5) * f / (H * 0.55);
  const distW = (st.width_m / 2 + 2) * f / (W / 2);
  const dist = Math.max(9.5, distH, distW);
  const eye = [cx, dist, Math.max(2.2, roomH * 0.3)], target = [cx, Math.max(-0.5, ext.back / 3), tz];
  show.eye = eye;
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm = v => { const l = Math.hypot(...v); return v.map(x => x / l); };
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const fwd = norm(sub(target, eye)), right = norm(cross(fwd, [0, 0, 1])), up = cross(right, fwd);
  return p => {
    const v = sub(p, eye), z = dot(v, fwd);
    if (z < 0.2) return null;
    return [W / 2 + f * dot(v, right) / z, H * 0.55 - f * dot(v, up) / z, z, f / z];
  };
}

function beamEnd(pos, d, st, nearCam = 4) {
  // the room: floor, ceiling, far wall (audience side), back wall and side walls: beams stop where they would
  const depth = st.room_depth_m || 6, side = 2.0, W = st.width_m;
  const hits = [];
  if (d[2] < -1e-3) hits.push([-pos[2] / d[2], "floor"]);
  if (d[2] > 1e-3) hits.push([(st.ceiling_m - pos[2]) / d[2], "ceiling"]);
  if (d[1] > 1e-3) hits.push([(depth - pos[1]) / d[1], "wall"]);
  // beams scanning the audience: drawn until a few metres in front of the viewer (not through the camera)
  if (d[1] > 1e-3 && show.eye && show.eye[1] - nearCam < depth) hits.push([(show.eye[1] - nearCam - pos[1]) / d[1], "air"]);
  if (d[1] < -1e-3) hits.push([(Math.min(-2.5, show.ext?.back ?? -2.5) - pos[1]) / d[1], "wall"]);
  if (d[0] > 1e-3) hits.push([(W + side - pos[0]) / d[0], "wall"]);
  if (d[0] < -1e-3) hits.push([(-side - pos[0]) / d[0], "wall"]);
  const [t, surf] = hits.reduce((a, b) => (b[0] < a[0] ? b : a), [12, "air"]);
  return { p: [pos[0] + d[0] * t, pos[1] + d[1] * t, pos[2] + d[2] * t], t, surf };
}

function drawBeam(P, from, to, len, beamDeg, c, a) {
  const s = P(from), e = P(to);
  if (!s || !e) return;
  const rEnd = Math.max(2, len * Math.tan(beamDeg * Math.PI / 360) * e[3]);
  const rStart = Math.max(1.5, 0.05 * s[3]);
  const dx = e[0] - s[0], dy = e[1] - s[1], l = Math.hypot(dx, dy) || 1, nx = -dy / l, ny = dx / l;
  const g = ctx.createLinearGradient(s[0], s[1], e[0], e[1]);
  g.addColorStop(0, rgb(c, 0.75 * a)); g.addColorStop(1, rgb(c, 0.12 * a));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(s[0] + nx * rStart, s[1] + ny * rStart); ctx.lineTo(e[0] + nx * rEnd, e[1] + ny * rEnd);
  ctx.lineTo(e[0] - nx * rEnd, e[1] - ny * rEnd); ctx.lineTo(s[0] - nx * rStart, s[1] - ny * rStart);
  ctx.fill();
  return { e, rEnd };
}

// ---------- scenery: a stage with a DJ riser and booth for big rigs, just a DJ booth for a mobile setup
const wallView = new URLSearchParams(location.search).has("wall") ? (() => {
  const c = document.createElement("canvas");
  c.width = 1280; c.height = 720;
  c.style.cssText = "position:fixed;inset:0;width:100vw;height:100vh;object-fit:contain;background:#000;z-index:99";
  document.body.appendChild(c);
  return c;
})() : null;

function drawScenery(P, st) {
  const heads = show.fixtures.filter(f => f.kind === "head").length;
  const big = st.width_m >= 6 || heads >= 8;
  const cx = st.width_m / 2;
  const poly = (pts, fill, stroke) => {
    const q = pts.map(P); if (q.some(v => !v)) return;
    ctx.beginPath(); ctx.moveTo(q[0][0], q[0][1]); q.slice(1).forEach(v => ctx.lineTo(v[0], v[1])); ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = Math.max(1, cv.width / 1200); ctx.stroke(); }
  };
  // a box: x0..x1, y0..y1 (y0 = back), z0..z1; front, top and the visible side
  const box = (x0, x1, y0, y1, z0, z1, front, top, edge) => {
    poly([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], top, edge);
    poly([[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]], front, edge);
    const eye = show.eye || [cx, 10, 2];
    const sx = eye[0] < x0 ? x0 : eye[0] > x1 ? x1 : null;  // the side facing the viewer
    if (sx != null) poly([[sx, y0, z0], [sx, y1, z0], [sx, y1, z1], [sx, y0, z1]], front, edge);
  };
  // the LED wall behind the DJ (web/js/screen.js): dark unless the director gives it something to show
  const now = performance.now(), dt = Math.min(0.1, (now - (drawScenery.last || now)) / 1000) || 1 / 60;
  drawScenery.last = now;
  const wall = Screen.update(frame, show, dt);
  if (wall && wallView) {  // ?wall: the wall's own picture, full-window (what a real LED wall would get)
    const wc = wallView.getContext("2d");
    wc.globalAlpha = 1; wc.fillStyle = "#000"; wc.fillRect(0, 0, wallView.width, wallView.height);
    wc.globalAlpha = Math.max(0, Math.min(1, wall.level));
    wc.drawImage(wall.canvas, 0, 0, wallView.width, wallView.height);
  }
  if (wall) {
    const sw = big ? Math.min(10, st.width_m * 0.55) : 2.6, sh = sw * 9 / 16;
    const sy = big ? Math.min(-4.5, (show.ext?.back ?? -6) + 1.5) - 2.2 : -2.0;
    const sz = big ? 1.4 : 1.15;
    // the picture's left edge goes on the corner that appears on the left (seen from the audience; else mirrored)
    let lx = cx - sw / 2, rx = cx + sw / 2;
    const a = P([lx, sy, sz]), b = P([rx, sy, sz]);
    if (a && b && a[0] > b[0]) [lx, rx] = [rx, lx];
    const TL = P([lx, sy, sz + sh]), TR = P([rx, sy, sz + sh]), BL = P([lx, sy, sz]);
    if (TL && TR && BL) {
      const w = wall.canvas.width, h = wall.canvas.height;
      // frame
      ctx.save();
      ctx.setTransform((TR[0] - TL[0]) / w, (TR[1] - TL[1]) / w, (BL[0] - TL[0]) / h, (BL[1] - TL[1]) / h, TL[0], TL[1]);
      ctx.fillStyle = "#050507"; ctx.fillRect(-w * 0.012, -h * 0.02, w * 1.024, h * 1.04);
      ctx.globalAlpha = Math.max(0, Math.min(1, wall.level));
      ctx.drawImage(wall.canvas, 0, 0);
      // one colour scheme with the lights: tint the wall towards the phrase's palette (dark stays dark)
      const pal = wall.tint && PALETTES[show.plan?.[frame.phrase]?.palette];
      if (pal) {
        const grad = ctx.createLinearGradient(0, 0, w, h);
        pal.forEach((col, i) => grad.addColorStop(i / Math.max(pal.length - 1, 1), rgb(col)));
        ctx.globalCompositeOperation = "color"; ctx.globalAlpha = 0.55;
        ctx.fillStyle = grad; ctx.fillRect(0, 0, w, h);
      }
      ctx.restore();
      // the wall's own light, faintly on the stage around it
      const mid = P([cx, sy + 0.3, sz + sh / 2]);
      if (mid) {
        ctx.save(); ctx.globalCompositeOperation = "lighter";
        const r = Math.hypot(TR[0] - TL[0], BL[1] - TL[1]) * 0.75;
        const g = ctx.createRadialGradient(mid[0], mid[1], 0, mid[0], mid[1], r);
        g.addColorStop(0, `rgba(120,140,255,${0.06 * wall.level})`); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(mid[0], mid[1], r, 0, 7); ctx.fill(); ctx.restore();
      }
    }
  }

  let booth;  // where the DJ stands: [y of the booth front, z of the floor under it]
  if (big) {
    const back = Math.min(-3, (show.ext?.back ?? -6) + 1.0);
    box(-0.5, st.width_m + 0.5, back, -0.2, 0, 0.15, "#0c0d12", "#101219", "#1d2029");       // stage deck
    const ry = Math.max(back + 0.5, -4.5), rd = 2.2, rw = Math.min(5, st.width_m * 0.3);
    box(cx - rw / 2, cx + rw / 2, ry - rd, ry, 0.15, 0.95, "#11131a", "#161922", "#262a35");  // DJ riser
    booth = [ry - 0.4, 0.95];
  } else {
    booth = [-1.3, 0];
  }
  const [by, bz] = booth, bw = big ? 2.4 : 1.6;
  // the DJ (behind the booth): body and head
  const dy = by - 0.55;
  poly([[cx - 0.25, dy, bz + 0.9], [cx + 0.25, dy, bz + 0.9], [cx + 0.22, dy, bz + 1.5], [cx - 0.22, dy, bz + 1.5]], "#07080b");
  const hp = P([cx, dy, bz + 1.68]);
  if (hp) { ctx.fillStyle = "#07080b"; ctx.beginPath(); ctx.arc(hp[0], hp[1], 0.12 * hp[3], 0, 7); ctx.fill(); }
  // the booth: a table with a front panel, decks on top with a few lit controls
  box(cx - bw / 2, cx + bw / 2, by - 0.7, by, bz, bz + 1.05, "#14161e", "#1b1e28", "#2a2e3a");
  for (const off of [-0.55, 0, 0.55]) {
    const w = off === 0 ? 0.35 : 0.42;
    box(cx + off * (bw / 2.4) - w / 2, cx + off * (bw / 2.4) + w / 2, by - 0.55, by - 0.12, bz + 1.05, bz + 1.1,
        "#0d0e13", "#22252f", null);
    const led = P([cx + off * (bw / 2.4), by - 0.3, bz + 1.11]);
    if (led) { ctx.fillStyle = off === 0 ? "rgba(255,204,51,.8)" : "rgba(122,162,255,.75)";
               ctx.beginPath(); ctx.arc(led[0], led[1], Math.max(1.2, 0.025 * led[3]), 0, 7); ctx.fill(); }
  }
  // a thin LED line along the booth front that picks up the pars' colour
  const pars = show.fixtures.map((f, i) => [f, frame.fx[i]]).filter(([f, x]) => f.kind === "par" && x);
  let c = [0.25, 0.3, 0.45], k = 0.35;
  if (pars.length) {
    c = [0, 1, 2].map(m => pars.reduce((t, [, x]) => t + x[1 + m] * x[0], 0) / pars.length);
    const mx = Math.max(...c, 1e-3); c = c.map(v => v / mx); k = Math.min(1, 0.25 + pars.reduce((t, [, x]) => t + x[0], 0) / pars.length);
  }
  const a = P([cx - bw / 2, by, bz + 0.95]), b = P([cx + bw / 2, by, bz + 0.95]);
  if (a && b) { ctx.strokeStyle = rgb(c, 0.8 * k); ctx.lineWidth = Math.max(1.5, 0.02 * a[3]);
                ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); }
}

// a 30 cm box truss (quatro): four chords with lacing; vertical ones stand on a base plate
function drawTruss(P, t, line) {
  const r = (t.rot_deg || 0) * Math.PI / 180, L = t.length_m || 2, h = 0.15, col = "#3a3f4e";
  if (t.vertical) {
    const z0 = 0, z1 = (t.z_m || 0) + L / 2;
    for (const [dx, dy] of [[-h, -h], [h, -h], [h, h], [-h, h]]) line([t.x_m + dx, t.y_m + dy, z0], [t.x_m + dx, t.y_m + dy, z1], col);
    for (let z = 0.25; z < z1; z += 0.5) line([t.x_m - h, t.y_m - h, z], [t.x_m + h, t.y_m - h, z + 0.25], "#2a2e3a");
    return;
  }
  const ax = [Math.cos(r), Math.sin(r)], nx = [-Math.sin(r), Math.cos(r)];
  const at = (u, sv, sz) => [t.x_m + ax[0] * u + nx[0] * sv, t.y_m + ax[1] * u + nx[1] * sv, t.z_m + sz];
  for (const [sv, sz] of [[-h, -h], [h, -h], [h, h], [-h, h]]) line(at(-L / 2, sv, sz), at(L / 2, sv, sz), col);
  for (let u = -L / 2; u < L / 2 - 0.25; u += 0.5) {
    line(at(u, -h, -h), at(u + 0.25, -h, h), "#2a2e3a"); line(at(u, h, -h), at(u + 0.25, h, h), "#2a2e3a");
  }
}

// a zone (rig editor): dashed outline, blue = keep out, green = keep in, red = laser safety
function drawZone(P, z) {
  const r = (z.rot_deg || 0) * Math.PI / 180, t = (z.tilt_deg || 0) * Math.PI / 180, c = z.center, sz = z.size;
  const u = [Math.cos(r), Math.sin(r), 0], f = [-Math.sin(r), Math.cos(r), 0];
  let v, n, pts;
  const at = (a, b, k) => [0, 1, 2].map(i => c[i] + u[i] * a + v[i] * b + (n ? n[i] * k : 0));
  if (z.shape === "box") {
    v = f; n = [0, 0, 1];
    const [w, d, h] = [sz[0] / 2, (sz[1] || 1) / 2, (sz[2] || 1) / 2];
    pts = [[-w, -d, -h], [w, -d, -h], [w, d, -h], [-w, d, -h], [-w, -d, h], [w, -d, h], [w, d, h], [-w, d, h]].map(p => at(...p));
  } else {
    v = [0, 1, 2].map(i => [0, 0, 1][i] * Math.cos(t) - f[i] * Math.sin(t)); n = null;
    const [w, h] = [sz[0] / 2, (sz[1] || 1) / 2];
    pts = [[-w, -h], [w, -h], [w, h], [-w, h]].map(p => at(p[0], p[1], 0));
  }
  const edges = z.shape === "box" ? [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]] : [[0,1],[1,2],[2,3],[3,0]];
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  ctx.setLineDash([6, 5]);
  ctx.lineWidth = Math.max(1, cv.width / 900);
  ctx.strokeStyle = z.kind === "laser_out" ? "rgba(255,80,60,0.8)" : z.kind === "keep_in" ? "rgba(60,230,130,0.7)" : "rgba(90,150,255,0.8)";
  edges.forEach(([a, b]) => { const p = P(pts[a]), q = P(pts[b]); if (!p || !q) return;
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke(); });
  ctx.restore();
}

function draw() {
  requestAnimationFrame(draw);
  const W = cv.width, H = cv.height;
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = "#020205"; ctx.fillRect(0, 0, W, H);
  if (!show || !frame) return;
  const st = show.stage, P = camera(W, H);

  // floor grid: stage (y < 0) and dance floor (y > 0)
  ctx.lineWidth = Math.max(1, W / 900);
  const line = (a, b, col) => { const p = P(a), q = P(b); if (!p || !q) return;
    ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke(); };
  const back = Math.floor(Math.min(-3, show.ext?.back ?? -3)), front = Math.ceil(Math.max(7, (st.room_depth_m || 6)));
  for (let x = -2; x <= st.width_m + 2; x += 1) line([x, back, 0], [x, front, 0], "#10121a");
  for (let y = back; y <= front; y += 1) line([-2, y, 0], [st.width_m + 2, y, 0], y === 0 ? "#2a2f3d" : "#10121a");

  drawScenery(P, st);

  // trusses from the set (the rig editor places them); without them: a short stand/hang line per head
  const trusses = show.trusses || [];
  trusses.forEach(t => drawTruss(P, t, line));
  if (new URLSearchParams(location.search).has("zones")) (show.zones || []).forEach(z => drawZone(P, z));
  show.fixtures.forEach(fx => {
    if (fx.kind !== "head" || trusses.length) return;
    if (fx.mount === "hang") line([fx.pos[0], fx.pos[1], fx.pos[2] + 0.15], [fx.pos[0], fx.pos[1], fx.pos[2] + 0.6], "#2a2e3a");
    else line([fx.pos[0], fx.pos[1], 0], [fx.pos[0], fx.pos[1], fx.pos[2] - 0.15], "#2a2e3a");
  });

  ctx.globalCompositeOperation = "lighter";
  const spots = [];
  // many beams add up: keep the total brightness of a 60-head rig in range (2-4 heads: unchanged)
  const nHeads = show.fixtures.filter(f => f.kind === "head").length;
  const density = Math.min(1, 3 / Math.sqrt(Math.max(nHeads, 1)));
  show.fixtures.forEach((fx, i) => {
    const f = frame.fx[i]; if (!f) return;
    const { c, dim } = colourOf(f);
    if (dim <= 0.01) return;
    if (fx.kind === "head") {
      const d = frame.dirs?.[i]; if (!d) return;
      const fxName = frame.beam?.[i] || "open";
      // prism: three beams a few degrees apart (rotating for prism_spin); frost: one wide, soft beam
      const rays = (fxName.startsWith("prism") || fxName === "gobo_rotate") ? [0, 1, 2].map(k => {
        const a = (fxName !== "prism" ? frame.t * 2.5 : 0) + k * 2.094, off = fxName === "gobo_rotate" ? 0.035 : 0.07;
        const side = Math.abs(d[2]) > 0.9 ? [1, 0, 0] : [0, 0, 1];
        const u = [d[1] * side[2] - d[2] * side[1], d[2] * side[0] - d[0] * side[2], d[0] * side[1] - d[1] * side[0]];
        const ul = Math.hypot(...u), v = [d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0]];
        const r = [0, 1, 2].map(m => d[m] + off * (Math.cos(a) * u[m] / ul + Math.sin(a) * v[m] / ul));
        const rl = Math.hypot(...r); return r.map(x => x / rl);
      }) : [d];
      // the real lens: tight zoom for beams, wide (and softer: same light, bigger area) for frost
      const frost = fxName === "frost";
      const spread = frost ? Math.max(fx.beam_wide ?? 25, 25) * 1.2 : fx.beam_deg * 1.6;
      const strength = frost ? (fx.output_wide ?? 1) : (fx.output ?? 1);
      const alpha = (frost ? dim * 0.45 : rays.length > 1 ? dim * 0.6 : dim) * density * strength;
      rays.forEach(rd => {
        const end = beamEnd(fx.pos, rd, st);
        const b = drawBeam(P, fx.pos, end.p, end.t, spread, c, alpha);
        if (b && end.surf !== "air") spots.push({ ...b, c, dim: alpha, surf: end.surf, d: rd });
      });
    } else if (fx.kind === "laser") {
      // lasers: razor-thin beams, each with its own colour and brightness (fans, sheets, tunnels, ripples),
      // reaching out over the crowd almost to the viewer; a hot spot at the aperture
      const beams = frame.lz?.[i]; if (!beams) return;
      const s = P(fx.pos); if (!s) return;
      const thin = 1 / Math.sqrt(Math.max(1, beams.length / 6));  // dense fans: thinner, fainter lines
      let hot = [0, 0, 0];
      beams.forEach(b => {
        const rd = [b[0], b[1], b[2]], col = [b[3], b[4], b[5]], a = b[6] * dim;
        if (a <= 0.02) return;
        const end = beamEnd(fx.pos, rd, st, 1.2), e = P(end.p); if (!e) return;
        for (const [w, al] of [[5, 0.08], [1.8, 0.35], [0.7, 0.9]]) {
          ctx.strokeStyle = rgb(col, al * a * (w > 1 ? thin : 1)); ctx.lineWidth = w * devicePixelRatio * (w > 1 ? thin : 1);
          ctx.beginPath(); ctx.moveTo(s[0], s[1]); ctx.lineTo(e[0], e[1]); ctx.stroke();
        }
        hot = hot.map((x, m) => x + col[m] * a / beams.length);
        if (end.surf !== "air") spots.push({ e, rEnd: 2.5 * devicePixelRatio, c: col, dim: a * 0.7, surf: end.surf, d: rd });
      });
      const hm = Math.max(...hot, 0.01), r = 9 * devicePixelRatio;
      const g = ctx.createRadialGradient(s[0], s[1], 0, s[0], s[1], r);
      g.addColorStop(0, `rgba(255,255,255,${Math.min(1, dim)})`); g.addColorStop(0.3, rgb(hot.map(x => x / hm), 0.8 * dim));
      g.addColorStop(1, rgb(hot.map(x => x / hm), 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(s[0], s[1], r, 0, 7); ctx.fill();
    } else if (fx.kind === "blinder") {
      // stage blinder: two warm lamp faces and a wide, short blast of light into the audience
      const p = P(fx.pos); if (!p) return;
      const d = fx.dir || [0, 1, 0.12], end = beamEnd(fx.pos, d, st);
      drawBeam(P, fx.pos, end.p, Math.min(end.t, 5), 70, c, dim * 0.55);
      for (const off of [-0.07, 0.07]) {
        const q = P([fx.pos[0] + off, fx.pos[1] + 0.05, fx.pos[2]]); if (!q) continue;
        const r = 0.16 * q[3] * (1 + 2.5 * dim), g = ctx.createRadialGradient(q[0], q[1], 0, q[0], q[1], r);
        g.addColorStop(0, `rgba(255,255,240,${Math.min(1, dim * 1.2)})`); g.addColorStop(0.35, rgb(c, 0.8 * dim)); g.addColorStop(1, rgb(c, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, 7); ctx.fill();
      }
    } else if (fx.kind === "strobe") {
      // a strobe: one blinding white flash from its face, flooding the room for a moment
      const p = P(fx.pos); if (!p) return;
      const d = fx.dir || [0, 1, 0.14], end = beamEnd(fx.pos, d, st);
      drawBeam(P, fx.pos, end.p, Math.min(end.t, 7), 100, [1, 1, 1], dim * 0.7);
      const r = 0.5 * p[3] * (1 + 4 * dim), g = ctx.createRadialGradient(p[0], p[1], 0, p[0], p[1], r);
      g.addColorStop(0, `rgba(255,255,255,${Math.min(1, dim * 1.4)})`); g.addColorStop(0.3, `rgba(220,235,255,${0.6 * dim})`);
      g.addColorStop(1, "rgba(200,220,255,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 7); ctx.fill();
      ctx.fillStyle = `rgba(255,255,255,${0.12 * dim})`; ctx.fillRect(0, 0, cv.width, cv.height);  // the room lights up
    } else {
      const d = fx.dir || [0, 0.18, 1], end = beamEnd(fx.pos, d, st);  // up-lighter, slightly towards the crowd
      // the cells of a bar share its light: many small beams, not many full-strength ones
      const cellK = fx.cells > 1 ? 1 / Math.sqrt(fx.cells) : 1;
      drawBeam(P, fx.pos, end.p, Math.min(end.t, 3.5), Math.min(fx.beam_deg || 28, 40), c, dim * 0.8 * cellK);
      const p = P(fx.pos);
      if (p) {
        const r = 0.6 * p[3], g = ctx.createRadialGradient(p[0], p[1], 0, p[0], p[1], r);
        g.addColorStop(0, rgb(c, 0.5 * dim)); g.addColorStop(1, rgb(c, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(p[0], p[1], r, r * 0.4, 0, 0, 7); ctx.fill();
      }
    }
  });
  // where beams land: the clearest view of sync / mirror / focus / cross
  spots.forEach(({ e, rEnd, c, dim, surf, d }) => {
    const squash = surf === "floor" ? Math.max(0.25, Math.min(1, Math.abs(d[2]) * 0.8)) : surf === "wall" ? 0.9 : 0.5;
    const r = rEnd * 1.4, g = ctx.createRadialGradient(e[0], e[1], 0, e[0], e[1], r);
    g.addColorStop(0, rgb(c, 0.9 * dim)); g.addColorStop(1, rgb(c, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(e[0], e[1], r, r * squash, 0, 0, 7); ctx.fill();
  });

  // housings of bars (LED bars, moving bars, Sunstrips): one box along the bar, behind its cells
  ctx.globalCompositeOperation = "source-over";
  const bars = {};
  show.fixtures.forEach(fx => { if (fx.cells > 1) (bars[fx.fixture] ||= []).push(fx); });
  Object.values(bars).forEach(cells => {
    const f = cells[0], L = f.length || 1, r = (f.rot || 0) * Math.PI / 180;
    const cx = cells.reduce((t, c) => t + c.pos[0], 0) / cells.length, cy = cells.reduce((t, c) => t + c.pos[1], 0) / cells.length;
    const a = P([cx - Math.cos(r) * L / 2, cy - Math.sin(r) * L / 2, f.pos[2]]), b = P([cx + Math.cos(r) * L / 2, cy + Math.sin(r) * L / 2, f.pos[2]]);
    if (!a || !b) return;
    ctx.strokeStyle = "#2a2e3a"; ctx.lineCap = "round"; ctx.lineWidth = Math.max(3, 0.14 * (a[3] + b[3]) / 2);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); ctx.lineCap = "butt";
  });

  // fixture bodies and lenses on top
  show.fixtures.forEach((fx, i) => {
    const p = P(fx.pos), f = frame.fx[i]; if (!p || !f) return;
    const { c, dim } = colourOf(f);
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#2a2e3a";
    const size = (fx.cells > 1 ? 0.05 : fx.kind === "head" ? 0.16 : fx.kind === "strobe" ? 0.2 : 0.1) * p[3];
    if (!(fx.cells > 1)) ctx.fillRect(p[0] - size, p[1] - size * 0.8, size * 2, size * 1.6);
    ctx.globalCompositeOperation = "lighter";
    // a head pointing at the viewer shows its bright lens (audience scanning: the hot spots you see)
    let flare = 1;
    const d = frame.dirs?.[i];
    if (fx.kind === "head" && d && show.eye) {
      const v = [show.eye[0] - fx.pos[0], show.eye[1] - fx.pos[1], show.eye[2] - fx.pos[2]], l = Math.hypot(...v);
      const facing = Math.max(0, (d[0] * v[0] + d[1] * v[1] + d[2] * v[2]) / l);
      flare = 1 + 3 * facing ** 6;
    }
    const R = size * 2.2 * flare;
    const g = ctx.createRadialGradient(p[0], p[1], 0, p[0], p[1], R);
    g.addColorStop(0, rgb(c, dim)); g.addColorStop(0.25, rgb(c, dim * (flare > 1.5 ? 0.6 : 0.4))); g.addColorStop(1, rgb(c, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p[0], p[1], R, 0, 7); ctx.fill();
  });
}
requestAnimationFrame(draw);

// why the quick (rule-based) plan is running: the AI plan is still being made, or rules were chosen
function rulesNote() {
  const st = (frame?.decks || []).map(d => d.status || {}).find(s => s.lights === "rules") || {};
  if (st.ai === "running")
    return `Quick plan for now: the AI is still deciding this track (${st.ai_done || 0}/${st.ai_total || "…"} phrases). ` +
           `It takes over as soon as it is done.`;
  if (st.stems === "running")
    return "Quick plan for now: the instruments are being separated first; then the AI decides this track.";
  return "The rule-based director has no probabilities. Choose OpenAI or a local decision model on the " +
         "<a href='/setup.html' style='color:inherit'>setup page</a> to let the AI decide.";
}

// what is ready per track: analysis, separated instruments, AI plan, and which plan the lights use now
const mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
function stepChip(label, state, extra = "") {
  const icon = {done: "✓", running: "⧗", failed: "⚠", "n/a": "–"}[state] || "·";
  return `<span class="step ${state || "wait"}">${label} ${icon}${extra}</span>`;
}
function deckLine(d) {
  const s = d.status || {}, esc = t => String(t).replace(/[&<>]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));
  const run = st => st === "running" && s.elapsed != null ? " " + mmss(s.elapsed) : "";
  const ai = s.ai === "running" ? ` ${s.ai_done || 0}/${s.ai_total || "…"}` : s.ai === "done" ? ` ${s.ai_total}` : "";
  const lights = s.lights ? (s.lights === "rules" ? "quick plan" : "AI plan") : "dark";
  return `<div class="deck"><b>Deck ${d.deck} ${d.play ? "▶" : "⏸"}</b> <span>${esc(d.track)}</span>
    <span>${Math.round(d.vol * 100)}%</span>
    ${stepChip("analysis", s.analysis === "running" ? "running" : (s.analysis || (d.ready ? "done" : "running")))}
    ${stepChip("instruments", s.stems, run(s.stems))}
    ${stepChip("AI plan", s.ai || (s.lights && s.lights !== "rules" ? "done" : undefined), ai + run(s.ai))}
    <span class="step ${s.lights ? (s.lights === "rules" ? "running" : "done") : "wait"}">lights: ${lights}</span></div>`;
}

function onFrame(msg) {
  frame = msg;
  if (msg.decks) $("decks").innerHTML = msg.decks.map(deckLine).join("");
  const rn = document.getElementById("rulesNote");
  if (rn) { const t = rulesNote(); if (rn.innerHTML !== t) rn.innerHTML = t; }
  if (!show) return;
  $("clock").textContent = `${fmt(msg.t)} / ${fmt(show.duration)}`;
  $("playhead").style.left = `${(msg.t / show.duration) * 100}%`;
  BANDS.forEach((b, i) => $(`m-${b}`).style.height = `${(msg.bands[i] || 0) * 100}%`);
  if (msg.phrase !== shownPhrase) { shownPhrase = msg.phrase; showDecision(msg.phrase); }
}

// ---------- connection (reconnects so the page can stay open between runs)
function connect() {
  const wsPort = new URLSearchParams(location.search).get("ws") || 8765;  // ?ws=8766 for a second show
  const ws = new WebSocket(`ws://${location.hostname || "localhost"}:${wsPort}`);
  ws.onopen = () => $("status").textContent = "live";
  ws.onmessage = e => { const m = JSON.parse(e.data); m.type === "hello" ? onHello(m) : onFrame(m); };
  ws.onclose = () => { $("status").textContent = "player stopped · reconnecting…"; setTimeout(connect, 1500); };
}
connect();
