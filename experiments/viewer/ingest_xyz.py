"""
Ingere les fichiers xyz vers la table `xyz_files` de la DB du viewer. Le
contenu est gzip-compresse (ratio ~2.5x sur xyz ASCII).

Deux modes :

1. Mode DB-driven (--h hN) : utilise la table `solutions` de la DB d'entree
   pour determiner les paths xyz a ingerer. Necessite que --db ait deja la
   table solutions peuplee pour ce h. Pour chaque solution on tente :
     - <sol_dir>/md_validation/md_final_opt.xyz
   Et pour chaque molecule unique :
     - <mol_dir>/<mol>_original_opt.xyz       (1 par mol, pas par sol)

2. Mode scan-root (--scan-root <dir>) : walk directement le filesystem sous
   <dir>, sans dependre de la table solutions. Utile sur cluster (pas de
   db_v2.db en input) ou quand on veut juste produire la table xyz_files.
   Le --rel-prefix reecrit le path stocke pour matcher la convention locale
   (ex. cluster `/home/.../_h9_run/output/h9/...` -> local
   `csp_solver/experiments/_run_v2/output/h9/...`).

Idempotent : INSERT OR REPLACE sur la PK rel_path, peut etre relance sans
duplication. Les rel_paths deja en DB sont sautes au scan.

Usage :
    # Mode DB-driven (mode historique)
    python ingest_xyz.py --h h6 [--db db_v2.db] [--dry-run] [--limit N]

    # Mode scan-root (recommande sur cluster pour h9)
    python ingest_xyz.py \\
        --scan-root /home/COALA/.../_h9_run/output/h9 \\
        --rel-prefix csp_solver/experiments/_run_v2/output/h9 \\
        --db /tmp/h9_xyz.db \\
        --parallel 16
"""

import argparse
import gzip
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
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


def _read_compress_worker(task):
    """Worker top-level (picklable) pour ProcessPoolExecutor.
    task = (abs_path_str, rel_path_str).
    Retourne (rel_path, content_gz, size_raw) ou None si erreur/vide.
    """
    abs_path_str, rel_path = task
    try:
        raw = Path(abs_path_str).read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return (rel_path, gzip.compress(raw, compresslevel=6), len(raw))


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
        print(f"ERREUR: DB introuvable: {db_path}", file=sys.stderr, flush=True)
        sys.exit(2)

    print(f"=== ingest_xyz (DB-driven mode) ===", flush=True)
    print(f"  DB    : {db_path}", flush=True)
    print(f"  h     : {h}", flush=True)
    print(f"  root  : {_PROJECT_ROOT}", flush=True)
    if dry_run:
        print(f"  mode  : DRY-RUN (rien n'est ecrit)", flush=True)
    if limit is not None:
        print(f"  limit : {limit} solutions max", flush=True)
    print(flush=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    sol_query = "SELECT id, sol_dir, mol FROM solutions WHERE h = ?"
    params = [h]
    if limit is not None:
        sol_query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sol_query, params).fetchall()
    print(f"  {len(rows)} solutions trouvees en DB pour h={h}", flush=True)

    n_sol_ok = 0
    n_sol_missing = 0
    n_sol_skipped_already = 0
    bytes_raw = 0
    bytes_gz = 0
    mol_dirs: dict[str, str] = {}

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

        if mol not in mol_dirs:
            md = _mol_dir_from_sol_dir(sol_dir)
            if md is not None:
                mol_dirs[mol] = md

    _flush()

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

    print(flush=True)
    print(f"=== resume ===", flush=True)
    print(f"  md_final_opt.xyz   : OK={n_sol_ok}  manquants={n_sol_missing}  deja={n_sol_skipped_already}", flush=True)
    print(f"  *_original_opt.xyz : OK={n_orig_ok}  manquants={n_orig_missing}  deja={n_orig_skipped_already}", flush=True)
    if bytes_raw > 0:
        ratio = bytes_gz / bytes_raw
        print(f"  taille  : raw={bytes_raw/1e6:.1f} MB  gz={bytes_gz/1e6:.1f} MB  ratio={ratio:.3f}", flush=True)
    if dry_run:
        print(f"  (DRY-RUN: aucune ecriture)", flush=True)


def ingest_from_fs(db_path: Path, scan_root: Path, rel_prefix: str, *,
                   parallel: int = 1,
                   dry_run: bool = False) -> None:
    """Walk fs direct sous scan_root, ingere tous les md_final_opt.xyz
    trouves. Le path stocke est `<rel_prefix>/<chemin relatif a scan_root>`,
    slashes en forward. Si --parallel > 1, utilise ProcessPoolExecutor pour
    parallelo-iser lecture+gzip (workers picklable). SQLite reste mono-thread
    cote main (pas de contention)."""
    if not scan_root.is_dir():
        print(f"ERREUR: scan_root introuvable: {scan_root}",
              file=sys.stderr, flush=True)
        sys.exit(2)
    if not db_path.parent.is_dir():
        print(f"ERREUR: parent de db_path absent: {db_path.parent}",
              file=sys.stderr, flush=True)
        sys.exit(2)

    rel_prefix = rel_prefix.replace("\\", "/").strip("/")
    scan_root = scan_root.resolve()

    print(f"=== ingest_xyz (scan-root mode) ===", flush=True)
    print(f"  scan_root  : {scan_root}", flush=True)
    print(f"  rel_prefix : {rel_prefix}", flush=True)
    print(f"  DB         : {db_path}", flush=True)
    print(f"  parallel   : {parallel}", flush=True)
    if dry_run:
        print(f"  mode       : DRY-RUN (rien n'est ecrit)", flush=True)
    print(flush=True)

    conn = sqlite3.connect(str(db_path))
    ensure_schema(conn)

    if not dry_run:
        print(f"  chargement des rel_paths existants en DB ...", flush=True)
        already = {r[0] for r in conn.execute(
            "SELECT rel_path FROM xyz_files").fetchall()}
        print(f"  {len(already)} deja en DB", flush=True)
    else:
        already = set()

    print(f"  walk filesystem ...", flush=True)
    tasks: list[tuple[str, str]] = []
    for abs_path in scan_root.rglob("md_final_opt.xyz"):
        rel_remainder = abs_path.relative_to(scan_root).as_posix()
        rel_path = f"{rel_prefix}/{rel_remainder}"
        if rel_path in already:
            continue
        tasks.append((str(abs_path), rel_path))
    total = len(tasks)
    print(f"  {total} xyz a ingerer ({len(already)} skipped)", flush=True)

    if not tasks:
        print(f"  rien a faire.", flush=True)
        conn.close()
        return

    n_ok = 0
    n_err = 0
    bytes_raw = 0
    bytes_gz = 0
    pending: list[tuple[str, bytes, int]] = []
    BATCH = 500
    PROGRESS_EVERY = 5000

    def _flush():
        nonlocal pending
        if pending and not dry_run:
            conn.executemany(
                "INSERT OR REPLACE INTO xyz_files "
                "(rel_path, content_gz, size_raw) VALUES (?, ?, ?)",
                pending,
            )
            conn.commit()
        pending = []

    def _maybe_progress(force: bool = False):
        done = n_ok + n_err
        if force or done % PROGRESS_EVERY == 0:
            pct = 100 * done / total if total else 0
            print(f"  progress: {done}/{total} ({pct:.1f}%) "
                  f"OK={n_ok} err={n_err}", flush=True)

    if parallel <= 1:
        for task in tasks:
            result = _read_compress_worker(task)
            if result is None:
                n_err += 1
            else:
                rel_path, gz, raw_sz = result
                pending.append((rel_path, gz, raw_sz))
                n_ok += 1
                bytes_raw += raw_sz
                bytes_gz += len(gz)
                if len(pending) >= BATCH:
                    _flush()
            _maybe_progress()
    else:
        with ProcessPoolExecutor(max_workers=parallel) as ex:
            for result in ex.map(_read_compress_worker, tasks, chunksize=64):
                if result is None:
                    n_err += 1
                else:
                    rel_path, gz, raw_sz = result
                    pending.append((rel_path, gz, raw_sz))
                    n_ok += 1
                    bytes_raw += raw_sz
                    bytes_gz += len(gz)
                    if len(pending) >= BATCH:
                        _flush()
                _maybe_progress()

    _flush()
    conn.close()

    print(flush=True)
    print(f"=== resume ===", flush=True)
    print(f"  OK    = {n_ok}", flush=True)
    print(f"  err   = {n_err}", flush=True)
    if bytes_raw:
        ratio = bytes_gz / bytes_raw
        print(f"  taille: raw={bytes_raw/1e6:.1f} MB  gz={bytes_gz/1e6:.1f} MB  "
              f"ratio={ratio:.3f}", flush=True)
    if dry_run:
        print(f"  (DRY-RUN: aucune ecriture)", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Ingere les xyz dans la DB.")
    ap.add_argument("--h", default=None,
                    help="dataset cible (ex. h6). Mode DB-driven : lit la "
                         "table solutions pour determiner les paths.")
    ap.add_argument("--scan-root", default=None,
                    help="Mode scan-root: walk directement ce dossier au "
                         "lieu de lire la table solutions.")
    ap.add_argument("--rel-prefix", default=None,
                    help="Prefixe reecrit dans le rel_path stocke (mode "
                         "--scan-root). Defaut: chemin absolu de scan_root.")
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="chemin DB cible")
    ap.add_argument("--dry-run", action="store_true",
                    help="ne fait que compter, n'ecrit pas dans la DB")
    ap.add_argument("--limit", type=int, default=None,
                    help="limite le nombre de solutions traitees "
                         "(mode DB-driven uniquement)")
    ap.add_argument("--parallel", type=int, default=1,
                    help="Nombre de workers parallels pour lecture+gzip "
                         "(mode scan-root uniquement). Defaut: 1.")
    args = ap.parse_args()

    if args.scan_root and args.h:
        print("ERREUR: --scan-root et --h sont mutuellement exclusifs.",
              file=sys.stderr, flush=True)
        sys.exit(2)
    if not args.scan_root and not args.h:
        print("ERREUR: il faut --scan-root OU --h.", file=sys.stderr, flush=True)
        sys.exit(2)

    if args.scan_root:
        rel_prefix = args.rel_prefix or str(Path(args.scan_root).resolve())
        ingest_from_fs(
            Path(args.db),
            Path(args.scan_root),
            rel_prefix,
            parallel=args.parallel,
            dry_run=args.dry_run,
        )
    else:
        ingest_for_h(
            Path(args.db), args.h,
            dry_run=args.dry_run, limit=args.limit,
        )


if __name__ == "__main__":
    main()
