/**
 * Designer de benzenoides.
 *
 * Modules internes (IIFE, pas de loader externe) :
 *   HexGrid     : maths hexagonale (axial <-> pixel), canvas drawing
 *   ConfigPanel : panneau de configuration CSP (dynamique depuis /api/designer/configs)
 *   JobRunner   : submission + polling d'un job
 *   LoadingScreen / ResultModal : UI feedback
 *   Toolbar     : import / export / clear / zoom
 *
 * State central : window.__designerState__ (visible pour debug console).
 *
 * Convention de coordonnees :
 *   - Axial (q, r) : coords entieres des hexagones
 *   - Pixel : coords ecran. Y croit vers le BAS (convention canvas), mais
 *     pour ressembler a une representation chimique naturelle on inverse :
 *     r positif = visuellement HAUT.
 */

(function () {
  "use strict";

  // ====================================================================
  //  HexGrid : maths hexagonale + drawing
  // ====================================================================

  const SQRT3 = Math.sqrt(3);

  // Etat du canvas : un set de "q,r" pour les hex selectionnes,
  // origine + scale pour le pan/zoom.
  const grid = {
    hexes: new Set(),      // keys "q,r"
    size: 28,              // pixel radius d'un hex
    originX: 0, originY: 0,  // pixel offset (pan)
    canvasW: 0, canvasH: 0,
    hover: null,           // {q, r} de l'hex survole
    dragging: false,
    dragMoved: false,      // true si on a deplace pendant le drag (pas un clic)
    dragStartX: 0, dragStartY: 0,
    dragOrigX: 0, dragOrigY: 0,
  };

  function hexKey(q, r) { return `${q},${r}`; }
  function parseKey(k) { const [q, r] = k.split(",").map(Number); return { q, r }; }

  // Axial -> pixel (pointy-top hex, r positif = haut visuellement)
  function axialToPixel(q, r) {
    return {
      x: grid.originX + grid.size * (SQRT3 * q + SQRT3 / 2 * r),
      y: grid.originY - grid.size * (1.5 * r),
    };
  }

  // Pixel -> axial fractionnaire
  function pixelToAxialFrac(px, py) {
    const x = (px - grid.originX) / grid.size;
    const y = -(py - grid.originY) / grid.size;  // inverser le flip
    return {
      q: SQRT3 / 3 * x - 1 / 3 * y,
      r: 2 / 3 * y,
    };
  }

  // Arrondi au hex le plus proche (cube round)
  function axialRound(qf, rf) {
    const sf = -qf - rf;
    let q = Math.round(qf);
    let r = Math.round(rf);
    let s = Math.round(sf);
    const dq = Math.abs(q - qf);
    const dr = Math.abs(r - rf);
    const ds = Math.abs(s - sf);
    if (dq > dr && dq > ds) q = -r - s;
    else if (dr > ds) r = -q - s;
    return { q, r };
  }

  // 6 coins en pixel pour rendu (pointy-top : sommets en haut/bas)
  function hexCornersPixel(q, r) {
    const c = axialToPixel(q, r);
    const corners = [];
    for (let i = 0; i < 6; i++) {
      const angle = Math.PI / 3 * i + Math.PI / 6;
      corners.push({
        x: c.x + grid.size * Math.cos(angle),
        y: c.y - grid.size * Math.sin(angle),  // y inverse (canvas down)
      });
    }
    return corners;
  }

  // Voisins axiaux (6 directions)
  const NEIGHBOR_OFFSETS = [
    [1, 0], [-1, 0], [0, 1], [-1, 1], [0, -1], [1, -1],
  ];

  function neighbors(q, r) {
    return NEIGHBOR_OFFSETS.map(([dq, dr]) => ({ q: q + dq, r: r + dr }));
  }

  // Detecte les "trous" internes du dessin (positions vides totalement
  // enclavees par des hexagones existants) et les ajoute automatiquement.
  // Un benzenoide polycyclique ne peut pas avoir de trou interne : tout
  // hexagone vide entoure de pleins doit appartenir a la molecule.
  //
  // Algorithme :
  //  1. Calculer la bounding box (q,r) des hex existants, etendue de 1.
  //  2. BFS depuis le coin (forcement vide) sur les cases vides : marque
  //     la composante "externe" (= face infinie discretisee).
  //  3. Toute case vide dans la bbox non visitee par ce BFS est un trou
  //     interne -> on l'ajoute a grid.hexes.
  //
  // Retourne le nombre d'hex ajoutes (0 si aucun trou detecte).
  function fillHoles() {
    if (grid.hexes.size === 0) return 0;
    let qmin = Infinity, qmax = -Infinity, rmin = Infinity, rmax = -Infinity;
    for (const k of grid.hexes) {
      const { q, r } = parseKey(k);
      if (q < qmin) qmin = q;
      if (q > qmax) qmax = q;
      if (r < rmin) rmin = r;
      if (r > rmax) rmax = r;
    }
    qmin--; qmax++; rmin--; rmax++;
    // BFS sur la composante externe (cases vides accessibles depuis le coin)
    const externalEmpty = new Set();
    const stack = [hexKey(qmin, rmin)];
    while (stack.length) {
      const k = stack.pop();
      if (externalEmpty.has(k)) continue;
      externalEmpty.add(k);
      const { q, r } = parseKey(k);
      for (const n of neighbors(q, r)) {
        if (n.q < qmin || n.q > qmax || n.r < rmin || n.r > rmax) continue;
        const nk = hexKey(n.q, n.r);
        if (grid.hexes.has(nk)) continue;
        if (externalEmpty.has(nk)) continue;
        stack.push(nk);
      }
    }
    // Trous = cases vides dans la bbox mais hors composante externe
    let added = 0;
    for (let q = qmin; q <= qmax; q++) {
      for (let r = rmin; r <= rmax; r++) {
        const k = hexKey(q, r);
        if (grid.hexes.has(k)) continue;
        if (externalEmpty.has(k)) continue;
        grid.hexes.add(k);
        added++;
      }
    }
    return added;
  }

  // Verifie la connexite du set d'hexes courant
  function isConnected() {
    if (grid.hexes.size <= 1) return true;
    const visited = new Set();
    const start = grid.hexes.values().next().value;
    const stack = [start];
    while (stack.length) {
      const k = stack.pop();
      if (visited.has(k)) continue;
      visited.add(k);
      const { q, r } = parseKey(k);
      for (const n of neighbors(q, r)) {
        const nk = hexKey(n.q, n.r);
        if (grid.hexes.has(nk) && !visited.has(nk)) {
          stack.push(nk);
        }
      }
    }
    return visited.size === grid.hexes.size;
  }

  // ---- Rendu ----
  let ctx = null;

  function clearCanvas() {
    ctx.fillStyle = "#fafbfc";
    ctx.fillRect(0, 0, grid.canvasW, grid.canvasH);
  }

  function drawGuideGrid() {
    // Grille pointillee : on dessine les centres des hex visibles dans la viewport
    // en cherchant les (q, r) qui tombent dans le rect visible.
    ctx.fillStyle = "#cbd5e1";
    const margin = grid.size * 2;
    // Estimer le range (q, r) visible par les 4 coins
    const corners = [
      pixelToAxialFrac(-margin, -margin),
      pixelToAxialFrac(grid.canvasW + margin, -margin),
      pixelToAxialFrac(-margin, grid.canvasH + margin),
      pixelToAxialFrac(grid.canvasW + margin, grid.canvasH + margin),
    ];
    const qmin = Math.floor(Math.min(...corners.map(c => c.q)));
    const qmax = Math.ceil(Math.max(...corners.map(c => c.q)));
    const rmin = Math.floor(Math.min(...corners.map(c => c.r)));
    const rmax = Math.ceil(Math.max(...corners.map(c => c.r)));
    for (let q = qmin; q <= qmax; q++) {
      for (let r = rmin; r <= rmax; r++) {
        const p = axialToPixel(q, r);
        if (p.x < -margin || p.x > grid.canvasW + margin) continue;
        if (p.y < -margin || p.y > grid.canvasH + margin) continue;
        if (!grid.hexes.has(hexKey(q, r))) {
          // Dot vide
          ctx.beginPath();
          ctx.arc(p.x, p.y, 1.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }

  function drawHex(q, r, fill, stroke, opacity = 1.0) {
    const corners = hexCornersPixel(q, r);
    ctx.globalAlpha = opacity;
    ctx.beginPath();
    ctx.moveTo(corners[0].x, corners[0].y);
    for (let i = 1; i < 6; i++) {
      ctx.lineTo(corners[i].x, corners[i].y);
    }
    ctx.closePath();
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    ctx.globalAlpha = 1.0;
  }

  function render() {
    if (!ctx) return;
    clearCanvas();
    drawGuideGrid();

    // Hex selectionnes
    for (const k of grid.hexes) {
      const { q, r } = parseKey(k);
      drawHex(q, r, "#dbeafe", "#2563eb", 1.0);
    }

    // Hex survole (preview)
    if (grid.hover && !grid.dragging) {
      const { q, r } = grid.hover;
      const k = hexKey(q, r);
      if (grid.hexes.has(k)) {
        // Hex existant survole : preview suppression
        drawHex(q, r, "#fee2e2", "#dc2626", 0.7);
      } else {
        // Case vide : preview ajout (verifie qu'on garde la connexite)
        const wouldBeConnected = grid.hexes.size === 0 ||
          neighbors(q, r).some(n => grid.hexes.has(hexKey(n.q, n.r)));
        if (wouldBeConnected) {
          drawHex(q, r, "#d1fae5", "#16a34a", 0.5);
        } else {
          drawHex(q, r, "#f3f4f6", "#9ca3af", 0.3);
        }
      }
    }
  }

  // ---- Manipulation du set ----
  function toggleHex(q, r) {
    const k = hexKey(q, r);
    if (grid.hexes.has(k)) {
      // Retrait : verifier que le retrait ne deconnecte pas
      grid.hexes.delete(k);
      if (!isConnected() && grid.hexes.size > 0) {
        grid.hexes.add(k);  // restore
        updateStatus("Suppression refusee : deconnecte le benzenoide");
        return false;
      }
    } else {
      // Ajout : verifier connexite (si pas le 1er hex, doit toucher un voisin)
      if (grid.hexes.size > 0) {
        const ok = neighbors(q, r).some(n => grid.hexes.has(hexKey(n.q, n.r)));
        if (!ok) {
          updateStatus("Ajout refuse : non adjacent aux autres hex");
          return false;
        }
      }
      grid.hexes.add(k);
    }
    onHexesChanged();
    return true;
  }

  function setHexesFromList(list) {
    grid.hexes.clear();
    for (const h of list) {
      grid.hexes.add(hexKey(h.q, h.r));
    }
    onHexesChanged();
    recenterView();
  }

  function clearHexes() {
    grid.hexes.clear();
    onHexesChanged();
  }

  // Recadre la vue pour que tous les hex soient visibles
  function recenterView() {
    if (grid.hexes.size === 0) {
      grid.originX = grid.canvasW / 2;
      grid.originY = grid.canvasH / 2;
      render();
      return;
    }
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    for (const k of grid.hexes) {
      const { q, r } = parseKey(k);
      const p = axialToPixel(q, r);
      const dx = grid.size, dy = grid.size;
      xmin = Math.min(xmin, p.x - dx);
      xmax = Math.max(xmax, p.x + dx);
      ymin = Math.min(ymin, p.y - dy);
      ymax = Math.max(ymax, p.y + dy);
    }
    // Centre le bbox dans le canvas
    const bw = xmax - xmin, bh = ymax - ymin;
    const dx = grid.canvasW / 2 - (xmin + bw / 2);
    const dy = grid.canvasH / 2 - (ymin + bh / 2);
    grid.originX += dx;
    grid.originY += dy;
    render();
  }

  // ====================================================================
  //  Initialisation canvas + event listeners
  // ====================================================================

  let canvasEl = null;

  function initCanvas() {
    canvasEl = document.getElementById("hex-canvas");
    ctx = canvasEl.getContext("2d");
    resizeCanvas();
    window.addEventListener("resize", () => {
      resizeCanvas();
      render();
    });

    // Mouse events
    canvasEl.addEventListener("mousedown", onMouseDown);
    canvasEl.addEventListener("mousemove", onMouseMove);
    canvasEl.addEventListener("mouseup", onMouseUp);
    canvasEl.addEventListener("mouseleave", onMouseLeave);
    canvasEl.addEventListener("wheel", onWheel, { passive: false });
    canvasEl.addEventListener("contextmenu", e => e.preventDefault());

    // Position initiale : centre du canvas
    grid.originX = grid.canvasW / 2;
    grid.originY = grid.canvasH / 2;
    render();
  }

  function resizeCanvas() {
    const rect = canvasEl.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvasEl.width = rect.width * dpr;
    canvasEl.height = rect.height * dpr;
    canvasEl.style.width = rect.width + "px";
    canvasEl.style.height = rect.height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    grid.canvasW = rect.width;
    grid.canvasH = rect.height;
  }

  function getMousePos(e) {
    const rect = canvasEl.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function onMouseDown(e) {
    const p = getMousePos(e);
    grid.dragging = true;
    grid.dragMoved = false;
    grid.dragStartX = p.x;
    grid.dragStartY = p.y;
    grid.dragOrigX = grid.originX;
    grid.dragOrigY = grid.originY;
    canvasEl.classList.add("dragging");
  }

  function onMouseMove(e) {
    const p = getMousePos(e);
    if (grid.dragging) {
      const dx = p.x - grid.dragStartX;
      const dy = p.y - grid.dragStartY;
      // Pan uniquement si on a bouge significativement
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        grid.dragMoved = true;
        grid.originX = grid.dragOrigX + dx;
        grid.originY = grid.dragOrigY + dy;
        render();
      }
    } else {
      // Hover preview
      const f = pixelToAxialFrac(p.x, p.y);
      const h = axialRound(f.q, f.r);
      if (!grid.hover || grid.hover.q !== h.q || grid.hover.r !== h.r) {
        grid.hover = h;
        render();
      }
    }
  }

  function onMouseUp(e) {
    if (grid.dragging && !grid.dragMoved) {
      // Clic simple : toggle hex
      const p = getMousePos(e);
      const f = pixelToAxialFrac(p.x, p.y);
      const h = axialRound(f.q, f.r);
      toggleHex(h.q, h.r);
    }
    grid.dragging = false;
    grid.dragMoved = false;
    canvasEl.classList.remove("dragging");
    render();
  }

  function onMouseLeave() {
    grid.hover = null;
    grid.dragging = false;
    canvasEl.classList.remove("dragging");
    render();
  }

  function onWheel(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -1 : 1;
    const factor = delta > 0 ? 1.12 : 1 / 1.12;
    const p = getMousePos(e);
    // Zoom autour du curseur : maintien du point sous le curseur
    const before = pixelToAxialFrac(p.x, p.y);
    grid.size = Math.max(8, Math.min(80, grid.size * factor));
    const after = pixelToAxialFrac(p.x, p.y);
    // Compense : translater pour que before reste sous le curseur
    const pBefore = axialToPixel(before.q, before.r);
    const pAfter = axialToPixel(after.q, after.r);
    grid.originX += pBefore.x - pAfter.x;
    grid.originY += pBefore.y - pAfter.y;
    render();
  }

  // ====================================================================
  //  Status + counters
  // ====================================================================

  function onHexesChanged() {
    const filled = fillHoles();
    if (filled > 0) {
      const s = filled > 1 ? "s" : "";
      updateStatus(`${filled} hexagone${s} ajouté${s} automatiquement (trou${s} interne${s} fermé${s})`);
    }
    updateCounters();
    updateRunButton();
    updateHelpCardVisibility();
    render();
  }

  function updateCounters() {
    document.getElementById("count-hex").textContent = grid.hexes.size;
    // Calculer atomes/liaisons via le meme algo que graph_io.serialize_to_graph
    const atoms = new Set();
    const edges = new Set();
    for (const k of grid.hexes) {
      const { q, r } = parseKey(k);
      const corners = hexCorners(q, r);
      for (let i = 0; i < 6; i++) {
        atoms.add(corners[i]);
        const a = corners[i], b = corners[(i + 1) % 6];
        const edge = a < b ? `${a}|${b}` : `${b}|${a}`;
        edges.add(edge);
      }
    }
    document.getElementById("count-atoms").textContent = atoms.size;
    document.getElementById("count-edges").textContent = edges.size;
  }

  // hex_corners JS (miroir de graph_io.hex_corners cote Python)
  function hexCorners(q, r) {
    const cx = 2 * q + r;
    const cy = 2 * r;
    return [
      `${cx}_${cy}`,
      `${cx + 1}_${cy + 1}`,
      `${cx + 1}_${cy + 2}`,
      `${cx}_${cy + 3}`,
      `${cx - 1}_${cy + 2}`,
      `${cx - 1}_${cy + 1}`,
    ];
  }

  function updateRunButton() {
    document.getElementById("btn-run").disabled = grid.hexes.size === 0;
  }

  function updateHelpCardVisibility() {
    document.getElementById("canvas-help").classList.toggle(
      "hidden", grid.hexes.size > 0
    );
  }

  function updateStatus(msg) {
    document.getElementById("status-info").textContent = msg;
    // Auto-clear apres 3 secondes
    clearTimeout(updateStatus._t);
    updateStatus._t = setTimeout(() => {
      if (document.getElementById("status-info").textContent === msg) {
        document.getElementById("status-info").textContent = "";
      }
    }, 3000);
  }

  // ====================================================================
  //  Serialisation .graph (miroir Python pour export local)
  // ====================================================================

  function serializeToGraph(hexesList) {
    if (hexesList.length === 0) return "p DIMACS 0 0 0\n";
    const atoms = new Set();
    const hexCorners_ = [];
    for (const [q, r] of hexesList) {
      const c = hexCorners(q, r);
      hexCorners_.push(c);
      c.forEach(a => atoms.add(a));
    }
    const edges = new Set();
    for (const c of hexCorners_) {
      for (let i = 0; i < 6; i++) {
        const a = c[i], b = c[(i + 1) % 6];
        edges.add(a < b ? `${a}|${b}` : `${b}|${a}`);
      }
    }
    const lines = [`p DIMACS ${atoms.size} ${edges.size} ${hexesList.length}`];
    const sortedEdges = [...edges].sort();
    for (const e of sortedEdges) {
      const [a, b] = e.split("|");
      lines.push(`e ${a} ${b}`);
    }
    for (const c of hexCorners_) {
      lines.push("h " + c.join(" ") + " ");
    }
    return lines.join("\n") + "\n";
  }

  // ====================================================================
  //  ConfigPanel : panneau de configuration dynamique
  // ====================================================================

  // -----------------------------------------------------------------
  // configState contient TOUT l'etat du panneau :
  //   - preset           : 'C1' | 'C2' | 'C3' | 'Ctopo' | 'custom'
  //   - <flag advanced>  : chaque cle des CSP_ADVANCED_OPTIONS (K_pb, ...)
  //   - method, n_runs, cluster (validation)
  //
  // Quand preset != 'custom', les flags advanced sont IGNORES par le
  // backend (ecrases par les flags du preset). On les conserve quand meme
  // en memoire pour quand l'utilisateur switche vers 'custom'.
  // -----------------------------------------------------------------
  const configState = { preset: "C2" };
  let presetsCanonical = [];
  let advancedOptions = [];
  let advancedGroups = [];
  let validationOptions = [];
  let clusterEnabled = false;

  async function loadConfigPanel() {
    try {
      const r = await fetch("/api/designer/configs");
      const data = await r.json();
      presetsCanonical = data.presets_canonical || [];
      advancedOptions = data.advanced_options || [];
      advancedGroups = data.advanced_groups || [];
      validationOptions = data.validation_options || [];
      clusterEnabled = !!data.cluster_enabled;

      // Initialise defaults pour advanced et validation
      for (const c of advancedOptions) {
        if (configState[c.key] === undefined) {
          configState[c.key] = c.default;
        }
      }
      for (const v of validationOptions) {
        if (configState[v.key] === undefined) {
          configState[v.key] = v.default;
        }
      }

      renderPresetPanel();
      renderAdvancedPanel();
      renderValidationPanel();
      bindTabs();
    } catch (e) {
      console.error("Config load failed", e);
      document.getElementById("tab-panel-preset").innerHTML =
        '<p class="dz-muted">Erreur de chargement des configs</p>';
    }
  }

  // ---- Onglets ----
  function bindTabs() {
    document.querySelectorAll(".dz-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tab;
        document.querySelectorAll(".dz-tab").forEach((b) => {
          const active = b.dataset.tab === target;
          b.classList.toggle("active", active);
          b.setAttribute("aria-selected", active ? "true" : "false");
        });
        document.querySelectorAll(".dz-tab-panel").forEach((p) => {
          const active = p.id === `tab-panel-${target}`;
          p.classList.toggle("active", active);
          p.hidden = !active;
        });
      });
    });
  }

  // ---- Onglet "Preset" : 4 radios C1/C2/C3/Ctopo + custom ----
  function renderPresetPanel() {
    const panel = document.getElementById("tab-panel-preset");
    panel.innerHTML = "";
    const list = document.createElement("div");
    list.className = "dz-radio-list";

    // Les 4 presets canoniques
    for (const p of presetsCanonical) {
      const row = document.createElement("label");
      row.className = "dz-radio-row";
      if (configState.preset === p.key) row.classList.add("selected");

      const input = document.createElement("input");
      input.type = "radio";
      input.name = "preset";
      input.value = p.key;
      input.checked = (configState.preset === p.key);
      input.addEventListener("change", () => {
        if (input.checked) {
          configState.preset = p.key;
          renderPresetPanel();
          renderAdvancedPanel();  // recalcule disabled state
        }
      });

      const content = document.createElement("div");
      content.className = "dz-radio-content";
      const title = document.createElement("div");
      title.className = "dz-radio-title";
      title.textContent = p.label;
      const help = document.createElement("div");
      help.className = "dz-radio-help";
      help.textContent = p.help || "";
      content.appendChild(title);
      content.appendChild(help);

      row.appendChild(input);
      row.appendChild(content);
      list.appendChild(row);
    }

    // Option "custom" : utilise les valeurs de l'onglet Avance
    const customRow = document.createElement("label");
    customRow.className = "dz-radio-row";
    if (configState.preset === "custom") customRow.classList.add("selected");

    const customInput = document.createElement("input");
    customInput.type = "radio";
    customInput.name = "preset";
    customInput.value = "custom";
    customInput.checked = (configState.preset === "custom");
    customInput.addEventListener("change", () => {
      if (customInput.checked) {
        configState.preset = "custom";
        renderPresetPanel();
        renderAdvancedPanel();
      }
    });

    const customContent = document.createElement("div");
    customContent.className = "dz-radio-content";
    const customTitle = document.createElement("div");
    customTitle.className = "dz-radio-title";
    customTitle.textContent = "Custom (utiliser l'onglet Avance)";
    const customHelp = document.createElement("div");
    customHelp.className = "dz-radio-help";
    customHelp.textContent =
      "Aucun preset force. Les contraintes individuelles du tableau de bord " +
      "(onglet Avance) seront prises en compte.";
    customContent.appendChild(customTitle);
    customContent.appendChild(customHelp);

    customRow.appendChild(customInput);
    customRow.appendChild(customContent);
    list.appendChild(customRow);

    panel.appendChild(list);
  }

  // ---- Onglet "Avance" : tableau de bord groupe par theme ----
  function renderAdvancedPanel() {
    const panel = document.getElementById("tab-panel-advanced");
    panel.innerHTML = "";

    // Banniere d'info si un preset != custom est actif
    const presetActive = configState.preset && configState.preset !== "custom";
    if (presetActive) {
      const banner = document.createElement("div");
      banner.className = "dz-config-help";
      banner.style.background = "#fef3c7";
      banner.style.padding = "0.5rem";
      banner.style.borderRadius = "4px";
      banner.style.paddingLeft = "0.5rem";
      banner.textContent =
        `Preset ${configState.preset} actif : les contraintes CSP ci-dessous ` +
        `sont ignorees (le preset les ecrase). Passe en mode 'Custom' dans ` +
        `l'onglet Preset pour les utiliser.`;
      panel.appendChild(banner);
    }

    // Render chaque groupe
    for (const group of advancedGroups) {
      const inGroup = advancedOptions.filter((o) => o.group === group.key);
      if (inGroup.length === 0) continue;

      const sec = document.createElement("div");
      sec.className = "dz-group";
      const title = document.createElement("h4");
      title.className = "dz-group-title";
      title.textContent = group.label;
      sec.appendChild(title);

      for (const c of inGroup) {
        sec.appendChild(renderConfigRow(c, presetActive));
      }
      panel.appendChild(sec);
    }
  }

  // ---- Bloc "Validation xTB" : method + n_runs + cluster ----
  function renderValidationPanel() {
    const panel = document.getElementById("validation-panel");
    panel.innerHTML = "";
    for (const c of validationOptions) {
      if (c.cluster_feature && !clusterEnabled) continue;
      panel.appendChild(renderConfigRow(c, false));
    }
  }

  // ---- Helper generique de rendu d'une ligne (bool / int / int_or_none / select) ----
  function renderConfigRow(c, disabled) {
    const row = document.createElement("div");
    row.className = "dz-config-row";

    const label = document.createElement("label");
    let input;

    if (c.type === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!configState[c.key];
      input.disabled = !!disabled;
      input.addEventListener("change", () => {
        configState[c.key] = input.checked;
      });
      label.appendChild(input);
      label.appendChild(document.createTextNode(" " + c.label));
    } else if (c.type === "int" || c.type === "int_or_none") {
      const txt = document.createElement("span");
      txt.textContent = c.label + " : ";
      input = document.createElement("input");
      input.type = "number";
      input.disabled = !!disabled;
      if (c.min !== undefined) input.min = c.min;
      if (c.max !== undefined) input.max = c.max;
      if (configState[c.key] === null || configState[c.key] === undefined) {
        input.value = "";
        if (c.type === "int_or_none") {
          input.placeholder = "(vide = pas de contrainte)";
        }
      } else {
        input.value = configState[c.key];
      }
      input.addEventListener("change", () => {
        if (input.value === "" && c.type === "int_or_none") {
          configState[c.key] = null;
        } else {
          const v = parseInt(input.value, 10);
          configState[c.key] = isNaN(v) ? null : v;
        }
      });
      label.appendChild(txt);
      label.appendChild(input);
    } else if (c.type === "select") {
      const txt = document.createElement("div");
      txt.textContent = c.label;
      input = document.createElement("select");
      input.disabled = !!disabled;
      for (const opt of (c.options || [])) {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        if (opt.value === configState[c.key]) o.selected = true;
        input.appendChild(o);
      }
      const ck = c.key;
      input.addEventListener("change", () => {
        configState[ck] = input.value;
      });
      label.style.flexDirection = "column";
      label.style.alignItems = "flex-start";
      label.appendChild(txt);
      label.appendChild(input);
    }
    row.appendChild(label);

    if (c.help) {
      const help = document.createElement("p");
      help.className = "dz-config-help";
      help.textContent = c.help;
      row.appendChild(help);
    }
    return row;
  }

  // ====================================================================
  //  Templates : import depuis csp_solver/data/
  // ====================================================================

  async function loadTemplates() {
    const sel = document.getElementById("select-template");
    try {
      const r = await fetch("/api/designer/templates");
      const data = await r.json();
      for (const t of (data.templates || [])) {
        const o = document.createElement("option");
        o.value = t.name;
        o.textContent = `${t.name} (${t.n_hex} hex)`;
        sel.appendChild(o);
      }
    } catch (e) {
      console.warn("Templates load failed", e);
    }
    sel.addEventListener("change", async () => {
      const name = sel.value;
      if (!name) return;
      try {
        const r = await fetch(`/api/designer/templates/${encodeURIComponent(name)}`);
        const data = await r.json();
        if (data.hexes) {
          setHexesFromList(data.hexes);
          updateStatus(`Template "${name}" charge : ${data.hexes.length} hex`);
        }
      } catch (e) {
        updateStatus("Erreur de chargement du template");
      }
      sel.value = "";  // reset selection
    });
  }

  // Import fichier .graph local (parse cote serveur en POST n'est pas necessaire :
  // on peut parser cote client comme on a la formule en JS)
  function parseGraphContent(content) {
    const hexes = [];
    for (const line of content.split("\n")) {
      const parts = line.trim().split(/\s+/);
      if (parts[0] !== "h") continue;
      const atoms = parts.slice(1, 7);
      if (atoms.length !== 6) continue;
      // Calculer (q, r) depuis somme des coords (cf hex_from_atoms cote Python)
      let sum_cx = 0, sum_cy = 0;
      try {
        for (const a of atoms) {
          const [cx, cy] = a.split("_").map(Number);
          sum_cx += cx; sum_cy += cy;
        }
        if ((sum_cy - 9) % 12 !== 0) continue;
        const r = (sum_cy - 9) / 12;
        if ((sum_cx - 6 * r) % 12 !== 0) continue;
        const q = (sum_cx - 6 * r) / 12;
        hexes.push({ q, r });
      } catch (e) { continue; }
    }
    return hexes;
  }

  function initFileImport() {
    document.getElementById("file-import").addEventListener("change", async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const text = await f.text();
      const hexes = parseGraphContent(text);
      if (hexes.length === 0) {
        updateStatus("Fichier vide ou format non reconnu");
      } else {
        setHexesFromList(hexes);
        updateStatus(`Importe ${hexes.length} hex depuis ${f.name}`);
      }
      e.target.value = "";  // reset
    });
  }

  // Export .graph
  function exportGraph() {
    if (grid.hexes.size === 0) {
      updateStatus("Rien a exporter");
      return;
    }
    const list = [...grid.hexes].map(k => {
      const { q, r } = parseKey(k);
      return [q, r];
    });
    const content = serializeToGraph(list);
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `designer_${grid.hexes.size}hex.graph`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    updateStatus(`Exporte ${grid.hexes.size} hex`);
  }

  // ====================================================================
  //  JobRunner : submit + polling
  // ====================================================================

  const runner = {
    jobId: null,
    pollTimer: null,
    startTime: 0,
  };

  async function submitJob() {
    if (grid.hexes.size === 0) return;
    const hexes = [...grid.hexes].map(k => parseKey(k));
    try {
      showLoadingModal("Lancement…");
      const r = await fetch("/api/designer/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hexes, config: configState }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${r.status}`);
      }
      const data = await r.json();
      runner.jobId = data.job_id;
      runner.startTime = Date.now();
      document.getElementById("loading-jobid").textContent = `#${data.job_id}`;
      pollJob();
    } catch (e) {
      hideLoadingModal();
      showResultModal({ state: "failed", error: e.message });
    }
  }

  async function pollJob() {
    if (!runner.jobId) return;
    try {
      const r = await fetch(`/api/designer/jobs/${runner.jobId}`);
      const job = await r.json();
      updateLoadingFromJob(job);
      if (["success", "failed", "cancelled"].includes(job.state)) {
        runner.pollTimer = null;
        hideLoadingModal();
        showResultModal(job);
        refreshRecentJobs();
        return;
      }
    } catch (e) {
      console.warn("poll error", e);
    }
    runner.pollTimer = setTimeout(pollJob, 800);
  }

  function updateLoadingFromJob(job) {
    const stage = job.current_stage || "preparation";
    const stageLabels = {
      "original": "Test xTB du benzenoide d'entree",
      "parse": "Lecture du fichier .graph",
      "preprocess": "Pre-traitement (gel des hex, generateurs)",
      "csp": "Resolution CSP (recherche des solutions)",
      "csp_done": "Solutions CSP trouvees, reconstruction…",
      "reconstruct": "Reconstruction 3D des solutions",
      "md": "Validation xTB (dynamique moleculaire + optimisation)",
      "aggregate": "Calcul de la planarite des solutions",
      "done": "Termine",
    };
    document.getElementById("loading-stage").textContent =
      stageLabels[stage] || stage;
    const pct = Math.round((job.progress || 0) * 100);
    document.getElementById("progress-fill").style.width = `${pct}%`;
    const elapsed = (Date.now() - runner.startTime) / 1000;
    document.getElementById("loading-elapsed").textContent =
      `${elapsed.toFixed(1)} s ecoulees`;
    document.getElementById("loading-detail").textContent =
      `${pct}%`;
  }

  async function cancelJob() {
    if (!runner.jobId) return;
    try {
      await fetch(`/api/designer/jobs/${runner.jobId}/cancel`, { method: "POST" });
    } catch (e) { /* ignore */ }
  }

  function showLoadingModal(initStage) {
    document.getElementById("loading-stage").textContent = initStage || "Initialisation…";
    document.getElementById("progress-fill").style.width = "5%";
    document.getElementById("loading-elapsed").textContent = "0 s";
    document.getElementById("loading-detail").textContent = "";
    document.getElementById("loading-jobid").textContent = "";
    document.getElementById("loading-overlay").classList.remove("hidden");
  }

  function hideLoadingModal() {
    document.getElementById("loading-overlay").classList.add("hidden");
  }

  // ====================================================================
  //  ResultModal
  // ====================================================================

  async function showResultModal(job) {
    const overlay = document.getElementById("result-overlay");
    const title = document.getElementById("result-title");
    const body = document.getElementById("result-body");
    const jobIdEl = document.getElementById("result-jobid");
    const viewBtn = document.getElementById("btn-result-view");
    jobIdEl.textContent = job.job_id ? `#${job.job_id}` : "";
    body.innerHTML = "";

    if (job.state === "success") {
      title.textContent = "Generation terminee";
      title.style.color = "#16a34a";
      const s = job.summary || {};
      const stats = [
        ["Solutions trouvees", s.n_sol_dirs || 0],
        ["Solutions avec source.xyz", s.n_with_xyz || 0],
        ["Solutions validees MD", s.n_with_md || 0],
        ["Duree totale", job.duration_s ? `${job.duration_s.toFixed(1)} s` : "—"],
      ];
      for (const [lbl, val] of stats) {
        const d = document.createElement("div");
        d.className = "dz-result-stat";
        d.innerHTML = `<span class="lbl">${lbl}</span><span class="val">${val}</span>`;
        body.appendChild(d);
      }

      // Liste des solutions avec bouton 3D par ligne. On va chercher en lazy.
      const listWrap = document.createElement("div");
      listWrap.className = "dz-result-solutions";
      listWrap.innerHTML = `
        <div class="dz-section-title-sm">Solutions (3D)</div>
        <div class="dz-sol-list" id="result-sol-list">
          <div class="dz-loading-mini">Chargement…</div>
        </div>
      `;
      body.appendChild(listWrap);
      // Fetch async (ne bloque pas l'affichage du modal)
      fetchAndRenderSolutions(job.job_id);

      // Activation : DB-natif (n_ingested_db) OU legacy fs (n_sol_dirs).
      const hasSols = (s.n_ingested_db || 0) > 0 || (s.n_sol_dirs || 0) > 0;
      viewBtn.disabled = !hasSols;
      viewBtn.textContent = "Ouvrir dans le viewer principal";
      viewBtn.onclick = () => {
        // Ouvre la vue job dediee dans le viewer principal (route /?job=<id>,
        // cf viewer/static/app.js:loadJobView).
        window.open(`/?job=${job.job_id}`, "_blank");
      };
    } else if (job.state === "cancelled") {
      title.textContent = "Annule";
      title.style.color = "#92400e";
      body.innerHTML = '<p class="dz-muted">Le job a ete annule par l\'utilisateur.</p>';
      viewBtn.disabled = true;
    } else {
      title.textContent = "Echec";
      title.style.color = "#b91c1c";
      const errDiv = document.createElement("div");
      errDiv.className = "dz-result-error";
      errDiv.textContent = job.error || "Erreur inconnue";
      body.appendChild(errDiv);
      viewBtn.disabled = true;
    }
    overlay.classList.remove("hidden");
  }

  // Recupere la liste des solutions du job et l'affiche dans le modal.
  // Chaque ligne a un bouton "3D" qui ouvre molviz.
  async function fetchAndRenderSolutions(jobId) {
    const container = document.getElementById("result-sol-list");
    if (!container) return;
    try {
      const r = await fetch(`/api/designer/jobs/${jobId}/solutions`);
      const data = await r.json();
      const sols = data.solutions || [];
      if (sols.length === 0) {
        container.innerHTML =
          '<p class="dz-muted">Aucune solution materialisee. '
          + 'Active "Validation xTB" pour produire les fichiers .xyz.</p>';
        return;
      }
      container.innerHTML = "";
      for (const sol of sols) {
        const row = document.createElement("div");
        row.className = "dz-sol-row";
        const verdictClass = sol.verdict === "md_ok"
          ? "ok"
          : (sol.verdict === "md_failed" ? "warn" : "unk");
        const verdictLabel = sol.verdict === "md_ok" ? "MD OK"
          : (sol.verdict === "md_failed" ? "MD echec" : "—");
        const sizesDisplay = sol.sizes
          ? sol.sizes.replace(/_/g, "-")
          : "?";
        row.innerHTML = `
          <span class="dz-sol-idx">#${sol.sol_idx}</span>
          <span class="dz-sol-sizes">sizes ${sizesDisplay}</span>
          <span class="dz-sol-verdict ${verdictClass}">${verdictLabel}</span>
          <button class="dz-btn dz-btn-mini" data-path="${sol.best_xyz_path || ""}"
                  ${sol.best_xyz_path ? "" : "disabled"}>
            <span>📐</span> 3D
          </button>
        `;
        const btn = row.querySelector("button");
        if (sol.best_xyz_path) {
          btn.addEventListener("click", () => {
            // Utilise openSafe pour avoir un message d'erreur consistant
            // si 3Dmol.js n'est pas charge (cf molviz.js).
            const ok = window.MolViz && window.MolViz.openSafe
              && window.MolViz.openSafe({
                   xyz_path: sol.best_xyz_path,
                   title: `Job #${jobId} · ${sol.name}`,
                   subtitle: `sizes ${sizesDisplay} · ${verdictLabel}`,
                 });
            if (!ok) updateStatus("molviz non disponible");
          });
        }
        container.appendChild(row);
      }
    } catch (e) {
      container.innerHTML = `<p class="dz-muted">Erreur de chargement : ${e.message}</p>`;
    }
  }

  function hideResultModal() {
    document.getElementById("result-overlay").classList.add("hidden");
  }

  // ====================================================================
  //  Recent jobs panel
  // ====================================================================

  async function refreshRecentJobs() {
    try {
      const r = await fetch("/api/designer/jobs");
      const data = await r.json();
      const list = data.jobs || [];
      const panel = document.getElementById("recent-jobs-list");
      if (list.length === 0) {
        panel.innerHTML = '<p class="dz-muted">Aucun job recent</p>';
        return;
      }
      panel.innerHTML = "";
      for (const j of list.slice(0, 10)) {
        const item = document.createElement("div");
        item.className = "dz-job-item";
        const left = document.createElement("span");
        left.className = "dz-job-id";
        left.textContent = `#${j.job_id}`;
        const right = document.createElement("span");
        right.className = `dz-job-state ${j.state}`;
        right.textContent = j.state;
        item.appendChild(left);
        item.appendChild(right);
        // Clic sur un job success/failed pour rouvrir son modal de resultats
        if (["success", "failed", "cancelled"].includes(j.state)) {
          item.style.cursor = "pointer";
          item.title = "Cliquer pour rouvrir les resultats";
          item.addEventListener("click", async () => {
            try {
              const r = await fetch(`/api/designer/jobs/${j.job_id}`);
              const job = await r.json();
              showResultModal(job);
            } catch (e) { /* ignore */ }
          });
        }
        panel.appendChild(item);
      }
    } catch (e) {
      console.warn("recent jobs failed", e);
    }
  }

  // ====================================================================
  //  Boot
  // ====================================================================

  function initToolbar() {
    document.getElementById("btn-clear").addEventListener("click", () => {
      if (grid.hexes.size === 0) return;
      if (confirm("Vraiment tout effacer ?")) clearHexes();
    });
    document.getElementById("btn-export").addEventListener("click", exportGraph);
    document.getElementById("btn-zoom-in").addEventListener("click", () => {
      grid.size = Math.min(80, grid.size * 1.2);
      render();
    });
    document.getElementById("btn-zoom-out").addEventListener("click", () => {
      grid.size = Math.max(8, grid.size / 1.2);
      render();
    });
    document.getElementById("btn-recenter").addEventListener("click", recenterView);
    document.getElementById("btn-run").addEventListener("click", submitJob);
    document.getElementById("btn-cancel-job").addEventListener("click", cancelJob);
    document.getElementById("btn-result-close").addEventListener("click", hideResultModal);
  }

  function init() {
    initCanvas();
    initToolbar();
    initFileImport();
    loadConfigPanel();
    loadTemplates();
    refreshRecentJobs();
    onHexesChanged();
    updateStatus("Pret. Clic pour ajouter un hexagone.");

    // Expose state for debug
    window.__designerState__ = { grid, configState, runner };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
