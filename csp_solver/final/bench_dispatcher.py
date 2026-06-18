"""Dispatcher (master) du bench ACE vs Choco sur cluster COALA.

Reutilise l'infra SSH du dispatcher principal :
  - Pool de N threads SSH (1 par worker host)
  - Chaque thread claim un batch dans solver_bench.db, SSH vers le worker,
    le worker fait benchmark_one, le master commit les resultats
  - Sortie : solver_bench.db avec status='done' pour toutes les instances

Usage cluster :
  # 1. Init + populate (sur master, depuis n'importe quelle machine ayant la DB)
  python -m csp_solver.final.bench_dispatcher setup --db ~/solver_bench.db \\
      --project-root ~/projet --sizes 3,4,5,6,7,8,9 --configs C1,C2,C3,Ctopo

  # 2. Lance le dispatcher (depuis le master, SSH vers les workers)
  nohup python -m csp_solver.final.bench_dispatcher run --db ~/solver_bench.db \\
      --workers "49,50,...,64" --batch-size 8 --timeout-s 300 \\
      > ~/bench_dispatcher.log 2>&1 &

  # 3. Monitorer
  python -m csp_solver.final.bench_dispatcher status --db ~/solver_bench.db

Variables d'environnement (idem dispatcher principal) :
  CSP_CLUSTER_CONDA_INIT, CSP_CLUSTER_PROJECT_PATH.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def _ensure_imports():
    here = Path(__file__).resolve().parent
    csp_solver_dir = here.parent
    if str(csp_solver_dir) not in sys.path:
        sys.path.insert(0, str(csp_solver_dir))
    if str(csp_solver_dir.parent) not in sys.path:
        sys.path.insert(0, str(csp_solver_dir.parent))


_ensure_imports()

from csp_solver.final import bench_db as _bdb  # noqa: E402


CONDA_INIT = os.environ.get(
    "CSP_CLUSTER_CONDA_INIT",
    'eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" '
    '&& conda activate nonbenz',
)
REMOTE_PROJECT_PATH = os.environ.get("CSP_CLUSTER_PROJECT_PATH", "~/projet")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    print(f"[{_now()}] {msg}", flush=True)


# =====================================================================
#  SSH worker invocation
# =====================================================================

def _ssh_run_worker(host: str, payload: dict, ssh_timeout_s: int) -> dict:
    remote_cmd = (
        f'{CONDA_INIT} && cd {REMOTE_PROJECT_PATH} '
        f'&& python -m csp_solver.final.bench_worker'
    )
    ssh_cmd = [
        "ssh", "-o", "BatchMode=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=10",
        "-o", "ConnectTimeout=15",
        "-o", "TCPKeepAlive=yes",
        host, remote_cmd,
    ]
    proc = subprocess.run(
        ssh_cmd, input=json.dumps(payload),
        capture_output=True, text=True,
        timeout=ssh_timeout_s, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"SSH worker rc={proc.returncode} stderr={(proc.stderr or '').strip()[-500:]!r}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON from worker: {e}; stdout_tail={(proc.stdout or '')[-500:]!r}"
        )


# =====================================================================
#  Worker thread loop
# =====================================================================

class _NoMorePending(Exception):
    pass


def _worker_iter(host, db_path, batch_size, timeout_s, ssh_timeout_s,
                  claim_lock, stats, stats_lock):
    """1 itération : claim, SSH, commit."""
    with claim_lock:
        batch = _bdb.claim_batch(db_path, batch_size, host)
    if not batch:
        stats_db = _bdb.get_stats(db_path)
        n_pend = stats_db["by_status"].get("pending", 0)
        if n_pend == 0:
            raise _NoMorePending()
        _log(f"[{host}] claim returned 0 but {n_pend} pending; retry in 10s")
        time.sleep(10)
        return

    _log(f"[{host}] claimed {len(batch)} items")

    payload = {"timeout_s": timeout_s,
               "items": [{"h": b["h"], "config": b["config"],
                          "graph_name": b["graph_name"],
                          "graph_content": b["graph_content"]} for b in batch]}

    try:
        t0 = time.perf_counter()
        out = _ssh_run_worker(host, payload, ssh_timeout_s)
        dt = time.perf_counter() - t0
        _log(f"[{host}] SSH ok in {dt:.1f}s, {len(out.get('results',[]))} results")
    except subprocess.TimeoutExpired:
        _log(f"[{host}] SSH TIMEOUT, retry batch")
        for b in batch:
            _bdb.mark_failed_or_retry(db_path, b["h"], b["config"],
                                       b["graph_name"], "ssh_timeout")
        return
    except Exception as e:
        _log(f"[{host}] SSH ERROR: {e}")
        for b in batch:
            _bdb.mark_failed_or_retry(db_path, b["h"], b["config"],
                                       b["graph_name"], f"ssh_error:{e}")
        return

    for res in out.get("results", []):
        h = int(res["h"])
        cfg = res["config"]
        gn = res["graph_name"]
        r = res["result"]
        _bdb.commit_result(db_path, h, cfg, gn, r, host)

    with stats_lock:
        stats["batches"] += 1
        stats["items"] += len(batch)


def _worker_loop(host, db_path, batch_size, timeout_s, ssh_timeout_s,
                  stop_event, claim_lock, stats, stats_lock):
    _log(f"[{host}] worker started")
    while not stop_event.is_set():
        try:
            _worker_iter(host, db_path, batch_size, timeout_s, ssh_timeout_s,
                          claim_lock, stats, stats_lock)
        except _NoMorePending:
            _log(f"[{host}] no more pending, exit")
            return
        except Exception as e:
            _log(f"[{host}] LOOP EXCEPTION: {e}")
            time.sleep(10)
    _log(f"[{host}] worker stopped")


# =====================================================================
#  Commandes CLI
# =====================================================================

def cmd_setup(args):
    """Init DB + populate avec toutes les (h, config, graph)."""
    project_root = args.project_root or str(Path(__file__).resolve().parent.parent.parent)
    sizes = [int(s) for s in args.sizes.split(",")]
    configs = args.configs.split(",")
    _bdb.init_db(args.db)
    _log(f"DB initialised : {args.db}")
    n = _bdb.populate(args.db, sizes, configs, project_root)
    _log(f"Inserted {n:,} new (h, config, graph) rows")
    cmd_status(args)


def cmd_run(args):
    """Boucle dispatcher : SSH workers."""
    workers = [f"192.168.200.{w.strip()}" for w in args.workers.split(",")
               if w.strip()]
    _log(f"Workers: {workers}")
    _log(f"Batch size: {args.batch_size}, timeout_s: {args.timeout_s}")

    # Reset stale
    n = _bdb.reset_stale_running(args.db)
    if n:
        _log(f"Reset {n} stale 'running' rows to 'pending'")

    stop_event = threading.Event()
    claim_lock = threading.Lock()
    stats = {"batches": 0, "items": 0}
    stats_lock = threading.Lock()

    threads = []
    for h in workers:
        t = threading.Thread(target=_worker_loop, args=(
            h, args.db, args.batch_size, args.timeout_s, args.ssh_timeout,
            stop_event, claim_lock, stats, stats_lock,
        ), daemon=False)
        t.start()
        threads.append(t)

    # Heartbeat : log status periodiquement
    last_heartbeat = time.time()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(30)
            now = time.time()
            if now - last_heartbeat > 60:
                s = _bdb.get_stats(args.db)
                _log(f"HEARTBEAT : status={s['by_status']}  "
                     f"batches={stats['batches']} items={stats['items']}")
                last_heartbeat = now
    except KeyboardInterrupt:
        _log("KeyboardInterrupt : stopping workers")
        stop_event.set()

    for t in threads:
        t.join(timeout=60)
    _log("=== ALL WORKERS DONE ===")
    cmd_status(args)


def cmd_status(args):
    """Affiche les stats du bench."""
    s = _bdb.get_stats(args.db)
    _log(f"by_status: {s['by_status']}")
    _log("by (h, config) :")
    for (h, cfg), d in sorted(s["by_h_config"].items()):
        total = sum(d.values())
        done = d.get("done", 0)
        pend = d.get("pending", 0)
        run = d.get("running", 0)
        fail = d.get("failed", 0)
        pct = (100.0 * done / total) if total else 0
        _log(f"  h{h} {cfg:<8} : {done:>5}/{total:>5} done ({pct:>5.1f}%)  "
             f"pending={pend} running={run} failed={fail}")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)

    p1 = sp.add_parser("setup")
    p1.add_argument("--db", required=True)
    p1.add_argument("--project-root", default=None)
    p1.add_argument("--sizes", default="3,4,5,6,7,8,9")
    p1.add_argument("--configs", default="C1,C2,C3,Ctopo")
    p1.set_defaults(func=cmd_setup)

    p2 = sp.add_parser("run")
    p2.add_argument("--db", required=True)
    p2.add_argument("--workers", default="49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64")
    p2.add_argument("--batch-size", type=int, default=8)
    p2.add_argument("--timeout-s", type=int, default=300,
                    help="Timeout par solveur par instance (sec)")
    p2.add_argument("--ssh-timeout", type=int, default=2000,
                    help="Timeout SSH global pour un batch (sec)")
    p2.set_defaults(func=cmd_run)

    p3 = sp.add_parser("status")
    p3.add_argument("--db", required=True)
    p3.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
