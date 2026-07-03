"""
Gestion CRUD des tables de voisinage T(n) dans la DB SQLite.

Une table de voisinage contient, pour chaque taille de cycle n in {5,6,7},
la liste des sequences de voisins admissibles (contrainte C3 du CSP,
cf. csp_solver/utils/table.py et preprocessing.py). Ce module permet aux
chimistes de creer des variantes de cette table (plus restrictives, plus
permissives, exploratoires) sans toucher au fichier source du projet.

La table par defaut (csp_solver/data/table_voisinage.json, utilisee par
tout le pipeline existant y compris le run final h3-h9) est migree comme
premiere entree protegee (is_default=1) : toujours presente, non
supprimable, modifiable ou dupliquable comme les autres. Si un job ne
precise pas de table_id, il utilise cette table par defaut (comportement
identique a avant l'introduction du CRUD).

Schema :
    id          : UUID court (8 chars) - PK
    name        : nom de la table (obligatoire)
    description : texte libre optionnel
    content_json: JSON {"5": [[...], ...], "6": [...], "7": [...]}
    is_default  : 1 pour la table par defaut migree (protegee), 0 sinon
    created_at  : timestamp UTC ISO 8601
    updated_at  : timestamp UTC ISO 8601

API principale :
    init_tables_table(db_path)
    create_table(db_path, name, content, description=None) -> id
    duplicate_table(db_path, source_id, new_name) -> id
    get_table(db_path, id) -> dict | None
    update_table(db_path, id, **fields) -> None
    add_sequence(db_path, id, cycle_size, sequence) -> None
    remove_sequence(db_path, id, cycle_size, sequence) -> None
    delete_table(db_path, id) -> bool
    list_tables(db_path) -> list[dict]  (sans content_json, pour l'aperçu)
    count_jobs_using(db_path, id) -> int
    materialize_table_file(db_path, id, dest_path) -> None
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS designer_neighbor_tables (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,
    content_json TEXT NOT NULL,
    is_default   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_designer_neighbor_tables_created
    ON designer_neighbor_tables(created_at DESC);
"""

_CYCLE_SIZES = (5, 6, 7)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _default_table_source_path() -> Path:
    """Chemin du fichier table_voisinage.json source (csp_solver/data/)."""
    # viewer/designer/tables_mgmt.py -> viewer/designer -> viewer -> racine
    return (Path(__file__).resolve().parent.parent.parent
            / "csp_solver" / "data" / "table_voisinage.json")


def init_tables_table(db_path: str) -> None:
    """Cree designer_neighbor_tables si absente, et y insere la table par
    defaut (migree depuis csp_solver/data/table_voisinage.json) si elle
    n'y est pas deja. Idempotent : ne recree pas la table par defaut si
    une ligne is_default=1 existe deja (meme si son contenu a ete edite
    depuis -- on ne veut pas ecraser les modifications du chimiste a
    chaque redemarrage du serveur).
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT id FROM designer_neighbor_tables WHERE is_default = 1"
        ).fetchone()
        if row is None:
            source = _default_table_source_path()
            if source.is_file():
                content = source.read_text(encoding="utf-8")
                now = _now_iso()
                conn.execute(
                    "INSERT INTO designer_neighbor_tables "
                    "(id, name, description, content_json, is_default,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                    ("default", "Table par defaut",
                     "Table de voisinage standard du projet "
                     "(csp_solver/data/table_voisinage.json), utilisee "
                     "par le run final h3-h9. Non supprimable.",
                     content, now, now),
                )
        conn.commit()


def _row_to_dict(row: sqlite3.Row, include_content: bool = True) -> Dict:
    d = dict(row)
    d["is_default"] = bool(d.get("is_default"))
    if include_content and d.get("content_json"):
        try:
            d["content"] = json.loads(d["content_json"])
        except (json.JSONDecodeError, TypeError):
            d["content"] = {}
    d.pop("content_json", None)
    return d


def _validate_content(content: Dict) -> Dict:
    """Normalise et valide grossierement le contenu d'une table.

    Format attendu : {"5": [[...], ...], "6": [...], "7": [...]}, chaque
    sequence de longueur egale a la taille du cycle, valeurs dans
    {0, 5, 6, 7}. Leve ValueError si la structure est invalide.
    """
    out = {}
    for n in _CYCLE_SIZES:
        key = str(n)
        seqs = content.get(key, content.get(n, []))
        if not isinstance(seqs, list):
            raise ValueError(f"contenu invalide pour le cycle {n} : liste attendue")
        clean = []
        for seq in seqs:
            if not isinstance(seq, (list, tuple)) or len(seq) != n:
                raise ValueError(
                    f"sequence invalide pour le cycle {n} : {seq!r} "
                    f"(longueur {n} attendue)")
            if any(v not in (0, 5, 6, 7) for v in seq):
                raise ValueError(
                    f"sequence invalide pour le cycle {n} : {seq!r} "
                    f"(valeurs autorisees : 0, 5, 6, 7)")
            clean.append(list(seq))
        out[key] = clean
    return out


def create_table(db_path: str, name: str, content: Dict,
                 description: Optional[str] = None) -> str:
    """Cree une nouvelle table de voisinage. Retourne son id (8 chars hex)."""
    clean_content = _validate_content(content)
    table_id = uuid.uuid4().hex[:8]
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO designer_neighbor_tables "
            "(id, name, description, content_json, is_default,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (table_id, name, description, json.dumps(clean_content), now, now),
        )
    return table_id


def duplicate_table(db_path: str, source_id: str, new_name: str) -> Optional[str]:
    """Duplique une table existante (contenu copie) sous un nouveau nom.
    Retourne le nouvel id, ou None si source_id est introuvable.
    """
    source = get_table(db_path, source_id)
    if source is None:
        return None
    return create_table(
        db_path, new_name, source["content"],
        description=f"Duplique depuis « {source['name']} »",
    )


def get_table(db_path: str, table_id: str) -> Optional[Dict]:
    """Retourne la table (avec son contenu) comme dict, ou None si introuvable."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM designer_neighbor_tables WHERE id = ?", (table_id,)
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def update_table(db_path: str, table_id: str, **fields) -> bool:
    """Met a jour name/description/content. updated_at est rafraichi
    automatiquement. Retourne False si table_id est introuvable.

    'content' (dict) est valide puis serialise en content_json.
    """
    if not fields:
        return True
    row = get_table(db_path, table_id)
    if row is None:
        return False
    if "content" in fields:
        fields["content_json"] = json.dumps(_validate_content(fields.pop("content")))
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [table_id]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE designer_neighbor_tables SET {cols} WHERE id = ?", values
        )
    return True


def add_sequence(db_path: str, table_id: str, cycle_size: int,
                 sequence: List[int]) -> bool:
    """Ajoute une sequence de voisins admissible pour un cycle donne.
    Ignore silencieusement si la sequence est deja presente (evite les
    doublons). Retourne False si table_id est introuvable.
    """
    if cycle_size not in _CYCLE_SIZES or len(sequence) != cycle_size:
        raise ValueError(f"sequence invalide pour le cycle {cycle_size} : {sequence!r}")
    row = get_table(db_path, table_id)
    if row is None:
        return False
    content = row["content"]
    key = str(cycle_size)
    seqs = content.setdefault(key, [])
    seq_list = list(sequence)
    if seq_list not in seqs:
        seqs.append(seq_list)
    update_table(db_path, table_id, content=content)
    return True


def remove_sequence(db_path: str, table_id: str, cycle_size: int,
                    sequence: List[int]) -> bool:
    """Retire une sequence de voisins d'un cycle donne, si presente.
    Retourne False si table_id est introuvable.
    """
    row = get_table(db_path, table_id)
    if row is None:
        return False
    content = row["content"]
    key = str(cycle_size)
    seqs = content.get(key, [])
    seq_list = list(sequence)
    content[key] = [s for s in seqs if list(s) != seq_list]
    update_table(db_path, table_id, content=content)
    return True


def delete_table(db_path: str, table_id: str) -> bool:
    """Supprime une table. Refuse de supprimer la table par defaut
    (is_default=1) -- leve ValueError dans ce cas. Retourne True si une
    table a effectivement ete supprimee, False si table_id est introuvable.
    """
    row = get_table(db_path, table_id)
    if row is None:
        return False
    if row["is_default"]:
        raise ValueError("La table par defaut ne peut pas etre supprimee.")
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM designer_neighbor_tables WHERE id = ?", (table_id,)
        )
        return cur.rowcount > 0


def list_tables(db_path: str) -> List[Dict]:
    """Liste toutes les tables (sans leur contenu complet, pour l'aperçu),
    triees : table par defaut d'abord, puis par date de creation decroissante.
    Inclut un compte de sequences par cycle (n_seq_5, n_seq_6, n_seq_7).
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, description, content_json, is_default,"
            "       created_at, updated_at "
            "FROM designer_neighbor_tables "
            "ORDER BY is_default DESC, created_at DESC"
        ).fetchall()
    out = []
    for row in rows:
        d = _row_to_dict(row, include_content=True)
        content = d.pop("content")
        d["n_seq"] = {n: len(content.get(str(n), [])) for n in _CYCLE_SIZES}
        out.append(d)
    return out


def count_jobs_using(db_path: str, table_id: str) -> int:
    """Nombre de jobs designer ayant utilise cette table (via config_json).
    Best-effort : parcourt config_json en Python (pas d'index dedie, le
    volume de jobs designer reste modeste). Retourne 0 si designer_jobs
    n'existe pas encore (ordre d'init non garanti entre modules).
    """
    with sqlite3.connect(db_path) as conn:
        try:
            rows = conn.execute("SELECT config_json FROM designer_jobs").fetchall()
        except sqlite3.OperationalError:
            return 0
    count = 0
    for (config_json,) in rows:
        if not config_json:
            continue
        try:
            config = json.loads(config_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if config.get("table_id") == table_id:
            count += 1
    return count


def materialize_table_file(db_path: str, table_id: str, dest_path: str) -> bool:
    """Ecrit le contenu d'une table dans un fichier JSON (format attendu
    par csp_solver/utils/table.py::load_table), pour le passer en
    --table-path au subprocess CLI. Retourne False si table_id introuvable.
    """
    row = get_table(db_path, table_id)
    if row is None:
        return False
    Path(dest_path).write_text(json.dumps(row["content"]), encoding="utf-8")
    return True
