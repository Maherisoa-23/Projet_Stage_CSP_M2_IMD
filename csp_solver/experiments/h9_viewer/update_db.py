"""
Met à jour h9.db pour un sous-ensemble de (config, mol), sans tout
re-scanner. Utile après que le cluster a complété des sol_dirs vides
et que tu as re-téléchargé `cluster_results/h9/<config>/<mol>/`.

Pour chaque (config, mol) ciblée, le script :
  1. Supprime les anciennes lignes de solutions.
  2. Re-scanne les sol_dirs sur disque, calcule la planarité.
  3. Réinsère les lignes solutions et MAJ la ligne molecules.
  4. Recalcule la stat globale par config.

Usage :
    # MAJ une mol précise
    python update_db.py --config no-freeze_no-table --mol 0-10-19-20-27-28-29-37-38

    # MAJ toutes les mols listées dans un TSV (ex: missing_per_mol.tsv)
    python update_db.py --from-tsv missing_export/missing_per_mol.tsv

    # MAJ toutes les mols partielles selon la DB actuelle (utile après
    # qu'un batch de complétion a tourné)
    python update_db.py --all-partials

    # MAJ toutes les mols (équivalent build_db, plus lent)
    python update_db.py --all
"""

import argparse
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
_GEN_ROOT = _PROJECT_ROOT / "non_benzenoid_generator"
ROOT_REL = "cluster_results/h9"

THRESHOLD_DEG = 10.0
_PLAN = {}

def _load_planarity():
    if _PLAN:
        return
    spec = importlib.util.spec_from_file_location(
        "gen_planarity", str(_GEN_ROOT / "utils" / "planarity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _PLAN["compute_planarity"] = mod.compute_planarity
    _PLAN["is_planar"] = mod.is_planar


def read_xyz_coords(p):
    coords = []
    try:
        with open(p) as f:
            lines = f.readlines()
    except OSError:
        return coords
    if len(lines) < 3:
        return coords
    try:
        n = int(lines[0].strip())
    except ValueError:
        return coords
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                pass
    return coords


def test_planarity(p):
    c = read_xyz_coords(str(p))
    if len(c) < 3:
        return None
    _load_planarity()
    m = _PLAN["compute_planarity"](c)
    return {
        "planar": _PLAN["is_planar"](m, THRESHOLD_DEG),
        "angle_deg": float(m["max_angle_deg"]),
        "rmsd": float(m["rmsd_plane"]),
        "height": float(m["height"]),
    }


def parse_sol_dirname(name):
    if not name.startswith("sol_"):
        return None, None
    parts = name.split("_")
    if len(parts) < 3:
        return None, None
    try:
        idx = int(parts[1])
    except ValueError:
        return None, None
    sizes_str = "_".join(parts[2:])
    return idx, sizes_str


def rescan_one(conn, config, mol):
    mol_dir = _PROJECT_ROOT / ROOT_REL / config / mol
    if not mol_dir.is_dir():
        print(f"  [SKIP] mol_dir absent : {mol_dir}")
        return False

    # Lecture job_status (peut avoir bougé après re-run)
    js = mol_dir / "job_status.json"
    job_status = None
    job_duration = None
    n_solutions_csp = None
    if js.is_file():
        try:
            jj = json.loads(js.read_text(encoding="utf-8"))
            job_status = jj.get("status")
            job_duration = jj.get("duration_sec")
            n_solutions_csp = jj.get("n_solutions")
        except (OSError, json.JSONDecodeError):
            pass

    orig_opt = mol_dir / f"{mol}_original_opt.xyz"
    original_planar = None
    original_angle = None
    if orig_opt.is_file():
        plan = test_planarity(orig_opt)
        if plan is not None:
            original_planar = 1 if plan["planar"] else 0
            original_angle = plan["angle_deg"]

    # Wipe puis re-insert
    conn.execute(
        "DELETE FROM solutions WHERE config = ? AND mol = ?",
        (config, mol),
    )

    sol_root = mol_dir / "solutions"
    n_md = 0
    n_geom_infeasible = 0
    n_xtb_failed = 0
    n_plans = 0
    n_non_plans = 0
    min_a = None
    max_a = None

    if sol_root.is_dir():
        rows = []
        for sol_dir in sorted(sol_root.iterdir()):
            if not sol_dir.is_dir():
                continue
            idx, sizes = parse_sol_dirname(sol_dir.name)
            if idx is None:
                continue
            source_xyz = sol_dir / "source.xyz"
            final_xyz = sol_dir / "md_validation" / "md_final_opt.xyz"
            if not final_xyz.is_file():
                if not source_xyz.is_file():
                    n_geom_infeasible += 1
                else:
                    n_xtb_failed += 1
                continue
            plan = test_planarity(final_xyz)
            if plan is None:
                n_xtb_failed += 1
                continue
            n_md += 1
            angle = plan["angle_deg"]
            planar = 1 if plan["planar"] else 0
            if planar:
                n_plans += 1
            else:
                n_non_plans += 1
            if min_a is None or angle < min_a:
                min_a = angle
            if max_a is None or angle > max_a:
                max_a = angle

            n_attempts = None
            det = None
            meta_p = sol_dir / "md_validation" / "md_meta.json"
            if meta_p.is_file():
                try:
                    md_meta = json.loads(meta_p.read_text(encoding="utf-8"))
                    n_attempts = md_meta.get("n_attempts")
                    d = md_meta.get("deterministic")
                    if d is not None:
                        det = 1 if d else 0
                except (OSError, json.JSONDecodeError):
                    pass

            sol_dir_rel = str(sol_dir.relative_to(_PROJECT_ROOT)).replace("\\", "/")
            rows.append((
                config, mol, idx, sizes, planar,
                angle, plan["rmsd"], plan["height"],
                n_attempts, det, sol_dir_rel,
            ))
        if rows:
            conn.executemany(
                "INSERT INTO solutions "
                "(config, mol, sol_idx, sizes, planar, angle_deg, rmsd, height, "
                " n_attempts, deterministic, sol_dir) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    # MAJ molecule
    conn.execute(
        "INSERT OR REPLACE INTO molecules "
        "(config, mol, n_solutions_csp, n_md_completed, "
        " n_geom_infeasible, n_xtb_failed, "
        " n_plans, n_non_plans, "
        " min_angle, max_angle, original_planar, original_angle_deg, "
        " job_status, job_duration_sec) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (config, mol, n_solutions_csp, n_md,
         n_geom_infeasible, n_xtb_failed,
         n_plans, n_non_plans,
         min_a, max_a, original_planar, original_angle,
         job_status, job_duration),
    )
    return True


def refresh_config_stats(conn, config):
    r = conn.execute(
        "SELECT COUNT(*) AS n_mols, "
        "       COALESCE(SUM(n_md_completed), 0) AS n_sols, "
        "       COALESCE(SUM(n_geom_infeasible), 0) AS n_geom, "
        "       COALESCE(SUM(n_plans), 0) AS n_plans, "
        "       COALESCE(SUM(n_non_plans), 0) AS n_non_plans "
        "FROM molecules WHERE config = ?",
        (config,),
    ).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO configs "
        "(name, n_molecules, n_solutions, n_geom_infeasible, n_plans, n_non_plans) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (config, r[0], r[1], r[2], r[3], r[4]),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_HERE / "h9.db"))
    ap.add_argument("--config")
    ap.add_argument("--mol")
    ap.add_argument("--from-tsv",
                    help="TSV avec colonnes 'config' et 'mol' (header attendu)")
    ap.add_argument("--all-partials", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if not Path(args.db).is_file():
        print(f"ERREUR : DB introuvable : {args.db}")
        return

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    targets = []
    if args.config and args.mol:
        targets = [(args.config, args.mol)]
    elif args.from_tsv:
        with open(args.from_tsv, encoding="utf-8") as f:
            header = f.readline().strip().split("\t")
            i_cfg = header.index("config")
            i_mol = header.index("mol")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                targets.append((parts[i_cfg], parts[i_mol]))
    elif args.all_partials:
        rows = conn.execute(
            "SELECT config, mol FROM molecules "
            "WHERE n_solutions_csp > n_md_completed "
            "ORDER BY config, mol"
        ).fetchall()
        targets = [(r["config"], r["mol"]) for r in rows]
    elif args.all:
        rows = conn.execute(
            "SELECT config, mol FROM molecules ORDER BY config, mol"
        ).fetchall()
        targets = [(r["config"], r["mol"]) for r in rows]
    else:
        ap.error("rien à faire — précise --config/--mol, --from-tsv, "
                 "--all-partials ou --all")

    print(f"=== {len(targets)} (config, mol) à rescanner ===")
    affected_cfgs = set()
    t0 = time.time()
    for i, (cfg, mol) in enumerate(targets, 1):
        ok = rescan_one(conn, cfg, mol)
        if ok:
            affected_cfgs.add(cfg)
        if i % 20 == 0 or i == len(targets):
            conn.commit()
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(targets) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(targets)}]  ({rate:.1f} mol/s, eta {eta/60:.1f} min)")
    conn.commit()

    for cfg in sorted(affected_cfgs):
        refresh_config_stats(conn, cfg)
    conn.commit()

    elapsed = (time.time() - t0) / 60
    print(f"\nTermine en {elapsed:.1f} min. Configs MAJ : {len(affected_cfgs)}")
    conn.close()


if __name__ == "__main__":
    main()
