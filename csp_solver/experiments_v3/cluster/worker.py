"""Worker cluster pour experiments_v3.

Duplique experiments_v2/cluster/worker.py mais :
  - SCRATCH_PREFIX = "coala_v3_" (separation)
  - RUN_ONE_JOB pointe sur experiments_v3/run_one_job.py
  - propage entry["extra_flags"] vers run_one_job_v3 (--no-freeze etc)

Reste : pull-based, atomic claims sur NFS, ProcessPoolExecutor.

Usage :
    python -m csp_solver.experiments_v3.cluster.worker \\
        --manifest FILE --output-root DIR --claims-dir DIR \\
        [--scratch-root DIR] [--concurrency N] [--timeout SEC]
"""

import argparse
import errno
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from datetime import datetime
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[3]))
    __package__ = "csp_solver.experiments_v3.cluster"


SCRATCH_PREFIX = "coala_v3_"

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("PYTHONHASHSEED", "0")


_HERE = Path(__file__).resolve().parent
RUN_ONE_JOB = _HERE.parent / "run_one_job.py"


def load_manifest(manifest_path):
    entries = []
    with open(manifest_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARN ligne {line_no} ignoree: {e}", file=sys.stderr)
    return entries


def try_claim(lock_path):
    try:
        fd = os.open(str(lock_path),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        info = f"{socket.gethostname()}:{os.getpid()}:{datetime.now().isoformat(timespec='seconds')}\n"
        os.write(fd, info.encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError as e:
        if e.errno == errno.EEXIST:
            return False
        print(f"WARN claim {lock_path}: {e}", file=sys.stderr)
        return False


def cleanup_orphan_scratch(scratch_root, max_age_min=60):
    scratch_root = Path(scratch_root)
    if not scratch_root.is_dir():
        return
    cutoff = time.time() - max_age_min * 60
    n = 0
    for d in scratch_root.glob(f"{SCRATCH_PREFIX}*"):
        if not d.is_dir():
            continue
        try:
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        except OSError as e:
            print(f"  WARN cleanup {d.name}: {e}", file=sys.stderr)
    if n:
        print(f"  cleanup orphan : {n} scratch supprimes", flush=True)


def is_done(entry, output_root):
    status_path = (Path(output_root) / entry["h"] / entry["config"]
                   / entry["mol"] / "job_status.json")
    return status_path.exists()


def execute_job(entry, output_root, scratch_root, timeout_sec):
    t0 = time.time()
    cmd = [
        sys.executable, str(RUN_ONE_JOB),
        "--graph", entry["graph"],
        "--config", entry["config"],
        "--output-root", str(output_root),
        "--scratch-root", str(scratch_root),
        "--timeout", str(timeout_sec),
    ]
    for flag in entry.get("extra_flags", []):
        cmd.append(f"--{flag}")
    try:
        result = subprocess.run(cmd, timeout=2 * timeout_sec + 60)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        rc = -1
    return {
        "job_id": entry["job_id"],
        "returncode": rc,
        "duration_sec": round(time.time() - t0, 1),
    }


def worker_main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--claims-dir", required=True)
    parser.add_argument("--scratch-root", default="/tmp")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--shuffle-seed", type=int, default=None)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    output_root = Path(args.output_root).resolve()
    claims_dir = Path(args.claims_dir).resolve()
    scratch_root = Path(args.scratch_root).resolve()

    if not manifest_path.is_file():
        print(f"ERR manifest introuvable : {manifest_path}", file=sys.stderr)
        sys.exit(2)
    if not RUN_ONE_JOB.is_file():
        print(f"ERR run_one_job_v3 introuvable : {RUN_ONE_JOB}", file=sys.stderr)
        sys.exit(2)

    claims_dir.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)
    cleanup_orphan_scratch(scratch_root, max_age_min=60)

    host = socket.gethostname()
    pid = os.getpid()
    print(f"=== Worker_v3 {host}:{pid} demarre ===", flush=True)
    print(f"  manifest    : {manifest_path}", flush=True)
    print(f"  output_root : {output_root}", flush=True)
    print(f"  claims_dir  : {claims_dir}", flush=True)
    print(f"  scratch     : {scratch_root}", flush=True)
    print(f"  concurrency : {args.concurrency}", flush=True)

    entries = load_manifest(manifest_path)
    print(f"  manifest    : {len(entries)} jobs au total", flush=True)

    rng = random.Random(args.shuffle_seed)
    rng.shuffle(entries)

    n_skip_done = n_skip_locked = n_submitted = n_ok = n_failed = 0
    pending = set()
    iter_entries = iter(entries)
    no_more = False
    t_start = time.time()

    pool = ProcessPoolExecutor(max_workers=args.concurrency)
    try:
        while True:
            while not no_more and len(pending) < args.concurrency:
                try:
                    entry = next(iter_entries)
                except StopIteration:
                    no_more = True
                    break
                if is_done(entry, output_root):
                    n_skip_done += 1
                    continue
                lock_path = claims_dir / f"{entry['job_id']}.lock"
                if not try_claim(lock_path):
                    n_skip_locked += 1
                    continue
                future = pool.submit(execute_job, entry,
                                      output_root, scratch_root, args.timeout)
                pending.add(future)
                n_submitted += 1
                print(f"  [submit] {entry['job_id']} (en cours: {len(pending)}, "
                      f"total: {n_submitted})", flush=True)
            if not pending:
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    res = fut.result()
                    if res["returncode"] == 0:
                        n_ok += 1; marker = "[ok]"
                    else:
                        n_failed += 1; marker = f"[FAIL rc={res['returncode']}]"
                    print(f"  {marker} {res['job_id']} ({res['duration_sec']}s)",
                          flush=True)
                except Exception as e:
                    n_failed += 1
                    print(f"  [CRASH] {e}", flush=True)
    finally:
        pool.shutdown(wait=True)

    duration = round(time.time() - t_start, 1)
    print(f"\n=== Worker_v3 {host}:{pid} termine ({duration}s) ===", flush=True)
    print(f"  soumis      : {n_submitted}", flush=True)
    print(f"  reussis     : {n_ok}", flush=True)
    print(f"  echecs      : {n_failed}", flush=True)
    print(f"  skip done   : {n_skip_done}", flush=True)
    print(f"  skip locked : {n_skip_locked}", flush=True)


if __name__ == "__main__":
    worker_main()
