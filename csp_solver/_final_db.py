"""DB Final pour le run h3-h9 x 3 configs sur cluster.

Schema dedie a la persistance des solutions CSP + resultats xTB enrichis
(verdict planeite, energie, HOMO-LUMO, temps CPU, et plus tard Clar/RBO
en post-traitement).

Lecteurs : le dispatcher (master) ecrit, les outils d'analyse lisent.
Pas accede par les workers (workers communiquent via stdin/stdout JSON).

Voir doc/ARCHITECTURE_FINAL_RUN.md section 3.3 pour le design.
"""

import gzip
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS final_runs (
  run_id          INTEGER PRIMARY KEY,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  state           TEXT NOT NULL DEFAULT 'running',
  last_heartbeat  TEXT,
  config_json     TEXT,
  notes           TEXT
);

CREATE TABLE IF NOT EXISTS final_solutions (
  sol_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id            INTEGER NOT NULL REFERENCES final_runs(run_id),
  size_h            INTEGER NOT NULL,
  config            TEXT NOT NULL,
  graph_name        TEXT NOT NULL,
  sol_index         INTEGER NOT NULL,
  graph_content_gz  BLOB NOT NULL,
  csp_solution_json TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'pending',
  retry_count       INTEGER NOT NULL DEFAULT 0,
  hostname          TEXT,
  error_message     TEXT,
  verdict           TEXT,
  angle_deg         REAL,
  energy_eh         REAL,
  homo_lumo_ev      REAL,
  cpu_time_s        REAL,
  wall_time_s       REAL,
  clar_sextets      INTEGER,
  rbo_pauling       REAL,
  xyz_optimized_gz  BLOB,
  started_at        TEXT,
  finished_at       TEXT,
  UNIQUE(run_id, size_h, config, graph_name, sol_index)
);

CREATE INDEX IF NOT EXISTS idx_final_sols_status
  ON final_solutions(run_id, status);
CREATE INDEX IF NOT EXISTS idx_final_sols_size_config
  ON final_solutions(run_id, size_h, config);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def open_conn(db_path: str, timeout: float = 30.0):
    """Connexion sqlite avec PRAGMA WAL + busy_timeout + close garantie."""
    conn = sqlite3.connect(db_path, timeout=timeout, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    """Cree les tables si absentes. Idempotent."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with open_conn(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


def create_run(db_path: str, config_dict: dict, notes: str = "") -> int:
    """Cree une nouvelle entree final_runs et retourne run_id."""
    with open_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO final_runs (started_at, state, last_heartbeat, config_json, notes) "
            "VALUES (?, 'running', ?, ?, ?)",
            (_utcnow(), _utcnow(), json.dumps(config_dict, sort_keys=True), notes),
        )
        return int(cur.lastrowid)


def insert_solutions(
    db_path: str,
    run_id: int,
    size_h: int,
    config: str,
    graph_name: str,
    graph_content: str,
    solutions: list,
) -> int:
    """Insere les sols d'un (taille, config, graph) avec status='pending'.

    solutions = liste de dicts {v_idx: taille} (au format CSP).
    Retourne le nombre de lignes insérées (0 si deja la, vu UNIQUE).
    """
    graph_gz = gzip.compress(graph_content.encode("utf-8"))
    inserted = 0
    with open_conn(db_path) as conn:
        conn.execute("BEGIN")
        try:
            for idx, sol in enumerate(solutions):
                try:
                    conn.execute(
                        "INSERT INTO final_solutions "
                        "(run_id, size_h, config, graph_name, sol_index, "
                        " graph_content_gz, csp_solution_json, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                        (run_id, size_h, config, graph_name, idx,
                         graph_gz, json.dumps(sol, sort_keys=True)),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return inserted


def claim_batch(db_path: str, run_id: int, batch_size: int, hostname: str) -> list:
    """Pop atomiquement un batch de sols pending, les marque running.

    Retourne une liste de dicts (sol_id, size_h, config, graph_name, sol_index,
    graph_content, csp_solution).
    Liste vide si plus rien a faire.
    """
    with open_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                "SELECT sol_id, size_h, config, graph_name, sol_index, "
                "       graph_content_gz, csp_solution_json "
                "FROM final_solutions "
                "WHERE run_id=? AND status='pending' "
                "ORDER BY size_h ASC, sol_id ASC "
                "LIMIT ?",
                (run_id, batch_size),
            ).fetchall()
            if not rows:
                conn.execute("COMMIT")
                return []
            ids = [r["sol_id"] for r in rows]
            now = _utcnow()
            qmarks = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE final_solutions SET status='running', hostname=?, started_at=? "
                f"WHERE sol_id IN ({qmarks})",
                [hostname, now] + ids,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return [
        {
            "sol_id": r["sol_id"],
            "size_h": r["size_h"],
            "config": r["config"],
            "graph_name": r["graph_name"],
            "sol_index": r["sol_index"],
            "graph_content": gzip.decompress(r["graph_content_gz"]).decode("utf-8"),
            "csp_solution": json.loads(r["csp_solution_json"]),
        }
        for r in rows
    ]


def commit_results_batch(db_path: str, results: list) -> int:
    """Commit en BATCH (1 transaction) tous les resultats d'un batch.

    results : liste de dicts (chacun contenant 'sol_id', 'status', etc.)
    Beaucoup plus rapide que N appels a commit_result (1 transaction
    par batch au lieu de N transactions sur NFS).
    Retourne le nombre de rows mises a jour.
    """
    if not results:
        return 0
    updates = []
    for r in results:
        xyz_gz = None
        if r.get("xyz_optimized"):
            xyz_gz = gzip.compress(r["xyz_optimized"].encode("utf-8"))
        updates.append((
            r.get("status", "failed"),
            r.get("verdict"),
            r.get("angle_deg"),
            r.get("energy_eh"),
            r.get("homo_lumo_ev"),
            r.get("cpu_time_s"),
            r.get("wall_time_s"),
            xyz_gz,
            r.get("error_message"),
            r.get("hostname"),
            _utcnow(),
            r["sol_id"],
        ))
    sql = (
        "UPDATE final_solutions SET "
        "  status=?, verdict=?, angle_deg=?, energy_eh=?, homo_lumo_ev=?, "
        "  cpu_time_s=?, wall_time_s=?, xyz_optimized_gz=?, "
        "  error_message=?, hostname=COALESCE(?, hostname), finished_at=? "
        "WHERE sol_id=?"
    )
    with open_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(sql, updates)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return len(updates)


def commit_result(db_path: str, sol_id: int, result: dict) -> None:
    """Update une sol avec le resultat du worker.

    result attendu :
      status      : 'done' ou 'failed'
      verdict     : PLAN/LIMITE/NON_PLAN (si done)
      angle_deg   : float
      energy_eh   : float
      homo_lumo_ev: float
      cpu_time_s  : float
      wall_time_s : float
      xyz_optimized: str (contenu XYZ, sera gzippe)
      error_message: str (si failed)
      hostname    : str
    """
    xyz_gz = None
    if result.get("xyz_optimized"):
        xyz_gz = gzip.compress(result["xyz_optimized"].encode("utf-8"))
    with open_conn(db_path) as conn:
        conn.execute(
            "UPDATE final_solutions SET "
            "  status=?, verdict=?, angle_deg=?, energy_eh=?, homo_lumo_ev=?, "
            "  cpu_time_s=?, wall_time_s=?, xyz_optimized_gz=?, "
            "  error_message=?, hostname=COALESCE(?, hostname), finished_at=? "
            "WHERE sol_id=?",
            (
                result.get("status", "failed"),
                result.get("verdict"),
                result.get("angle_deg"),
                result.get("energy_eh"),
                result.get("homo_lumo_ev"),
                result.get("cpu_time_s"),
                result.get("wall_time_s"),
                xyz_gz,
                result.get("error_message"),
                result.get("hostname"),
                _utcnow(),
                sol_id,
            ),
        )


def mark_failed_or_retry(db_path: str, sol_id: int, error_msg: str, max_retries: int = 2) -> bool:
    """Selon retry_count, soit re-pending soit failed final.

    Retourne True si re-pending (sera retentee), False si failed final.
    """
    with open_conn(db_path) as conn:
        conn.execute("BEGIN")
        try:
            row = conn.execute(
                "SELECT retry_count FROM final_solutions WHERE sol_id=?",
                (sol_id,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return False
            n = int(row["retry_count"])
            if n < max_retries:
                conn.execute(
                    "UPDATE final_solutions SET status='pending', retry_count=?, "
                    "  error_message=?, started_at=NULL, hostname=NULL "
                    "WHERE sol_id=?",
                    (n + 1, error_msg, sol_id),
                )
                conn.execute("COMMIT")
                return True
            conn.execute(
                "UPDATE final_solutions SET status='failed', error_message=?, finished_at=? "
                "WHERE sol_id=?",
                (error_msg, _utcnow(), sol_id),
            )
            conn.execute("COMMIT")
            return False
        except Exception:
            conn.execute("ROLLBACK")
            raise


def reset_stale_running(db_path: str, run_id: int) -> int:
    """Au demarrage du dispatcher : reset des sols 'running' a 'pending'.

    Utile apres un crash du master. Retourne le nb de sols reset.
    Garde retry_count tel quel (le crash master n'est pas une faute du worker).
    """
    with open_conn(db_path) as conn:
        cur = conn.execute(
            "UPDATE final_solutions SET status='pending', started_at=NULL "
            "WHERE run_id=? AND status='running'",
            (run_id,),
        )
        return int(cur.rowcount)


def update_heartbeat(db_path: str, run_id: int) -> None:
    with open_conn(db_path) as conn:
        conn.execute(
            "UPDATE final_runs SET last_heartbeat=? WHERE run_id=?",
            (_utcnow(), run_id),
        )


def get_stats(db_path: str, run_id: int) -> dict:
    """Retourne dict {status: count} + breakdown par (size_h, config)."""
    with open_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM final_solutions WHERE run_id=? GROUP BY status",
            (run_id,),
        ).fetchall()
        by_status = {r["status"]: r["n"] for r in rows}
        rows2 = conn.execute(
            "SELECT size_h, config, status, COUNT(*) AS n "
            "FROM final_solutions WHERE run_id=? "
            "GROUP BY size_h, config, status",
            (run_id,),
        ).fetchall()
        by_size_config = {}
        for r in rows2:
            key = (r["size_h"], r["config"])
            by_size_config.setdefault(key, {})[r["status"]] = r["n"]
    return {"by_status": by_status, "by_size_config": by_size_config}


def mark_run_completed(db_path: str, run_id: int) -> None:
    with open_conn(db_path) as conn:
        conn.execute(
            "UPDATE final_runs SET state='completed', finished_at=? WHERE run_id=?",
            (_utcnow(), run_id),
        )


def get_run_info(db_path: str, run_id: Optional[int] = None) -> Optional[dict]:
    """Retourne info sur un run. Si run_id=None, prend le dernier."""
    with open_conn(db_path) as conn:
        if run_id is None:
            row = conn.execute(
                "SELECT * FROM final_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM final_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None
