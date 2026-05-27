"""
Dispatcher dedie analysis_v2 : orchestre l'execution SSH parallele
des workers sur les 16 machines du cluster COALA.

Distinct du dispatcher CSP existant (qui gere claims/timeouts/recover
pour des jobs heterogenes longs avec xTB). Ici les jobs sont :
  - homogenes (calcul combinatoire pur sur slice de N sols)
  - rapides (~10-30s par slice de 500 sols)
  - sans timeout (juste continue jusqu'au bout)

Modele : on partitionne les slices entre les machines (round-robin par
hash(slice_id) % n_hosts), et chaque machine lance LOCALEMENT son
worker.py qui traite ses slices en serie.

Avantage : tres simple. Pas de claim system, pas de polling, pas de
recover. Si une machine echoue, on peut relancer le dispatcher avec
juste les slices manquantes (build_manifest --all + filtrage).

Usage :
    python -m experiments.viewer.analysis_v2.cluster.dispatcher \\
        --hosts lis-cluster-coala-49,lis-cluster-coala-50,...  \\
        --remote-db /home/COALA/ramaherisoa/projet/.../db_v2.db \\
        --remote-manifest /home/COALA/ramaherisoa/projet/.../manifest.jsonl \\
        --remote-output-dir /home/COALA/ramaherisoa/projet/.../workers \\
        --remote-cwd /home/COALA/ramaherisoa/projet/csp_solver/experiments \\
        --conda-activate "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook" \\
        --conda-env nonbenz

NB : a lancer DEPUIS UNE MACHINE DU CLUSTER (par ex. saphir2 via tmux),
pas depuis Windows : il faut les cles SSH deja configurees pour les
16 machines (cf DEPLOIEMENT_CLUSTER.md sec 8).
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[5]))
    __package__ = "experiments.viewer.analysis_v2.cluster"


def partition_slices(slice_ids: list[int], hosts: list[str]) -> dict[str, list[int]]:
    """Round-robin : slice_id k -> host k % n_hosts. Distribue
    uniformement la charge.
    """
    n = len(hosts)
    out = {h: [] for h in hosts}
    for sid in slice_ids:
        out[hosts[sid % n]].append(sid)
    return out


def build_remote_command(args, slice_ids: list[int]) -> str:
    """Construit la commande shell a executer sur la machine distante."""
    slice_str = ",".join(str(s) for s in slice_ids)
    worker_cmd = (
        f"cd {args.remote_cwd} && "
        f'eval "$({args.conda_activate})" && '
        f"conda activate {args.conda_env} && "
        f"python -m experiments.viewer.analysis_v2.cluster.worker "
        f"--db {args.remote_db} "
        f"--manifest {args.remote_manifest} "
        f"--slice-ids {slice_str} "
        f"--output-dir {args.remote_output_dir}"
    )
    return worker_cmd


def launch_remote_worker(host: str, command: str, log_path: Path,
                          dry_run: bool = False) -> subprocess.Popen | None:
    """Lance un worker en background sur `host`. Retourne le Popen."""
    # On utilise nohup pour que la connexion SSH puisse se fermer
    # sans tuer le worker. stdout/stderr sont rediriges en local
    # (via SSH) dans log_path.
    full = f"nohup bash -c '{command}'"
    ssh_cmd = [
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
        host, full
    ]
    if dry_run:
        print(f"[dry-run] {host} : {' '.join(ssh_cmd)}")
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_path, "wb")
    p = subprocess.Popen(ssh_cmd, stdout=f, stderr=subprocess.STDOUT)
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", required=True,
                        help="liste de hosts SSH separes par virgules")
    parser.add_argument("--manifest", required=True,
                        help="chemin LOCAL (vu depuis le dispatcher) du manifest")
    parser.add_argument("--remote-db", required=True)
    parser.add_argument("--remote-manifest", required=True)
    parser.add_argument("--remote-output-dir", required=True)
    parser.add_argument("--remote-cwd", required=True)
    parser.add_argument("--conda-activate", required=True,
                        help='ex: "/home/COALA/ramaherisoa/miniforge3/bin/conda shell.bash hook"')
    parser.add_argument("--conda-env", required=True)
    parser.add_argument("--local-logs-dir", default="./_analysis_v2_logs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    if not hosts:
        print("ERR : --hosts vide")
        sys.exit(1)

    # Charge le manifest pour avoir la liste des slices
    slice_ids = []
    with open(args.manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                slice_ids.append(json.loads(line)["slice_id"])

    if not slice_ids:
        print("[dispatcher] manifest vide, rien a faire")
        sys.exit(0)

    # Partition par host
    parts = partition_slices(slice_ids, hosts)
    print(f"[dispatcher] {len(slice_ids)} slices, {len(hosts)} hosts")
    for h in hosts:
        print(f"  {h} : {len(parts[h])} slices")

    # Lance les workers (un par host) en parallele
    logs_dir = Path(args.local_logs_dir)
    procs = {}
    for h in hosts:
        ssids = parts[h]
        if not ssids:
            continue
        cmd = build_remote_command(args, ssids)
        log_path = logs_dir / f"{h}.log"
        p = launch_remote_worker(h, cmd, log_path, dry_run=args.dry_run)
        if p is not None:
            procs[h] = (p, log_path)
            print(f"[dispatcher] -> {h} ({len(ssids)} slices) log={log_path}")

    if args.dry_run:
        print("[dispatcher] dry-run termine")
        return

    # Attente
    print(f"[dispatcher] attente de {len(procs)} workers...")
    t0 = time.monotonic()
    n_done = 0
    n_failed = 0
    for h, (p, log_path) in procs.items():
        rc = p.wait()
        n_done += 1
        if rc != 0:
            n_failed += 1
            print(f"  [{h}] ECHEC (rc={rc}, voir {log_path})")
        else:
            print(f"  [{h}] OK ({n_done}/{len(procs)})")

    elapsed = time.monotonic() - t0
    print(f"[dispatcher] DONE en {elapsed:.1f}s : "
          f"{len(procs) - n_failed}/{len(procs)} workers OK")
    sys.exit(0 if n_failed == 0 else 1)


if __name__ == "__main__":
    main()
