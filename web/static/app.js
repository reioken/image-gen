"use strict";

// --- state ---------------------------------------------------------------
const store = {
  get token() { return localStorage.getItem("pib_token") || ""; },
  set token(v) { v ? localStorage.setItem("pib_token", v) : localStorage.removeItem("pib_token"); },
  get apiBase() { return localStorage.getItem("pib_api_base") || ""; },
  set apiBase(v) { v ? localStorage.setItem("pib_api_base", v) : localStorage.removeItem("pib_api_base"); },
};

let CONFIG = { providers: [], default_master_prompt: "" };
let REFERENCES = [];   // File[]
let MASK = null;       // File | null
let CURRENT_RUN = null;
let EVT = null;

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

  // preset defaults: pick first provider that has a key, else first
  const withKey = CONFIG.providers.find(p => p.has_key) || CONFIG.providers[0];
  provSel.value = (preset && preset.provider) || (withKey ? withKey.name : "openai");
  fillModels(provSel.value);
  if (preset) {
    if (preset.model) modelInput.value = preset.model;
    if (preset.prompt) row.querySelector(".prompt").value = preset.prompt;
    if (preset.images) row.querySelector(".images").value = preset.images;
  }

  row.querySelector(".remove").addEventListener("click", () => row.remove());
  $("#agents").appendChild(row);
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
function initAgentProgress() {
  document.querySelectorAll(".agent").forEach(row => {
    const expected = parseInt(row.querySelector(".images").value || "1", 10);
    row.dataset.expected = expected;
    row.dataset.done = 0;
    setAgentBar(row, 0);
  });
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

// --- lightbox ------------------------------------------------------------
function openLightbox(url) {
  const lb = $("#lightbox");
  $("#lightbox-img").src = url;
  lb.hidden = false;
  requestAnimationFrame(() => lb.classList.add("show"));
}
function closeLightbox() {
  const lb = $("#lightbox");
  lb.classList.remove("show");
  setTimeout(() => { lb.hidden = true; $("#lightbox-img").src = ""; }, 200);
}

// --- run -----------------------------------------------------------------
async function startRun() {
  const agents = collectAgents().filter(a => a.prompt);
  if (REFERENCES.length === 0) { setStatus("Mindestens ein Referenzbild nötig."); return; }
  if (agents.length === 0) { setStatus("Mindestens ein Agent mit Prompt nötig."); return; }

  const fd = new FormData();
  fd.append("config", JSON.stringify({
    name: "web-run",
    master_prompt: $("#master-prompt").value,
    agents: collectAgents(),   // full list so indices line up with backend
  }));
  REFERENCES.forEach(f => fd.append("references", f, f.name));
  if (MASK) fd.append("mask", MASK, MASK.name);

  setStatus("Starte…");
  $("#gallery").innerHTML = "";
  initAgentProgress();
  document.querySelectorAll(".agent-status").forEach(s => { s.textContent = "wartet"; s.dataset.state = ""; });
  const res = await fetch(api("/api/run"), { method: "POST", headers: authHeaders(), body: fd });
  if (!res.ok) { setStatus("Fehler: " + (await res.text())); toast("Start fehlgeschlagen", "error"); return; }
  const { run_id, total } = await res.json();
  CURRENT_RUN = run_id;
  $("#start").disabled = true;
  $("#stop").disabled = false;
  setStatus(`läuft — 0/${total}`);
  toast(`Lauf gestartet — ${total} Bild(er)`, "info");
  streamEvents(run_id, total);
}

function streamEvents(runId, total) {
  if (EVT) EVT.close();
  let done = 0;
  EVT = new EventSource(api(`/api/run/${runId}/events?token=${encodeURIComponent(store.token)}`));
  EVT.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "started") {
      const row = rowForPrompt(ev.prompt_id);
      const p = row ? `läuft (${row.dataset.done || 0}/${row.dataset.expected || 1})` : "läuft…";
      setAgentStatus(ev.prompt_id, p, "run");
    }
    else if (ev.type === "image") {
      const n = ev.images.length;
      for (const img of ev.images) addResult(runId, img.file);
      const prog = bumpAgentProgress(ev.prompt_id, n);
      if (prog) setAgentStatus(ev.prompt_id, prog.done >= prog.expected ? "✓ fertig" : `läuft (${prog.done}/${prog.expected})`, prog.done >= prog.expected ? "ok" : "run");
      done += n; setStatus(`läuft — ${done}/${total}`);
      if (ev.budget) updateBudget(ev.budget);
    }
    else if (ev.type === "failed") {
      setAgentStatus(ev.prompt_id, "✕ " + ev.error, "err");
      toast(`Fehler bei ${ev.prompt_id}: ${ev.error}`, "error");
      done++; setStatus(`läuft — ${done}/${total}`);
    }
    else if (ev.type === "skipped") { setAgentStatus(ev.prompt_id, "übersprungen", "warn"); done++; }
    else if (ev.type === "done") {
      setStatus(`fertig — ${ev.succeeded} ok, ${ev.failed} Fehler, ${ev.skipped} übersprungen`);
      if (ev.budget) updateBudget(ev.budget);
      $("#start").disabled = false; $("#stop").disabled = true;
      const kind = ev.failed ? "warn" : "success";
      toast(`Fertig — ${ev.succeeded} ok${ev.failed ? `, ${ev.failed} Fehler` : ""}${ev.skipped ? `, ${ev.skipped} übersprungen` : ""}`, kind, 6000);
      EVT.close(); EVT = null;
    }
    else if (ev.type === "error") { setStatus("Fehler: " + ev.message); toast(ev.message, "error"); }
  };
  EVT.onerror = () => { setStatus("Verbindung unterbrochen."); toast("Verbindung unterbrochen", "error"); $("#start").disabled = false; $("#stop").disabled = true; };
}

function addResult(runId, filename) {
  const gallery = $("#gallery");
  const empty = gallery.querySelector(".empty");
  if (empty) empty.remove();
  const url = api(`/api/run/${runId}/image/${encodeURIComponent(filename)}?token=${encodeURIComponent(store.token)}`);
  const a = document.createElement("a");
  a.href = url;
  a.addEventListener("click", (e) => { e.preventDefault(); openLightbox(url); });
  const img = document.createElement("img");
  img.src = url; img.loading = "lazy";
  a.appendChild(img);
  gallery.appendChild(a);
}

async function stopRun() {
  if (!CURRENT_RUN) return;
  await fetch(api(`/api/run/${CURRENT_RUN}/cancel`), { method: "POST", headers: authHeaders() });
  setStatus("gestoppt.");
  toast("Lauf gestoppt", "warn");
}

function setStatus(t) { $("#status").textContent = t; }
function updateBudget(b) { $("#budget").textContent = `Budget: $${(b.estimated_spend_usd || 0).toFixed(2)}`; }

// --- boot ----------------------------------------------------------------
async function enterApp() {
  await loadConfig();
  $("#login").hidden = true;
  $("#app").hidden = false;
  $("#master-prompt").value = CONFIG.default_master_prompt || "";
  if (!document.querySelector(".agent")) addAgent();
  updateBudget(CONFIG.budget || {});
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
  // lightbox close: button, backdrop click, Esc
  $("#lightbox-close").addEventListener("click", closeLightbox);
  $("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox") closeLightbox(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLightbox(); });
  $("#reset-master").addEventListener("click", () => $("#master-prompt").value = CONFIG.default_master_prompt || "");
  $("#clear-master").addEventListener("click", () => $("#master-prompt").value = "");
  $("#add-agent").addEventListener("click", () => addAgent());
  $("#start").addEventListener("click", startRun);
  $("#stop").addEventListener("click", stopRun);
  setupDropzone();
}

document.addEventListener("DOMContentLoaded", async () => {
  wire();
  // auto-resume if a valid token is already stored
  if (store.token) {
    try { await enterApp(); } catch { /* show login */ }
  }
});
