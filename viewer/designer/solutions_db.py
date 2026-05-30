"""Persistance DB des solutions designer.

Cree deux tables :

* `designer_solutions` (nouvelle)  : 1 ligne par solution, contient les
  metriques structurees (sol_idx, sizes, planarity, md_verdict, ...) et
  les chemins relatifs vers les XYZ associes.

* `xyz_files` (deja utilisee par les experiments v2/v3 et le viewer
  principal) : 1 ligne par fichier XYZ, contenu gzippe. La fonction
  `_load_xyz_text` du serveur cherche d'abord en filesystem puis dans
  cette table, donc une fois ingere, le XYZ est servi automatiquement
  via /api/mol3d et /file sans modification cote viewer.

L'avantage : un job designer "termine + ingere" peut etre lu sans avoir
besoin du filesystem (utile pour cluster_runner.py qui rapatrie tout en
DB sans laisser de fichiers locaux).

API publique :
    init_solutions_table(db_path)
    ingest_local_job(db_path, job_id, output_dir, project_root, threshold_deg)
    insert_solution(db_path, job_id, **fields)
    insert_xyz_blob(db_path, rel_path, xyz_text)
    get_job_solutions(db_path, job_id) -> list[dict] | None
"""

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS designer_solutions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL,
    sol_idx          INTEGER NOT NULL,
    sizes            TEXT,
    sol_name         TEXT NOT NULL,
    source_xyz_path  TEXT,
    md_xyz_path      TEXT,
    md_verdict       TEXT,
    n_attempts       INTEGER,
    planar           INTEGER,
    angle_deg        REAL,
    rmsd             REAL,
    height           REAL,
    threshold_deg    REAL,
    UNIQUE(job_id, sol_name)
);
CREATE INDEX IF NOT EXISTS idx_designer_solutions_job ON designer_solutions(job_id);

CREATE TABLE IF NOT EXISTS xyz_files (
    rel_path   TEXT PRIMARY KEY,
    content_gz BLOB NOT NULL,
    size_raw   INTEGER NOT NULL
);
"""


def init_solutions_table(db_path: str) -> None:
    """Cree designer_solutions et (si absente) xyz_files."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def insert_xyz_blob(db_path: str, rel_path: str, xyz_text: str) -> None:
    """Ingere un XYZ texte en table xyz_files (gzippe, INSERT OR REPLACE).

    La cle `rel_path` doit etre un chemin POSIX relatif depuis project_root
    (ex: 'viewer/output/designer_jobs/abc/sol_1_5_6_7/md_final_opt.xyz').
    C'est exactement la cle que /api/mol3d et /file vont utiliser pour
    retrouver le contenu.
    """
    rel_norm = rel_path.replace("\\", "/").lstrip("/")
    raw = xyz_text.encode("utf-8")
    gz = gzip.compress(raw)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO xyz_files (rel_path, content_gz, size_raw) "
            "VALUES (?, ?, ?)",
            (rel_norm, gz, len(raw)),
        )


def insert_solution(db_path: str, job_id: str, sol_name: str, sol_idx: int,
                    sizes: str, source_xyz_path: Optional[str],
                    md_xyz_path: Optional[str], md_verdict: str,
                    n_attempts: Optional[int], planar: Optional[bool],
                    angle_deg: Optional[float], rmsd: Optional[float],
                    height: Optional[float], threshold_deg: float) -> None:
    """INSERT OR REPLACE une row designer_solutions. Idempotent par (job_id, sol_name)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO designer_solutions ("
            "  job_id, sol_idx, sizes, sol_name,"
            "  source_xyz_path, md_xyz_path,"
            "  md_verdict, n_attempts,"
            "  planar, angle_deg, rmsd, height, threshold_deg"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, sol_idx, sizes, sol_name,
             source_xyz_path, md_xyz_path,
             md_verdict, n_attempts,
             None if planar is None else int(bool(planar)),
             angle_deg, rmsd, height, threshold_deg),
        )


def get_job_solutions(db_path: str, job_id: str) -> Optional[List[Dict]]:
    """Lit les solutions d'un job depuis la DB.

    Retourne None si aucune ligne n'existe pour ce job (signal pour
    l'appelant de fallback sur le filesystem). Retourne une liste vide []
    si le job existe mais n'a aucune solution (cas success avec 0 sol).
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT sol_idx, sizes, sol_name, source_xyz_path, md_xyz_path,"
            "       md_verdict, n_attempts, planar, angle_deg, rmsd, height,"
            "       threshold_deg "
            "FROM designer_solutions "
            "WHERE job_id = ? "
            "ORDER BY sol_idx ASC",
            (job_id,),
        ).fetchall()
    if not rows:
        return None
    out: List[Dict] = []
    for r in rows:
        d = dict(r)
        # Convertir planar 0/1/NULL -> bool|None pour l'API
        if d["planar"] is not None:
            d["planar"] = bool(d["planar"])
        out.append(d)
    return out


def ingest_local_job(db_path: str, job_id: str, output_dir: Path,
                     project_root: Path, threshold_deg: float = 10.0) -> int:
    """Ingere les resultats d'un job termine (mode local) en DB.

    Parcourt output_dir/sol_*/ et pour chaque solution :
      - lit source.xyz et md_validation/md_final_opt.xyz, ingere en xyz_files
      - lit md_validation/md_meta.json (md_verdict, n_attempts)
      - lit planarity.json si calcule localement, sinon utilise None
      - INSERT OR REPLACE dans designer_solutions

    Args:
        threshold_deg : seuil de planarite (degres). Stocke pour reference.

    Returns:
        Nombre de solutions ingerees.
    """
    if not output_dir.is_dir():
        return 0
    n_ingested = 0
    for sol_dir in sorted(output_dir.glob("sol_*")):
        if not sol_dir.is_dir():
            continue
        parts = sol_dir.name.split("_")
        try:
            sol_idx = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            sol_idx = 0
        sizes = "_".join(parts[2:]) if len(parts) > 2 else ""

        source_xyz = sol_dir / "source.xyz"
        md_dir = sol_dir / "md_validation"
        md_final = md_dir / "md_final_opt.xyz"

        # Ingestion des XYZ en xyz_files
        source_rel: Optional[str] = None
        md_rel: Optional[str] = None
        if source_xyz.is_file():
            source_rel = source_xyz.relative_to(project_root).as_posix()
            insert_xyz_blob(db_path, source_rel,
                            source_xyz.read_text(encoding="utf-8",
                                                 errors="replace"))
        if md_final.is_file():
            md_rel = md_final.relative_to(project_root).as_posix()
            insert_xyz_blob(db_path, md_rel,
                            md_final.read_text(encoding="utf-8",
                                               errors="replace"))

        # md_meta.json
        md_verdict = "unknown"
        n_attempts: Optional[int] = None
        meta_file = md_dir / "md_meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                n_attempts = meta.get("n_attempts")
                if meta.get("success") and meta.get("converged"):
                    md_verdict = "md_ok"
                else:
                    md_verdict = "md_failed"
            except (OSError, json.JSONDecodeError):
                pass

        # planarity.json (peut ne pas exister si le compute n'a pas tourne)
        planar: Optional[bool] = None
        angle_deg: Optional[float] = None
        rmsd: Optional[float] = None
        height: Optional[float] = None
        plan_file = sol_dir / "planarity.json"
        if plan_file.is_file():
            try:
                p = json.loads(plan_file.read_text(encoding="utf-8"))
                if p.get("success"):
                    planar = bool(p.get("planar"))
                    angle_deg = p.get("angle_deg")
                    rmsd = p.get("rmsd")
                    height = p.get("height")
            except (OSError, json.JSONDecodeError):
                pass

        insert_solution(db_path, job_id, sol_dir.name, sol_idx, sizes,
                        source_rel, md_rel, md_verdict, n_attempts,
                        planar, angle_deg, rmsd, height, threshold_deg)
        n_ingested += 1
    return n_ingested
