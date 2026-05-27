"""Valide le filtre Huckel par comparaison avec les verdicts xTB de db_v3.

Strategie :
  1. Pour chaque (h, config), sample N sols (equilibre plan / non_plan)
  2. Reconstruit chaque mol via reconstruction.pipeline.reconstruct_molecule
  3. Calcule le gap HOMO-LUMO Huckel sur le squelette C
  4. Stocke (gap, vrai verdict) pour analyse
  5. Trace la distribution + cherche le seuil optimal
  6. Matrice de confusion au meilleur seuil

Usage :
    venv/Scripts/python.exe -m experiments.v3.validate_huckel \\
        --db csp_solver/experiments/csp_viewer/db_v3.db \\
        --configs pb1 \\
        --n-per-bucket 500
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import time
from pathlib import Path

# Permet l'execution directe
if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[2]))

from csp_solver.utils.parser import parse as parse_graph
from experiments.v3.huckel_filter import huckel_score, build_c_adjacency, huckel_orbitals


DB_DEFAULT = "csp_solver/experiments/csp_viewer/db_v3.db"
GRAPH_DIR_DEFAULT = "csp_solver/experiments/plane/benzdb"


def parse_sizes_string(sizes_str: str) -> list[int]:
    """'5_7_6_6_5_7' -> [5,7,6,6,5,7]"""
    return [int(p) for p in sizes_str.split("_") if p]


def reconstruct_and_huckel(graph, sol: dict) -> dict | None:
    """Reconstruit et calcule Huckel sans passer par fichier xyz."""
    # Late import (suppose csp_solver/ deja dans sys.path)
    _csp_root = Path(__file__).resolve().parent.parent
    if str(_csp_root) not in sys.path:
        sys.path.insert(0, str(_csp_root))
    from reconstruction.pipeline import reconstruct_molecule

    try:
        mol = reconstruct_molecule(graph, sol, None)
    except Exception:
        return None

    # Extraire elements + positions du MolecularGraph (API : .vertices, .element)
    atoms = sorted(mol.vertices.values(), key=lambda v: v.id)
    syms = [a.element for a in atoms]
    import numpy as np
    coords = np.array([[a.x, a.y, a.z] for a in atoms], dtype=float)

    adj = build_c_adjacency(syms, coords)
    if adj is None:
        return None
    Nc = len(adj)
    eigvals = huckel_orbitals(adj)
    n_occ = Nc // 2
    if n_occ <= 0 or n_occ >= Nc:
        return None
    homo = float(eigvals[n_occ - 1])
    lumo = float(eigvals[n_occ])
    return {"Nc": Nc, "homo": homo, "lumo": lumo, "gap": lumo - homo}


def evaluate(db_path: str, graph_dir: str, configs_filter: list[str] | None,
              n_per_bucket: int, seed: int = 42):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rng = random.Random(seed)

    # Buckets : table configs a colonne 'name', pas 'config'
    if configs_filter:
        where = "name IN (" + ",".join("?" * len(configs_filter)) + ")"
        params0 = configs_filter
    else:
        where = "1=1"
        params0 = []
    buckets = list(cur.execute(
        f"SELECT DISTINCT h, name FROM configs WHERE {where} ORDER BY h, name",
        params0
    ))

    # Collect samples
    print(f"[buckets] {len(buckets)} (h, config) combos", flush=True)
    samples = []
    graph_cache: dict[str, object] = {}
    for h, cfg in buckets:
        for verdict in ("plan", "non_plan"):
            rows = list(cur.execute(
                "SELECT mol, sol_idx, sizes, verdict, angle_deg "
                "FROM solutions WHERE h=? AND config=? AND verdict=? "
                "LIMIT ?",
                (h, cfg, verdict, n_per_bucket * 5)
            ))
            if len(rows) > n_per_bucket:
                rng.shuffle(rows)
                rows = rows[:n_per_bucket]
            for r in rows:
                samples.append({
                    "h": h, "config": cfg,
                    "mol": r["mol"], "sol_idx": r["sol_idx"],
                    "sizes": r["sizes"], "verdict": r["verdict"],
                    "xtb_angle": r["angle_deg"],
                })
    print(f"[samples] {len(samples)} sols a evaluer", flush=True)

    # Compute Huckel
    results = []
    t0 = time.perf_counter()
    n_failed = 0
    for i, s in enumerate(samples, 1):
        if s["mol"] not in graph_cache:
            gp = Path(graph_dir) / s["h"] / f"{s['mol']}.graph"
            if not gp.exists():
                n_failed += 1
                continue
            graph_cache[s["mol"]] = parse_graph(str(gp))
        graph = graph_cache[s["mol"]]
        sizes = parse_sizes_string(s["sizes"])
        if len(sizes) != graph.h:
            n_failed += 1
            continue
        sol = {i: sizes[i] for i in range(graph.h)}
        hr = reconstruct_and_huckel(graph, sol)
        if hr is None:
            n_failed += 1
            continue
        results.append({
            **s,
            "Nc": hr["Nc"],
            "gap": hr["gap"],
            "homo": hr["homo"],
            "lumo": hr["lumo"],
        })
        if i % 500 == 0:
            rate = i / (time.perf_counter() - t0)
            print(f"  [{i}/{len(samples)}] @ {rate:.0f}/s", flush=True)

    elapsed = time.perf_counter() - t0
    print(f"[time] {elapsed:.1f}s  n_evaluated={len(results)}  n_failed={n_failed}", flush=True)

    if not results:
        return

    # Analyse : distribution du gap par verdict
    import numpy as np
    gaps_plan = np.array([r["gap"] for r in results if r["verdict"] == "plan"])
    gaps_non = np.array([r["gap"] for r in results if r["verdict"] == "non_plan"])
    print(f"\n=== Distribution du gap HOMO-LUMO ({len(gaps_plan)} plan / {len(gaps_non)} non_plan) ===", flush=True)
    for label, arr in [("PLAN    ", gaps_plan), ("NON_PLAN", gaps_non)]:
        if len(arr) == 0:
            continue
        print(f"  {label} : mean={arr.mean():.3f} median={np.median(arr):.3f} "
               f"min={arr.min():.3f} q25={np.quantile(arr,0.25):.3f} q75={np.quantile(arr,0.75):.3f} max={arr.max():.3f}", flush=True)

    # Recherche du seuil optimal (max accuracy ou max F1)
    all_gaps = np.array([r["gap"] for r in results])
    all_plan = np.array([r["verdict"] == "plan" for r in results])
    thresholds = np.linspace(0.0, max(all_gaps) + 0.1, 200)
    best_acc, best_thr_acc = 0.0, 0.0
    best_f1, best_thr_f1 = 0.0, 0.0
    for thr in thresholds:
        pred_plan = all_gaps >= thr
        tp = int(((pred_plan) & (all_plan)).sum())
        tn = int(((~pred_plan) & (~all_plan)).sum())
        fp = int(((pred_plan) & (~all_plan)).sum())
        fn = int(((~pred_plan) & (all_plan)).sum())
        n = tp + tn + fp + fn
        if n == 0:
            continue
        acc = (tp + tn) / n
        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        if acc > best_acc:
            best_acc = acc
            best_thr_acc = thr
        if f1 > best_f1:
            best_f1 = f1
            best_thr_f1 = thr

    print(f"\n=== Seuil optimal ===", flush=True)
    print(f"  best accuracy = {best_acc*100:.1f}%  at gap >= {best_thr_acc:.3f}", flush=True)
    print(f"  best F1       = {best_f1*100:.1f}%  at gap >= {best_thr_f1:.3f}", flush=True)

    # Matrice confusion au seuil best_acc
    pred_plan = all_gaps >= best_thr_acc
    tp = int(((pred_plan) & (all_plan)).sum())
    tn = int(((~pred_plan) & (~all_plan)).sum())
    fp = int(((pred_plan) & (~all_plan)).sum())
    fn = int(((~pred_plan) & (all_plan)).sum())
    print(f"\n  Matrice confusion @ best_thr={best_thr_acc:.3f} :", flush=True)
    print(f"                pred_plan   pred_non_plan", flush=True)
    print(f"   true_plan      {tp:>6}      {fn:>6}", flush=True)
    print(f"   true_non_pl    {fp:>6}      {tn:>6}", flush=True)

    # Par bucket (h, config)
    print(f"\n=== Precision/Recall par (h, config) au seuil optimal ===", flush=True)
    print(f"  {'h':<3} {'config':<14} {'N':>5} {'TP':>5} {'FN':>5} {'FP':>5} {'TN':>5} {'acc':>6}", flush=True)
    from collections import defaultdict
    bucket_stats = defaultdict(lambda: [0,0,0,0])  # TP, FN, FP, TN
    for r in results:
        key = (r["h"], r["config"])
        is_plan = r["verdict"] == "plan"
        pred = r["gap"] >= best_thr_acc
        if pred and is_plan: bucket_stats[key][0] += 1
        elif not pred and is_plan: bucket_stats[key][1] += 1
        elif pred and not is_plan: bucket_stats[key][2] += 1
        else: bucket_stats[key][3] += 1
    for key in sorted(bucket_stats):
        tp, fn, fp, tn = bucket_stats[key]
        n = tp + fn + fp + tn
        acc = (tp + tn) / max(n, 1) * 100
        h, cfg = key
        print(f"  {h:<3} {cfg:<14} {n:>5} {tp:>5} {fn:>5} {fp:>5} {tn:>5} {acc:>5.1f}%", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--graph-dir", default=GRAPH_DIR_DEFAULT)
    ap.add_argument("--configs", default="pb1",
                     help="comma-separated, eg 'pb1' ou 'pb1,pb2,sym1'")
    ap.add_argument("--n-per-bucket", type=int, default=500,
                     help="sols par (h, config, verdict)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    print(f"[db] {args.db}", flush=True)
    print(f"[configs] {configs}", flush=True)
    print(f"[n_per_bucket] {args.n_per_bucket}", flush=True)
    evaluate(args.db, args.graph_dir, configs, args.n_per_bucket, args.seed)


if __name__ == "__main__":
    main()
