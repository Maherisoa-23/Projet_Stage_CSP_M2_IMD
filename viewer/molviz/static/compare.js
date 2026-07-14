/**
 * Comparaison cote a cote de deux solutions (2 viewers 3Dmol synchronises).
 *
 * API publique : window.MolCompare
 *   open(solA, solB)  -> ouvre le modal de comparaison.
 *                        sol = { xyz_path, title, subtitle? }
 *   close()           -> ferme le modal
 *   pin(sol)          -> memorise une molecule "epinglee" (flux en 2 temps
 *                        depuis le viewer molviz : epingler A, ouvrir B,
 *                        cliquer "Comparer")
 *   getPinned()       -> sol epinglee ou null
 *   clearPin()        -> oublie la molecule epinglee
 *
 * Choix d'architecture : module autonome, INDEPENDANT du singleton molviz.js
 * (dont l'etat de modes Kekule/RBO/Clar est monolithique). La comparaison
 * n'affiche que la vue "defaut" (cycles colores + atomes + liaisons du
 * matching maximum) : le mini-renderer ci-dessous est une copie volontairement
 * minimale de molviz.js::render() pour ce mode-la — duplication assumee pour
 * ne pas refactorer un module eprouve a 4 jours de la fin du stage.
 *
 * Synchronisation des cameras : setViewChangeCallback + setView croisés
 * (APIs publiques 3Dmol), avec garde anti-recursion et case a cocher pour
 * desactiver. Les deux solutions d'un meme squelette partagent le meme
 * repere de reconstruction, donc partager la vue absolue est pertinent.
 *
 * Le modal et ses 2 viewers sont construits UNE fois puis reutilises
 * (overlay cache/affiche) : evite de fuiter un contexte WebGL a chaque
 * ouverture (3Dmol n'expose pas de dispose()).
 */

(function () {
  "use strict";

  // Palette identique a molviz.js (vue defaut)
  const COLORS = {
    atom: 0x222222,
    bond: 0x444444,
    radical: 0x9333ea,
    cycle5: 0xfed7aa,
    cycle6: 0xcbd5e1,
    cycle7: 0xa5b4fc,
    cycleAnomaly: 0xfde047,
  };

  function cycleColor(size) {
    if (size === 5) return COLORS.cycle5;
    if (size === 6) return COLORS.cycle6;
    if (size === 7) return COLORS.cycle7;
    return COLORS.cycleAnomaly;
  }

  let overlay = null;          // racine DOM (construite une fois, reutilisee)
  let viewers = [null, null];  // 2 instances 3Dmol GLViewer
  let panels = [null, null];   // refs DOM {title, meta, warn, loading}
  let pinned = null;           // molecule epinglee (flux molviz)
  let syncEnabled = true;
  let applyingView = false;    // garde anti-recursion du sync

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") e.className = v;
        else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v);
      }
    }
    for (const c of children) {
      if (c == null) continue;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return e;
  }

  // ---- Rendu minimal (vue "defaut" de molviz : cycles + atomes + bonds) ----
  function renderMolecule(v, data) {
    v.removeAllModels();
    v.removeAllShapes();
    v.removeAllLabels();

    // Cycles colores (polygones retrecis vers le centroide, cf. molviz.js)
    const SHRINK = 0.70;
    const sortedCycles = [...data.cycles].sort((a, b) => b.size - a.size);
    for (const c of sortedCycles) {
      const color = cycleColor(c.size);
      const verts = c.atoms.map(i => data.atoms[i]);
      const cx = verts.reduce((s, a) => s + a.x, 0) / verts.length;
      const cy = verts.reduce((s, a) => s + a.y, 0) / verts.length;
      const cz = verts.reduce((s, a) => s + a.z, 0) / verts.length;
      const shrunk = verts.map(a => ({
        x: cx + SHRINK * (a.x - cx),
        y: cy + SHRINK * (a.y - cy),
        z: cz + SHRINK * (a.z - cz),
      }));
      let signedArea = 0;
      for (let k = 0; k < shrunk.length; k++) {
        const a = shrunk[k];
        const b = shrunk[(k + 1) % shrunk.length];
        signedArea += a.x * b.y - b.x * a.y;
      }
      if (signedArea < 0) shrunk.reverse();
      const center = { x: cx, y: cy, z: cz };
      const vertexArr = [center, ...shrunk];
      const normalArr = vertexArr.map(() => ({ x: 0, y: 0, z: 1 }));
      const faceArr = [];
      for (let k = 0; k < shrunk.length; k++) {
        faceArr.push(0, k + 1, ((k + 1) % shrunk.length) + 1);
      }
      v.addCustom({ vertexArr, normalArr, faceArr, color, opacity: 1.0 });
    }

    // Atomes (radicaux en violet, comme molviz)
    const radSet = new Set(data.radicals || []);
    for (let i = 0; i < data.atoms.length; i++) {
      const a = data.atoms[i];
      const isRadical = radSet.has(i);
      v.addSphere({
        center: { x: a.x, y: a.y, z: a.z },
        radius: isRadical ? 0.32 : 0.22,
        color: isRadical ? COLORS.radical : COLORS.atom,
        opacity: 1.0,
      });
    }

    // Liaisons (ordres du matching maximum renvoye par /api/mol3d)
    for (const bnd of data.bonds) {
      const a = data.atoms[bnd.a];
      const b = data.atoms[bnd.b];
      if (bnd.order === 2) {
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        let px = -dy / len, py = dx / len, pz = 0;
        if (Math.abs(dz) / len > 0.8) { px = 1; py = 0; pz = 0; }
        const off = 0.10;
        v.addCylinder({
          start: { x: a.x + px * off, y: a.y + py * off, z: a.z + pz * off },
          end:   { x: b.x + px * off, y: b.y + py * off, z: b.z + pz * off },
          radius: 0.06, color: COLORS.bond,
        });
        v.addCylinder({
          start: { x: a.x - px * off, y: a.y - py * off, z: a.z - pz * off },
          end:   { x: b.x - px * off, y: b.y - py * off, z: b.z - pz * off },
          radius: 0.06, color: COLORS.bond,
        });
      } else {
        v.addCylinder({
          start: { x: a.x, y: a.y, z: a.z },
          end:   { x: b.x, y: b.y, z: b.z },
          radius: 0.07, color: COLORS.bond,
        });
      }
    }

    v.zoomTo();
    v.render();
  }

  // ---- Construction du modal (une seule fois) ----
  function buildOverlay() {
    const panelDefs = [0, 1].map((i) => {
      const title = el("div", { class: "molcmp-title" }, "—");
      const meta = el("div", { class: "molcmp-meta" }, "");
      const warn = el("div", { class: "molcmp-warn hidden" },
        "⚠ Geometrie non relaxee (mode skip)");
      const loading = el("div", { class: "molcmp-loading" }, "Chargement…");
      const canvas = el("div", { class: "molcmp-canvas", id: `molcmp-canvas-${i}` });
      const wrap = el("div", { class: "molcmp-canvas-wrap" }, canvas, loading);
      const panel = el("div", { class: "molcmp-panel" },
        el("div", { class: "molcmp-panel-header" }, title, meta, warn),
        wrap,
      );
      panels[i] = { title, meta, warn, loading, canvas, panel };
      return panel;
    });

    const syncCheck = el("input", { type: "checkbox", id: "molcmp-sync" });
    syncCheck.checked = true;
    syncCheck.addEventListener("change", () => { syncEnabled = syncCheck.checked; });

    const header = el("div", { class: "molcmp-header" },
      el("div", { class: "molcmp-header-title" }, "Comparaison de solutions"),
      el("label", { class: "molcmp-sync-label",
                    title: "Tourner/zoomer une molecule applique le meme point de vue a l'autre" },
        syncCheck, " Synchroniser la rotation"),
      el("button", { class: "molcmp-close", title: "Fermer (Esc)", onclick: close }, "✕"),
    );

    const body = el("div", { class: "molcmp-body" }, panelDefs[0], panelDefs[1]);
    const modal = el("div", { class: "molcmp-modal", onclick: (e) => e.stopPropagation() },
      header, body);
    overlay = el("div", { class: "molcmp-overlay hidden", onclick: close }, modal);
    document.body.appendChild(overlay);

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && overlay && !overlay.classList.contains("hidden")) {
        close();
      }
    });
  }

  function ensureViewers() {
    if (viewers[0]) return true;
    if (typeof $3Dmol === "undefined") return false;
    for (const i of [0, 1]) {
      viewers[i] = $3Dmol.createViewer(`molcmp-canvas-${i}`, { backgroundColor: "white" });
    }
    // Sync croise des cameras. applyingView casse la recursion
    // (setView declenche le callback du viewer cible).
    viewers[0].setViewChangeCallback((view) => {
      if (!syncEnabled || applyingView) return;
      applyingView = true;
      try { viewers[1].setView(view); } finally { applyingView = false; }
    });
    viewers[1].setViewChangeCallback((view) => {
      if (!syncEnabled || applyingView) return;
      applyingView = true;
      try { viewers[0].setView(view); } finally { applyingView = false; }
    });
    return true;
  }

  async function loadPanel(i, sol) {
    const p = panels[i];
    p.title.textContent = sol.title || "Molecule";
    p.meta.textContent = sol.subtitle || "";
    p.warn.classList.add("hidden");
    p.loading.style.display = "";
    p.loading.textContent = "Chargement…";
    p.loading.style.color = "";

    let data;
    try {
      const r = await fetch(`/api/mol3d?path=${encodeURIComponent(sol.xyz_path)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      data = await r.json();
      if (data.error) throw new Error(data.error);
    } catch (e) {
      p.loading.textContent = `Erreur : ${e.message}`;
      p.loading.style.color = "#dc2626";
      return;
    }

    const m = data.meta || {};
    const extra = [];
    if (m.n_carbons) extra.push(`${m.n_carbons} C`);
    if (m.n_doubles != null) extra.push(`${m.n_doubles} doubles`);
    if (m.n_radicals > 0) extra.push(`${m.n_radicals} radical${m.n_radicals > 1 ? "aux" : ""}`);
    p.meta.textContent = [sol.subtitle, extra.join(" · ")].filter(Boolean).join("  ·  ");
    p.warn.classList.toggle("hidden", !m.unclosed_ring);

    p.loading.style.display = "none";
    renderMolecule(viewers[i], data);
  }

  // ---- API publique ----
  async function open(solA, solB) {
    if (!overlay) buildOverlay();
    overlay.classList.remove("hidden");
    if (!ensureViewers()) {
      panels[0].loading.textContent = "3Dmol.js non charge.";
      panels[1].loading.textContent = "3Dmol.js non charge.";
      return;
    }
    // Chargement parallele des deux panneaux
    await Promise.all([loadPanel(0, solA), loadPanel(1, solB)]);
  }

  function close() {
    if (overlay) overlay.classList.add("hidden");
  }

  function pin(sol) { pinned = sol; }
  function getPinned() { return pinned; }
  function clearPin() { pinned = null; }

  window.MolCompare = { open, close, pin, getPinned, clearPin };
})();
