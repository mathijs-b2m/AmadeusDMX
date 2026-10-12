const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const SOURCE = {local: "Your library", qlc: "QLC+", ofl: "Open Fixture Lib"};
const COLORS = ["#7aa2ff", "#ff8fd0", "#63d39b", "#ffcc33", "#c792ff", "#ff9f5a", "#5ad1e6"];
let rig = null, lib = {};

function log(event) {  // shows up in the server's output and .cache/setup-events.log
  fetch("/api/log", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({event})}).catch(() => {});
}
window.addEventListener("error", e => log(`JS error: ${e.message} @${e.lineno}`));
window.addEventListener("unhandledrejection", e => log(`JS error: ${e.reason?.message || e.reason}`));

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const raw = await r.text();
  let j;
  try { j = JSON.parse(raw); }
  catch { throw new Error(`${path}: HTTP ${r.status}, not a JSON answer (is an older server running on this port?)`); }
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}
function toast(text) {
  const t = $("#toast"); t.textContent = text; t.classList.add("show");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 2200);
}

// ------------------------------------------------------------------ rig
async function loadRig() {
  [rig, lib] = await Promise.all([api("/api/rig"), api("/api/library").then(l => Object.fromEntries(l.map(d => [d.key, d])))]);
  renderRig();
}
function renderRig() {
  const fx = rig.fixtures;
  $("#status").textContent = `${fx.length} fixture${fx.length === 1 ? "" : "s"} · node ${rig.artnet?.ip || "?"}`;
  if (!fx.length) { $("#rig").innerHTML = `<span class="note">No fixtures yet: search below to add one.</span>`; return; }
  const universes = [...new Set(fx.map(f => f.universe))].sort((a, b) => a - b);
  let html = "";
  fx.forEach((f, i) => {
    const d = lib[f.fixture] || {model: f.fixture, manufacturer: "", modes: {}};
    const n = d.modes[f.mode] || 0;
    html += `<div class="fx">
      <div class="name"><span class="dot" style="background:${COLORS[i % COLORS.length]}"></span>${esc(d.manufacturer)} ${esc(d.model)} <span class="id">${esc(f.id)}</span></div>
      <div class="acts">
        <button class="small" data-identify="${esc(f.id)}">Identify</button>
        <button class="small danger" data-remove="${esc(f.id)}" aria-label="Remove">✕</button>
      </div>
      <div class="meta">${esc(f.mode)} · DMX ${f.address}–${f.address + n - 1}${universes.length > 1 ? ` · universe ${f.universe}` : ""}</div>
    </div>`;
  });
  for (const u of universes) {
    const inU = fx.map((f, i) => [f, i]).filter(([f]) => f.universe === u).sort((a, b) => a[0].address - b[0].address);
    const last = Math.max(...inU.map(([f]) => f.address + (lib[f.fixture]?.modes[f.mode] || 0) - 1));
    const span = Math.min(512, Math.max(64, Math.ceil((last + 8) / 32) * 32));
    let pos = 1, bar = "";
    for (const [f, i] of inU) {
      const n = lib[f.fixture]?.modes[f.mode] || 0;
      if (f.address > pos) bar += `<div style="flex:${f.address - pos}"></div>`;
      bar += `<div title="${esc(f.id)}" style="flex:${n};background:${COLORS[i % COLORS.length]}"></div>`;
      pos = f.address + n;
    }
    if (span + 1 > pos) bar += `<div style="flex:${span + 1 - pos}"></div>`;
    html += `<div class="map">${bar}</div><div class="mapnote"><span>${universes.length > 1 ? `Universe ${u} · ` : ""}ch 1</span><span>last used: ${last}</span><span>${span}</span></div>`;
  }
  $("#rig").innerHTML = html;
}
$("#rig").addEventListener("click", async e => {
  const id = e.target.dataset.identify, rm = e.target.dataset.remove;
  if (id) {
    try { await api("/api/identify", {fixture: id, rig}); toast(`${id} lights up white for 2 s`); }
    catch (err) { toast(err.message); }
  }
  if (rm && confirm(`Remove ${rm} from the rig?`)) {
    const next = {...rig, fixtures: rig.fixtures.filter(f => f.id !== rm)};
    try {
      const r = await api("/api/rig", next);
      if (!r.saved) throw new Error(r.problems.join("; "));
      rig = next; renderRig(); toast(`${rm} removed`);
    } catch (err) { toast(err.message); }
  }
});

// ------------------------------------------------------------------ search
let searchSeq = 0;
$("#q").addEventListener("input", () => {
  clearTimeout(search.h);
  search.h = setTimeout(search, 220);
});
async function search() {
  const q = $("#q").value.trim(), seq = ++searchSeq;
  if (q.length < 2) { $("#results").innerHTML = ""; return; }
  $("#results").innerHTML = `<span class="note">Searching…</span>`;
  try {
    const res = await api(`/api/catalog?q=${encodeURIComponent(q)}&limit=20`);
    if (seq !== searchSeq) return;
    $("#scan").innerHTML = "";
    $("#results").innerHTML = res.length ? res.map(c => resultHtml(c, false)).join("") : `<span class="note">Nothing found. Try only the brand, or only the model number.</span>`;
  } catch (err) { $("#results").innerHTML = `<span class="msg bad">${esc(err.message)}</span>`; }
}
function resultHtml(c, best) {
  const pct = c.probability != null ? `<span class="pct">${Math.round(c.probability * 100)}% match</span>` : "";
  return `<button class="result ${best ? "best" : ""}" data-key="${esc(c.key)}">
      <span class="model">${esc(c.model)}</span>
      <span class="badge ${c.source}">${SOURCE[c.source]}</span>
      <span class="brand">${esc(c.manufacturer)} ${pct}</span>
    </button>`;
}

// ------------------------------------------------------------------ label scan
$("#scanBtn").addEventListener("click", () => $("#photo").click());
$("#photo").addEventListener("change", async e => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) { log("scan: camera closed without a photo"); return; }
  log(`scan: photo ${file.type || "?"} ${Math.round(file.size / 1024)} kB`);
  $("#q").value = ""; $("#results").innerHTML = "";
  let image;
  try { image = await shrink(file, 1600); }
  catch (err) { log(`scan: shrink failed: ${err.message}`); $("#scan").innerHTML = `<div class="msg bad">${esc(err.message)}</div>`; return; }
  log(`scan: sending ${Math.round(image.length * 0.75 / 1024)} kB`);
  $("#scan").innerHTML = `<div class="scan"><img src="${image}" alt="">
    <div><span class="spin"></span>Looking at the photo…<div class="note">About 5–10 s with OpenAI; a local model up to half a minute.</div></div></div>`;
  try {
    const r = await api("/api/label", {image});
    const top = r.matches[0];
    const sure = !!r.direct;
    const engine = r.engine.startsWith("openai") ? r.engine.replace("openai:", "OpenAI ").replace("openai", "OpenAI Decisions API") : r.engine.replace("ollama:", "local ");
    const what = [r.photo === "fixture" ? "from the looks" : r.photo === "other" ? "" : "from the label",
                  r.type, r.look].filter(Boolean).join(" · ");
    const said = r.read && (r.read.brand || r.read.model) ? `${r.read.brand} ${r.read.model}`.trim() : "";
    $("#scan").innerHTML = `<div class="scan"><img src="${image}" alt=""><div>
        ${said ? `<div><b>${esc(said)}</b>${r.read.confidence != null ? ` <span class="pct">${Math.round(r.read.confidence * 100)}% sure</span>` : ""}</div>`
               : r.brand ? `<div><b>${esc(r.brand.name)}</b></div>` : ""}
        ${what ? `<div class="note">${esc(what)}</div>` : ""}
        ${r.read?.reasoning ? `<div class="read">${esc(r.read.reasoning)}</div>` : r.read?.text ? `<div class="read">${esc(r.read.text)}</div>` : ""}
        ${r.note ? `<div class="msg ${r.matches.length ? "" : "bad"}">${esc(r.note)}</div>` : ""}
        <div class="note">${sure ? "Found it." : r.matches.length ? "Tap the right one:" : ""} (${esc(engine)})</div>
      </div></div>
      <div class="results">${r.matches.map((c, i) => resultHtml(c, i === 0 && sure)).join("")}</div>`;
    log(`scan: shown ${r.matches.length} matches${sure ? ", opened " + top.key : ""}`);
    if (sure) openFixture(top.key);
  } catch (err) {
    log(`scan: failed: ${err.message}`);
    $("#scan").innerHTML = `<div class="scan"><img src="${image}" alt=""><div class="msg bad">${esc(err.message)}</div></div>`;
  }
});
$("#scan").addEventListener("click", e => {
  const b = e.target.closest("[data-key]");
  if (b) openFixture(b.dataset.key);
});

// Phone photos are 12+ MP: scale down (labels stay readable at 1600 px) and re-encode as JPEG.
function shrink(file, max) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      log(`scan: photo ${img.width}x${img.height} -> ${c.width}x${c.height}`);
      resolve(c.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => reject(new Error("Could not read that photo"));
    img.src = URL.createObjectURL(file);
  });
}

$("#results").addEventListener("click", e => {
  const b = e.target.closest("[data-key]");
  if (b) openFixture(b.dataset.key);
});

// ------------------------------------------------------------------ add sheet
const sel = {key: null, det: null, mode: null, count: 1, universe: 1, plan: "easy", sugg: null};
function openSheet() { document.body.classList.add("open"); }
function closeSheet() { document.body.classList.remove("open"); }
$("#scrim").addEventListener("click", closeSheet);

async function openFixture(key) {
  Object.assign(sel, {key, det: null, mode: null, count: 1, universe: rig.fixtures[0]?.universe || 1, sugg: null});
  $("#sheet").innerHTML = `<div class="grab"></div><p class="note">Loading the fixture definition…</p>`;
  openSheet();
  try {
    sel.det = await api(`/api/catalog/details?key=${encodeURIComponent(key)}`);
    sel.mode = sel.det.default_mode;
    // how many of this model are already in the rig: a sensible default for "how many more"
    renderSheet();
    await suggest();
  } catch (err) { $("#sheet").innerHTML = `<div class="grab"></div><p class="msg bad">${esc(err.message)}</p>`; }
}

function renderSheet() {
  const d = sel.det, chans = d.modes[sel.mode];
  const extras = [d.kind.replace("_", " "), d.color_wheel && "colour wheel", d.gobos && `${d.gobos} gobos`].filter(Boolean).join(" · ");
  const s = sel.sugg, starts = s && s[sel.plan];
  $("#sheet").innerHTML = `<div class="grab"></div>
    <div class="brand">${esc(d.manufacturer)}</div>
    <h3>${esc(d.model)}</h3>
    <div class="note">${esc(extras)}</div>
    ${d.inert ? `<p class="note">Not driven by the show: ${esc(d.inert)}.</p>` : ""}
    ${d.warning ? `<p class="msg bad">⚠ ${esc(d.warning)}.</p>` : ""}

    <div class="section"><h2>DMX mode</h2>
      <div class="chips">${Object.entries(d.modes).map(([m, c]) =>
        `<button class="chip ${m === sel.mode ? "on" : ""}" data-mode="${esc(m)}">${esc(m)}${/^\d+ch$/.test(m) ? "" : ` (${c.length})`}</button>`).join("")}</div>
      <div class="note" style="margin-top:6px">${sel.mode === d.default_mode ? "Recommended: the richest mode (fine movement, per-head colour)." : "The richest mode gives the show the most control."}</div>
      <div class="chans">${chans.map((a, i) => `<span><b>${i + 1}</b>${esc(a.replace(/_/g, " "))}</span>`).join("")}</div>
    </div>

    <div class="section"><h2>How many</h2>
      <div class="stepper"><button data-count="-1">−</button><output>${sel.count}</output><button data-count="1">+</button></div>
    </div>

    <div class="section"><h2>DMX address${sel.count > 1 ? "es" : ""}</h2>
      ${!s ? `<p class="note">Finding free channels…</p>` : `
      ${["easy", "packed"].map(p => s[p] ? `<button class="opt ${p === sel.plan ? "on" : ""}" data-plan="${p}">
          <div class="addr">${s[p].join(", ")}</div>
          <div class="note">${p === "easy" ? "Easy to dial: every address ends in 1" : "Packed: no unused channels in between"}</div>
        </button>` : "").join("")}
      ${!s.easy && !s.packed ? `<p class="msg bad">Not enough free channels in universe ${sel.universe} for ${sel.count}× ${s.footprint} channels.</p>` : ""}`}
    </div>

    ${starts ? `<div class="section howto">On ${sel.count > 1 ? "each fixture" : "the fixture"}'s menu set:<br>
      DMX mode <code>${esc(sel.mode)}</code>${chans.length ? ` (${chans.length} channels)` : ""}<br>
      ${starts.map((a, i) => `${sel.count > 1 ? `#${i + 1}: ` : ""}address <code>${String(a).padStart(3, "0")}</code>`).join("<br>")}
      <div class="note" style="margin-top:6px">Many fixtures show it as <code style="font-size:13px">A${String(starts[0]).padStart(3, "0")}</code> or <code style="font-size:13px">d${String(starts[0]).padStart(3, "0")}</code>.</div>
    </div>` : ""}

    <div class="section">
      <button class="primary" id="addBtn" ${starts ? "" : "disabled"}>Add ${sel.count > 1 ? `${sel.count} fixtures` : "to rig"}</button>
      <div class="msg" id="addMsg"></div>
      <button style="width:100%;margin-top:8px" id="cancelBtn">Cancel</button>
    </div>`;
}

async function suggest() {
  sel.sugg = null; renderSheet();
  const key = sel.key, mode = sel.mode, count = sel.count;
  const s = await api("/api/suggest", {key, mode, count, universe: sel.universe});
  if (key !== sel.key || mode !== sel.mode || count !== sel.count) return;  // changed meanwhile
  sel.sugg = s;
  if (!s[sel.plan]) sel.plan = s.easy ? "easy" : "packed";
  renderSheet();
}

$("#sheet").addEventListener("click", async e => {
  const t = e.target.closest("button");
  if (!t) return;
  if (t.dataset.mode) { sel.mode = t.dataset.mode; suggest(); }
  else if (t.dataset.count) { sel.count = Math.max(1, Math.min(16, sel.count + +t.dataset.count)); suggest(); }
  else if (t.dataset.plan) { sel.plan = t.dataset.plan; renderSheet(); }
  else if (t.id === "cancelBtn") closeSheet();
  else if (t.id === "addBtn") {
    t.disabled = true; $("#addMsg").textContent = "Adding…";
    try {
      const r = await api("/api/rig/add", {key: sel.key, mode: sel.mode, addresses: sel.sugg[sel.plan], universe: sel.universe});
      if (!r.saved) throw new Error(r.problems.join("; "));
      closeSheet();
      $("#q").value = ""; $("#results").innerHTML = ""; $("#scan").innerHTML = "";
      await loadRig();
      toast(`Added ${r.added.map(f => f.id).join(", ")}`);
    } catch (err) { $("#addMsg").className = "msg bad"; $("#addMsg").textContent = err.message; t.disabled = false; }
  }
});

// ------------------------------------------------------------------ placement from a setup photo
const place = {lit: [], batch: 0, batches: 1, proposal: null};
$("#lightBtn").addEventListener("click", async () => {
  try {
    const r = await api("/api/placement/lights", {on: true, batch: place.batch});
    place.lit = r.lit; place.batches = r.batches;
    $("#legend").innerHTML = r.lit.map(a => `<span style="border-color:${a.hex};color:${a.hex}">● ${esc(a.fixture)}: ${a.colour}</span>`).join("")
      + (r.batches > 1 ? `<span class="note">group ${place.batch + 1} of ${r.batches}</span>` : "");
    $("#shotBtn").disabled = false;
    $("#lightBtn").textContent = "1. Lit (2 min) · tap to light again";
    log(`placement: lit ${r.lit.map(a => a.fixture + "=" + a.colour).join(", ")}`);
  } catch (err) { toast(err.message); }
});
$("#shotBtn").addEventListener("click", () => $("#setupPhoto").click());
$("#setupPhoto").addEventListener("change", async e => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  let image, blobs;
  try {
    image = await shrink(file, 1600);
    blobs = await lightSpots(image, place.lit);
  } catch (err) { toast(err.message); return; }
  log(`placement: photo, light spots ${JSON.stringify(Object.fromEntries(Object.entries(blobs).map(([k, v]) => [k, [v.x.toFixed(2), v.y.toFixed(2), v.n]])))}`);
  $("#placeResult").innerHTML = `<div class="shot"><img src="${image}" alt=""></div>
    <p class="note"><span class="spin"></span>Looking at the setup… (10–30 s)</p>`;
  try {
    const r = await api("/api/placement/analyze", {image, blobs, batch: place.batch});
    api("/api/placement/lights", {on: false}).catch(() => {});
    $("#lightBtn").textContent = "1. Light up the rig"; $("#shotBtn").disabled = true;
    place.proposal = r;
    renderProposal(image, r);
  } catch (err) { $("#placeResult").innerHTML += `<p class="msg bad">${esc(err.message)}</p>`; log(`placement failed: ${err.message}`); }
});

const CHANGE_LABELS = {x: ["x", ""], mount: ["mount", ""], y_m: ["distance to stage edge", " m"], z_m: ["height", " m"],
                       width_m: ["stage width", " m"], ceiling_m: ["ceiling", " m"], room_depth_m: ["room depth", " m"]};
function changeRows(changes, attr = "data-change") {
  return changes.map((c, i) => `<label class="change"><input type="checkbox" ${attr}="${i}" checked>
      <span class="what"><b>${esc(c.fixture || "stage")}</b> ${Object.entries(CHANGE_LABELS).filter(([k]) => c[k])
        .map(([k, [label, unit]]) => `${label} ${c[k][0]}${unit} → <b>${c[k][1]}${unit}</b>`).join(" · ")}
      ${c.note ? `<div class="note">${esc(c.note)}</div>` : ""}</span></label>`).join("");
}

function renderProposal(image, r) {
  const marks = r.found.map(f => `
    ${f.box ? `<div class="box" style="left:${f.box[0] * 100}%;top:${f.box[1] * 100}%;width:${f.box[2] * 100}%;height:${f.box[3] * 100}%;border-color:${f.hex}"></div>` : ""}
    <div class="mark" style="left:${f.img_x * 100}%;top:${(f.box ? f.box[1] : f.img_y) * 100}%;background:${f.hex}">${esc(f.fixture)}${f.source === "vision" ? " ?" : ""}</div>`).join("");
  const rows = changeRows(r.changes);
  $("#placeResult").innerHTML = `<div class="shot"><img src="${image}" alt="">${marks}</div>
    ${r.camera ? `<p class="note">Photo taken from: ${esc(r.camera)}${r.outer_distance_m ? ` · outermost fixtures ~${r.outer_distance_m} m apart (${esc(r.distance_source)})` : ""}</p>` : ""}
    ${r.missing.length ? `<p class="msg bad">Not found in the photo: ${r.missing.map(esc).join(", ")}. Are they in view and lit? (Identify checks the address.)</p>` : ""}
    ${r.notes.length ? `<h2 style="margin-top:12px">Check</h2><ul class="issues">${r.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <h2 style="margin-top:12px">Proposed changes</h2>
    ${rows || `<p class="note">The rig already matches the photo.</p>`}
    ${rows ? `<button class="primary" id="applyPlace" style="margin-top:10px">Apply to the rig</button>` : ""}
    ${place.batches > 1 && place.batch + 1 < place.batches ? `<button id="nextBatch" style="width:100%;margin-top:8px">Next group of fixtures</button>` : ""}`;
}
$("#placeResult").addEventListener("click", async e => {
  if (e.target.id === "nextBatch") { place.batch++; $("#lightBtn").click(); return; }
  if (e.target.id !== "applyPlace") return;
  const chosen = [...document.querySelectorAll("[data-change]")].filter(c => c.checked).map(c => place.proposal.changes[+c.dataset.change]);
  try {
    const r = await api("/api/placement/apply", {changes: chosen});
    if (!r.saved) throw new Error(r.problems.join("; "));
    toast(`Rig updated (${chosen.length} change${chosen.length === 1 ? "" : "s"})`);
    e.target.disabled = true; e.target.textContent = "Applied";
    if (place.batch + 1 >= place.batches) place.batch = 0;
    await loadRig();
  } catch (err) { toast(err.message); }
});

// ------------------------------------------------------------------ 3D scan
const scan = {result: null, moves: {}, flip: false, picked: null};
$("#scanLight").addEventListener("click", async () => {
  try {
    const r = await api("/api/placement/lights", {on: true, batch: 0, seconds: 600});
    $("#scanLight").textContent = "Lit for 10 min";
    toast(r.lit.map(a => `${a.fixture}: ${a.colour}`).join(" · "));
  } catch (err) { toast(err.message); }
});
$("#scanOff").addEventListener("click", () => { api("/api/placement/lights", {on: false}); $("#scanLight").textContent = "Light up for a scan"; });
$("#scanUpload").addEventListener("click", () => $("#scanFile").click());
$("#scanFile").addEventListener("change", e => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  log(`scan: uploading ${file.name} ${Math.round(file.size / 1e6)} MB`);
  $("#scanResult").innerHTML = `<p class="note">Uploading ${esc(file.name)} (${(file.size / 1e6).toFixed(1)} MB)…</p><progress id="scanProg" max="1" value="0"></progress>`;
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/scan");
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.setRequestHeader("X-Filename", file.name);
  xhr.upload.onprogress = ev => { if (ev.lengthComputable) $("#scanProg").value = ev.loaded / ev.total; };
  xhr.upload.onload = () => { $("#scanResult").innerHTML = `<p class="note"><span class="spin"></span>Finding the fixtures in 3D…</p>`; };
  xhr.onload = () => {
    let r; try { r = JSON.parse(xhr.responseText); } catch { r = {error: `HTTP ${xhr.status}`}; }
    if (r.error) { $("#scanResult").innerHTML = `<p class="msg bad">${esc(r.error)}</p>`; log(`scan failed: ${r.error}`); return; }
    Object.assign(scan, {result: r, moves: {}, flip: false, picked: null});
    api("/api/placement/lights", {on: false}).catch(() => {});
    $("#scanLight").textContent = "Light up for a scan";
    renderScan();
  };
  xhr.onerror = () => { $("#scanResult").innerHTML = `<p class="msg bad">Upload failed</p>`; };
  xhr.send(file);
});

async function redoScan() {
  try {
    scan.result = await api("/api/scan/redo", {scan: scan.result.scan, flip: scan.flip, moves: scan.moves});
    renderScan();
  } catch (err) { toast(err.message); }
}

function renderScan() {
  const r = scan.result;
  $("#scanResult").innerHTML = `
    <div class="scanview"><canvas id="scanCanvas"></canvas><div class="aud">▼ audience ▼</div></div>
    <p class="note">${r.points.toLocaleString()} points · ceiling ${r.ceiling_m} m · room ${r.room_depth_m ?? "?"} m deep in front.
      Tap a fixture marker, then where it really is, to correct it.</p>
    <div class="row2"><button id="scanFlip">Audience is on the other side</button></div>
    ${r.missing.length ? `<p class="msg bad">Not found in the scan: ${r.missing.map(esc).join(", ")}. Was it lit and in the scan?
      Scan again, or use the photo placement for it.</p>` : ""}
    ${r.fixtures.filter(f => f.spill_only).map(f => `<p class="msg bad">${esc(f.fixture)}: only found its light on a wall: check its marker.</p>`).join("")}
    <h2 style="margin-top:12px">Proposed changes</h2>
    ${r.changes.length ? changeRows(r.changes, "data-scanchange") + `<button class="primary" id="scanApply" style="margin-top:10px">Apply to the rig</button>`
                       : `<p class="note">The rig already matches the scan.</p>`}`;
  drawScan();
}

function drawScan() {
  const r = scan.result, cv = $("#scanCanvas");
  const W = cv.clientWidth * devicePixelRatio, H = Math.round(W * 0.8);
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  const pts = r.preview.filter(p => p[2] > 0.05 && p[2] < 2.2);  // walls and furniture, not floor/ceiling
  const fx = r.fixtures.filter(f => f.x_m != null);
  const xs = fx.map(f => f.x_m), ys = fx.map(f => f.y_m);
  const cx = xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0, cy = ys.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : 0;
  const view = Math.max(3, (Math.max(...xs, 0) - Math.min(...xs, 0)) + 2);  // metres across
  const k = W / view;
  const toPx = (x, y) => [W / 2 + (x - cx) * k, H * 0.4 + (y - cy) * k];  // audience (y+) is down
  scan.view = {cx, cy, k, W, H};
  for (const p of pts) {
    const [px, py] = toPx(p[0], p[1]);
    if (px < 0 || py < 0 || px > W || py > H) continue;
    ctx.fillStyle = `rgb(${p[3] * 255 | 0},${p[4] * 255 | 0},${p[5] * 255 | 0})`;
    ctx.fillRect(px, py, 1.5 * devicePixelRatio, 1.5 * devicePixelRatio);
  }
  ctx.font = `${12 * devicePixelRatio}px system-ui`;
  for (const f of fx) {
    const [px, py] = toPx(f.x_m, f.y_m);
    ctx.beginPath(); ctx.arc(px, py, 7 * devicePixelRatio, 0, 7);
    ctx.fillStyle = f.hex; ctx.fill();
    ctx.lineWidth = (scan.picked === f.fixture ? 4 : 1.5) * devicePixelRatio; ctx.strokeStyle = "#fff"; ctx.stroke();
    ctx.fillStyle = "#fff";
    ctx.fillText(`${f.fixture} ${f.z_m.toFixed(2)} m${f.moved ? " ✎" : ""}`, px + 10 * devicePixelRatio, py + 4 * devicePixelRatio);
  }
  // 1 m scale bar
  ctx.fillStyle = "#8b91a1"; ctx.fillRect(10 * devicePixelRatio, H - 14 * devicePixelRatio, k, 3 * devicePixelRatio);
  ctx.fillText("1 m", 10 * devicePixelRatio, H - 20 * devicePixelRatio);
}

$("#scanResult").addEventListener("click", async e => {
  if (e.target.id === "scanFlip") { scan.flip = !scan.flip; scan.moves = {}; return redoScan(); }
  if (e.target.id === "scanCanvas") {
    const rect = e.target.getBoundingClientRect(), v = scan.view;
    const px = (e.clientX - rect.left) * devicePixelRatio, py = (e.clientY - rect.top) * devicePixelRatio;
    const x = v.cx + (px - v.W / 2) / v.k, y = v.cy + (py - v.H * 0.4) / v.k;
    const hit = scan.result.fixtures.filter(f => f.x_m != null)
      .find(f => Math.hypot((f.x_m - x) * v.k, (f.y_m - y) * v.k) < 18 * devicePixelRatio);
    if (hit) { scan.picked = scan.picked === hit.fixture ? null : hit.fixture; drawScan(); return; }
    if (scan.picked) { scan.moves[scan.picked] = [+x.toFixed(3), +y.toFixed(3)]; scan.picked = null; return redoScan(); }
    return;
  }
  if (e.target.id !== "scanApply") return;
  const chosen = [...document.querySelectorAll("[data-scanchange]")].filter(c => c.checked).map(c => scan.result.changes[+c.dataset.scanchange]);
  try {
    const r = await api("/api/placement/apply", {changes: chosen});
    if (!r.saved) throw new Error(r.problems.join("; "));
    toast(`Rig updated (${chosen.length} change${chosen.length === 1 ? "" : "s"})`);
    e.target.disabled = true; e.target.textContent = "Applied";
    await loadRig();
  } catch (err) { toast(err.message); }
});

// Find each lit colour in the photo: the brightest saturated pixels of that hue (coloured lenses and LEDs;
// overexposed cores are white, their coloured rims count). Returns colour → {x, y, w, h, n} in 0..1.
function lightSpots(dataUrl, lit) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 480 / Math.max(img.width, img.height));
      const W = Math.round(img.width * k), H = Math.round(img.height * k);
      const c = document.createElement("canvas"); c.width = W; c.height = H;
      const ctx = c.getContext("2d"); ctx.drawImage(img, 0, 0, W, H);
      const px = ctx.getImageData(0, 0, W, H).data;
      const hits = Object.fromEntries(lit.map(a => [a.colour, []]));
      for (let i = 0, p = 0; i < px.length; i += 4, p++) {
        const r = px[i] / 255, g = px[i + 1] / 255, b = px[i + 2] / 255;
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b), v = mx, s = mx ? (mx - mn) / mx : 0;
        if (v < 0.5 || s < 0.45) continue;
        const d = mx - mn;
        let h = mx === r ? 60 * (((g - b) / d) % 6) : mx === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
        if (h < 0) h += 360;
        let best = null, bestD = 28;
        for (const a of lit) { const dh = Math.min(Math.abs(h - a.hue), 360 - Math.abs(h - a.hue)); if (dh < bestD) { bestD = dh; best = a.colour; } }
        if (best) hits[best].push([p % W, Math.floor(p / W), v * s]);
      }
      const out = {};
      for (const [colour, list] of Object.entries(hits)) {
        if (list.length < 4) continue;
        const top = Math.max(...list.map(q => q[2]));
        const strong = list.filter(q => q[2] >= 0.75 * top);
        if (strong.length < 3) continue;
        const xs = strong.map(q => q[0]).sort((a, b) => a - b), ys = strong.map(q => q[1]).sort((a, b) => a - b);
        const pct = (arr, f) => arr[Math.min(arr.length - 1, Math.floor(f * arr.length))];
        const x0 = pct(xs, 0.05), x1 = pct(xs, 0.95), y0 = pct(ys, 0.05), y1 = pct(ys, 0.95);
        const wsum = strong.reduce((t, q) => t + q[2], 0);
        out[colour] = {x: strong.reduce((t, q) => t + q[0] * q[2], 0) / wsum / W, y: strong.reduce((t, q) => t + q[1] * q[2], 0) / wsum / H,
                       w: Math.max(2, x1 - x0) / W, h: Math.max(2, y1 - y0) / H, n: strong.length};
      }
      resolve(out);
    };
    img.onerror = () => reject(new Error("Could not read that photo"));
    img.src = dataUrl;
  });
}

loadRig().catch(err => { $("#rig").innerHTML = `<span class="msg bad">${esc(err.message)}</span>`; });
