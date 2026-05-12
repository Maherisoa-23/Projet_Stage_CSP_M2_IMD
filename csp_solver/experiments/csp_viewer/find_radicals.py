"""Script jetable : trouve les sols (h=h4) avec V (nb atomes C) impair.

Theoreme : un perfect matching de Kekule necessite un nombre pair d'atomes.
Donc V impair => radical garanti (au moins 1 electron non apparie).

Pas de calcul de matching ici, juste un compte des C dans md_final_opt.xyz.
"""

import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
DB_PATH = HERE / "db_all.db"

DATASET = "h4"
N_TO_SHOW = 15  # nombre max de candidats a afficher


def resolve_path(rel: str):
    """Reproduit la logique de server._resolve_local_path : essaie plusieurs
    variantes de chemin (cluster vs local) pour trouver le fichier xyz."""
    rel = rel.replace("\\", "/").lstrip("/")
    candidates = [rel]
    m = re.match(r"^_h(\d+)_run/output/h\1/(.+)$", rel)
    if m:
        candidates.append(f"cluster_results/h{m.group(1)}/{m.group(2)}")
    m = re.match(r"^cluster_results/(h\d+)/(.+)$", rel)
    if m:
        candidates.append(f"_{m.group(1)}_run/output/{m.group(1)}/{m.group(2)}")
    for c in candidates:
        p = (PROJECT_ROOT / c).resolve()
        try:
            p.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            continue
        if p.is_file():
            return p
    return None


def count_carbons(xyz_path: Path):
    """Compte les atomes C dans un xyz. Retourne None si fichier illisible."""
    try:
        with open(xyz_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    if len(lines) < 3:
        return None
    try:
        n_total = int(lines[0].strip())
    except ValueError:
        return None
    n_c = 0
    for line in lines[2:2 + n_total]:
        parts = line.split()
        if parts and parts[0] == "C":
            n_c += 1
    return n_c


def main():
    if not DB_PATH.is_file():
        print(f"DB introuvable : {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT h, config, mol, sol_idx, sizes, verdict, sol_dir, planar, angle_deg "
        "FROM solutions "
        "WHERE h = ? AND verdict IN ('plan', 'non_plan') "
        "ORDER BY config, mol, sol_idx",
        (DATASET,),
    ).fetchall()
    print(f"[{DATASET}] {len(rows)} sols valides (plan + non_plan) a verifier...")

    candidates = []
    checked = 0
    missing = 0
    for r in rows:
        xyz_rel = f"{r['sol_dir']}/md_validation/md_final_opt.xyz"
        xyz = resolve_path(xyz_rel)
        if xyz is None:
            missing += 1
            continue
        v = count_carbons(xyz)
        if v is None:
            continue
        checked += 1
        if v % 2 == 1:
            candidates.append({
                "h": r["h"], "config": r["config"], "mol": r["mol"],
                "sol_idx": r["sol_idx"], "sizes": r["sizes"],
                "verdict": r["verdict"], "n_carbons": v,
                "planar": r["planar"], "angle_deg": r["angle_deg"],
            })

    print(f"  Verifies   : {checked}")
    print(f"  Manquants  : {missing}")
    print(f"  V impair   : {len(candidates)} (radical garanti)")
    print()
    if not candidates:
        print("Aucun candidat trouve : toutes les mols ont V pair.")
        return
    print(f"{'config':32} | {'mol':32} | {'sol':5} | {'sizes':14} | {'V':3} | {'verdict':9} | angle")
    print("-" * 130)
    for c in candidates[:N_TO_SHOW]:
        ang = "" if c["angle_deg"] is None else f"{c['angle_deg']:.2f} deg"
        print(f"{c['config']:32} | {c['mol']:32} | {c['sol_idx']:5} | {c['sizes']:14} | {c['n_carbons']:3} | {c['verdict']:9} | {ang}")


if __name__ == "__main__":
    main()
