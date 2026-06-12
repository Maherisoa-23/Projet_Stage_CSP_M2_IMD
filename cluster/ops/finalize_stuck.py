"""Finalise les sols pending restantes en mode SEQUENTIEL (pas de threading).

Resout les problemes de race SQLite + workers stuck du dispatcher
multi-thread. Round-robin sur les 16 machines avec blacklist temporaire
pour les machines qui timeout.

Lance via :
  nohup python finalize_stuck.py --db ~/projet/final_h3_h9.db --run-id 1 > finalize.log 2>&1 &
"""

import argparse
import gzip
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


CONDA_INIT = (
    'eval "$(/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook)" '
    '&& conda activate nonbenz'
)
REMOTE_PROJECT_PATH = "~/projet"

# Machines workers
ALL_MACHINES = [f"192.168.200.{i}" for i in range(49, 65)]

# Blacklist : machine -> timestamp jusqu'a quand elle est exclue
BLACKLIST_DURATION_S = 300  # 5 min


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ssh_run_worker(host, sol_input, ssh_timeout_s):
    """Envoie 1 sol via SSH au worker batch, retourne dict result.

    Leve subprocess.TimeoutExpired si SSH stuck.
    """
    remote_cmd = (
        f'{CONDA_INIT} && cd {REMOTE_PROJECT_PATH} '
        f'&& python -m csp_solver._worker_batch'
    )
    ssh_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=4",
        "-o", "ConnectTimeout=10",
        "-o", "TCPKeepAlive=yes",
        host,
        remote_cmd,
    ]
    batch_input = {
        "max_parallel": 1,
        "timeout_xtb": 300,
        "sols": [sol_input],
    }
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
        raise RuntimeError(f"SSH returncode={proc.returncode} stderr={proc.stderr[:200]!r}")
    out = json.loads(proc.stdout)
    results = out.get("results", [])
    if not results:
        raise RuntimeError("Worker retourne 0 results")
    return results[0]


def commit_result(conn, sol_id, result):
    """Commit le result d'une sol dans la DB."""
    xyz_gz = None
    if result.get("xyz_optimized"):
        xyz_gz = gzip.compress(result["xyz_optimized"].encode("utf-8"))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
            result.get("error_message"),
            result.get("hostname"),
            now,
            sol_id,
        ),
    )
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--run-id", type=int, default=1)
    ap.add_argument("--ssh-timeout", type=int, default=120,
                    help="Timeout SSH par sol (defaut 120s)")
    ap.add_argument("--max-blacklist-loops", type=int, default=3,
                    help="Combien de fois on parcourt les machines avant abandon")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row

    log("=== finalize_stuck START ===")

    # Recup sols pending
    sols = conn.execute(
        "SELECT sol_id, size_h, config, graph_name, sol_index, "
        "       graph_content_gz, csp_solution_json "
        "FROM final_solutions WHERE run_id=? AND status='pending' "
        "ORDER BY sol_id",
        (args.run_id,),
    ).fetchall()
    log(f"  {len(sols)} sols pending a traiter")

    if not sols:
        log("Rien a faire, fin.")
        return

    blacklist = {}  # host -> ts_expire
    machine_idx = 0
    n_done = 0
    n_failed = 0

    for sol in sols:
        sol_id = sol["sol_id"]
        sol_input = {
            "sol_id": sol_id,
            "graph_content": gzip.decompress(sol["graph_content_gz"]).decode("utf-8"),
            "csp_solution": json.loads(sol["csp_solution_json"]),
            "sol_index": sol["sol_index"],
        }

        # Marquer running
        conn.execute(
            "UPDATE final_solutions SET status='running', started_at=? WHERE sol_id=?",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), sol_id),
        )
        conn.commit()

        attempt = 0
        result = None
        loops_full_blacklist = 0
        while True:
            # Pick prochaine machine non blacklistee
            now = time.time()
            blacklist = {h: t for h, t in blacklist.items() if t > now}
            tried_all = True
            for _ in range(len(ALL_MACHINES)):
                machine_idx = (machine_idx + 1) % len(ALL_MACHINES)
                host = ALL_MACHINES[machine_idx]
                if host not in blacklist:
                    tried_all = False
                    break
            if tried_all:
                loops_full_blacklist += 1
                if loops_full_blacklist >= args.max_blacklist_loops:
                    log(f"  sol{sol_id} : toutes machines blacklistees apres {loops_full_blacklist} loops, ABANDON")
                    break
                log(f"  sol{sol_id} : toutes blacklistees, attente 60s...")
                time.sleep(60)
                blacklist = {}  # reset blacklist
                continue

            attempt += 1
            try:
                t0 = time.perf_counter()
                result = ssh_run_worker(host, sol_input, args.ssh_timeout)
                dt = time.perf_counter() - t0
                log(f"  sol{sol_id} h{sol['size_h']} {sol['config']} -> {host} OK ({dt:.1f}s) verdict={result.get('verdict')}")
                break
            except subprocess.TimeoutExpired:
                log(f"  sol{sol_id} -> {host} TIMEOUT ({args.ssh_timeout}s), blacklist {BLACKLIST_DURATION_S}s")
                blacklist[host] = time.time() + BLACKLIST_DURATION_S
            except Exception as e:
                log(f"  sol{sol_id} -> {host} ERREUR: {e}")
                blacklist[host] = time.time() + BLACKLIST_DURATION_S
            if attempt >= 5:
                log(f"  sol{sol_id} : 5 tentatives epuisees, ABANDON")
                break

        if result and result.get("status") == "done":
            commit_result(conn, sol_id, result)
            n_done += 1
        else:
            # Mark failed
            conn.execute(
                "UPDATE final_solutions SET status='failed', "
                "  error_message=?, finished_at=? WHERE sol_id=?",
                (
                    "finalize_stuck: SSH inaccessible apres retries",
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    sol_id,
                ),
            )
            conn.commit()
            n_failed += 1

        if (n_done + n_failed) % 10 == 0:
            log(f"  Progress: {n_done + n_failed}/{len(sols)} (done={n_done} failed={n_failed})")

    log(f"=== finalize_stuck END : done={n_done}, failed={n_failed}, total={len(sols)} ===")

    # Si plus rien de running/pending, marquer le run completed
    n_remain = conn.execute(
        "SELECT COUNT(*) FROM final_solutions WHERE run_id=? AND status IN ('pending', 'running')",
        (args.run_id,),
    ).fetchone()[0]
    if n_remain == 0:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "UPDATE final_runs SET state='completed', finished_at=? WHERE run_id=?",
            (now, args.run_id),
        )
        conn.commit()
        log(f"Run {args.run_id} marque completed.")

    conn.close()


if __name__ == "__main__":
    main()
