const $ = id => document.getElementById(id);
let rig = null, library = [], directors = [];
const lib = key => library.find(l => l.key === key);
const footprint = f => (lib(f.fixture)?.modes || {})[f.mode] || 0;

function msg(text, kind = "") { const m = $("msg"); m.textContent = text; m.className = "msg " + kind; }

async function load() {
  try {
  [library, rig, directors] = await Promise.all([fetch("/api/library").then(r => r.json()),
    fetch("/api/rig").then(r => r.json()), fetch("/api/directors").then(r => r.json())]);
  const cur = rig.director || "rules";
  if (!directors.some(d => d.value === cur)) directors.push({ value: cur, label: cur, available: false, note: "not available right now" });
  $("director").innerHTML = directors.map(d =>
    `<option value="${d.value}" ${d.value === cur ? "selected" : ""} ${d.available ? "" : "disabled"}>${d.label}${d.available ? "" : " (unavailable)"}</option>`).join("");
  showDirectorNote();
  rig.stage ||= {}; rig.safety ||= {}; rig.artnet ||= {};
  $("addModel").innerHTML = library.map(l => `<option value="${l.key}">${l.manufacturer} ${l.model}</option>`).join("");
  $("ip").value = rig.artnet.ip || ""; $("port").value = rig.artnet.port || 6454; $("fps").value = rig.artnet.fps || 40;
  const out = Array.isArray(rig.output) ? rig.output[0] : rig.output;
  $("outType").value = out?.type || "artnet";
  if (out?.type === "sacn") { $("ip").value = out.ip || ""; $("prio").value = out.priority ?? 100; }
  if (out?.type === "enttec_pro") {
    if (out.port && out.port !== "auto") $("usbPort").add(new Option(out.port, out.port));
    $("usbPort").value = out.port || "auto"; $("usbUni").value = out.universe || 1;
  }
  showOutput();
  $("width").value = rig.stage.width_m ?? 6; $("ceiling").value = rig.stage.ceiling_m ?? 4.5; $("depth").value = rig.stage.room_depth_m ?? 6;
  $("outdoor").checked = !!rig.stage.outdoor;
  $("master").value = rig.safety.master ?? 1; $("masterVal").textContent = Math.round($("master").value * 100) + "%";
  $("strobe").checked = !!rig.safety.allow_fast_strobe;
  render(); msg("");
  } catch (e) {
    msg("Can't reach the show/setup server. Start it (amadeus live or amadeus setup) and reload this page.", "bad");
  }
}

function showDirectorNote() {
  const d = directors.find(x => x.value === $("director").value);
  $("directorNote").textContent = d ? d.note : "";
}

function overlaps() {
  const used = {}, bad = new Set();
  for (const f of rig.fixtures) for (let c = f.address; c < f.address + footprint(f); c++) {
    const k = f.universe + ":" + c;
    if (used[k]) { bad.add(f.id); bad.add(used[k]); } else used[k] = f.id;
    if (c > 512 || c < 1) bad.add(f.id);
  }
  return bad;
}

function render() {
  const bad = overlaps();
  $("rows").innerHTML = rig.fixtures.map((f, i) => {
    const l = lib(f.fixture), n = footprint(f), head = l?.kind === "moving_head";
    const modes = Object.entries(l?.modes || {}).map(([m, c]) => `<option value="${m}" ${m === f.mode ? "selected" : ""}>${m} (${c} ch)</option>`).join("");
    return `<tr>
      <td><input data-i="${i}" data-k="id" value="${f.id}" size="8"></td>
      <td>${l ? l.manufacturer + " " + l.model : f.fixture}</td>
      <td><select data-i="${i}" data-k="mode">${modes}</select></td>
      <td><input data-i="${i}" data-k="universe" type="number" min="0" value="${f.universe}"></td>
      <td><input data-i="${i}" data-k="address" type="number" min="1" max="512" value="${f.address}"></td>
      <td class="ch ${bad.has(f.id) ? "bad" : ""}">${f.address}–${f.address + n - 1}${bad.has(f.id) ? " ⚠ overlap" : ""}</td>
      <td class="hide-sm">${head ? `<select data-i="${i}" data-k="mount">${["stand", "floor", "hang"].map(m => `<option ${m === (f.mount || "stand") ? "selected" : ""}>${m}</option>`).join("")}</select>` : ""}</td>
      <td class="hide-sm"><input data-i="${i}" data-k="x" type="range" min="0" max="1" step="0.01" value="${f.x ?? 0.5}"></td>
      <td><button data-act="identify" data-i="${i}">Identify</button> <button data-act="remove" data-i="${i}">Remove</button></td>
    </tr>`;
  }).join("");
}

$("rows").addEventListener("change", e => {
  const el = e.target, i = +el.dataset.i, k = el.dataset.k; if (!k) return;
  const v = ["universe", "address"].includes(k) ? parseInt(el.value) : k === "x" ? parseFloat(el.value) : el.value;
  rig.fixtures[i][k] = v; render();
});
$("rows").addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return;
  const i = +b.dataset.i;
  if (b.dataset.act === "remove") { rig.fixtures.splice(i, 1); render(); }
  if (b.dataset.act === "identify") {
    collect();
    const r = await fetch("/api/identify", { method: "POST", body: JSON.stringify({ fixture: rig.fixtures[i].id, rig }) }).then(r => r.json());
    msg(r.error ? r.error : `Identifying ${rig.fixtures[i].id} (2 s white)`, r.error ? "bad" : "good");
  }
});
$("add").onclick = () => {
  const key = $("addModel").value, l = lib(key), n = Math.max(1, +$("addCount").value || 1);
  const last = rig.fixtures.reduce((m, f) => f.universe === (rig.fixtures[0]?.universe ?? 1) ? Math.max(m, f.address + footprint(f)) : m, 1);
  let addr = last;
  for (let k = 0; k < n; k++) {
    const base = key.split("/")[1].match(/[a-z]+/)[0]; let j = 1; while (rig.fixtures.some(f => f.id === base + j)) j++;
    const f = { id: base + j, fixture: key, mode: l.default_mode, universe: rig.fixtures[0]?.universe ?? 1, address: addr, x: 0.5 };
    if (l.kind === "moving_head") f.mount = "stand";
    rig.fixtures.push(f); addr += l.modes[l.default_mode];
  }
  render();
};
$("autopatch").onclick = async () => {
  const r = await fetch("/api/autopatch", { method: "POST", body: JSON.stringify({ fixtures: rig.fixtures }) }).then(r => r.json());
  if (r.error) return msg(r.error, "bad");
  rig.fixtures = r.fixtures; render(); msg("Addresses and positions assigned. Save to keep them.", "good");
};
$("find").onclick = async () => {
  $("nodes").textContent = "Searching …";
  const r = await fetch("/api/discover", { method: "POST" }).then(r => r.json());
  if (r.error) return $("nodes").textContent = r.error;
  if (!r.nodes.length) return $("nodes").textContent = "No Art-Net node answered. Is it powered and on this network?";
  $("nodes").innerHTML = r.nodes.map(n => `<button data-ip="${n.ip}" data-port="${n.port}">Use ${n.name} at ${n.ip} (universes ${n.outputs.join(", ")})</button>`).join("");
};
$("nodes").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; $("ip").value = b.dataset.ip; $("port").value = b.dataset.port; });
$("director").onchange = async () => {
  showDirectorNote();
  const value = $("director").value;
  const r = await fetch("/api/director", { method: "POST", body: JSON.stringify({ director: value }) })
    .then(r => r.json()).catch(() => ({ error: "No connection to the show/setup server. Is it still running?" }));
  if (r.error) { $("directorNote").textContent = "⚠ " + r.error; return; }
  rig.director = value;
  $("directorNote").textContent = "✓ Switched to " + $("director").selectedOptions[0].text + " and saved";
};
$("master").oninput = () => $("masterVal").textContent = Math.round($("master").value * 100) + "%";

// the DMX output: Art-Net and sACN go to a network node (a Showtec NET-2/3 or NET-2/5 Pocket speaks both;
// set the node's input protocol to match), the USB widget plugs into this Mac
function showOutput() {
  const t = $("outType").value;
  $("netRow").style.display = t === "enttec_pro" ? "none" : "";
  $("usbRow").style.display = t === "enttec_pro" ? "" : "none";
  document.querySelectorAll(".artnetOnly").forEach(e => e.style.display = t === "artnet" ? "" : "none");
  document.querySelectorAll(".sacnOnly").forEach(e => e.style.display = t === "sacn" ? "" : "none");
  if (t === "sacn" && !$("prio").value) $("prio").value = 100;
  $("ip").placeholder = t === "sacn" ? "empty: multicast" : "";
  $("outNote").textContent = {
    artnet: "Art-Net: the node's IP (or a broadcast like 2.255.255.255). Universe 1 = the node's first port.",
    sacn: "sACN: leave the IP empty for multicast (most nodes), or give one node's IP. Set the node's input protocol to sACN (Showtec NET-2: in its menu or web page).",
    enttec_pro: "USB: ENTTEC DMX USB Pro / Pro Mk2, DMXking ultraDMX, Eurolite USB-DMX512-PRO and other Pro-compatible interfaces. One universe per interface.",
  }[t];
}
$("outType").onchange = showOutput;
$("findUsb").onclick = async () => {
  $("outNote").textContent = "Looking for USB interfaces …";
  const r = await fetch("/api/outputs").then(r => r.json());
  const keep = $("usbPort").value;
  $("usbPort").innerHTML = `<option value="auto">first one found</option>` + r.usb.map(p =>
    `<option value="${p.port}">${p.port}${p.pro ? " ✓ DMX USB Pro" + (p.widget_serial ? " #" + p.widget_serial : "") : ""}${p.manufacturer ? " · " + p.manufacturer : ""}</option>`).join("");
  $("usbPort").value = [...$("usbPort").options].some(o => o.value === keep) ? keep : (r.usb.find(p => p.pro)?.port || "auto");
  $("outNote").textContent = r.usb.length ? `${r.usb.length} USB serial device(s); ✓ = answers the DMX USB Pro protocol.`
                                          : "No USB serial devices found. Is the interface plugged in?";
};

function collect() {
  rig.director = $("director").value;
  const t = $("outType").value;
  if (t === "artnet") {
    rig.artnet = { ...rig.artnet, ip: $("ip").value.trim(), port: +$("port").value || 6454, fps: +$("fps").value || 40 };
    delete rig.output;
  } else if (t === "sacn") {
    rig.artnet = { ...rig.artnet, fps: +$("fps").value || 40 };
    rig.output = { type: "sacn", priority: +$("prio").value || 100 };
    if ($("ip").value.trim()) rig.output.ip = $("ip").value.trim();
  } else {
    rig.output = { type: "enttec_pro", port: $("usbPort").value, universe: +$("usbUni").value || 1 };
  }
  rig.stage = { ...rig.stage, width_m: +$("width").value, ceiling_m: +$("ceiling").value, room_depth_m: +$("depth").value, outdoor: $("outdoor").checked };
  rig.safety = { ...rig.safety, master: +$("master").value, allow_fast_strobe: $("strobe").checked };
}
$("save").onclick = async () => {
  collect();
  const r = await fetch("/api/rig", { method: "POST", body: JSON.stringify(rig) }).then(r => r.json());
  if (r.error) msg(r.error, "bad");
  else if (!r.saved) msg("Not saved: " + r.problems.join("; "), "bad");
  else msg("Saved. A running show picks it up after a restart.", "good");
};
$("reload").onclick = load;

// ---------- sets
async function loadSets() {
  const r = await fetch("/api/sets").then(r => r.json());
  const active = r.sets.find(s => s.active);
  $("setSel").innerHTML = r.sets.map(s => `<option value="${s.name}" ${s.active ? "selected" : ""}>${s.name} (${s.fixtures} fixtures)</option>`).join("");
  $("rigSel").innerHTML = r.rigs.map(g => `<option value="${g.name}" ${g.active ? "selected" : ""}>${g.name} (${g.width_m} m, ${g.trusses} trusses)</option>`).join("");
  rigTemplates = r.templates || {};
  const fixed = r.fixed;
  for (const id of ["setSel", "setCopy", "setNew", "setDel", "gMake", "rigSel", "rigNew"]) $(id).disabled = !!fixed;
  $("setNote").textContent = fixed
    ? `This server edits ${fixed} (started with --set/--rig, or a show is running with it). Start "amadeus setup" without --set to manage sets here.`
    : `${active?.description || active?.summary || ""} · ${active?.output || "Art-Net " + (active?.artnet || "?")} · play/live/setup start with this set on this rig unless given --set / --rig.`;
  $("gModel").innerHTML = library.filter(l => l.kind === "moving_head").concat(library.filter(l => l.kind !== "moving_head"))
    .map(l => `<option value="${l.key}" ${/encore/i.test(l.model) ? "selected" : ""}>${l.manufacturer} ${l.model}</option>`).join("");
}
async function setsPost(body) {
  const r = await fetch("/api/sets", { method: "POST", body: JSON.stringify(body) }).then(r => r.json());
  if (r.error) { msg(r.error, "bad"); return; }
  await load(); await loadSets();
}
$("setSel").onchange = () => setsPost({ active: $("setSel").value });
let rigTemplates = {};
async function rigsPost(body, path = "/api/rigs") {
  const r = await fetch(path, { method: "POST", body: JSON.stringify(body) }).then(r => r.json());
  if (r.error) { msg(r.error, "bad"); return; }
  await load(); await loadSets();
}
$("rigSel").onchange = () => rigsPost({ active: $("rigSel").value });
$("rigNew").onclick = () => {
  const t = prompt("Template: " + Object.entries(rigTemplates).map(([k, v]) => `${k} (${v})`).join("; "), "club"); if (!t) return;
  const n = prompt("Name of the new rig:", t); if (!n) return;
  const w = +prompt("Stage width in metres:", "10") || 10;
  rigsPost({ name: n, template: t, width: w, screen: t === "club" || t === "stage" });
};
$("rigMount").onclick = () => rigsPost({}, "/api/automount");
$("setCopy").onclick = () => { const n = prompt("Name of the new set (a copy of this one):"); if (n) setsPost({ name: n, copy: $("setSel").value }); };
$("setNew").onclick = () => { const n = prompt("Name of the new, empty set:"); if (n) setsPost({ name: n }); };
$("setDel").onclick = () => { const n = $("setSel").value; if (confirm(`Delete the set "${n}"? Its fixtures and patch are removed (the rigs stay).`)) setsPost({ delete: n }); };
$("gMake").onclick = () => {
  const n = prompt("Name of the new set:", `grid${$("gCount").value}`); if (!n) return;
  setsPost({ name: n, grid: { layout: $("gLayout").value, model: $("gModel").value, count: +$("gCount").value, rows: +$("gRows").value,
             width: +$("gWidth").value, height: +$("gHeight").value, depth: +$("gDepth").value,
             lasers: +$("gLasers").value } });
};
load().then(loadSets);
