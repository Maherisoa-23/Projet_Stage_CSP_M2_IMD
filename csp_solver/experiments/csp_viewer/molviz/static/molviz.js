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
  let currentXyzRel = null;     // chemin xyz courant (pour fetch lazy Kekule)
  let showCycles = true;
  let showRadicals = true;
  let showLabels = false;

  // Etat du systeme de modes (defaut / kekule / rbo)
  // - 'default'  : bonds + radicaux tels que renvoyes par /api/mol3d (matching max)
  // - 'kekule'   : bonds + radicaux du i-eme Kekule de la liste enumere
  // - 'rbo'      : vue Ring Bond Order. Bonds = ceux du matching max (mode
  //                'default'), avec en plus un label "CBO=x/y" au centre
  //                de chaque cycle. Si molecule radicalaire, banniere d'erreur.
  let currentMode = "default";

  // Cache de la liste Kekule pour la molecule courante (lazy-loadee)
  // Format : { kekule: [{bond_orders, radicals, n_doubles}, ...], meta: {...} }
  let kekuleList = null;
  let kekuleIndex = 0;
  let kekuleLoading = false;
  // Refs DOM mises a jour quand le mode change ou qu'on navigue
  let kekuleNavRef = null;
  let kekuleStatusRef = null;
  let kekuleChipRef = null;    // bouton chip "Kekule"/"Radicalaires"
  let kekuleLabelRef = null;   // span dans la barre de nav
  let kekuleHelpRef = null;    // icone d'aide "ⓘ" visible si radicaux

  // Cache du payload RBO pour la molecule courante (lazy-loadee)
  // Format : { available, bond_orders, cycles: [{atoms, cbo, cbo_max}], meta }
  let rboData = null;
  let rboLoading = false;
  // Banniere pour les avertissements RBO (radicaux, approximation)
  let rboBannerRef = null;

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
    currentXyzRel = null;
    currentMode = "default";
    kekuleList = null;
    kekuleIndex = 0;
    kekuleLoading = false;
    kekuleNavRef = null;
    kekuleStatusRef = null;
    kekuleChipRef = null;
    kekuleLabelRef = null;
    kekuleHelpRef = null;
    rboData = null;
    rboLoading = false;
    rboBannerRef = null;
    document.removeEventListener("keydown", onKey);
  }

  function onKey(ev) {
    if (ev.key === "Escape") {
      close();
      return;
    }
    // Navigation Kekule au clavier (uniquement quand on est en mode kekule)
    if (currentMode === "kekule" && kekuleList && kekuleList.kekule.length > 0) {
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        gotoKekule(kekuleIndex - 1);
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        gotoKekule(kekuleIndex + 1);
      }
    }
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

    // Barre de modes : chips pour basculer entre les vues
    // (defaut = matching max, kekule = navigation parmi tous les Kekule)
    // Le label de la chip "kekule" est mis a jour dynamiquement par
    // updateModeLabels() apres l'arrivee des donnees /api/mol3d :
    //   - "Kekule"       si la molecule a un matching parfait (n_radicals = 0)
    //   - "Radicalaires" sinon (les configurations enumerees ont des
    //                          electrons radicalaires, donc ce ne sont pas
    //                          des Kekule au sens strict)
    const kekuleChip = el("button", {
      class: "molviz-mode-chip",
      id: "mode-kekule",
      onclick: () => setMode("kekule"),
    }, "Kekule");
    const rboChip = el("button", {
      class: "molviz-mode-chip",
      id: "mode-rbo",
      onclick: () => setMode("rbo"),
      title: "Ring Bond Order : aromaticite locale de chaque cycle",
    }, "RBO");
    const modeBar = el("div", { class: "molviz-modebar" },
      el("button", {
        class: "molviz-mode-chip active",
        id: "mode-default",
        onclick: () => setMode("default"),
        title: "Vue par defaut : un matching maximum",
      }, "Defaut"),
      kekuleChip,
      rboChip,
    );

    // Banniere d'information/avertissement pour le mode RBO (cachee par defaut).
    // S'affiche pour :
    //   - molecule radicalaire (RBO non defini)
    //   - calcul approxime (Kekule plafonnees)
    //   - chargement en cours
    const rboBanner = el("div", { class: "molviz-rbo-banner hidden" });
    rboBannerRef = rboBanner;

    // Barre de navigation Kekule (cachee par defaut, affichee en mode kekule)
    const kekuleLabel = el("span", { class: "molviz-kekule-label" }, "Kekule");
    const kekuleHelp = el("span", {
      class: "molviz-kekule-help hidden",
      title: "Cette molecule n'admet pas de structure de Kekule classique "
           + "(nombre impair de carbones ou topologie qui force des "
           + "electrons non apparies). Les configurations affichees sont "
           + "les matchings maximums : les liaisons doubles sont placees "
           + "de toutes les manieres valides, et les carbones non couverts "
           + "(en violet) sont les sites radicalaires possibles.",
    }, "ⓘ");
    const kekuleStatus = el("span", { class: "molviz-kekule-status" }, "—");
    const kekuleNav = el("div", { class: "molviz-kekule-nav hidden" },
      kekuleLabel,
      kekuleHelp,
      el("button", {
        class: "molviz-kekule-btn",
        title: "Precedent (fleche gauche)",
        onclick: () => gotoKekule(kekuleIndex - 1),
      }, "◀"),
      kekuleStatus,
      el("button", {
        class: "molviz-kekule-btn",
        title: "Suivant (fleche droite)",
        onclick: () => gotoKekule(kekuleIndex + 1),
      }, "▶"),
    );
    kekuleNavRef = kekuleNav;
    kekuleStatusRef = kekuleStatus;
    kekuleChipRef = kekuleChip;
    kekuleLabelRef = kekuleLabel;
    kekuleHelpRef = kekuleHelp;

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
    modal.appendChild(modeBar);
    modal.appendChild(kekuleNav);
    modal.appendChild(rboBanner);
    modal.appendChild(body);
    modal.appendChild(controls);
    overlay.appendChild(modal);
    overlay.addEventListener("click", close);

    document.body.appendChild(overlay);
    document.addEventListener("keydown", onKey);

    return { overlay, body, canvas, loading, headerMeta: header.querySelector("#molviz-meta") };
  }

  /** Retourne l'override (bond_orders, radicals) a appliquer selon le mode
   *  courant. En mode "default" on renvoie null (= utiliser les valeurs
   *  natives de currentData). En mode "kekule" on renvoie le Kekule courant.
   */
  function currentOverride() {
    if (currentMode === "kekule" && kekuleList && kekuleList.kekule.length > 0) {
      const k = kekuleList.kekule[kekuleIndex];
      return { bond_orders: k.bond_orders, radicals: k.radicals };
    }
    return null;
  }

  /** Trace les atomes + bonds + cycles + radicaux dans le viewer 3Dmol. */
  function render() {
    if (!currentViewer || !currentData) return;
    const v = currentViewer;
    const data = currentData;
    const override = currentOverride();

    // Bond orders et radicaux effectifs (selon mode)
    const bondOrders = override
      ? override.bond_orders
      : data.bonds.map(b => b.order);
    const radicalsList = override ? override.radicals : data.radicals;

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
    const radSet = new Set(showRadicals ? radicalsList : []);
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

    // 2bis. Labels CBO au centre des cycles (mode RBO uniquement, si RBO defini)
    //       Format : "CBO/max" (ex : "2.3 / 3"). Affiche aussi si is_exact=false
    //       pour signaler les valeurs approximees.
    if (currentMode === "rbo" && rboData && rboData.available) {
      const isApprox = !rboData.meta.is_exact;
      for (let ci = 0; ci < rboData.cycles.length; ci++) {
        const c = rboData.cycles[ci];
        if (c.cbo == null) continue;
        const verts = c.atoms.map(i => data.atoms[i]);
        const cx = verts.reduce((s, a) => s + a.x, 0) / verts.length;
        const cy = verts.reduce((s, a) => s + a.y, 0) / verts.length;
        const cz = verts.reduce((s, a) => s + a.z, 0) / verts.length;
        const txt = `${c.cbo.toFixed(2)} / ${c.cbo_max}`;
        v.addLabel(txt, {
          position: { x: cx, y: cy, z: cz + 0.05 },
          fontColor: isApprox ? "#a16207" : "#1e293b",
          fontSize: 13,
          backgroundColor: "white",
          backgroundOpacity: 0.92,
          borderThickness: 1,
          borderColor: isApprox ? "#a16207" : "#1e293b",
          inFront: true,
        });
      }
    }

    // 3. Bonds : single = 1 cylindre central, double = 2 cylindres paralleles
    //    L'ordre vient de bondOrders (qui depend du mode courant).
    for (let i = 0; i < data.bonds.length; i++) {
      const bnd = data.bonds[i];
      const order = bondOrders[i];
      const a = data.atoms[bnd.a];
      const b = data.atoms[bnd.b];
      if (order === 2) {
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
    updateKekuleStatus();
    updateRboBanner();
  }

  /** Met a jour le compteur "i / N" et l'etat des boutons prev/next. */
  function updateKekuleStatus() {
    if (!kekuleStatusRef) return;
    if (!kekuleList) {
      kekuleStatusRef.textContent = kekuleLoading ? "chargement…" : "—";
      return;
    }
    const total = kekuleList.kekule.length;
    if (total === 0) {
      kekuleStatusRef.textContent = "aucun";
      return;
    }
    const suffix = kekuleList.meta.has_more
      ? `${total}+`
      : `${total}`;
    kekuleStatusRef.textContent = `${kekuleIndex + 1} / ${suffix}`;
  }

  /** Active/desactive l'affichage de la barre de navigation Kekule. */
  function setKekuleNavVisible(visible) {
    if (!kekuleNavRef) return;
    if (visible) {
      kekuleNavRef.classList.remove("hidden");
    } else {
      kekuleNavRef.classList.add("hidden");
    }
  }

  /** Met a jour les labels "Kekule" / "Radicalaires" partout dans l'UI.
   *
   *  Appele apres l'arrivee des donnees /api/mol3d, quand on sait si la
   *  molecule admet un matching parfait ou non.
   *
   *  - n_radicals == 0 : la molecule a (au moins) une structure de Kekule
   *                       classique. Label = "Kekule".
   *  - n_radicals  > 0 : aucune Kekule classique possible. Les configurations
   *                       enumerees ont toutes le meme nombre de radicaux.
   *                       Label = "Radicalaires", icone d'aide visible.
   */
  function updateModeLabels(nRadicals) {
    const isKekule = (nRadicals === 0);
    const label = isKekule ? "Kekule" : "Radicalaires";
    if (kekuleChipRef) {
      kekuleChipRef.textContent = label;
      kekuleChipRef.title = isKekule
        ? "Naviguer parmi toutes les structures de Kekule de la molecule"
        : "Naviguer parmi les configurations radicalaires (la molecule "
          + "n'admet pas de structure de Kekule classique)";
    }
    if (kekuleLabelRef) {
      kekuleLabelRef.textContent = label;
    }
    if (kekuleHelpRef) {
      kekuleHelpRef.classList.toggle("hidden", isKekule);
    }
  }

  /** Met a jour l'apparence des chips de mode (lequel est "active"). */
  function updateModeChips() {
    const chips = document.querySelectorAll(".molviz-mode-chip");
    chips.forEach(chip => {
      const isActive = chip.id === `mode-${currentMode}`;
      chip.classList.toggle("active", isActive);
    });
  }

  /** Met a jour le contenu et la visibilite de la banniere RBO selon l'etat. */
  function updateRboBanner() {
    if (!rboBannerRef) return;
    // Cacher si on n'est pas en mode rbo
    if (currentMode !== "rbo") {
      rboBannerRef.classList.add("hidden");
      rboBannerRef.textContent = "";
      return;
    }
    if (rboLoading) {
      rboBannerRef.classList.remove("hidden");
      rboBannerRef.className = "molviz-rbo-banner info";
      rboBannerRef.textContent = "Calcul du RBO en cours…";
      return;
    }
    if (!rboData) {
      rboBannerRef.classList.add("hidden");
      return;
    }
    if (!rboData.available) {
      rboBannerRef.classList.remove("hidden");
      rboBannerRef.className = "molviz-rbo-banner warn";
      rboBannerRef.textContent =
        rboData.meta.reason
          ? `RBO non defini : ${rboData.meta.reason}.`
          : "RBO non defini pour cette molecule.";
      return;
    }
    if (!rboData.meta.is_exact) {
      rboBannerRef.classList.remove("hidden");
      rboBannerRef.className = "molviz-rbo-banner warn";
      rboBannerRef.textContent =
        `RBO approxime : enumeration plafonnee a ${rboData.meta.n_kekule} Kekule `
        + `(la molecule en a davantage). Les valeurs sont indicatives.`;
      return;
    }
    // RBO exact disponible : on cache la banniere
    rboBannerRef.classList.add("hidden");
    rboBannerRef.textContent = "";
  }

  /** Charge le payload RBO via /api/rbo (lazy). */
  async function loadRbo() {
    if (rboData || rboLoading || !currentXyzRel) return;
    rboLoading = true;
    updateRboBanner();
    try {
      const url = `/api/rbo?path=${encodeURIComponent(currentXyzRel)}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const payload = await r.json();
      if (payload.error) throw new Error(payload.error);
      rboData = payload;
    } catch (e) {
      rboData = {
        available: false,
        cycles: [],
        bond_orders: [],
        meta: { reason: `erreur de calcul (${e.message})`, is_exact: true,
                n_kekule: 0, n_radicals: 0 },
      };
      console.error("Echec chargement RBO :", e);
    } finally {
      rboLoading = false;
    }
    if (currentMode === "rbo") {
      rerender();
    }
  }

  /** Charge la liste des Kekule via /api/kekule_list (lazy). */
  async function loadKekuleList() {
    if (kekuleList || kekuleLoading || !currentXyzRel) return;
    kekuleLoading = true;
    updateKekuleStatus();
    try {
      const url = `/api/kekule_list?path=${encodeURIComponent(currentXyzRel)}&max=200`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const payload = await r.json();
      if (payload.error) throw new Error(payload.error);
      kekuleList = payload;
      kekuleIndex = 0;
    } catch (e) {
      kekuleList = { kekule: [], meta: { returned: 0, is_exact: true, has_more: false } };
      console.error("Echec chargement Kekule :", e);
    } finally {
      kekuleLoading = false;
    }
    // Si on est encore en mode kekule au retour de la requete, on re-render
    if (currentMode === "kekule") {
      rerender();
    } else {
      updateKekuleStatus();
    }
  }

  /** Bascule le mode courant. Si on passe en kekule/rbo pour la 1ere fois,
   *  declenche le chargement lazy.
   */
  function setMode(mode) {
    if (mode === currentMode) return;
    currentMode = mode;
    updateModeChips();
    setKekuleNavVisible(mode === "kekule");
    if (mode === "kekule" && !kekuleList && !kekuleLoading) {
      // Affiche "chargement…" tout de suite puis fetch
      updateKekuleStatus();
      loadKekuleList();
      return; // loadKekuleList rerender quand fini
    }
    if (mode === "rbo" && !rboData && !rboLoading) {
      updateRboBanner();
      loadRbo();
      return; // loadRbo rerender quand fini
    }
    rerender();
  }

  /** Navigue dans la liste des Kekule. Index borne et cyclique. */
  function gotoKekule(newIndex) {
    if (!kekuleList || kekuleList.kekule.length === 0) return;
    const n = kekuleList.kekule.length;
    // Comportement cyclique : <- depuis 0 va a n-1, -> depuis n-1 va a 0.
    kekuleIndex = ((newIndex % n) + n) % n;
    rerender();
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
    currentXyzRel = xyzRel;
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
    // Renomme la chip et le label de nav selon la nature de la molecule
    // (Kekule vs Radicalaires). A faire AVANT que l'utilisateur puisse
    // cliquer sur la chip.
    updateModeLabels(data.meta.n_radicals || 0);
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
