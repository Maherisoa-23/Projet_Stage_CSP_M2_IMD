"""Post-traitement : calcul Clar A + Clar B + RBO sur toutes les sols done.

Multiprocessing local (N workers). Lit batch de sols depuis DB, calcule
en parallel, commit batch UPDATE.

Colonnes DB ajoutees (ALTER TABLE idempotent) :
  clar_a          INTEGER  : nb sextets Option A (hex uniquement, Huckel n=1 neutre)
  clar_b          INTEGER  : nb sextets Option B (hex + pent-anion + hept-cation)
  clar_b_hex      INTEGER  : nb d'hex dans la couverture Option B
  clar_b_pent     INTEGER  : nb de pent (anion implicite) dans Option B
  clar_b_hept     INTEGER  : nb de hept (cation implicite) dans Option B
  n_kekule        INTEGER  : nb de structures Kekule enumerees
  is_biradical    INTEGER  : 1 si molecule radicalaire (pas de Kekule stricte)
  rbo_avg         REAL     : moyenne des bond_orders Pauling-Randic
                             (NULL si biradical)
  compute_error   TEXT     : message d'erreur si echec du calcul (NULL sinon)
"""

import argparse
import gzip
import multiprocessing
import sqlite3
import sys
import time
from pathlib import Path


# ====== Worker (process pool) ======

def _init_worker():
    """Init du worker process : imports lourds une fois."""
    global _build_mol_graph_from_text, _enumerate_clar_covers, _compute_rbo
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "viewer"))
    from molviz.bonds import build_mol_graph_from_text
    from molviz.clar import enumerate_clar_covers
    from molviz.rbo import compute_rbo
    _build_mol_graph_from_text = build_mol_graph_from_text
    _enumerate_clar_covers = enumerate_clar_covers
    _compute_rbo = compute_rbo


def _process_sol(row):
    """Calcule Clar A / Clar B / RBO pour une sol. Retourne tuple pour UPDATE."""
    sol_id, xyz_gz = row
    try:
        xyz = gzip.decompress(xyz_gz).decode("utf-8")
        mol = _build_mol_graph_from_text(xyz)
        if not mol.atoms or not mol.bonds:
            return (sol_id, None, None, None, None, None, None, None, None, "empty_mol")

        # Clar A : hex uniquement
        covers_a, _ = _enumerate_clar_covers(mol, max_count=5, include_huckel_4n2=False)
        clar_a = covers_a[0].n_sextets if covers_a else 0

        # Clar B : hex + pent + hept
        covers_b, _ = _enumerate_clar_covers(mol, max_count=5, include_huckel_4n2=True)
        if covers_b:
            cv = covers_b[0]
            clar_b = cv.n_sextets
            clar_b_hex = cv.n_hex_sextets
            clar_b_pent = cv.n_pent_sextets
            clar_b_hept = cv.n_hept_sextets
        else:
            clar_b = clar_b_hex = clar_b_pent = clar_b_hept = 0

        # RBO
        rbo = _compute_rbo(mol, max_count=10000)
        if rbo.available:
            n_kekule = rbo.n_kekule
            is_biradical = 0
            rbo_avg = (sum(rbo.bond_orders) / len(rbo.bond_orders)) if rbo.bond_orders else 0.0
        else:
            n_kekule = rbo.n_kekule
            is_biradical = 1 if rbo.n_radicals > 0 else 0
            rbo_avg = None  # pas de Kekule stricte

        return (sol_id, clar_a, clar_b, clar_b_hex, clar_b_pent, clar_b_hept,
                n_kekule, is_biradical, rbo_avg, None)
    except Exception as e:
        return (sol_id, None, None, None, None, None, None, None, None, f"{type(e).__name__}: {str(e)[:180]}")


# ====== Main (orchestrateur DB) ======

ALTER_COLUMNS = [
    ("clar_a", "INTEGER"),
    ("clar_b", "INTEGER"),
    ("clar_b_hex", "INTEGER"),
    ("clar_b_pent", "INTEGER"),
    ("clar_b_hept", "INTEGER"),
    ("n_kekule", "INTEGER"),
    ("is_biradical", "INTEGER"),
    ("rbo_avg", "REAL"),
    ("compute_error", "TEXT"),
]


def ensure_columns(conn):
    """Ajoute les colonnes de post-traitement si absentes. Idempotent."""
    cols_existing = {r[1] for r in conn.execute("PRAGMA table_info(final_solutions)").fetchall()}
    added = []
    for col, ty in ALTER_COLUMNS:
        if col not in cols_existing:
            conn.execute(f"ALTER TABLE final_solutions ADD COLUMN {col} {ty}")
            added.append(col)
    if added:
        print(f"  Colonnes ajoutees : {added}")
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-id", type=int, default=1)
    ap.add_argument("--workers", type=int, default=10,
                    help="Nb de processes (defaut 10, max=cpu_count-1)")
    ap.add_argument("--batch-size", type=int, default=500,
                    help="Sols par batch fetch+update")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limiter a N sols (pour test). Defaut: toutes les done.")
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip les sols qui ont deja clar_a renseigne")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")

    print(f"=== postprocess_clar_rbo START (workers={args.workers}, batch={args.batch_size}) ===")
    ensure_columns(conn)

    # Compter
    where_extra = " AND clar_a IS NULL" if args.only_missing else ""
    n_total = conn.execute(
        f"SELECT COUNT(*) FROM final_solutions WHERE run_id=? AND status='done'{where_extra}",
        (args.run_id,),
    ).fetchone()[0]
    if args.limit:
        n_total = min(n_total, args.limit)
    print(f"  Sols a traiter : {n_total}")

    if n_total == 0:
        print("Rien a faire.")
        return

    update_sql = (
        "UPDATE final_solutions SET "
        "  clar_a=?, clar_b=?, clar_b_hex=?, clar_b_pent=?, clar_b_hept=?, "
        "  n_kekule=?, is_biradical=?, rbo_avg=?, compute_error=? "
        "WHERE sol_id=?"
    )

    n_processed = 0
    n_errors = 0
    n_biradical = 0
    t_start = time.perf_counter()

    pool = multiprocessing.Pool(processes=args.workers, initializer=_init_worker)
    try:
        last_sol_id = 0
        while True:
            # Fetch batch (cursor pagination par sol_id)
            params = (args.run_id, last_sol_id)
            limit = args.batch_size
            if args.limit and (args.limit - n_processed) < limit:
                limit = args.limit - n_processed
            if limit <= 0:
                break
            rows = conn.execute(
                f"SELECT sol_id, xyz_optimized_gz FROM final_solutions "
                f"WHERE run_id=? AND status='done' AND sol_id > ?{where_extra} "
                f"ORDER BY sol_id LIMIT {limit}",
                params,
            ).fetchall()
            if not rows:
                break
            last_sol_id = rows[-1][0]

            # Process en pool
            results = pool.map(_process_sol, rows, chunksize=10)

            # Commit batch
            conn.execute("BEGIN IMMEDIATE")
            try:
                update_params = []
                for r in results:
                    sol_id = r[0]
                    update_params.append((r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], sol_id))
                    if r[9] is not None:  # error
                        n_errors += 1
                    elif r[7] == 1:  # is_biradical
                        n_biradical += 1
                conn.executemany(update_sql, update_params)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            n_processed += len(rows)
            dt = time.perf_counter() - t_start
            rate = n_processed / dt
            eta = (n_total - n_processed) / rate if rate > 0 else 0
            print(f"  {n_processed:>7}/{n_total} ({100*n_processed/n_total:5.1f}%)  "
                  f"rate={rate:.1f}/s  ETA={eta/60:.1f}min  "
                  f"err={n_errors} birad={n_biradical}", flush=True)

            if args.limit and n_processed >= args.limit:
                break
    finally:
        pool.close()
        pool.join()

    dt_tot = time.perf_counter() - t_start
    print(f"=== postprocess DONE : {n_processed} sols en {dt_tot/60:.1f}min "
          f"(err={n_errors}, biradical={n_biradical}) ===")
    conn.close()


if __name__ == "__main__":
    main()
