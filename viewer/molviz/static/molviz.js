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

  // Cache de la liste Clar pour la molecule courante (lazy-loadee)
  // Format : { clar: [{sextets, bond_orders, radicals, n_sextets}, ...], meta: {clar_number, ...} }
  let clarList = null;
  let clarIndex = 0;
  let clarLoading = false;
  let clarNavRef = null;
  let clarStatusRef = null;
  let clarChipRef = null;     // bouton chip "Clar"
  let clarLabelRef = null;    // span "Clar N=..." dans la barre de nav

  // Panneau du graphe dual (SVG 2D, verite topologique de la solution).
  let dualPanelRef = null;

  // Lien de telechargement du .xyz de la molecule courante (header du modal).
  let exportLinkRef = null;

  // Bouton epingler/comparer du header (flux en 2 temps via compare.js :
  // epingler la molecule A, ouvrir la B, cliquer "Comparer"). Refs mises a
  // jour par updateCompareBtn(). currentTitle sert de libelle d'epinglage.
  let compareBtnRef = null;
  let currentTitle = null;

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
    clarList = null;
    clarIndex = 0;
    clarLoading = false;
    clarNavRef = null;
    clarStatusRef = null;
    clarChipRef = null;
    clarLabelRef = null;
    dualPanelRef = null;
    exportLinkRef = null;
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
    // Navigation Clar au clavier (uniquement quand on est en mode clar)
    if (currentMode === "clar" && clarList && clarList.clar.length > 0) {
      if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        gotoClar(clarIndex - 1);
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        gotoClar(clarIndex + 1);
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

    const exportLink = el("a", {
      class: "molviz-export",
      id: "molviz-export-link",
      title: "Telecharger le fichier .xyz de cette molecule",
      download: "",
      href: "#",
    }, "⬇ .xyz");
    exportLinkRef = exportLink;

    const headerTitle = buildHeaderTitle(info);
    currentTitle = headerTitle;

    // Bouton epingler/comparer : present seulement si compare.js est charge
    // sur la page (window.MolCompare). el() ignore les enfants null, donc
    // le header reste valide sans lui.
    let compareBtn = null;
    if (window.MolCompare) {
      compareBtn = el("button", {
        class: "molviz-compare-btn",
        id: "molviz-compare-btn",
        onclick: onCompareClick,
      }, "📌 Comparer…");
    }
    compareBtnRef = compareBtn;

    const header = el("div", { class: "molviz-header" },
      el("div", { class: "title" }, headerTitle),
      el("div", { class: "meta", id: "molviz-meta" }, "—"),
      compareBtn,
      exportLink,
      el("button", { class: "molviz-close", title: "Fermer (Esc)", onclick: close }, "✕"),
    );

    const body = el("div", { class: "molviz-body" });
    // Zone 3D (flex:1) : wrapper qui contient le canvas 3Dmol + le loader.
    const canvasWrap = el("div", { class: "molviz-canvas-wrap" });
    const canvas = el("div", { class: "molviz-canvas", id: "molviz-canvas" });
    const loading = el("div", { class: "molviz-loading" },
      el("div", null, "Chargement de la molecule…"),
    );
    canvasWrap.appendChild(canvas);
    canvasWrap.appendChild(loading);
    body.appendChild(canvasWrap);

    // Panneau "graphe dual" (vue topologique 2D, verite de la solution CSP).
    // Rendu en SVG, independant de la geometrie 3D. Sert a confirmer les
    // vraies tailles de cycles (5/6/7) meme quand le rendu 3D skip est deforme.
    const dualPanel = el("div", { class: "molviz-dual", id: "molviz-dual" },
      el("div", { class: "molviz-dual-title" }, "Graphe dual (solution)"),
      el("div", { class: "molviz-dual-svg", id: "molviz-dual-svg" }, "—"),
      el("div", { class: "molviz-dual-legend" },
        el("span", { class: "molviz-dual-leg-item" },
          el("span", { class: "molviz-dual-swatch", style: "background:#fed7aa" }), "5"),
        el("span", { class: "molviz-dual-leg-item" },
          el("span", { class: "molviz-dual-swatch", style: "background:#cbd5e1" }), "6"),
        el("span", { class: "molviz-dual-leg-item" },
          el("span", { class: "molviz-dual-swatch", style: "background:#a5b4fc" }), "7"),
      ),
    );
    body.appendChild(dualPanel);
    dualPanelRef = dualPanel;

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
    const clarChip = el("button", {
      class: "molviz-mode-chip",
      id: "mode-clar",
      onclick: () => setMode("clar"),
      title: "Couvertures de Clar : navigation parmi les structures maximisant le nombre de sextets aromatiques",
    }, "Clar");
    clarChipRef = clarChip;
    const modeBar = el("div", { class: "molviz-modebar" },
      el("button", {
        class: "molviz-mode-chip active",
        id: "mode-default",
        onclick: () => setMode("default"),
        title: "Vue par defaut : un matching maximum",
      }, "Defaut"),
      kekuleChip,
      rboChip,
      clarChip,
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

    // Barre de navigation Clar (cachee par defaut, affichee en mode clar)
    // Label dynamique "Clar N=X" mis a jour par updateClarStatus() apres
    // l'arrivee des donnees /api/clar_list.
    const clarLabel = el("span", { class: "molviz-kekule-label" }, "Clar");
    const clarStatus = el("span", { class: "molviz-kekule-status" }, "—");
    const clarNav = el("div", { class: "molviz-kekule-nav hidden" },
      clarLabel,
      el("button", {
        class: "molviz-kekule-btn",
        title: "Couverture precedente (fleche gauche)",
        onclick: () => gotoClar(clarIndex - 1),
      }, "◀"),
      clarStatus,
      el("button", {
        class: "molviz-kekule-btn",
        title: "Couverture suivante (fleche droite)",
        onclick: () => gotoClar(clarIndex + 1),
      }, "▶"),
    );
    clarNavRef = clarNav;
    clarStatusRef = clarStatus;
    clarLabelRef = clarLabel;

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
    modal.appendChild(clarNav);
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
   *  natives de currentData). En mode "kekule" / "clar" on renvoie le
   *  Kekule / la couverture Clar courante.
   */
  function currentOverride() {
    if (currentMode === "kekule" && kekuleList && kekuleList.kekule.length > 0) {
      const k = kekuleList.kekule[kekuleIndex];
      return { bond_orders: k.bond_orders, radicals: k.radicals };
    }
    if (currentMode === "clar" && clarList && clarList.clar.length > 0) {
      const c = clarList.clar[clarIndex];
      return { bond_orders: c.bond_orders, radicals: c.radicals };
    }
    return null;
  }

  /** Indices des cycles porteurs d'un rond de Clar pour le mode courant
   *  (ou null sinon). Utilise par render() pour dessiner les ronds.
   */
  function currentSextets() {
    if (currentMode === "clar" && clarList && clarList.clar.length > 0) {
      return clarList.clar[clarIndex].sextets;
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
        // Triangulation en eventail depuis le centroide, BATCHEE en UN seul
        // addCustom (un seul mesh three.js par cycle au lieu d'un par triangle).
        // Reduit fortement le nombre d'objets WebGL -> rendu plus rapide.
        const center = { x: cx, y: cy, z: cz };
        const vertexArr = [center, ...shrunk];
        const normalArr = vertexArr.map(() => ({ x: 0, y: 0, z: 1 }));
        const faceArr = [];
        for (let k = 0; k < shrunk.length; k++) {
          // triangle (centre=0, sommet k+1, sommet suivant)
          const a = k + 1;
          const b = ((k + 1) % shrunk.length) + 1;
          faceArr.push(0, a, b);
        }
        v.addCustom({ vertexArr, normalArr, faceArr, color, opacity: 1.0 });
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

    // 2ter. Ronds de Clar au centre des hexagones porteurs d'un sextet
    //       (mode Clar uniquement). On dessine un anneau (annulus) plat
    //       a 60% du rayon de l'hexagone, en gris fonce, par-dessus le
    //       polygone du cycle.
    const sextets = currentSextets();
    if (sextets && sextets.length > 0) {
      const RING_RAD_FRAC = 0.55;  // rayon exterieur de l'anneau
      const RING_THICKNESS = 0.10; // epaisseur de l'anneau (en A)
      const N_SEG = 32;            // resolution angulaire
      for (const ci of sextets) {
        const cyc = data.cycles[ci];
        if (!cyc) continue;
        const verts = cyc.atoms.map(i => data.atoms[i]);
        const cx = verts.reduce((s, a) => s + a.x, 0) / verts.length;
        const cy = verts.reduce((s, a) => s + a.y, 0) / verts.length;
        const cz = verts.reduce((s, a) => s + a.z, 0) / verts.length;
        // Rayon = distance moyenne du centroide aux sommets
        let rmean = 0;
        for (const a of verts) {
          rmean += Math.sqrt((a.x-cx)**2 + (a.y-cy)**2 + (a.z-cz)**2);
        }
        rmean /= verts.length;
        const rOuter = RING_RAD_FRAC * rmean;
        const rInner = Math.max(0.01, rOuter - RING_THICKNESS);
        // Triangulation de l'anneau : 2 triangles par segment
        for (let k = 0; k < N_SEG; k++) {
          const t0 = (2 * Math.PI * k) / N_SEG;
          const t1 = (2 * Math.PI * (k + 1)) / N_SEG;
          const out0 = { x: cx + rOuter*Math.cos(t0), y: cy + rOuter*Math.sin(t0), z: cz + 0.02 };
          const out1 = { x: cx + rOuter*Math.cos(t1), y: cy + rOuter*Math.sin(t1), z: cz + 0.02 };
          const in0  = { x: cx + rInner*Math.cos(t0), y: cy + rInner*Math.sin(t0), z: cz + 0.02 };
          const in1  = { x: cx + rInner*Math.cos(t1), y: cy + rInner*Math.sin(t1), z: cz + 0.02 };
          v.addCustom({
            vertexArr: [out0, out1, in1, in0],
            normalArr: [
              { x: 0, y: 0, z: 1 }, { x: 0, y: 0, z: 1 },
              { x: 0, y: 0, z: 1 }, { x: 0, y: 0, z: 1 },
            ],
            faceArr: [0, 1, 2, 0, 2, 3],
            color: 0x1e293b,  // gris fonce
            opacity: 1.0,
          });
        }
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
    updateClarStatus();
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

  /** Active/desactive l'affichage de la barre de navigation Clar. */
  function setClarNavVisible(visible) {
    if (!clarNavRef) return;
    if (visible) {
      clarNavRef.classList.remove("hidden");
    } else {
      clarNavRef.classList.add("hidden");
    }
  }

  /** Met a jour "Clar N=X" + compteur "i / N" + libelle de la chip. */
  function updateClarStatus() {
    if (!clarStatusRef) return;
    if (!clarList) {
      clarStatusRef.textContent = clarLoading ? "chargement…" : "—";
      if (clarLabelRef) clarLabelRef.textContent = "Clar";
      return;
    }
    const clarNumber = clarList.meta.clar_number || 0;
    const total = clarList.clar.length;
    if (clarLabelRef) {
      clarLabelRef.textContent = `Clar N=${clarNumber}`;
    }
    if (total === 0) {
      clarStatusRef.textContent = "aucune";
      return;
    }
    const suffix = clarList.meta.has_more ? `${total}+` : `${total}`;
    clarStatusRef.textContent = `${clarIndex + 1} / ${suffix}`;
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

  /** Charge la liste des couvertures de Clar via /api/clar_list (lazy). */
  async function loadClarList() {
    if (clarList || clarLoading || !currentXyzRel) return;
    clarLoading = true;
    updateClarStatus();
    try {
      const url = `/api/clar_list?path=${encodeURIComponent(currentXyzRel)}&max=200`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const payload = await r.json();
      if (payload.error) throw new Error(payload.error);
      clarList = payload;
      clarIndex = 0;
    } catch (e) {
      clarList = { clar: [], meta: { returned: 0, is_exact: true, has_more: false,
                                      clar_number: 0 } };
      console.error("Echec chargement Clar :", e);
    } finally {
      clarLoading = false;
    }
    if (currentMode === "clar") {
      rerender();
    } else {
      updateClarStatus();
    }
  }

  /** Navigue dans la liste des couvertures Clar. Index borne et cyclique. */
  function gotoClar(newIndex) {
    if (!clarList || clarList.clar.length === 0) return;
    const n = clarList.clar.length;
    clarIndex = ((newIndex % n) + n) % n;
    rerender();
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

  /** Bascule le mode courant. Si on passe en kekule/rbo/clar pour la 1ere
   *  fois, declenche le chargement lazy.
   */
  function setMode(mode) {
    if (mode === currentMode) return;
    currentMode = mode;
    updateModeChips();
    setKekuleNavVisible(mode === "kekule");
    setClarNavVisible(mode === "clar");
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
    if (mode === "clar" && !clarList && !clarLoading) {
      updateClarStatus();
      loadClarList();
      return; // loadClarList rerender quand fini
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

  // Couleurs des cycles pour le SVG dual (memes teintes que le 3D).
  function dualCycleColor(size) {
    if (size === 5) return "#fed7aa";  // orange peche
    if (size === 6) return "#cbd5e1";  // gris-bleu
    if (size === 7) return "#a5b4fc";  // indigo clair
    return "#fde047";                   // jaune (taille inattendue)
  }

  /** Construit le SVG du graphe dual a partir du payload /api/dual. */
  function renderDualSvg(dual) {
    if (!dual || !dual.available || !dual.nodes || dual.nodes.length === 0) {
      return `<div class="molviz-dual-empty">Graphe dual indisponible
              (solution non-designer ou graphe d'entree absent).</div>`;
    }
    const nodes = dual.nodes;
    const edges = dual.edges || [];
    // Bornes pour normaliser dans le viewbox SVG.
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const W = 220, H = 240, PAD = 30, R = 18;
    const spanX = (maxX - minX) || 1, spanY = (maxY - minY) || 1;
    const sx = (W - 2 * PAD) / spanX;
    const sy = (H - 2 * PAD) / spanY;
    const scale = Math.min(sx, sy);
    // Centrage
    const offX = (W - spanX * scale) / 2 - minX * scale;
    const offY = (H - spanY * scale) / 2 - minY * scale;
    const px = n => offX + n.x * scale;
    const py = n => offY + n.y * scale;

    let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="100%" `
            + `xmlns="http://www.w3.org/2000/svg">`;
    // Aretes d'abord (sous les noeuds)
    for (const e of edges) {
      const a = nodes[e.a], b = nodes[e.b];
      if (!a || !b) continue;
      svg += `<line x1="${px(a).toFixed(1)}" y1="${py(a).toFixed(1)}" `
           + `x2="${px(b).toFixed(1)}" y2="${py(b).toFixed(1)}" `
           + `stroke="#475569" stroke-width="2" />`;
    }
    // Noeuds : cercle colore par taille + label de la taille
    for (const n of nodes) {
      const cx = px(n).toFixed(1), cy = py(n).toFixed(1);
      svg += `<circle cx="${cx}" cy="${cy}" r="${R}" `
           + `fill="${dualCycleColor(n.size)}" stroke="#1e293b" stroke-width="1.5" />`;
      svg += `<text x="${cx}" y="${cy}" text-anchor="middle" `
           + `dominant-baseline="central" font-size="14" font-weight="600" `
           + `fill="#1e293b">${n.size != null ? n.size : "?"}</text>`;
    }
    svg += `</svg>`;
    return svg;
  }

  /** Fetch /api/dual et injecte le SVG dans le panneau. Lazy, non bloquant. */
  async function loadAndRenderDual(xyzRel) {
    if (!dualPanelRef) return;
    const svgHost = dualPanelRef.querySelector("#molviz-dual-svg");
    if (!svgHost) return;
    try {
      const r = await fetch(`/api/dual?path=${encodeURIComponent(xyzRel)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const dual = await r.json();
      svgHost.innerHTML = renderDualSvg(dual);
    } catch (e) {
      svgHost.innerHTML = `<div class="molviz-dual-empty">Graphe dual indisponible.</div>`;
    }
  }

  /** Charge un .xyz et ouvre le modal. Accepte deux formes d'info :
   *   - {xyz_path, title, subtitle}   pour ouvrir un xyz arbitraire
   *   - {sol_dir, sol_idx, sizes, verdict}  pour les solutions (retro-compat)
   */
  /** Met a jour le libelle du bouton epingler/comparer selon l'etat. */
  function updateCompareBtn() {
    if (!compareBtnRef || !window.MolCompare) return;
    const p = window.MolCompare.getPinned();
    if (!p) {
      compareBtnRef.textContent = "📌 Comparer…";
      compareBtnRef.title = "Epingle cette molecule, puis ouvre une autre "
        + "solution et clique sur Comparer pour les voir cote a cote";
      compareBtnRef.classList.remove("pinned");
    } else if (p.xyz_path === currentXyzRel) {
      compareBtnRef.textContent = "📌 Epinglee";
      compareBtnRef.title = "Molecule epinglee. Ouvre une autre solution puis "
        + "clique sur Comparer. (Cliquer ici pour desepingler.)";
      compareBtnRef.classList.add("pinned");
    } else {
      compareBtnRef.textContent = "⚖ Comparer";
      compareBtnRef.title = `Comparer cote a cote avec : ${p.title}`;
      compareBtnRef.classList.add("pinned");
    }
  }

  /** Cycle epingler -> desepingler -> comparer du bouton header. */
  function onCompareClick() {
    if (!window.MolCompare || !currentXyzRel) return;
    const p = window.MolCompare.getPinned();
    const current = { xyz_path: currentXyzRel, title: currentTitle || "Molecule" };
    if (!p) {
      window.MolCompare.pin(current);
      updateCompareBtn();
    } else if (p.xyz_path === currentXyzRel) {
      window.MolCompare.clearPin();
      updateCompareBtn();
    } else {
      window.MolCompare.clearPin();
      close();
      window.MolCompare.open(p, current);
    }
  }

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
    // Le libelle du bouton epingler/comparer depend du chemin courant
    // (epinglee = ce meme chemin ? -> "Epinglee" vs "Comparer").
    updateCompareBtn();
    // Lien de telechargement direct : le navigateur gere le download via
    // Content-Disposition, pas besoin de fetch cote JS.
    if (exportLinkRef) {
      exportLinkRef.href = `/api/xyz_export?path=${encodeURIComponent(xyzRel)}`;
    }
    // Charge le graphe dual en parallele (non bloquant pour le rendu 3D).
    loadAndRenderDual(xyzRel);
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
    const unclosed = !!data.meta.unclosed_ring;
    refs.headerMeta.innerHTML = `
      <span>${data.meta.n_carbons} C</span>
      <span>${data.meta.n_bonds} liaisons (${data.meta.n_doubles} doubles)</span>
      ${unclosed
        ? ""
        : (data.meta.n_radicals > 0
            ? `<span style="color:#9333ea">${data.meta.n_radicals} radical${data.meta.n_radicals>1?'aux':''}</span>`
            : `<span style="color:#16a34a">perfect matching</span>`)}
      ${nAnomaly > 0
        ? `<span style="color:#a16207" title="Cycles de taille != 5/6/7 detectes (bond parasite ou geometrie cassee)">${nAnomaly} cycle${nAnomaly>1?'s':''} anormal${nAnomaly>1?'aux':''}</span>`
        : ""}
    `;

    // Bandeau "geometrie non relaxee" : affiche UNIQUEMENT pour le cas
    // detecte cote serveur (mode skip + cycle non ferme). On masque alors le
    // compteur de radicaux (qui serait trompeur : ce sont de faux radicaux dus
    // a un cycle ouvert, pas de vrais sites radicalaires).
    if (unclosed) {
      const banner = el("div", {
        class: "molviz-unclosed-banner",
        title: "La reconstruction rapide (skip) a deforme la geometrie a "
             + "l'interface 5/7 : les tailles de cycles affichees ne "
             + "correspondent pas a la solution (un 5 ou un 7 peut apparaitre "
             + "comme un hexagone, ou un cycle peut rester ouvert). "
             + "Relancez en validation xTB pour une geometrie exacte.",
      },
        "⚠ Geometrie non relaxee : les cycles affiches ne correspondent pas "
        + "exactement a la solution (reconstruction rapide). "
        + "Lancez la validation xTB pour une vue exacte.");
      // Insere le bandeau juste sous l'en-tete, avant la barre de modes.
      const modal = refs.overlay.querySelector(".molviz-modal");
      const modeBar = modal && modal.querySelector(".molviz-modebar");
      if (modal && modeBar) {
        modal.insertBefore(banner, modeBar);
      } else if (modal) {
        modal.insertBefore(banner, modal.children[1] || null);
      }
    }

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
  // openSafe : wrapper qui guard l'appelant si 3Dmol.js ou molviz n'est pas
  // charge sur la page courante. Centralise le message d'erreur pour eviter
  // des "MolViz non charge" formules de 5 manieres differentes dans app.js
  // et designer.js. Renvoie true si on a pu ouvrir, false sinon.
  function openSafe(info) {
    if (typeof $3Dmol === "undefined") {
      alert("3Dmol.js non charge. Ajouter <script src=\".../3Dmol-min.js\"> "
            + "avant molviz.js dans la page.");
      return false;
    }
    open(info);
    return true;
  }

  // Pre-chauffage du contexte WebGL de 3Dmol. Le PREMIER createViewer d'une
  // page est lent (~200-500 ms) car three.js compile ses shaders et initialise
  // le contexte WebGL a ce moment-la. On paie ce cout une fois, en arriere-plan
  // au chargement, sur un div jetable hors-ecran -> la premiere ouverture reelle
  // du modal devient quasi instantanee. Idempotent et sans effet sur le flux
  // open()/close() (div separe, detruit immediatement).
  let _warmedUp = false;
  function warmup() {
    if (_warmedUp || typeof $3Dmol === "undefined") return;
    _warmedUp = true;
    try {
      const tmp = el("div", {
        style: "position:absolute;width:2px;height:2px;left:-9999px;"
             + "top:-9999px;visibility:hidden;",
        id: "molviz-warmup",
      });
      document.body.appendChild(tmp);
      const vw = $3Dmol.createViewer("molviz-warmup", { backgroundColor: "white" });
      // un minuscule rendu force la compilation des shaders
      vw.addSphere({ center: { x: 0, y: 0, z: 0 }, radius: 0.1, color: 0x000000 });
      vw.render();
      // nettoyage immediat
      try { vw.removeAllModels(); } catch (_) {}
      try { vw.removeAllShapes(); } catch (_) {}
      tmp.remove();
    } catch (_) {
      // si le warmup echoue, ce n'est pas grave : open() recreera un viewer.
    }
  }

  // Declenche le warmup des que le DOM est pret (sans bloquer le chargement).
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => setTimeout(warmup, 0));
    } else {
      setTimeout(warmup, 0);
    }
  }

  window.MolViz = { open, openSafe, close, warmup };
})();
