"""
Genere un manifest JSONL pour experiments_v2 : (graph, config_v2) pairs.

Reprend la structure du build_manifest existant
(csp_solver/experiments/cluster/build_manifest.py) mais utilise les 5
configs preset de experiments_v2/configs.py au lieu des 8 combinaisons
CSP existantes.

Le manifest produit est consomme par le worker_v2.py (ou le worker
existant si on l'enrichit avec --run-one-job).

Usage :
    python -m csp_solver.experiments_v2.cluster.build_manifest \\
        <dossier_graphs> \\
        [--configs all|comma,sep,list] \\
        [--extra-flag no-freeze,no-table,...] \\
        [--output FILE]

Exemple :
    # 5 configs v2 sur h7 = 144 graphes x 5 = 720 jobs
    python -m csp_solver.experiments_v2.cluster.build_manifest \\
        plane/benzdb/h7 --configs all
"""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[3]))
    __package__ = "csp_solver.experiments_v2.cluster"

from .. import configs as v2configs  # noqa: E402


def parse_config_list(s):
    if s.lower() == "all":
        return v2configs.all_names()
    names = [n.strip() for n in s.split(",") if n.strip()]
    valid = set(v2configs.all_names())
    bad = [n for n in names if n not in valid]
    if bad:
        raise SystemExit(f"ERREUR : configs invalides : {bad}\n"
                          f"Valides : {sorted(valid)}")
    return names


def build_manifest(graphs_dir: Path, configs: list, output_path: Path,
                    extra_flags: list = None) -> int:
    graphs_dir = Path(graphs_dir).resolve()
    if not graphs_dir.is_dir():
        raise SystemExit(f"ERREUR : dossier graphs introuvable : {graphs_dir}")

    graphs = sorted(graphs_dir.glob("*.graph"))
    if not graphs:
        raise SystemExit(f"ERREUR : aucun .graph dans {graphs_dir}")

    h_name = graphs_dir.name
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    extra_flags = list(extra_flags or [])
    with open(output_path, "w", encoding="utf-8") as f:
        for g in graphs:
            mol = g.stem
            for cfg in configs:
                # job_id integre les extras pour distinguer les variantes
                extra_suffix = "_" + "_".join(extra_flags) if extra_flags else ""
                entry = {
                    "job_id": f"{h_name}_{cfg}{extra_suffix}_{mol}",
                    "graph": str(g),
                    "h": h_name,
                    "config": cfg,
                    "mol": mol,
                    "extra_flags": extra_flags,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                n += 1
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graphs_dir")
    parser.add_argument("--configs", default="all",
                        help="liste de configs v2 (cf experiments_v2/configs.py) "
                             "ou 'all' (defaut)")
    parser.add_argument("--extra-flag", default="",
                        help="flags CSP additionnels (no-freeze,no-table,adj-57). "
                             "Seront passes a TOUTES les configs.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    configs = parse_config_list(args.configs)
    extra = [f.strip() for f in args.extra_flag.split(",") if f.strip()]
    h_name = Path(args.graphs_dir).resolve().name
    output_path = Path(args.output) if args.output \
                    else Path(f"manifest_v2_{h_name}.jsonl")

    print(f"=== build_manifest_v2 ===")
    print(f"  source       : {args.graphs_dir}")
    print(f"  configs (v2) : {len(configs)} ({', '.join(configs)})")
    print(f"  extra_flags  : {extra}")
    print(f"  output       : {output_path}")

    n = build_manifest(Path(args.graphs_dir), configs, output_path, extra)
    print(f"  {n} jobs ecrits dans {output_path}")


if __name__ == "__main__":
    main()
