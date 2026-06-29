"""Enumeration COMPLETE de h9 config Cstr (structurel, sans table) via Choco.

Contrairement au run ACE (cluster/ops/run_no_table.sh, h3-h8), Choco enumere
chaque graphe h9 sans table en <1s (mesure : 0.8-0.9s/graphe, 600-3000 sols/
graphe), donc l'enumeration COMPLETE des ~2418 graphes h9 est tractable en
~30-40 min, contrairement a ACE qui n'a pas fini un seul graphe en 60s+.

Ecrit dans une DB au MEME schema que final_solutions (reutilise
csp_solver._final_db), donc compatible avec :
  - cluster/ops/plafond_h9_C1.py (plafond 200 sols/molecule, stratifie)
  - python -m csp_solver._run_final dispatch (xTB sur cluster, infra existante)

Usage (sur la frontale, env conda 'nonbenz') :
  python enumerate_h9_choco.py --db ~/projet/h9_choco.db \
      --notes "h9 Cstr via Choco"
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Resout la racine projet via cwd (l'appelant doit faire `cd ~/projet` avant,
# comme run_no_table.sh / run_h9_choco.sh) plutot que via __file__, car ce
# script est deploye independamment de l'arborescence cluster/ops/ locale.
ROOT = Path(os.environ.get("PROJET_ROOT", os.getcwd()))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "csp_solver"))


def _log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--graphs-dir", default=None,
                     help="defaut : experiments/v1/plane/benzdb/h9 (relatif a la racine projet)")
    ap.add_argument("--config-name", default="Cstr",
                     help="nom de config stocke en DB (defaut Cstr, coherent avec "
                          "csp_solver._final_configs / le run ACE h3-h8)")
    ap.add_argument("--notes", default="")
    ap.add_argument("--limit", type=int, default=None,
                     help="ne traiter que les N premiers graphes (debug/dry-run)")
    ap.add_argument("--start-idx", type=int, default=0,
                     help="indice de depart (inclus) dans la liste triee des "
                          ".graph -- pour repartir le travail entre plusieurs "
                          "groupes de machines/DB independantes (sharding par "
                          "plage, pas par modulo, pour permettre des parts "
                          "proportionnelles a la capacite de chaque groupe).")
    ap.add_argument("--end-idx", type=int, default=None,
                     help="indice de fin (exclu). Defaut : fin de la liste.")
    args = ap.parse_args()

    from csp_solver import _final_db as final_db
    from utils.parser import parse as parse_graph
    from utils.preprocessing import preprocess
    from utils.model import build_and_solve

    final_db.init_db(args.db)
    config_dict = {
        "size_h": 9, "config": args.config_name, "solver": "choco",
        "no_table": True, "adj_57": False, "freeze_b2": False,
        "enumerate_all": True, "count_hexagon": False,
    }
    run_id = final_db.create_run(args.db, config_dict, notes=args.notes)
    _log(f"Run cree : run_id={run_id}  db={args.db}")

    gdir = Path(args.graphs_dir) if args.graphs_dir else (ROOT / "experiments/v1/plane/benzdb/h9")
    all_graphs = sorted(gdir.glob("*.graph"))
    end_idx = args.end_idx if args.end_idx is not None else len(all_graphs)
    graphs = all_graphs[args.start_idx:end_idx]
    if args.limit:
        graphs = graphs[: args.limit]
    _log(f"{len(graphs)} graphes h9 a traiter depuis {gdir} "
         f"(shard [{args.start_idx}:{end_idx}] sur {len(all_graphs)} au total)")

    t_start = time.time()
    total_sols = 0
    n_err = 0
    for i, g in enumerate(graphs, 1):
        graph_name = g.stem
        t0 = time.time()
        try:
            graph = parse_graph(str(g))
            prep = preprocess(graph, freeze_b2=False)
            sols = build_and_solve(
                graph, prep, enumerate_all=True,
                adj_57=False, no_table=True, count_hexagon=False,
                solver="choco",
            )
        except Exception as e:
            n_err += 1
            _log(f"  [ERR] {graph_name} : {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        if not sols:
            if i <= 5 or i % 200 == 0:
                _log(f"  [{i}/{len(graphs)}] {graph_name} : 0 sol, {dt:.2f}s")
            continue

        graph_content = g.read_text(encoding="utf-8")
        n_ins = final_db.insert_solutions(
            args.db, run_id, 9, args.config_name,
            graph_name, graph_content, sols,
        )
        total_sols += n_ins
        if i <= 5 or i % 200 == 0 or i == len(graphs):
            elapsed = time.time() - t_start
            eta = elapsed / i * (len(graphs) - i)
            _log(f"  [{i}/{len(graphs)}] {graph_name} : {len(sols)} sols "
                 f"({n_ins} new), {dt:.2f}s | cumul={total_sols} sols, "
                 f"elapsed={elapsed/60:.1f}min eta={eta/60:.1f}min")

    dt_total = time.time() - t_start
    _log(f"=== ENUM DONE : {total_sols} sols inserees, {n_err} erreurs, "
         f"{dt_total/60:.1f} min ===")
    _log(f"Run ID a utiliser pour plafond + dispatch : {run_id}")


if __name__ == "__main__":
    main()
