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

Garanties de robustesse (post-audit phase 2) :
  - Toute l'ingestion d'un job tient dans UNE seule transaction sqlite,
    avec busy_timeout=5s pour survivre aux requetes API concurrentes.
  - Si une solution echoue (XYZ illisible, JSON corrompu, ...), elle est
    sautee mais l'ingestion continue ; le compteur n_failed est expose.
  - L'appelant peut ainsi savoir si l'ingestion est COMPLETE (n_failed==0)
    avant de marquer le job comme servable depuis la DB.

API publique :
    init_solutions_table(db_path)
    ingest_local_job(db_path, job_id, output_dir, project_root, threshold_deg)
        -> dict(n_ingested, n_failed, total)
    get_job_solutions(db_path, job_id) -> list[dict]  # vide si pas de row
"""

import gzip
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


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


@contextmanager
def _open_conn(db_path: str):
    """Ouvre une connexion avec busy_timeout=5s et fermeture explicite.

    Sur Windows, les locks sqlite sont stricts ; busy_timeout permet
    d'attendre quelques secondes plutot que de lever OperationalError
    immediatement quand l'API lit pendant que le runner ecrit. La
    fermeture explicite (au lieu de compter sur le GC) evite les
    handles de fichiers qui trainent et augmentent le risque de lock.
    """
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def init_solutions_table(db_path: str) -> None:
    """Cree designer_solutions et (si absente) xyz_files."""
    with _open_conn(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _insert_xyz_blob(conn: sqlite3.Connection, rel_path: str, xyz_text: str) -> None:
    """Helper interne : INSERT OR REPLACE dans xyz_files. La connexion
    est passee par l'appelant pour que l'ensemble de l'ingestion tienne
    dans une seule transaction. Pas appele directement de l'exterieur.
    """
    rel_norm = rel_path.replace("\\", "/").lstrip("/")
    raw = xyz_text.encode("utf-8")
    gz = gzip.compress(raw)
    conn.execute(
        "INSERT OR REPLACE INTO xyz_files (rel_path, content_gz, size_raw) "
        "VALUES (?, ?, ?)",
        (rel_norm, gz, len(raw)),
    )


def _insert_solution(conn: sqlite3.Connection, job_id: str, sol_name: str,
                     sol_idx: int, sizes: str,
                     source_xyz_path: Optional[str],
                     md_xyz_path: Optional[str], md_verdict: str,
                     n_attempts: Optional[int], planar: Optional[bool],
                     angle_deg: Optional[float], rmsd: Optional[float],
                     height: Optional[float], threshold_deg: float) -> None:
    """Helper interne : INSERT OR REPLACE dans designer_solutions."""
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


def get_job_solutions(db_path: str, job_id: str) -> List[Dict]:
    """Lit les solutions d'un job depuis la DB.

    Retourne TOUJOURS une liste (vide si rien en DB). Le choix
    DB-vs-filesystem ne se fait plus sur "rows non vide" (qui pouvait
    masquer une ingestion partielle) mais sur summary.ingest_complete
    cote appelant.
    """
    with _open_conn(db_path) as conn:
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
    out: List[Dict] = []
    for r in rows:
        d = dict(r)
        if d["planar"] is not None:
            d["planar"] = bool(d["planar"])
        out.append(d)
    return out


def _read_json_safe(path: Path) -> Optional[Dict]:
    """Lit un JSON avec encoding tolerant, retourne None si quoi que ce soit
    rate (file absent, UnicodeDecodeError, JSON invalide, type non-dict).
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return None
        return obj
    except (OSError, ValueError):
        return None


def _ingest_original_block(conn: sqlite3.Connection, output_dir: Path,
                            project_root: Path,
                            threshold_deg: float) -> Optional[Dict[str, Any]]:
    """Ingere output_dir/original/original_opt.xyz en xyz_files et retourne
    un dict (metriques + xyz_path) destine a summary['original'].

    Retourne None si rien a ingerer (pas de bloc original sur le fs).
    """
    orig_dir = output_dir / "original"
    orig_opt_xyz = orig_dir / "original_opt.xyz"
    orig_plan_file = orig_dir / "planarity.json"
    if not orig_dir.is_dir():
        return None

    out: Dict[str, Any] = {}
    if orig_opt_xyz.is_file():
        rel = orig_opt_xyz.relative_to(project_root).as_posix()
        try:
            _insert_xyz_blob(conn, rel,
                             orig_opt_xyz.read_text(encoding="utf-8",
                                                    errors="replace"))
            out["xyz_path"] = rel
        except Exception:
            pass

    plan = _read_json_safe(orig_plan_file)
    if plan is not None:
        out["success"] = bool(plan.get("success", False))
        if out["success"]:
            out["planar"] = plan.get("planar")
            out["angle_deg"] = plan.get("angle_deg")
            out["rmsd"] = plan.get("rmsd")
            out["height"] = plan.get("height")
            out["threshold_deg"] = plan.get("threshold_deg", threshold_deg)
        else:
            out["message"] = plan.get("message")

    return out if out else None


def ingest_local_job(db_path: str, job_id: str, output_dir: Path,
                     project_root: Path,
                     threshold_deg: float = 10.0) -> Dict[str, Any]:
    """Ingere les resultats d'un job termine en DB. Atomique par job.

    Parcourt output_dir/sol_*/ et pour chaque solution :
      - lit source.xyz et md_validation/md_final_opt.xyz, ingere en xyz_files
      - lit md_validation/md_meta.json (md_verdict, n_attempts)
      - lit planarity.json si dispo, sinon planar=None
      - INSERT OR REPLACE dans designer_solutions

    Ingere aussi le bloc original (output_dir/original/) en xyz_files, et
    retourne ses metriques dans le champ 'original' du dict de retour
    pour que l'appelant le stocke dans summary['original'] -- ainsi l'UI
    peut afficher le benzenoide d'origine meme apres suppression du fs.

    Toutes les insertions tiennent dans UNE transaction : si la connexion
    sqlite plante au milieu, rien n'est commit (atomicite). Si une
    SOLUTION particuliere plante (XYZ illisible par ex), elle est sautee
    mais l'ingestion continue, et n_failed est incremente.

    **Suppression auto du workdir** : si n_failed == 0 (ingestion complete)
    et que l'env DESIGNER_KEEP_WORKDIR n'est pas defini, output_dir est
    supprime recursivement apres le commit. C'est l'aboutissement de la
    migration DB : plus aucun fichier residuel sur le fs apres un job
    reussi. Pour debugger, definir DESIGNER_KEEP_WORKDIR=1 cote serveur.

    Args:
        threshold_deg : seuil de planarite (degres). Stocke pour reference.

    Returns:
        {'n_ingested': int, 'n_failed': int, 'total': int,
         'original': dict|None, 'workdir_deleted': bool}
        n_failed == 0 signifie que toutes les sol_dirs ont ete ingerees
        avec succes (appelant peut alors marquer summary.ingest_complete).
    """
    if not output_dir.is_dir():
        return {"n_ingested": 0, "n_failed": 0, "total": 0,
                "original": None, "workdir_deleted": False}

    sol_dirs = sorted(d for d in output_dir.glob("sol_*") if d.is_dir())
    n_ingested = 0
    n_failed = 0
    original_block: Optional[Dict[str, Any]] = None

    with _open_conn(db_path) as conn:
        for sol_dir in sol_dirs:
            try:
                parts = sol_dir.name.split("_")
                try:
                    sol_idx = int(parts[1]) if len(parts) > 1 else 0
                except ValueError:
                    sol_idx = 0
                sizes = "_".join(parts[2:]) if len(parts) > 2 else ""

                source_xyz = sol_dir / "source.xyz"
                md_dir = sol_dir / "md_validation"
                md_final = md_dir / "md_final_opt.xyz"

                source_rel: Optional[str] = None
                md_rel: Optional[str] = None
                if source_xyz.is_file():
                    source_rel = source_xyz.relative_to(project_root).as_posix()
                    _insert_xyz_blob(conn, source_rel,
                                     source_xyz.read_text(encoding="utf-8",
                                                          errors="replace"))
                if md_final.is_file():
                    md_rel = md_final.relative_to(project_root).as_posix()
                    _insert_xyz_blob(conn, md_rel,
                                     md_final.read_text(encoding="utf-8",
                                                        errors="replace"))

                meta = _read_json_safe(md_dir / "md_meta.json")
                md_verdict = "unknown"
                n_attempts: Optional[int] = None
                if meta is not None:
                    n_attempts = meta.get("n_attempts")
                    if meta.get("success") and meta.get("converged"):
                        md_verdict = "md_ok"
                    else:
                        md_verdict = "md_failed"

                plan = _read_json_safe(sol_dir / "planarity.json")
                planar: Optional[bool] = None
                angle_deg: Optional[float] = None
                rmsd: Optional[float] = None
                height: Optional[float] = None
                if plan is not None and plan.get("success"):
                    planar = bool(plan.get("planar"))
                    angle_deg = plan.get("angle_deg")
                    rmsd = plan.get("rmsd")
                    height = plan.get("height")
                    # Mode skip xTB : la planarite est calculee sur la
                    # reconstruction plate (source.xyz). On marque le verdict
                    # comme "skipped" pour que l'UI sache que ce n'est pas
                    # une vraie validation xtb.
                    if plan.get("verdict_mode") == "skipped":
                        md_verdict = "skipped"

                _insert_solution(conn, job_id, sol_dir.name, sol_idx, sizes,
                                 source_rel, md_rel, md_verdict, n_attempts,
                                 planar, angle_deg, rmsd, height,
                                 threshold_deg)
                n_ingested += 1
            except Exception:
                # On note l'echec mais on continue avec les autres sols.
                n_failed += 1

        # Bloc original (best-effort, n'incremente pas n_failed si rate)
        try:
            original_block = _ingest_original_block(conn, output_dir,
                                                     project_root, threshold_deg)
        except Exception:
            original_block = None

        conn.commit()

    # Suppression du workdir si ingestion complete et toggle debug absent.
    workdir_deleted = False
    if n_failed == 0 and not os.getenv("DESIGNER_KEEP_WORKDIR"):
        try:
            shutil.rmtree(output_dir)
            workdir_deleted = True
        except OSError:
            # Echec de suppression (handles ouverts sur Windows, droits...)
            # n'est pas fatal : la DB est commit, le workdir reste sur fs.
            pass

    return {"n_ingested": n_ingested, "n_failed": n_failed,
            "total": len(sol_dirs), "original": original_block,
            "workdir_deleted": workdir_deleted}
