"""
Gestion des collections (regroupements de jobs designer) dans la DB SQLite.

Une collection = un dossier nomme pour organiser des jobs designer (ex.
"Etude pentagones isoles", "Test config C2 vs C3"). Relation simple :
un job appartient a AU PLUS UNE collection (designer_jobs.collection_id,
nullable). Pas de many-to-many : garde le modele simple, un job "non classe"
a collection_id = NULL.

Schema :
    id          : UUID court (8 chars) - PK
    name        : nom de la collection (obligatoire)
    description : texte libre optionnel
    created_at  : timestamp UTC ISO 8601
    updated_at  : timestamp UTC ISO 8601

Suppression d'une collection : ne supprime PAS les jobs qu'elle contient.
Leur collection_id repasse a NULL (ils redeviennent "non classes"). C'est
un choix delibere pour eviter qu'une suppression de dossier n'efface des
resultats de calcul par accident.

API principale :
    init_collections_table(db_path)
    create_collection(db_path, name, description=None) -> id
    get_collection(db_path, id) -> dict | None
    update_collection(db_path, id, **fields)
    delete_collection(db_path, id) -> bool
    list_collections(db_path) -> list[dict]  (avec job_count par collection)
"""

import sqlite3
import uuid
from datetime import datetime
from typing import Dict, List, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS designer_collections (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_designer_collections_created
    ON designer_collections(created_at DESC);
"""


def init_collections_table(db_path: str) -> None:
    """Cree la table designer_collections si elle n'existe pas."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def create_collection(db_path: str, name: str,
                      description: Optional[str] = None) -> str:
    """Cree une nouvelle collection. Retourne son id (8 chars hex)."""
    coll_id = uuid.uuid4().hex[:8]
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO designer_collections "
            "(id, name, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (coll_id, name, description, now, now),
        )
    return coll_id


def get_collection(db_path: str, coll_id: str) -> Optional[Dict]:
    """Retourne la collection comme dict, ou None si introuvable."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM designer_collections WHERE id = ?", (coll_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def update_collection(db_path: str, coll_id: str, **fields) -> None:
    """Met a jour name/description. updated_at est rafraichi automatiquement."""
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [coll_id]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE designer_collections SET {cols} WHERE id = ?", values
        )


def delete_collection(db_path: str, coll_id: str) -> bool:
    """Supprime la collection. Les jobs qu'elle contenait repassent
    collection_id = NULL (pas de suppression en cascade). Retourne True
    si une collection a effectivement ete supprimee.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE designer_jobs SET collection_id = NULL "
            "WHERE collection_id = ?",
            (coll_id,),
        )
        cur = conn.execute(
            "DELETE FROM designer_collections WHERE id = ?", (coll_id,)
        )
        return cur.rowcount > 0


def list_collections(db_path: str) -> List[Dict]:
    """Liste toutes les collections avec leur nombre de jobs (job_count),
    triees par date de creation decroissante.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT c.id, c.name, c.description, c.created_at, c.updated_at,"
            "       COUNT(j.job_id) AS job_count "
            "FROM designer_collections c "
            "LEFT JOIN designer_jobs j ON j.collection_id = c.id "
            "GROUP BY c.id "
            "ORDER BY c.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def count_unfiled_jobs(db_path: str) -> int:
    """Nombre de jobs sans collection (collection_id IS NULL)."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM designer_jobs WHERE collection_id IS NULL"
        ).fetchone()
    return row[0] if row else 0
