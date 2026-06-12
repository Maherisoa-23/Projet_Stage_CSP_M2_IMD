"""
Worker cluster : recoit un slice du manifest, calcule les descripteurs,
ecrit dans son propre sqlite local (worker_<slice_id>.db).

Pas de lock contention possible : chaque worker ecrit dans son fichier.
Le merge final est fait par finalize.py.

Usage :
    python -m viewer.analysis_v2.cluster.worker \\
        --db /path/to/db_v2.db \\
        --manifest /path/to/manifest.jsonl \\
        --slice-ids 12,13,14 \\
        --output-dir /tmp/analysis_v2_workers

Sortie :
  /tmp/analysis_v2_workers/worker_<slice_id>.db   (par slice)
  /tmp/analysis_v2_workers/worker_<slice_id>.log  (log + stats)

Si --slice-ids absent, traite TOUTES les slices du manifest (mode single-machine).
"""

import argparse
import datetime as _dt
import gzip
import json
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Iterable, Set

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "viewer.analysis_v2.cluster"

from .. import __version__ as ANALYSIS_VERSION  # noqa: E402
from ..compute_one import compute_all_descriptors  # noqa: E402
from ...molviz.bonds import build_mol_graph_from_text  # noqa: E402


COMPUTE_VERSION = ANALYSIS_VERSION


_INSERT_SQL = """
INSERT OR REPLACE INTO solution_descriptors (
    h, config, mol, sol_idx,
    n_pent, n_hex, n_hept, n_cycles_total,
    n_55, n_57, n_56, n_66, n_67, n_77,
    n_azulene_units, n_stone_wales, n_3_fused_atoms,
    dual_diameter, dual_radius, dual_max_degree, dual_n_components,
    n_boundary_atoms, n_interior_atoms, boundary_length,
    n_solo, n_duo, n_trio, n_quatuor, n_groups_5plus,
    irregularity_param,
    n_pent_at_boundary, n_hept_at_boundary, n_hex_at_boundary,
    pent_boundary_ratio, hept_boundary_ratio,
    max_angle_deg, buckling_height, radius_of_gyration, aspect_ratio,
    convex_hull_area, curvature_discrete_mean, curvature_discrete_max,
    n_atoms_above_plane, n_atoms_below_plane, plane_asymmetry,
    n_kekule, is_exact, n_radicals,
    clar_number, n_clar_covers,
    cbo_available,
    cbo_mean_hex, cbo_max_hex, cbo_mean_pent, cbo_max_pent,
    cbo_mean_hept, cbo_max_hept,
    radical_on_pent_freq, radical_on_hex_freq, radical_on_hept_freq,
    radical_at_boundary_freq,
    n_aromatic_islands, largest_aromatic_island,
    aromatic_planarity_score, radical_planarity_score,
    computed_at, compute_version
) VALUES (
    :h, :config, :mol, :sol_idx,
    :n_pent, :n_hex, :n_hept, :n_cycles_total,
    :n_55, :n_57, :n_56, :n_66, :n_67, :n_77,
    :n_azulene_units, :n_stone_wales, :n_3_fused_atoms,
    :dual_diameter, :dual_radius, :dual_max_degree, :dual_n_components,
    :n_boundary_atoms, :n_interior_atoms, :boundary_length,
    :n_solo, :n_duo, :n_trio, :n_quatuor, :n_groups_5plus,
    :irregularity_param,
    :n_pent_at_boundary, :n_hept_at_boundary, :n_hex_at_boundary,
    :pent_boundary_ratio, :hept_boundary_ratio,
    :max_angle_deg, :buckling_height, :radius_of_gyration, :aspect_ratio,
    :convex_hull_area, :curvature_discrete_mean, :curvature_discrete_max,
    :n_atoms_above_plane, :n_atoms_below_plane, :plane_asymmetry,
    :n_kekule, :is_exact, :n_radicals,
    :clar_number, :n_clar_covers,
    :cbo_available,
    :cbo_mean_hex, :cbo_max_hex, :cbo_mean_pent, :cbo_max_pent,
    :cbo_mean_hept, :cbo_max_hept,
    :radical_on_pent_freq, :radical_on_hex_freq, :radical_on_hept_freq,
    :radical_at_boundary_freq,
    :n_aromatic_islands, :largest_aromatic_island,
    :aromatic_planarity_score, :radical_planarity_score,
    :computed_at, :compute_version
)
"""


def _xyz_relpath(sol_dir: str) -> str:
    return sol_dir.replace("\\", "/").rstrip("/") + "/md_validation/md_final_opt.xyz"


def _load_xyz_text(conn: sqlite3.Connection, rel_path: str):
    row = conn.execute(
        "SELECT content_gz FROM xyz_files WHERE rel_path = ?",
        (rel_path,)
    ).fetchone()
    if row is None:
        return None
    try:
        return gzip.decompress(row[0]).decode("utf-8", errors="replace")
    except (OSError, EOFError):
        return None


def _create_worker_db(path: Path, schema_sql: str) -> sqlite3.Connection:
    """Cree un sqlite local pour ce worker (mini-DB avec juste la table
    solution_descriptors). Reutilise le schema.sql du package."""
    conn = sqlite3.connect(str(path))
    conn.executescript(schema_sql)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def process_slice(db_path: Path,
                   slice_data: dict,
                   worker_db_path: Path,
                   schema_sql: str,
                   verbose: bool = True) -> dict:
    """Traite un slice : charge les rowids, calcule, ecrit dans worker DB."""
    slice_id = slice_data["slice_id"]
    h = slice_data["h"]
    rowids = slice_data["rowids"]

    main_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    main_conn.row_factory = sqlite3.Row
    worker_conn = _create_worker_db(worker_db_path, schema_sql)

    n_processed = 0
    n_missing = 0
    n_errors = 0
    pending = []
    BATCH = 100

    t0 = time.monotonic()
    now_str = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for rid in rowids:
        row = main_conn.execute(
            "SELECT h, config, mol, sol_idx, sol_dir "
            "FROM solutions WHERE rowid = ?",
            (rid,)
        ).fetchone()
        if row is None:
            continue
        rel = _xyz_relpath(row["sol_dir"])
        xyz_text = _load_xyz_text(main_conn, rel)
        if xyz_text is None:
            n_missing += 1
            continue
        mol_graph = build_mol_graph_from_text(xyz_text)
        if not mol_graph.atoms:
            n_missing += 1
            continue
        try:
            metrics = compute_all_descriptors(mol_graph)
        except Exception as e:
            n_errors += 1
            if verbose and n_errors <= 3:
                print(f"  ERR slice={slice_id} {row['h']}/{row['mol']}/sol_{row['sol_idx']}: "
                      f"{e.__class__.__name__}: {e}",
                      file=sys.stderr)
                traceback.print_exc(limit=2, file=sys.stderr)
            continue
        metrics.update({
            "h": row["h"], "config": row["config"],
            "mol": row["mol"], "sol_idx": row["sol_idx"],
            "computed_at": now_str,
            "compute_version": COMPUTE_VERSION,
        })
        pending.append(metrics)
        n_processed += 1
        if len(pending) >= BATCH:
            worker_conn.executemany(_INSERT_SQL, pending)
            worker_conn.commit()
            pending.clear()

    if pending:
        worker_conn.executemany(_INSERT_SQL, pending)
        worker_conn.commit()

    elapsed = time.monotonic() - t0
    main_conn.close()
    worker_conn.close()

    stats = {
        "slice_id": slice_id, "h": h,
        "n_rowids": len(rowids),
        "n_processed": n_processed,
        "n_missing": n_missing,
        "n_errors": n_errors,
        "elapsed_sec": elapsed,
        "rate_per_sec": n_processed / elapsed if elapsed > 0 else 0,
    }
    if verbose:
        print(f"[slice {slice_id} h={h}] {n_processed}/{len(rowids)} "
              f"done in {elapsed:.1f}s ({stats['rate_per_sec']:.1f}/s) "
              f"missing={n_missing} errors={n_errors}")
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--slice-ids", default=None,
                        help="liste de slice_ids separes par virgules. "
                             "Si absent, traite TOUS les slices du manifest.")
    parser.add_argument("--output-dir", required=True,
                        help="dossier ou seront ecrits worker_<id>.db")
    parser.add_argument("--schema", default=None,
                        help="chemin vers schema.sql. Default: pres du package.")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Schema sql : par defaut on lit celui pres du package
    schema_path = (Path(args.schema) if args.schema else
                   Path(__file__).resolve().parent.parent / "schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")

    # Charge le manifest
    manifest_lines = []
    with open(args.manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                manifest_lines.append(json.loads(line))

    # Filtrage par slice_ids si demande
    if args.slice_ids:
        wanted: Set[int] = set(int(s) for s in args.slice_ids.split(","))
        slices_to_do = [s for s in manifest_lines if s["slice_id"] in wanted]
    else:
        slices_to_do = manifest_lines

    print(f"[worker] {len(slices_to_do)}/{len(manifest_lines)} slices a traiter")

    all_stats = []
    for slice_data in slices_to_do:
        worker_db = out_dir / f"worker_{slice_data['slice_id']}.db"
        stats = process_slice(
            db_path=Path(args.db),
            slice_data=slice_data,
            worker_db_path=worker_db,
            schema_sql=schema_sql,
        )
        all_stats.append(stats)

    # Stats finales
    total_proc = sum(s["n_processed"] for s in all_stats)
    total_err = sum(s["n_errors"] for s in all_stats)
    total_miss = sum(s["n_missing"] for s in all_stats)
    total_time = sum(s["elapsed_sec"] for s in all_stats)
    print(f"[worker] DONE : {len(all_stats)} slices, {total_proc} sols processed, "
          f"{total_miss} missing, {total_err} errors, total_time={total_time:.1f}s")

    sys.exit(0 if total_err == 0 else 1)


if __name__ == "__main__":
    main()
