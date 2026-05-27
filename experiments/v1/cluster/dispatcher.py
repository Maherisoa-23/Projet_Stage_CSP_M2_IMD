"""
Dispatcher : lance N workers en parallele, les surveille, les arrete.

Deux backends :
  - LOCAL : N workers en subprocess.Popen sur la machine courante (utile pour
            test bout-en-bout sur PC).
  - SSH   : 1 worker par host distant via SSH non-interactif (production cluster).

Etat persistant : <state_dir>/dispatcher_state.json
    {
      "mode": "local"|"ssh",
      "started_at": "...",
      "manifest": "...", "output_root": "...", "claims_dir": "...",
      "workers": [
        {"id": 0, "pid": 12345, "host": "lis-cluster-coala-49", "log": "..."},
        ...
      ]
    }

Sous-commandes :
  start  : demarre les workers
  status : compte les jobs done/pending/failed depuis le NFS, affiche par host
  stop   : tue tous les workers connus

Usage :
    # Mode local (test sur PC)
    python dispatcher.py start --mode local --workers 2 \\
        --manifest m.jsonl --output-root out --claims-dir claims

    python dispatcher.py status --output-root out --manifest m.jsonl
    python dispatcher.py stop --state-dir cluster_state

    # Mode SSH (production cluster)
    python dispatcher.py start --mode ssh \\
        --hosts lis-cluster-coala-49,lis-cluster-coala-50,...,lis-cluster-coala-64 \\
        --remote-cwd /home/COALA/ramaherisoa/projet/csp_solver/experiments \\
        --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \\
        --conda-env nonbenz \\
        --manifest /home/.../manifest_h6.jsonl \\
        --output-root /home/.../output \\
        --claims-dir /home/.../claims \\
        --concurrency 20

Le code est volontairement minimaliste. Pas de monitoring distant en
streaming : status est un snapshot a la demande, qui lit le NFS.
"""

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


_HERE = Path(__file__).resolve().parent
WORKER_PY = _HERE / "worker.py"


# =====================================================================
#  Helpers : etat persistant
# =====================================================================

def load_state(state_dir):
    state_path = Path(state_dir) / "dispatcher_state.json"
    if not state_path.exists():
        return None
    with open(state_path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state_dir, state):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    state_path = Path(state_dir) / "dispatcher_state.json"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def parse_hosts_arg(s):
    """Accepte 'a,b,c' ou 'lis-cluster-coala-49..64' (range numerique en suffixe)."""
    if ".." in s and "," not in s:
        # ex. 'lis-cluster-coala-49..64'
        prefix, rng = s.rsplit("-", 1)
        if ".." in rng:
            lo, hi = rng.split("..")
            try:
                lo, hi = int(lo), int(hi)
                return [f"{prefix}-{i}" for i in range(lo, hi + 1)]
            except ValueError:
                pass
    # Fallback : separateur virgule
    return [h.strip() for h in s.split(",") if h.strip()]


# =====================================================================
#  Sous-commande : start
# =====================================================================

def start_local(args):
    """Lance N workers sur la machine courante."""
    state_dir = Path(args.state_dir).resolve()
    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    workers = []
    for i in range(args.workers):
        log_path = log_dir / f"worker_local_{i:02d}.log"
        cmd = [
            sys.executable, str(WORKER_PY),
            "--manifest", str(Path(args.manifest).resolve()),
            "--output-root", str(Path(args.output_root).resolve()),
            "--claims-dir", str(Path(args.claims_dir).resolve()),
            "--scratch-root", args.scratch_root,
            "--concurrency", str(args.concurrency),
            "--timeout", str(args.timeout),
            "--shuffle-seed", str(i),    # seeds differents -> ordres differents
        ]
        log_f = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
        workers.append({
            "id": i, "pid": proc.pid, "host": socket.gethostname(),
            "log": str(log_path), "cmd": cmd,
        })
        print(f"  [local#{i}] PID {proc.pid} -> {log_path}", flush=True)

    state = {
        "mode": "local",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": str(Path(args.manifest).resolve()),
        "output_root": str(Path(args.output_root).resolve()),
        "claims_dir": str(Path(args.claims_dir).resolve()),
        "concurrency": args.concurrency,
        "workers": workers,
    }
    save_state(state_dir, state)
    print(f"\n  state -> {state_dir / 'dispatcher_state.json'}", flush=True)


def _build_remote_command(args, host):
    """Construit la commande shell distante a executer via SSH.

    Sequence : cd -> activate conda -> nohup worker -> &
    """
    parts = []
    parts.append(f"cd {shlex.quote(args.remote_cwd)}")
    if args.conda_activate:
        # ex. /home/.../miniforge3/bin/conda shell.bash hook
        parts.append(f'eval "$({args.conda_activate})"')
    if args.conda_env:
        parts.append(f"conda activate {shlex.quote(args.conda_env)}")
    # OMP/MKL belt-and-braces (worker.py les met aussi mais on les pose ici aussi)
    parts.append("export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 "
                 "OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1")
    log_remote = f"{args.remote_log_dir}/worker_{host}.log"
    parts.append(f"mkdir -p {shlex.quote(args.remote_log_dir)}")
    worker_cmd = (
        f"nohup python {shlex.quote(str(args.worker_path))} "
        f"--manifest {shlex.quote(args.manifest)} "
        f"--output-root {shlex.quote(args.output_root)} "
        f"--claims-dir {shlex.quote(args.claims_dir)} "
        f"--scratch-root {shlex.quote(args.scratch_root)} "
        f"--concurrency {args.concurrency} "
        f"--timeout {args.timeout} "
        f"> {shlex.quote(log_remote)} 2>&1 & echo $!"
    )
    parts.append(worker_cmd)
    return " && ".join(parts)


def start_ssh(args):
    """Lance 1 worker par host distant via SSH non-interactif.

    Retourne le PID distant (parse de stdout = 'echo $!').
    Suppose que les cles SSH sont propagees (BatchMode=yes refuse password).
    """
    state_dir = Path(args.state_dir).resolve()
    hosts = parse_hosts_arg(args.hosts)
    if not hosts:
        print("ERREUR: --hosts vide ou invalide", file=sys.stderr)
        sys.exit(2)

    workers = []
    for i, host in enumerate(hosts):
        remote_cmd = _build_remote_command(args, host)
        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            host,
            remote_cmd,
        ]
        print(f"  [ssh#{i}] -> {host} ...", flush=True)
        try:
            result = subprocess.run(
                ssh_cmd, capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT (host non joignable)", flush=True)
            continue

        if result.returncode != 0:
            print(f"    ECHEC ssh (rc={result.returncode}): "
                  f"{result.stderr.strip()[:200]}", flush=True)
            continue

        # La derniere ligne de stdout = PID distant
        remote_pid = None
        for line in reversed(result.stdout.strip().split("\n")):
            line = line.strip()
            if line.isdigit():
                remote_pid = int(line)
                break

        workers.append({
            "id": i, "pid": remote_pid, "host": host,
            "log": f"{args.remote_log_dir}/worker_{host}.log",
        })
        print(f"    PID distant {remote_pid}", flush=True)

    state = {
        "mode": "ssh",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": args.manifest,
        "output_root": args.output_root,
        "claims_dir": args.claims_dir,
        "concurrency": args.concurrency,
        "workers": workers,
        "ssh_config": {
            "remote_cwd": args.remote_cwd,
            "conda_activate": args.conda_activate,
            "conda_env": args.conda_env,
        },
    }
    save_state(state_dir, state)
    print(f"\n  state -> {state_dir / 'dispatcher_state.json'}", flush=True)
    print(f"  {len(workers)}/{len(hosts)} workers demarres", flush=True)


# =====================================================================
#  Sous-commande : status
# =====================================================================

def cmd_status(args):
    """Affiche un snapshot des jobs done/pending depuis le NFS."""
    output_root = Path(args.output_root).resolve()
    if not output_root.is_dir():
        print(f"ERREUR: output_root introuvable : {output_root}", file=sys.stderr)
        sys.exit(2)

    # Charger le manifest pour le total attendu
    n_expected = None
    if args.manifest:
        with open(args.manifest, encoding="utf-8") as f:
            n_expected = sum(1 for line in f if line.strip())

    # Compter les job_status.json
    n_ok = n_failed = n_timeout = n_other = 0
    per_host = {}
    durations = []
    for status_path in output_root.glob("*/*/*/job_status.json"):
        try:
            with open(status_path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        st = d.get("status", "other")
        if st == "ok":
            n_ok += 1
            durations.append(d.get("duration_sec", 0))
        elif st == "failed":
            n_failed += 1
        elif st == "timeout":
            n_timeout += 1
        else:
            n_other += 1
        host = d.get("host", "?")
        per_host[host] = per_host.get(host, 0) + 1

    n_done = n_ok + n_failed + n_timeout + n_other

    # Compter les claims (jobs en cours ou recents)
    n_claimed = 0
    if args.claims_dir:
        claims_dir = Path(args.claims_dir)
        if claims_dir.is_dir():
            n_claimed = sum(1 for _ in claims_dir.glob("*.lock"))

    # ETA
    eta_str = "?"
    if n_expected and n_ok > 0 and durations:
        avg = sum(durations) / len(durations)
        n_remaining = n_expected - n_done
        if args.concurrency:
            eta_sec = (n_remaining * avg) / args.concurrency
            h, rem = divmod(int(eta_sec), 3600)
            m, _ = divmod(rem, 60)
            eta_str = f"~{h}h{m:02d}m"

    print(f"=== status @ {datetime.now().strftime('%H:%M:%S')} ===")
    if n_expected:
        pct = 100 * n_done / n_expected if n_expected else 0
        print(f"  Done       : {n_done}/{n_expected} ({pct:.1f}%)")
    else:
        print(f"  Done       : {n_done}")
    print(f"    OK       : {n_ok}")
    print(f"    Failed   : {n_failed}")
    print(f"    Timeout  : {n_timeout}")
    if n_other:
        print(f"    Autre    : {n_other}")
    if args.claims_dir:
        print(f"  Claimed    : {n_claimed} (locks presents)")
    if n_expected:
        n_pending = n_expected - n_done
        print(f"  Pending    : {n_pending}")
        if eta_str != "?":
            print(f"  ETA        : {eta_str} (avg {sum(durations)/len(durations):.1f}s/job, "
                  f"concurrency {args.concurrency})")

    if per_host:
        print(f"  Hosts      :")
        for host, n in sorted(per_host.items()):
            print(f"    {host:<25} {n} jobs")


# =====================================================================
#  Sous-commande : stop
# =====================================================================

def cmd_stop(args):
    """Tue tous les workers connus du state."""
    state = load_state(args.state_dir)
    if state is None:
        print(f"Aucun state trouve dans {args.state_dir}", file=sys.stderr)
        sys.exit(2)

    mode = state.get("mode")
    workers = state.get("workers", [])
    print(f"=== stop (mode={mode}, {len(workers)} workers) ===")

    if mode == "local":
        for w in workers:
            pid = w.get("pid")
            if pid is None:
                continue
            try:
                # Sur Windows, signal.SIGTERM existe mais on prefere taskkill ;
                # os.kill(pid, signal.SIGTERM) marche generalement aussi.
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                                   capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
                print(f"  [local#{w['id']}] PID {pid} : kill envoye")
            except (OSError, ProcessLookupError) as e:
                print(f"  [local#{w['id']}] PID {pid} : {e}")

    elif mode == "ssh":
        for w in workers:
            host = w["host"]
            ssh_cmd = ["ssh", "-o", "BatchMode=yes",
                       "-o", "ConnectTimeout=10",
                       host, "pkill -f worker.py; true"]
            try:
                result = subprocess.run(ssh_cmd, capture_output=True,
                                        timeout=20, text=True)
                print(f"  [ssh] {host} : pkill envoye (rc={result.returncode})")
            except subprocess.TimeoutExpired:
                print(f"  [ssh] {host} : TIMEOUT")
    else:
        print(f"ERREUR: mode inconnu : {mode}", file=sys.stderr)
        sys.exit(2)


# =====================================================================
#  CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="cmd", required=True)

    # start
    p_start = sub.add_parser("start", help="Demarre les workers")
    p_start.add_argument("--mode", choices=["local", "ssh"], required=True)
    p_start.add_argument("--manifest", required=True)
    p_start.add_argument("--output-root", required=True)
    p_start.add_argument("--claims-dir", required=True)
    p_start.add_argument("--scratch-root", default="/tmp")
    p_start.add_argument("--concurrency", type=int, default=20)
    p_start.add_argument("--timeout", type=int, default=3600)
    p_start.add_argument("--state-dir", default="cluster_state",
                         help="Dossier ou ecrire dispatcher_state.json")
    # local-only
    p_start.add_argument("--workers", type=int, default=2,
                         help="(mode local) nombre de workers a lancer")
    # ssh-only
    p_start.add_argument("--hosts", default=None,
                         help="(mode ssh) hosts separes par virgules ou range "
                              "(ex. lis-cluster-coala-49..64)")
    p_start.add_argument("--remote-cwd", default=None,
                         help="(mode ssh) repertoire de travail sur le host distant")
    p_start.add_argument("--conda-activate", default=None,
                         help="(mode ssh) commande passee a eval pour activer conda. "
                              "Ex: '/home/.../miniforge3/bin/conda shell.bash hook'")
    p_start.add_argument("--conda-env", default=None,
                         help="(mode ssh) nom de l'env conda (ex. nonbenz)")
    p_start.add_argument("--worker-path", default="cluster/worker.py",
                         help="(mode ssh) chemin du worker.py sur le host distant. "
                              "Defaut : 'cluster/worker.py' (relatif a remote-cwd)")
    p_start.add_argument("--remote-log-dir", default="/tmp",
                         help="(mode ssh) dossier des logs sur le host distant")

    # status
    p_status = sub.add_parser("status", help="Snapshot des jobs done/pending")
    p_status.add_argument("--output-root", required=True)
    p_status.add_argument("--manifest", default=None,
                          help="Pour calculer le pourcentage et l'ETA")
    p_status.add_argument("--claims-dir", default=None,
                          help="Pour compter les locks")
    p_status.add_argument("--concurrency", type=int, default=320,
                          help="Concurrence totale (pour ETA, defaut 16x20=320)")

    # stop
    p_stop = sub.add_parser("stop", help="Tue tous les workers connus")
    p_stop.add_argument("--state-dir", default="cluster_state")

    args = parser.parse_args()

    if args.cmd == "start":
        if args.mode == "ssh":
            for required in ("hosts", "remote_cwd"):
                if not getattr(args, required, None):
                    print(f"ERREUR: --{required.replace('_','-')} requis en mode ssh",
                          file=sys.stderr)
                    sys.exit(2)
            start_ssh(args)
        else:
            start_local(args)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "stop":
        cmd_stop(args)


if __name__ == "__main__":
    main()
