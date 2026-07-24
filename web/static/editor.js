"use strict";
/* Design editor (Phase 1): Fabric.js overlay on top of generated images.
   - Layers: container (rounded rect), text, logo.
   - Move/resize/rotate via Fabric handles; opacity, colour, radius, shadow, align.
   - The layout (positions + styles) is ONE template shared by every image in the
     series; text content is stored PER IMAGE. Per-image metadata (produktart /
     name / colour) is captured for the later pack export.
   Relies on globals from app.js: $, api, store, toast, RESULTS_LOG, CURRENT_RUN. */
(function () {
  const F = window.fabric;
  if (!F) { console.error("fabric.js not loaded"); return; }

  const el = (id) => document.getElementById(id);
  let canvas = null;
  let imgs = [];            // [{file, provider, model, promptId}]
  let curIdx = 0;
  let curFile = null;
  let template = { layers: [] };   // shared layer specs
  let imageText = {};       // file -> { layerId: text }
  let imageMeta = {};       // file -> { art, name, color }
  let translations = {};    // file -> { layerId: { de, en, fr, it, es, pl } }
  let lastLogo = null;      // last uploaded logo data-URL
  let curNat = { w: 0, h: 0 };  // native size of the current image
  let uid = 1;

  const LANGS = [
    ["de", "Deutsch", "deutsch"], ["en", "English", "englisch"],
    ["fr", "Français", "franzoesisch"], ["it", "Italiano", "italienisch"],
    ["es", "Español", "spanisch"], ["pl", "Polski", "polnisch"],
  ];
  const nid = () => "L" + (uid++);

  const FONTS = ["Outfit Variable", "Arial", "Georgia", "Times New Roman", "Courier New", "Impact"];

  // --- persistence (per run) ---------------------------------------------
  const KEY = () => "pib_editor_" + (CURRENT_RUN || "run");
  function saveState() {
    try {
      localStorage.setItem(KEY(), JSON.stringify({ template, imageText, imageMeta, translations, lastLogo }));
    } catch { /* quota */ }
  }
  function loadState() {
    template = { layers: [] }; imageText = {}; imageMeta = {}; translations = {}; lastLogo = null;
    try {
      const s = JSON.parse(localStorage.getItem(KEY()) || "null");
      if (s) { template = s.template || { layers: [] }; imageText = s.imageText || {}; imageMeta = s.imageMeta || {}; translations = s.translations || {}; lastLogo = s.lastLogo || null; }
    } catch { /* ignore */ }
    let mx = 0; (template.layers || []).forEach(l => { const n = parseInt(String(l.id).slice(1), 10); if (n > mx) mx = n; });
    uid = mx + 1;
  }

  function fullUrl(file) {
    return api(`/api/run/${CURRENT_RUN}/image/${encodeURIComponent(file)}?token=${encodeURIComponent(store.token)}`);
  }

  // --- open / close -------------------------------------------------------
  function open() {
    imgs = (typeof RESULTS_LOG !== "undefined" ? RESULTS_LOG : []).slice();
    if (!imgs.length) { toast("Erst Bilder generieren", "warn"); return; }
    loadState();
    el("editor").hidden = false;
    requestAnimationFrame(() => el("editor").classList.add("show"));
    if (!canvas) initCanvas();
    buildFilmstrip();
    loadImage(0);
  }
  function close() {
    saveState();
    el("editor").classList.remove("show");
    setTimeout(() => { el("editor").hidden = true; }, 200);
  }

  // --- canvas -------------------------------------------------------------
  function initCanvas() {
    canvas = new F.Canvas("edit-canvas", {
      backgroundColor: "#0b0d14", preserveObjectStacking: true, selection: true,
    });
    canvas.on("selection:created", () => showProps(canvas.getActiveObject()));
    canvas.on("selection:updated", () => showProps(canvas.getActiveObject()));
    canvas.on("selection:cleared", () => showProps(null));
    canvas.on("object:modified", (e) => { if (e.target) syncFromObject(e.target); saveState(); });
    canvas.on("text:changed", (e) => { if (e.target && e.target.layerType === "text") { imageText[curFile] = imageText[curFile] || {}; imageText[curFile][e.target.layerId] = e.target.text; saveState(); } });
  }

  function fitSize(natW, natH) {
    const wrap = el("editor").querySelector(".ed-canvas-wrap");
    const maxW = Math.max(320, wrap.clientWidth - 24);
    const maxH = Math.max(320, wrap.clientHeight - 24);
    const s = Math.min(maxW / natW, maxH / natH, 1.2);
    return { w: Math.round(natW * s), h: Math.round(natH * s) };
  }

  function loadImage(idx) {
    curIdx = idx; curFile = imgs[idx].file;
    highlightFilmstrip();
    loadMeta();
    F.Image.fromURL(fullUrl(curFile), (img) => {
      const natW = img.width, natH = img.height;
      curNat = { w: natW, h: natH };
      // Pin the editing canvas size for the whole series so the shared layout
      // coordinates stay consistent across images. Native export scales up by
      // natW / baseW later.
      if (!template.baseW) { const f = fitSize(natW, natH); template.baseW = f.w; template.baseH = f.h; }
      const w = template.baseW, h = template.baseH;
      canvas.setDimensions({ width: w, height: h });
      img.set({ selectable: false, evented: false, left: 0, top: 0,
                scaleX: w / natW, scaleY: h / natH, originX: "left", originY: "top" });
      canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
      renderLayers();
    }, { crossOrigin: "anonymous" });
  }

  // build fabric objects from template specs for the current image
  function renderLayers() {
    canvas.getObjects().slice().forEach(o => canvas.remove(o));
    for (const spec of template.layers) {
      const o = objFromSpec(spec);
      if (o) canvas.add(o);
    }
    canvas.renderAll();
  }

  function applyCommon(o, spec) {
    o.set({ left: spec.left, top: spec.top, angle: spec.angle || 0, opacity: spec.opacity ?? 1,
            scaleX: spec.scaleX ?? 1, scaleY: spec.scaleY ?? 1 });
    o.layerId = spec.id; o.layerType = spec.type;
    if (spec.shadow) o.set("shadow", new F.Shadow({ color: "rgba(0,0,0,.45)", blur: 18, offsetX: 0, offsetY: 6 }));
    else o.set("shadow", null);
  }

  function objFromSpec(spec) {
    if (spec.type === "container") {
      const r = new F.Rect({ width: spec.width, height: spec.height, rx: spec.rx || 0, ry: spec.rx || 0,
        fill: spec.fill || "rgba(10,12,20,0.55)", stroke: spec.stroke || null, strokeWidth: spec.strokeWidth || 0,
        originX: "left", originY: "top" });
      applyCommon(r, spec); return r;
    }
    if (spec.type === "text") {
      const txt = (imageText[curFile] && imageText[curFile][spec.id] != null) ? imageText[curFile][spec.id] : (spec.text || "Text");
      const t = new F.Textbox(txt, { width: spec.width || 360, fontSize: spec.fontSize || 44,
        fill: spec.fill || "#ffffff", fontFamily: spec.fontFamily || "Outfit Variable",
        textAlign: spec.textAlign || "left", fontWeight: spec.fontWeight || "700",
        originX: "left", originY: "top", editable: true });
      applyCommon(t, spec); return t;
    }
    if (spec.type === "logo" && spec.src) {
      // created async; add a placeholder-free image
      F.Image.fromURL(spec.src, (im) => {
        im.set({ originX: "left", originY: "top" });
        applyCommon(im, spec);
        canvas.add(im); canvas.renderAll();
      });
      return null;
    }
    return null;
  }

  // write an object's geometry back into its shared template spec
  function syncFromObject(o) {
    const spec = template.layers.find(l => l.id === o.layerId);
    if (!spec) return;
    spec.left = Math.round(o.left); spec.top = Math.round(o.top);
    spec.angle = o.angle || 0; spec.opacity = o.opacity ?? 1;
    spec.scaleX = o.scaleX ?? 1; spec.scaleY = o.scaleY ?? 1;
    if (spec.type === "container") { spec.width = o.width; spec.height = o.height; }
    if (spec.type === "text") { spec.width = o.width; spec.fontSize = o.fontSize; }
  }

  // --- add layers ---------------------------------------------------------
  function centerPos(w, h) { return { left: Math.round((canvas.width - w) / 2), top: Math.round((canvas.height - h) / 2) }; }

  function addContainer() {
    const w = Math.round(canvas.width * 0.7), h = Math.round(canvas.height * 0.22);
    const p = centerPos(w, h);
    const spec = { id: nid(), type: "container", left: p.left, top: Math.round(canvas.height * 0.7),
      width: w, height: h, rx: 18, fill: "rgba(10,12,20,0.55)", opacity: 1, shadow: true, scaleX: 1, scaleY: 1, angle: 0 };
    template.layers.push(spec); renderLayers(); selectLayer(spec.id); saveState();
  }
  function addText() {
    const w = Math.round(canvas.width * 0.66);
    const spec = { id: nid(), type: "text", left: Math.round(canvas.width * 0.08), top: Math.round(canvas.height * 0.74),
      width: w, fontSize: Math.round(canvas.height * 0.05), fill: "#ffffff", fontFamily: "Outfit Variable",
      textAlign: "left", fontWeight: "700", text: "Dein Text", opacity: 1, shadow: true, scaleX: 1, scaleY: 1, angle: 0 };
    template.layers.push(spec);
    imageText[curFile] = imageText[curFile] || {}; imageText[curFile][spec.id] = spec.text;
    renderLayers(); selectLayer(spec.id); saveState();
  }
  function addLogo(dataUrl) {
    lastLogo = dataUrl;
    const spec = { id: nid(), type: "logo", src: dataUrl, left: 24, top: 24, opacity: 1, shadow: false, scaleX: 1, scaleY: 1, angle: 0 };
    // scale so the logo is ~18% of canvas width
    F.Image.fromURL(dataUrl, (im) => {
      const target = canvas.width * 0.18; const s = target / im.width;
      spec.scaleX = s; spec.scaleY = s;
      template.layers.push(spec); renderLayers(); selectLayer(spec.id); saveState();
    });
  }

  function selectLayer(id) {
    const o = canvas.getObjects().find(x => x.layerId === id);
    if (o) { canvas.setActiveObject(o); canvas.renderAll(); showProps(o); }
  }

  // --- properties panel ---------------------------------------------------
  function showProps(o) {
    const panel = el("ed-prop-panel"), empty = el("ed-prop-empty");
    if (!o) { panel.hidden = true; empty.hidden = false; return; }
    empty.hidden = true; panel.hidden = false;
    const spec = template.layers.find(l => l.id === o.layerId) || {};
    let html = `<div class="ed-group-h">${o.layerType === "container" ? "Container" : o.layerType === "text" ? "Text" : "Logo"}</div>`;
    if (o.layerType === "text") {
      const cur = (imageText[curFile] && imageText[curFile][o.layerId] != null) ? imageText[curFile][o.layerId] : (spec.text || "");
      html += `<label class="small">Text (dieses Bild)<textarea id="pp-text" rows="2">${escapeHtml(cur)}</textarea></label>
        <div class="pp-row"><label class="small">Größe<input id="pp-size" type="number" min="8" max="400" value="${Math.round(o.fontSize)}"></label>
        <label class="small">Farbe<input id="pp-fill" type="color" value="${toHex(o.fill)}"></label></div>
        <div class="pp-row"><label class="small">Schrift<select id="pp-font">${FONTS.map(f => `<option ${f === o.fontFamily ? "selected" : ""}>${f}</option>`).join("")}</select></label>
        <label class="small">Ausrichtung<select id="pp-align"><option ${o.textAlign === "left" ? "selected" : ""}>left</option><option ${o.textAlign === "center" ? "selected" : ""}>center</option><option ${o.textAlign === "right" ? "selected" : ""}>right</option></select></label></div>
        <label class="small"><input id="pp-bold" type="checkbox" ${String(o.fontWeight) === "700" || o.fontWeight === "bold" ? "checked" : ""}> Fett</label>`;
    } else if (o.layerType === "container") {
      html += `<div class="pp-row"><label class="small">Füllfarbe<input id="pp-fill" type="color" value="${toHex(o.fill)}"></label>
        <label class="small">Deckkraft Füllung<input id="pp-fillop" type="range" min="0" max="100" value="${Math.round(alphaOf(o.fill) * 100)}"></label></div>
        <label class="small">Ecken-Radius<input id="pp-radius" type="range" min="0" max="80" value="${o.rx || 0}"></label>
        <div class="pp-row"><label class="small">Rahmenfarbe<input id="pp-stroke" type="color" value="${toHex(o.stroke || "#8b9cf5")}"></label>
        <label class="small">Rahmen<input id="pp-strokew" type="range" min="0" max="12" value="${o.strokeWidth || 0}"></label></div>`;
    }
    html += `<label class="small">Deckkraft<input id="pp-op" type="range" min="10" max="100" value="${Math.round((o.opacity ?? 1) * 100)}"></label>
      <label class="small"><input id="pp-shadow" type="checkbox" ${o.shadow ? "checked" : ""}> Schatten</label>`;
    panel.innerHTML = html;
    wireProps(o, spec);
  }

  function wireProps(o, spec) {
    const on = (id, ev, fn) => { const n = el(id); if (n) n.addEventListener(ev, fn); };
    on("pp-text", "input", (e) => { o.set("text", e.target.value); imageText[curFile] = imageText[curFile] || {}; imageText[curFile][o.layerId] = e.target.value; canvas.renderAll(); saveState(); });
    on("pp-size", "input", (e) => { o.set("fontSize", +e.target.value); spec.fontSize = +e.target.value; canvas.renderAll(); saveState(); });
    on("pp-fill", "input", (e) => { if (o.layerType === "container") { o.set("fill", withAlpha(e.target.value, alphaOf(o.fill))); spec.fill = o.fill; } else { o.set("fill", e.target.value); spec.fill = e.target.value; } canvas.renderAll(); saveState(); });
    on("pp-fillop", "input", (e) => { o.set("fill", withAlpha(toHex(o.fill), +e.target.value / 100)); spec.fill = o.fill; canvas.renderAll(); saveState(); });
    on("pp-radius", "input", (e) => { o.set({ rx: +e.target.value, ry: +e.target.value }); spec.rx = +e.target.value; canvas.renderAll(); saveState(); });
    on("pp-stroke", "input", (e) => { o.set("stroke", e.target.value); spec.stroke = e.target.value; canvas.renderAll(); saveState(); });
    on("pp-strokew", "input", (e) => { o.set("strokeWidth", +e.target.value); spec.strokeWidth = +e.target.value; canvas.renderAll(); saveState(); });
    on("pp-font", "change", (e) => { o.set("fontFamily", e.target.value); spec.fontFamily = e.target.value; canvas.renderAll(); saveState(); });
    on("pp-align", "change", (e) => { o.set("textAlign", e.target.value); spec.textAlign = e.target.value; canvas.renderAll(); saveState(); });
    on("pp-bold", "change", (e) => { const w = e.target.checked ? "700" : "400"; o.set("fontWeight", w); spec.fontWeight = w; canvas.renderAll(); saveState(); });
    on("pp-op", "input", (e) => { o.set("opacity", +e.target.value / 100); spec.opacity = +e.target.value / 100; canvas.renderAll(); saveState(); });
    on("pp-shadow", "change", (e) => { o.set("shadow", e.target.checked ? new F.Shadow({ color: "rgba(0,0,0,.45)", blur: 18, offsetY: 6 }) : null); spec.shadow = e.target.checked; canvas.renderAll(); saveState(); });
  }

  // --- layer ops ----------------------------------------------------------
  function activeSpec() { const o = canvas.getActiveObject(); return o ? template.layers.find(l => l.id === o.layerId) : null; }
  function delActive() { const o = canvas.getActiveObject(); if (!o) return; template.layers = template.layers.filter(l => l.id !== o.layerId); canvas.remove(o); showProps(null); saveState(); }
  function dupActive() {
    const s = activeSpec(); if (!s) return;
    const c = JSON.parse(JSON.stringify(s)); c.id = nid(); c.left += 20; c.top += 20;
    template.layers.push(c);
    if (s.type === "text" && imageText[curFile]) { imageText[curFile][c.id] = imageText[curFile][s.id] || s.text; }
    renderLayers(); selectLayer(c.id); saveState();
  }
  function reorder(dir) {
    const o = canvas.getActiveObject(); if (!o) return;
    if (dir > 0) canvas.bringToFront(o); else canvas.sendToBack(o);
    // reflect z-order in the spec array
    const idx = template.layers.findIndex(l => l.id === o.layerId);
    if (idx >= 0) { const [sp] = template.layers.splice(idx, 1); dir > 0 ? template.layers.push(sp) : template.layers.unshift(sp); }
    canvas.renderAll(); saveState();
  }

  // --- filmstrip + metadata ----------------------------------------------
  function buildFilmstrip() {
    const strip = el("ed-filmstrip"); strip.innerHTML = "";
    imgs.forEach((im, i) => {
      const b = document.createElement("button");
      b.className = "ed-frame"; b.title = im.file;
      const img = document.createElement("img");
      img.src = fullUrl(im.file) + "&thumb=1"; img.loading = "lazy";
      b.appendChild(img);
      b.addEventListener("click", () => { saveState(); loadImage(i); });
      strip.appendChild(b);
    });
  }
  function highlightFilmstrip() {
    [...el("ed-filmstrip").children].forEach((c, i) => c.classList.toggle("on", i === curIdx));
  }
  function loadMeta() {
    const m = imageMeta[curFile] || {};
    el("ed-meta-art").value = m.art || ""; el("ed-meta-name").value = m.name || ""; el("ed-meta-color").value = m.color || "";
  }
  function saveMeta() {
    imageMeta[curFile] = { art: el("ed-meta-art").value.trim(), name: el("ed-meta-name").value.trim(), color: el("ed-meta-color").value.trim() };
    saveState();
  }

  // --- translation + pack export (Phase 2/3) ------------------------------
  function textLayers() { return template.layers.filter(l => l.type === "text"); }
  function gatherItems() {
    const out = [];
    for (const im of imgs) for (const t of textLayers()) {
      const src = (imageText[im.file] && imageText[im.file][t.id] != null) ? imageText[im.file][t.id] : (t.text || "");
      out.push({ file: im.file, layerId: t.id, source: src });
    }
    return out;
  }

  function startExport() {
    saveMeta();
    const hasContainer = template.layers.some(l => l.type === "container");
    const hasText = textLayers().length > 0;
    if (!hasContainer || !hasText) { toast("Erst einen Container UND einen Text hinzufügen", "warn"); return; }
    // Warn (non-blocking) about images that still miss text or metadata.
    const miss = [];
    for (const im of imgs) {
      const m = imageMeta[im.file] || {};
      if (!m.art || !m.name || !m.color) { miss.push(im.file); continue; }
      for (const t of textLayers()) { const v = imageText[im.file] && imageText[im.file][t.id]; if (!v || !v.trim()) { miss.push(im.file); break; } }
    }
    if (miss.length) toast(`${miss.length} Bild(er) ohne Text/Metadaten — fehlende Felder ausfüllen für saubere Ordner`, "warn", 6000);
    openTrModal();
  }

  function openTrModal() {
    el("ed-tr").hidden = false;
    requestAnimationFrame(() => el("ed-tr").classList.add("show"));
    renderTrTable();
    const need = gatherItems().some(it => !(translations[it.file] && translations[it.file][it.layerId] && translations[it.file][it.layerId].en));
    if (need && (typeof CONFIG === "undefined" || CONFIG.can_translate !== false)) autoTranslate();
  }
  function closeTrModal() {
    readTrInputs();
    el("ed-tr").classList.remove("show");
    setTimeout(() => { el("ed-tr").hidden = true; }, 200);
  }

  function labelForLayer(id) { const n = textLayers().findIndex(t => t.id === id); return "Text " + (n + 1); }
  function renderTrTable() {
    const body = el("ed-tr-body"); body.innerHTML = "";
    imgs.forEach((im, i) => {
      const m = imageMeta[im.file] || {};
      const card = document.createElement("div"); card.className = "ed-tr-img";
      const pathBits = [m.art, m.name, m.color].filter(Boolean).map(escapeHtml).join(" / ") || "<em>Metadaten fehlen</em>";
      card.innerHTML = `<div class="ed-tr-h"><span class="ed-tr-n">#${i + 1}</span> <span class="muted small">${pathBits}</span></div>`;
      for (const t of textLayers()) {
        const tr = (translations[im.file] && translations[im.file][t.id]) || {};
        const de = (imageText[im.file] && imageText[im.file][t.id] != null) ? imageText[im.file][t.id] : (t.text || "");
        const block = document.createElement("div"); block.className = "ed-tr-block";
        block.innerHTML = `<div class="ed-tr-lname small muted">${labelForLayer(t.id)}</div>` +
          LANGS.map(([code, label]) => {
            const val = code === "de" ? de : (tr[code] || "");
            return `<label class="ed-tr-row small"><span class="ed-tr-lang">${label}</span>` +
              `<input data-file="${escapeHtml(im.file)}" data-layer="${t.id}" data-lang="${code}" value="${escapeHtml(val)}"></label>`;
          }).join("");
        card.appendChild(block);
      }
      body.appendChild(card);
    });
  }

  function readTrInputs() {
    el("ed-tr-body").querySelectorAll("input[data-lang]").forEach(inp => {
      const f = inp.getAttribute("data-file"), lid = inp.getAttribute("data-layer"), lang = inp.getAttribute("data-lang");
      if (lang === "de") { imageText[f] = imageText[f] || {}; imageText[f][lid] = inp.value; }
      translations[f] = translations[f] || {}; translations[f][lid] = translations[f][lid] || {};
      translations[f][lid][lang] = inp.value;
    });
    saveState();
  }

  async function autoTranslate() {
    const status = el("ed-tr-status"); const items = gatherItems();
    if (!items.length) return;
    status.textContent = "Übersetze …";
    try {
      const r = await fetch(api("/api/translate"), {
        method: "POST", headers: { ...authHeaders(), "content-type": "application/json" },
        body: JSON.stringify({ texts: items.map(i => i.source), source: "de", targets: ["en", "fr", "it", "es", "pl"] }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const tl = (await r.json()).translations || {};
      items.forEach((it, i) => {
        translations[it.file] = translations[it.file] || {};
        translations[it.file][it.layerId] = { de: it.source,
          en: (tl.en || [])[i] || "", fr: (tl.fr || [])[i] || "", it: (tl.it || [])[i] || "",
          es: (tl.es || [])[i] || "", pl: (tl.pl || [])[i] || "" };
      });
      saveState(); renderTrTable();
      status.textContent = "Übersetzt — alles editierbar.";
    } catch (e) {
      status.textContent = "Auto-Übersetzung nicht verfügbar — Felder manuell ausfüllen.";
    }
  }

  // render one image × language × logo-state to a native-resolution PNG data URL
  function loadFabricImage(url) {
    return new Promise((res, rej) => F.Image.fromURL(url, im => im ? res(im) : rej(new Error("img")), { crossOrigin: "anonymous" }));
  }
  function pickText(file, spec, code) {
    const tr = translations[file] && translations[file][spec.id];
    if (tr && tr[code] != null && tr[code] !== "") return tr[code];
    if (imageText[file] && imageText[file][spec.id] != null) return imageText[file][spec.id];
    return spec.text || "";
  }
  async function composite(file, code, withLogo) {
    const baseW = template.baseW, baseH = template.baseH;
    const sc = new F.StaticCanvas(null, { width: baseW, height: baseH, backgroundColor: "#000" });
    const bg = await loadFabricImage(fullUrl(file));
    const nW = bg.width, nH = bg.height;
    bg.set({ left: 0, top: 0, scaleX: baseW / nW, scaleY: baseH / nH, originX: "left", originY: "top" });
    await new Promise(r => sc.setBackgroundImage(bg, r));
    for (const spec of template.layers) {
      if (spec.type === "logo") {
        if (!withLogo || !spec.src) continue;
        const im = await loadFabricImage(spec.src);
        im.set({ originX: "left", originY: "top" }); applyCommon(im, spec); sc.add(im);
      } else if (spec.type === "container") {
        const r = new F.Rect({ width: spec.width, height: spec.height, rx: spec.rx || 0, ry: spec.rx || 0,
          fill: spec.fill || "rgba(10,12,20,0.55)", stroke: spec.stroke || null, strokeWidth: spec.strokeWidth || 0,
          originX: "left", originY: "top" });
        applyCommon(r, spec); sc.add(r);
      } else if (spec.type === "text") {
        const t = new F.Textbox(pickText(file, spec, code), { width: spec.width || 360, fontSize: spec.fontSize || 44,
          fill: spec.fill || "#ffffff", fontFamily: spec.fontFamily || "Outfit Variable",
          textAlign: spec.textAlign || "left", fontWeight: spec.fontWeight || "700", originX: "left", originY: "top" });
        applyCommon(t, spec); sc.add(t);
      }
    }
    sc.renderAll();
    const url = sc.toDataURL({ format: "png", multiplier: nW / baseW });
    sc.dispose();
    return url;
  }

  function slug(s) { return String(s || "").trim().replace(/[\\/:*?"<>|]+/g, "-").replace(/\s+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "unbenannt"; }
  function baseName(f) { return /\.(png|jpg|jpeg|webp)$/i.test(f) ? f : f + ".png"; }
  function downloadBlob(blob, name) {
    const u = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 4000);
  }

  async function buildPack() {
    if (typeof JSZip === "undefined") { toast("JSZip nicht geladen", "err"); return; }
    readTrInputs();
    const status = el("ed-tr-status"); const btn = el("ed-tr-export");
    btn.disabled = true;
    try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch { /* ignore */ }
    const zip = new JSZip();
    const total = imgs.length * 2 * LANGS.length; let n = 0;
    try {
      for (const im of imgs) {
        const m = imageMeta[im.file] || {};
        const dir = `${slug(m.art || "produktart")}/${slug(m.name || "name")}/${slug(m.color || "farbe")}`;
        for (const withLogo of [true, false]) {
          const lf = withLogo ? "mit-logo" : "ohne-logo";
          for (const [code, , folder] of LANGS) {
            const url = await composite(im.file, code, withLogo);
            zip.file(`${dir}/${lf}/${folder}/${baseName(im.file)}`, url.split(",")[1], { base64: true });
            n++; status.textContent = `Rendere ${n}/${total} …`;
          }
        }
      }
      status.textContent = "Packe ZIP …";
      const blob = await zip.generateAsync({ type: "blob", compression: "STORE" });
      downloadBlob(blob, `pack_${(CURRENT_RUN || "run")}.zip`);
      status.textContent = `Fertig — ${total} Bilder im Pack.`;
      toast("Pack erstellt & heruntergeladen ✓", "success");
    } catch (e) {
      console.error(e); status.textContent = "Fehler beim Rendern: " + (e && e.message || e);
      toast("Export fehlgeschlagen", "err");
    } finally { btn.disabled = false; }
  }

  // --- helpers ------------------------------------------------------------
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function toHex(c) {
    if (!c) return "#ffffff";
    if (c[0] === "#") return c.length === 4 ? "#" + [...c.slice(1)].map(x => x + x).join("") : c.slice(0, 7);
    const m = String(c).match(/rgba?\(([^)]+)\)/); if (!m) return "#ffffff";
    const [r, g, b] = m[1].split(",").map(x => parseInt(x, 10));
    return "#" + [r, g, b].map(x => (x || 0).toString(16).padStart(2, "0")).join("");
  }
  function alphaOf(c) { const m = String(c).match(/rgba\(([^)]+)\)/); if (!m) return 1; const p = m[1].split(","); return p.length > 3 ? parseFloat(p[3]) : 1; }
  function withAlpha(hex, a) { const h = toHex(hex); const r = parseInt(h.slice(1, 3), 16), g = parseInt(h.slice(3, 5), 16), b = parseInt(h.slice(5, 7), 16); return `rgba(${r},${g},${b},${a})`; }

  // --- wire ---------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    el("ed-close").addEventListener("click", close);
    el("ed-add-container").addEventListener("click", addContainer);
    el("ed-add-text").addEventListener("click", addText);
    el("ed-logo-input").addEventListener("change", (e) => {
      const f = e.target.files[0]; if (!f) return;
      const rd = new FileReader(); rd.onload = () => addLogo(rd.result); rd.readAsDataURL(f); e.target.value = "";
    });
    el("ed-del").addEventListener("click", delActive);
    el("ed-dup").addEventListener("click", dupActive);
    el("ed-front").addEventListener("click", () => reorder(1));
    el("ed-back").addEventListener("click", () => reorder(-1));
    ["ed-meta-art", "ed-meta-name", "ed-meta-color"].forEach(id => el(id).addEventListener("input", saveMeta));
    el("ed-lang").addEventListener("click", startExport);
    el("ed-tr-close").addEventListener("click", closeTrModal);
    el("ed-tr-cancel").addEventListener("click", closeTrModal);
    el("ed-tr-retranslate").addEventListener("click", () => { readTrInputs(); autoTranslate(); });
    el("ed-tr-export").addEventListener("click", buildPack);
    const ob = el("open-editor"); if (ob) ob.addEventListener("click", open);

    // keyboard: Delete removes selection, Esc closes
    document.addEventListener("keydown", (e) => {
      if (el("editor").hidden) return;
      if ((e.key === "Delete" || e.key === "Backspace") && canvas && canvas.getActiveObject() && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); delActive(); }
      if (e.key === "Escape") { if (!el("ed-tr").hidden) closeTrModal(); else close(); }
    });

    // reveal the editor button whenever results exist
    const gallery = el("gallery");
    if (gallery) {
      const sync = () => { const has = !!gallery.querySelector(".result-item"); const b = el("open-editor"); if (b) b.hidden = !has; };
      new MutationObserver(sync).observe(gallery, { childList: true, subtree: true });
      sync();
    }
  });

  window.PIB_Editor = { open };
})();
