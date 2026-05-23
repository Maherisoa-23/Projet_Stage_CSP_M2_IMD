"""finalize_v3 : merge tous les worker DBs (output_root/worker_dbs/*.db)
dans db_v4.db.

Strategie : ATTACH DATABASE + INSERT OR REPLACE (idem v2). Idempotent.

Differences vs finalize_v2 :
  - schema v3 (avec decision_path, mmff_angle_deg sur solutions ;
    n_mmff_sure_plan, n_mmff_sure_non_plan, n_mmff_gray sur molecules)
  - db cible par defaut : db_v4.db (pour ne pas ecraser db_v3 si elle existe)

Usage :
    python -m csp_solver.experiments_v3.cluster.finalize \\
        --workers-dir /home/.../output/worker_dbs \\
        --db /home/.../csp_solver/experiments/csp_viewer/db_v4.db \\
        [--delete-after-merge]
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[3]))
    __package__ = "csp_solver.experiments_v3.cluster"

from ..db_helpers import SCHEMA_SQL  # noqa: E402


def init_main_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.commit()
    return conn


def merge_one(main_conn: sqlite3.Connection, worker_db: Path) -> dict:
    """Copie molecules + solutions + xyz_files dans main_conn.

    On utilise les listes explicites de colonnes pour eviter les SELECT *
    sensibles a l'ordre du schema.
    """
    main_conn.execute("ATTACH DATABASE ? AS w", (str(worker_db),))
    try:
        # molecules
        cur1 = main_conn.execute(
            "INSERT OR REPLACE INTO molecules "
            "(h, config, mol, n_solutions_csp, n_md_completed, "
            "n_geom_infeasible, n_xtb_failed, n_plans, n_non_plans, "
            "n_mmff_sure_plan, n_mmff_sure_non_plan, n_mmff_gray, "
            "min_angle, max_angle, original_planar, original_angle_deg, "
            "job_status, job_duration_sec) "
            "SELECT h, config, mol, n_solutions_csp, n_md_completed, "
            "n_geom_infeasible, n_xtb_failed, n_plans, n_non_plans, "
            "n_mmff_sure_plan, n_mmff_sure_non_plan, n_mmff_gray, "
            "min_angle, max_angle, original_planar, original_angle_deg, "
            "job_status, job_duration_sec FROM w.molecules"
        )
        n_mols = cur1.rowcount

        # solutions : supprimer les anciennes (h, config, mol) puis copier
        main_conn.execute("""
            DELETE FROM solutions WHERE (h, config, mol) IN (
                SELECT DISTINCT h, config, mol FROM w.solutions
            )
        """)
        cur2 = main_conn.execute(
            "INSERT INTO solutions "
            "(h, config, mol, sol_idx, sizes, verdict, "
            "planar, angle_deg, rmsd, height, "
            "n_attempts, deterministic, sol_dir, "
            "decision_path, mmff_angle_deg) "
            "SELECT h, config, mol, sol_idx, sizes, verdict, "
            "planar, angle_deg, rmsd, height, "
            "n_attempts, deterministic, sol_dir, "
            "decision_path, mmff_angle_deg FROM w.solutions"
        )
        n_sols = cur2.rowcount

        cur3 = main_conn.execute(
            "INSERT OR REPLACE INTO xyz_files "
            "SELECT * FROM w.xyz_files"
        )
        n_xyz = cur3.rowcount
        main_conn.commit()
    finally:
        main_conn.execute("DETACH DATABASE w")
    return {"n_molecules": n_mols, "n_solutions": n_sols, "n_xyz": n_xyz}


def rebuild_configs_table(main_conn: sqlite3.Connection):
    main_conn.execute("DELETE FROM configs")
    main_conn.execute("""
        INSERT INTO configs (h, name, n_molecules, n_solutions,
                              n_geom_infeasible, n_plans, n_non_plans)
        SELECT h, config,
               COUNT(*),
               COALESCE(SUM(n_md_completed), 0),
               COALESCE(SUM(n_geom_infeasible), 0),
               COALESCE(SUM(n_plans), 0),
               COALESCE(SUM(n_non_plans), 0)
        FROM molecules
        GROUP BY h, config
    """)
    main_conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers-dir", required=True)
    parser.add_argument("--db", required=True,
                        help="chemin de la db_v4.db a creer/mettre a jour")
    parser.add_argument("--delete-after-merge", action="store_true")
    args = parser.parse_args()

    workers_dir = Path(args.workers_dir)
    db_path = Path(args.db)

    if not workers_dir.is_dir():
        print(f"ERR : workers-dir introuvable : {workers_dir}", file=sys.stderr)
        sys.exit(1)

    worker_files = sorted(workers_dir.glob("*.db"))
    if not worker_files:
        print(f"[finalize_v3] aucun worker_*.db dans {workers_dir}")
        sys.exit(0)

    print(f"[finalize_v3] {len(worker_files)} workers a merger -> {db_path}")
    main_conn = init_main_db(db_path)

    t0 = time.monotonic()
    total = {"n_molecules": 0, "n_solutions": 0, "n_xyz": 0}
    n_failed = 0
    for i, wf in enumerate(worker_files, 1):
        try:
            stats = merge_one(main_conn, wf)
            for k in total:
                total[k] += stats[k]
            if i % 50 == 0 or i == len(worker_files):
                elapsed = time.monotonic() - t0
                print(f"  [{i}/{len(worker_files)}] +mol={total['n_molecules']} "
                      f"+sol={total['n_solutions']} +xyz={total['n_xyz']} "
                      f"({elapsed:.0f}s)")
        except sqlite3.Error as e:
            n_failed += 1
            print(f"  ECHEC [{wf.name}] : {e}", file=sys.stderr)
            continue
        if args.delete_after_merge:
            try:
                wf.unlink()
            except OSError as e:
                print(f"  WARN : suppression {wf.name} : {e}", file=sys.stderr)

    print(f"[finalize_v3] merge termine. Rebuild table configs ...")
    rebuild_configs_table(main_conn)

    print(f"[finalize_v3] DONE : {total['n_molecules']} mols, "
          f"{total['n_solutions']} sols, {total['n_xyz']} xyz copies. "
          f"{n_failed} workers en echec.")
    main_conn.close()
    sys.exit(0 if n_failed == 0 else 1)


if __name__ == "__main__":
    main()
