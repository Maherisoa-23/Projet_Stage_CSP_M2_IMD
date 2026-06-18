"""DB SQLite separee pour le bench ACE vs Choco.

Table unique `solver_bench` avec un row par (h, config, graph).
Workflow : init -> populate (insert pending) -> dispatcher run -> stats.
"""

import sqlite3
import time
from contextlib import closing
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS solver_bench (
    h           INTEGER NOT NULL,
    config      TEXT NOT NULL,
    graph_name  TEXT NOT NULL,
    graph_content TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    -- ACE
    n_sols_ace    INTEGER,
    t_ace_ms      INTEGER,
    status_ace    TEXT,
    -- Choco
    n_sols_choco  INTEGER,
    t_choco_ms    INTEGER,
    status_choco  TEXT,
    -- meta
    build_ms      INTEGER,
    hostname      TEXT,
    started_at    TEXT,
    finished_at   TEXT,
    error_message TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (h, config, graph_name)
);

CREATE INDEX IF NOT EXISTS idx_bench_status ON solver_bench(status);
CREATE INDEX IF NOT EXISTS idx_bench_h_config ON solver_bench(h, config);
"""


def init_db(db_path: str) -> None:
    """Cree le schema."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        c.executescript(SCHEMA)


def populate(db_path: str, sizes: list, configs: list, project_root: str) -> int:
    """Insert un row 'pending' pour chaque (h, config, graph) du corpus.

    Idempotent : INSERT OR IGNORE sur la PK.
    Retourne le nb de rows nouvellement inserees.
    """
    import sys
    here = Path(__file__).resolve().parent
    csp_root = here.parent
    if str(csp_root) not in sys.path:
        sys.path.insert(0, str(csp_root))
    from csp_solver.final.configs import list_graphs

    n_inserted = 0
    with sqlite3.connect(db_path) as c:
        for h in sizes:
            graph_paths = list_graphs(project_root, h)
            for gp in graph_paths:
                graph_name = Path(gp).stem
                content = Path(gp).read_text(encoding="utf-8")
                for cfg in configs:
                    r = c.execute(
                        "INSERT OR IGNORE INTO solver_bench "
                        "(h, config, graph_name, graph_content) VALUES (?, ?, ?, ?)",
                        (h, cfg, graph_name, content),
                    )
                    n_inserted += r.rowcount
        c.commit()
    return n_inserted


def claim_batch(db_path: str, batch_size: int, hostname: str) -> list:
    """Claim atomiquement N rows pending et les passe a 'running'.

    Retourne une liste de dicts {h, config, graph_name, graph_content}.
    """
    rows = []
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with closing(sqlite3.connect(db_path, timeout=30.0)) as c:
        c.execute("BEGIN IMMEDIATE")
        try:
            picked = c.execute(
                "SELECT h, config, graph_name, graph_content "
                "FROM solver_bench WHERE status='pending' "
                "ORDER BY h, config, graph_name LIMIT ?",
                (batch_size,),
            ).fetchall()
            if not picked:
                c.execute("COMMIT")
                return []
            for h, cfg, gn, gc in picked:
                c.execute(
                    "UPDATE solver_bench SET status='running', hostname=?, started_at=? "
                    "WHERE h=? AND config=? AND graph_name=? AND status='pending'",
                    (hostname, now, h, cfg, gn),
                )
                rows.append({"h": h, "config": cfg, "graph_name": gn, "graph_content": gc})
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return rows


def commit_result(db_path: str, h: int, cfg: str, graph_name: str,
                  result: dict, hostname: str) -> None:
    """Enregistre un resultat (status='done' ou 'failed' selon le contenu)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    err = result.get("error")
    final_status = "failed" if err else "done"
    with closing(sqlite3.connect(db_path, timeout=30.0)) as c:
        c.execute(
            "UPDATE solver_bench SET "
            "  status=?, finished_at=?, hostname=?, "
            "  n_sols_ace=?, t_ace_ms=?, status_ace=?, "
            "  n_sols_choco=?, t_choco_ms=?, status_choco=?, "
            "  build_ms=?, error_message=? "
            "WHERE h=? AND config=? AND graph_name=?",
            (
                final_status, now, hostname,
                result.get("n_sols_ace"), result.get("t_ace_ms"),
                result.get("status_ace"),
                result.get("n_sols_choco"), result.get("t_choco_ms"),
                result.get("status_choco"),
                result.get("build_ms"), err,
                h, cfg, graph_name,
            ),
        )
        c.commit()


def mark_failed_or_retry(db_path: str, h: int, cfg: str, graph_name: str,
                          error: str, max_retries: int = 2) -> None:
    """Si retry < max : remet pending, sinon failed."""
    with closing(sqlite3.connect(db_path, timeout=30.0)) as c:
        row = c.execute(
            "SELECT retry_count FROM solver_bench WHERE h=? AND config=? AND graph_name=?",
            (h, cfg, graph_name),
        ).fetchone()
        rc = (row[0] if row else 0) or 0
        if rc < max_retries:
            c.execute(
                "UPDATE solver_bench SET status='pending', retry_count=retry_count+1, "
                "error_message=? WHERE h=? AND config=? AND graph_name=?",
                (error, h, cfg, graph_name),
            )
        else:
            c.execute(
                "UPDATE solver_bench SET status='failed', error_message=? "
                "WHERE h=? AND config=? AND graph_name=?",
                (error, h, cfg, graph_name),
            )
        c.commit()


def reset_stale_running(db_path: str) -> int:
    """Reprise sur crash : remet 'running' a 'pending'."""
    with closing(sqlite3.connect(db_path, timeout=30.0)) as c:
        r = c.execute("UPDATE solver_bench SET status='pending' WHERE status='running'")
        c.commit()
        return r.rowcount


def get_stats(db_path: str) -> dict:
    """Stats globales du bench."""
    with closing(sqlite3.connect(db_path)) as c:
        by_status = dict(c.execute(
            "SELECT status, COUNT(*) FROM solver_bench GROUP BY status"
        ).fetchall())
        by_h_config = {}
        for h, cfg, st, n in c.execute(
            "SELECT h, config, status, COUNT(*) FROM solver_bench GROUP BY h, config, status"
        ):
            by_h_config.setdefault((h, cfg), {})[st] = n
    return {"by_status": by_status, "by_h_config": by_h_config}
