"""Integre le corpus pre-calcule (corpus_only_for_chimiste.db) dans le
designer.db du container, SANS toucher aux jobs/solutions deja crees par
le designer (tables designer_jobs, designer_solutions, designer_xyz_files,
designer_collections, designer_neighbor_tables, xtb_cache).

A executer DANS le container (voir INSTRUCTIONS.md a cote de ce fichier).

Ce script est idempotent pour les tables corpus (relancer apres un nouvel
envoi de corpus_only_for_chimiste.db mis a jour re-remplace le corpus sans
toucher aux jobs), mais n'est pas concu pour fusionner deux corpus entre
eux (un seul appel par mise a jour de corpus).
"""

import argparse
import sqlite3
import sys
import time

CORPUS_TABLES = [
    "final_runs",
    "final_solutions",
    "configs",
    "molecules",
    "solutions",
    "sol_features",
    "sol_features_c9",
    "sol_motif_features",
    "sol_combined_features",
]


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=?", (name,)
    ).fetchone() is not None


def _get_type(conn, name):
    r = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (name,)
    ).fetchone()
    return r[0] if r else None


def _migrate_existing_xyz_table(conn):
    """Si xyz_files est deja une TABLE (contient les XYZ que le designer a
    generes localement), deplace son contenu vers designer_xyz_files avant
    de la remplacer par la VIEW corpus. Si c'est deja une VIEW (corpus deja
    integre precedemment), ne fait rien."""
    typ = _get_type(conn, "xyz_files")
    if typ is None:
        print("  xyz_files absente : rien a migrer.")
        return
    if typ == "view":
        print("  xyz_files est deja une VIEW (corpus deja integre) : rien a migrer.")
        return

    n_src = conn.execute("SELECT COUNT(*) FROM xyz_files").fetchone()[0]
    print(f"  xyz_files est une TABLE avec {n_src} lignes -> migration vers designer_xyz_files")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS designer_xyz_files (
            rel_path   TEXT PRIMARY KEY,
            content_gz BLOB NOT NULL,
            size_raw   INTEGER NOT NULL
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO designer_xyz_files (rel_path, content_gz, size_raw)
        SELECT rel_path, content_gz, size_raw FROM xyz_files
    """)
    conn.execute("DROP TABLE xyz_files")
    conn.commit()
    n_dst = conn.execute("SELECT COUNT(*) FROM designer_xyz_files").fetchone()[0]
    print(f"  -> migration OK (designer_xyz_files contient maintenant {n_dst} lignes au total)")


def _copy_corpus_tables(conn, source_path):
    print(f"  ATTACH DATABASE '{source_path}' AS src")
    conn.execute("ATTACH DATABASE ? AS src", (source_path,))
    try:
        src_tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM src.sqlite_master WHERE type='table'"
            )
        }
        for t in CORPUS_TABLES:
            if t not in src_tables:
                print(f"  [SKIP] table '{t}' absente de la source.")
                continue
            if _table_exists(conn, t) and _get_type(conn, t) != "view":
                n_existing = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                if n_existing:
                    print(f"  '{t}' existe deja avec {n_existing} lignes -> remplacement (DROP+recreate) pour la mise a jour du corpus")
                    conn.execute(f"DROP TABLE {t}")
            t0 = time.perf_counter()
            create_sql = conn.execute(
                "SELECT sql FROM src.sqlite_master WHERE name=? AND type='table'", (t,)
            ).fetchone()
            if create_sql and create_sql[0] and not _table_exists(conn, t):
                conn.execute(create_sql[0])
            conn.execute(f"INSERT INTO {t} SELECT * FROM src.{t}")
            conn.commit()
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  '{t}' : {n} lignes en place ({time.perf_counter()-t0:.1f}s)")
    finally:
        conn.execute("DETACH DATABASE src")


def _create_xyz_view(conn):
    conn.execute("DROP VIEW IF EXISTS xyz_files")
    conn.execute("""
        CREATE VIEW xyz_files AS
        SELECT
            'final/h' || size_h || '/' || config || '/' || graph_name
                || '/sol' || sol_index
                || '/md_validation/md_final_opt.xyz' AS rel_path,
            xyz_optimized_gz AS content_gz,
            COALESCE(LENGTH(xyz_optimized_gz), 0) AS size_raw
        FROM final_solutions
        WHERE status = 'done' AND xyz_optimized_gz IS NOT NULL
    """)
    n = conn.execute("SELECT COUNT(*) FROM xyz_files").fetchone()[0]
    print(f"  VIEW xyz_files recreee : {n} lignes visibles")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="/app/data/designer.db",
                     help="DB du volume designer a completer (defaut: /app/data/designer.db)")
    ap.add_argument("--source", required=True,
                     help="DB corpus recue (ex: /tmp/corpus.db)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.target, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    print("=== Etat AVANT (vos jobs designer) ===")
    for t in ["designer_jobs", "designer_solutions"]:
        if _table_exists(conn, t):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n} lignes")

    print("\n[1/3] Preservation des XYZ deja generes...")
    _migrate_existing_xyz_table(conn)

    print("\n[2/3] Copie du corpus recu...")
    _copy_corpus_tables(conn, args.source)

    print("\n[3/3] Activation de l'explorateur (VIEW xyz_files)...")
    _create_xyz_view(conn)

    print("\n=== Etat APRES (verification : vos jobs designer doivent etre INCHANGES) ===")
    for t in ["designer_jobs", "designer_solutions"]:
        if _table_exists(conn, t):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n} lignes")

    conn.close()
    print("\n=== TERMINE : redemarrez le container pour voir l'explorateur (/explorer) ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERREUR : {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
