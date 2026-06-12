"""Test motifs rayon-2 du graphe dual.

Pour chaque cycle d'une sol, on extrait :
  motif = (taille_central, tuple_trie(tailles_voisins_directs))

Exemples :
  (6, (5, 6, 7))  : hex avec un pent, un hex, un hept voisins
  (7, (5, 5))     : hept avec 2 pent voisins (sur le bord, donc degre 2)
  (6, (6, 6, 6, 6, 6, 6))  : hex peri-condense entoure d'hex

Un sol contient un multiset de ces motifs. On accumule :
  - pour chaque motif distinct, n_plan / n_nonplan parmi les sols qui le contiennent.

Cible h8 (statistique riche, baseline 60% PLAN).
"""

import gzip
import json
import multiprocessing
import sqlite3
import sys
import time
from collections import defaultdict


def _parse_hexs(graph_content):
    hexs = []
    for line in graph_content.strip().split("\n"):
        line = line.strip()
        if line.startswith("h "):
            hexs.append(line.split()[1:])
    return hexs


def _adjacency(hexs):
    sets = [set(h) for h in hexs]
    n = len(hexs)
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i+1, n):
            if len(sets[i] & sets[j]) >= 2:
                adj[i].append(j); adj[j].append(i)
    return adj


def _extract(args):
    sol_id, graph_gz, csp_json, verdict = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        hexs = _parse_hexs(graph)
        sizes = [int(sol.get(str(i), 6)) for i in range(len(hexs))]
        adj = _adjacency(hexs)
        # Pour chaque cycle, construit son motif rayon-2
        motifs = set()
        for ci in range(len(hexs)):
            nbr_sizes = tuple(sorted(sizes[u] for u in adj[ci]))
            motif = (sizes[ci], nbr_sizes)
            motifs.add(motif)
        return (sol_id, verdict, list(motifs))
    except Exception:
        return (sol_id, verdict, [])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db)

    H = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    print(f"=== Motifs rayon-2 dual sur h{H} ===")
    cur = conn.execute(
        "SELECT sol_id, graph_content_gz, csp_solution_json, verdict "
        "FROM final_solutions WHERE size_h=? AND config='C1' AND status='done' "
        "AND verdict IN ('PLAN','NON_PLAN')",
        (H,),
    )
    tasks = [(r[0], r[1], r[2], r[3]) for r in cur]
    print(f"  sols : {len(tasks)}")

    t0 = time.perf_counter()
    pool = multiprocessing.Pool(10)
    counts = defaultdict(lambda: [0, 0])  # motif -> [n_plan, n_nonplan]
    examples = defaultdict(lambda: {"plan": [], "nonplan": []})
    n_done = 0
    n_sol_plan = 0
    n_sol_total = 0
    try:
        for r in pool.imap_unordered(_extract, tasks, chunksize=200):
            sol_id, verdict, motifs = r
            is_plan = (verdict == "PLAN")
            n_sol_total += 1
            if is_plan: n_sol_plan += 1
            key = 0 if is_plan else 1
            tag = "plan" if is_plan else "nonplan"
            for m in motifs:
                counts[m][key] += 1
                if len(examples[m][tag]) < 3:
                    examples[m][tag].append(sol_id)
            n_done += 1
            if n_done % 20000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s (motifs={len(counts)})")
    finally:
        pool.close()
        pool.join()

    baseline = 100 * n_sol_plan / n_sol_total
    print(f"  baseline : {baseline:.2f}% PLAN")
    print(f"  motifs distincts : {len(counts)}")
    print(f"  termine en {time.perf_counter()-t0:.1f}s")

    # Tableau : tous motifs avec n_total, %PLAN, delta_pp
    import math
    rows = []
    for motif, (np_, nnp_) in counts.items():
        tot = np_ + nnp_
        pct = 100 * np_ / tot if tot else 0
        delta = pct - baseline
        score = abs(delta) * math.sqrt(tot)
        center, nbrs = motif
        nbr_str = "[" + ",".join(str(x) for x in nbrs) + "]"
        motif_str = f"{center}|{nbr_str}"
        rows.append((motif_str, tot, np_, nnp_, pct, delta, score,
                     examples[motif]["plan"], examples[motif]["nonplan"]))
    rows.sort(key=lambda r: -r[6])

    # Sauve CSV
    with open(f"tmp/motifs_radius2_h{H}.csv", "w", encoding="utf-8") as f:
        f.write("motif\tn_total\tn_plan\tn_nonplan\tpct_plan\tdelta_pp\tscore\tex_plan\tex_nonplan\n")
        for r in rows:
            f.write("\t".join([
                str(r[0]), str(r[1]), str(r[2]), str(r[3]),
                f"{r[4]:.2f}", f"{r[5]:+.2f}", f"{r[6]:.1f}",
                ",".join(str(x) for x in r[7]),
                ",".join(str(x) for x in r[8]),
            ]) + "\n")
    print(f"  ecrit tmp/motifs_radius2_h{H}.csv")

    # Top 15 favorisants + 15 defavorisants (filtre n>=1000)
    print()
    print("=== TOP 15 motifs rayon-2 FAVORISANT (h8, n>=1000) ===")
    print(f"  {'center|neighbors':<35} {'N':>8} {'%PLAN':>7} {'delta':>9}")
    filt_fav = [r for r in rows if r[1] >= 1000 and r[5] > 0]
    filt_fav.sort(key=lambda r: -r[6])
    for r in filt_fav[:15]:
        print(f"  {r[0]:<35} {r[1]:>8} {r[4]:>6.2f}% {r[5]:>+8.2f}")
    print()
    print("=== TOP 15 motifs rayon-2 DEFAVORISANT (h8, n>=1000) ===")
    filt_def = [r for r in rows if r[1] >= 1000 and r[5] < 0]
    filt_def.sort(key=lambda r: -r[6])
    print(f"  {'center|neighbors':<35} {'N':>8} {'%PLAN':>7} {'delta':>9}")
    for r in filt_def[:15]:
        print(f"  {r[0]:<35} {r[1]:>8} {r[4]:>6.2f}% {r[5]:>+8.2f}")

    conn.close()


if __name__ == "__main__":
    main()
