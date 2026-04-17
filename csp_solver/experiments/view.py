"""
Genere data.json et view.html a partir des resultats d'un dossier output.

Usage:
    python view.py <dossier_output>

Exemple:
    python view.py output/h3
    python view.py output/h4

Scanne le dossier pour trouver les fichiers _opt.xyz (test.py et main.py),
calcule la planarite, et produit :
  - data.json  : resultats structures
  - view.html  : tableau de bord visuel
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


def read_xyz_coords(xyz_path):
    """Lit les coordonnees 3D depuis un fichier XYZ."""
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
    """Lit la ligne de commentaire (ligne 2) d'un XYZ."""
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    if len(lines) >= 2:
        return lines[1].strip()
    return ""


def analyze_opt_xyz(opt_path):
    """Analyse un fichier _opt.xyz et retourne les metriques."""
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
    """Extrait les tailles depuis un commentaire XYZ de solution.
    Ex: 'Solution 1: v0=6 v1=5 v2=7' -> 'v0=6 v1=5 v2=7'
    """
    if ":" in comment:
        return comment.split(":", 1)[1].strip()
    return comment


def scan_directory(h_dir):
    """Scanne un dossier output/hX/ et collecte les resultats."""
    h_dir = Path(h_dir)
    molecules = {}

    for mol_dir in sorted(h_dir.iterdir()):
        if not mol_dir.is_dir():
            continue
        name = mol_dir.name
        entry = {"name": name, "original": None, "solutions": []}

        # Test original (batch_test.py)
        for opt_file in mol_dir.glob("*_original_opt.xyz"):
            result = analyze_opt_xyz(opt_file)
            if result:
                entry["original"] = result

        # Solutions (batch_main.py --validate)
        sol_dir = mol_dir / "solutions"
        if sol_dir.is_dir():
            # Lire les XYZ non-optimises pour le commentaire (metadata)
            sol_files = sorted(sol_dir.glob("sol_*_opt.xyz"))
            for opt_file in sol_files:
                result = analyze_opt_xyz(opt_file)
                if result is None:
                    continue
                # Trouver le XYZ source pour le commentaire
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


def write_json(h_dir, molecules):
    """Ecrit data.json."""
    data = {
        "source": h_dir.name,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "threshold_deg": THRESHOLD_DEG,
        "molecules": molecules,
    }
    out = h_dir / "data.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  data.json -> {out}")
    return data


def write_html(h_dir, data):
    """Ecrit view.html."""
    molecules = data["molecules"]

    # Stats
    total = len(molecules)
    has_original = [m for m in molecules.values() if m["original"]]
    originals_planar = sum(1 for m in has_original if m["original"]["planar"])
    originals_non_planar = len(has_original) - originals_planar

    has_solutions = [m for m in molecules.values() if m["solutions"]]
    total_solutions = sum(len(m["solutions"]) for m in molecules.values())
    solutions_planar = sum(
        1 for m in molecules.values()
        for s in m["solutions"] if s["planar"]
    )
    solutions_non_planar = total_solutions - solutions_planar

    # Lignes du tableau
    rows_html = ""
    for name, mol in sorted(molecules.items()):
        # Original
        orig = mol["original"]
        if orig:
            cls = "planar" if orig["planar"] else "non-planar"
            orig_cell = (f'<span class="{cls}">'
                         f'{"PLAN" if orig["planar"] else "NON PLAN"}</span>'
                         f' ({orig["angle_deg"]}&deg;)')
        else:
            orig_cell = '<span class="na">-</span>'

        # Solutions
        n_sol = len(mol["solutions"])
        if n_sol == 0:
            sol_cell = '<span class="na">-</span>'
            detail_rows = ""
        else:
            n_plan = sum(1 for s in mol["solutions"] if s["planar"])
            n_non = n_sol - n_plan
            sol_cell = (f'{n_sol} solutions '
                        f'(<span class="planar">{n_plan} plan</span>'
                        f'{f", <span class=&quot;non-planar&quot;>{n_non} non plan</span>" if n_non else ""})')
            detail_rows = ""
            for s in mol["solutions"]:
                cls = "planar" if s["planar"] else "non-planar"
                detail_rows += (
                    f'<tr class="detail-row" data-parent="{name}">'
                    f'<td></td>'
                    f'<td class="sizes">{s["sizes"]}</td>'
                    f'<td><span class="{cls}">{"PLAN" if s["planar"] else "NON PLAN"}</span></td>'
                    f'<td>{s["angle_deg"]}&deg;</td>'
                    f'<td>{s["rmsd"]}</td>'
                    f'<td>{s["height"]}</td>'
                    f'</tr>\n'
                )

        rows_html += (
            f'<tr class="mol-row" onclick="toggleDetails(\'{name}\')">'
            f'<td class="mol-name">{name}</td>'
            f'<td>{orig_cell}</td>'
            f'<td colspan="4">{sol_cell}</td>'
            f'</tr>\n'
            f'{detail_rows}'
        )

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Resultats - {data["source"]}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f6fa; color: #2d3436; padding: 24px; }}
  h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .meta {{ color: #636e72; font-size: 0.85em; margin-bottom: 20px; }}
  .cards {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px 20px; min-width: 160px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .card .value {{ font-size: 1.8em; font-weight: 700; }}
  .card .label {{ font-size: 0.8em; color: #636e72; margin-top: 2px; }}
  .card.green .value {{ color: #00b894; }}
  .card.red .value {{ color: #d63031; }}
  .card.blue .value {{ color: #0984e3; }}
  table {{ width: 100%; background: #fff; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-collapse: collapse; }}
  th {{ background: #dfe6e9; padding: 10px 12px; text-align: left; font-size: 0.85em;
        text-transform: uppercase; letter-spacing: 0.5px; color: #636e72; }}
  td {{ padding: 8px 12px; border-top: 1px solid #f0f0f0; font-size: 0.9em; }}
  .mol-row {{ cursor: pointer; }}
  .mol-row:hover {{ background: #f8f9fa; }}
  .mol-name {{ font-weight: 600; font-family: monospace; }}
  .detail-row {{ background: #fafbfc; display: none; }}
  .detail-row td {{ padding-left: 32px; font-size: 0.85em; }}
  .detail-row .sizes {{ font-family: monospace; font-size: 0.8em; }}
  .planar {{ color: #00b894; font-weight: 600; }}
  .non-planar {{ color: #d63031; font-weight: 600; }}
  .na {{ color: #b2bec3; }}
  .threshold {{ background: #ffeaa7; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }}
</style>
<script>
function toggleDetails(name) {{
  document.querySelectorAll('.detail-row[data-parent="' + name + '"]').forEach(function(row) {{
    row.style.display = row.style.display === 'table-row' ? 'none' : 'table-row';
  }});
}}
function expandAll() {{
  document.querySelectorAll('.detail-row').forEach(function(row) {{
    row.style.display = 'table-row';
  }});
}}
function collapseAll() {{
  document.querySelectorAll('.detail-row').forEach(function(row) {{
    row.style.display = 'none';
  }});
}}
</script>
</head>
<body>
<h1>Resultats : {data["source"]}</h1>
<p class="meta">
  Genere le {data["generated"]} &mdash;
  Seuil de planarite : <span class="threshold">{data["threshold_deg"]}&deg;</span>
</p>

<div class="cards">
  <div class="card blue">
    <div class="value">{total}</div>
    <div class="label">Molecules</div>
  </div>
  {"".join(f'''
  <div class="card green">
    <div class="value">{originals_planar}</div>
    <div class="label">Originaux plans</div>
  </div>
  <div class="card red">
    <div class="value">{originals_non_planar}</div>
    <div class="label">Originaux non plans</div>
  </div>
  ''' if has_original else '''
  ''')}
  {"".join(f'''
  <div class="card blue">
    <div class="value">{total_solutions}</div>
    <div class="label">Solutions CSP</div>
  </div>
  <div class="card green">
    <div class="value">{solutions_planar}</div>
    <div class="label">Solutions planes</div>
  </div>
  <div class="card red">
    <div class="value">{solutions_non_planar}</div>
    <div class="label">Solutions non planes</div>
  </div>
  ''' if has_solutions else '''
  ''')}
</div>

<div style="margin-bottom: 8px;">
  <button onclick="expandAll()" style="cursor:pointer; padding: 4px 12px; border: 1px solid #ddd; border-radius: 4px; background: #fff;">Tout ouvrir</button>
  <button onclick="collapseAll()" style="cursor:pointer; padding: 4px 12px; border: 1px solid #ddd; border-radius: 4px; background: #fff;">Tout fermer</button>
</div>

<table>
<thead>
  <tr>
    <th>Molecule</th>
    <th>Original</th>
    <th>Solutions / Tailles</th>
    <th>Statut</th>
    <th>Angle max</th>
    <th>RMSD</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

</body>
</html>"""

    out = h_dir / "view.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  view.html -> {out}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python view.py <dossier_output>")
        print("Exemple: python view.py output/h3")
        sys.exit(1)

    h_dir = Path(sys.argv[1])
    if not h_dir.is_dir():
        print(f"ERREUR : {h_dir} n'est pas un dossier.")
        sys.exit(1)

    print(f"Scan de {h_dir}...")
    molecules = scan_directory(h_dir)

    if not molecules:
        print("Aucun resultat trouve.")
        sys.exit(0)

    print(f"  {len(molecules)} molecules trouvees")
    data = write_json(h_dir, molecules)
    write_html(h_dir, data)
    print("Termine.")


if __name__ == "__main__":
    main()
