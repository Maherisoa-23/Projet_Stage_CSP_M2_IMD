"""Execute UN seul (graph, config) en isolation pour experiments_v3.

MODE DB-ONLY (idem v2) : a la fin du job, on insere TOUT dans
worker_dbs/<job_id>.db. Aucun xyz n'est ecrit sur le NFS.

Pipeline v3 (vs v2) :
  1. CSP enrichi avec Gauss-Bonnet (csp_model_v3)
  2. Pour chaque solution : MMFF 3-tier
       sure_plan       -> accept, skip xTB
       sure_non_plan   -> reject, skip xTB
       gray | failed   -> xTB MD + opt comme v2
  3. ingest_mol_dir_v3 : decision_path et mmff_angle stockes en DB

Usage :
    python -m experiments.v3.run_one_job \\
        --graph plane/benzdb/h7/0-7-8-15-16-23-24.graph \\
        --config sym1_pb2_curv1 \\
        --output-root /home/.../output_v3 \\
        --scratch-root /tmp \\
        [--no-freeze] [--no-table] [--adj-57] \\
        [--th-sure-plan 5] [--th-sure-non-plan 25] \\
        [--timeout 1800]
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

_HERE = Path(__file__).resolve().parent          # experiments/v3/
_PROJECT_ROOT = _HERE.parent.parent              # racine projet
_CSP_ROOT = _PROJECT_ROOT / "csp_solver"
sys.path.insert(0, str(_PROJECT_ROOT / "cluster"))
sys.path.insert(0, str(_PROJECT_ROOT))
from atomic_io import write_atomic_json  # noqa: E402

LOGICAL_OUTPUT_ROOT = "experiments/v3/_runs/output"

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("PYTHONHASHSEED", "0")


SCRATCH_PREFIX = "coala_v3_"

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
    n_md_or_mmff = 0
    for d in sol_dirs:
        if (d / "md_validation" / "md_final_opt.xyz").exists():
            n_md_or_mmff += 1
        elif (d / "mmff_validation" / "mmff_opt.xyz").exists():
            n_md_or_mmff += 1
    return len(sol_dirs), n_md_or_mmff


def run_subprocess(cmd, timeout, log_prefix="", cwd=None, env=None):
    print(f"{log_prefix}$ {' '.join(str(c) for c in cmd)}", flush=True)
    t0 = time.time()
    result = subprocess.run(cmd, timeout=timeout,
                             cwd=str(cwd) if cwd else None,
                             env=env,
                             encoding="utf-8", errors="replace")
    return result.returncode, round(time.time() - t0, 1)


def run_one_job_v3(graph_path: Path, config_name: str,
                    output_root: Path, scratch_root: Path,
                    extra_flags=None,
                    th_sure_plan: float = 5.0,
                    th_sure_non_plan: float = 25.0,
                    timeout_sec: int = 1800,
                    cleanup: bool = True) -> dict:
    """Pipeline experiments_v3 sur 1 (graph, config v3)."""
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
        "th_sure_plan": th_sure_plan,
        "th_sure_non_plan": th_sure_non_plan,
    }

    final_status_dir = output_root / h_name / config_name / mol_name
    worker_db_dir = output_root / "worker_dbs"
    worker_db_dir.mkdir(parents=True, exist_ok=True)
    worker_db_path = worker_db_dir / f"{h_name}__{config_name}__{mol_name}.db"

    print(f"=== Job v3 {job_id} ===", flush=True)
    print(f"  graph    : {graph_path}", flush=True)
    print(f"  config   : {config_name} extra={extra_flags}", flush=True)
    print(f"  th_sp={th_sure_plan}  th_snp={th_sure_non_plan}", flush=True)
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

        # Run experiments_v3.main avec --validate
        # cwd = scratch (NON la racine projet) car pycsp3 ecrit model_v3.xml
        # dans cwd, risque de collision si 2 workers partagent cwd.
        cmd = [
            sys.executable, "-m",
            "csp_solver.main",
            str(graph_local),
            "--preset", config_name,
            "--all",
            "--validate",
            "--output-dir", str(sol_dir),
            # Note refactor option C : la chaine v3 (MMFF 3-tier) n'est plus
            # appelee par defaut ; les seuils --th-sure-plan/--th-sure-non-plan
            # restent acceptes en CLI mais ignores par csp_solver.main.
            # Le pipeline complet v3 reste accessible via experiments/v3/v3_pipeline.py
            # pour qui veut le reproduire (cf rapport_exp_v3.tex).
        ] + [f"--{flag}" for flag in extra_flags]

        env = os.environ.copy()
        existing_pp = env.get("PYTHONPATH", "")
        new_pp = str(_PROJECT_ROOT)
        env["PYTHONPATH"] = (new_pp + os.pathsep + existing_pp) if existing_pp else new_pp
        rc_main, dur_main = run_subprocess(
            cmd, timeout=timeout_sec, log_prefix="  [main_v3] ",
            cwd=scratch, env=env,
        )
        status["main_returncode"] = rc_main
        status["main_duration_sec"] = dur_main

        if rc_main != 0:
            status["status"] = "failed"
            status["error"] = f"main_v3 exit code {rc_main}"
            return _finalize(status, t_start, output_root, h_name,
                              config_name, mol_name)

        n_sols, n_md = count_results(local_mol_dir)
        status["n_solutions"] = n_sols
        status["n_md_or_mmff_outputs"] = n_md

        # Ingestion DB-only
        sol_dir_prefix = (f"{LOGICAL_OUTPUT_ROOT}/{h_name}/{config_name}/"
                          f"{mol_name}/solutions")
        from experiments.v3.db_helpers import (
            init_worker_db, ingest_mol_dir_v3
        )
        t_ingest = time.time()
        if worker_db_path.exists():
            worker_db_path.unlink()
        conn = init_worker_db(worker_db_path)
        try:
            stats = ingest_mol_dir_v3(
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
        print(f"  {status.get('n_solutions','?')} sols, "
              f"{status.get('n_md_or_mmff_outputs','?')} valides "
              f"(sp={status.get('n_mmff_sure_plan','?')}, "
              f"snp={status.get('n_mmff_sure_non_plan','?')}, "
              f"gray={status.get('n_mmff_gray','?')})", flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--config", required=True,
                        help="Nom d'une config v3 (cf experiments_v3/configs.py)")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--scratch-root", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--no-freeze", action="store_true")
    parser.add_argument("--no-table", action="store_true")
    parser.add_argument("--adj-57", action="store_true")
    parser.add_argument("--th-sure-plan", type=float, default=5.0)
    parser.add_argument("--th-sure-non-plan", type=float, default=25.0)
    args = parser.parse_args()

    scratch_root = Path(args.scratch_root) if args.scratch_root \
                    else Path(tempfile.gettempdir())

    extra = []
    if args.no_freeze: extra.append("no-freeze")
    if args.no_table: extra.append("no-table")
    if args.adj_57: extra.append("adj-57")

    try:
        status = run_one_job_v3(
            graph_path=Path(args.graph),
            config_name=args.config,
            output_root=Path(args.output_root),
            scratch_root=scratch_root,
            extra_flags=extra,
            th_sure_plan=args.th_sure_plan,
            th_sure_non_plan=args.th_sure_non_plan,
            timeout_sec=args.timeout,
            cleanup=not args.no_cleanup,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"ERREUR: {e}", file=sys.stderr, flush=True)
        sys.exit(2)
    sys.exit(0 if status["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
