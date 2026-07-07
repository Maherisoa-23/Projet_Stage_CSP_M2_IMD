"""Export de secours des solutions h3-h9 en JSON Lines (.jsonl.gz), un
fichier par (taille h, config). A utiliser si l'application (Docker/designer)
est indisponible : les donnees restent consultables avec des outils standards
(Python, grep/zcat, pandas) sans dependre du solveur CSP ni de xTB.

Decoupage par config (pas seulement par h) : un fichier qui melangerait
toutes les configs d'une taille h serait trop lourd a telecharger/ouvrir
d'un bloc (ex. h9 toutes configs confondues ~2.3 Go). Le decoupage par
config permet de ne recuperer que celle qui interesse (typiquement C1,
la config recommandee, ~170 Mo pour h9) sans charger les autres.

Note : Ctopo n'est PAS exportable par ce script -- cette config est
materialisee a part (csp_solver.analysis.materialize_ctopo) et n'a pas de
ligne propre dans final_solutions (pas de graph_content_gz/xyz_optimized_gz
associes). Voir doc/PIPELINE.md pour son mode de calcul.

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
    python -m csp_solver.analysis.export_jsonl --out exports/ --only-h 9 --only-config Cstr
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


def list_configs_for_h(conn: sqlite3.Connection, size_h: int) -> list[str]:
    """Liste les configs ayant au moins une solution exportable (done +
    xyz) pour cette taille h. Exclut implicitement Ctopo (jamais dans
    final_solutions)."""
    cur = conn.execute(
        """SELECT DISTINCT config FROM final_solutions
           WHERE size_h = ? AND status = 'done' AND xyz_optimized_gz IS NOT NULL
           ORDER BY config""",
        (size_h,),
    )
    return [r[0] for r in cur]


def export_size_h_config(conn: sqlite3.Connection, size_h: int, config: str,
                          out_dir: Path) -> tuple[int, float]:
    """Exporte les solutions 'done' d'une taille h et d'une config donnees
    vers <out_dir>/h<size_h>_<config>.jsonl.gz. Retourne (n_lignes, duree_s).
    """
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        f"""SELECT {', '.join(_PLAIN_COLUMNS)}, csp_solution_json,
                   graph_content_gz, xyz_optimized_gz
            FROM final_solutions
            WHERE size_h = ? AND config = ? AND status = 'done'
              AND xyz_optimized_gz IS NOT NULL
            ORDER BY graph_name, sol_index""",
        (size_h, config),
    )

    out_path = out_dir / f"h{size_h}_{config}.jsonl.gz"
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
                print(f"  h{size_h}_{config}: {n} lignes ecrites ({elapsed:.0f}s)...", flush=True)

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
    ap.add_argument("--only-config", action="append", dest="only_config",
                    help="Restreint a une (ou plusieurs, repetable) config "
                         "(ex. C1, Cstr). Defaut : toutes les configs "
                         "presentes pour chaque h.")
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
    total_files = 0
    for h in sizes:
        configs = args.only_config or list_configs_for_h(conn, h)
        if not configs:
            print(f"=== h{h} : aucune config exportable (pas de solutions done+xyz) ===")
            continue
        for config in configs:
            print(f"=== h{h} / {config} ===")
            n, dt = export_size_h_config(conn, h, config, out_dir)
            if n == 0:
                (out_dir / f"h{h}_{config}.jsonl.gz").unlink(missing_ok=True)
                print(f"  -> 0 ligne (config absente pour ce h), fichier non cree")
                continue
            size_mb = (out_dir / f"h{h}_{config}.jsonl.gz").stat().st_size / 1e6
            print(f"  -> {n} lignes, {size_mb:.1f} MB (.gz), {dt:.1f}s")
            total_n += n
            total_t += dt
            total_files += 1

    conn.close()
    print()
    print(f"Total : {total_n} lignes, {total_files} fichiers, exportes en {total_t:.0f}s")


if __name__ == "__main__":
    main()
