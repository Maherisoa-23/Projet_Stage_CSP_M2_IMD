"""Dispatcher (master) du run final sur cluster.

Orchestre le traitement des sols pending dans la DB Final :
  - Pool de N threads SSH (1 par machine cible, defaut 16 : 49..64)
  - Chaque thread :
      1. claim_batch(batch_size, hostname)
      2. SSH host -> python -m csp_solver.final.worker < json > json
      3. commit_result pour chaque sol
      4. Si SSH fail (timeout, broken pipe) : mark_failed_or_retry par sol
  - Heartbeat dans la DB toutes les 60s
  - Au demarrage : reset_stale_running (reprise sur crash master)
  - A la fin : mark_run_completed quand toutes les sols sont done/failed

Lance via :
  nohup python -m csp_solver.final.dispatcher --db ~/projet/final_h3_h9.db \\
      --run-id <id> --workers "49,50,...,64" --batch-size 40 \\
      --max-parallel-xtb 40 --timeout-xtb 50000 \\
      > ~/dispatcher.log 2>&1 &

Variables d'environnement (sinon defauts COALA) :
  CSP_CLUSTER_CONDA_INIT  : commande shell pour activer le bon env conda
                            (defaut : eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda
                                              shell.bash hook)" && conda activate nonbenz)
  CSP_CLUSTER_PROJECT_PATH : chemin du repo cote workers (defaut : ~/projet)
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path


def _ensure_imports():
    """Assure que csp_solver/ est dans sys.path."""
    here = Path(__file__).resolve().parent
    csp_solver_dir = here.parent
    if str(csp_solver_dir) not in sys.path:
        sys.path.insert(0, str(csp_solver_dir))


_ensure_imports()

from csp_solver.final import db as _final_db  # noqa: E402


CONDA_INIT = os.environ.get(
    "CSP_CLUSTER_CONDA_INIT",
    'eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" '
    '&& conda activate nonbenz',
)
REMOTE_PROJECT_PATH = os.environ.get("CSP_CLUSTER_PROJECT_PATH", "~/projet")


def _now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    print(f"[{_now_str()}] {msg}", flush=True)


def _ssh_run_worker(host: str, batch_input: dict, ssh_timeout_s: int) -> dict:
    """Lance worker_batch sur `host` via SSH, retourne dict resultats.

    Leve subprocess.TimeoutExpired ou RuntimeError sur erreur SSH.
    """
    remote_cmd = (
        f'{CONDA_INIT} && cd {REMOTE_PROJECT_PATH} '
        f'&& python -m csp_solver.final.worker'
    )
    ssh_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=10",
        "-o", "ConnectTimeout=15",
        "-o", "TCPKeepAlive=yes",
        host,
        remote_cmd,
    ]
    proc = subprocess.run(
        ssh_cmd,
        input=json.dumps(batch_input),
        capture_output=True,
        text=True,
        timeout=ssh_timeout_s,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip()[-500:]
        raise RuntimeError(
            f"SSH worker returncode={proc.returncode} stderr={stderr_tail!r}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        stdout_tail = (proc.stdout or "")[-500:]
        raise RuntimeError(
            f"Invalid JSON from worker: {e}; stdout_tail={stdout_tail!r}"
        )


_CLAIM_LOCK = threading.Lock()


def _worker_thread_loop(
    host: str, db_path: str, run_id: int, batch_size: int,
    max_parallel_xtb: int, timeout_xtb: int, ssh_timeout_s: int,
    stop_event: threading.Event, stats: dict, stats_lock: threading.Lock,
    claim_lock: threading.Lock,
):
    """Boucle d'un thread worker.

    Tourne tant qu'il reste des sols pending dans la DB.
    """
    import traceback
    _log(f"[{host}] worker started")
    while not stop_event.is_set():
        try:
            _worker_iter(host, db_path, run_id, batch_size, max_parallel_xtb,
                         timeout_xtb, ssh_timeout_s, stop_event, stats, stats_lock,
                         claim_lock)
        except _NoMorePending:
            _log(f"[{host}] no more pending sols, exiting")
            return
        except Exception as e:
            _log(f"[{host}] WORKER ITER EXCEPTION: {e}\n{traceback.format_exc()[-1500:]}")
            time.sleep(10)
            continue
    _log(f"[{host}] worker stopped (stop_event)")


class _NoMorePending(Exception):
    pass


def _worker_iter(
    host: str, db_path: str, run_id: int, batch_size: int,
    max_parallel_xtb: int, timeout_xtb: int, ssh_timeout_s: int,
    stop_event: threading.Event, stats: dict, stats_lock: threading.Lock,
    claim_lock: threading.Lock,
):
    """Une iteration : claim un batch, SSH, commit. Lève _NoMorePending si fini."""
    # Mutex SEULEMENT autour du claim_batch (court), pas autour du SSH (long)
    with claim_lock:
        try:
            batch = _final_db.claim_batch(db_path, run_id, batch_size, host)
        except Exception as e:
            _log(f"[{host}] claim_batch error: {e}")
            time.sleep(5)
            return

    if not batch:
        # claim_batch a retourne [] : verifier que c'est vraiment fini
        # (NFS+WAL peuvent avoir des snapshots stale, ne pas tuer le worker trop tot)
        try:
            stats_db = _final_db.get_stats(db_path, run_id)
            n_pend = stats_db["by_status"].get("pending", 0)
        except Exception:
            n_pend = -1
        if n_pend == 0:
            raise _NoMorePending()
        _log(f"[{host}] claim returned [] but {n_pend} pending in DB, retry in 10s")
        time.sleep(10)
        return

    sol_ids = [s["sol_id"] for s in batch]
    _log(f"[{host}] claimed {len(batch)} sols : {sol_ids[:5]}{'...' if len(sol_ids) > 5 else ''}")

    batch_input = {
        "max_parallel": max_parallel_xtb,
        "timeout_xtb": timeout_xtb,
        "sols": [
            {
                "sol_id": s["sol_id"],
                "graph_content": s["graph_content"],
                "csp_solution": s["csp_solution"],
                "sol_index": s["sol_index"],
            }
            for s in batch
        ],
    }

    # Tente l'execution SSH
    try:
        t0 = time.perf_counter()
        _log(f"[{host}] SSH starting (batch of {len(batch)} sols)")
        out = _ssh_run_worker(host, batch_input, ssh_timeout_s)
        dt = time.perf_counter() - t0
        _log(f"[{host}] SSH returned in {dt:.1f}s, {len(out.get('results', []))} results")
    except subprocess.TimeoutExpired:
        _log(f"[{host}] SSH TIMEOUT apres {ssh_timeout_s}s, retry batch")
        for sid in sol_ids:
            _final_db.mark_failed_or_retry(db_path, sid, "ssh_timeout")
        with stats_lock:
            stats["batches_timeout"] += 1
        return
    except Exception as e:
        _log(f"[{host}] SSH ERROR: {e}, retry batch")
        for sid in sol_ids:
            _final_db.mark_failed_or_retry(db_path, sid, f"ssh_error: {e}"[:500])
        with stats_lock:
            stats["batches_failed"] += 1
        return

    # Commit results — TOUT EN 1 TRANSACTION (batch)
    results = out.get("results", [])
    result_ids = set(r["sol_id"] for r in results)
    done_results = [r for r in results if r.get("status") == "done"]
    failed_results = [r for r in results if r.get("status") != "done"]
    missing_sids = [sid for sid in sol_ids if sid not in result_ids]

    n_done = len(done_results)
    n_failed = len(failed_results) + len(missing_sids)

    if done_results:
        _final_db.commit_results_batch(db_path, done_results)
    for r in failed_results:
        _final_db.mark_failed_or_retry(
            db_path, r["sol_id"], r.get("error_message", "unknown") or "unknown"
        )
    for sid in missing_sids:
        _final_db.mark_failed_or_retry(db_path, sid, "no_result_from_worker")

    with stats_lock:
        stats["sols_done"] += n_done
        stats["sols_failed"] += n_failed
        stats["batches_ok"] += 1
    _log(f"[{host}] batch done ({n_done} OK, {n_failed} failed) in {dt:.1f}s")


def _heartbeat_loop(db_path: str, run_id: int, interval_s: int,
                    stop_event: threading.Event, stats: dict, stats_lock: threading.Lock):
    import sqlite3
    STALE_RUNNING_SEC = 1800  # 30 min : sol running plus longtemps = stuck, reset
    while not stop_event.wait(interval_s):
        try:
            _final_db.update_heartbeat(db_path, run_id)
            db_stats = _final_db.get_stats(db_path, run_id)
            by_status = db_stats["by_status"]
            with stats_lock:
                snap = dict(stats)
            # Reset des sols running stuck (filet de secours si worker thread mort)
            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                conn.execute("PRAGMA busy_timeout=30000")
                cur = conn.execute(
                    "UPDATE final_solutions SET status='pending', started_at=NULL, hostname=NULL "
                    "WHERE run_id=? AND status='running' "
                    "AND (julianday('now') - julianday(started_at)) * 86400 > ?",
                    (run_id, STALE_RUNNING_SEC),
                )
                n_stale_reset = cur.rowcount
                conn.commit()
                conn.close()
                if n_stale_reset > 0:
                    _log(f"HEARTBEAT reset {n_stale_reset} stale running -> pending (>{STALE_RUNNING_SEC}s)")
            except Exception as e:
                _log(f"heartbeat stale-reset error: {e}")
            _log(
                f"HEARTBEAT db={by_status} session=batches_ok={snap['batches_ok']} "
                f"timeout={snap['batches_timeout']} ssh_err={snap['batches_failed']} "
                f"sols_done={snap['sols_done']} sols_failed={snap['sols_failed']}"
            )
            # Detection completion : 0 pending et 0 running
            n_pending = by_status.get("pending", 0)
            n_running = by_status.get("running", 0)
            if n_pending == 0 and n_running == 0:
                _log("All sols done/failed (terminal state), signaling stop")
                stop_event.set()
                return
        except Exception as e:
            _log(f"heartbeat error: {e}")


def run_dispatcher(
    db_path: str, run_id: int,
    workers: list, batch_size: int,
    max_parallel_xtb: int, timeout_xtb: int,
    ssh_timeout_s: int, heartbeat_s: int,
):
    """Boucle principale du dispatcher. Bloque jusqu'a fin du run."""
    n_reset = _final_db.reset_stale_running(db_path, run_id)
    if n_reset > 0:
        _log(f"Reset {n_reset} 'running' sols a 'pending' (reprise apres crash)")

    initial_stats = _final_db.get_stats(db_path, run_id)
    _log(f"Initial DB stats: {initial_stats['by_status']}")

    stop_event = threading.Event()
    stats = {
        "batches_ok": 0, "batches_timeout": 0, "batches_failed": 0,
        "sols_done": 0, "sols_failed": 0,
    }
    stats_lock = threading.Lock()
    claim_lock = threading.Lock()

    threads = []
    for host in workers:
        t = threading.Thread(
            target=_worker_thread_loop,
            args=(host, db_path, run_id, batch_size, max_parallel_xtb,
                  timeout_xtb, ssh_timeout_s, stop_event, stats, stats_lock,
                  claim_lock),
            daemon=True,
        )
        t.start()
        threads.append(t)

    hb = threading.Thread(
        target=_heartbeat_loop,
        args=(db_path, run_id, heartbeat_s, stop_event, stats, stats_lock),
        daemon=True,
    )
    hb.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        _log("KeyboardInterrupt -- shutting down threads")
        stop_event.set()
        for t in threads:
            t.join(timeout=5)

    stop_event.set()
    hb.join(timeout=5)

    final_stats = _final_db.get_stats(db_path, run_id)
    _log(f"FINAL DB stats: {final_stats['by_status']}")
    if final_stats["by_status"].get("pending", 0) == 0 and \
       final_stats["by_status"].get("running", 0) == 0:
        _final_db.mark_run_completed(db_path, run_id)
        _log(f"Run {run_id} marked completed")


def main():
    ap = argparse.ArgumentParser(description="Dispatcher du run final h3-h9")
    ap.add_argument("--db", required=True, help="Chemin DB Final")
    ap.add_argument("--run-id", type=int, required=True, help="ID du run a traiter")
    ap.add_argument("--workers", default="49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64",
                    help="Liste IPs courtes des workers (suffixe 192.168.200.X), separes par ,")
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--max-parallel-xtb", type=int, default=40)
    ap.add_argument("--timeout-xtb", type=int, default=50000)
    ap.add_argument("--ssh-timeout", type=int, default=18000,
                    help="Timeout SSH global par batch (defaut 5h)")
    ap.add_argument("--heartbeat", type=int, default=60)
    args = ap.parse_args()

    workers = [f"192.168.200.{s.strip()}" for s in args.workers.split(",") if s.strip()]
    _log(f"Workers: {workers}")

    run_dispatcher(
        db_path=args.db,
        run_id=args.run_id,
        workers=workers,
        batch_size=args.batch_size,
        max_parallel_xtb=args.max_parallel_xtb,
        timeout_xtb=args.timeout_xtb,
        ssh_timeout_s=args.ssh_timeout,
        heartbeat_s=args.heartbeat,
    )


if __name__ == "__main__":
    main()
