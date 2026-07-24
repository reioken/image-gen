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
  let lastLogo = null;      // last uploaded logo data-URL
  let uid = 1;
  const nid = () => "L" + (uid++);

  const FONTS = ["Outfit Variable", "Arial", "Georgia", "Times New Roman", "Courier New", "Impact"];

  // --- persistence (per run) ---------------------------------------------
  const KEY = () => "pib_editor_" + (CURRENT_RUN || "run");
  function saveState() {
    try {
      localStorage.setItem(KEY(), JSON.stringify({ template, imageText, imageMeta, lastLogo }));
    } catch { /* quota */ }
  }
  function loadState() {
    template = { layers: [] }; imageText = {}; imageMeta = {}; lastLogo = null;
    try {
      const s = JSON.parse(localStorage.getItem(KEY()) || "null");
      if (s) { template = s.template || { layers: [] }; imageText = s.imageText || {}; imageMeta = s.imageMeta || {}; lastLogo = s.lastLogo || null; }
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
      const { w, h } = fitSize(natW, natH);
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
    el("ed-lang").addEventListener("click", () => toast("Sprachen & Export kommen in Phase 2/3 🚧", "info"));
    const ob = el("open-editor"); if (ob) ob.addEventListener("click", open);

    // keyboard: Delete removes selection, Esc closes
    document.addEventListener("keydown", (e) => {
      if (el("editor").hidden) return;
      if ((e.key === "Delete" || e.key === "Backspace") && canvas && canvas.getActiveObject() && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); delActive(); }
      if (e.key === "Escape") close();
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
