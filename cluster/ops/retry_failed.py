"""Retry les sols failed avec perturbation random forte (mode fallback).

Pour les sols ou la reconstruction 3D a des atomes superposes, la
perturbation deterministe structuree (amp=0.05) ne suffit pas a evacuer
les degenerescences geometriques. On utilise une perturbation random
deterministe (random.Random(seed) + uniform(-1, 1)) avec amplitude 1.0 A
qui ecarte les atomes superposes tout en restant byte-deterministe.

Strategie : pool de threads SSH (1 par machine cluster), batch de sols
failed envoyes au _worker_batch existant avec perturb_params={mode:random}.
"""

import argparse
import gzip
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

WORKERS = [f"192.168.200.{i}" for i in range(49, 65)]
CONDA_INIT = 'eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" && conda activate nonbenz'
REMOTE_PROJECT = "~/projet"


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ssh_run_batch(host, batch_input, ssh_timeout_s):
    """Lance worker_batch sur host via SSH, retourne dict resultats."""
    remote_cmd = (
        f'{CONDA_INIT} && cd {REMOTE_PROJECT} '
        f'&& python -m csp_solver._worker_batch'
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
        raise RuntimeError(f"SSH returncode={proc.returncode} stderr={(proc.stderr or '')[:300]!r}")
    return json.loads(proc.stdout)


def commit_result(conn, sol_id, result):
    """Update sol avec result. Marque error_message specifique au fallback."""
    xyz_gz = None
    if result.get("xyz_optimized"):
        xyz_gz = gzip.compress(result["xyz_optimized"].encode("utf-8"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    err_msg = result.get("error_message")
    if result.get("status") == "done":
        err_msg = "retry_fallback_random_amp1_seed42"  # trace pour rapport
    conn.execute(
        "UPDATE final_solutions SET "
        "  status=?, verdict=?, angle_deg=?, energy_eh=?, homo_lumo_ev=?, "
        "  cpu_time_s=?, wall_time_s=?, xyz_optimized_gz=?, "
        "  error_message=?, hostname=?, finished_at=? "
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
            err_msg,
            result.get("hostname"),
            now,
            sol_id,
        ),
    )
    conn.commit()


def worker_thread(host, sol_queue, queue_lock, db_path, ssh_timeout, batch_size, max_parallel, stats, stats_lock):
    """Thread qui prend des sols dans la queue, envoie au worker via SSH, commit."""
    log(f"[{host}] thread started")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    while True:
        with queue_lock:
            if not sol_queue:
                break
            batch = []
            while sol_queue and len(batch) < batch_size:
                batch.append(sol_queue.pop())
        if not batch:
            break

        batch_input = {
            "max_parallel": max_parallel,
            "timeout_xtb": 300,
            "perturb_params": {
                "mode": "random",
                "amplitude": 1.0,
                "seed": 42,
            },
            "fallback_cascade": [
                {"mode": "random", "amplitude": 2.0, "seed": 42},
                {"mode": "random", "amplitude": 1.0, "seed": 7},
                {"mode": "random", "amplitude": 3.0, "seed": 42},
                {"mode": "random", "amplitude": 2.0, "seed": 100},
                {"mode": "random", "amplitude": 2.0, "seed": 13},
            ],
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

        try:
            t0 = time.perf_counter()
            out = ssh_run_batch(host, batch_input, ssh_timeout)
            dt = time.perf_counter() - t0
        except Exception as e:
            log(f"[{host}] SSH error: {str(e)[:200]}, releasing batch back to queue")
            with queue_lock:
                sol_queue.extend(batch)
            time.sleep(10)
            continue

        n_done = n_failed = 0
        for r in out.get("results", []):
            commit_result(conn, r["sol_id"], r)
            if r.get("status") == "done":
                n_done += 1
            else:
                n_failed += 1
        log(f"[{host}] batch {len(batch)} sols -> {n_done} done, {n_failed} failed in {dt:.1f}s")
        with stats_lock:
            stats["done"] += n_done
            stats["failed"] += n_failed
    conn.close()
    log(f"[{host}] thread exit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-id", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--max-parallel-xtb", type=int, default=20)
    ap.add_argument("--ssh-timeout", type=int, default=600)
    ap.add_argument("--workers", default=None,
                    help="Liste IPs courtes (def: 49..64)")
    args = ap.parse_args()

    if args.workers:
        workers = [f"192.168.200.{s.strip()}" for s in args.workers.split(",")]
    else:
        workers = WORKERS

    log(f"=== retry_failed START ({len(workers)} workers) ===")

    conn0 = sqlite3.connect(args.db, timeout=30.0)
    conn0.row_factory = sqlite3.Row
    # Fetch sols failed OR pending (=non-traitees encore)
    sols = conn0.execute(
        "SELECT sol_id, size_h, config, graph_name, sol_index, "
        "       graph_content_gz, csp_solution_json "
        "FROM final_solutions WHERE run_id=? AND status IN ('failed', 'pending')",
        (args.run_id,),
    ).fetchall()
    log(f"  {len(sols)} sols a retraiter (failed + pending)")

    if not sols:
        log("Rien a faire.")
        return

    # Prepare queue (decompresse une fois)
    sol_queue = []
    for r in sols:
        sol_queue.append({
            "sol_id": r["sol_id"],
            "size_h": r["size_h"],
            "config": r["config"],
            "graph_name": r["graph_name"],
            "sol_index": r["sol_index"],
            "graph_content": gzip.decompress(r["graph_content_gz"]).decode("utf-8"),
            "csp_solution": json.loads(r["csp_solution_json"]),
        })
    conn0.close()

    queue_lock = threading.Lock()
    stats = {"done": 0, "failed": 0}
    stats_lock = threading.Lock()

    threads = []
    for host in workers:
        t = threading.Thread(
            target=worker_thread,
            args=(host, sol_queue, queue_lock, args.db, args.ssh_timeout,
                  args.batch_size, args.max_parallel_xtb, stats, stats_lock),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Heartbeat periodique
    def heartbeat():
        while any(t.is_alive() for t in threads):
            time.sleep(60)
            with stats_lock:
                snap = dict(stats)
            with queue_lock:
                remaining = len(sol_queue)
            log(f"HEARTBEAT done={snap['done']} failed={snap['failed']} queue={remaining}")
    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()

    for t in threads:
        t.join()

    log(f"=== retry_failed END : done={stats['done']}, failed={stats['failed']} ===")


if __name__ == "__main__":
    main()
