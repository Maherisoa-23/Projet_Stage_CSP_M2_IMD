"""
Genere un manifest JSONL listant tous les jobs (graph, config) a executer.

Le manifest est consomme par les workers : chaque ligne = 1 job atomique
(au sens de run_one_job.py).

Format JSONL (1 ligne JSON par job) :
    {"job_id": "h6_default_0-5-6-11-12",
     "graph": "/abs/path/.../h6/0-5-6-11-12.graph",
     "h": "h6", "config": "default", "mol": "0-5-6-11-12"}

Le job_id est STABLE entre executions (ne contient ni PID ni timestamp).
Cela permet aux workers de partager les claims/<job_id>.lock sur NFS.

Usage :
    python build_manifest.py <dossier_graphs> [--configs LIST] [--output FILE]

Exemples :
    # 8 configs sur h6 (defaut) -> 44 graphes x 8 configs = 352 jobs
    python build_manifest.py plane/benzdb/h6

    # 2 configs seulement -> 88 jobs
    python build_manifest.py plane/benzdb/h6 --configs default,no-freeze

    # Output explicite
    python build_manifest.py plane/benzdb/h9 --output /home/.../manifest_h9.jsonl
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

# Doit rester synchronise avec CSP_FLAGS de batch_main.py et VALID_CSP_FLAGS
# de run_one_job.py.
CSP_FLAGS = ["adj-57", "no-freeze", "no-table"]


def all_config_names():
    """Genere les 8 noms de config canoniques (alphabetiques pour les multi-flags).

    Retourne ['default', 'adj-57', 'no-freeze', 'no-table',
              'adj-57_no-freeze', 'adj-57_no-table', 'no-freeze_no-table',
              'adj-57_no-freeze_no-table'].
    Compatible avec config_name() de batch_main.py (CSP_FLAGS trie alphabetiquement).
    """
    sorted_flags = sorted(CSP_FLAGS)
    names = ["default"]
    for r in range(1, len(sorted_flags) + 1):
        for combo in combinations(sorted_flags, r):
            names.append("_".join(combo))
    return names


def parse_config_list(s):
    """Parse une liste de configs sous forme 'a,b,c' ou 'all'."""
    if s.lower() == "all":
        return all_config_names()
    names = [n.strip() for n in s.split(",") if n.strip()]
    valid = set(all_config_names())
    bad = [n for n in names if n not in valid]
    if bad:
        raise SystemExit(
            f"ERREUR: configs invalides : {bad}\n"
            f"Valides : {sorted(valid)}"
        )
    return names


def build_manifest(graphs_dir, configs, output_path):
    """Ecrit le manifest JSONL.

    Args:
        graphs_dir   : dossier contenant les *.graph (ex. plane/benzdb/h6)
        configs      : liste de noms de config (ex. ['default', 'no-freeze'])
        output_path  : fichier de sortie

    Returns:
        nombre de jobs ecrits
    """
    graphs_dir = Path(graphs_dir).resolve()
    if not graphs_dir.is_dir():
        raise SystemExit(f"ERREUR: dossier graphs introuvable : {graphs_dir}")

    graphs = sorted(graphs_dir.glob("*.graph"))
    if not graphs:
        raise SystemExit(f"ERREUR: aucun .graph dans {graphs_dir}")

    h_name = graphs_dir.name   # ex. "h6"
    n_jobs = 0
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for graph in graphs:
            mol = graph.stem
            for cfg in configs:
                entry = {
                    "job_id": f"{h_name}_{cfg}_{mol}",
                    "graph": str(graph),
                    "h": h_name,
                    "config": cfg,
                    "mol": mol,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                n_jobs += 1

    return n_jobs


def main():
    parser = argparse.ArgumentParser(
        description="Genere un manifest JSONL des jobs a executer sur cluster.",
    )
    parser.add_argument("graphs_dir",
                        help="Dossier contenant les *.graph (ex. plane/benzdb/h6)")
    parser.add_argument("--configs", default="all",
                        help="Liste de configs separees par virgule (ex. "
                             "'default,no-freeze') ou 'all' pour les 8. Defaut : all")
    parser.add_argument("--output", default=None,
                        help="Fichier de sortie. Defaut : manifest_<hX>.jsonl "
                             "dans le repertoire courant")
    args = parser.parse_args()

    configs = parse_config_list(args.configs)
    h_name = Path(args.graphs_dir).resolve().name
    output_path = Path(args.output) if args.output else Path(f"manifest_{h_name}.jsonl")

    print(f"=== build_manifest ===")
    print(f"  source  : {args.graphs_dir}")
    print(f"  configs : {len(configs)} ({', '.join(configs)})")
    print(f"  output  : {output_path}")

    n = build_manifest(args.graphs_dir, configs, output_path)
    print(f"  {n} jobs ecrits dans {output_path}")


if __name__ == "__main__":
    main()
