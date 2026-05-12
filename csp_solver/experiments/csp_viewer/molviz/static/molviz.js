/**
 * Visualisation 3D d'une molecule avec 3Dmol.js.
 *
 * API publique : window.MolViz.open(info)
 *
 *   Variante "solution" (par defaut, retro-compatible) :
 *     info = {
 *       sol_dir: "...",   // chemin relatif du sol_dir
 *       sol_idx: 1234,
 *       sizes:   "5_7_6",
 *       verdict: "plan" | "non_plan" | ...,
 *     }
 *   -> charge <sol_dir>/md_validation/md_final_opt.xyz et titre "sol_X · sizes Y".
 *
 *   Variante "generique" (override explicite, pour ex. molecule d'origine) :
 *     info = {
 *       xyz_path: "...",  // chemin relatif d'un .xyz (resolu cote serveur)
 *       title:    "Original",
 *       subtitle: "0-10-19-…",
 *     }
 *   -> charge directement xyz_path et utilise title + subtitle dans l'en-tete.
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
  // Couleurs (palette sans rouge ni vert pour la coloration des cycles)
  const COLORS = {
    atom: 0x222222,
    bondSingle: 0x444444,
    bondDouble: 0x444444,
    radical: 0x9333ea,        // violet
    cycle5: 0xfed7aa,         // orange peche
    cycle6: 0xcbd5e1,         // gris-bleu
    cycle7: 0xa5b4fc,         // indigo clair
    cycleAnomaly: 0xfde047,   // jaune vif (taille != 5/6/7)
  };

  function cycleColor(size) {
    if (size === 5) return COLORS.cycle5;
    if (size === 6) return COLORS.cycle6;
    if (size === 7) return COLORS.cycle7;
    return COLORS.cycleAnomaly;
  }

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

  /** Construit le titre d'en-tete a partir des infos d'ouverture. */
  function buildHeaderTitle(info) {
    // Variante explicite : title (+ subtitle) fournis directement
    if (info.title) {
      return info.subtitle
        ? `${info.title}  ·  ${info.subtitle}`
        : info.title;
    }
    // Variante "solution" (retro-compatible)
    if (info.sol_idx !== undefined) {
      return `sol_${info.sol_idx}  ·  sizes ${info.sizes}`;
    }
    return "Molécule";
  }

  /** Construit le modal et son contenu. Retourne {body, header, controls}. */
  function buildModal(info) {
    const overlay = el("div", { class: "molviz-overlay" });
    const modal = el("div", { class: "molviz-modal", onclick: (e) => e.stopPropagation() });

    const header = el("div", { class: "molviz-header" },
      el("div", { class: "title" }, buildHeaderTitle(info)),
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
      el("div", { class: "legend", id: "molviz-legend" },
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#fed7aa" }), "5"),
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#cbd5e1" }), "6"),
        el("span", { class: "item" },
          el("span", { class: "swatch", style: "background:#a5b4fc" }), "7"),
        el("span", { class: "item legend-anomaly hidden" },
          el("span", { class: "swatch", style: "background:#fde047" }), "anomalie"),
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

    // 1. Cycles colores : on dessine pour chaque cycle un polygone "retreci"
    //    vers son centroide (facteur 0.70) avec opacite pleine. Ca evite que
    //    deux cycles fusionnes ne se chevauchent et que leurs couleurs ne se
    //    melangent vers du gris (probleme typique des polycycles partages).
    //    On dessine du plus grand au plus petit : si un residu de chevauchement
    //    subsiste, le petit cycle reste visible par-dessus le grand.
    if (showCycles) {
      const SHRINK = 0.70;
      const sortedCycles = [...data.cycles].sort((a, b) => b.size - a.size);
      for (const c of sortedCycles) {
        const color = cycleColor(c.size);
        const verts = c.atoms.map(i => data.atoms[i]);
        // Centroide
        const cx = verts.reduce((s, a) => s + a.x, 0) / verts.length;
        const cy = verts.reduce((s, a) => s + a.y, 0) / verts.length;
        const cz = verts.reduce((s, a) => s + a.z, 0) / verts.length;
        // Sommets retrecis vers le centroide
        const shrunk = verts.map(a => ({
          x: cx + SHRINK * (a.x - cx),
          y: cy + SHRINK * (a.y - cy),
          z: cz + SHRINK * (a.z - cz),
        }));
        // Determine le winding du cycle dans le plan XY (formule du lacet).
        // L'ordre des sommets renvoye par _order_cycle_vertices cote Python
        // n'est pas garanti d'etre anti-horaire vu de +Z : on inverse si CW.
        // Comme ca le triangle a sa normale +Z face a la camera -> eclaire.
        let signedArea = 0;
        for (let k = 0; k < shrunk.length; k++) {
          const a = shrunk[k];
          const b = shrunk[(k + 1) % shrunk.length];
          signedArea += a.x * b.y - b.x * a.y;
        }
        if (signedArea < 0) {
          shrunk.reverse();
        }
        // Triangulation en eventail depuis le centroide, une seule face.
        const center = { x: cx, y: cy, z: cz };
        for (let k = 0; k < shrunk.length; k++) {
          const a = shrunk[k];
          const b = shrunk[(k + 1) % shrunk.length];
          v.addCustom({
            vertexArr: [center, a, b],
            normalArr: [
              { x: 0, y: 0, z: 1 },
              { x: 0, y: 0, z: 1 },
              { x: 0, y: 0, z: 1 },
            ],
            faceArr: [0, 1, 2],
            color: color,
            opacity: 1.0,
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

  /** Charge un .xyz et ouvre le modal. Accepte deux formes d'info :
   *   - {xyz_path, title, subtitle}   pour ouvrir un xyz arbitraire
   *   - {sol_dir, sol_idx, sizes, verdict}  pour les solutions (retro-compat)
   */
  async function open(info) {
    if (currentRoot) close();

    const refs = buildModal(info);
    currentRoot = refs.overlay;

    // Resolution du chemin : explicite > deduit depuis sol_dir
    let xyzRel;
    if (info.xyz_path) {
      xyzRel = info.xyz_path;
    } else if (info.sol_dir) {
      // Path = <sol_dir>/md_validation/md_final_opt.xyz
      xyzRel = `${info.sol_dir}/md_validation/md_final_opt.xyz`;
    } else {
      refs.loading.innerHTML = `<div style="color:#dc2626">Erreur : aucun chemin de molécule fourni.</div>`;
      return;
    }
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
    const nAnomaly = data.meta.n_anomaly_cycles || 0;
    refs.headerMeta.innerHTML = `
      <span>${data.meta.n_carbons} C</span>
      <span>${data.meta.n_bonds} liaisons (${data.meta.n_doubles} doubles)</span>
      ${data.meta.n_radicals > 0
        ? `<span style="color:#9333ea">${data.meta.n_radicals} radical${data.meta.n_radicals>1?'aux':''}</span>`
        : `<span style="color:#16a34a">perfect matching</span>`}
      ${nAnomaly > 0
        ? `<span style="color:#a16207" title="Cycles de taille != 5/6/7 detectes (bond parasite ou geometrie cassee)">${nAnomaly} cycle${nAnomaly>1?'s':''} anormal${nAnomaly>1?'aux':''}</span>`
        : ""}
    `;

    // Affiche le swatch "anomalie" dans la legende uniquement si necessaire
    const anomalyItem = document.querySelector(".legend-anomaly");
    if (anomalyItem) {
      anomalyItem.classList.toggle("hidden", nAnomaly === 0);
    }

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
