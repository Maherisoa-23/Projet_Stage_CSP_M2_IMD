"""
Genere data.json et view.html a partir des resultats.

Usage:
    python view.py <dossier_config>                 # Mode config : genere data.json + view.html
    python view.py <dossier_hX> --aggregate         # Mode agrege : genere view.html interactif

Exemples:
    python view.py output/h4/default                # Scan une config, genere data.json
    python view.py output/h4 --aggregate            # Charge tous les data.json, genere view.html
"""

import sys
import json
import math
import importlib.util
from pathlib import Path
from datetime import datetime

# --- Import du module planarity ---
_gen_root = Path(__file__).parent.parent.parent / "non_benzenoid_generator"
_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_gen_root / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar

THRESHOLD_DEG = 10.0


# =====================================================================
#  Utilitaires lecture XYZ
# =====================================================================

def read_xyz_coords(xyz_path):
    coords = []
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 3:
        return coords
    n = int(lines[0].strip())
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return coords


def read_xyz_comment(xyz_path):
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    if len(lines) >= 2:
        return lines[1].strip()
    return ""


def analyze_opt_xyz(opt_path):
    coords = read_xyz_coords(str(opt_path))
    if len(coords) < 3:
        return None
    metrics = compute_planarity(coords)
    return {
        "planar": is_planar(metrics, THRESHOLD_DEG),
        "angle_deg": round(metrics["max_angle_deg"], 2),
        "rmsd": round(metrics["rmsd_plane"], 4),
        "height": round(metrics["height"], 4),
    }


def parse_solution_comment(comment):
    if ":" in comment:
        return comment.split(":", 1)[1].strip()
    return comment


# =====================================================================
#  Mode config : scan + data.json + view.html simple
# =====================================================================

def scan_directory(config_dir):
    config_dir = Path(config_dir)
    molecules = {}
    for mol_dir in sorted(config_dir.iterdir()):
        if not mol_dir.is_dir():
            continue
        name = mol_dir.name
        entry = {"name": name, "original": None, "solutions": []}
        for opt_file in mol_dir.glob("*_original_opt.xyz"):
            result = analyze_opt_xyz(opt_file)
            if result:
                entry["original"] = result
        sol_dir = mol_dir / "solutions"
        if sol_dir.is_dir():
            for opt_file in sorted(sol_dir.glob("sol_*_opt.xyz")):
                result = analyze_opt_xyz(opt_file)
                if result is None:
                    continue
                src_name = opt_file.name.replace("_opt.xyz", ".xyz")
                src_file = sol_dir / src_name
                if src_file.exists():
                    comment = read_xyz_comment(str(src_file))
                    result["sizes"] = parse_solution_comment(comment)
                else:
                    result["sizes"] = opt_file.stem.replace("_opt", "")
                result["file"] = opt_file.name
                entry["solutions"].append(result)
        molecules[name] = entry
    return molecules


def write_json(config_dir, molecules):
    data = {
        "source": config_dir.parent.name,
        "config": config_dir.name,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "threshold_deg": THRESHOLD_DEG,
        "molecules": molecules,
    }
    out = config_dir / "data.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  data.json -> {out}")
    return data


# =====================================================================
#  Mode agrege : charge tous les data.json et genere view.html interactif
# =====================================================================

def load_all_configs(h_dir):
    """Charge tous les data.json des sous-dossiers de config."""
    configs = {}
    for sub in sorted(h_dir.iterdir()):
        if sub.is_dir() and (sub / "data.json").exists():
            with open(sub / "data.json", "r", encoding="utf-8") as f:
                configs[sub.name] = json.load(f)
    return configs


def write_aggregate_html(h_dir, configs):
    """Genere un view.html interactif avec toutes les configs."""
    h_name = h_dir.name
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    configs_json = json.dumps(configs, ensure_ascii=False)
    config_names = sorted(configs.keys())
    n_configs = len(config_names)

    # Boutons de config
    config_buttons = "\n".join(
        f'    <button class="cfg-btn" data-cfg="{c}" onclick="selectConfig(\'{c}\')">{c}</button>'
        for c in config_names
    )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Resultats - {h_name}</title>
<style>
  :root {{
    --bg: #f0f2f5; --surface: #ffffff; --surface-alt: #f8f9fa;
    --border: #e1e4e8; --text: #24292e; --text-muted: #6a737d;
    --accent: #0969da; --accent-subtle: #ddf4ff;
    --green: #1a7f37; --green-bg: #dafbe1;
    --red: #cf222e; --red-bg: #ffebe9;
    --yellow-bg: #fff8c5;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
    --shadow-md: 0 3px 8px rgba(0,0,0,0.08);
    --radius: 8px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: var(--bg);
         color: var(--text); padding: 0; line-height: 1.5; font-size: 15px; }}

  /* Header & Footer */
  .page-header {{ background: var(--surface); border-bottom: 1px solid var(--border);
                  padding: 20px 24px; margin-bottom: 20px; box-shadow: var(--shadow-sm); }}
  .page-header h1 {{ font-size: 1.4em; margin-bottom: 2px; }}
  .page-header .meta {{ color: var(--text-muted); font-size: 0.82em; }}
  .page-footer {{ margin-top: 32px; padding: 16px 24px; text-align: center;
                  font-size: 0.78em; color: var(--text-muted); border-top: 1px solid var(--border); }}
  .page-footer span {{ margin: 0 12px; }}

  /* Container */
  .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px 40px; }}

  /* Config bar */
  .config-bar {{ background: var(--surface); border-radius: var(--radius); padding: 12px 16px;
                 margin-bottom: 20px; box-shadow: var(--shadow-sm);
                 display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .config-bar .label {{ font-weight: 600; color: var(--text-muted); font-size: 0.82em; white-space: nowrap; }}
  .cfg-btn {{ padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface);
              cursor: pointer; font-size: 0.82em; font-family: 'SFMono-Regular', Consolas, monospace;
              transition: all 0.15s; color: var(--text); }}
  .cfg-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .cfg-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .compare-toggle {{ margin-left: auto; padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px;
                     background: var(--surface); cursor: pointer; font-size: 0.82em;
                     transition: all 0.15s; color: var(--text-muted); }}
  .compare-toggle:hover {{ border-color: #bf8700; color: #bf8700; }}
  .compare-toggle.active {{ background: #bf8700; color: #fff; border-color: #bf8700; }}

  /* Cards */
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 14px; margin-bottom: 20px; }}
  .card {{ background: var(--surface); border-radius: var(--radius); padding: 16px 20px;
           box-shadow: var(--shadow-sm); border-top: 3px solid var(--border);
           transition: transform 0.15s, box-shadow 0.15s; }}
  .card:hover {{ transform: translateY(-1px); box-shadow: var(--shadow-md); }}
  .card .value {{ font-size: 1.7em; font-weight: 700; }}
  .card .label {{ font-size: 0.78em; color: var(--text-muted); margin-top: 2px; }}
  .card.green {{ border-top-color: var(--green); }}  .card.green .value {{ color: var(--green); }}
  .card.red {{ border-top-color: var(--red); }}      .card.red .value {{ color: var(--red); }}
  .card.blue {{ border-top-color: var(--accent); }}  .card.blue .value {{ color: var(--accent); }}

  /* Toolbar */
  .toolbar {{ background: var(--surface); border-radius: var(--radius); padding: 10px 16px;
              margin-bottom: 16px; box-shadow: var(--shadow-sm);
              display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .search-input {{ padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px;
                   font-size: 0.85em; width: 220px; outline: none;
                   transition: border-color 0.15s; font-family: inherit; }}
  .search-input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px rgba(9,105,218,0.15); }}
  .filter-group {{ display: flex; align-items: center; gap: 4px; }}
  .filter-group .flabel {{ font-size: 0.78em; color: var(--text-muted); font-weight: 600;
                           margin-right: 4px; white-space: nowrap; }}
  .filter-btn {{ padding: 4px 10px; border: 1px solid var(--border); border-radius: 12px;
                 background: var(--surface); cursor: pointer; font-size: 0.78em;
                 transition: all 0.15s; color: var(--text-muted); }}
  .filter-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .filter-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .btn-group {{ display: flex; gap: 4px; margin-left: auto; }}
  .btn-group button {{ cursor: pointer; padding: 5px 12px; border: 1px solid var(--border);
                       border-radius: 6px; background: var(--surface); font-size: 0.8em;
                       color: var(--text-muted); transition: all 0.15s; }}
  .btn-group button:hover {{ border-color: var(--accent); color: var(--accent); }}

  /* Table */
  .table-wrap {{ overflow-x: auto; border-radius: var(--radius); box-shadow: var(--shadow-sm); }}
  table {{ width: 100%; background: var(--surface); border-collapse: collapse; }}
  th {{ background: #f6f8fa; padding: 10px 14px; text-align: left; font-size: 0.78em;
       text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted);
       border-bottom: 1px solid var(--border); white-space: nowrap; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ color: var(--accent); }}
  th.sortable::after {{ content: ' \\25B3'; font-size: 0.8em; color: var(--border); }}
  th.sort-asc::after {{ content: ' \\25B2'; color: var(--accent); }}
  th.sort-desc::after {{ content: ' \\25BC'; color: var(--accent); }}
  td {{ padding: 8px 14px; border-top: 1px solid #f0f0f0; font-size: 0.88em; }}
  .mol-row {{ cursor: pointer; transition: background 0.1s; }}
  .mol-row:hover {{ background: var(--accent-subtle); }}
  .mol-row .expand-icon {{ display: inline-block; width: 16px; font-size: 0.7em;
                           color: var(--text-muted); transition: transform 0.2s; }}
  .mol-row.expanded .expand-icon {{ transform: rotate(90deg); }}
  .mol-name {{ font-weight: 600; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.88em; }}
  .detail-row {{ background: var(--surface-alt); display: none; }}
  .detail-row td {{ padding: 6px 14px 6px 48px; font-size: 0.82em; border-left: 3px solid var(--border); }}
  .detail-row td:first-child {{ border-left: none; }}
  .sizes {{ font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.82em; }}
  .sizes a {{ color: var(--accent); text-decoration: none; }}
  .sizes a:hover {{ text-decoration: underline; }}
  .planar {{ color: var(--green); font-weight: 600; }}
  .non-planar {{ color: var(--red); font-weight: 600; }}
  .na {{ color: #b2bec3; }}
  .count-badge {{ font-size: 0.75em; color: var(--text-muted); font-weight: 400; margin-left: 4px; }}

  /* Comparison -- side-by-side panels */
  .compare-panels {{ display: flex; gap: 14px; overflow-x: auto; padding-bottom: 8px; align-items: flex-start; }}
  .compare-panel {{ flex: 0 0 auto; width: 560px; background: var(--surface); border-radius: var(--radius);
                    padding: 12px 14px; box-shadow: var(--shadow-sm);
                    display: flex; flex-direction: column; gap: 10px; }}
  .panel-header {{ font-weight: 700; color: var(--accent); font-size: 0.88em;
                   padding: 6px 10px; background: var(--accent-subtle); border-radius: 6px;
                   text-align: center; font-family: 'SFMono-Regular', Consolas, monospace;
                   letter-spacing: 0.3px; }}
  .panel-cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }}
  .mini-card {{ background: var(--surface-alt); border-radius: 6px; padding: 8px 10px;
                text-align: center; border-top: 2px solid var(--border); }}
  .mini-card .v {{ font-size: 1.15em; font-weight: 700; line-height: 1.2; }}
  .mini-card .l {{ font-size: 0.68em; color: var(--text-muted); margin-top: 1px; }}
  .mini-card.green {{ border-top-color: var(--green); }}  .mini-card.green .v {{ color: var(--green); }}
  .mini-card.red {{ border-top-color: var(--red); }}      .mini-card.red .v {{ color: var(--red); }}
  .mini-card.blue {{ border-top-color: var(--accent); }}  .mini-card.blue .v {{ color: var(--accent); }}
  .panel-table {{ width: 100%; border-collapse: collapse; font-size: 0.82em; }}
  .panel-table th {{ background: #f6f8fa; padding: 6px 8px; text-align: left; font-size: 0.7em;
                     text-transform: uppercase; letter-spacing: 0.4px; color: var(--text-muted);
                     border-bottom: 1px solid var(--border); white-space: nowrap; }}
  .panel-table td {{ padding: 5px 8px; border-top: 1px solid #f0f0f0; }}
  .panel-table .mol-row {{ cursor: pointer; transition: background 0.1s; }}
  .panel-table .mol-row:hover {{ background: var(--accent-subtle); }}
  .panel-table .mol-row .expand-icon {{ display: inline-block; width: 12px; font-size: 0.65em;
                                        color: var(--text-muted); transition: transform 0.2s; }}
  .panel-table .mol-row.expanded .expand-icon {{ transform: rotate(90deg); }}
  .panel-table .mol-name {{ font-weight: 600; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.92em; }}
  .panel-table .detail-row {{ background: var(--surface-alt); display: none; }}
  .panel-table .detail-row td {{ padding: 4px 8px 4px 22px; font-size: 0.78em;
                                 border-left: 2px solid var(--border); }}
  .panel-table .detail-row td:first-child {{ border-left: none; }}
  .panel-table .sizes {{ font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.9em; }}
  .panel-table .sizes a {{ color: var(--accent); text-decoration: none; }}
  .panel-table .sizes a:hover {{ text-decoration: underline; }}
  .panel-table .na-row td {{ text-align: center; color: var(--text-muted); font-style: italic; padding: 16px; }}
  .diff-highlight {{ background: var(--yellow-bg) !important; }}
  .diff-highlight:hover {{ background: #fff0b3 !important; }}
  .diff-badge {{ display: inline-block; background: #bf8700; color: #fff; font-size: 0.7em;
                 padding: 1px 6px; border-radius: 8px; margin-left: 6px; font-weight: 600; }}
  .compare-empty {{ padding: 32px; text-align: center; color: var(--text-muted);
                    background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow-sm); }}

  /* Responsive */
  @media (max-width: 768px) {{
    .container {{ padding: 0 12px 24px; }}
    .cards {{ grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }}
    .toolbar {{ flex-direction: column; align-items: stretch; gap: 8px; }}
    .search-input {{ width: 100%; }}
    .btn-group {{ margin-left: 0; }}
    .config-bar {{ flex-direction: column; align-items: stretch; }}
    .compare-toggle {{ margin-left: 0; }}
    th, td {{ padding: 6px 8px; font-size: 0.8em; }}
  }}
</style>
</head>
<body>

<header class="page-header">
  <h1>Resultats : {h_name}</h1>
  <p class="meta">Mis a jour le {now} &mdash; Seuil de planarite : {THRESHOLD_DEG}&deg;</p>
</header>

<div class="container">

<div class="config-bar">
  <span class="label">Configuration :</span>
{config_buttons}
  <button class="compare-toggle" id="compareModeBtn" onclick="toggleCompareMode()">Comparer</button>
</div>

<!-- ====== Normal view ====== -->
<div id="normalView">
  <div class="cards" id="cards"></div>

  <div class="toolbar">
    <input type="text" class="search-input" id="searchInput"
           placeholder="Rechercher une molecule..." oninput="applyFilters()">
    <div class="filter-group">
      <span class="flabel">Originaux :</span>
      <button class="filter-btn active" data-filter="orig-all" onclick="setFilter('orig','all')">Tous</button>
      <button class="filter-btn" data-filter="orig-planar" onclick="setFilter('orig','planar')">Plans</button>
      <button class="filter-btn" data-filter="orig-nonplanar" onclick="setFilter('orig','nonplanar')">Non plans</button>
    </div>
    <div class="filter-group">
      <span class="flabel">Solutions :</span>
      <button class="filter-btn active" data-filter="sol-all" onclick="setFilter('sol','all')">Toutes</button>
      <button class="filter-btn" data-filter="sol-planar" onclick="setFilter('sol','planar')">Planes</button>
      <button class="filter-btn" data-filter="sol-nonplanar" onclick="setFilter('sol','nonplanar')">Non planes</button>
    </div>
    <div class="btn-group">
      <button onclick="expandAll()">Tout ouvrir</button>
      <button onclick="collapseAll()">Tout fermer</button>
    </div>
  </div>

  <div class="table-wrap">
    <table>
    <thead>
      <tr>
        <th class="sortable sort-asc" data-sort="name" onclick="sortTable('name')">Molecule</th>
        <th class="sortable" data-sort="original" onclick="sortTable('original')">Original</th>
        <th class="sortable" data-sort="solutions" onclick="sortTable('solutions')">Solutions</th>
        <th class="sortable" data-sort="planar" onclick="sortTable('planar')">Planarite</th>
        <th class="sortable" data-sort="angle" onclick="sortTable('angle')">Angle max</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
    </table>
  </div>
</div>

<!-- ====== Comparison view (side-by-side panels) ====== -->
<div id="compareView" style="display:none;">
  <div class="toolbar">
    <input type="text" class="search-input" id="compareSearchInput"
           placeholder="Rechercher une molecule..." oninput="applyFilters()">
    <div class="filter-group">
      <span class="flabel">Originaux :</span>
      <button class="filter-btn active" data-filter="orig-all" onclick="setFilter('orig','all')">Tous</button>
      <button class="filter-btn" data-filter="orig-planar" onclick="setFilter('orig','planar')">Plans</button>
      <button class="filter-btn" data-filter="orig-nonplanar" onclick="setFilter('orig','nonplanar')">Non plans</button>
    </div>
    <div class="filter-group">
      <span class="flabel">Solutions :</span>
      <button class="filter-btn active" data-filter="sol-all" onclick="setFilter('sol','all')">Toutes</button>
      <button class="filter-btn" data-filter="sol-planar" onclick="setFilter('sol','planar')">Planes</button>
      <button class="filter-btn" data-filter="sol-nonplanar" onclick="setFilter('sol','nonplanar')">Non planes</button>
    </div>
    <div class="filter-group">
      <span class="flabel">Diff :</span>
      <button class="filter-btn active" data-filter="diff-all" onclick="setCompareFilter('all')">Toutes</button>
      <button class="filter-btn" data-filter="diff-only" onclick="setCompareFilter('diff')">Differences</button>
    </div>
    <div class="btn-group">
      <button onclick="expandAll()">Tout ouvrir</button>
      <button onclick="collapseAll()">Tout fermer</button>
    </div>
  </div>

  <div class="compare-panels" id="comparePanels"></div>
</div>

</div>

<footer class="page-footer">
  <span>Genere le {now}</span>
  <span>Seuil : {THRESHOLD_DEG}&deg;</span>
  <span>{n_configs} configuration(s)</span>
</footer>

<script>
var ALL_CONFIGS = {configs_json};
var currentConfig = null;
var selectedConfigs = [];
var compareMode = false;
var sortCol = 'name';
var sortAsc = true;
var filterOrig = 'all';
var filterSol = 'all';
var searchQuery = '';
var expandedMols = {{}};
var compareFilter = 'all';

/* ---- Config selection ---- */
function selectConfig(name) {{
  if (compareMode) {{
    var idx = selectedConfigs.indexOf(name);
    if (idx >= 0) selectedConfigs.splice(idx, 1);
    else selectedConfigs.push(name);
    document.querySelectorAll('.cfg-btn').forEach(function(b) {{
      b.classList.toggle('active', selectedConfigs.indexOf(b.dataset.cfg) >= 0);
    }});
    renderComparison();
  }} else {{
    currentConfig = name;
    selectedConfigs = [name];
    document.querySelectorAll('.cfg-btn').forEach(function(b) {{
      b.classList.toggle('active', b.dataset.cfg === name);
    }});
    render(ALL_CONFIGS[name]);
  }}
}}

/* ---- Data pipeline: build, filter, sort ---- */
function buildRows(data) {{
  var mols = data.molecules;
  var rows = [];
  Object.keys(mols).forEach(function(name) {{
    var m = mols[name];
    var nP = 0, nN = 0, maxA = 0;
    m.solutions.forEach(function(s) {{
      if (s.planar) nP++; else nN++;
      if (s.angle_deg > maxA) maxA = s.angle_deg;
    }});
    rows.push({{
      name: name, mol: m,
      origPlanar: m.original ? m.original.planar : null,
      origAngle: m.original ? m.original.angle_deg : null,
      numSol: m.solutions.length, numPlan: nP, numNon: nN, maxAngle: maxA
    }});
  }});
  return rows;
}}

function filterRows(rows) {{
  if (searchQuery) {{
    var q = searchQuery.toLowerCase();
    rows = rows.filter(function(r) {{ return r.name.toLowerCase().indexOf(q) >= 0; }});
  }}
  if (filterOrig === 'planar') rows = rows.filter(function(r) {{ return r.origPlanar === true; }});
  else if (filterOrig === 'nonplanar') rows = rows.filter(function(r) {{ return r.origPlanar === false; }});
  if (filterSol === 'planar') rows = rows.filter(function(r) {{ return r.numPlan > 0; }});
  else if (filterSol === 'nonplanar') rows = rows.filter(function(r) {{ return r.numNon > 0; }});
  return rows;
}}

function sortRows(rows) {{
  rows.sort(function(a, b) {{
    var va, vb;
    switch (sortCol) {{
      case 'name': return sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
      case 'original':
        va = a.origPlanar === true ? 1 : (a.origPlanar === false ? -1 : 0);
        vb = b.origPlanar === true ? 1 : (b.origPlanar === false ? -1 : 0); break;
      case 'solutions': va = a.numSol; vb = b.numSol; break;
      case 'planar': va = a.numPlan; vb = b.numPlan; break;
      case 'angle': va = a.maxAngle; vb = b.maxAngle; break;
      default: va = a.name; vb = b.name;
    }}
    var c = (va < vb) ? -1 : (va > vb) ? 1 : 0;
    return sortAsc ? c : -c;
  }});
  return rows;
}}

/* ---- Main render (single config) ---- */
function render(data) {{
  var cfg = data.config || currentConfig;
  var allRows = buildRows(data);
  var rows = sortRows(filterRows(allRows.slice()));

  /* Stats from ALL rows (unfiltered) */
  var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0, nPlan = 0, nNon = 0;
  allRows.forEach(function(r) {{
    if (r.origPlanar === true) nOrigP++;
    else if (r.origPlanar === false) nOrigN++;
    nSol += r.numSol; nPlan += r.numPlan; nNon += r.numNon;
  }});

  var badge = rows.length < allRows.length
    ? '<span class="count-badge">(' + rows.length + '/' + allRows.length + ')</span>' : '';

  var el = document.getElementById('cards');
  el.innerHTML =
    '<div class="card blue"><div class="value">' + nMol + '</div><div class="label">Molecules' + badge + '</div></div>' +
    '<div class="card green"><div class="value">' + nOrigP + '</div><div class="label">Originaux plans</div></div>' +
    '<div class="card red"><div class="value">' + nOrigN + '</div><div class="label">Originaux non plans</div></div>' +
    '<div class="card blue"><div class="value">' + nSol + '</div><div class="label">Solutions CSP</div></div>' +
    '<div class="card green"><div class="value">' + nPlan + '</div><div class="label">Solutions planes</div></div>' +
    '<div class="card red"><div class="value">' + nNon + '</div><div class="label">Solutions non planes</div></div>';

  /* Table rows */
  var html = '';
  rows.forEach(function(r) {{
    var m = r.mol;
    var origCell;
    if (m.original) {{
      var cls = m.original.planar ? 'planar' : 'non-planar';
      var txt = m.original.planar ? 'PLAN' : 'NON PLAN';
      origCell = '<span class="' + cls + '">' + txt + '</span> (' + m.original.angle_deg + '&deg;)';
    }} else {{
      origCell = '<span class="na">-</span>';
    }}

    var solCell = r.numSol === 0
      ? '<span class="na">-</span>'
      : r.numSol + ' solution' + (r.numSol > 1 ? 's' : '');

    var planCell;
    if (r.numSol === 0) {{
      planCell = '<span class="na">-</span>';
    }} else {{
      planCell = '<span class="planar">' + r.numPlan + ' plan</span>';
      if (r.numNon > 0) planCell += ', <span class="non-planar">' + r.numNon + ' non</span>';
    }}

    var angleCell = r.numSol > 0 ? r.maxAngle + '&deg;' : '<span class="na">-</span>';
    var isExp = expandedMols[r.name] ? ' expanded' : '';

    html += '<tr class="mol-row' + isExp + '" data-mol="' + r.name + '" onclick="toggleDetails(\\'' + r.name + '\\')">' +
      '<td class="mol-name"><span class="expand-icon">&#9654;</span> ' + r.name + '</td>' +
      '<td>' + origCell + '</td>' +
      '<td>' + solCell + '</td>' +
      '<td>' + planCell + '</td>' +
      '<td>' + angleCell + '</td>' +
      '</tr>\\n';

    m.solutions.forEach(function(s) {{
      var scls = s.planar ? 'planar' : 'non-planar';
      var stxt = s.planar ? 'PLAN' : 'NON PLAN';
      var href = cfg + '/' + r.name + '/solutions/' + s.file;
      var disp = expandedMols[r.name] ? 'table-row' : 'none';
      html += '<tr class="detail-row" data-parent="' + r.name + '" style="display:' + disp + ';">' +
        '<td></td><td></td>' +
        '<td class="sizes"><a href="' + href + '" target="_blank">' + (s.sizes || s.file) + '</a></td>' +
        '<td><span class="' + scls + '">' + stxt + '</span></td>' +
        '<td>' + s.angle_deg + '&deg;</td>' +
        '</tr>\\n';
    }});
  }});

  document.getElementById('tbody').innerHTML = html;
}}

/* ---- Expand / Collapse ---- */
function toggleDetails(name) {{
  expandedMols[name] = !expandedMols[name];
  document.querySelectorAll('.detail-row[data-parent="' + name + '"]').forEach(function(row) {{
    row.style.display = expandedMols[name] ? 'table-row' : 'none';
  }});
  var molRow = document.querySelector('.mol-row[data-mol="' + name + '"]');
  if (molRow) molRow.classList.toggle('expanded', expandedMols[name]);
}}

function expandAll() {{
  document.querySelectorAll('.mol-row').forEach(function(r) {{
    r.classList.add('expanded');
    expandedMols[r.dataset.mol] = true;
  }});
  document.querySelectorAll('.detail-row').forEach(function(r) {{ r.style.display = 'table-row'; }});
}}

function collapseAll() {{
  document.querySelectorAll('.mol-row').forEach(function(r) {{ r.classList.remove('expanded'); }});
  document.querySelectorAll('.detail-row').forEach(function(r) {{ r.style.display = 'none'; }});
  expandedMols = {{}};
}}

/* ---- Sort ---- */
function sortTable(col) {{
  if (sortCol === col) sortAsc = !sortAsc;
  else {{ sortCol = col; sortAsc = true; }}
  document.querySelectorAll('th.sortable').forEach(function(th) {{
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === col) th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
  }});
  if (!compareMode && currentConfig) render(ALL_CONFIGS[currentConfig]);
}}

/* ---- Filters ---- */
function setFilter(group, value) {{
  if (group === 'orig') filterOrig = value;
  else if (group === 'sol') filterSol = value;
  document.querySelectorAll('.filter-btn').forEach(function(b) {{
    var f = b.dataset.filter;
    if (f && f.startsWith(group + '-')) b.classList.toggle('active', f === group + '-' + value);
  }});
  applyFilters();
}}

function setCompareFilter(value) {{
  compareFilter = value;
  document.querySelectorAll('[data-filter^="diff-"]').forEach(function(b) {{
    b.classList.toggle('active', b.dataset.filter === 'diff-' + value);
  }});
  renderComparison();
}}

function applyFilters() {{
  searchQuery = document.getElementById(compareMode ? 'compareSearchInput' : 'searchInput').value;
  if (compareMode) renderComparison();
  else if (currentConfig) render(ALL_CONFIGS[currentConfig]);
}}

/* ---- Comparison mode ---- */
function toggleCompareMode() {{
  compareMode = !compareMode;
  var btn = document.getElementById('compareModeBtn');
  btn.classList.toggle('active', compareMode);
  btn.textContent = compareMode ? 'Comparer (ON)' : 'Comparer';

  if (compareMode) {{
    document.getElementById('normalView').style.display = 'none';
    document.getElementById('compareView').style.display = 'block';
    if (currentConfig && selectedConfigs.indexOf(currentConfig) < 0)
      selectedConfigs = [currentConfig];
    renderComparison();
  }} else {{
    document.getElementById('normalView').style.display = 'block';
    document.getElementById('compareView').style.display = 'none';
    if (selectedConfigs.length > 0) {{
      currentConfig = selectedConfigs[0];
      selectedConfigs = [currentConfig];
    }}
    document.querySelectorAll('.cfg-btn').forEach(function(b) {{
      b.classList.toggle('active', b.dataset.cfg === currentConfig);
    }});
    if (currentConfig) render(ALL_CONFIGS[currentConfig]);
  }}
}}

function computeDiffMols(cfgs) {{
  /* For each molecule across configs, detect if any meaningful difference. */
  var allNames = {{}};
  cfgs.forEach(function(cfgName) {{
    Object.keys(ALL_CONFIGS[cfgName].molecules).forEach(function(n) {{ allNames[n] = true; }});
  }});
  var diffMols = {{}};
  Object.keys(allNames).forEach(function(name) {{
    var planarities = [], solRatios = [];
    var hasMissing = false, hasPresent = false;
    cfgs.forEach(function(cfgName) {{
      var mol = ALL_CONFIGS[cfgName].molecules[name];
      if (!mol) {{ hasMissing = true; return; }}
      hasPresent = true;
      planarities.push(mol.original ? mol.original.planar : null);
      var np = 0;
      mol.solutions.forEach(function(s) {{ if (s.planar) np++; }});
      solRatios.push(np + '/' + mol.solutions.length);
    }});
    var hasDiff = hasMissing && hasPresent;
    if (!hasDiff && planarities.length > 1) {{
      for (var i = 1; i < planarities.length; i++) {{
        if (planarities[i] !== planarities[0]) {{ hasDiff = true; break; }}
      }}
    }}
    if (!hasDiff && solRatios.length > 1) {{
      for (var i = 1; i < solRatios.length; i++) {{
        if (solRatios[i] !== solRatios[0]) {{ hasDiff = true; break; }}
      }}
    }}
    diffMols[name] = hasDiff;
  }});
  return diffMols;
}}

function buildPanel(cfgName, diffMols) {{
  var data = ALL_CONFIGS[cfgName];
  var allRows = buildRows(data);
  var rows = sortRows(filterRows(allRows.slice()));

  if (compareFilter === 'diff') {{
    rows = rows.filter(function(r) {{ return diffMols[r.name]; }});
  }}

  /* Stats from ALL rows (unfiltered) */
  var nMol = allRows.length, nOrigP = 0, nOrigN = 0, nSol = 0, nPlan = 0, nNon = 0;
  allRows.forEach(function(r) {{
    if (r.origPlanar === true) nOrigP++;
    else if (r.origPlanar === false) nOrigN++;
    nSol += r.numSol; nPlan += r.numPlan; nNon += r.numNon;
  }});

  var html = '<div class="compare-panel" data-panel-cfg="' + cfgName + '">';
  html += '<div class="panel-header">' + cfgName + '</div>';
  html += '<div class="panel-cards">' +
    '<div class="mini-card blue"><div class="v">' + nMol + '</div><div class="l">Molecules</div></div>' +
    '<div class="mini-card green"><div class="v">' + nOrigP + '</div><div class="l">Orig. plans</div></div>' +
    '<div class="mini-card red"><div class="v">' + nOrigN + '</div><div class="l">Orig. non pl.</div></div>' +
    '<div class="mini-card blue"><div class="v">' + nSol + '</div><div class="l">Solutions</div></div>' +
    '<div class="mini-card green"><div class="v">' + nPlan + '</div><div class="l">Sol. planes</div></div>' +
    '<div class="mini-card red"><div class="v">' + nNon + '</div><div class="l">Sol. non pl.</div></div>' +
    '</div>';

  /* Table */
  html += '<table class="panel-table"><thead><tr>' +
    '<th class="sortable' + (sortCol === 'name' ? (sortAsc ? ' sort-asc' : ' sort-desc') : '') + '" data-sort="name" onclick="sortTable(\\'name\\')">Molecule</th>' +
    '<th class="sortable' + (sortCol === 'original' ? (sortAsc ? ' sort-asc' : ' sort-desc') : '') + '" data-sort="original" onclick="sortTable(\\'original\\')">Orig.</th>' +
    '<th class="sortable' + (sortCol === 'solutions' ? (sortAsc ? ' sort-asc' : ' sort-desc') : '') + '" data-sort="solutions" onclick="sortTable(\\'solutions\\')">Sol.</th>' +
    '<th class="sortable' + (sortCol === 'angle' ? (sortAsc ? ' sort-asc' : ' sort-desc') : '') + '" data-sort="angle" onclick="sortTable(\\'angle\\')">Angle</th>' +
    '</tr></thead><tbody>';

  if (rows.length === 0) {{
    html += '<tr class="na-row"><td colspan="4">Aucune molecule</td></tr>';
  }}

  rows.forEach(function(r) {{
    var m = r.mol;
    var diffCls = diffMols[r.name] ? ' diff-highlight' : '';
    var expCls = expandedMols[r.name] ? ' expanded' : '';
    var diffBadge = diffMols[r.name] ? '<span class="diff-badge">diff</span>' : '';

    var origCell;
    if (m.original) {{
      var cls = m.original.planar ? 'planar' : 'non-planar';
      var txt = m.original.planar ? 'PLAN' : 'NON';
      origCell = '<span class="' + cls + '">' + txt + '</span> <small>(' + m.original.angle_deg + '&deg;)</small>';
    }} else {{
      origCell = '<span class="na">-</span>';
    }}

    var solCell;
    if (r.numSol === 0) {{
      solCell = '<span class="na">-</span>';
    }} else {{
      solCell = r.numSol + ' <small>(<span class="planar">' + r.numPlan + '</span>';
      if (r.numNon > 0) solCell += '/<span class="non-planar">' + r.numNon + '</span>';
      solCell += ')</small>';
    }}
    var angleCell = r.numSol > 0 ? r.maxAngle + '&deg;' : '<span class="na">-</span>';

    html += '<tr class="mol-row' + expCls + diffCls + '" data-mol="' + r.name + '" onclick="toggleDetails(\\'' + r.name + '\\')">' +
      '<td class="mol-name"><span class="expand-icon">&#9654;</span> ' + r.name + diffBadge + '</td>' +
      '<td>' + origCell + '</td>' +
      '<td>' + solCell + '</td>' +
      '<td>' + angleCell + '</td>' +
      '</tr>';

    var disp = expandedMols[r.name] ? 'table-row' : 'none';
    m.solutions.forEach(function(s) {{
      var scls = s.planar ? 'planar' : 'non-planar';
      var stxt = s.planar ? 'PLAN' : 'NON';
      var href = cfgName + '/' + r.name + '/solutions/' + s.file;
      html += '<tr class="detail-row" data-parent="' + r.name + '" style="display:' + disp + ';">' +
        '<td class="sizes"><a href="' + href + '" target="_blank">' + (s.sizes || s.file) + '</a></td>' +
        '<td colspan="2"><span class="' + scls + '">' + stxt + '</span></td>' +
        '<td>' + s.angle_deg + '&deg;</td>' +
        '</tr>';
    }});

    /* If molecule missing -- render a placeholder row so alignment is preserved visually */
    /* (skip: missing mols simply absent from this panel's rows) */
  }});

  html += '</tbody></table></div>';
  return html;
}}

function renderComparison() {{
  var cfgs = selectedConfigs;
  var container = document.getElementById('comparePanels');
  if (cfgs.length === 0) {{
    container.innerHTML = '<div class="compare-empty">Selectionnez au moins une configuration dans la barre du haut.</div>';
    return;
  }}
  var diffMols = computeDiffMols(cfgs);
  var html = '';
  cfgs.forEach(function(cfgName) {{ html += buildPanel(cfgName, diffMols); }});
  container.innerHTML = html;
}}

/* ---- Keyboard shortcuts ---- */
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') collapseAll();
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {{
    e.preventDefault();
    var el = document.getElementById(compareMode ? 'compareSearchInput' : 'searchInput');
    if (el) el.focus();
  }}
}});

/* ---- Init ---- */
var firstConfig = Object.keys(ALL_CONFIGS).sort()[0];
if (firstConfig) selectConfig(firstConfig);
</script>

</body>
</html>"""

    out = h_dir / "view.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  view.html (agrege) -> {out}")


# =====================================================================
#  Main
# =====================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python view.py <dossier_config>              # genere data.json")
        print("  python view.py <dossier_hX> --aggregate      # genere view.html interactif")
        sys.exit(1)

    target = Path(sys.argv[1])
    aggregate = "--aggregate" in sys.argv

    if not target.is_dir():
        print(f"ERREUR : {target} n'est pas un dossier.")
        sys.exit(1)

    if aggregate:
        # Mode agrege : charge les data.json existants
        print(f"Mode agrege : {target}")
        configs = load_all_configs(target)
        if not configs:
            print("Aucun data.json trouve dans les sous-dossiers.")
            sys.exit(0)
        print(f"  {len(configs)} configs trouvees : {', '.join(sorted(configs.keys()))}")
        write_aggregate_html(target, configs)
    else:
        # Mode config : scan et genere data.json
        print(f"Scan de {target}...")
        molecules = scan_directory(target)
        if not molecules:
            print("Aucun resultat trouve.")
            sys.exit(0)
        print(f"  {len(molecules)} molecules trouvees")
        write_json(target, molecules)

    print("Termine.")


if __name__ == "__main__":
    main()
