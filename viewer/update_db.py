"""
Met a jour db_all.db pour un sous-ensemble de (h, config, mol), sans tout
re-scanner. Utile apres avoir modifie ciblement quelques mols (ex.
re-telechargement partiel du cluster).

Pour chaque (h, config, mol) ciblee, le script :
  1. Supprime les anciennes lignes de solutions correspondantes.
  2. Re-scanne les sol_dirs sur disque, calcule la planarite.
  3. Reinsere les lignes solutions et MAJ la ligne molecules.
  4. Recalcule la stat globale par (h, config).

Usage :
    # MAJ une mol precise
    python update_db.py --h h9 --config no-freeze_no-table \\
        --mol 0-10-19-20-27-28-29-37-38

    # MAJ toutes les mols d'un dataset
    python update_db.py --h h7 --all

    # MAJ tous les datasets
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

DEFAULT_ROOT_PATTERNS = [
    "cluster_results/{h}",
    "csp_solver/experiments/output/{h}",
    "_{h}_run/output/{h}",
]

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


def resolve_root_for_h(project_root, h_name, custom_pattern=None):
    patterns = [custom_pattern] if custom_pattern else DEFAULT_ROOT_PATTERNS
    for pat in patterns:
        if pat is None:
            continue
        candidate = Path(pat.format(h=h_name, H=h_name))
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.is_dir():
            return candidate
    return None


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
    return idx, "_".join(parts[2:])


def rescan_one(conn, root_abs, h_name, config, mol):
    mol_dir = root_abs / config / mol
    if not mol_dir.is_dir():
        print(f"  [SKIP] mol_dir absent : {mol_dir}")
        return False

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

    conn.execute(
        "DELETE FROM solutions WHERE h = ? AND config = ? AND mol = ?",
        (h_name, config, mol),
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

            try:
                sol_dir_rel = str(sol_dir.relative_to(_PROJECT_ROOT)).replace("\\", "/")
            except ValueError:
                sol_dir_rel = str(sol_dir).replace("\\", "/")

            if not final_xyz.is_file():
                if not source_xyz.is_file():
                    n_geom_infeasible += 1
                    rows.append((
                        h_name, config, mol, idx, sizes, "geom_infeasible",
                        None, None, None, None, None, None, sol_dir_rel,
                    ))
                else:
                    n_xtb_failed += 1
                    rows.append((
                        h_name, config, mol, idx, sizes, "xtb_failed",
                        None, None, None, None, None, None, sol_dir_rel,
                    ))
                continue
            plan = test_planarity(final_xyz)
            if plan is None:
                n_xtb_failed += 1
                rows.append((
                    h_name, config, mol, idx, sizes, "xtb_failed",
                    None, None, None, None, None, None, sol_dir_rel,
                ))
                continue
            n_md += 1
            angle = plan["angle_deg"]
            planar = 1 if plan["planar"] else 0
            verdict = "plan" if planar else "non_plan"
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

            rows.append((
                h_name, config, mol, idx, sizes, verdict,
                planar, angle, plan["rmsd"], plan["height"],
                n_attempts, det, sol_dir_rel,
            ))
        if rows:
            conn.executemany(
                "INSERT INTO solutions "
                "(h, config, mol, sol_idx, sizes, verdict, "
                " planar, angle_deg, rmsd, height, n_attempts, "
                " deterministic, sol_dir) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    conn.execute(
        "INSERT OR REPLACE INTO molecules "
        "(h, config, mol, n_solutions_csp, n_md_completed, "
        " n_geom_infeasible, n_xtb_failed, "
        " n_plans, n_non_plans, "
        " min_angle, max_angle, original_planar, original_angle_deg, "
        " job_status, job_duration_sec) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (h_name, config, mol, n_solutions_csp, n_md,
         n_geom_infeasible, n_xtb_failed,
         n_plans, n_non_plans,
         min_a, max_a, original_planar, original_angle,
         job_status, job_duration),
    )
    return True


def refresh_config_stats(conn, h_name, config):
    r = conn.execute(
        "SELECT COUNT(*) AS n_mols, "
        "       COALESCE(SUM(n_md_completed), 0) AS n_sols, "
        "       COALESCE(SUM(n_geom_infeasible), 0) AS n_geom, "
        "       COALESCE(SUM(n_plans), 0) AS n_plans, "
        "       COALESCE(SUM(n_non_plans), 0) AS n_non_plans "
        "FROM molecules WHERE h = ? AND config = ?",
        (h_name, config),
    ).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO configs "
        "(h, name, n_molecules, n_solutions, n_geom_infeasible, "
        " n_plans, n_non_plans) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (h_name, config, r[0], r[1], r[2], r[3], r[4]),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_HERE / "db_all.db"))
    ap.add_argument("--h", help="dataset (ex. h9)")
    ap.add_argument("--config")
    ap.add_argument("--mol")
    ap.add_argument("--all", action="store_true",
                    help="MAJ toutes les (h, config, mol) de la DB.")
    ap.add_argument("--root-pattern", default=None)
    args = ap.parse_args()

    if not Path(args.db).is_file():
        print(f"ERREUR : DB introuvable : {args.db}")
        return

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.h and args.config and args.mol:
        targets = [(args.h, args.config, args.mol)]
    elif args.h and args.all:
        rows = conn.execute(
            "SELECT h, config, mol FROM molecules WHERE h = ? "
            "ORDER BY config, mol", (args.h,)
        ).fetchall()
        targets = [(r["h"], r["config"], r["mol"]) for r in rows]
    elif args.all:
        rows = conn.execute(
            "SELECT h, config, mol FROM molecules ORDER BY h, config, mol"
        ).fetchall()
        targets = [(r["h"], r["config"], r["mol"]) for r in rows]
    else:
        ap.error("rien a faire -- precise --h --config --mol, ou --h --all, ou --all")
        return

    print(f"=== {len(targets)} (h, config, mol) a rescanner ===")

    # Cache des roots resolus par dataset
    roots_cache = {}
    def get_root(h):
        if h not in roots_cache:
            r = resolve_root_for_h(_PROJECT_ROOT, h, args.root_pattern)
            roots_cache[h] = r
        return roots_cache[h]

    affected = set()  # (h, config)
    t0 = time.time()
    for i, (h, cfg, mol) in enumerate(targets, 1):
        root = get_root(h)
        if root is None:
            print(f"  [SKIP] {h}/{cfg}/{mol} : root introuvable")
            continue
        if rescan_one(conn, root, h, cfg, mol):
            affected.add((h, cfg))
        if i % 50 == 0 or i == len(targets):
            conn.commit()
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(targets) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(targets)}]  ({rate:.1f} mol/s, eta {eta/60:.1f} min)")
    conn.commit()

    for h, cfg in sorted(affected):
        refresh_config_stats(conn, h, cfg)
    conn.commit()

    elapsed = (time.time() - t0) / 60
    print(f"\nTermine en {elapsed:.1f} min. (h, config) MAJ : {len(affected)}")
    conn.close()


if __name__ == "__main__":
    main()
