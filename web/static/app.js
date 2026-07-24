"use strict";

// --- state ---------------------------------------------------------------
const store = {
  get token() { return localStorage.getItem("pib_token") || ""; },
  set token(v) { v ? localStorage.setItem("pib_token", v) : localStorage.removeItem("pib_token"); },
  get apiBase() { return localStorage.getItem("pib_api_base") || ""; },
  set apiBase(v) { v ? localStorage.setItem("pib_api_base", v) : localStorage.removeItem("pib_api_base"); },
  defaults() {
    try { return JSON.parse(localStorage.getItem("pib_defaults") || "{}"); } catch { return {}; }
  },
  setDefaults(d) { localStorage.setItem("pib_defaults", JSON.stringify(d || {})); },
};

let CONFIG = { providers: [], default_master_prompt: "" };
let REFERENCES = [];   // File[]
let MASK = null;       // File | null
let CURRENT_RUN = null;
let EVT = null;

// Default number of versions (images) generated per agent/prompt. Users can
// override per agent or via Settings; this is the "always N versions" default.
const DEFAULT_IMAGES = 20;

let RESULT_COUNT = 0;   // images shown in the current run's gallery
let FAVORITES = new Set();   // favourite filenames for the current run

// --- master-prompt templates ---------------------------------------------
const MASTER_CORE = `PRODUCT CONSISTENCY (applies to every image):
- Keep the exact same product in every image: identical shape, proportions, size ratios, materials, colors, textures and finish.
- Preserve all branding exactly — logo, label text, typography, icons and their placement. Do not alter, translate, reflow, blur or invent any text.
- Do not add, remove, duplicate or swap any product part (cap, lid, nozzle, seams, labels).
- Only the scene may change: background, surface, lighting, camera angle, styling and props.

NO ADDED TEXT:
- Do not add any text, captions, headlines, words, letters, watermarks, signatures, stickers or extra logos anywhere in the image; keep the background and scene free of writing. Only text physically printed on the product stays — never add, translate or invent text.

SINGLE IMAGE ONLY:
- Output exactly one photorealistic product photograph that fills the whole frame as one continuous scene. Never make a collage, photo grid, contact sheet, montage, mosaic, storyboard, split-screen, multiple panels, insets or thumbnails — just one clean single image.`;

const MASTER_TEMPLATES = {
  studio: `${MASTER_CORE}

SETTING & STYLE (Studio-Packshot):
- Clean seamless studio background, high-end commercial product photography.
- Soft key light with believable soft shadows and accurate reflections; neutral, true-to-life color.
- Product tack-sharp, hero angle, shallow depth of field. High resolution, crisp detail, no distortions.`,
  lifestyle: `${MASTER_CORE}

SETTING & STYLE (Lifestyle):
- Real-world lifestyle scene with natural, story-telling context and props that fit the product.
- Natural daylight or warm ambient light, gentle bokeh, believable environment and surfaces.
- Photorealistic, editorial feel; the product stays the clear hero and tack-sharp.`,
  social: `${MASTER_CORE}

SETTING & STYLE (Social Ad):
- Bold, vibrant, scroll-stopping composition for social feeds; punchy color and contrast.
- Dynamic angle, generous clean negative space for later text overlays (but add NO text yourself).
- Modern look, strong lighting, product crisp and prominent.`,
  market: `${MASTER_CORE}

SETTING & STYLE (Marktplatz / E-Commerce):
- Pure white seamless background, even shadowless catalog lighting.
- Straight-on or slight hero angle, product centered and fully in frame with small margins.
- Neutral true color, maximum clarity and detail, marketplace-compliant packshot.`,
};

function applyMasterTemplate(key) {
  const t = MASTER_TEMPLATES[key];
  if (!t) return;
  $("#master-prompt").value = t;
  toast("Master-Vorlage eingesetzt — bei Bedarf anpassen", "success");
}

const $ = (sel, root = document) => root.querySelector(sel);
const api = (path) => `${store.apiBase}${path}`;

// --- auth ----------------------------------------------------------------
async function login(password, apiBase) {
  store.apiBase = apiBase.trim().replace(/\/$/, "");
  const res = await fetch(api("/api/login"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error("Falsches Passwort");
  const data = await res.json();
  store.token = data.token;
}

function authHeaders() { return { "authorization": `Bearer ${store.token}` }; }

async function loadConfig() {
  const res = await fetch(api("/api/config"), { headers: authHeaders() });
  if (res.status === 401) { logout(); throw new Error("Sitzung abgelaufen"); }
  CONFIG = await res.json();
}

function logout() {
  store.token = "";
  if (EVT) { EVT.close(); EVT = null; }
  $("#app").hidden = true;
  $("#login").hidden = false;
}

// --- UI: references ------------------------------------------------------
function renderRefThumbs() {
  const host = $("#ref-thumbs");
  host.innerHTML = "";
  REFERENCES.forEach((file, i) => {
    const div = document.createElement("div");
    div.className = "thumb";
    const img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    const rm = document.createElement("button");
    rm.textContent = "✕";
    rm.onclick = () => { REFERENCES.splice(i, 1); renderRefThumbs(); };
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = file.name;
    div.append(img, rm, name);
    host.appendChild(div);
  });
}

function addReferenceFiles(fileList) {
  for (const f of fileList) {
    if (!/\.(png|jpe?g|webp)$/i.test(f.name)) continue;
    REFERENCES.push(f);
  }
  renderRefThumbs();
}

function setupDropzone() {
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => {
    e.preventDefault(); dz.classList.remove("drag");
  }));
  dz.addEventListener("drop", e => addReferenceFiles(e.dataTransfer.files));
  $("#ref-input").addEventListener("change", e => addReferenceFiles(e.target.files));
  $("#mask-input").addEventListener("change", e => {
    MASK = e.target.files[0] || null;
    const host = $("#mask-thumbs");
    host.innerHTML = "";
    if (MASK) {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(MASK);
      img.style.width = "88px"; img.style.borderRadius = "8px";
      host.appendChild(img);
    }
  });
}

// --- UI: agents ----------------------------------------------------------
let agentCounter = 0;

function providerOptions() {
  return CONFIG.providers.map(p =>
    `<option value="${p.name}"${p.has_key ? "" : ""}>${p.name}${p.has_key ? "" : " (kein Key)"}</option>`
  ).join("");
}

function addAgent(preset) {
  agentCounter++;
  const tpl = $("#agent-template").content.cloneNode(true);
  const row = tpl.querySelector(".agent");
  row.querySelector(".agent-label").textContent = `Agent ${agentCounter}`;

  const provSel = row.querySelector(".provider");
  provSel.innerHTML = providerOptions();
  const modelInput = row.querySelector(".model");
  const listId = `models-${agentCounter}`;
  const datalist = document.createElement("datalist");
  datalist.id = listId;
  modelInput.setAttribute("list", listId);
  row.appendChild(datalist);

  function fillModels(providerName) {
    const p = CONFIG.providers.find(x => x.name === providerName);
    datalist.innerHTML = (p ? p.models : []).map(m => `<option value="${m}">`).join("");
    modelInput.value = p ? p.default_model : "";
  }
  provSel.addEventListener("change", () => fillModels(provSel.value));

  // defaults: preset (Auto-Fill/duplicate) wins, else saved settings defaults,
  // else first provider that has a key.
  const d = store.defaults();
  const withKey = CONFIG.providers.find(p => p.has_key) || CONFIG.providers[0];
  provSel.value = (preset && preset.provider) || d.provider || (withKey ? withKey.name : "openai");
  fillModels(provSel.value);
  const model = (preset && preset.model) || d.model;
  if (model) modelInput.value = model;
  if (preset && preset.prompt) row.querySelector(".prompt").value = preset.prompt;
  const images = (preset && preset.images) || d.images || DEFAULT_IMAGES;
  if (images) row.querySelector(".images").value = images;
  const size = (preset && preset.size) || d.size;
  if (size) row.querySelector(".size").value = size;

  row.querySelector(".remove").addEventListener("click", () => { row.remove(); updateScope(); });
  $("#agents").appendChild(row);
  updateScope();
  return row;
}

function collectAgents() {
  return [...document.querySelectorAll(".agent")].map(row => ({
    provider: row.querySelector(".provider").value,
    model: row.querySelector(".model").value.trim(),
    prompt: row.querySelector(".prompt").value.trim(),
    images: parseInt(row.querySelector(".images").value || "1", 10),
    size: row.querySelector(".size").value.trim() || "1024x1024",
    seed: row.querySelector(".seed").value.trim(),
    strength: row.querySelector(".strength").value.trim(),
  }));
}

function agentRowByIndex(i) {
  return document.querySelectorAll(".agent")[i] || null;
}
function rowForPrompt(promptId) {
  const idx = parseInt(promptId.replace(/\D/g, ""), 10) - 1;
  return agentRowByIndex(idx);
}
function setAgentStatus(promptId, text, state) {
  const row = rowForPrompt(promptId);
  if (!row) return;
  const el = row.querySelector(".agent-status");
  el.textContent = text;
  el.dataset.state = state || "";
}

// --- per-agent elapsed timer (so a slow provider still shows it is working) --
function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}:${String(s % 60).padStart(2, "0")}` : `${s}s`;
}
function startAgentTimer(row) {
  if (!row || row._timer) return;
  row._startTs = performance.now();
  const tick = () => {
    const done = parseInt(row.dataset.done || "0", 10);
    const expected = parseInt(row.dataset.expected || "1", 10);
    const el = row.querySelector(".agent-status");
    el.dataset.state = "run";
    el.textContent = `generiert… ${fmtElapsed(performance.now() - row._startTs)} (${done}/${expected})`;
  };
  tick();
  row._timer = setInterval(tick, 1000);
}
function stopAgentTimer(row) {
  if (row && row._timer) { clearInterval(row._timer); row._timer = null; }
}
function initAgentProgress() {
  document.querySelectorAll(".agent").forEach(row => {
    stopAgentTimer(row);
    const expected = parseInt(row.querySelector(".images").value || "1", 10);
    row.dataset.expected = expected;
    row.dataset.done = 0;
    setAgentBar(row, 0);
  });
}

// --- overall run progress bar -------------------------------------------
function setOverallProgress(done, total) {
  const wrap = $("#overall");
  if (!wrap) return;
  wrap.hidden = total <= 0;
  const pct = total > 0 ? (done / total) * 100 : 0;
  const bar = $("#overall-bar > span");
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  const label = $("#overall-count");
  if (label) label.textContent = `${done}/${total}`;
}
function setAgentBar(row, pct) {
  const bar = row.querySelector(".agent-progress > span");
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
}
function bumpAgentProgress(promptId, by) {
  const row = rowForPrompt(promptId);
  if (!row) return;
  const expected = parseInt(row.dataset.expected || "1", 10);
  const done = Math.min(expected, (parseInt(row.dataset.done || "0", 10) + by));
  row.dataset.done = done;
  setAgentBar(row, (done / expected) * 100);
  return { done, expected };
}

// --- toasts --------------------------------------------------------------
function toast(message, type = "info", ms = 4200) {
  const host = $("#toasts");
  if (!host) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  const kill = () => { el.classList.remove("show"); setTimeout(() => el.remove(), 300); };
  el.addEventListener("click", kill);
  setTimeout(kill, ms);
}

// --- Settings ------------------------------------------------------------
function openSettings() {
  // provider status
  const host = $("#settings-providers");
  host.innerHTML = CONFIG.providers
    .filter(p => p.name !== "mock")
    .map(p => `<div class="status-row"><span class="dot ${p.has_key ? "on" : "off"}"></span>
      <span class="status-name">${p.name}</span>
      <span class="status-tag ${p.has_key ? "on" : ""}">${p.has_key ? "aktiv" : "kein Key"}</span></div>`)
    .join("");
  // budget
  const b = CONFIG.budget || {};
  const cap = b.max_total_cost_usd ? `$${b.max_total_cost_usd.toFixed(2)}` : "kein Limit";
  $("#settings-budget").textContent =
    `Ausgegeben (geschätzt): $${(b.estimated_spend_usd || 0).toFixed(2)} · Deckel: ${cap}`;
  // defaults
  const d = store.defaults();
  const setSel = $("#set-provider");
  setSel.innerHTML = `<option value="">— erster mit Key —</option>` +
    CONFIG.providers.map(p => `<option value="${p.name}">${p.name}${p.has_key ? "" : " (kein Key)"}</option>`).join("");
  setSel.value = d.provider || "";
  const syncSetModels = () => {
    const p = CONFIG.providers.find(x => x.name === setSel.value);
    $("#set-models").innerHTML = (p ? p.models : []).map(m => `<option value="${m}">`).join("");
  };
  setSel.onchange = syncSetModels; syncSetModels();
  $("#set-model").value = d.model || "";
  $("#set-images").value = d.images || DEFAULT_IMAGES;
  $("#set-size").value = d.size || "1024x1024";
  $("#set-apibase").value = store.apiBase;

  settingsTab("budget");   // always open on the first tab
  const m = $("#settings");
  m.hidden = false;
  requestAnimationFrame(() => m.classList.add("show"));
}
function settingsTab(name) {
  document.querySelectorAll("#settings .tab").forEach(t => {
    const on = t.dataset.tab === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll("#settings .tab-panel").forEach(p => {
    const on = p.dataset.panel === name;
    p.classList.toggle("active", on);
    p.hidden = !on;
  });
}
function closeSettings() {
  const m = $("#settings");
  m.classList.remove("show");
  setTimeout(() => { m.hidden = true; }, 200);
}
function saveSettings() {
  store.setDefaults({
    provider: $("#set-provider").value || undefined,
    model: $("#set-model").value.trim() || undefined,
    images: parseInt($("#set-images").value || "1", 10),
    size: $("#set-size").value.trim() || "1024x1024",
  });
  const newBase = $("#set-apibase").value.trim().replace(/\/$/, "");
  store.apiBase = newBase;
  closeSettings();
  toast("Einstellungen gespeichert", "success");
}

// --- Auto-Fill (parse Perplexity text -> master + N agents) --------------
const PERPLEXITY_TEMPLATE =
`Du bist Art Director für Produktfotografie. Ich hänge dir ein oder mehrere
Produktbilder an (bitte genau ansehen und das Produkt exakt erhalten).

Produkt / Kampagne: [HIER KURZ BESCHREIBEN — Marke, Produkt, gewünschter Look/Anlass]
Anzahl Prompts: 10

Erstelle mir:
1) einen MASTER-Prompt: globale Regeln, die das Produkt EXAKT erhalten (Form,
   Proportionen, Logo, Label-Text, Material, Farbe) und Setting, Licht, Kamera
   und Qualität festlegen. Auf Englisch.
2) danach die einzelnen Bild-Prompts (Anzahl wie oben): verschiedene Szenen,
   Hintergründe, Licht und Kamerawinkel — je 1 Zeile, Produkt bleibt identisch.
   Auf Englisch.

Gib die Antwort GENAU in diesem Format aus, ohne weiteren Text:

MASTER:
<master prompt hier>

PROMPTS:
1. <prompt 1>
2. <prompt 2>
3. <prompt 3>
...`;

async function copyPromptWithAnim(btn) {
  const ok = await (async () => {
    try { await navigator.clipboard.writeText(PERPLEXITY_TEMPLATE); return true; }
    catch { return false; }
  })();
  if (!ok) { toast("Kopieren nicht möglich — bitte manuell", "warn"); return; }
  const label = btn.dataset.label || btn.textContent;
  btn.classList.add("copied");
  btn.textContent = "✓ Kopiert!";
  toast("Perplexity-Prompt kopiert — in Perplexity einfügen, Produktinfo + Bilder ergänzen", "success", 5000);
  setTimeout(() => { btn.classList.remove("copied"); btn.textContent = label; }, 1600);
}

function extractPrompts(sectionText) {
  const bullet = /^\s*(?:\d+[.)]|[-*•])\s+/;
  const label = /^\s*prompt\s*\d*\s*[:\-]\s*/i;
  const items = [];
  let cur = null;
  for (const line of sectionText.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    if (bullet.test(line) || label.test(t)) {
      if (cur !== null) items.push(cur.trim());
      cur = t.replace(bullet, "").replace(label, "");
    } else {
      cur = cur === null ? t : `${cur} ${t}`;
    }
  }
  if (cur && cur.trim()) items.push(cur.trim());
  // strip wrapping quotes
  return items.map(s => s.replace(/^["'«»]+|["'«»]+$/g, "").trim()).filter(Boolean);
}

function parseAuto(text) {
  const raw = (text || "").replace(/\r/g, "").replace(/ /g, " ").trim();
  if (!raw) return { master: "", prompts: [] };
  const lines = raw.split("\n");
  const masterLabel = /^\s*master(?:\s*[- ]?\s*prompt)?\s*[:\-]?\s*/i;
  const isMaster = (s) => /^\s*master(?:\s*[- ]?\s*prompt)?\s*[:\-]?\s*(\S.*)?$/i.test(s);
  const isPrompts = (s) => /^\s*(?:prompts?|bilder|shots?)\s*[:\-]?\s*$/i.test(s);
  let mi = -1, pi = -1;
  for (let i = 0; i < lines.length; i++) {
    if (mi < 0 && isMaster(lines[i])) mi = i;
    else if (pi < 0 && isPrompts(lines[i])) pi = i;
  }
  let master = "", promptsText = "";
  if (mi >= 0 && pi >= 0 && mi < pi) {
    const first = lines[mi].replace(masterLabel, "");
    master = [first, ...lines.slice(mi + 1, pi)].join("\n").trim();
    promptsText = lines.slice(pi + 1).join("\n");
  } else if (pi >= 0) {
    master = lines.slice(0, pi).join("\n").replace(masterLabel, "").trim();
    promptsText = lines.slice(pi + 1).join("\n");
  } else {
    const bi = lines.findIndex(l => /^\s*(?:\d+[.)]|[-*•])\s+/.test(l));
    if (bi >= 0) {
      master = lines.slice(0, bi).join("\n").replace(masterLabel, "").trim();
      promptsText = lines.slice(bi).join("\n");
    } else {
      const blocks = raw.split(/\n\s*\n/).map(b => b.trim()).filter(Boolean);
      const m = blocks.shift() || "";
      return { master: m.replace(masterLabel, "").trim(), prompts: blocks };
    }
  }
  return { master, prompts: extractPrompts(promptsText) };
}

function fillAutoProviders() {
  const host = document.getElementById("auto-providers");
  if (!host) return;
  // Pre-check every provider that actually has a key (so each prompt fans out
  // across all usable providers). Fall back to mock if nothing has a key yet.
  const anyKey = CONFIG.providers.some(p => p.has_key && p.name !== "mock");
  host.innerHTML = CONFIG.providers.map(p => {
    const on = anyKey ? (p.has_key && p.name !== "mock") : (p.name === "mock");
    const dis = p.has_key ? "" : "";
    return `<label class="pick${p.has_key ? "" : " nokey"}">
      <input type="checkbox" value="${p.name}"${on ? " checked" : ""}${dis} />
      <span>${p.name}${p.has_key ? "" : " · kein Key"}</span>
    </label>`;
  }).join("");
}
function selectedAutoProviders() {
  return [...document.querySelectorAll("#auto-providers input:checked")].map(c => c.value);
}
function setAutoProviders(on) {
  document.querySelectorAll("#auto-providers input").forEach(c => { c.checked = on; });
  previewAuto();
}

function openAuto() {
  fillAutoProviders();
  $("#auto-input").value = "";
  $("#auto-preview").textContent = "";
  const m = $("#auto");
  m.hidden = false;
  requestAnimationFrame(() => m.classList.add("show"));
  $("#auto-input").focus();
}
function closeAuto() {
  const m = $("#auto");
  m.classList.remove("show");
  setTimeout(() => { m.hidden = true; }, 200);
}
function previewAuto() {
  const { master, prompts } = parseAuto($("#auto-input").value);
  const provs = selectedAutoProviders().length;
  if (!prompts.length) { $("#auto-preview").textContent = "Noch keine Prompts erkannt"; return; }
  const total = prompts.length * provs;
  $("#auto-preview").textContent = provs
    ? `${prompts.length} Prompt(s) × ${provs} Provider = ${total} Agent(en)${master ? " + Master" : ""}`
    : `${prompts.length} Prompt(s) erkannt — bitte Provider auswählen`;
}
function applyAuto() {
  const { master, prompts } = parseAuto($("#auto-input").value);
  if (!prompts.length) { toast("Keine Prompts erkannt — prüfe das Format", "error"); return; }
  const providers = selectedAutoProviders();
  if (!providers.length) { toast("Mindestens einen Provider auswählen", "error"); return; }
  if (master) $("#master-prompt").value = master;
  document.querySelectorAll(".agent").forEach(a => a.remove());
  agentCounter = 0;
  // For every prompt line, create one agent per selected provider so each
  // prompt is generated across all of them in parallel.
  prompts.forEach(p => {
    providers.forEach(prov => {
      const cfg = CONFIG.providers.find(x => x.name === prov);
      addAgent({ provider: prov, model: cfg ? cfg.default_model : "", prompt: p, images: store.defaults().images || DEFAULT_IMAGES });
    });
  });
  closeAuto();
  updateScope();
  const total = prompts.length * providers.length;
  toast(`${total} Agent(en) angelegt — ${prompts.length} Prompt(s) × ${providers.length} Provider${master ? " + Master-Prompt" : ""}`, "success");
}
async function copyTemplate() {
  try {
    await navigator.clipboard.writeText(PERPLEXITY_TEMPLATE);
    toast("Perplexity-Vorlage kopiert", "success");
  } catch {
    toast("Kopieren nicht möglich — Vorlage manuell markieren", "warn");
  }
}

// --- lightbox (with metadata, navigation, actions) -----------------------
let LB_ITEMS = [];
let LB_INDEX = -1;

function openLightboxFor(anchor) {
  const onlyFav = $("#gallery").classList.contains("only-fav");
  LB_ITEMS = [...document.querySelectorAll("#gallery .result-item")]
    .filter(a => !onlyFav || a.classList.contains("is-fav"));
  LB_INDEX = LB_ITEMS.indexOf(anchor);
  if (LB_INDEX < 0) { LB_ITEMS = [anchor]; LB_INDEX = 0; }
  renderLightbox();
  const lb = $("#lightbox");
  lb.hidden = false;
  requestAnimationFrame(() => lb.classList.add("show"));
}
function renderLightbox() {
  const a = LB_ITEMS[LB_INDEX];
  if (!a) return;
  $("#lightbox-img").src = a.dataset.full;
  $("#lightbox-img").alt = `${a.dataset.provider || ""} ${a.dataset.promptId || ""}`.trim();
  $("#lb-provider").textContent = [a.dataset.provider, a.dataset.model].filter(Boolean).join(" · ") || "—";
  $("#lb-index").textContent = LB_ITEMS.length > 1 ? `${LB_INDEX + 1} / ${LB_ITEMS.length}` : "";
  $("#lb-prompt").textContent = a.dataset.prompt || "";
  $("#lb-download").href = a.dataset.full;
  const isFav = a.classList.contains("is-fav");
  const favBtn = $("#lb-fav");
  favBtn.classList.toggle("active", isFav);
  favBtn.textContent = isFav ? "★ Favorit" : "☆ Favorit";
  $("#lb-prev").disabled = LB_INDEX <= 0;
  $("#lb-next").disabled = LB_INDEX >= LB_ITEMS.length - 1;
}
function lbNav(delta) {
  const n = LB_INDEX + delta;
  if (n >= 0 && n < LB_ITEMS.length) { LB_INDEX = n; renderLightbox(); }
}
function lbToggleFav() {
  const a = LB_ITEMS[LB_INDEX];
  if (a) { toggleFavorite(a.dataset.file, a); renderLightbox(); }
}
function lbAsNewSet() {
  const a = LB_ITEMS[LB_INDEX];
  if (!a) return;
  addAgent({ provider: a.dataset.provider, prompt: a.dataset.prompt || "" });
  toast("Als neues Set übernommen — unten anpassen & starten", "success");
  closeLightbox();
  document.querySelector("#agents .agent:last-child")?.scrollIntoView({ behavior: "smooth", block: "center" });
}
function closeLightbox() {
  const lb = $("#lightbox");
  lb.classList.remove("show");
  setTimeout(() => { lb.hidden = true; $("#lightbox-img").src = ""; }, 200);
}

// --- run -----------------------------------------------------------------
const TEST_RUN_IMAGES = 2;

async function startRun(opts = {}) {
  const testRun = !!opts.testRun;
  // Full agent list (indices must line up with the backend); optionally cap the
  // image count for a quick, cheap test run.
  let agentsFull = collectAgents();
  if (testRun) {
    agentsFull = agentsFull.map(a => ({ ...a, images: Math.min(parseInt(a.images, 10) || 1, TEST_RUN_IMAGES) }));
  }
  const agents = agentsFull.filter(a => a.prompt);
  if (REFERENCES.length === 0) { setStatus("Mindestens ein Referenzbild nötig."); return; }
  if (agents.length === 0) { setStatus("Mindestens ein Agent mit Prompt nötig."); return; }

  // Cost/quantity preview — a run can be hundreds of images, so confirm first.
  const totalImages = agents.reduce((s, a) => s + (parseInt(a.images, 10) || 1), 0);
  const est = agents.reduce((s, a) => {
    const p = CONFIG.providers.find(x => x.name === a.provider);
    const price = (p && p.price_per_image != null) ? p.price_per_image : 0.05;
    return s + (parseInt(a.images, 10) || 1) * price;
  }, 0);
  const b = CONFIG.budget || {};
  let budgetLine = "";
  if (b.max_total_cost_usd) {
    const rem = Math.max(0, b.max_total_cost_usd - (b.estimated_spend_usd || 0));
    const warn = est > rem ? ' <span class="danger">— könnte den Deckel sprengen</span>' : "";
    budgetLine = `<br>Budget übrig: ~$${rem.toFixed(2)} von $${b.max_total_cost_usd.toFixed(2)}${warn}`;
  }
  const testLine = testRun ? `<br><span class="muted">Testlauf: nur ${TEST_RUN_IMAGES} Varianten je Set.</span>` : "";
  const ok = await confirmRun(
    `<b>${totalImages} Bild${totalImages === 1 ? "" : "er"}</b> über ${agents.length} Agent${agents.length === 1 ? "" : "en"}.` +
    `<br>Geschätzte Kosten: <b>~$${est.toFixed(2)}</b> <span class="muted">(grobe Schätzung, je nach Modell/Größe)</span>${budgetLine}${testLine}`
  );
  if (!ok) { setStatus("abgebrochen."); return; }

  const fd = new FormData();
  fd.append("config", JSON.stringify({
    name: testRun ? "web-testrun" : "web-run",
    master_prompt: $("#master-prompt").value,
    agents: agentsFull,   // full list so indices line up with backend
  }));
  REFERENCES.forEach(f => fd.append("references", f, f.name));
  if (MASK) fd.append("mask", MASK, MASK.name);

  setStatus("Starte…");
  const gal = $("#gallery");
  gal.innerHTML = ""; gal.classList.remove("only-fav");
  $("#filter-fav").setAttribute("aria-pressed", "false");
  $("#filter-fav").classList.remove("active");
  RESULT_COUNT = 0; FAVORITES = new Set();
  initAgentProgress();
  setOverallProgress(0, 0);
  document.querySelectorAll(".agent-status").forEach(s => { s.textContent = "wartet auf Anbieter", s.dataset.state = "queue"; });
  let res;
  try {
    res = await fetch(api("/api/run"), { method: "POST", headers: authHeaders(), body: fd });
  } catch (ex) {
    setStatus("Start fehlgeschlagen: " + ex.message); toast("Start fehlgeschlagen", "error"); return;
  }
  if (!res.ok) { setStatus("Fehler: " + (await res.text())); toast("Start fehlgeschlagen", "error"); return; }
  const { run_id, total } = await res.json();
  CURRENT_RUN = run_id;
  loadFavorites(); updateResultsToolbar();
  $("#start").disabled = true;
  $("#test-run").disabled = true;
  $("#stop").disabled = false;
  setStatus(`läuft — 0/${total}`);
  setOverallProgress(0, total);
  document.querySelectorAll(".agent-status").forEach(s => { s.textContent = "wartet auf Anbieter"; s.dataset.state = "queue"; });
  toast(`Lauf gestartet — ${total} Bild(er)`, "info");
  streamEvents(run_id, total);
}

function finishRun() {
  document.querySelectorAll(".agent").forEach(stopAgentTimer);
  $("#start").disabled = false; $("#test-run").disabled = false; $("#stop").disabled = true;
  if (EVT) { EVT.close(); EVT = null; }
}

function streamEvents(runId, total) {
  if (EVT) EVT.close();
  let done = 0;
  let finished = false;
  const url = api(`/api/run/${runId}/events?token=${encodeURIComponent(store.token)}`);
  EVT = new EventSource(url);
  EVT.onopen = () => {
    // Cleared after a reconnect so the "reconnecting" notice goes away.
    if (!finished && done < total) setStatus(`läuft — ${done}/${total}`);
  };
  EVT.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "queued") {
      setAgentStatus(ev.prompt_id, "wartet auf Anbieter", "queue");
    }
    else if (ev.type === "running") {
      startAgentTimer(rowForPrompt(ev.prompt_id));
    }
    else if (ev.type === "image") {
      const n = ev.images.length;
      for (const img of ev.images) addResult(runId, img.file, ev.prompt_id, ev.provider, ev.model);
      const prog = bumpAgentProgress(ev.prompt_id, n);
      const row = rowForPrompt(ev.prompt_id);
      if (prog && prog.done >= prog.expected) {
        stopAgentTimer(row);
        setAgentStatus(ev.prompt_id, `✓ fertig (${prog.done}/${prog.expected})`, "ok");
      } else if (prog) {
        setAgentStatus(ev.prompt_id, `generiert… (${prog.done}/${prog.expected})`, "run");
      }
      done += n; setStatus(`läuft — ${done}/${total}`); setOverallProgress(done, total);
      if (ev.budget) updateBudget(ev.budget);
    }
    else if (ev.type === "failed") {
      stopAgentTimer(rowForPrompt(ev.prompt_id));
      setAgentStatus(ev.prompt_id, "✕ " + ev.error, "err");
      toast(`Fehler bei ${ev.prompt_id}: ${ev.error}`, "error");
      done++; setStatus(`läuft — ${done}/${total}`); setOverallProgress(done, total);
    }
    else if (ev.type === "skipped") {
      stopAgentTimer(rowForPrompt(ev.prompt_id));
      setAgentStatus(ev.prompt_id, "übersprungen", "warn");
      done++; setOverallProgress(done, total);
    }
    else if (ev.type === "done") {
      finished = true;
      setStatus(`fertig — ${ev.succeeded} ok, ${ev.failed} Fehler, ${ev.skipped} übersprungen`);
      setOverallProgress(total, total);
      if (ev.budget) updateBudget(ev.budget);
      finishRun();
      const kind = ev.failed ? "warn" : "success";
      toast(`Fertig — ${ev.succeeded} ok${ev.failed ? `, ${ev.failed} Fehler` : ""}${ev.skipped ? `, ${ev.skipped} übersprungen` : ""}`, kind, 6000);
      if (!document.querySelector("#gallery img")) {
        $("#gallery").innerHTML = '<p class="empty muted">Keine Bilder erzeugt — prüfe Provider-Key & Prompt.</p>';
      }
    }
    else if (ev.type === "error") { setStatus("Fehler: " + ev.message); toast(ev.message, "error"); }
  };
  EVT.onerror = () => {
    // EventSource auto-reconnects; the server keeps the run's event queue, so a
    // dropped connection is recoverable. Only give up once the run is truly done.
    if (finished) { finishRun(); return; }
    setStatus(`Verbindung wird wiederhergestellt… — ${done}/${total}`);
  };
}

// Find (or create) the per-agent result group so hundreds of images stay
// grouped by their prompt instead of one endless flat grid.
function resultGroup(promptId, provider) {
  const gallery = $("#gallery");
  const empty = gallery.querySelector(".empty");
  if (empty) empty.remove();
  const key = promptId || "a00";
  let g = gallery.querySelector(`.result-group[data-group="${key}"]`);
  if (!g) {
    g = document.createElement("div");
    g.className = "result-group";
    g.dataset.group = key;
    g.dataset.n = "0";
    const num = parseInt(key.replace(/\D/g, ""), 10) || "";
    const row = rowForPrompt(key);
    const promptTxt = row ? (row.querySelector(".prompt").value || "").trim() : "";
    const head = document.createElement("div");
    head.className = "result-group-head";
    const meta = document.createElement("div");
    meta.className = "rg-meta";
    const title = document.createElement("span");
    title.className = "rg-title";
    title.textContent = `Agent ${num}${provider ? " · " + provider : ""}`;
    const sub = document.createElement("span");
    sub.className = "rg-sub muted";
    sub.textContent = promptTxt;
    sub.title = promptTxt;
    meta.append(title, sub);
    const count = document.createElement("span");
    count.className = "rg-count";
    count.textContent = "0";
    head.append(meta, count);
    const grid = document.createElement("div");
    grid.className = "result-grid";
    g.append(head, grid);
    gallery.appendChild(g);
  }
  return g;
}

function addResult(runId, filename, promptId, provider, model) {
  const g = resultGroup(promptId, provider);
  const grid = g.querySelector(".result-grid");
  const base = api(`/api/run/${runId}/image/${encodeURIComponent(filename)}?token=${encodeURIComponent(store.token)}`);
  const full = base;
  const thumb = base + "&thumb=1";
  const row = rowForPrompt(promptId);
  const promptText = row ? (row.querySelector(".prompt").value || "").trim() : "";
  const a = document.createElement("a");
  a.href = full;
  a.className = "result-item";
  a.dataset.full = full;
  a.dataset.file = filename;
  a.dataset.provider = provider || "";
  a.dataset.model = model || "";
  a.dataset.promptId = promptId || "";
  a.dataset.prompt = promptText;
  if (FAVORITES.has(filename)) a.classList.add("is-fav");
  // Grid shows a lightweight thumbnail; the lightbox opens the full image.
  a.addEventListener("click", (e) => { e.preventDefault(); openLightboxFor(a); });
  const img = document.createElement("img");
  img.src = thumb; img.loading = "lazy"; img.decoding = "async";
  img.alt = `Ergebnis ${provider || ""} ${promptId || ""}`.trim();
  // Favourite star (always visible on touch; hover on desktop).
  const star = document.createElement("button");
  star.className = "fav-star";
  star.type = "button";
  star.textContent = "★";
  star.title = "Als Favorit markieren";
  star.setAttribute("aria-label", "Als Favorit markieren");
  star.setAttribute("aria-pressed", FAVORITES.has(filename) ? "true" : "false");
  star.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); toggleFavorite(filename, a); });
  a.append(img, star);
  grid.appendChild(a);
  g.dataset.n = String((parseInt(g.dataset.n, 10) || 0) + 1);
  g.querySelector(".rg-count").textContent = g.dataset.n;
  RESULT_COUNT++;
  updateResultsToolbar();
}

async function stopRun() {
  if (!CURRENT_RUN) return;
  await fetch(api(`/api/run/${CURRENT_RUN}/cancel`), { method: "POST", headers: authHeaders() });
  setStatus("gestoppt.");
  toast("Lauf gestoppt", "warn");
}

function setStatus(t) { $("#status").textContent = t; }
function updateBudget(b) {
  if (b) CONFIG.budget = b;   // keep the cached budget fresh for the cost preview
  const s = (b || CONFIG.budget || {});
  $("#budget").textContent = `Budget: $${(s.estimated_spend_usd || 0).toFixed(2)}`;
}

// --- results toolbar (count + ZIP download) ------------------------------
function updateResultsToolbar() {
  const c = $("#results-count");
  const z = $("#download-zip");
  const ff = $("#filter-fav");
  const df = $("#download-fav");
  const hasImages = RESULT_COUNT > 0;
  c.hidden = !hasImages;
  z.hidden = !hasImages;
  if (hasImages) c.textContent = `${RESULT_COUNT} Bild${RESULT_COUNT === 1 ? "" : "er"}`;
  const favN = FAVORITES.size;
  ff.hidden = !hasImages;
  df.hidden = favN === 0;
  if (favN) df.textContent = `⬇ Favoriten (${favN})`;
}
function downloadAllZip() {
  if (!CURRENT_RUN || RESULT_COUNT === 0) return;
  const url = api(`/api/run/${CURRENT_RUN}/download?token=${encodeURIComponent(store.token)}`);
  const a = document.createElement("a");
  a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
  toast("ZIP wird erstellt & geladen…", "info");
}

// --- confirm-before-start modal ------------------------------------------
let _confirmResolve = null;
function confirmRun(html) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    $("#confirm-text").innerHTML = html;
    const m = $("#confirm");
    m.hidden = false;
    requestAnimationFrame(() => m.classList.add("show"));
  });
}
function closeConfirm(val) {
  const m = $("#confirm");
  m.classList.remove("show");
  setTimeout(() => { m.hidden = true; }, 180);
  if (_confirmResolve) { const r = _confirmResolve; _confirmResolve = null; r(val); }
}

// --- live run scope (updates as agents/counts change) --------------------
function runScope() {
  const agents = collectAgents().filter(a => a.prompt);
  const images = agents.reduce((s, a) => s + (parseInt(a.images, 10) || 1), 0);
  const est = agents.reduce((s, a) => {
    const p = CONFIG.providers.find(x => x.name === a.provider);
    const price = (p && p.price_per_image != null) ? p.price_per_image : 0.05;
    return s + (parseInt(a.images, 10) || 1) * price;
  }, 0);
  return { count: agents.length, images, est };
}
function updateScope() {
  const el = $("#scope");
  if (!el) return;
  const { count, images, est } = runScope();
  el.textContent = count
    ? `${images} Bild${images === 1 ? "" : "er"} · ${count} Set${count === 1 ? "" : "s"} · ~$${est.toFixed(2)}`
    : "";
}

// --- favourites ----------------------------------------------------------
function favKey() { return `pib_fav_${CURRENT_RUN || "none"}`; }
function loadFavorites() {
  try { FAVORITES = new Set(JSON.parse(localStorage.getItem(favKey()) || "[]")); }
  catch { FAVORITES = new Set(); }
}
function saveFavorites() {
  try { localStorage.setItem(favKey(), JSON.stringify([...FAVORITES])); } catch { /* ignore */ }
}
function toggleFavorite(filename, linkEl) {
  if (FAVORITES.has(filename)) { FAVORITES.delete(filename); linkEl.classList.remove("is-fav"); }
  else { FAVORITES.add(filename); linkEl.classList.add("is-fav"); }
  const star = linkEl.querySelector(".fav-star");
  if (star) star.setAttribute("aria-pressed", FAVORITES.has(filename) ? "true" : "false");
  saveFavorites();
  updateResultsToolbar();
}
function downloadFavorites() {
  if (!CURRENT_RUN || FAVORITES.size === 0) return;
  const list = [...FAVORITES].map(encodeURIComponent).join(",");
  const url = api(`/api/run/${CURRENT_RUN}/download?token=${encodeURIComponent(store.token)}&files=${list}`);
  const a = document.createElement("a");
  a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
  toast(`${FAVORITES.size} Favorit(en) als ZIP…`, "info");
}
function toggleFavFilter() {
  const g = $("#gallery");
  const on = g.classList.toggle("only-fav");
  const btn = $("#filter-fav");
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.classList.toggle("active", on);
}

// --- boot ----------------------------------------------------------------
async function enterApp() {
  await loadConfig();
  $("#login").hidden = true;
  $("#app").hidden = false;
  $("#master-prompt").value = CONFIG.default_master_prompt || "";
  if (!document.querySelector(".agent")) addAgent();
  updateBudget(CONFIG.budget || {});
  updateScope();
}

function wire() {
  $("#api-base").value = store.apiBase;
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#login-error");
    err.hidden = true;
    try {
      await login($("#password").value, $("#api-base").value);
      await enterApp();
    } catch (ex) {
      err.textContent = ex.message; err.hidden = false;
      toast(ex.message, "error");
    }
  });
  $("#logout").addEventListener("click", logout);
  // Settings
  $("#settings-open").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-cancel").addEventListener("click", closeSettings);
  $("#settings-save").addEventListener("click", saveSettings);
  $("#settings").addEventListener("click", (e) => { if (e.target.id === "settings") closeSettings(); });
  document.querySelectorAll("#settings .tab").forEach(t =>
    t.addEventListener("click", () => settingsTab(t.dataset.tab)));
  // lightbox close: button, backdrop click, Esc; navigation + actions
  $("#lightbox-close").addEventListener("click", closeLightbox);
  $("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox" || e.target.classList.contains("lb-figure")) closeLightbox(); });
  $("#lb-prev").addEventListener("click", () => lbNav(-1));
  $("#lb-next").addEventListener("click", () => lbNav(1));
  $("#lb-fav").addEventListener("click", lbToggleFav);
  $("#lb-asset").addEventListener("click", lbAsNewSet);
  document.addEventListener("keydown", (e) => {
    if ($("#lightbox").hidden) return;
    if (e.key === "Escape") closeLightbox();
    else if (e.key === "ArrowLeft") lbNav(-1);
    else if (e.key === "ArrowRight") lbNav(1);
  });
  // swipe navigation on touch
  let _sx = 0, _sy = 0;
  const lbImg = $("#lightbox-img");
  lbImg.addEventListener("touchstart", (e) => { _sx = e.touches[0].clientX; _sy = e.touches[0].clientY; }, { passive: true });
  lbImg.addEventListener("touchend", (e) => {
    const dx = e.changedTouches[0].clientX - _sx, dy = e.changedTouches[0].clientY - _sy;
    if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) lbNav(dx < 0 ? 1 : -1);
  }, { passive: true });
  $("#reset-master").addEventListener("click", () => $("#master-prompt").value = CONFIG.default_master_prompt || "");
  $("#clear-master").addEventListener("click", () => $("#master-prompt").value = "");
  $("#add-agent").addEventListener("click", () => addAgent());
  $("#start").addEventListener("click", () => startRun());
  $("#test-run").addEventListener("click", () => startRun({ testRun: true }));
  $("#stop").addEventListener("click", stopRun);
  document.querySelectorAll(".tmpl").forEach(btn =>
    btn.addEventListener("click", () => applyMasterTemplate(btn.dataset.tmpl)));
  $("#download-zip").addEventListener("click", downloadAllZip);
  $("#download-fav").addEventListener("click", downloadFavorites);
  $("#filter-fav").addEventListener("click", toggleFavFilter);
  $("#agents").addEventListener("input", updateScope);
  $("#agents").addEventListener("change", updateScope);
  // Confirm-before-start modal
  $("#confirm-ok").addEventListener("click", () => closeConfirm(true));
  $("#confirm-cancel").addEventListener("click", () => closeConfirm(false));
  $("#confirm-close").addEventListener("click", () => closeConfirm(false));
  $("#confirm").addEventListener("click", (e) => { if (e.target.id === "confirm") closeConfirm(false); });
  // Perplexity prompt copy (with animation)
  $("#get-prompt").addEventListener("click", (e) => copyPromptWithAnim(e.currentTarget));
  // Auto-Fill
  $("#auto-open").addEventListener("click", openAuto);
  $("#auto-close").addEventListener("click", closeAuto);
  $("#auto-cancel").addEventListener("click", closeAuto);
  $("#auto-apply").addEventListener("click", applyAuto);
  $("#auto-copy-template").addEventListener("click", copyTemplate);
  $("#auto-input").addEventListener("input", previewAuto);
  $("#auto-providers").addEventListener("change", previewAuto);
  $("#auto-all").addEventListener("click", () => setAutoProviders(true));
  $("#auto-none").addEventListener("click", () => setAutoProviders(false));
  $("#auto").addEventListener("click", (e) => { if (e.target.id === "auto") closeAuto(); });
  setupDropzone();
}

document.addEventListener("DOMContentLoaded", async () => {
  wire();
  // auto-resume if a valid token is already stored
  if (store.token) {
    try { await enterApp(); } catch { /* show login */ }
  }
});
