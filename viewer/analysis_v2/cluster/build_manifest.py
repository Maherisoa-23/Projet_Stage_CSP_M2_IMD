"""
Construit un manifest.jsonl pour le compute distribue.

Pour chaque h cible, on requete les solutions a traiter (verdict in
plan/non_plan) et on les decoupe en SLICES de taille fixe. Chaque slice
devient un job pour un worker.

Format d'une ligne du manifest :
  {"slice_id": 42, "h": "h7", "rowids": [12, 87, 102, ...]}

`rowids` = rowid SQLite des lignes de la table `solutions`. C'est
l'identifiant le plus compact (un int au lieu de 4 strings).

Usage :
    python -m viewer.analysis_v2.cluster.build_manifest \\
        --db db_v2.db \\
        --h h7 h8 h9 \\
        --output manifest.jsonl \\
        --slice-size 500

Sortie : manifest.jsonl + une ligne de log par slice cree.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[4]))
    __package__ = "viewer.analysis_v2.cluster"


def build_manifest(db_path: Path,
                   hs: list[str],
                   output_path: Path,
                   slice_size: int = 500,
                   skip_already_done: bool = True,
                   compute_version: str = "2.0.0") -> int:
    """Construit le manifest. Retourne le nombre de slices crees."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    n_slices = 0
    n_total_sols = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for h in hs:
            # Solutions a traiter pour ce h
            sql = (
                "SELECT s.rowid AS rid FROM solutions s "
                "WHERE s.h = ? AND s.verdict IN ('plan', 'non_plan')"
            )
            if skip_already_done:
                # On exclut les sols deja calculees a la version courante
                sql += (
                    " AND NOT EXISTS ("
                    "  SELECT 1 FROM solution_descriptors d "
                    "  WHERE d.h = s.h AND d.config = s.config "
                    "    AND d.mol = s.mol AND d.sol_idx = s.sol_idx "
                    "    AND d.compute_version = ?"
                    ")"
                )
                params = (h, compute_version)
            else:
                params = (h,)

            rowids = [r["rid"] for r in conn.execute(sql, params)]
            n_total_sols += len(rowids)
            if not rowids:
                print(f"  [{h}] 0 sol a traiter (toutes calculees)")
                continue

            # Decoupage en slices
            for i in range(0, len(rowids), slice_size):
                slice_rowids = rowids[i:i + slice_size]
                line = {
                    "slice_id": n_slices,
                    "h": h,
                    "rowids": slice_rowids,
                }
                f.write(json.dumps(line) + "\n")
                n_slices += 1
            print(f"  [{h}] {len(rowids)} sols -> {(len(rowids) + slice_size - 1) // slice_size} slices")

    conn.close()
    print(f"[manifest] {n_slices} slices, {n_total_sols} sols totales -> {output_path}")
    return n_slices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--h", nargs="+", required=True,
                        help="liste des h a traiter, ex: h6 h7 h8 h9")
    parser.add_argument("--output", required=True,
                        help="chemin du manifest.jsonl a creer")
    parser.add_argument("--slice-size", type=int, default=500,
                        help="nb de sols par slice (default 500)")
    parser.add_argument("--all", action="store_true",
                        help="inclut les sols deja calculees (pour --force)")
    parser.add_argument("--compute-version", default="2.0.0",
                        help="version d'algo a comparer pour skip auto")
    args = parser.parse_args()

    n = build_manifest(
        db_path=Path(args.db),
        hs=args.h,
        output_path=Path(args.output),
        slice_size=args.slice_size,
        skip_already_done=not args.all,
        compute_version=args.compute_version,
    )
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
