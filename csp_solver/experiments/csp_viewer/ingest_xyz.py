"""
Ingere les fichiers xyz d'un dataset (h) depuis le filesystem vers la table
`xyz_files` de la DB du viewer. Le contenu est gzip-compresse (ratio ~2.5x
sur xyz ASCII).

Pour chaque solution de la DB on tente d'ingerer :
  - <sol_dir>/md_validation/md_final_opt.xyz
Et pour chaque molecule unique on tente :
  - <mol_dir>/<mol>_original_opt.xyz       (1 par molecule, pas par solution)

Les fichiers absents du filesystem sont logges et ignores.
La cle de stockage (rel_path) est exactement le chemin relatif depuis
project_root, slashes normalises en forward slash (comme sol_dir en DB).

Usage :
    python ingest_xyz.py --h h6 [--db db_v2.db] [--dry-run] [--limit N]

Idempotent : INSERT OR REPLACE sur la PK rel_path, peut etre relance sans
duplication.
"""

import argparse
import gzip
import sqlite3
import sys
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
_DEFAULT_DB = _HERE / "db_v2.db"


def _norm(rel: str) -> str:
    """Normalise un chemin relatif : forward slashes uniquement."""
    return rel.replace("\\", "/").lstrip("/")


def _load_and_compress(abs_path: Path):
    """Lit le fichier, retourne (size_raw, content_gz) ou (None, None) si KO."""
    try:
        raw = abs_path.read_bytes()
    except OSError:
        return None, None
    if not raw:
        return None, None
    return len(raw), gzip.compress(raw, compresslevel=6)


def _mol_dir_from_sol_dir(sol_dir: str) -> str | None:
    """A partir de <prefix>/<mol>/solutions/sol_*, retourne <prefix>/<mol>.
    Retourne None si format inattendu."""
    parts = sol_dir.rstrip("/").split("/")
    if len(parts) < 3 or parts[-2] != "solutions":
        return None
    return "/".join(parts[:-2])


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Cree la table xyz_files si elle n'existe pas. Idempotent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS xyz_files (
            rel_path   TEXT PRIMARY KEY,
            content_gz BLOB NOT NULL,
            size_raw   INTEGER NOT NULL
        )
    """)
    conn.commit()


def ingest_for_h(db_path: Path, h: str, *,
                 dry_run: bool = False,
                 limit: int | None = None) -> None:
    if not db_path.is_file():
        print(f"ERREUR: DB introuvable: {db_path}", file=sys.stderr)
        sys.exit(2)

    print(f"=== ingest_xyz ===")
    print(f"  DB    : {db_path}")
    print(f"  h     : {h}")
    print(f"  root  : {_PROJECT_ROOT}")
    if dry_run:
        print(f"  mode  : DRY-RUN (rien n'est ecrit)")
    if limit is not None:
        print(f"  limit : {limit} solutions max")
    print()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    sol_query = "SELECT id, sol_dir, mol FROM solutions WHERE h = ?"
    params = [h]
    if limit is not None:
        sol_query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sol_query, params).fetchall()
    print(f"  {len(rows)} solutions trouvees en DB pour h={h}")

    n_sol_ok = 0
    n_sol_missing = 0
    n_sol_skipped_already = 0
    bytes_raw = 0
    bytes_gz = 0
    mol_dirs: dict[str, str] = {}  # mol -> mol_dir (rel)

    if not dry_run:
        already = {r[0] for r in conn.execute(
            "SELECT rel_path FROM xyz_files").fetchall()}
    else:
        already = set()

    pending: list[tuple[str, bytes, int]] = []
    BATCH = 500

    def _flush():
        nonlocal pending
        if not pending:
            return
        if not dry_run:
            conn.executemany(
                "INSERT OR REPLACE INTO xyz_files "
                "(rel_path, content_gz, size_raw) VALUES (?, ?, ?)",
                pending,
            )
            conn.commit()
        pending = []

    for row in rows:
        sol_dir = _norm(row["sol_dir"])
        mol = row["mol"]

        rel_xyz = f"{sol_dir}/md_validation/md_final_opt.xyz"
        if rel_xyz in already:
            n_sol_skipped_already += 1
        else:
            abs_xyz = (_PROJECT_ROOT / rel_xyz).resolve()
            try:
                abs_xyz.relative_to(_PROJECT_ROOT.resolve())
            except ValueError:
                n_sol_missing += 1
                continue
            if not abs_xyz.is_file():
                n_sol_missing += 1
                continue
            size_raw, content_gz = _load_and_compress(abs_xyz)
            if content_gz is None:
                n_sol_missing += 1
                continue
            pending.append((rel_xyz, content_gz, size_raw))
            n_sol_ok += 1
            bytes_raw += size_raw
            bytes_gz += len(content_gz)
            if len(pending) >= BATCH:
                _flush()

        # Memorise le mol_dir pour ingestion des originaux ensuite
        if mol not in mol_dirs:
            md = _mol_dir_from_sol_dir(sol_dir)
            if md is not None:
                mol_dirs[mol] = md

    _flush()

    # Ingestion des <mol>_original_opt.xyz
    n_orig_ok = 0
    n_orig_missing = 0
    n_orig_skipped_already = 0

    for mol, mol_dir in mol_dirs.items():
        rel_orig = f"{mol_dir}/{mol}_original_opt.xyz"
        if rel_orig in already:
            n_orig_skipped_already += 1
            continue
        abs_orig = (_PROJECT_ROOT / rel_orig).resolve()
        try:
            abs_orig.relative_to(_PROJECT_ROOT.resolve())
        except ValueError:
            n_orig_missing += 1
            continue
        if not abs_orig.is_file():
            n_orig_missing += 1
            continue
        size_raw, content_gz = _load_and_compress(abs_orig)
        if content_gz is None:
            n_orig_missing += 1
            continue
        pending.append((rel_orig, content_gz, size_raw))
        n_orig_ok += 1
        bytes_raw += size_raw
        bytes_gz += len(content_gz)
        if len(pending) >= BATCH:
            _flush()

    _flush()
    conn.close()

    print()
    print(f"=== resume ===")
    print(f"  md_final_opt.xyz : OK={n_sol_ok}  manquants={n_sol_missing}  deja={n_sol_skipped_already}")
    print(f"  *_original_opt.xyz : OK={n_orig_ok}  manquants={n_orig_missing}  deja={n_orig_skipped_already}")
    if bytes_raw > 0:
        ratio = bytes_gz / bytes_raw if bytes_raw else 0.0
        print(f"  taille  : raw={bytes_raw/1e6:.1f} MB  gz={bytes_gz/1e6:.1f} MB  ratio={ratio:.3f}")
    if dry_run:
        print(f"  (DRY-RUN: aucune ecriture)")


def main():
    ap = argparse.ArgumentParser(description="Ingere les xyz d'un h dans db_v2.db.")
    ap.add_argument("--h", required=True, help="dataset cible (ex. h6)")
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="chemin DB")
    ap.add_argument("--dry-run", action="store_true",
                    help="ne fait que compter, n'ecrit pas dans la DB")
    ap.add_argument("--limit", type=int, default=None,
                    help="limite le nombre de solutions traitees (debug)")
    args = ap.parse_args()

    ingest_for_h(Path(args.db), args.h,
                 dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
