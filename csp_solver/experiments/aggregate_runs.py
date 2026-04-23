"""
Scanne un dossier de config avec la structure multi-runs et produit data.json.

Usage:
    python aggregate_runs.py <dossier_config>

Structure attendue (quand n_runs > 1) :
    <config_dir>/
      {mol_name}/
        {mol_name}_original/
          source.xyz
          run_01_opt.xyz
          run_02_opt.xyz
          ...
        solutions/
          sol_1_<sizes>/
            source.xyz
            run_01_opt.xyz
            ...
          sol_2_<sizes>/
            ...

Produit :
    <config_dir>/data.json    (format enrichi avec bloc 'runs' par solution)

Classifications :
    always_planar     : 100% plans ET angle_mean < 5
    mostly_planar     : >= 70% plans ET angle_std < 3
    unstable          : 30-70% plans OU angle_std > 5
    mostly_non_planar : < 30% plans ET planar_pct > 0
    always_non_planar : 0% plans
    ambiguous         : autre (ex: n < 3, tous runs echoues)
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
#  Lecture XYZ
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
    return lines[1].strip() if len(lines) >= 2 else ""


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
#  Agregation et classification
# =====================================================================

def classify(n, planar_pct, angle_mean, angle_std):
    """Classifie une solution selon stats multi-runs.
    Retourne une chaine parmi les 6 categories specifiees.
    """
    if n < 3:
        return "ambiguous"
    if planar_pct == 100 and angle_mean < 5:
        return "always_planar"
    if planar_pct == 0:
        return "always_non_planar"
    # unstable prime sur mostly_* si indicateurs contradictoires
    if 30 <= planar_pct <= 70 or angle_std > 5:
        return "unstable"
    if planar_pct >= 70 and angle_std < 3:
        return "mostly_planar"
    if 0 < planar_pct < 30:
        return "mostly_non_planar"
    return "ambiguous"


def aggregate_runs(sol_dir):
    """Scanne un sous-dossier (sol_X_sizes/ ou {mol}_original/)
    et retourne (dernier_resultat, bloc_runs) ou (None, None) si vide.
    """
    run_files = sorted(sol_dir.glob("run_*_opt.xyz"))
    if not run_files:
        return None, None

    angles = []
    planar_flags = []
    last_result = None
    for f in run_files:
        r = analyze_opt_xyz(f)
        if r is None:
            continue
        angles.append(r["angle_deg"])
        planar_flags.append(r["planar"])
        last_result = r  # chaque itération ecrase — on garde le dernier

    if not angles:
        return None, None

    n = len(angles)
    planar_count = sum(planar_flags)
    non_planar_count = n - planar_count
    planar_pct = round(100 * planar_count / n)
    mean = sum(angles) / n
    var = sum((a - mean) ** 2 for a in angles) / n
    std = math.sqrt(var)

    runs = {
        "n": n,
        "planar_count": planar_count,
        "non_planar_count": non_planar_count,
        "planar_pct": planar_pct,
        "angle_mean": round(mean, 2),
        "angle_std": round(std, 2),
        "angle_min": round(min(angles), 2),
        "angle_max": round(max(angles), 2),
        "angles": angles,
        "classification": classify(n, planar_pct, mean, std),
    }
    return last_result, runs


# =====================================================================
#  Scan du dossier config
# =====================================================================

def scan_config(config_dir):
    """Scanne un dossier de config. Retourne (molecules_dict, n_runs_max)."""
    config_dir = Path(config_dir)
    molecules = {}
    max_n = 0

    for mol_dir in sorted(config_dir.iterdir()):
        if not mol_dir.is_dir():
            continue
        name = mol_dir.name
        entry = {"name": name, "original": None, "solutions": []}

        # Original — deux structures possibles
        orig_multi = mol_dir / f"{name}_original"
        if orig_multi.is_dir():
            # multi-runs
            last, runs = aggregate_runs(orig_multi)
            if last:
                last["runs"] = runs
                entry["original"] = last
                max_n = max(max_n, runs["n"])
        else:
            # single-run (structure plate historique)
            for opt_file in mol_dir.glob("*_original_opt.xyz"):
                r = analyze_opt_xyz(opt_file)
                if r:
                    entry["original"] = r

        # Solutions
        sol_dir = mol_dir / "solutions"
        if sol_dir.is_dir():
            # multi-runs : sous-dossiers sol_*
            multi_sols = sorted([d for d in sol_dir.iterdir()
                                 if d.is_dir() and d.name.startswith("sol_")])
            if multi_sols:
                for sd in multi_sols:
                    last, runs = aggregate_runs(sd)
                    if last is None:
                        continue
                    # metadata : commentaire de source.xyz
                    src = sd / "source.xyz"
                    sizes = parse_solution_comment(read_xyz_comment(str(src))) if src.exists() else sd.name
                    last["sizes"] = sizes
                    last["file"] = f"{sd.name}/run_{runs['n']:02d}_opt.xyz"
                    last["runs"] = runs
                    entry["solutions"].append(last)
                    max_n = max(max_n, runs["n"])
            else:
                # single-run : fichiers plats sol_*_opt.xyz
                for opt_file in sorted(sol_dir.glob("sol_*_opt.xyz")):
                    r = analyze_opt_xyz(opt_file)
                    if r is None:
                        continue
                    src_name = opt_file.name.replace("_opt.xyz", ".xyz")
                    src = sol_dir / src_name
                    r["sizes"] = parse_solution_comment(read_xyz_comment(str(src))) if src.exists() else opt_file.stem
                    r["file"] = opt_file.name
                    entry["solutions"].append(r)

        molecules[name] = entry

    return molecules, max_n


def write_data_json(config_dir, molecules, n_runs):
    data = {
        "source": config_dir.parent.name,
        "config": config_dir.name,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "threshold_deg": THRESHOLD_DEG,
        "n_runs": n_runs if n_runs > 0 else 1,
        "molecules": molecules,
    }
    out = config_dir / "data.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  data.json -> {out}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python aggregate_runs.py <dossier_config>")
        sys.exit(1)
    target = Path(sys.argv[1])
    if not target.is_dir():
        print(f"ERREUR : {target} n'est pas un dossier.")
        sys.exit(1)

    print(f"Scan de {target}...")
    molecules, n_runs = scan_config(target)
    if not molecules:
        print("Aucun resultat trouve.")
        sys.exit(0)
    print(f"  {len(molecules)} molecules, n_runs max = {n_runs}")
    write_data_json(target, molecules, n_runs)
    print("Termine.")


if __name__ == "__main__":
    main()
