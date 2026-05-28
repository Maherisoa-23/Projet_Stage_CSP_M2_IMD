"""
Execute UN seul (graph, config) en isolation pour experiments_v2.

MODE DB-ONLY (mai 2026) : a la fin du job, au lieu de copier l'arbre
des resultats (xyz, json...) vers le NFS via shutil.copytree, on
INSERE directement dans un sqlite local au job (worker_dbs/<job_id>.db).
Ce sqlite contient : solutions, molecules, configs, xyz_files (BLOB gzip).
Aucune ecriture de xyz sur le NFS partage.

Le finalize_v2.py merge tous les worker DBs en db_v3.db a la fin du run.

Pipeline :
  1. Cree un scratch local (typ. /tmp = tmpfs)
  2. Copie le .graph
  3. python -m experiments.v2.main file.graph --config NAME
     --validate --output-dir scratch/output [--no-freeze ...]
     -> les xyz sont generes en scratch local UNIQUEMENT
  4. Lit le scratch, ingere TOUT dans worker_dbs/<job_id>.db
     (xyz en BLOB gzip, calcul de planarite a la volee)
  5. Ecrit job_status.json sur NFS (juste 1 petit JSON par job, pour
     que is_done() du worker fonctionne)
  6. Nettoie scratch (TOUT supprime sauf le worker DB)

Usage :
    python -m experiments.v2.run_one_job \\
        --graph plane/benzdb/h7/0-7-8-15-16-23-24.graph \\
        --config sym1_pb2 \\
        --output-root /home/.../output_v2 \\
        --scratch-root /tmp \\
        [--no-freeze] [--no-table] [--adj-57] \\
        [--timeout 1800]

Le `--config NAME` doit etre l'un des presets de experiments_v2/configs.py.
Les flags --no-freeze/--no-table/--adj-57 sont compatibles si voulu.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Ajout au path :
#   - cluster/ (racine) pour atomic_io
#   - racine projet pour pouvoir importer experiments.v2.* en
#     absolu (ce script est typiquement lance comme script direct par le
#     worker via `python /path/to/run_one_job.py`, donc __package__ = None
#     et les imports relatifs `from .db_helpers ...` plantent).
_HERE = Path(__file__).resolve().parent              # experiments/v2/
_PROJECT_ROOT = _HERE.parent.parent                  # racine projet
_CSP_ROOT = _PROJECT_ROOT / "csp_solver"
sys.path.insert(0, str(_PROJECT_ROOT / "cluster"))
sys.path.insert(0, str(_PROJECT_ROOT))
from atomic_io import write_atomic_json  # noqa: E402

# Sentinel : prefixe LOGIQUE des sol_dir stockes en DB. On utilise une
# arborescence "experiments/v2/_runs/output/<h>/<config>/<mol>/solutions"
# pour rester coherent avec ce que le viewer attend.
LOGICAL_OUTPUT_ROOT = "experiments/v2/_runs/output"

# Single-thread pour BLAS/MKL/OMP (idem run_one_job existant)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("PYTHONHASHSEED", "0")


SCRATCH_PREFIX = "coala_v2_"

# Flags CSP additionnels (au-dela du preset v2) que le user peut passer
EXTRA_CSP_FLAGS = {"no-freeze", "no-table", "adj-57"}


def make_job_id(graph_path: Path, config_name: str) -> str:
    h_name = graph_path.parent.name
    mol_name = graph_path.stem
    ts = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    return f"{h_name}_{config_name}_{mol_name}_{os.getpid()}_{ts}"


def count_results(mol_dir: Path):
    sol_root = mol_dir / "solutions"
    if not sol_root.is_dir():
        return 0, 0
    sol_dirs = [d for d in sol_root.iterdir()
                if d.is_dir() and d.name.startswith("sol_")]
    n_md = sum(1 for d in sol_dirs
               if (d / "md_validation" / "md_final_opt.xyz").exists())
    return len(sol_dirs), n_md


def run_subprocess(cmd, timeout, log_prefix="", cwd=None, env=None):
    print(f"{log_prefix}$ {' '.join(str(c) for c in cmd)}", flush=True)
    t0 = time.time()
    result = subprocess.run(cmd, timeout=timeout,
                             cwd=str(cwd) if cwd else None,
                             env=env,
                             encoding="utf-8", errors="replace")
    return result.returncode, round(time.time() - t0, 1)


def run_one_job_v2(graph_path: Path, config_name: str,
                    output_root: Path, scratch_root: Path,
                    extra_flags=None,
                    timeout_sec: int = 1800,
                    cleanup: bool = True) -> dict:
    """Pipeline experiments_v2 sur 1 (graph, config v2)."""
    graph_path = Path(graph_path).resolve()
    output_root = Path(output_root).resolve()
    scratch_root = Path(scratch_root).resolve()
    extra_flags = list(extra_flags or [])

    if not graph_path.is_file():
        raise FileNotFoundError(f"Graph introuvable : {graph_path}")

    h_name = graph_path.parent.name
    mol_name = graph_path.stem
    job_id = make_job_id(graph_path, config_name)

    scratch = scratch_root / f"{SCRATCH_PREFIX}{job_id}"
    scratch.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    status = {
        "job_id": job_id,
        "graph": str(graph_path),
        "config": config_name,
        "h": h_name,
        "mol": mol_name,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "scratch": str(scratch),
        "extra_flags": extra_flags,
    }

    # On garde le job_status.json sur NFS (1 petit fichier JSON par job)
    # pour que is_done() du worker fonctionne sans avoir a lire la mini DB.
    final_status_dir = output_root / h_name / config_name / mol_name
    # Le mini DB du job, sur NFS aussi (~quelques centaines de Ko gzip)
    worker_db_dir = output_root / "worker_dbs"
    worker_db_dir.mkdir(parents=True, exist_ok=True)
    worker_db_path = worker_db_dir / f"{h_name}__{config_name}__{mol_name}.db"

    print(f"=== Job v2 {job_id} ===", flush=True)
    print(f"  graph    : {graph_path}", flush=True)
    print(f"  config   : {config_name} extra={extra_flags}", flush=True)
    print(f"  scratch  : {scratch}", flush=True)
    print(f"  status   : {final_status_dir}/job_status.json", flush=True)
    print(f"  worker_db: {worker_db_path}", flush=True)

    try:
        graph_local = scratch / graph_path.name
        shutil.copy2(graph_path, graph_local)

        local_mol_dir = scratch / "output" / h_name / config_name / mol_name
        local_mol_dir.mkdir(parents=True, exist_ok=True)
        sol_dir = local_mol_dir / "solutions"
        sol_dir.mkdir(parents=True, exist_ok=True)

        # Run experiments_v2.main avec --validate
        #
        # IMPORTANT : cwd DOIT etre le scratch (et NON la racine projet)
        # car pycsp3 ecrit model.xml dans cwd. Si plusieurs workers
        # tournent dans le meme cwd, ils ecrasent mutuellement model.xml
        # -> FileNotFoundError aleatoire / corrompu.
        #
        # Pour que `python -m experiments.v2.main` trouve le
        # package, on passe PYTHONPATH=_PROJECT_ROOT dans l'env du
        # sous-process (alternative a cwd=projet_root, qui causait la
        # collision sur model.xml en parallele).
        # Refactor option C (mai 2026) : main.py de v2 est supprime ;
        # csp_solver.main couvre tous les presets via --preset NAME.
        cmd = [
            sys.executable, "-m",
            "csp_solver.main",
            str(graph_local),
            "--preset", config_name,
            "--all",
            "--validate",
            "--output-dir", str(sol_dir),
        ] + [f"--{flag}" for flag in extra_flags]

        env = os.environ.copy()
        existing_pp = env.get("PYTHONPATH", "")
        new_pp = str(_PROJECT_ROOT)
        env["PYTHONPATH"] = (new_pp + os.pathsep + existing_pp) if existing_pp else new_pp
        rc_main, dur_main = run_subprocess(
            cmd, timeout=timeout_sec, log_prefix="  [main_v2] ",
            cwd=scratch, env=env,
        )
        status["main_returncode"] = rc_main
        status["main_duration_sec"] = dur_main

        if rc_main != 0:
            status["status"] = "failed"
            status["error"] = f"main_v2 exit code {rc_main}"
            return _finalize(status, t_start, output_root, h_name,
                              config_name, mol_name)

        n_sols, n_md = count_results(local_mol_dir)
        status["n_solutions"] = n_sols
        status["n_md_outputs"] = n_md

        # ===== Ingestion DB-only (au lieu du copytree NFS) =====
        # Chemin LOGIQUE des sol_dir : aligne sur ce que le viewer attend
        sol_dir_prefix = (f"{LOGICAL_OUTPUT_ROOT}/{h_name}/{config_name}/"
                          f"{mol_name}/solutions")
        # Import ABSOLU (relative import echoue si script lance directement
        # via `python /path/to/run_one_job.py`, ce que fait le worker).
        from experiments.v2.db_helpers import (
            init_worker_db, ingest_mol_dir
        )
        t_ingest = time.time()
        # Si une DB precedente existe (re-run), on l'ecrase pour repartir
        # propre (sinon les anciennes solutions trainent).
        if worker_db_path.exists():
            worker_db_path.unlink()
        conn = init_worker_db(worker_db_path)
        try:
            stats = ingest_mol_dir(
                conn, local_mol_dir, h_name, config_name, mol_name,
                sol_dir_prefix=sol_dir_prefix,
                job_status="ok",
                job_duration_sec=round(time.time() - t_start, 1),
                n_solutions_csp=n_sols,
            )
        finally:
            conn.close()
        status["ingest_duration_sec"] = round(time.time() - t_ingest, 1)
        status["worker_db"] = str(worker_db_path)
        status.update(stats)

        status["status"] = "ok"
        return _finalize(status, t_start, output_root, h_name,
                          config_name, mol_name, final_status_dir)

    except subprocess.TimeoutExpired as e:
        status["status"] = "timeout"
        status["error"] = f"Timeout apres {e.timeout}s"
        return _finalize(status, t_start, output_root, h_name,
                          config_name, mol_name)
    except Exception as e:
        status["status"] = "failed"
        status["error"] = f"{type(e).__name__}: {e}"
        return _finalize(status, t_start, output_root, h_name,
                          config_name, mol_name)
    finally:
        if cleanup:
            shutil.rmtree(scratch, ignore_errors=True)


def _finalize(status, t_start, output_root, h_name, config_name, mol_name,
              status_dir=None):
    """Ecrit job_status.json (1 petit fichier sur NFS).

    En mode DB-only, c'est le SEUL fichier que ce job ecrit sur NFS (en
    plus de son worker_dbs/<job_id>.db). Tout le reste (xyz, json...)
    est encapsule dans le sqlite ou dans le scratch local detruit.
    """
    status["duration_sec"] = round(time.time() - t_start, 1)
    status["ended_at"] = datetime.now().isoformat(timespec="seconds")
    if status_dir is None:
        status_dir = output_root / h_name / config_name / mol_name
    status_dir.mkdir(parents=True, exist_ok=True)
    try:
        write_atomic_json(status_dir / "job_status.json", status)
    except OSError as e:
        print(f"  WARN : ecriture status echouee : {e}", flush=True)
    print(f"=== Fin {status['status'].upper()} ({status['duration_sec']}s) ===",
          flush=True)
    if status["status"] == "ok":
        print(f"  {status.get('n_solutions','?')} solutions, "
              f"{status.get('n_md_outputs','?')} avec MD", flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--config", required=True,
                        help="Nom d'une config v2 (cf experiments_v2/configs.py)")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--no-freeze", action="store_true",
                        help="Combinable avec preset v2 : ajoute --no-freeze a main_v2")
    parser.add_argument("--no-table", action="store_true")
    parser.add_argument("--adj-57", action="store_true")
    args = parser.parse_args()

    scratch_root = Path(args.scratch_root) if args.scratch_root \
                    else Path(tempfile.gettempdir())

    extra = []
    if args.no_freeze: extra.append("no-freeze")
    if args.no_table: extra.append("no-table")
    if args.adj_57: extra.append("adj-57")

    try:
        status = run_one_job_v2(
            graph_path=Path(args.graph),
            config_name=args.config,
            output_root=Path(args.output_root),
            scratch_root=scratch_root,
            extra_flags=extra,
            timeout_sec=args.timeout,
            cleanup=not args.no_cleanup,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"ERREUR: {e}", file=sys.stderr, flush=True)
        sys.exit(2)
    sys.exit(0 if status["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
