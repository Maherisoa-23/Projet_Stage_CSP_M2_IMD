/* =========================================================================
   view.js -- Logique interactive du viewer agrege.

   Les donnees (ALL_CONFIGS) sont injectees par Python dans `window.__DATA__`
   via un <script> prealable. Ce fichier est pur JS (pas de substitution
   Python) : il lit __DATA__ une fois puis pilote l'affichage.

   Toutes les fonctions manipulent un etat unique (`state`), encapsule dans
   une IIFE. Les handlers onclick inline dans le HTML sont exposes sur
   `window.<name>` en fin de fichier (sinon ils seraient invisibles du DOM).
   ========================================================================= */

(function () {
  'use strict';

  var state = {
    ALL_CONFIGS: window.__DATA__,
    currentConfig: null,
    selectedConfigs: [],
    compareMode: false,
    sortCol: 'name',
    sortAsc: true,
    filterOrig: 'all',     // 'all' | 'planar' | 'nonplanar'
    filterSol: 'all',
    filterStab: 'all',     // 'all' | 'stable_planar' | 'unstable' | 'stable_non_planar'
    searchQuery: '',
    /* expandedMols est partage entre la vue simple et la vue comparaison :
       le meme selecteur CSS [data-parent="X"] matche dans les deux, donc
       un toggle dans un panneau deplie la molecule dans tous. Voulu. */
    expandedMols: {},
    compareFilter: 'all',  // 'all' | 'diff'
  };

  /* ==== Multi-runs : classes de stabilite ====
     Invariant partage avec update_report.py (CLASSIFICATIONS). Si on change
     un emoji/label/couleur ici, le changer aussi la-bas pour coherence. */
  var CLASSIFICATIONS = {
    always_planar:     { emoji: '\uD83D\uDFE2', label: 'Toujours plan',     short: 'Tjrs pl.',      color: '#1a7f37' },
    mostly_planar:     { emoji: '\uD83D\uDFE1', label: 'Majorit. plan',     short: 'Maj. pl.',      color: '#6fb347' },
    unstable:          { emoji: '\uD83D\uDFE0', label: 'Instable',          short: 'Instable',      color: '#e66f00' },
    mostly_non_planar: { emoji: '\uD83D\uDD34', label: 'Majorit. non-plan', short: 'Maj. non pl.',  color: '#c72d0f' },
    always_non_planar: { emoji: '\u26AB',       label: 'Toujours non-plan', short: 'Tjrs non pl.',  color: '#cf222e' },
    ambiguous:         { emoji: '\u26AA',       label: 'Ambigu',            short: 'Ambigu',        color: '#6a737d' },
  };

  /* Groupes de stabilite utilises pour les cards et le filtre (aggregats). */
  var STABLE_PLANAR = { always_planar: 1, mostly_planar: 1 };
  var UNSTABLE = { unstable: 1 };
  var STABLE_NON_PLANAR = { always_non_planar: 1, mostly_non_planar: 1 };

  /* ---- Rendu du badge classification ---- */
  function renderStabilityBadge(classKey) {
    var c = CLASSIFICATIONS[classKey] || CLASSIFICATIONS.ambiguous;
    return '<span class="stab-badge" style="background:' + c.color + '"' +
           ' title="' + c.label + '">' + c.emoji + ' ' + c.short + '</span>';
  }

  /* ---- Couleur absolue a un angle donne (dégradé vert->jaune->orange->rouge) ---- */
  function _colorAtAngle(angle) {
    /* Stops : [angle_deg, [r,g,b]] */
    var stops = [
      [0,   [26, 127, 55]],   // vert #1a7f37
      [5,   [125, 214, 142]], // vert clair
      [10,  [244, 211, 94]],  // jaune (seuil)
      [20,  [239, 131, 84]],  // orange
      [30,  [207, 34, 46]],   // rouge #cf222e
    ];
    if (angle <= stops[0][0]) return _rgb(stops[0][1]);
    if (angle >= stops[stops.length - 1][0]) return _rgb(stops[stops.length - 1][1]);
    for (var i = 0; i < stops.length - 1; i++) {
      if (angle <= stops[i + 1][0]) {
        var t = (angle - stops[i][0]) / (stops[i + 1][0] - stops[i][0]);
        return _rgb([
          Math.round(stops[i][1][0] * (1 - t) + stops[i + 1][1][0] * t),
          Math.round(stops[i][1][1] * (1 - t) + stops[i + 1][1][1] * t),
          Math.round(stops[i][1][2] * (1 - t) + stops[i + 1][1][2] * t),
        ]);
      }
    }
    return _rgb(stops[stops.length - 1][1]);
  }
  function _rgb(arr) { return 'rgb(' + arr[0] + ',' + arr[1] + ',' + arr[2] + ')'; }

  /* Compteur monotone pour ids de gradients SVG (eviter collisions). */
  var _svgCounter = 0;

  /* ---- SVG barre de dispersion (adaptative) ----
     xmax = max(12, angle_max * 1.1) garde toujours le seuil 10° visible.
     Degrade fixe sur l'echelle absolue d'angle, pas sur la plage locale. */
  function renderDispersionBarSVG(runs) {
    var W = 180, H = 22, padL = 2, padR = 2;
    var innerW = W - padL - padR;
    var xmax = Math.max(12, runs.angle_max * 1.1);
    var toX = function (a) { return padL + Math.max(0, Math.min(1, a / xmax)) * innerW; };
    var gid = 'dbg' + (++_svgCounter);

    /* Gradient : 5 stops equidistants, couleur calculee pour l'angle a ce %. */
    var gradStops = '';
    [0, 0.25, 0.5, 0.75, 1.0].forEach(function (p) {
      gradStops += '<stop offset="' + (p * 100) + '%" stop-color="' + _colorAtAngle(p * xmax) + '"/>';
    });

    var parts = [];
    parts.push('<svg class="dispersion-bar" viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg">');
    parts.push('<defs><linearGradient id="' + gid + '" x1="0" x2="1" y1="0" y2="0">' + gradStops + '</linearGradient></defs>');
    parts.push('<rect x="' + padL + '" y="5" width="' + innerW + '" height="13" fill="url(#' + gid + ')" rx="2"/>');

    /* Ligne du seuil 10° (toujours visible puisque xmax >= 12). */
    var tx = toX(10);
    parts.push('<line x1="' + tx.toFixed(1) + '" y1="3" x2="' + tx.toFixed(1) + '" y2="20" stroke="#2d3436" stroke-width="1" stroke-dasharray="2,2" opacity="0.7"/>');

    /* Ticks par run individuel. */
    runs.angles.forEach(function (a) {
      var x = toX(a);
      parts.push('<line x1="' + x.toFixed(1) + '" y1="7" x2="' + x.toFixed(1) + '" y2="16" stroke="#1a1f24" stroke-width="0.9" opacity="0.55"/>');
    });

    /* Marqueur mu : cercle bleu avec contour blanc. */
    var mx = toX(runs.angle_mean);
    parts.push('<circle cx="' + mx.toFixed(1) + '" cy="11" r="3.2" fill="#0969da" stroke="#fff" stroke-width="1.1"/>');

    parts.push('</svg>');
    return parts.join('');
  }

  /* ---- Bloc complet d'une solution multi-runs (a mettre dans un <td colspan=N>) ----
     Contenu : lien fichier, badge, %, stats mu±sigma, barre SVG, range min-max. */
  function renderSolutionMultiRun(sol, hrefBase) {
    var r = sol.runs;
    var href = hrefBase + '/' + sol.file;
    var badge = renderStabilityBadge(r.classification);
    var bar = renderDispersionBarSVG(r);
    return (
      '<a class="sol-link" href="' + href + '" target="_blank">' + (sol.sizes || sol.file) + '</a>' +
      badge +
      '<span class="stab-pct">' + r.planar_count + '/' + r.n + '</span>' +
      '<span class="stab-stats">&mu;=' + r.angle_mean + '&deg; <small>&plusmn;' + r.angle_std + '&deg;</small></span>' +
      bar +
      '<span class="stab-range">' + r.angle_min + '&deg;\u2013' + r.angle_max + '&deg;</span>'
    );
  }

  /* Classe une solution dans un des 3 groupes pour cards/filtres ('stable_planar',
     'unstable', 'stable_non_planar'), ou null si pas de runs/ambigu. */
  function stabilityGroup(sol) {
    if (!sol.runs) return null;
    var c = sol.runs.classification;
    if (STABLE_PLANAR[c])     return 'stable_planar';
    if (UNSTABLE[c])          return 'unstable';
    if (STABLE_NON_PLANAR[c]) return 'stable_non_planar';
    return null;
  }

  /* ---- Config selection ---- */
  function selectConfig(name) {
    if (state.compareMode) {
      var idx = state.selectedConfigs.indexOf(name);
      if (idx >= 0) state.selectedConfigs.splice(idx, 1);
      else state.selectedConfigs.push(name);
      document.querySelectorAll('.cfg-btn').forEach(function (b) {
        b.classList.toggle('active', state.selectedConfigs.indexOf(b.dataset.cfg) >= 0);
      });
      renderComparison();
    } else {
      state.currentConfig = name;
      state.selectedConfigs = [name];
      document.querySelectorAll('.cfg-btn').forEach(function (b) {
        b.classList.toggle('active', b.dataset.cfg === name);
      });
      render(state.ALL_CONFIGS[name]);
    }
  }

  /* ---- Data pipeline: build, filter, sort ----
     Tous consomment/produisent un tableau de "row objects" pour permettre
     des transformations empilables (filter puis sort).
     Lorsqu'au moins une solution a un bloc 'runs', on compte aussi les
     groupes de stabilite (stab*) pour les cards et le filtrage. */
  function buildRows(data) {
    var mols = data.molecules;
    var rows = [];
    Object.keys(mols).forEach(function (name) {
      var m = mols[name];
      var nP = 0, nN = 0, maxA = 0;
      var stabCount = { stable_planar: 0, unstable: 0, stable_non_planar: 0, other: 0 };
      var hasRuns = false;
      m.solutions.forEach(function (s) {
        if (s.planar) nP++; else nN++;
        if (s.angle_deg > maxA) maxA = s.angle_deg;
        if (s.runs) {
          hasRuns = true;
          var g = stabilityGroup(s);
          if (g) stabCount[g]++;
          else   stabCount.other++;
        }
      });
      rows.push({
        name: name, mol: m,
        origPlanar: m.original ? m.original.planar : null,
        origAngle: m.original ? m.original.angle_deg : null,
        numSol: m.solutions.length, numPlan: nP, numNon: nN, maxAngle: maxA,
        hasRuns: hasRuns, stabCount: stabCount,
      });
    });
    return rows;
  }

  /* Est-ce que TOUTES les rows ont des runs ? (controle si on montre
     cards de stabilite / filtre stabilite). Meme si juste une partie a des
     runs, on les compte : l'utilisateur veut les voir. */
  function anyHasRuns(rows) {
    for (var i = 0; i < rows.length; i++) if (rows[i].hasRuns) return true;
    return false;
  }

  function filterRows(rows) {
    if (state.searchQuery) {
      var q = state.searchQuery.toLowerCase();
      rows = rows.filter(function (r) { return r.name.toLowerCase().indexOf(q) >= 0; });
    }
    if (state.filterOrig === 'planar')         rows = rows.filter(function (r) { return r.origPlanar === true; });
    else if (state.filterOrig === 'nonplanar') rows = rows.filter(function (r) { return r.origPlanar === false; });
    if (state.filterSol === 'planar')          rows = rows.filter(function (r) { return r.numPlan > 0; });
    else if (state.filterSol === 'nonplanar')  rows = rows.filter(function (r) { return r.numNon > 0; });
    /* Filtre stabilite : molecule retenue si au moins une de ses solutions
       tombe dans le groupe choisi (stable_planar / unstable / stable_non_planar). */
    if (state.filterStab !== 'all') {
      rows = rows.filter(function (r) { return r.stabCount && r.stabCount[state.filterStab] > 0; });
    }
    return rows;
  }

  function sortRows(rows) {
    rows.sort(function (a, b) {
      var va, vb;
      switch (state.sortCol) {
        case 'name': return state.sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        case 'original':
          va = a.origPlanar === true ? 1 : (a.origPlanar === false ? -1 : 0);
          vb = b.origPlanar === true ? 1 : (b.origPlanar === false ? -1 : 0); break;
        case 'solutions': va = a.numSol; vb = b.numSol; break;
        case 'planar':    va = a.numPlan; vb = b.numPlan; break;
        case 'angle':     va = a.maxAngle; vb = b.maxAngle; break;
        default:          va = a.name; vb = b.name;
      }
      var c = (va < vb) ? -1 : (va > vb) ? 1 : 0;
      return state.sortAsc ? c : -c;
    });
    return rows;
  }

  /* ---- Main render (single config) ---- */
  function render(data) {
    var cfg = data.config || state.currentConfig;
    var allRows = buildRows(data);
    var rows = sortRows(filterRows(allRows.slice()));
    var showStab = anyHasRuns(allRows);

    /* Stats sur TOUTES les lignes (non filtrees) -- les cards montrent
       l'ensemble, pas le sous-ensemble filtre. */
    var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0, nPlan = 0, nNon = 0;
    var nStabPl = 0, nUnst = 0, nStabNon = 0;
    allRows.forEach(function (r) {
      if (r.origPlanar === true) nOrigP++;
      else if (r.origPlanar === false) nOrigN++;
      nSol += r.numSol; nPlan += r.numPlan; nNon += r.numNon;
      if (r.hasRuns) {
        nStabPl  += r.stabCount.stable_planar;
        nUnst    += r.stabCount.unstable;
        nStabNon += r.stabCount.stable_non_planar;
      }
    });

    var badge = rows.length < allRows.length
      ? '<span class="count-badge">(' + rows.length + '/' + allRows.length + ')</span>' : '';

    /* Cards : 4 communes + (3 stabilite SI runs presents SINON 2 anciennes). */
    var cardsHtml =
      '<div class="card blue"><div class="value">' + nMol + '</div><div class="label">Molecules' + badge + '</div></div>' +
      '<div class="card green"><div class="value">' + nOrigP + '</div><div class="label">Originaux plans</div></div>' +
      '<div class="card red"><div class="value">' + nOrigN + '</div><div class="label">Originaux non plans</div></div>' +
      '<div class="card blue"><div class="value">' + nSol + '</div><div class="label">Solutions CSP</div></div>';
    if (showStab) {
      cardsHtml +=
        '<div class="card green"><div class="value">' + nStabPl  + '</div><div class="label">\uD83D\uDFE2 Stables planes</div></div>' +
        '<div class="card" style="border-top-color:#e66f00"><div class="value" style="color:#e66f00">' + nUnst + '</div><div class="label">\uD83D\uDFE0 Instables</div></div>' +
        '<div class="card red"><div class="value">' + nStabNon + '</div><div class="label">\u26AB Stables non planes</div></div>';
    } else {
      cardsHtml +=
        '<div class="card green"><div class="value">' + nPlan + '</div><div class="label">Solutions planes</div></div>' +
        '<div class="card red"><div class="value">' + nNon  + '</div><div class="label">Solutions non planes</div></div>';
    }
    document.getElementById('cards').innerHTML = cardsHtml;

    var html = '';
    rows.forEach(function (r) {
      var m = r.mol;
      var origCell;
      if (m.original) {
        var cls = m.original.planar ? 'planar' : 'non-planar';
        var txt = m.original.planar ? 'PLAN' : 'NON PLAN';
        origCell = '<span class="' + cls + '">' + txt + '</span> (' + m.original.angle_deg + '&deg;)';
      } else {
        origCell = '<span class="na">-</span>';
      }

      var solCell = r.numSol === 0
        ? '<span class="na">-</span>'
        : r.numSol + ' solution' + (r.numSol > 1 ? 's' : '');

      var planCell;
      if (r.numSol === 0) {
        planCell = '<span class="na">-</span>';
      } else {
        planCell = '<span class="planar">' + r.numPlan + ' plan</span>';
        if (r.numNon > 0) planCell += ', <span class="non-planar">' + r.numNon + ' non</span>';
      }

      var angleCell = r.numSol > 0 ? r.maxAngle + '&deg;' : '<span class="na">-</span>';
      var isExp = state.expandedMols[r.name] ? ' expanded' : '';

      html += '<tr class="mol-row' + isExp + '" data-mol="' + r.name + '" onclick="toggleDetails(\'' + r.name + '\')">' +
        '<td class="mol-name"><span class="expand-icon">&#9654;</span> ' + r.name + '</td>' +
        '<td>' + origCell + '</td>' +
        '<td>' + solCell + '</td>' +
        '<td>' + planCell + '</td>' +
        '<td>' + angleCell + '</td>' +
        '</tr>\n';

      var hrefBase = cfg + '/' + r.name + '/solutions';
      m.solutions.forEach(function (s) {
        var disp = state.expandedMols[r.name] ? 'table-row' : 'none';
        var rowInner;
        if (s.runs) {
          /* Multi-runs : cellule unique colspan=5 avec bloc structure. */
          rowInner = '<td colspan="5" class="solution-multirun">' +
            renderSolutionMultiRun(s, hrefBase) + '</td>';
        } else {
          /* Single-run classique (retrocompat). */
          var scls = s.planar ? 'planar' : 'non-planar';
          var stxt = s.planar ? 'PLAN' : 'NON PLAN';
          var href = hrefBase + '/' + s.file;
          rowInner = '<td></td><td></td>' +
            '<td class="sizes"><a href="' + href + '" target="_blank">' + (s.sizes || s.file) + '</a></td>' +
            '<td><span class="' + scls + '">' + stxt + '</span></td>' +
            '<td>' + s.angle_deg + '&deg;</td>';
        }
        html += '<tr class="detail-row" data-parent="' + r.name + '" style="display:' + disp + ';">' +
          rowInner + '</tr>\n';
      });
    });

    document.getElementById('tbody').innerHTML = html;
  }

  /* ---- Expand / Collapse ---- */
  function toggleDetails(name) {
    state.expandedMols[name] = !state.expandedMols[name];
    document.querySelectorAll('.detail-row[data-parent="' + name + '"]').forEach(function (row) {
      row.style.display = state.expandedMols[name] ? 'table-row' : 'none';
    });
    /* Rotation du chevron dans toutes les mol-rows (normal + panneaux compare). */
    document.querySelectorAll('.mol-row[data-mol="' + name + '"]').forEach(function (row) {
      row.classList.toggle('expanded', state.expandedMols[name]);
    });
  }

  function expandAll() {
    document.querySelectorAll('.mol-row').forEach(function (r) {
      r.classList.add('expanded');
      state.expandedMols[r.dataset.mol] = true;
    });
    document.querySelectorAll('.detail-row').forEach(function (r) { r.style.display = 'table-row'; });
  }

  function collapseAll() {
    document.querySelectorAll('.mol-row').forEach(function (r) { r.classList.remove('expanded'); });
    document.querySelectorAll('.detail-row').forEach(function (r) { r.style.display = 'none'; });
    state.expandedMols = {};
  }

  /* ---- Sort ---- */
  function sortTable(col) {
    if (state.sortCol === col) state.sortAsc = !state.sortAsc;
    else { state.sortCol = col; state.sortAsc = true; }
    /* Re-render complet : le mode compare regenere aussi les th des panneaux. */
    if (state.compareMode) renderComparison();
    else {
      document.querySelectorAll('th.sortable').forEach(function (th) {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === col) th.classList.add(state.sortAsc ? 'sort-asc' : 'sort-desc');
      });
      if (state.currentConfig) render(state.ALL_CONFIGS[state.currentConfig]);
    }
  }

  /* ---- Filters ---- */
  function setFilter(group, value) {
    if (group === 'orig')      state.filterOrig = value;
    else if (group === 'sol')  state.filterSol = value;
    else if (group === 'stab') state.filterStab = value;
    /* Meme data-filter present dans les 2 toolbars (normal + compare) --
       un seul appel met a jour les deux. */
    document.querySelectorAll('.filter-btn').forEach(function (b) {
      var f = b.dataset.filter;
      if (f && f.indexOf(group + '-') === 0) b.classList.toggle('active', f === group + '-' + value);
    });
    applyFilters();
  }

  function setCompareFilter(value) {
    state.compareFilter = value;
    document.querySelectorAll('[data-filter^="diff-"]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.filter === 'diff-' + value);
    });
    renderComparison();
  }

  function applyFilters() {
    var inputId = state.compareMode ? 'compareSearchInput' : 'searchInput';
    state.searchQuery = document.getElementById(inputId).value;
    if (state.compareMode) renderComparison();
    else if (state.currentConfig) render(state.ALL_CONFIGS[state.currentConfig]);
  }

  /* ---- Comparison mode ---- */
  function toggleCompareMode() {
    state.compareMode = !state.compareMode;
    var btn = document.getElementById('compareModeBtn');
    btn.classList.toggle('active', state.compareMode);
    btn.textContent = state.compareMode ? 'Comparer (ON)' : 'Comparer';

    if (state.compareMode) {
      document.getElementById('normalView').style.display = 'none';
      document.getElementById('compareView').style.display = 'block';
      if (state.currentConfig && state.selectedConfigs.indexOf(state.currentConfig) < 0) {
        state.selectedConfigs = [state.currentConfig];
      }
      renderComparison();
    } else {
      document.getElementById('normalView').style.display = 'block';
      document.getElementById('compareView').style.display = 'none';
      if (state.selectedConfigs.length > 0) {
        state.currentConfig = state.selectedConfigs[0];
        state.selectedConfigs = [state.currentConfig];
      }
      document.querySelectorAll('.cfg-btn').forEach(function (b) {
        b.classList.toggle('active', b.dataset.cfg === state.currentConfig);
      });
      if (state.currentConfig) render(state.ALL_CONFIGS[state.currentConfig]);
    }
  }

  /* Detecte les molecules dont la planarite, le ratio plan/total, ou la
     classification multi-runs differe entre les configs selectionnees (ou
     qui sont absentes de certaines). Ces lignes seront highlightees. */
  function computeDiffMols(cfgs) {
    var allNames = {};
    cfgs.forEach(function (cfgName) {
      Object.keys(state.ALL_CONFIGS[cfgName].molecules).forEach(function (n) { allNames[n] = true; });
    });
    var diffMols = {};
    Object.keys(allNames).forEach(function (name) {
      var planarities = [], solRatios = [], classSigs = [];
      var hasMissing = false, hasPresent = false;
      cfgs.forEach(function (cfgName) {
        var mol = state.ALL_CONFIGS[cfgName].molecules[name];
        if (!mol) { hasMissing = true; return; }
        hasPresent = true;
        planarities.push(mol.original ? mol.original.planar : null);
        var np = 0, classes = [];
        mol.solutions.forEach(function (s) {
          if (s.planar) np++;
          classes.push(s.runs ? s.runs.classification : '-');
        });
        solRatios.push(np + '/' + mol.solutions.length);
        /* Signature classification : concat triee (taille independante de l'ordre). */
        classSigs.push(classes.slice().sort().join(','));
      });
      var hasDiff = hasMissing && hasPresent;
      if (!hasDiff && planarities.length > 1) {
        for (var i = 1; i < planarities.length; i++) {
          if (planarities[i] !== planarities[0]) { hasDiff = true; break; }
        }
      }
      if (!hasDiff && solRatios.length > 1) {
        for (var j = 1; j < solRatios.length; j++) {
          if (solRatios[j] !== solRatios[0]) { hasDiff = true; break; }
        }
      }
      /* Diff de classification : si au moins 2 configs ont des runs et
         leur signature classification differe, on highlight. */
      if (!hasDiff && classSigs.length > 1) {
        for (var k = 1; k < classSigs.length; k++) {
          if (classSigs[k] !== classSigs[0]) { hasDiff = true; break; }
        }
      }
      diffMols[name] = hasDiff;
    });
    return diffMols;
  }

  function buildPanel(cfgName, diffMols) {
    var data = state.ALL_CONFIGS[cfgName];
    var allRows = buildRows(data);
    var rows = sortRows(filterRows(allRows.slice()));
    var showStab = anyHasRuns(allRows);

    if (state.compareFilter === 'diff') {
      rows = rows.filter(function (r) { return diffMols[r.name]; });
    }

    var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0, nPlan = 0, nNon = 0;
    var nStabPl = 0, nUnst = 0, nStabNon = 0;
    allRows.forEach(function (r) {
      if (r.origPlanar === true) nOrigP++;
      else if (r.origPlanar === false) nOrigN++;
      nSol += r.numSol; nPlan += r.numPlan; nNon += r.numNon;
      if (r.hasRuns) {
        nStabPl  += r.stabCount.stable_planar;
        nUnst    += r.stabCount.unstable;
        nStabNon += r.stabCount.stable_non_planar;
      }
    });

    var html = '<div class="compare-panel" data-panel-cfg="' + cfgName + '">';
    html += '<div class="panel-header">' + cfgName + '</div>';
    html += '<div class="panel-cards">' +
      '<div class="mini-card blue"><div class="v">' + nMol   + '</div><div class="l">Molecules</div></div>' +
      '<div class="mini-card green"><div class="v">' + nOrigP + '</div><div class="l">Orig. plans</div></div>' +
      '<div class="mini-card red"><div class="v">' + nOrigN  + '</div><div class="l">Orig. non pl.</div></div>' +
      '<div class="mini-card blue"><div class="v">' + nSol   + '</div><div class="l">Solutions</div></div>';
    if (showStab) {
      html +=
        '<div class="mini-card green"><div class="v">' + nStabPl  + '</div><div class="l">\uD83D\uDFE2 Stables pl.</div></div>' +
        '<div class="mini-card" style="border-top-color:#e66f00"><div class="v" style="color:#e66f00">' + nUnst + '</div><div class="l">\uD83D\uDFE0 Instables</div></div>' +
        '<div class="mini-card red"><div class="v">' + nStabNon + '</div><div class="l">\u26AB Stables non</div></div>';
    } else {
      html +=
        '<div class="mini-card green"><div class="v">' + nPlan + '</div><div class="l">Sol. planes</div></div>' +
        '<div class="mini-card red"><div class="v">'   + nNon  + '</div><div class="l">Sol. non pl.</div></div>';
    }
    html += '</div>';

    function thClass(col) {
      return 'sortable' + (state.sortCol === col ? (state.sortAsc ? ' sort-asc' : ' sort-desc') : '');
    }
    html += '<table class="panel-table"><thead><tr>' +
      '<th class="' + thClass('name')      + '" data-sort="name"      onclick="sortTable(\'name\')">Molecule</th>' +
      '<th class="' + thClass('original')  + '" data-sort="original"  onclick="sortTable(\'original\')">Orig.</th>' +
      '<th class="' + thClass('solutions') + '" data-sort="solutions" onclick="sortTable(\'solutions\')">Sol.</th>' +
      '<th class="' + thClass('angle')     + '" data-sort="angle"     onclick="sortTable(\'angle\')">Angle</th>' +
      '</tr></thead><tbody>';

    if (rows.length === 0) {
      html += '<tr class="na-row"><td colspan="4">Aucune molecule</td></tr>';
    }

    rows.forEach(function (r) {
      var m = r.mol;
      var diffCls = diffMols[r.name] ? ' diff-highlight' : '';
      var expCls = state.expandedMols[r.name] ? ' expanded' : '';
      var diffBadge = diffMols[r.name] ? '<span class="diff-badge">diff</span>' : '';

      var origCell;
      if (m.original) {
        var cls = m.original.planar ? 'planar' : 'non-planar';
        var txt = m.original.planar ? 'PLAN' : 'NON';
        origCell = '<span class="' + cls + '">' + txt + '</span> <small>(' + m.original.angle_deg + '&deg;)</small>';
      } else {
        origCell = '<span class="na">-</span>';
      }

      var solCell;
      if (r.numSol === 0) {
        solCell = '<span class="na">-</span>';
      } else {
        solCell = r.numSol + ' <small>(<span class="planar">' + r.numPlan + '</span>';
        if (r.numNon > 0) solCell += '/<span class="non-planar">' + r.numNon + '</span>';
        solCell += ')</small>';
      }
      var angleCell = r.numSol > 0 ? r.maxAngle + '&deg;' : '<span class="na">-</span>';

      html += '<tr class="mol-row' + expCls + diffCls + '" data-mol="' + r.name + '" onclick="toggleDetails(\'' + r.name + '\')">' +
        '<td class="mol-name"><span class="expand-icon">&#9654;</span> ' + r.name + diffBadge + '</td>' +
        '<td>' + origCell + '</td>' +
        '<td>' + solCell + '</td>' +
        '<td>' + angleCell + '</td>' +
        '</tr>';

      var disp = state.expandedMols[r.name] ? 'table-row' : 'none';
      var hrefBase = cfgName + '/' + r.name + '/solutions';
      m.solutions.forEach(function (s) {
        var rowInner;
        if (s.runs) {
          rowInner = '<td colspan="4" class="solution-multirun">' +
            renderSolutionMultiRun(s, hrefBase) + '</td>';
        } else {
          var scls = s.planar ? 'planar' : 'non-planar';
          var stxt = s.planar ? 'PLAN' : 'NON';
          var href = hrefBase + '/' + s.file;
          rowInner = '<td class="sizes"><a href="' + href + '" target="_blank">' + (s.sizes || s.file) + '</a></td>' +
            '<td colspan="2"><span class="' + scls + '">' + stxt + '</span></td>' +
            '<td>' + s.angle_deg + '&deg;</td>';
        }
        html += '<tr class="detail-row" data-parent="' + r.name + '" style="display:' + disp + ';">' +
          rowInner + '</tr>';
      });
    });

    html += '</tbody></table></div>';
    return html;
  }

  function renderComparison() {
    var cfgs = state.selectedConfigs;
    var container = document.getElementById('comparePanels');
    if (cfgs.length === 0) {
      container.innerHTML = '<div class="compare-empty">Selectionnez au moins une configuration dans la barre du haut.</div>';
      return;
    }
    var diffMols = computeDiffMols(cfgs);
    var html = '';
    cfgs.forEach(function (cfgName) { html += buildPanel(cfgName, diffMols); });
    container.innerHTML = html;
  }

  /* ---- Keyboard shortcuts ---- */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') collapseAll();
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      var el = document.getElementById(state.compareMode ? 'compareSearchInput' : 'searchInput');
      if (el) el.focus();
    }
  });

  /* ---- Expose onclick handlers (le HTML les appelle inline) ---- */
  window.selectConfig      = selectConfig;
  window.toggleDetails     = toggleDetails;
  window.toggleCompareMode = toggleCompareMode;
  window.sortTable         = sortTable;
  window.setFilter         = setFilter;
  window.setCompareFilter  = setCompareFilter;
  window.applyFilters      = applyFilters;
  window.expandAll         = expandAll;
  window.collapseAll       = collapseAll;

  /* ---- Init : charger la premiere config ---- */
  var firstConfig = Object.keys(state.ALL_CONFIGS).sort()[0];
  if (firstConfig) selectConfig(firstConfig);
})();
