"""
Gestion du cycle de vie des jobs designer dans la DB SQLite.

Schema de la table designer_jobs (creee a la demande dans la meme db_all.db
que le reste du viewer, pour eviter de multiplier les fichiers) :

    job_id        : UUID court (8 chars) - PK
    created_at    : timestamp UTC ISO 8601
    updated_at    : timestamp UTC ISO 8601 (mis a jour a chaque transition)
    state         : 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
    current_stage : texte libre ('parse', 'csp', 'reconstruct', 'md', 'done')
    progress      : reel dans [0, 1], indicatif
    graph_content : contenu .graph soumis (string)
    config_json   : config CSP serialisee (json)
    output_dir    : chemin du dossier de sortie (relatif au project root)
    error         : message + traceback si state='failed', sinon NULL
    duration_s    : temps d'execution en secondes (set a la fin)
    pid           : PID du subprocess (pour cancel), sinon NULL
    summary_json  : resume des resultats (json : n_solutions, n_plans, ...)

Cycle de vie typique :
    pending -> running -> success
                       -> failed
                       -> cancelled

API principale :
    init_jobs_table(db_path)
    create_job(db_path, graph_content, config) -> job_id
    get_job(db_path, job_id) -> dict | None
    update_job(db_path, job_id, **fields)
    list_jobs(db_path, limit=50) -> list[dict]
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS designer_jobs (
    job_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    state         TEXT NOT NULL,
    current_stage TEXT,
    progress      REAL,
    graph_content TEXT,
    config_json   TEXT,
    output_dir    TEXT,
    error         TEXT,
    duration_s    REAL,
    pid           INTEGER,
    summary_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_designer_jobs_created ON designer_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_designer_jobs_state ON designer_jobs(state);
"""


def init_jobs_table(db_path: str) -> None:
    """Cree la table designer_jobs si elle n'existe pas."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _row_to_dict(row: sqlite3.Row) -> Dict:
    """Convertit une row en dict + deserialise les champs JSON."""
    d = dict(row)
    if d.get("config_json"):
        try:
            d["config"] = json.loads(d["config_json"])
        except (json.JSONDecodeError, TypeError):
            d["config"] = {}
    else:
        d["config"] = {}
    if d.get("summary_json"):
        try:
            d["summary"] = json.loads(d["summary_json"])
        except (json.JSONDecodeError, TypeError):
            d["summary"] = {}
    else:
        d["summary"] = {}
    return d


def create_job(db_path: str, graph_content: str, config: Dict,
               output_dir: str) -> str:
    """Cree une nouvelle entree job en etat 'pending'. Retourne l'UUID.

    Args:
        db_path       : chemin de db_all.db
        graph_content : contenu du fichier .graph soumis
        config        : dict des options CSP (validate, no_freeze, no_table,
                        adj_57, count_hexagon, n_runs, method, etc.)
        output_dir    : chemin du dossier de sortie (relatif au project root)

    Returns:
        job_id (8 chars hex).
    """
    job_id = uuid.uuid4().hex[:8]
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO designer_jobs ("
            "  job_id, created_at, updated_at, state, current_stage, progress,"
            "  graph_content, config_json, output_dir"
            ") VALUES (?, ?, ?, 'pending', NULL, 0.0, ?, ?, ?)",
            (job_id, now, now, graph_content, json.dumps(config), output_dir),
        )
    return job_id


def get_job(db_path: str, job_id: str) -> Optional[Dict]:
    """Retourne le job comme dict, ou None si introuvable."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM designer_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def update_job(db_path: str, job_id: str, **fields) -> None:
    """Met a jour des champs d'un job. updated_at est rafraichi automatiquement.

    Champs serialisables en JSON acceptes via les cles 'config' et 'summary'
    (qui sont convertis en config_json/summary_json).
    """
    if not fields:
        return
    # Convertir config / summary en JSON
    if "config" in fields:
        fields["config_json"] = json.dumps(fields.pop("config"))
    if "summary" in fields:
        fields["summary_json"] = json.dumps(fields.pop("summary"))
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [job_id]
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"UPDATE designer_jobs SET {cols} WHERE job_id = ?", values)


def list_jobs(db_path: str, limit: int = 50) -> List[Dict]:
    """Liste les jobs les plus recents."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT job_id, created_at, updated_at, state, current_stage,"
            "       progress, output_dir, duration_s, error "
            "FROM designer_jobs "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
