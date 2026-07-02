"""Export de secours des solutions h3-h9 en JSON Lines (.jsonl.gz), un
fichier par taille h. A utiliser si l'application (Docker/designer) est
indisponible : les donnees restent consultables avec des outils standards
(Python, grep/zcat, pandas) sans dependre du solveur CSP ni de xTB.

Format JSON Lines plutot qu'un unique JSON array : chaque ligne est un objet
JSON complet et independant, streamable sans tout charger en memoire (un
JSON array de plusieurs millions d'objets ne se parse pas raisonnablement
d'un bloc). Compresse en .gz : le texte XYZ est tres repetitif, la
compression est efficace (~5-8x) et evite de distribuer des fichiers de
plusieurs Go non compresses.

Un objet exporte, par ligne :
{
  "size_h": 6,
  "config": "C1",
  "graph_name": "0-3-4-...",
  "sol_index": 2,
  "csp_solution": {"0": 5, "1": 6, "2": 7, ...},
  "verdict": "PLAN",
  "angle_deg": 0.0123,
  "energy_eh": -123.456,
  "homo_lumo_ev": 3.21,
  "max_dihedral_deg": 0.45,
  "graph": "p DIMACS ...",   -- .graph DIMACS d'entree (texte brut)
  "xyz": "22\n energy: ...\nC  ..."  -- geometrie xTB optimisee (texte brut)
}

Seules les colonnes reellement peuplees sont incluses (clar_sextets et
rbo_pauling sont vides sur toute la DB actuelle -- pas d'interet a exporter
des null partout ; a ajouter si csp_solver/analysis/postprocess_clar_rbo.py
est lance un jour sur cette DB).

Usage :
    python -m csp_solver.analysis.export_jsonl --out exports/
    python -m csp_solver.analysis.export_jsonl --out exports/ --only-h 9
    python -m csp_solver.analysis.export_jsonl --db path/to/other.db --out exports/
"""

import argparse
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "experiments" / "final" / "final_h3_h9.db"

# Colonnes SQL a exporter tel quel (hors graph_content_gz / xyz_optimized_gz,
# traitees a part car elles doivent etre decompressees).
_PLAIN_COLUMNS = [
    "size_h", "config", "graph_name", "sol_index",
    "verdict", "angle_deg", "energy_eh", "homo_lumo_ev", "max_dihedral_deg",
]


def _row_to_json_obj(row: dict) -> dict:
    """Convertit une ligne SQL (dict) en objet JSON exportable."""
    obj = {k: row[k] for k in _PLAIN_COLUMNS}
    obj["csp_solution"] = json.loads(row["csp_solution_json"])
    obj["graph"] = gzip.decompress(row["graph_content_gz"]).decode("utf-8")
    obj["xyz"] = gzip.decompress(row["xyz_optimized_gz"]).decode("utf-8")
    return obj


def export_size_h(conn: sqlite3.Connection, size_h: int, out_dir: Path) -> tuple[int, float]:
    """Exporte toutes les solutions 'done' d'une taille h donnee vers
    <out_dir>/h<size_h>.jsonl.gz. Retourne (n_lignes, duree_s).
    """
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        f"""SELECT {', '.join(_PLAIN_COLUMNS)}, csp_solution_json,
                   graph_content_gz, xyz_optimized_gz
            FROM final_solutions
            WHERE size_h = ? AND status = 'done' AND xyz_optimized_gz IS NOT NULL
            ORDER BY config, graph_name, sol_index""",
        (size_h,),
    )

    out_path = out_dir / f"h{size_h}.jsonl.gz"
    t0 = time.time()
    n = 0
    with gzip.open(out_path, "wt", encoding="utf-8", compresslevel=6) as f:
        for row in cur:
            obj = _row_to_json_obj(row)
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")
            n += 1
            if n % 50000 == 0:
                elapsed = time.time() - t0
                print(f"  h{size_h}: {n} lignes ecrites ({elapsed:.0f}s)...", flush=True)

    return n, time.time() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help=f"Chemin de la DB source (defaut: {DEFAULT_DB})")
    ap.add_argument("--out", required=True, help="Dossier de sortie (cree si absent)")
    ap.add_argument("--only-h", type=int, action="append", dest="only_h",
                    help="Restreint a une (ou plusieurs, repetable) taille h. "
                         "Defaut : h3 a h9.")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERREUR : DB introuvable : {db_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sizes = args.only_h or list(range(3, 10))

    conn = sqlite3.connect(str(db_path))
    print(f"DB source : {db_path}")
    print(f"Sortie    : {out_dir}")
    print(f"Tailles h : {sizes}")
    print()

    total_n = 0
    total_t = 0.0
    for h in sizes:
        print(f"=== h{h} ===")
        n, dt = export_size_h(conn, h, out_dir)
        size_mb = (out_dir / f"h{h}.jsonl.gz").stat().st_size / 1e6
        print(f"  -> {n} lignes, {size_mb:.1f} MB (.gz), {dt:.1f}s")
        total_n += n
        total_t += dt

    conn.close()
    print()
    print(f"Total : {total_n} lignes exportees en {total_t:.0f}s")


if __name__ == "__main__":
    main()
