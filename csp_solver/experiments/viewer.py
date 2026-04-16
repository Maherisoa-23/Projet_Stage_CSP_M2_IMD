"""
Generateur de rapport HTML a partir des JSON de resultats.

Usage :
    python viewer.py results/benzdb/h4/         -> rapport pour tous les JSON du dossier
    python viewer.py results/benzdb/h4/foo.json  -> rapport pour un seul fichier

Ou appele automatiquement par batch_run.py apres --solve / --validate.
"""

import json
import sys
from pathlib import Path


SEUIL_PLANARITE = 10.0  # degres


def load_json_files(path):
    """Charge les JSON depuis un fichier ou dossier."""
    p = Path(path)
    if p.is_file() and p.suffix == '.json':
        with open(p) as f:
            return [json.load(f)]
    elif p.is_dir():
        data = []
        for jp in sorted(p.rglob("*.json")):
            with open(jp) as f:
                data.append(json.load(f))
        return data
    return []


def _bar(value, max_val=30.0, width=15):
    """Barre visuelle proportionnelle."""
    if value <= 0:
        return ""
    ratio = min(value / max_val, 1.0)
    filled = int(ratio * width)
    return '<span class="bar">' + \
           '<span class="bar-fill" style="width:{}%"></span>'.format(
               int(ratio * 100)) + \
           '</span>'


def _solution_row_html(idx, sol_data):
    """Genere une ligne <tr> pour une solution."""
    tailles = sol_data.get("tailles", [])
    tailles_str = " ".join(str(t) for t in tailles)
    n5 = sol_data.get("nb_pentagones", 0)
    n6 = sol_data.get("nb_hexagones", 0)
    n7 = sol_data.get("nb_heptagones", 0)
    est_orig = sol_data.get("est_original", False)

    # Description composition
    if est_orig:
        comp = '<span class="tag tag-orig">original</span>'
    else:
        parts = []
        if n5 > 0:
            parts.append(f'{n5} penta')
        if n6 > 0:
            parts.append(f'{n6} hexa')
        if n7 > 0:
            parts.append(f'{n7} hepta')
        comp = ", ".join(parts)

    # Tailles colorees
    colored = []
    for t in tailles:
        if t == 5:
            colored.append('<span class="c5">5</span>')
        elif t == 7:
            colored.append('<span class="c7">7</span>')
        else:
            colored.append('<span class="c6">6</span>')
    tailles_html = " ".join(colored)

    # Validation
    val = sol_data.get("validation")
    if val:
        angle = val.get("angle_max_deg", -1)
        est_p = val.get("est_planaire", False)
        if est_p:
            status = f'<span class="plan">PLAN</span>'
        else:
            status = f'<span class="non-plan">NON PLAN</span>'
        angle_str = f"{angle:.1f}&deg;" if angle >= 0 else "—"
        bar_html = _bar(angle)
        rmsd = val.get("rmsd_plan", -1)
        hauteur = val.get("hauteur", -1)
        rmsd_str = f"{rmsd:.4f}" if rmsd >= 0 else "—"
        hauteur_str = f"{hauteur:.4f}" if hauteur >= 0 else "—"
    else:
        status = '<span class="pending">—</span>'
        angle_str = "—"
        bar_html = ""
        rmsd_str = "—"
        hauteur_str = "—"

    return f"""<tr>
        <td class="idx">#{idx}</td>
        <td class="tailles">{tailles_html}</td>
        <td>{comp}</td>
        <td class="center">{status}</td>
        <td class="right">{angle_str}</td>
        <td>{bar_html}</td>
        <td class="right">{rmsd_str}</td>
        <td class="right">{hauteur_str}</td>
    </tr>"""


def _benzenoid_block_html(data):
    """Genere le bloc HTML pour un benzenoide."""
    fname = data.get("file", "?")
    h = data.get("h", "?")
    solve = data.get("solve", {})
    nb_sol = solve.get("nb_solutions", 0)
    temps = solve.get("temps_s", "—")
    freeze = solve.get("freeze_mode", "freeze")
    solutions = solve.get("solutions", [])
    nb_p = solve.get("nb_planaires")
    nb_np = solve.get("nb_non_planaires")

    # Resume validation
    if nb_p is not None:
        summary_val = (f' &mdash; <span class="plan">{nb_p} planaire(s)</span>'
                       f', <span class="non-plan">{nb_np} non planaire(s)</span>')
    else:
        summary_val = ""

    # Lignes solutions
    sol_rows = ""
    for idx, sol_data in enumerate(solutions, 1):
        sol_rows += _solution_row_html(idx, sol_data)

    return f"""
    <div class="benzenoid">
        <div class="benz-header">
            <h3>{fname}</h3>
            <span class="meta">h={h} &bull; {nb_sol} solution(s)
                &bull; {freeze} &bull; {temps}s{summary_val}</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Tailles</th>
                    <th>Composition</th>
                    <th>Planaire</th>
                    <th>Angle max</th>
                    <th></th>
                    <th>RMSD</th>
                    <th>Hauteur</th>
                </tr>
            </thead>
            <tbody>
                {sol_rows}
            </tbody>
        </table>
    </div>"""


CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #f5f5f5; color: #333; padding: 30px;
}
h1 { margin-bottom: 8px; color: #1a1a1a; }
.subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
.benzenoid {
    background: #fff; border-radius: 8px; padding: 20px;
    margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.benz-header { margin-bottom: 12px; }
.benz-header h3 { font-size: 16px; color: #1a1a1a; margin-bottom: 4px; }
.meta { font-size: 13px; color: #888; }
table {
    width: 100%; border-collapse: collapse; font-size: 13px;
}
thead th {
    text-align: left; padding: 6px 10px; border-bottom: 2px solid #eee;
    color: #888; font-weight: 600; font-size: 11px; text-transform: uppercase;
}
tbody td { padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }
tbody tr:hover { background: #fafafa; }
.idx { color: #aaa; width: 40px; }
.tailles { font-family: 'Consolas', 'Courier New', monospace; font-size: 13px; }
.center { text-align: center; }
.right { text-align: right; font-family: 'Consolas', monospace; font-size: 12px; }
.c5 { color: #e67e22; font-weight: 700; }
.c6 { color: #888; }
.c7 { color: #3498db; font-weight: 700; }
.plan {
    background: #d4edda; color: #155724; padding: 2px 8px;
    border-radius: 3px; font-size: 11px; font-weight: 600;
}
.non-plan {
    background: #f8d7da; color: #721c24; padding: 2px 8px;
    border-radius: 3px; font-size: 11px; font-weight: 600;
}
.pending { color: #ccc; }
.tag { padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; }
.tag-orig { background: #e8f4fd; color: #2980b9; }
.bar {
    display: inline-block; width: 80px; height: 10px;
    background: #eee; border-radius: 5px; overflow: hidden;
    vertical-align: middle;
}
.bar-fill {
    display: block; height: 100%; border-radius: 5px;
    background: linear-gradient(90deg, #2ecc71, #e67e22, #e74c3c);
}
.summary {
    background: #fff; border-radius: 8px; padding: 16px 20px;
    margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    display: flex; gap: 30px; font-size: 14px;
}
.summary .num { font-size: 24px; font-weight: 700; color: #1a1a1a; }
.summary .label { font-size: 11px; color: #888; text-transform: uppercase; }
"""


def generate_html(json_paths, output_path):
    """Genere le rapport HTML a partir d'une liste de fichiers JSON."""
    all_data = []
    for jp in json_paths:
        jp = Path(jp)
        if jp.exists():
            with open(jp) as f:
                all_data.append(json.load(f))

    if not all_data:
        print("  Aucun JSON a afficher.")
        return

    # Statistiques globales
    total_benz = len(all_data)
    total_sol = sum(d.get("solve", {}).get("nb_solutions", 0) for d in all_data)
    total_plan = sum(d.get("solve", {}).get("nb_planaires", 0)
                     for d in all_data if d.get("solve", {}).get("nb_planaires") is not None)
    total_nplan = sum(d.get("solve", {}).get("nb_non_planaires", 0)
                      for d in all_data if d.get("solve", {}).get("nb_non_planaires") is not None)
    has_validation = total_plan + total_nplan > 0

    # Titre
    category = all_data[0].get("file", "").split(".")[0] if all_data else ""
    h_val = all_data[0].get("h", "?") if all_data else "?"
    title = f"Resultats CSP — h={h_val} ({total_benz} benzenoides)"

    # Resume
    summary_html = f"""
    <div class="summary">
        <div><div class="num">{total_benz}</div><div class="label">Benzenoides</div></div>
        <div><div class="num">{total_sol}</div><div class="label">Solutions CSP</div></div>
    """
    if has_validation:
        summary_html += f"""
        <div><div class="num" style="color:#155724">{total_plan}</div>
             <div class="label">Planaires</div></div>
        <div><div class="num" style="color:#721c24">{total_nplan}</div>
             <div class="label">Non planaires</div></div>
        """
    summary_html += "</div>"

    # Blocs benzenoides
    blocks = ""
    for d in all_data:
        blocks += _benzenoid_block_html(d)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>{CSS}</style>
</head>
<body>
    <h1>{title}</h1>
    <p class="subtitle">Seuil de planarite : {SEUIL_PLANARITE}&deg;
       &bull; Solveur : PyCSP3 + ACE</p>
    {summary_html}
    {blocks}
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  HTML genere : {output_path}")


# ===== Main standalone =====

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python viewer.py <dossier_json_ou_fichier> [output.html]")
        sys.exit(1)

    source = sys.argv[1]
    p = Path(source)

    if p.is_file() and p.suffix == '.json':
        json_paths = [p]
        default_out = p.with_suffix('.html')
    elif p.is_dir():
        json_paths = sorted(p.rglob("*.json"))
        default_out = p.parent / f"rapport_{p.name}.html"
    else:
        print(f"ERREUR: {source} introuvable")
        sys.exit(1)

    output = sys.argv[2] if len(sys.argv) > 2 else str(default_out)
    generate_html(json_paths, output)
