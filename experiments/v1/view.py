"""
Genere data.json et view.html a partir des resultats.

Usage:
    python view.py <dossier_config>                 # Mode config : genere data.json
    python view.py <dossier_hX> --aggregate         # Mode agrege : genere view.html interactif

Exemples:
    python view.py output/h4/default                # Scan une config, genere data.json
    python view.py output/h4 --aggregate            # Charge tous les data.json, genere view.html

Les templates HTML/CSS/JS sont dans ./templates/ (edites avec coloration
syntaxique). Ce fichier les charge, substitue les donnees et ecrit le HTML.
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from string import Template

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from csp_solver.planarity.pca import compute_planarity, is_planar

THRESHOLD_DEG = 10.0
TEMPLATES_DIR = Path(__file__).parent / "templates"


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
#  Mode config : scan + data.json
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
#  Mode agrege : charge tous les data.json et genere view.html
# =====================================================================

def load_all_configs(h_dir):
    """Charge tous les data.json des sous-dossiers de config."""
    configs = {}
    for sub in sorted(h_dir.iterdir()):
        if sub.is_dir() and (sub / "data.json").exists():
            with open(sub / "data.json", "r", encoding="utf-8") as f:
                configs[sub.name] = json.load(f)
    return configs


def _load_template(name):
    """Lit un fichier dans templates/, retourne son contenu."""
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _render_config_buttons(config_names):
    return "\n".join(
        f'    <button class="cfg-btn" data-cfg="{c}" onclick="selectConfig(\'{c}\')">{c}</button>'
        for c in config_names
    )


def _render_batch_meta(h_dir):
    """Si output/hX/batch_meta.json existe, genere un bandeau stats du dernier
    batch_all.py. Retourne chaine vide si absent (cas normal)."""
    meta_path = h_dir / "batch_meta.json"
    if not meta_path.exists():
        return ""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    # Format timestamp ISO -> "JJ/MM/AAAA HH:MM"
    gen = meta.get("generated", "")
    try:
        gen_fmt = datetime.fromisoformat(gen).strftime("%d/%m/%Y %H:%M")
    except Exception:
        gen_fmt = gen

    n_configs = meta.get("n_configs", 0)
    n_inst = meta.get("n_instances", 0)
    n_mol = n_inst // n_configs if n_configs > 0 else n_inst
    n_sol = meta.get("n_solutions", 0)
    duration = meta.get("duration_str", "")
    options = meta.get("options", [])
    opts_str = " ".join(options) if options else "(aucune)"
    source = meta.get("source", "")

    parts = [
        '<span class="batch-meta-label">Dernier batch complet</span>',
        f'<span>le {gen_fmt}</span>',
        f'<span>{n_mol} molecules &times; {n_configs} configs = {n_inst} instances</span>',
        f'<span>{n_sol} solutions</span>',
        f'<span>en {duration}</span>',
        f'<span>options : <code>{opts_str}</code></span>',
    ]
    if source:
        parts.insert(1, f'<span title="source">{source}</span>')

    sep = '<span class="batch-meta-sep">&middot;</span>'
    inner = sep.join(parts)
    return f'<div class="batch-meta">{inner}</div>'


def write_aggregate_html(h_dir, configs):
    """Genere un view.html interactif avec toutes les configs.
    Les donnees sont embarquees en JSON dans <script>window.__DATA__ = ...</script>.
    """
    config_names = sorted(configs.keys())
    configs_json = json.dumps(configs, ensure_ascii=False)
    # Defense : si un nom contient '</', un tag <script> serait casse.
    # Remplacer '</' par '<\/' est interprete identiquement par le JS.
    configs_json = configs_json.replace("</", "<\\/")

    template = Template(_load_template("view.html"))
    html = template.safe_substitute(
        h_name=h_dir.name,
        now=datetime.now().strftime("%d/%m/%Y %H:%M"),
        threshold_deg=THRESHOLD_DEG,
        n_configs=len(config_names),
        config_buttons=_render_config_buttons(config_names),
        batch_meta_html=_render_batch_meta(h_dir),
        configs_json=configs_json,
        common_css=_load_template("common.css"),
        view_css=_load_template("view.css"),
        view_js=_load_template("view.js"),
    )

    out = h_dir / "view.html"
    out.write_text(html, encoding="utf-8")
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
        print(f"Mode agrege : {target}")
        configs = load_all_configs(target)
        if not configs:
            print("Aucun data.json trouve dans les sous-dossiers.")
            sys.exit(0)
        print(f"  {len(configs)} configs trouvees : {', '.join(sorted(configs.keys()))}")
        write_aggregate_html(target, configs)
    else:
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
