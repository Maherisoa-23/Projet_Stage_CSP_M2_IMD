"""Validation POST-HOC de la contrainte Gauss-Bonnet locale.

Pour chaque solution stockee dans db_v2.db, on calcule
   max_local_curvature(graph, labeling, radius=R)
ce qui dit "ce candidat aurait-il ete rejete par la contrainte tau ?".

Tabulation : matrice (max_local_curvature, verdict) -> on voit si la
contrainte est un bon predicteur.

Usage :
    venv/Scripts/python.exe -m csp_solver.experiments_v3.validate_curvature \\
        --h h7 --n 500 --radius 2

Sortie : pour chaque valeur de max_local_curv (0,1,2,...), montre :
   - nb total de mols
   - % plan (vs xTB)
   -> on cherche le seuil tau qui maximise %plan_kept

Et : si on impose tau=K, combien de mols restent ? combien % sont plan ?
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from collections import defaultdict

# Permet l'execution directe (python -m) ou comme script
if __name__ == "__main__" and __package__ is None:
    _here = Path(__file__).resolve()
    sys.path.insert(0, str(_here.parents[2]))

from csp_solver.utils.parser import parse as parse_graph
from csp_solver.experiments_v3.curvature_helper import (
    curvature_summary, max_local_curvature, all_k_neighborhoods,
    local_curvature_at, vertex_curvature,
)


DB_DEFAULT = "csp_solver/experiments/csp_viewer/db_v2.db"
GRAPH_DIR_DEFAULT = "csp_solver/experiments/plane/benzdb"


def parse_sol_dirname(name: str) -> tuple[int | None, list[int] | None]:
    """sol_42_5_7_6_6_5_6 -> (42, [5,7,6,6,5,6])."""
    parts = name.split("_")
    if len(parts) < 2 or parts[0] != "sol":
        return None, None
    try:
        idx = int(parts[1])
    except ValueError:
        return None, None
    sizes = []
    for p in parts[2:]:
        try:
            sizes.append(int(p))
        except ValueError:
            return idx, None
    return idx, sizes


def fetch_solutions(db_path: str, h_filter: str, n_per_class: int,
                     seed: int = 42) -> list[dict]:
    """Recupere N plan + N non_plan, melange."""
    import random
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rng = random.Random(seed)

    out = []
    pool_size = max(n_per_class * 5, 100)
    for verdict in ("plan", "non_plan"):
        rows = list(cur.execute(
            "SELECT h, mol, sol_dir, verdict, angle_deg "
            "FROM solutions WHERE verdict=? AND h=? LIMIT ?",
            (verdict, h_filter, pool_size)
        ))
        if len(rows) > n_per_class:
            rng.shuffle(rows)
            rows = rows[:n_per_class]
        out.extend(dict(r) for r in rows)
    rng.shuffle(out)
    return out


def evaluate(db_path: str, graph_dir: str, h_filter: str,
              n_per_class: int, radii: tuple[int, ...] = (1, 2, 3),
              seed: int = 42, verbose: bool = False) -> None:

    samples = fetch_solutions(db_path, h_filter, n_per_class, seed)
    print(f"[sample] {len(samples)} mols ({h_filter})", flush=True)

    # Cache graph parsing par mol
    graph_cache: dict[str, object] = {}
    rows_data = []  # liste de dicts {sol_dir, verdict, n_pent, n_hept, max_r1, max_r2, max_r3}
    n_skipped = 0

    t0 = time.perf_counter()
    for s in samples:
        mol = s["mol"]
        sd = Path(s["sol_dir"]).name  # 'sol_1_5_7_7_5_5_7'
        idx, sizes = parse_sol_dirname(sd)
        if sizes is None:
            n_skipped += 1
            continue

        # Charge le graphe
        if mol not in graph_cache:
            gpath = Path(graph_dir) / h_filter / f"{mol}.graph"
            if not gpath.exists():
                n_skipped += 1
                continue
            graph_cache[mol] = parse_graph(str(gpath))
        graph = graph_cache[mol]

        if len(sizes) != graph.h:
            n_skipped += 1
            continue
        labeling = {i: sizes[i] for i in range(graph.h)}
        summ = curvature_summary(graph, labeling, radii=radii)
        rows_data.append({
            "verdict": s["verdict"],
            "angle_deg": s["angle_deg"],
            **summ,
        })

    elapsed = time.perf_counter() - t0
    print(f"[time] {elapsed:.1f} s  | mols traitees: {len(rows_data)}  skipped: {n_skipped}", flush=True)
    if not rows_data:
        print("Aucune mol n'a pu etre evaluee. Verifier --graph-dir.", flush=True)
        return

    # ---------------- Analyse par max_local_r ----------------

    for r in radii:
        key = f"max_local_r{r}"
        print(f"\n=== Distribution de {key} ===", flush=True)
        # buckets
        bucket = defaultdict(lambda: {"plan": 0, "non_plan": 0})
        for row in rows_data:
            bucket[row[key]][row["verdict"]] += 1
        items = sorted(bucket.items())
        print(f"  {'max':>4} | {'plan':>5} | {'non':>5} | {'%plan':>6}", flush=True)
        for v, d in items:
            tot = d["plan"] + d["non_plan"]
            pct = 100.0 * d["plan"] / max(tot, 1)
            print(f"  {v:>4} | {d['plan']:>5} | {d['non_plan']:>5} | {pct:>5.1f}%", flush=True)

        # Cumulative cutoff
        print(f"\n  Si on impose {key} <= tau, on garde combien et de quelle qualite ?", flush=True)
        print(f"  {'tau':>4} | {'kept':>5} | {'plan':>5} | {'%plan':>6}", flush=True)
        max_v = max((row[key] for row in rows_data), default=0)
        for tau in range(max_v + 1):
            kept = [r0 for r0 in rows_data if r0[key] <= tau]
            n_pl = sum(1 for r0 in kept if r0["verdict"] == "plan")
            pct = 100.0 * n_pl / max(len(kept), 1)
            print(f"  {tau:>4} | {len(kept):>5} | {n_pl:>5} | {pct:>5.1f}%", flush=True)

    # ---------------- Compose : Gauss-Bonnet + analyse globale ----------------

    print(f"\n=== Statistiques globales (sur {len(rows_data)} mols) ===", flush=True)
    pl = [r0 for r0 in rows_data if r0["verdict"] == "plan"]
    npl = [r0 for r0 in rows_data if r0["verdict"] == "non_plan"]
    if pl:
        for r in radii:
            avg = sum(r0[f"max_local_r{r}"] for r0 in pl) / len(pl)
            mx = max(r0[f"max_local_r{r}"] for r0 in pl)
            print(f"  plan     (n={len(pl)}) : max_r{r} mean={avg:.2f} / max={mx}", flush=True)
    if npl:
        for r in radii:
            avg = sum(r0[f"max_local_r{r}"] for r0 in npl) / len(npl)
            mx = max(r0[f"max_local_r{r}"] for r0 in npl)
            print(f"  non_plan (n={len(npl)}) : max_r{r} mean={avg:.2f} / max={mx}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--graph-dir", default=GRAPH_DIR_DEFAULT)
    ap.add_argument("--h", required=True, help="h6, h7, h8 ou h9")
    ap.add_argument("--n-per-class", type=int, default=200)
    ap.add_argument("--radii", default="1,2,3")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    radii = tuple(int(x) for x in args.radii.split(","))
    print(f"[db] {args.db}", flush=True)
    print(f"[h] {args.h}  n_per_class={args.n_per_class}  radii={radii}", flush=True)
    evaluate(args.db, args.graph_dir, args.h, args.n_per_class, radii,
             args.seed, args.verbose)


if __name__ == "__main__":
    main()
