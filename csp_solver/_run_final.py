"""Point d'entree du run final h3-h9 x 3 configs.

3 commandes :
  setup    : init DB + enumere CSP + insert sols pending (1 fois par run)
  dispatch : lance le dispatcher (boucle worker)
  status   : affiche les stats du run

Workflow typique :
  python -m csp_solver._run_final setup --db ~/final.db --sizes 3,4,5,6,7,8,9
  python -m csp_solver._run_final dispatch --db ~/final.db --run-id 1
  # En parallele depuis un autre shell :
  python -m csp_solver._run_final status --db ~/final.db

Recommande sur cluster :
  nohup python -m csp_solver._run_final setup ... > setup.log 2>&1 &
  nohup python -m csp_solver._run_final dispatch ... > dispatcher.log 2>&1 &
"""

import argparse
import json
import sys
import time
from pathlib import Path


def _ensure_imports():
    here = Path(__file__).resolve().parent
    parent = here.parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))


_ensure_imports()


def _log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# === Commande setup ===

def cmd_setup(args):
    from csp_solver import _final_db, _final_configs, _enumerate

    sizes = [int(s) for s in args.sizes.split(",")] if args.sizes else [3, 4, 5, 6, 7, 8, 9]
    configs = args.configs.split(",") if args.configs else ["C1", "C2", "C3"]

    # Verifier les configs
    for c in configs:
        _final_configs.get_config(c)  # leve si invalide

    _final_db.init_db(args.db)
    _log(f"DB initialised : {args.db}")

    # Soit on cree un nouveau run, soit on reprend le run-id specifie
    if args.run_id:
        run_info = _final_db.get_run_info(args.db, args.run_id)
        if run_info is None:
            _log(f"ERROR: run-id {args.run_id} introuvable, abort")
            sys.exit(1)
        run_id = int(args.run_id)
        _log(f"Reprise run_id={run_id} (created_at={run_info['started_at']})")
    else:
        config_dict = {
            "sizes": sizes,
            "configs": configs,
            "seed_md": _final_configs.SEED_MD,
            "config_definitions": {c: _final_configs.get_config(c) for c in configs},
        }
        run_id = _final_db.create_run(args.db, config_dict, notes=args.notes or "")
        _log(f"Nouveau run cree : run_id={run_id}")

    project_root = args.project_root or str(Path(__file__).resolve().parent.parent)
    _log(f"project_root = {project_root}")

    total_inserted = 0
    for size_h in sizes:
        graphs = _final_configs.list_graphs(project_root, size_h)
        _log(f"h{size_h} : {len(graphs)} .graph trouves")
        if not graphs:
            _log(f"h{size_h} : SKIP (aucun graph)")
            continue
        for config_name in configs:
            config = _final_configs.get_config(config_name)
            _log(f"  --- {config_name} ({config['label']}) ---")
            for g_path in graphs:
                graph_name = Path(g_path).stem
                t0 = time.perf_counter()
                try:
                    sols = _enumerate.enumerate_solutions(g_path, config)
                    graph_content = _enumerate.read_graph_content(g_path)
                except Exception as e:
                    _log(f"    [ERR] {graph_name} : {e}")
                    continue
                dt = time.perf_counter() - t0
                if not sols:
                    _log(f"    {graph_name} : 0 sol (skip), {dt:.2f}s")
                    continue
                n_ins = _final_db.insert_solutions(
                    args.db, run_id, size_h, config_name,
                    graph_name, graph_content, sols,
                )
                total_inserted += n_ins
                _log(f"    {graph_name} : {len(sols)} sols ({n_ins} new), {dt:.2f}s")

    _log(f"=== SETUP DONE : {total_inserted} new sols inserted ===")
    _log(f"Run ID a utiliser pour dispatch : {run_id}")


# === Commande dispatch ===

def cmd_dispatch(args):
    from csp_solver import _dispatcher

    workers = [f"192.168.200.{s.strip()}" for s in args.workers.split(",") if s.strip()]
    _log(f"Workers: {workers}")

    _dispatcher.run_dispatcher(
        db_path=args.db,
        run_id=args.run_id,
        workers=workers,
        batch_size=args.batch_size,
        max_parallel_xtb=args.max_parallel_xtb,
        timeout_xtb=args.timeout_xtb,
        ssh_timeout_s=args.ssh_timeout,
        heartbeat_s=args.heartbeat,
    )


# === Commande status ===

def cmd_status(args):
    from csp_solver import _final_db

    run_info = _final_db.get_run_info(args.db, args.run_id)
    if run_info is None:
        _log("Aucun run trouve")
        return
    run_id = run_info["run_id"]
    _log(f"--- run_id={run_id} state={run_info['state']} ---")
    _log(f"started_at  = {run_info['started_at']}")
    _log(f"finished_at = {run_info['finished_at']}")
    _log(f"heartbeat   = {run_info['last_heartbeat']}")

    stats = _final_db.get_stats(args.db, run_id)
    _log(f"\nby_status: {stats['by_status']}")
    _log(f"\nby (size, config) :")
    for (h, c), d in sorted(stats["by_size_config"].items()):
        total = sum(d.values())
        done = d.get("done", 0)
        pending = d.get("pending", 0)
        running = d.get("running", 0)
        failed = d.get("failed", 0)
        pct = (100.0 * done / total) if total > 0 else 0.0
        _log(f"  h{h} {c} : {done:6}/{total:6} done ({pct:5.1f}%)  "
             f"pending={pending} running={running} failed={failed}")


# === CLI ===

def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)

    # setup
    p1 = sp.add_parser("setup", help="Init DB + enumere CSP + insert sols")
    p1.add_argument("--db", required=True)
    p1.add_argument("--sizes", default="3,4,5,6,7,8,9",
                    help="Tailles separees par , (defaut 3,4,5,6,7,8,9)")
    p1.add_argument("--configs", default="C1,C2,C3")
    p1.add_argument("--run-id", type=int, default=None,
                    help="Reprendre un run existant au lieu d'en creer un nouveau")
    p1.add_argument("--notes", default=None)
    p1.add_argument("--project-root", default=None,
                    help="Racine du projet (par defaut parent de csp_solver/)")
    p1.set_defaults(func=cmd_setup)

    # dispatch
    p2 = sp.add_parser("dispatch", help="Lance le dispatcher (boucle workers)")
    p2.add_argument("--db", required=True)
    p2.add_argument("--run-id", type=int, required=True)
    p2.add_argument("--workers",
                    default="49,50,51,52,53,54,55,56,57,58,59,60,61,62,63,64")
    p2.add_argument("--batch-size", type=int, default=40)
    p2.add_argument("--max-parallel-xtb", type=int, default=40)
    p2.add_argument("--timeout-xtb", type=int, default=50000)
    p2.add_argument("--ssh-timeout", type=int, default=18000)
    p2.add_argument("--heartbeat", type=int, default=60)
    p2.set_defaults(func=cmd_dispatch)

    # status
    p3 = sp.add_parser("status", help="Affiche les stats du run")
    p3.add_argument("--db", required=True)
    p3.add_argument("--run-id", type=int, default=None,
                    help="Si absent, prend le dernier run")
    p3.set_defaults(func=cmd_status)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
