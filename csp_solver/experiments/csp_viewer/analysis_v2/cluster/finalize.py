"""
Finalize : merge tous les worker_*.db dans db_v2.solution_descriptors.

Approche : pour chaque worker DB, on attache (ATTACH DATABASE), on copie
les lignes via INSERT OR REPLACE, on detache. Pas de risque de
duplication (PRIMARY KEY).

Optionnellement, supprime les worker DBs apres merge reussi.

Usage :
    python -m csp_solver.experiments.csp_viewer.analysis_v2.cluster.finalize \\
        --db db_v2.db \\
        --workers-dir /tmp/analysis_v2_workers \\
        [--delete-after-merge]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[5]))
    __package__ = "csp_solver.experiments.csp_viewer.analysis_v2.cluster"


def ensure_main_schema(conn: sqlite3.Connection, schema_sql: str):
    conn.executescript(schema_sql)
    conn.commit()


def merge_worker(main_conn: sqlite3.Connection, worker_db: Path) -> int:
    """Copie toutes les lignes de worker_db.solution_descriptors vers
    main_conn.solution_descriptors. INSERT OR REPLACE (idempotent).
    Retourne le nb de lignes copiees."""
    # ATTACH puis INSERT INTO ... SELECT FROM
    main_conn.execute(f"ATTACH DATABASE ? AS w", (str(worker_db),))
    try:
        cur = main_conn.execute(
            "INSERT OR REPLACE INTO solution_descriptors "
            "SELECT * FROM w.solution_descriptors"
        )
        n = cur.rowcount
        main_conn.commit()
    finally:
        main_conn.execute("DETACH DATABASE w")
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--workers-dir", required=True)
    parser.add_argument("--delete-after-merge", action="store_true")
    parser.add_argument("--schema", default=None)
    args = parser.parse_args()

    workers_dir = Path(args.workers_dir)
    worker_files = sorted(workers_dir.glob("worker_*.db"))
    if not worker_files:
        print(f"[finalize] aucun worker_*.db trouve dans {workers_dir}")
        sys.exit(0)

    print(f"[finalize] {len(worker_files)} workers a merger dans {args.db}")

    schema_path = (Path(args.schema) if args.schema else
                   Path(__file__).resolve().parent.parent / "schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")

    main_conn = sqlite3.connect(args.db)
    ensure_main_schema(main_conn, schema_sql)
    main_conn.execute("PRAGMA journal_mode = WAL")

    total = 0
    n_failed = 0
    for wf in worker_files:
        try:
            n = merge_worker(main_conn, wf)
            total += n
            print(f"  [{wf.name}] +{n} lignes")
        except sqlite3.Error as e:
            n_failed += 1
            print(f"  ECHEC [{wf.name}] : {e}")
            continue
        if args.delete_after_merge:
            try:
                wf.unlink()
            except OSError as e:
                print(f"  WARNING : impossible de supprimer {wf.name} : {e}")

    print(f"[finalize] {total} lignes copiees, {n_failed} workers en echec")
    main_conn.close()
    sys.exit(0 if n_failed == 0 else 1)


if __name__ == "__main__":
    main()
