"""
Construit la base SQLite h9.db à partir de cluster_results/h9/.

Multiprocessing : un worker par molécule (config, mol). Chaque worker
calcule la planarité de tous ses sol_dirs et renvoie les rangées à insérer.
Le main process agrège et écrit dans SQLite (un seul writer pour éviter
les locks).

Usage :
    python build_db.py [--root cluster_results/h9] [--db h9.db]
                       [--limit N] [--processes K]

--limit N : ne traite que N (config, mol) au total — utile pour tests rapides.
"""

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
_GEN_ROOT = _PROJECT_ROOT / "non_benzenoid_generator"

# Import compute_planarity sans toucher au sys.path global
_plan_spec = importlib.util.spec_from_file_location(
    "gen_planarity", str(_GEN_ROOT / "utils" / "planarity.py"))
_plan_mod = importlib.util.module_from_spec(_plan_spec)
_plan_spec.loader.exec_module(_plan_mod)
compute_planarity = _plan_mod.compute_planarity
is_planar = _plan_mod.is_planar

THRESHOLD_DEG = 10.0


def read_xyz_coords(xyz_path):
    coords = []
    try:
        with open(xyz_path, "r") as f:
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


def test_planarity(xyz_path):
    coords = read_xyz_coords(str(xyz_path))
    if len(coords) < 3:
        return None
    metrics = compute_planarity(coords)
    return {
        "planar": is_planar(metrics, THRESHOLD_DEG),
        "angle_deg": float(metrics["max_angle_deg"]),
        "rmsd": float(metrics["rmsd_plane"]),
        "height": float(metrics["height"]),
    }


def parse_sol_dirname(name):
    """sol_<idx>_<sizes_underscore>  ->  (idx, sizes_underscore_to_blank)
    Ex : sol_1000_7_6_6_5_5_7_5_6_7  ->  (1000, '7_6_6_5_5_7_5_6_7')
    """
    if not name.startswith("sol_"):
        return None, None
    parts = name.split("_", 2)
    if len(parts) < 3:
        return None, None
    try:
        idx = int(parts[1])
    except ValueError:
        return None, None
    sizes = parts[2]
    return idx, sizes


def process_molecule(args):
    """Worker : traite une (config, mol). Retourne (mol_row, [sol_rows]).

    mol_row : tuple à insérer dans table 'molecules'
    sol_rows : liste de tuples à insérer dans 'solutions'
    """
    project_root, root_rel, config, mol = args
    project_root = Path(project_root)
    mol_dir = project_root / root_rel / config / mol

    # job_status.json
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

    # planarité de l'original
    orig_opt = mol_dir / f"{mol}_original_opt.xyz"
    original_planar = None
    original_angle = None
    if orig_opt.is_file():
        plan = test_planarity(orig_opt)
        if plan is not None:
            original_planar = 1 if plan["planar"] else 0
            original_angle = plan["angle_deg"]

    # solutions
    sol_root = mol_dir / "solutions"
    sol_rows = []
    n_md_completed = 0
    n_geom_infeasible = 0     # sol_dirs sans source.xyz (reconstruction echouee)
    n_xtb_failed = 0          # sol_dirs avec source.xyz mais sans md_final_opt
    n_plans = 0
    n_non_plans = 0
    min_angle = None
    max_angle = None

    if sol_root.is_dir():
        for sol_dir in sorted(sol_root.iterdir()):
            if not sol_dir.is_dir():
                continue
            idx, sizes = parse_sol_dirname(sol_dir.name)
            if idx is None:
                continue
            source_xyz = sol_dir / "source.xyz"
            final_xyz = sol_dir / "md_validation" / "md_final_opt.xyz"
            if not final_xyz.is_file():
                # Distinguer : pas de source.xyz du tout (reconstruction
                # ValueError, geometriquement infeasible) vs source.xyz
                # present mais xtb a echoue.
                if not source_xyz.is_file():
                    n_geom_infeasible += 1
                else:
                    n_xtb_failed += 1
                continue
            plan = test_planarity(final_xyz)
            if plan is None:
                n_xtb_failed += 1
                continue
            n_md_completed += 1
            planar = 1 if plan["planar"] else 0
            angle = plan["angle_deg"]
            if planar:
                n_plans += 1
            else:
                n_non_plans += 1
            if min_angle is None or angle < min_angle:
                min_angle = angle
            if max_angle is None or angle > max_angle:
                max_angle = angle

            # md_meta
            n_attempts = None
            deterministic = None
            meta_path = sol_dir / "md_validation" / "md_meta.json"
            if meta_path.is_file():
                try:
                    md_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    n_attempts = md_meta.get("n_attempts")
                    det = md_meta.get("deterministic")
                    if det is not None:
                        deterministic = 1 if det else 0
                except (OSError, json.JSONDecodeError):
                    pass

            sol_dir_rel = str(sol_dir.relative_to(project_root)).replace("\\", "/")
            sol_rows.append((
                config, mol, idx, sizes, planar,
                angle, plan["rmsd"], plan["height"],
                n_attempts, deterministic, sol_dir_rel,
            ))

    mol_row = (
        config, mol, n_solutions_csp, n_md_completed,
        n_geom_infeasible, n_xtb_failed,
        n_plans, n_non_plans,
        min_angle, max_angle,
        original_planar, original_angle,
        job_status, job_duration,
    )
    return mol_row, sol_rows


def discover_jobs(project_root, root_rel, limit=None):
    base = Path(project_root) / root_rel
    jobs = []
    for cfg_dir in sorted(base.iterdir()):
        if not cfg_dir.is_dir():
            continue
        config = cfg_dir.name
        for mol_dir in sorted(cfg_dir.iterdir()):
            if not mol_dir.is_dir():
                continue
            jobs.append((str(project_root), root_rel, config, mol_dir.name))
            if limit and len(jobs) >= limit:
                return jobs
    return jobs


def init_db(db_path, schema_path):
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="cluster_results/h9",
                    help="dossier racine relatif à la project root")
    ap.add_argument("--db", default=str(_HERE / "h9.db"),
                    help="chemin de la base sqlite à créer")
    ap.add_argument("--limit", type=int, default=None,
                    help="ne traite que N (config, mol) — pour debug")
    ap.add_argument("--processes", type=int,
                    default=max(1, (os.cpu_count() or 4) - 1))
    args = ap.parse_args()

    project_root = _PROJECT_ROOT
    db_path = Path(args.db)
    schema_path = _HERE / "schema.sql"

    print(f"Project root: {project_root}")
    print(f"Source      : {project_root / args.root}")
    print(f"DB          : {db_path}")
    print(f"Workers     : {args.processes}")

    print("Discovery des jobs ...")
    t0 = time.time()
    jobs = discover_jobs(project_root, args.root, args.limit)
    print(f"  {len(jobs)} (config, mol) à traiter ({time.time()-t0:.1f}s)")

    conn = init_db(db_path, schema_path)
    cur = conn.cursor()

    n_done = 0
    n_sols_total = 0
    t0 = time.time()
    print("Calcul de planarité + insertion ...")
    with mp.Pool(args.processes) as pool:
        for mol_row, sol_rows in pool.imap_unordered(
                process_molecule, jobs, chunksize=4):
            cur.execute(
                "INSERT INTO molecules "
                "(config, mol, n_solutions_csp, n_md_completed, "
                " n_geom_infeasible, n_xtb_failed, "
                " n_plans, n_non_plans, min_angle, max_angle, "
                " original_planar, original_angle_deg, "
                " job_status, job_duration_sec) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                mol_row,
            )
            if sol_rows:
                cur.executemany(
                    "INSERT INTO solutions "
                    "(config, mol, sol_idx, sizes, planar, "
                    " angle_deg, rmsd, height, n_attempts, "
                    " deterministic, sol_dir) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    sol_rows,
                )
            n_sols_total += len(sol_rows)
            n_done += 1
            if n_done % 100 == 0 or n_done == len(jobs):
                conn.commit()
                elapsed = time.time() - t0
                rate = n_done / elapsed if elapsed > 0 else 0
                eta = (len(jobs) - n_done) / rate if rate > 0 else 0
                print(f"  [{n_done}/{len(jobs)}] sols={n_sols_total}  "
                      f"({rate:.1f} mol/s, eta {eta/60:.1f} min)")
    conn.commit()

    # Résumé par config
    print("Calcul des stats par config ...")
    cur.execute("""
        INSERT OR REPLACE INTO configs
            (name, n_molecules, n_solutions, n_geom_infeasible, n_plans, n_non_plans)
        SELECT
            config,
            COUNT(*),
            COALESCE(SUM(n_md_completed), 0),
            COALESCE(SUM(n_geom_infeasible), 0),
            COALESCE(SUM(n_plans), 0),
            COALESCE(SUM(n_non_plans), 0)
        FROM molecules
        GROUP BY config
    """)
    conn.commit()

    # Affichage
    print("\nConfigs :")
    for row in cur.execute(
            "SELECT name, n_molecules, n_solutions, n_geom_infeasible, "
            "       n_plans, n_non_plans "
            "FROM configs ORDER BY name"):
        name, nm, ns, ngi, np, nnp = row
        pct = (100 * np / ns) if ns else 0
        print(f"  {name:35s} mols={nm:5d} valides={ns:7d} "
              f"infaisables={ngi:6d} plans={np:7d} ({pct:.1f}%)")

    conn.close()
    print(f"\nTermine en {(time.time()-t0)/60:.1f} min.")


if __name__ == "__main__":
    main()
