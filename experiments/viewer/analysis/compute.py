"""
Calcul batch des metriques topologiques sur db_v2.db.

Pour chaque solution avec verdict IN ('plan', 'non_plan') :
  1. Charge le xyz depuis xyz_files (fallback fs si necessaire)
  2. Construit le MolGraph
  3. Calcule :
       - matching max (assign_kekule)        -> n_radicals
       - enumeration Kekule (enumerate_kekule) -> n_kekule, is_exact
       - couvertures de Clar (enumerate_clar_covers) -> clar_number, n_clar_covers
       - RBO agrege (compute_rbo)            -> cbo_mean_*, cbo_max_*
       - contexte                            -> n_hex, n_pent, n_hept
  4. INSERT OR REPLACE dans topology_metrics

Idempotent : si une entree existe deja avec la meme compute_version,
on skip (sauf --force).

Usage :
    python -m experiments.viewer.analysis.compute --h h6
    python -m experiments.viewer.analysis.compute --h h6 --force
    python -m experiments.viewer.analysis.compute --h h6 --limit 100

Sortie stdout : progression + stats finales (combien calcules, combien
skippes, combien d'erreurs).
"""

import argparse
import datetime as _dt
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "experiments.viewer.analysis"

from . import __version__ as ANALYSIS_VERSION  # noqa: E402
from .loader import load_molgraph_from_solution  # noqa: E402
from ..molviz.bonds import MolGraph  # noqa: E402
from ..molviz.kekule import assign_kekule, enumerate_kekule  # noqa: E402
from ..molviz.rbo import compute_rbo, DEFAULT_MAX_KEKULE  # noqa: E402
from ..molviz.clar import enumerate_clar_covers  # noqa: E402


COMPUTE_VERSION = ANALYSIS_VERSION  # synchro avec le package
_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = _HERE.parent / "db_v2.db"
_SCHEMA_SQL = _HERE / "schema.sql"


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Applique schema.sql. Idempotent."""
    conn.executescript(_SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()


def _aggregate_cbo_by_size(mol: MolGraph, rbo_result):
    """Calcule (mean, max) du CBO pour les cycles de chaque taille (5, 6, 7).

    Retourne (mean_hex, max_hex, mean_pent, max_pent, mean_hept, max_hept)
    avec None pour les categories sans cycle de cette taille, ou si RBO
    n'est pas disponible.
    """
    if not rbo_result.available:
        return (None,) * 6
    by_size = {5: [], 6: [], 7: []}
    for cyc, val in zip(mol.cycles, rbo_result.cbo):
        if cyc.size in by_size:
            by_size[cyc.size].append(val)

    def stats(lst):
        if not lst:
            return None, None
        return (sum(lst) / len(lst)), max(lst)

    mean_hex, max_hex = stats(by_size[6])
    mean_pent, max_pent = stats(by_size[5])
    mean_hept, max_hept = stats(by_size[7])
    return mean_hex, max_hex, mean_pent, max_pent, mean_hept, max_hept


def compute_metrics(mol: MolGraph,
                    max_kekule: int = DEFAULT_MAX_KEKULE,
                    max_clar: int = 200) -> dict:
    """Calcule tous les indicateurs topologiques d'une molecule.

    Retourne un dict prepret a etre insere dans topology_metrics.
    Les colonnes h, config, mol, sol_idx, computed_at, compute_version
    sont a ajouter par l'appelant.
    """
    # 1. Matching max (1 echantillon, pour n_radicals)
    kekule_one = assign_kekule(mol)

    # 2. Enumeration Kekule (plafonnee)
    kekule_list, is_exact = enumerate_kekule(mol, max_count=max_kekule)
    n_kekule = len(kekule_list)
    n_radicals = len(kekule_one.radicals)  # invariant sur tous les matchings max

    # 3. Couvertures de Clar
    clar_covers, _clar_exact = enumerate_clar_covers(mol, max_count=max_clar)
    clar_number = clar_covers[0].n_sextets if clar_covers else 0
    n_clar_covers = len(clar_covers)

    # 4. RBO agrege par taille de cycle
    rbo = compute_rbo(mol, max_count=max_kekule)
    cbo_available = 1 if rbo.available else 0
    mean_hex, max_hex, mean_pent, max_pent, mean_hept, max_hept = \
        _aggregate_cbo_by_size(mol, rbo)

    # 5. Contexte
    n_hex = sum(1 for c in mol.cycles if c.size == 6)
    n_pent = sum(1 for c in mol.cycles if c.size == 5)
    n_hept = sum(1 for c in mol.cycles if c.size == 7)

    return {
        "n_kekule": int(n_kekule),
        "is_exact": int(bool(is_exact)),
        "n_radicals": int(n_radicals),
        "clar_number": int(clar_number),
        "n_clar_covers": int(n_clar_covers),
        "cbo_available": int(cbo_available),
        "cbo_mean_hex": mean_hex,
        "cbo_max_hex": max_hex,
        "cbo_mean_pent": mean_pent,
        "cbo_max_pent": max_pent,
        "cbo_mean_hept": mean_hept,
        "cbo_max_hept": max_hept,
        "n_hex": int(n_hex),
        "n_pent": int(n_pent),
        "n_hept": int(n_hept),
    }


_INSERT_SQL = """
INSERT OR REPLACE INTO topology_metrics
  (h, config, mol, sol_idx,
   n_kekule, is_exact, n_radicals, clar_number, n_clar_covers,
   cbo_available, cbo_mean_hex, cbo_max_hex, cbo_mean_pent, cbo_max_pent,
   cbo_mean_hept, cbo_max_hept,
   n_hex, n_pent, n_hept,
   computed_at, compute_version)
VALUES
  (:h, :config, :mol, :sol_idx,
   :n_kekule, :is_exact, :n_radicals, :clar_number, :n_clar_covers,
   :cbo_available, :cbo_mean_hex, :cbo_max_hex, :cbo_mean_pent, :cbo_max_pent,
   :cbo_mean_hept, :cbo_max_hept,
   :n_hex, :n_pent, :n_hept,
   :computed_at, :compute_version)
"""


def _already_computed(conn: sqlite3.Connection,
                      h: str, config: str, mol: str, sol_idx: int) -> bool:
    """True ssi (h,config,mol,sol_idx) est deja dans topology_metrics avec
    la compute_version courante."""
    row = conn.execute(
        "SELECT compute_version FROM topology_metrics "
        "WHERE h=? AND config=? AND mol=? AND sol_idx=?",
        (h, config, mol, sol_idx),
    ).fetchone()
    return row is not None and row[0] == COMPUTE_VERSION


def _iter_solutions(conn: sqlite3.Connection,
                    h: Optional[str],
                    limit: Optional[int]):
    """Itere sur les solutions a calculer (verdict IN plan/non_plan)."""
    sql = (
        "SELECT h, config, mol, sol_idx, sol_dir "
        "FROM solutions "
        "WHERE verdict IN ('plan', 'non_plan')"
    )
    params = []
    if h is not None:
        sql += " AND h = ?"
        params.append(h)
    sql += " ORDER BY h, config, mol, sol_idx"
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    yield from conn.execute(sql, params)


def batch_compute(db_path: Path,
                  h: Optional[str] = None,
                  force: bool = False,
                  limit: Optional[int] = None,
                  fallback_fs: bool = True,
                  verbose: bool = True) -> dict:
    """Lance le calcul batch sur la DB.

    Args:
        db_path : chemin de la DB sqlite (db_v2.db)
        h       : si fourni, ne traite que les solutions de cet h
        force   : si True, recalcule meme les entrees deja a jour
        limit   : si fourni, ne traite que les N premieres solutions
        fallback_fs : si True, fallback filesystem en cas d'absence xyz_files
        verbose : print progression

    Returns:
        dict avec n_processed, n_skipped, n_errors, elapsed_sec.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    # On ouvre une transaction explicite pour commits par batch (perf)
    BATCH_COMMIT = 200

    n_processed = 0
    n_skipped = 0
    n_errors = 0
    n_missing_xyz = 0

    t0 = time.monotonic()
    last_log = t0
    LOG_INTERVAL_SEC = 5.0

    rows = list(_iter_solutions(conn, h, limit))
    total = len(rows)
    if verbose:
        scope = f"h={h}" if h else "tous"
        print(f"[compute] {total} solutions a evaluer ({scope})")
        if limit:
            print(f"[compute] limit={limit}")

    write_conn = sqlite3.connect(str(db_path))
    write_conn.execute("PRAGMA journal_mode = WAL")
    write_conn.execute("PRAGMA synchronous = NORMAL")

    pending = []
    for row in rows:
        h_, config_, mol_, sol_idx_, sol_dir_ = (
            row["h"], row["config"], row["mol"], row["sol_idx"], row["sol_dir"]
        )

        # Skip si deja calcule avec la version courante (sauf --force)
        if not force and _already_computed(conn, h_, config_, mol_, sol_idx_):
            n_skipped += 1
            continue

        mol_graph = load_molgraph_from_solution(
            conn, sol_dir_, fallback_filesystem=fallback_fs)
        if mol_graph is None:
            n_missing_xyz += 1
            continue

        try:
            metrics = compute_metrics(mol_graph)
        except Exception as e:  # garde-fou : un calcul ne doit pas casser le batch
            n_errors += 1
            if verbose and n_errors <= 5:
                print(f"  ERROR {h_}/{config_}/{mol_}/sol_{sol_idx_}: "
                      f"{e.__class__.__name__}: {e}")
                traceback.print_exc(limit=2)
            continue

        metrics.update({
            "h": h_,
            "config": config_,
            "mol": mol_,
            "sol_idx": sol_idx_,
            "computed_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "compute_version": COMPUTE_VERSION,
        })
        pending.append(metrics)
        n_processed += 1

        if len(pending) >= BATCH_COMMIT:
            write_conn.executemany(_INSERT_SQL, pending)
            write_conn.commit()
            pending.clear()

        # Logging periodique
        now = time.monotonic()
        if verbose and (now - last_log) > LOG_INTERVAL_SEC:
            done = n_processed + n_skipped + n_missing_xyz + n_errors
            rate = n_processed / (now - t0) if (now - t0) > 0 else 0
            eta = (total - done) / rate if rate > 0 else float("inf")
            print(f"  [{done}/{total}] processed={n_processed} "
                  f"skipped={n_skipped} missing_xyz={n_missing_xyz} "
                  f"errors={n_errors}  rate={rate:.1f}/s  eta={eta:.0f}s")
            last_log = now

    # Flush final
    if pending:
        write_conn.executemany(_INSERT_SQL, pending)
        write_conn.commit()
        pending.clear()

    elapsed = time.monotonic() - t0
    stats = {
        "n_processed": n_processed,
        "n_skipped": n_skipped,
        "n_missing_xyz": n_missing_xyz,
        "n_errors": n_errors,
        "n_total": total,
        "elapsed_sec": elapsed,
    }
    if verbose:
        print(f"[compute] DONE in {elapsed:.1f}s : "
              f"processed={n_processed}, skipped={n_skipped}, "
              f"missing_xyz={n_missing_xyz}, errors={n_errors}")
    conn.close()
    write_conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB),
                        help="chemin de la DB (par defaut db_v2.db)")
    parser.add_argument("--h", default=None,
                        help="ne calcule que ce h (ex. h6). Default = tous.")
    parser.add_argument("--force", action="store_true",
                        help="recalcule meme les entrees deja a jour")
    parser.add_argument("--limit", type=int, default=None,
                        help="ne calcule que les N premieres solutions")
    parser.add_argument("--no-fs", action="store_true",
                        help="desactive le fallback filesystem")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR : DB introuvable : {db_path}")
        sys.exit(1)

    stats = batch_compute(
        db_path=db_path,
        h=args.h,
        force=args.force,
        limit=args.limit,
        fallback_fs=not args.no_fs,
    )
    sys.exit(0 if stats["n_errors"] == 0 else 1)


if __name__ == "__main__":
    main()
