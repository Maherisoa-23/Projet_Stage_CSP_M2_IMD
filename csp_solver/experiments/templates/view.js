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
    filterVerdict: 'all',  // 'all' | 'plane' | 'autres' | 'nonplane' (3 buckets unifies)
    searchQuery: '',
    /* expandedMols est partage entre la vue simple et la vue comparaison :
       le meme selecteur CSS [data-parent="X"] matche dans les deux, donc
       un toggle dans un panneau deplie la molecule dans tous. Voulu. */
    expandedMols: {},
    compareFilter: 'all',  // 'all' | 'diff'
    /* Methode de validation active (toggle UI). Calcule a l'init :
       'multi-runs' si seul ce bloc est present, 'md' si seul md, 'both'
       par defaut quand les 2 sont disponibles. */
    activeMethod: 'multi-runs',
    availableMethods: [],  // ['multi-runs'] | ['md'] | ['multi-runs', 'md']
  };

  /* Detecte les methodes disponibles globalement (presence d'au moins une
     solution avec le bloc correspondant). Calcule une fois a l'init. */
  function detectAvailableMethods(allConfigs) {
    var hasRuns = false, hasMD = false;
    var cfgs = Object.keys(allConfigs);
    for (var i = 0; i < cfgs.length && (!hasRuns || !hasMD); i++) {
      var mols = allConfigs[cfgs[i]].molecules;
      var molKeys = Object.keys(mols);
      for (var j = 0; j < molKeys.length && (!hasRuns || !hasMD); j++) {
        var sols = mols[molKeys[j]].solutions;
        for (var k = 0; k < sols.length; k++) {
          if (sols[k].runs) hasRuns = true;
          if (sols[k].md_validation) hasMD = true;
          if (hasRuns && hasMD) break;
        }
      }
    }
    var avail = [];
    if (hasRuns) avail.push('multi-runs');
    if (hasMD) avail.push('md');
    return avail;
  }

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

  /* === 3 BUCKETS unifies (vue simplifiee, demande utilisateur) ===
     - PLANE     : always_planar + mostly_planar (MR), md.planar=true (MD)
     - NON_PLANE : always_non_planar + mostly_non_planar (MR), md.planar=false (MD)
     - AUTRES    : unstable + ambiguous (MR), ou desaccord MR vs MD en mode "both"
     Les sous-categories (toujours/majoritairement) restent visibles dans la
     ligne detail depliee, via les badges existants. */
  var BUCKETS = {
    PLANE:     { label: 'Plan',     color: '#1a7f37', bg: '#dafbe1', emoji: '🟢' },
    AUTRES:    { label: 'Autres',   color: '#bf8700', bg: '#fff8c5', emoji: '🟡' },
    NON_PLANE: { label: 'Non plan', color: '#cf222e', bg: '#ffebe9', emoji: '⚫' },
  };

  function _classToBucket(cls) {
    if (cls === 'always_planar' || cls === 'mostly_planar') return 'PLANE';
    if (cls === 'always_non_planar' || cls === 'mostly_non_planar') return 'NON_PLANE';
    return 'AUTRES';
  }

  /* Bucket d'une solution selon la methode active.
     - "multi-runs" : depuis runs.classification (fallback sur sol.planar)
     - "md"         : depuis md_validation.planar (jamais AUTRES)
     - "both"       : si les 2 d'accord -> ce bucket ; sinon AUTRES */
  function solutionBucket(sol) {
    var meth = state.activeMethod;
    var hasMR = !!(sol.runs && sol.runs.classification);
    var hasMD = !!sol.md_validation;
    var mr = hasMR ? _classToBucket(sol.runs.classification) : null;
    var md = hasMD ? (sol.md_validation.planar ? 'PLANE' : 'NON_PLANE') : null;
    if (meth === 'multi-runs') {
      return mr || (sol.planar ? 'PLANE' : 'NON_PLANE');
    }
    if (meth === 'md') {
      return md || (sol.planar ? 'PLANE' : 'NON_PLANE');
    }
    /* both : consensus ou divergence */
    if (mr && md) {
      if (mr === md) return mr;
      /* Si l'un dit AUTRES et l'autre PLANE/NON_PLANE -> AUTRES (incertitude) */
      if (mr === 'AUTRES' || md === 'AUTRES') return 'AUTRES';
      return 'AUTRES';  /* desaccord franc plane vs non plane */
    }
    return mr || md || (sol.planar ? 'PLANE' : 'NON_PLANE');
  }

  /* Pill bucket : badge unique 3-couleurs affiche dans la "Planarite" mol-row.
     Dimension compacte. */
  function renderBucketPill(bucket, count) {
    var b = BUCKETS[bucket];
    return '<span class="bucket-pill" style="background:' + b.bg + ';color:' + b.color + ';border-color:' + b.color + '" title="' + b.label + '">'
         + (count !== undefined ? count + ' ' : '') + b.label + '</span>';
  }

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

  /* ---- SVG barre de dispersion (echelle fixe commune 0-30 deg) ----
     Echelle fixe : seuil 10° toujours au meme endroit visuellement (33.3%),
     comparable d'une solution a l'autre. Les rares angles > 30° sont
     signales par une fleche rouge au bord droit (debordement). */
  function renderDispersionBarSVG(runs) {
    var W = 260, H = 22, padL = 2, padR = 2;
    var innerW = W - padL - padR;
    var X_MAX_FIXED = 30;
    var xmax = X_MAX_FIXED;
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

    /* Indicateur de debordement : fleche rouge au bord droit si une valeur > xmax. */
    if (runs.angle_max > X_MAX_FIXED) {
      parts.push('<text x="' + (W - padR - 8) + '" y="16" fill="#cf222e" font-size="14" font-weight="700">&#9654;</text>');
    }

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

  /* ---- Bloc complet d'une solution MD (1 run deterministe + opt finale) ----
     Contenu : lien fichier final, badge planar/non-planar, angle, params MD. */
  function renderSolutionMD(sol, hrefBase) {
    var mv = sol.md_validation;
    /* Le final_opt_file est relatif au dossier solutions/sol_X/ ; on extrait
       sol_X depuis sol.file (qui pointe lui aussi dans sol_X/). */
    var solDir = (sol.file || '').split('/')[0];
    var finalRel = mv.final_opt_file || 'md_validation/md_final_opt.xyz';
    var trajRel = mv.trajectory_file || 'md_validation/md_traj.xyz';
    var hrefFinal = hrefBase + '/' + solDir + '/' + finalRel;
    var hrefTraj  = hrefBase + '/' + solDir + '/' + trajRel;

    var planarCls = mv.planar ? 'planar' : 'non-planar';
    var planarTxt = mv.planar ? 'PLAN' : 'NON PLAN';
    var p = mv.params || {};
    var meta = '';
    if (p.temp !== undefined && p.time !== undefined) {
      meta = '<span class="md-meta">T=' + p.temp + 'K, t=' + p.time + 'ps</span>';
    }
    return (
      '<a class="sol-link" href="' + hrefFinal + '" target="_blank">' + (sol.sizes || sol.file) + '</a>' +
      '<span class="md-badge ' + planarCls + '">' + planarTxt + '</span>' +
      '<span class="md-angle">angle=' + mv.angle_deg + '&deg;</span>' +
      meta +
      '<a class="md-traj-link" href="' + hrefTraj + '" target="_blank" title="Trajectoire MD">trajectoire</a>'
    );
  }

  /* Dispatcher : selon les blocs presents ET la methode active, render
     multi-runs et/ou md. Retourne le HTML interieur d'un <td> ; null si
     fallback single-run requis (aucun bloc enrichi present). */
  function renderSolutionDetail(sol, hrefBase) {
    var hasRuns = !!sol.runs;
    var hasMD = !!sol.md_validation;
    var meth = state.activeMethod;
    /* Filtre selon methode active : on n'affiche que ce que l'utilisateur a
       choisi via le toggle (ou les 2 si "both"). */
    var showRuns = hasRuns && (meth === 'multi-runs' || meth === 'both');
    var showMD   = hasMD   && (meth === 'md'         || meth === 'both');

    if (showRuns && showMD) {
      return (
        '<div class="method-block method-multiruns">' +
          '<span class="method-label">Multi-runs</span>' +
          renderSolutionMultiRun(sol, hrefBase) +
        '</div>' +
        '<div class="method-block method-md">' +
          '<span class="method-label">MD</span>' +
          renderSolutionMD(sol, hrefBase) +
        '</div>'
      );
    }
    if (showRuns) return renderSolutionMultiRun(sol, hrefBase);
    if (showMD)   return renderSolutionMD(sol, hrefBase);
    /* Si la methode active n'est pas dispo pour cette solution, on retombe
       sur l'autre methode si elle existe (mieux qu'une ligne vide). */
    if (hasRuns) return renderSolutionMultiRun(sol, hrefBase);
    if (hasMD)   return renderSolutionMD(sol, hrefBase);
    return null;  /* aucun bloc enrichi : single-run classique */
  }

  /* Mapping verdict (filtre Verdict) -> bucket. */
  var FILTER_TO_BUCKET = { plane: 'PLANE', autres: 'AUTRES', nonplane: 'NON_PLANE' };

  /* ==== Partition CSP : couverture des solutions entre configs ==== */

  /* Critere d'inclusion : on ne compte que les solutions vraiment plates.
     - Multi-runs : classe always_planar ou mostly_planar.
     - Single-run (h5 par ex.) : booleen sol.planar. */
  function isPlanarSolution(sol) {
    /* Critere depend de state.activeMethod :
         "multi-runs" : classe always_planar ou mostly_planar
         "md"         : md_validation.planar = true
         "both"       : planaire selon AU MOINS une des methodes (OR)
       Fallback (aucun bloc enrichi present) : booleen sol.planar. */
    var meth = state.activeMethod;
    var ranMR = !!(sol.runs && sol.runs.classification);
    var ranMD = !!sol.md_validation;
    if ((meth === 'multi-runs' || meth === 'both') && ranMR) {
      var c = sol.runs.classification;
      if (c === 'always_planar' || c === 'mostly_planar') return true;
      if (meth === 'multi-runs') return false;
    }
    if ((meth === 'md' || meth === 'both') && ranMD) {
      if (sol.md_validation.planar) return true;
      if (meth === 'md') return false;
    }
    if (!ranMR && !ranMD) return !!sol.planar;
    return false;
  }

  /* Calcule la partition des solutions planes entre les configs CSP.
     Identite d'une solution : (mol_name, sizes). Pure, pas d'effet de bord. */
  function computeCSPPartition(allConfigs) {
    var configNames = Object.keys(allConfigs).sort();
    var nConfigs = configNames.length;

    /* solConfigs : { "molName|sizes" -> { configName: true, ... } } */
    var solConfigs = {};
    configNames.forEach(function (cfgName) {
      var mols = allConfigs[cfgName].molecules;
      Object.keys(mols).forEach(function (molName) {
        mols[molName].solutions.forEach(function (sol) {
          if (!isPlanarSolution(sol)) return;
          var key = molName + '|' + (sol.sizes || sol.file);
          if (!solConfigs[key]) solConfigs[key] = {};
          solConfigs[key][cfgName] = true;
        });
      });
    });

    /* Regrouper par signature (set de configs ordonnees, separees par ',').
       solutions = liste complete des cles "mol|sizes" pour cette intersection. */
    var groups = {};
    Object.keys(solConfigs).forEach(function (key) {
      var configs = Object.keys(solConfigs[key]).sort();
      var sig = configs.join(',');
      if (!groups[sig]) groups[sig] = { configs: configs, count: 0, solutions: [] };
      groups[sig].count++;
      groups[sig].solutions.push(key);
    });

    /* Tri par count desc -- l'UpSet montre les plus grosses intersections d'abord. */
    var intersections = Object.keys(groups).map(function (sig) { return groups[sig]; });
    intersections.sort(function (a, b) { return b.count - a.count; });

    /* Per-config : total + breakdown par sharing degree (combien de solutions
       trouvees a la fois par cette config et N-1 autres). */
    var perConfig = {};
    configNames.forEach(function (cfgName) {
      perConfig[cfgName] = { total: 0, byDegree: {} };
      for (var d = 1; d <= nConfigs; d++) perConfig[cfgName].byDegree[d] = 0;
    });
    intersections.forEach(function (intr) {
      var d = intr.configs.length;
      intr.configs.forEach(function (cfgName) {
        perConfig[cfgName].total += intr.count;
        perConfig[cfgName].byDegree[d] += intr.count;
      });
    });

    return {
      configNames: configNames,
      nConfigs: nConfigs,
      totalUnique: Object.keys(solConfigs).length,
      intersections: intersections,
      perConfig: perConfig,
    };
  }

  /* Donne la cle de classification d'une solution. Multi-runs : champ
     direct. Single-run (h5 sans bloc 'runs') : map planar/non-planar vers
     always_planar/always_non_planar (simplification visuelle). */
  function _classificationKeyForSolution(sol) {
    if (sol.runs && sol.runs.classification && CLASSIFICATIONS[sol.runs.classification]) {
      return sol.runs.classification;
    }
    return sol.planar ? 'always_planar' : 'always_non_planar';
  }

  /* Pour chaque config, repartition de TOUTES ses solutions (planaires et
     non-planaires) par classe de stabilite. Utilise par le bar chart
     "Total par config" pour montrer le profil qualite de chaque solveur. */
  function computePerConfigBreakdown(allConfigs) {
    var configNames = Object.keys(allConfigs).sort();
    var classKeys = ['always_planar', 'mostly_planar', 'unstable',
                     'mostly_non_planar', 'always_non_planar', 'ambiguous'];
    var perConfig = {};
    configNames.forEach(function (cfgName) {
      var counts = {};
      classKeys.forEach(function (k) { counts[k] = 0; });
      var total = 0;
      var mols = allConfigs[cfgName].molecules;
      Object.keys(mols).forEach(function (molName) {
        mols[molName].solutions.forEach(function (sol) {
          var key = _classificationKeyForSolution(sol);
          if (counts.hasOwnProperty(key)) {
            counts[key]++;
            total++;
          }
        });
      });
      perConfig[cfgName] = { total: total, counts: counts };
    });
    return { configNames: configNames, classOrder: classKeys, perConfig: perConfig };
  }

  /* Liste de sections depliables : 1 <details> par intersection.
     Triees par degre de partage descendant (universelles d'abord, uniques en
     dernier), puis par count desc au sein du meme degre. Chaque section
     dévoile la liste des solutions (mol + sizes) qui la composent. */
  function renderIntersectionsList(partition) {
    var n = partition.nConfigs;
    var sorted = partition.intersections.slice().sort(function (a, b) {
      var d = b.configs.length - a.configs.length;
      if (d !== 0) return d;
      return b.count - a.count;
    });
    if (sorted.length === 0) return '<div class="csp-empty">Aucune intersection.</div>';

    var html = '';
    sorted.forEach(function (intr) {
      var deg = intr.configs.length;

      /* Titre : adapte selon le degre. Aucune couleur sur les blocs --
         les "couleurs" du viewer sont reservees aux classes de stabilite
         (vert/orange/rouge des badges) pour eviter toute confusion entre
         les 2 dimensions (stabilite xTB vs partage CSP). */
      var label, cfgsDetail = '';
      if (deg === n) {
        label = 'Universelles &mdash; trouvees par les ' + n + ' configurations';
      } else if (deg === 1) {
        label = 'Unique &agrave; <code>' + intr.configs[0] + '</code>';
      } else {
        label = deg + ' configs';
        cfgsDetail = '<span class="csp-intr-cfgs">' + intr.configs.map(function (c) {
          return '<code>' + c + '</code>';
        }).join(' &middot; ') + '</span>';
      }

      /* Liste des solutions de cette intersection (mol + sizes). */
      var items = intr.solutions.slice().sort().map(function (key) {
        var idx = key.indexOf('|');
        var mol = idx >= 0 ? key.slice(0, idx) : key;
        var sizes = idx >= 0 ? key.slice(idx + 1) : '';
        return '<li>'
             + '<span class="csp-item-mol">' + mol + '</span>'
             + '<span class="csp-item-sizes">' + sizes + '</span>'
             + '</li>';
      }).join('');

      html += '<details class="csp-intr-block">'
            + '<summary>'
            + '<span class="csp-intr-count">' + intr.count + '</span>'
            + '<span class="csp-intr-label">' + label + '</span>'
            + cfgsDetail
            + '</summary>'
            + '<ul class="csp-intr-items">' + items + '</ul>'
            + '</details>';
    });
    return html;
  }

  /* SVG per-config bar : 1 ligne par config, segments colores par classe
     de stabilite (CLASSIFICATIONS). Montre le profil qualite des solutions
     trouvees par chaque solveur (combien sont stables planes, instables,
     non-planes, etc). Utilise les MEMES couleurs que les badges et les
     cards de stabilite -> coherence visuelle dans tout le viewer. */
  function renderPerConfigBarSVG(breakdown) {
    var configNames = breakdown.configNames;
    var classOrder = breakdown.classOrder;
    var perConfig = breakdown.perConfig;
    var n = configNames.length;

    var maxTotal = 0;
    configNames.forEach(function (cfg) {
      if (perConfig[cfg].total > maxTotal) maxTotal = perConfig[cfg].total;
    });
    if (maxTotal === 0) maxTotal = 1;

    var labelW = 150, barW = 200, totalW = 50, padR = 12;
    var W = labelW + barW + totalW + padR;
    var rowH = 28;
    var H = n * rowH + 6;

    var parts = [];
    parts.push('<svg viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg" '
             + 'style="width:100%;max-width:' + W + 'px;font-family:Segoe UI,system-ui,sans-serif;">');

    configNames.forEach(function (cfg, i) {
      var y = i * rowH + 4;
      var midY = y + rowH / 2 + 4;
      var total = perConfig[cfg].total;
      var counts = perConfig[cfg].counts;

      parts.push('<text x="' + (labelW - 8) + '" y="' + midY.toFixed(1) + '" '
               + 'text-anchor="end" font-size="11" '
               + 'font-family="SFMono-Regular,Consolas,monospace" fill="#24292e">'
               + cfg + '</text>');
      parts.push('<rect x="' + labelW + '" y="' + (y + 4) + '" width="' + barW + '" '
               + 'height="' + (rowH - 8) + '" fill="#f0f0f0" rx="3"/>');

      if (total > 0) {
        var x = labelW;
        var fullW = (total / maxTotal) * barW;
        classOrder.forEach(function (classKey) {
          var c = counts[classKey];
          if (c === 0) return;
          var info = CLASSIFICATIONS[classKey];
          var segW = (c / total) * fullW;
          parts.push('<rect x="' + x.toFixed(1) + '" y="' + (y + 4) + '" '
                   + 'width="' + segW.toFixed(1) + '" height="' + (rowH - 8) + '" '
                   + 'fill="' + info.color + '">'
                   + '<title>' + cfg + ' : ' + c + ' ' + info.label + '</title></rect>');
          x += segW;
        });
      }

      parts.push('<text x="' + (labelW + barW + 8) + '" y="' + midY.toFixed(1) + '" '
               + 'font-size="11" font-weight="600" fill="#24292e">' + total + '</text>');
    });

    parts.push('</svg>');
    return parts.join('');
  }

  /* Orchestrateur : appele 1 fois a l'init. Si pas de container, no-op.
     - "Total par config" : breakdown par classe de stabilite (toutes les
       solutions, peu importe planaire/non).
     - "Intersections" : partition des solutions PLANAIRES seulement
       entre configs (filtre always_planar + mostly_planar). */
  function renderCSPPartitionSection() {
    var container = document.getElementById('cspPartitionContent');
    if (!container) return;
    var partition = computeCSPPartition(state.ALL_CONFIGS);
    var breakdown = computePerConfigBreakdown(state.ALL_CONFIGS);
    var n = partition.nConfigs;

    container.innerHTML =
      '<div class="csp-summary">' +
        '<b>' + partition.totalUnique + '</b> solution(s) planaire(s) unique(s) au total, '
      + 'partagee(s) entre <b>' + n + '</b> configurations CSP. '
      + '<i>(filtre intersection : always_planar + mostly_planar)</i>' +
      '</div>' +
      '<div class="csp-charts-row">' +
        '<div class="csp-chart-box">' +
          '<h4>Repartition par config (toutes solutions)</h4>' +
          renderPerConfigBarSVG(breakdown) +
          '<p class="csp-caption">Total de solutions trouvees par chaque config, segmente par classe de stabilite (memes couleurs que les badges -- voir legende stabilite plus bas).</p>' +
        '</div>' +
        '<div class="csp-chart-box wide">' +
          '<h4>Intersections (cliquer pour voir les solutions)</h4>' +
          '<div class="csp-intr-scroll">' + renderIntersectionsList(partition) + '</div>' +
          '<p class="csp-caption">Triees du plus universel (en haut) au plus unique (en bas). Cliquer un en-tete deplie la liste des solutions de cette intersection.</p>' +
        '</div>' +
      '</div>';
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
      var bucketCount = { PLANE: 0, AUTRES: 0, NON_PLANE: 0 };
      var hasRuns = false, hasMD = false;
      m.solutions.forEach(function (s) {
        if (s.planar) nP++; else nN++;
        if (s.angle_deg > maxA) maxA = s.angle_deg;
        if (s.runs) hasRuns = true;
        if (s.md_validation) hasMD = true;
        var b = solutionBucket(s);
        bucketCount[b]++;
      });
      rows.push({
        name: name, mol: m,
        origPlanar: m.original ? m.original.planar : null,
        origAngle: m.original ? m.original.angle_deg : null,
        numSol: m.solutions.length, numPlan: nP, numNon: nN, maxAngle: maxA,
        hasRuns: hasRuns, hasMD: hasMD,
        bucketCount: bucketCount,
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
    /* Filtre Verdict (3 buckets unifies) : retenue si au moins une solution
       est dans le bucket choisi pour la methode active. */
    if (state.filterVerdict !== 'all') {
      var b = FILTER_TO_BUCKET[state.filterVerdict];
      rows = rows.filter(function (r) { return r.bucketCount && r.bucketCount[b] > 0; });
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
    var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0;
    var nPlane = 0, nAutres = 0, nNonPlane = 0;
    allRows.forEach(function (r) {
      if (r.origPlanar === true) nOrigP++;
      else if (r.origPlanar === false) nOrigN++;
      nSol += r.numSol;
      nPlane    += r.bucketCount.PLANE;
      nAutres   += r.bucketCount.AUTRES;
      nNonPlane += r.bucketCount.NON_PLANE;
    });

    var badge = rows.length < allRows.length
      ? '<span class="count-badge">(' + rows.length + '/' + allRows.length + ')</span>' : '';

    /* Cards simplifiees : Mol + Originaux + 3 buckets (PLANE/AUTRES/NON_PLANE).
       En mode "both", AUTRES inclut les divergences MR vs MD (vu via solutionBucket). */
    var cardsHtml =
      '<div class="card blue"><div class="value">' + nMol + '</div><div class="label">Molecules' + badge + '</div></div>' +
      '<div class="card green"><div class="value">' + nOrigP + '</div><div class="label">Originaux plans</div></div>' +
      '<div class="card red"><div class="value">' + nOrigN + '</div><div class="label">Originaux non plans</div></div>' +
      '<div class="card blue"><div class="value">' + nSol + '</div><div class="label">Solutions CSP</div></div>' +
      '<div class="card green"><div class="value">' + nPlane + '</div><div class="label">\uD83D\uDFE2 Plans</div></div>' +
      '<div class="card" style="border-top-color:#bf8700"><div class="value" style="color:#bf8700">' + nAutres + '</div><div class="label">\uD83D\uDFE1 Autres</div></div>' +
      '<div class="card red"><div class="value">' + nNonPlane + '</div><div class="label">\u26AB Non plans</div></div>';
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
        var bc = r.bucketCount;
        var pills = [];
        if (bc.PLANE > 0)     pills.push(renderBucketPill('PLANE', bc.PLANE));
        if (bc.AUTRES > 0)    pills.push(renderBucketPill('AUTRES', bc.AUTRES));
        if (bc.NON_PLANE > 0) pills.push(renderBucketPill('NON_PLANE', bc.NON_PLANE));
        planCell = '<span class="bucket-pill-row">' + pills.join('') + '</span>';
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
        var detailHTML = renderSolutionDetail(s, hrefBase);
        var rowInner;
        if (detailHTML !== null) {
          /* Multi-runs et/ou MD : cellule unique colspan=5. */
          rowInner = '<td colspan="5" class="solution-multirun">' + detailHTML + '</td>';
        } else {
          /* Single-run classique (retrocompat, aucun bloc enrichi). */
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
    if (group === 'orig')        state.filterOrig = value;
    else if (group === 'sol')    state.filterSol = value;
    else if (group === 'verdict') state.filterVerdict = value;
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

  /* Detecte les molecules dont la planarite, le ratio plan/total, la
     classification multi-runs OU le verdict MD differe entre les configs
     selectionnees (ou qui sont absentes de certaines). Ces lignes seront
     highlightees. */
  function computeDiffMols(cfgs) {
    var allNames = {};
    cfgs.forEach(function (cfgName) {
      Object.keys(state.ALL_CONFIGS[cfgName].molecules).forEach(function (n) { allNames[n] = true; });
    });
    var diffMols = {};
    Object.keys(allNames).forEach(function (name) {
      var planarities = [], bucketSigs = [];
      var hasMissing = false, hasPresent = false;
      cfgs.forEach(function (cfgName) {
        var mol = state.ALL_CONFIGS[cfgName].molecules[name];
        if (!mol) { hasMissing = true; return; }
        hasPresent = true;
        planarities.push(mol.original ? mol.original.planar : null);
        /* Signature 3-bucket : compte par bucket selon methode active.
           Invariant a l'ordre des solutions. */
        var bk = { PLANE: 0, AUTRES: 0, NON_PLANE: 0 };
        mol.solutions.forEach(function (s) { bk[solutionBucket(s)]++; });
        bucketSigs.push(bk.PLANE + '|' + bk.AUTRES + '|' + bk.NON_PLANE);
      });
      var hasDiff = hasMissing && hasPresent;
      function differs(arr) {
        for (var i = 1; i < arr.length; i++) if (arr[i] !== arr[0]) return true;
        return false;
      }
      if (!hasDiff && planarities.length > 1 && differs(planarities)) hasDiff = true;
      if (!hasDiff && bucketSigs.length > 1  && differs(bucketSigs))  hasDiff = true;
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

    var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0;
    var nPlane = 0, nAutres = 0, nNonPlane = 0;
    allRows.forEach(function (r) {
      if (r.origPlanar === true) nOrigP++;
      else if (r.origPlanar === false) nOrigN++;
      nSol += r.numSol;
      nPlane    += r.bucketCount.PLANE;
      nAutres   += r.bucketCount.AUTRES;
      nNonPlane += r.bucketCount.NON_PLANE;
    });

    var html = '<div class="compare-panel" data-panel-cfg="' + cfgName + '">';
    html += '<div class="panel-header">' + cfgName + '</div>';
    html += '<div class="panel-cards">' +
      '<div class="mini-card blue"><div class="v">' + nMol   + '</div><div class="l">Molecules</div></div>' +
      '<div class="mini-card green"><div class="v">' + nOrigP + '</div><div class="l">Orig. plans</div></div>' +
      '<div class="mini-card red"><div class="v">' + nOrigN  + '</div><div class="l">Orig. non pl.</div></div>' +
      '<div class="mini-card blue"><div class="v">' + nSol   + '</div><div class="l">Solutions</div></div>' +
      '<div class="mini-card green"><div class="v">' + nPlane + '</div><div class="l">\uD83D\uDFE2 Plans</div></div>' +
      '<div class="mini-card" style="border-top-color:#bf8700"><div class="v" style="color:#bf8700">' + nAutres + '</div><div class="l">\uD83D\uDFE1 Autres</div></div>' +
      '<div class="mini-card red"><div class="v">' + nNonPlane + '</div><div class="l">\u26AB Non plans</div></div>';
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
        var bc = r.bucketCount;
        var pills = [];
        if (bc.PLANE > 0)     pills.push(renderBucketPill('PLANE', bc.PLANE));
        if (bc.AUTRES > 0)    pills.push(renderBucketPill('AUTRES', bc.AUTRES));
        if (bc.NON_PLANE > 0) pills.push(renderBucketPill('NON_PLANE', bc.NON_PLANE));
        solCell = '<span class="bucket-pill-row">' + pills.join('') + '</span>';
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
        var detailHTML = renderSolutionDetail(s, hrefBase);
        var rowInner;
        if (detailHTML !== null) {
          rowInner = '<td colspan="4" class="solution-multirun">' + detailHTML + '</td>';
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

  /* ---- Toggle methode active (multi-runs / md / both) ---- */
  function setMethod(name) {
    if (state.availableMethods.indexOf(name) < 0 && name !== 'both') return;
    state.activeMethod = name;
    /* Mise a jour des classes actives sur les boutons. */
    document.querySelectorAll('[data-method-btn]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.methodBtn === name);
    });
    /* Re-render de tout ce qui depend de la methode. */
    renderCSPPartitionSection();
    if (state.compareMode) renderComparison();
    else if (state.currentConfig) render(state.ALL_CONFIGS[state.currentConfig]);
  }

  /* Genere les boutons du toggle methode, attache au container HTML.
     Affiche seulement si >= 2 methodes disponibles. */
  function renderMethodToggle() {
    var container = document.getElementById('methodToggle');
    if (!container) return;
    var avail = state.availableMethods;
    if (avail.length < 2) {
      container.style.display = 'none';
      return;
    }
    container.style.display = '';
    var labels = {
      'multi-runs': '🔬 Multi-runs',  /* microscope */
      'md':         '🧬 MD',          /* dna helix */
      'both':       '🔀 Les deux',    /* shuffle */
    };
    var html = '<span class="label">Methode :</span>';
    avail.forEach(function (m) {
      var active = (m === state.activeMethod) ? ' active' : '';
      html += '<button class="method-btn' + active + '" data-method-btn="' + m
            + '" onclick="setMethod(\'' + m + '\')">' + labels[m] + '</button>';
    });
    /* "Les deux" disponible si les 2 methodes existent */
    var bothActive = (state.activeMethod === 'both') ? ' active' : '';
    html += '<button class="method-btn' + bothActive + '" data-method-btn="both" '
          + 'onclick="setMethod(\'both\')">' + labels['both'] + '</button>';
    container.innerHTML = html;
  }

  /* ---- Init ---- */
  /* Detection des methodes disponibles dans les data.json embarques. */
  state.availableMethods = detectAvailableMethods(state.ALL_CONFIGS);
  /* Choix de la methode active par defaut : multi-runs si dispo, sinon md. */
  if (state.availableMethods.length === 1) {
    state.activeMethod = state.availableMethods[0];
  } else if (state.availableMethods.length >= 2) {
    state.activeMethod = 'both';  /* affiche tout par defaut quand on a les 2 */
  }
  renderMethodToggle();
  /* Partition CSP : 1 calcul + 1 rendu, ne depend pas de la config courante. */
  renderCSPPartitionSection();
  /* Charge la premiere config par defaut (declenche render() pour cards + table). */
  var firstConfig = Object.keys(state.ALL_CONFIGS).sort()[0];
  if (firstConfig) selectConfig(firstConfig);

  /* Expose les handlers onclick (le HTML les appelle inline) */
  window.setMethod = setMethod;
})();
