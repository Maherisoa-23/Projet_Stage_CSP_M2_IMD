/**
 * Visualisation 3D d'une molecule avec 3Dmol.js.
 *
 * API publique : window.MolViz.open(solInfo)
 *   solInfo = {
 *     sol_dir: "...",   // chemin relatif du sol_dir
 *     sol_idx: 1234,
 *     sizes:   "5_7_6",
 *     verdict: "plan" | "non_plan" | ...,
 *   }
 *
 * Le fichier 3Dmol-min.js doit etre charge AVANT ce script.
 *
 * Rendu :
 *   - Carbones uniquement (les H sont droppes cote serveur)
 *   - Liaisons single = un cylindre, double = deux cylindres paralleles
 *   - Cycles colores par taille (5=orange clair, 6=gris, 7=bleu clair)
 *   - Radicaux = sphere violette + asterisque
 *
 * Source de donnees : GET /api/mol3d?path=<sol_dir>/md_validation/md_final_opt.xyz
 */

(function () {
  // Couleurs
  const COLORS = {
    atom: 0x222222,
    bondSingle: 0x444444,
    bondDouble: 0x444444,
    radical: 0x9333ea,    // violet
    cycle5: 0xffe4b5,
    cycle6: 0xe5e7eb,
    cycle7: 0xbfdbfe,
  };

  // Etat actuel du modal
  let currentViewer = null;
  let currentRoot = null;
  let currentData = null;
  let showCycles = true;
  let showRadicals = true;
  let showLabels = false;

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") e.className = v;
        else if (k === "style") e.style.cssText = v;
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

  function close() {
    if (currentViewer) {
      try { currentViewer.removeAllModels(); } catch (_) {}
      try { currentViewer.removeAllShapes(); } catch (_) {}
      try { currentViewer.removeAllLabels(); } catch (_) {}
      currentViewer = null;
    }
    if (currentRoot) {
      currentRoot.remove();
      currentRoot = null;
    }
    currentData = null;
    document.removeEventListener("keydown", onKey);
  }

  function onKey(ev) {
    if (ev.key === "Escape") close();
  }

  /** Construit le modal et son contenu. Retourne {body, header, controls}. */
  function buildModal(solInfo) {
    const overlay = el("div", { class: "molviz-overlay" });
    const modal = el("div", { class: "molviz-modal", onclick: (e) => e.stopPropagation() });

    const header = el("div", { class: "molviz-header" },
      el("div", { class: "title" }, `sol_${solInfo.sol_idx}  ·  sizes ${solInfo.sizes}`),
      el("div", { class: "meta", id: "molviz-meta" }, "—"),
      el("button", { class: "molviz-close", title: "Fermer (Esc)", onclick: close }, "✕"),
    );

    const body = el("div", { class: "molviz-body" });
    const canvas = el("div", { class: "molviz-canvas", id: "molviz-canvas" });
    const loading = el("div", { class: "molviz-loading" },
      el("div", null, "Chargement de la molecule…"),
    );
    body.appendChild(canvas);
    body.appendChild(loading);

    const controls = el("div", { class: "molviz-controls" },
      el("label", null,
        el("input", { type: "checkbox", id: "ck-cycles", checked: "checked",
                       onchange: (e) => { showCycles = e.target.checked; rerender(); } }),
        "Cycles colores",
      ),
      el("label", null,
        el("input", { type: "checkbox", id: "ck-radicals", checked: "checked",
                       onchange: (e) => { showRadicals = e.target.checked; rerender(); } }),
        "Radicaux",
      ),
      el("label", null,
        el("input", { type: "checkbox", id: "ck-labels",
                       onchange: (e) => { showLabels = e.target.checked; rerender(); } }),
        "Indices atomes",
      ),
      el("div", { class: "legend" },
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#ffe4b5" }), "5"),
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#e5e7eb" }), "6"),
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#bfdbfe" }), "7"),
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#9333ea" }), "radical"),
      ),
    );

    modal.appendChild(header);
    modal.appendChild(body);
    modal.appendChild(controls);
    overlay.appendChild(modal);
    overlay.addEventListener("click", close);

    document.body.appendChild(overlay);
    document.addEventListener("keydown", onKey);

    return { overlay, body, canvas, loading, headerMeta: header.querySelector("#molviz-meta") };
  }

  /** Trace les atomes + bonds + cycles + radicaux dans le viewer 3Dmol. */
  function render() {
    if (!currentViewer || !currentData) return;
    const v = currentViewer;
    const data = currentData;

    v.removeAllModels();
    v.removeAllShapes();
    v.removeAllLabels();

    // 1. Cycles colores : on dessine un polygone rempli a plat sur les
    //    atomes du cycle, transparent pour ne pas masquer les bonds.
    if (showCycles) {
      for (const c of data.cycles) {
        const color = c.size === 5 ? COLORS.cycle5
                    : c.size === 7 ? COLORS.cycle7
                    : COLORS.cycle6;
        const verts = c.atoms.map(i => data.atoms[i]);
        // 3Dmol n'a pas de polygon natif, on triangule : centroid + paires
        const cx = verts.reduce((s, a) => s + a.x, 0) / verts.length;
        const cy = verts.reduce((s, a) => s + a.y, 0) / verts.length;
        const cz = verts.reduce((s, a) => s + a.z, 0) / verts.length;
        for (let k = 0; k < verts.length; k++) {
          const a = verts[k];
          const b = verts[(k + 1) % verts.length];
          v.addCustom({
            vertexArr: [
              { x: cx, y: cy, z: cz },
              { x: a.x, y: a.y, z: a.z },
              { x: b.x, y: b.y, z: b.z },
            ],
            normalArr: [
              { x: 0, y: 0, z: 1 },
              { x: 0, y: 0, z: 1 },
              { x: 0, y: 0, z: 1 },
            ],
            faceArr: [0, 1, 2],
            color: color,
            opacity: 0.45,
          });
        }
      }
    }

    // 2. Atomes : sphere par atome (carbones gris fonce, radicaux violet)
    const radSet = new Set(showRadicals ? data.radicals : []);
    for (let i = 0; i < data.atoms.length; i++) {
      const a = data.atoms[i];
      const isRadical = radSet.has(i);
      v.addSphere({
        center: { x: a.x, y: a.y, z: a.z },
        radius: isRadical ? 0.32 : 0.22,
        color: isRadical ? COLORS.radical : COLORS.atom,
        opacity: 1.0,
      });
      if (isRadical) {
        // Marqueur "*" au-dessus
        v.addLabel("•", {
          position: { x: a.x, y: a.y, z: a.z + 0.5 },
          fontColor: "#9333ea",
          fontSize: 18,
          backgroundColor: "white",
          backgroundOpacity: 0.7,
          borderThickness: 1,
          borderColor: "#9333ea",
          inFront: true,
        });
      }
      if (showLabels) {
        v.addLabel(String(i), {
          position: { x: a.x, y: a.y, z: a.z + 0.25 },
          fontColor: "#374151",
          fontSize: 11,
          backgroundOpacity: 0,
          inFront: true,
        });
      }
    }

    // 3. Bonds : single = 1 cylindre central, double = 2 cylindres paralleles
    for (const bnd of data.bonds) {
      const a = data.atoms[bnd.a];
      const b = data.atoms[bnd.b];
      if (bnd.order === 2) {
        // Decalage perpendiculaire dans le plan moyen
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        // Vecteur perpendiculaire approximatif (dans plan xy)
        const len = Math.sqrt(dx*dx + dy*dy + dz*dz) || 1;
        // perp dans le plan xy : rotate 90deg autour de z
        let px = -dy / len, py = dx / len, pz = 0;
        // Si la liaison est presque verticale (z dominant), prendre un autre perp
        const nz = Math.abs(dz) / len;
        if (nz > 0.8) { px = 1; py = 0; pz = 0; }
        const off = 0.10;
        v.addCylinder({
          start: { x: a.x + px*off, y: a.y + py*off, z: a.z + pz*off },
          end:   { x: b.x + px*off, y: b.y + py*off, z: b.z + pz*off },
          radius: 0.06,
          color: COLORS.bondDouble,
        });
        v.addCylinder({
          start: { x: a.x - px*off, y: a.y - py*off, z: a.z - pz*off },
          end:   { x: b.x - px*off, y: b.y - py*off, z: b.z - pz*off },
          radius: 0.06,
          color: COLORS.bondDouble,
        });
      } else {
        v.addCylinder({
          start: { x: a.x, y: a.y, z: a.z },
          end:   { x: b.x, y: b.y, z: b.z },
          radius: 0.07,
          color: COLORS.bondSingle,
        });
      }
    }

    v.zoomTo();
    v.render();
  }

  function rerender() {
    render();
  }

  /** Charge les donnees pour un sol_dir et ouvre le modal. */
  async function open(solInfo) {
    if (currentRoot) close();

    const refs = buildModal(solInfo);
    currentRoot = refs.overlay;

    // Path = <sol_dir>/md_validation/md_final_opt.xyz
    // (fallback source.xyz si verdict est xtb_failed mais on n'arrivera pas la
    // dans la vue actuelle ; le bouton 3D n'apparait pas pour ces sols)
    const xyzRel = `${solInfo.sol_dir}/md_validation/md_final_opt.xyz`;
    let data;
    try {
      const r = await fetch(`/api/mol3d?path=${encodeURIComponent(xyzRel)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      data = await r.json();
    } catch (e) {
      refs.loading.innerHTML = `<div style="color:#dc2626">Erreur : ${e.message}</div>`;
      return;
    }

    if (data.error) {
      refs.loading.innerHTML = `<div style="color:#dc2626">Erreur : ${data.error}</div>`;
      return;
    }

    currentData = data;
    refs.headerMeta.innerHTML = `
      <span>${data.meta.n_carbons} C</span>
      <span>${data.meta.n_bonds} liaisons (${data.meta.n_doubles} doubles)</span>
      ${data.meta.n_radicals > 0
        ? `<span style="color:#9333ea">${data.meta.n_radicals} radical${data.meta.n_radicals>1?'aux':''}</span>`
        : `<span style="color:#16a34a">perfect matching</span>`}
    `;

    // Initialise le viewer 3Dmol APRES insertion DOM (sinon dimensions 0)
    if (typeof $3Dmol === "undefined") {
      refs.loading.innerHTML = `<div style="color:#dc2626">3Dmol.js non chargé.</div>`;
      return;
    }
    currentViewer = $3Dmol.createViewer("molviz-canvas", {
      backgroundColor: "white",
    });
    refs.loading.style.display = "none";
    render();
  }

  // Expose
  window.MolViz = { open, close };
})();
