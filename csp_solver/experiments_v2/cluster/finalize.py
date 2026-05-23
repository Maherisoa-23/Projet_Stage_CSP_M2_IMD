"""
finalize_v2 : merge tous les worker DBs (output_root/worker_dbs/*.db)
dans db_v3.db.

Strategie : ATTACH DATABASE + INSERT OR REPLACE (cf analysis_v2/cluster/finalize).
Idempotent : peut etre re-lance, INSERT OR REPLACE evite les doublons.

Note speciale : la table `configs` agrege ses compteurs via la formule
"COALESCE(existing, 0) + delta". Comme chaque worker DB est UNE mol,
les somme totales doivent etre RECONSTRUITES en post-merge a partir de
SUM(...) sur molecules. On le fait dans une etape finale.

Usage :
    python -m csp_solver.experiments_v2.cluster.finalize \\
        --workers-dir /home/.../output/worker_dbs \\
        --db /home/.../csp_solver/experiments/csp_viewer/db_v3.db \\
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
    __package__ = "csp_solver.experiments_v2.cluster"

from ..db_helpers import SCHEMA_SQL  # noqa: E402


def init_main_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.commit()
    return conn


def merge_one(main_conn: sqlite3.Connection, worker_db: Path) -> dict:
    """Copie molecules + solutions + xyz_files du worker_db dans main_conn.
    Configs sera reconstruite globalement a la fin."""
    main_conn.execute("ATTACH DATABASE ? AS w", (str(worker_db),))
    try:
        # molecules : INSERT OR REPLACE (cle (h, config, mol))
        cur1 = main_conn.execute(
            "INSERT OR REPLACE INTO molecules "
            "SELECT * FROM w.molecules"
        )
        n_mols = cur1.rowcount
        # solutions : on supprime d'abord les anciennes du (h, config, mol)
        # pour eviter les doublons (auto-incremental id), puis on copie.
        # On utilise une jointure pour identifier les triplets a deleter.
        main_conn.execute("""
            DELETE FROM solutions WHERE (h, config, mol) IN (
                SELECT DISTINCT h, config, mol FROM w.solutions
            )
        """)
        cur2 = main_conn.execute(
            "INSERT INTO solutions "
            "(h, config, mol, sol_idx, sizes, verdict, "
            "planar, angle_deg, rmsd, height, "
            "n_attempts, deterministic, sol_dir) "
            "SELECT h, config, mol, sol_idx, sizes, verdict, "
            "planar, angle_deg, rmsd, height, "
            "n_attempts, deterministic, sol_dir FROM w.solutions"
        )
        n_sols = cur2.rowcount
        # xyz_files : PK = rel_path -> INSERT OR REPLACE
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
    """Reconstruit la table configs depuis SUM(molecules.*) groupees par (h, name)."""
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
    parser.add_argument("--workers-dir", required=True,
                        help="dossier contenant worker_dbs/*.db (en general "
                             "<output_root>/worker_dbs)")
    parser.add_argument("--db", required=True,
                        help="chemin de la db_v3.db a creer/mettre a jour")
    parser.add_argument("--delete-after-merge", action="store_true",
                        help="supprime les worker DBs apres merge OK")
    args = parser.parse_args()

    workers_dir = Path(args.workers_dir)
    db_path = Path(args.db)

    if not workers_dir.is_dir():
        print(f"ERR : workers-dir introuvable : {workers_dir}", file=sys.stderr)
        sys.exit(1)

    worker_files = sorted(workers_dir.glob("*.db"))
    if not worker_files:
        print(f"[finalize_v2] aucun worker_*.db dans {workers_dir}")
        sys.exit(0)

    print(f"[finalize_v2] {len(worker_files)} workers a merger -> {db_path}")
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

    print(f"[finalize_v2] merge termine. Rebuild table configs ...")
    rebuild_configs_table(main_conn)

    print(f"[finalize_v2] DONE : {total['n_molecules']} mols, "
          f"{total['n_solutions']} sols, {total['n_xyz']} xyz copies. "
          f"{n_failed} workers en echec.")
    main_conn.close()
    sys.exit(0 if n_failed == 0 else 1)


if __name__ == "__main__":
    main()
