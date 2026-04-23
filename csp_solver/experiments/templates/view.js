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
    searchQuery: '',
    /* expandedMols est partage entre la vue simple et la vue comparaison :
       le meme selecteur CSS [data-parent="X"] matche dans les deux, donc
       un toggle dans un panneau deplie la molecule dans tous. Voulu. */
    expandedMols: {},
    compareFilter: 'all',  // 'all' | 'diff'
  };

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
     des transformations empilables (filter puis sort). */
  function buildRows(data) {
    var mols = data.molecules;
    var rows = [];
    Object.keys(mols).forEach(function (name) {
      var m = mols[name];
      var nP = 0, nN = 0, maxA = 0;
      m.solutions.forEach(function (s) {
        if (s.planar) nP++; else nN++;
        if (s.angle_deg > maxA) maxA = s.angle_deg;
      });
      rows.push({
        name: name, mol: m,
        origPlanar: m.original ? m.original.planar : null,
        origAngle: m.original ? m.original.angle_deg : null,
        numSol: m.solutions.length, numPlan: nP, numNon: nN, maxAngle: maxA
      });
    });
    return rows;
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

    /* Stats sur TOUTES les lignes (non filtrees) -- les cards montrent
       l'ensemble, pas le sous-ensemble filtre. */
    var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0, nPlan = 0, nNon = 0;
    allRows.forEach(function (r) {
      if (r.origPlanar === true) nOrigP++;
      else if (r.origPlanar === false) nOrigN++;
      nSol += r.numSol; nPlan += r.numPlan; nNon += r.numNon;
    });

    var badge = rows.length < allRows.length
      ? '<span class="count-badge">(' + rows.length + '/' + allRows.length + ')</span>' : '';

    document.getElementById('cards').innerHTML =
      '<div class="card blue"><div class="value">' + nMol + '</div><div class="label">Molecules' + badge + '</div></div>' +
      '<div class="card green"><div class="value">' + nOrigP + '</div><div class="label">Originaux plans</div></div>' +
      '<div class="card red"><div class="value">' + nOrigN + '</div><div class="label">Originaux non plans</div></div>' +
      '<div class="card blue"><div class="value">' + nSol + '</div><div class="label">Solutions CSP</div></div>' +
      '<div class="card green"><div class="value">' + nPlan + '</div><div class="label">Solutions planes</div></div>' +
      '<div class="card red"><div class="value">' + nNon + '</div><div class="label">Solutions non planes</div></div>';

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

      m.solutions.forEach(function (s) {
        var scls = s.planar ? 'planar' : 'non-planar';
        var stxt = s.planar ? 'PLAN' : 'NON PLAN';
        var href = cfg + '/' + r.name + '/solutions/' + s.file;
        var disp = state.expandedMols[r.name] ? 'table-row' : 'none';
        html += '<tr class="detail-row" data-parent="' + r.name + '" style="display:' + disp + ';">' +
          '<td></td><td></td>' +
          '<td class="sizes"><a href="' + href + '" target="_blank">' + (s.sizes || s.file) + '</a></td>' +
          '<td><span class="' + scls + '">' + stxt + '</span></td>' +
          '<td>' + s.angle_deg + '&deg;</td>' +
          '</tr>\n';
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
    if (group === 'orig') state.filterOrig = value;
    else if (group === 'sol') state.filterSol = value;
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

  /* Detecte les molecules dont la planarite ou le ratio plan/total
     differe entre les configs selectionnees (ou qui sont absentes de
     certaines configs). Ces lignes seront highlightees. */
  function computeDiffMols(cfgs) {
    var allNames = {};
    cfgs.forEach(function (cfgName) {
      Object.keys(state.ALL_CONFIGS[cfgName].molecules).forEach(function (n) { allNames[n] = true; });
    });
    var diffMols = {};
    Object.keys(allNames).forEach(function (name) {
      var planarities = [], solRatios = [];
      var hasMissing = false, hasPresent = false;
      cfgs.forEach(function (cfgName) {
        var mol = state.ALL_CONFIGS[cfgName].molecules[name];
        if (!mol) { hasMissing = true; return; }
        hasPresent = true;
        planarities.push(mol.original ? mol.original.planar : null);
        var np = 0;
        mol.solutions.forEach(function (s) { if (s.planar) np++; });
        solRatios.push(np + '/' + mol.solutions.length);
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
      diffMols[name] = hasDiff;
    });
    return diffMols;
  }

  function buildPanel(cfgName, diffMols) {
    var data = state.ALL_CONFIGS[cfgName];
    var allRows = buildRows(data);
    var rows = sortRows(filterRows(allRows.slice()));

    if (state.compareFilter === 'diff') {
      rows = rows.filter(function (r) { return diffMols[r.name]; });
    }

    var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0, nPlan = 0, nNon = 0;
    allRows.forEach(function (r) {
      if (r.origPlanar === true) nOrigP++;
      else if (r.origPlanar === false) nOrigN++;
      nSol += r.numSol; nPlan += r.numPlan; nNon += r.numNon;
    });

    var html = '<div class="compare-panel" data-panel-cfg="' + cfgName + '">';
    html += '<div class="panel-header">' + cfgName + '</div>';
    html += '<div class="panel-cards">' +
      '<div class="mini-card blue"><div class="v">' + nMol   + '</div><div class="l">Molecules</div></div>' +
      '<div class="mini-card green"><div class="v">' + nOrigP + '</div><div class="l">Orig. plans</div></div>' +
      '<div class="mini-card red"><div class="v">' + nOrigN  + '</div><div class="l">Orig. non pl.</div></div>' +
      '<div class="mini-card blue"><div class="v">' + nSol   + '</div><div class="l">Solutions</div></div>' +
      '<div class="mini-card green"><div class="v">' + nPlan  + '</div><div class="l">Sol. planes</div></div>' +
      '<div class="mini-card red"><div class="v">' + nNon    + '</div><div class="l">Sol. non pl.</div></div>' +
      '</div>';

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
      m.solutions.forEach(function (s) {
        var scls = s.planar ? 'planar' : 'non-planar';
        var stxt = s.planar ? 'PLAN' : 'NON';
        var href = cfgName + '/' + r.name + '/solutions/' + s.file;
        html += '<tr class="detail-row" data-parent="' + r.name + '" style="display:' + disp + ';">' +
          '<td class="sizes"><a href="' + href + '" target="_blank">' + (s.sizes || s.file) + '</a></td>' +
          '<td colspan="2"><span class="' + scls + '">' + stxt + '</span></td>' +
          '<td>' + s.angle_deg + '&deg;</td>' +
          '</tr>';
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
