"""Lance le bench ACE vs Choco en LOCAL en multiprocessing.

Equivalent au dispatcher cluster mais sans SSH : utilise un Pool de N
workers locaux. Chaque worker = 1 subprocess qui claim + run + commit.

Reprend la-ou on s'est arrete : les rows running sont reset au demarrage,
puis on traite les pending.

Usage :
    python scripts/bench_local.py --db tmp/solver_bench.db \\
        --workers 6 --batch-size 4 --timeout-s 300
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "csp_solver"))

from csp_solver.final import bench_db as _bdb  # noqa


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def worker_loop(worker_id, db_path, python_exe, batch_size, timeout_s, claim_lock):
    """Boucle d'un worker local."""
    hostname = f"local-w{worker_id}"
    while True:
        with claim_lock:
            batch = _bdb.claim_batch(db_path, batch_size, hostname)
        if not batch:
            stats = _bdb.get_stats(db_path)
            n_pend = stats["by_status"].get("pending", 0)
            if n_pend == 0:
                _log(f"[w{worker_id}] no more pending, exit")
                return
            time.sleep(5)
            continue

        # Compose payload pour bench_worker
        payload = {
            "timeout_s": timeout_s,
            "items": [
                {"h": b["h"], "config": b["config"], "graph_name": b["graph_name"],
                 "graph_content": b["graph_content"]} for b in batch
            ],
        }

        try:
            t0 = time.perf_counter()
            proc = subprocess.run(
                [python_exe, "-m", "csp_solver.final.bench_worker"],
                input=json.dumps(payload),
                capture_output=True, text=True,
                timeout=timeout_s * len(batch) * 2 + 60,  # gros marge
                cwd=str(PROJECT_ROOT),
            )
            dt = time.perf_counter() - t0
        except subprocess.TimeoutExpired:
            _log(f"[w{worker_id}] SUBPROCESS TIMEOUT, retry batch")
            for b in batch:
                _bdb.mark_failed_or_retry(db_path, b["h"], b["config"],
                                           b["graph_name"], "subproc_timeout")
            continue

        if proc.returncode != 0:
            _log(f"[w{worker_id}] WORKER FAIL rc={proc.returncode}: "
                 f"{(proc.stderr or '')[-200:]}")
            for b in batch:
                _bdb.mark_failed_or_retry(db_path, b["h"], b["config"],
                                           b["graph_name"],
                                           f"worker_fail_rc={proc.returncode}")
            continue

        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            _log(f"[w{worker_id}] BAD JSON: {e}")
            for b in batch:
                _bdb.mark_failed_or_retry(db_path, b["h"], b["config"],
                                           b["graph_name"], "bad_json")
            continue

        # Commit chaque resultat
        for res in out["results"]:
            _bdb.commit_result(db_path, res["h"], res["config"],
                                res["graph_name"], res["result"], hostname)

        # Brief log : worst time of batch (pour reperer les longs)
        worst_ace = max((r["result"].get("t_ace_ms", 0) or 0)
                        for r in out["results"])
        worst_choco = max((r["result"].get("t_choco_ms", 0) or 0)
                          for r in out["results"])
        first = batch[0]
        _log(f"[w{worker_id}] h{first['h']} {first['config']:<6} "
             f"+{len(batch):>2} sols in {dt:>5.1f}s "
             f"(worst ACE={worst_ace}ms Choco={worst_choco}ms)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--timeout-s", type=int, default=300)
    args = ap.parse_args()

    db = args.db
    Path(db).parent.mkdir(parents=True, exist_ok=True)

    # Reset stale running
    n = _bdb.reset_stale_running(db)
    if n:
        _log(f"Reset {n} stale 'running' to 'pending'")

    stats = _bdb.get_stats(db)
    _log(f"Start: status={stats['by_status']}")

    python_exe = sys.executable
    _log(f"Python : {python_exe}")
    _log(f"Workers: {args.workers}, batch_size: {args.batch_size}, "
         f"timeout_s: {args.timeout_s}")

    claim_lock = threading.Lock()
    threads = []
    for i in range(args.workers):
        t = threading.Thread(target=worker_loop, args=(
            i, db, python_exe, args.batch_size, args.timeout_s, claim_lock
        ), daemon=False)
        t.start()
        threads.append(t)

    # Heartbeat
    last_hb = time.time()
    last_done = stats["by_status"].get("done", 0)
    while any(t.is_alive() for t in threads):
        time.sleep(10)
        if time.time() - last_hb > 60:
            s = _bdb.get_stats(db)
            done = s["by_status"].get("done", 0)
            pend = s["by_status"].get("pending", 0)
            run = s["by_status"].get("running", 0)
            fail = s["by_status"].get("failed", 0)
            rate = (done - last_done) / 60.0  # done/sec depuis last hb
            eta_min = pend / max(rate, 0.01) / 60.0
            _log(f"HEARTBEAT done={done:,}/{done+pend+run+fail:,} "
                 f"running={run} failed={fail} "
                 f"rate={rate:.1f}/s ETA={eta_min:.0f}min")
            last_hb = time.time()
            last_done = done

    for t in threads:
        t.join()

    s = _bdb.get_stats(db)
    _log(f"=== DONE === final: {s['by_status']}")


if __name__ == "__main__":
    main()
