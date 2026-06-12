"""Extrait les motifs de bord (fenetres glissantes w=4 et w=5) sur le bord
externe du graphe dual pour tous les sols hN C1 done.

Version generalisee : prend h en argument (ex. python extract_boundary_motifs.py 7).

Sortie : tmp/motifs_hN_w4.csv, tmp/motifs_hN_w5.csv
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


def _boundary_cycle_seq(hexs):
    edges_by_cycle = []
    for h in hexs:
        edges = [tuple(sorted([h[i], h[(i+1) % len(h)]])) for i in range(len(h))]
        edges_by_cycle.append(edges)
    edge_cycles = defaultdict(list)
    for ci, edges in enumerate(edges_by_cycle):
        for e in edges:
            edge_cycles[e].append(ci)
    boundary_edges = {e for e, cyc in edge_cycles.items() if len(cyc) == 1}
    if not boundary_edges:
        return None
    bd_neighbors = defaultdict(list)
    bd_edge_cycle = {}
    for e in boundary_edges:
        a, b = e
        bd_neighbors[a].append(b)
        bd_neighbors[b].append(a)
        bd_edge_cycle[e] = edge_cycles[e][0]
    start = next(iter(bd_neighbors))
    visited = {start}
    cycle_seq = []
    cur = start
    prev = None
    while True:
        nbrs = bd_neighbors[cur]
        nxt = None
        for n in nbrs:
            if n != prev:
                nxt = n
                break
        if nxt is None:
            break
        edge = tuple(sorted([cur, nxt]))
        cycle_seq.append(bd_edge_cycle[edge])
        if nxt == start:
            break
        if nxt in visited:
            break
        visited.add(nxt)
        prev = cur
        cur = nxt
    return cycle_seq


def _dedup_consecutive(seq):
    if not seq:
        return seq
    out = [seq[0]]
    for x in seq[1:]:
        if x != out[-1]:
            out.append(x)
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def _canonical_window(w):
    rev = tuple(reversed(w))
    return min(w, rev)


def _extract_motifs(args):
    sol_id, graph_gz, csp_json, verdict = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        hexs = _parse_hexs(graph)
        n_hex = len(hexs)
        sizes = [int(sol.get(str(i), 6)) for i in range(n_hex)]
        cycle_seq = _boundary_cycle_seq(hexs)
        if cycle_seq is None or len(cycle_seq) < 4:
            return (sol_id, verdict, [], [])
        ddup = _dedup_consecutive(cycle_seq)
        if len(ddup) < 4:
            return (sol_id, verdict, [], [])
        size_seq = [sizes[c] for c in ddup]
        L = len(size_seq)
        motifs_w4 = set()
        motifs_w5 = set()
        for i in range(L):
            w4 = tuple(size_seq[(i + k) % L] for k in range(4))
            motifs_w4.add(_canonical_window(w4))
            if L >= 5:
                w5 = tuple(size_seq[(i + k) % L] for k in range(5))
                motifs_w5.add(_canonical_window(w5))
        return (sol_id, verdict, list(motifs_w4), list(motifs_w5))
    except Exception:
        return (sol_id, verdict, [], [])


def run_for_h(h_int):
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.row_factory = sqlite3.Row

    print(f"\n=== extract_boundary_motifs h{h_int} START ===")

    cur = conn.execute(
        "SELECT sol_id, graph_content_gz, csp_solution_json, verdict "
        "FROM final_solutions WHERE size_h=? AND config='C1' AND status='done' "
        "AND verdict IN ('PLAN', 'NON_PLAN')",
        (h_int,),
    )
    tasks = [(r["sol_id"], r["graph_content_gz"], r["csp_solution_json"], r["verdict"])
             for r in cur]
    print(f"  sols h{h_int} C1 done: {len(tasks)}")
    if not tasks:
        return

    t0 = time.perf_counter()
    pool = multiprocessing.Pool(processes=10)
    counts_w4 = defaultdict(lambda: [0, 0])
    counts_w5 = defaultdict(lambda: [0, 0])
    examples_w4 = defaultdict(lambda: {"plan": [], "nonplan": []})
    examples_w5 = defaultdict(lambda: {"plan": [], "nonplan": []})

    n_done = 0
    try:
        for r in pool.imap_unordered(_extract_motifs, tasks, chunksize=200):
            sol_id, verdict, m4_list, m5_list = r
            is_plan = (verdict == "PLAN")
            key_idx = 0 if is_plan else 1
            tag = "plan" if is_plan else "nonplan"
            for m in m4_list:
                counts_w4[m][key_idx] += 1
                if len(examples_w4[m][tag]) < 5:
                    examples_w4[m][tag].append(sol_id)
            for m in m5_list:
                counts_w5[m][key_idx] += 1
                if len(examples_w5[m][tag]) < 5:
                    examples_w5[m][tag].append(sol_id)
            n_done += 1
            if n_done % 50000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s ({n_done/dt:.0f}/s) | w4={len(counts_w4)} w5={len(counts_w5)}")
    finally:
        pool.close()
        pool.join()

    n_sol_plan = sum(1 for t in tasks if t[3] == "PLAN")
    n_sol_total = len(tasks)
    baseline = 100 * n_sol_plan / n_sol_total
    print(f"  baseline h{h_int} C1 : {n_sol_plan}/{n_sol_total} = {baseline:.2f}% PLAN")
    print(f"  motifs distincts w4={len(counts_w4)}, w5={len(counts_w5)}, en {time.perf_counter()-t0:.1f}s")

    for w, counts, examples in [(4, counts_w4, examples_w4), (5, counts_w5, examples_w5)]:
        out = f"tmp/motifs_h{h_int}_w{w}.csv"
        with open(out, "w", encoding="utf-8") as f:
            f.write("motif\tn_total\tn_plan\tn_nonplan\tpct_plan\tdelta_pp\tex_plan\tex_nonplan\n")
            rows = []
            for m, (np_, nnp_) in counts.items():
                tot = np_ + nnp_
                pct = 100 * np_ / tot if tot else 0
                delta = pct - baseline
                rows.append((m, tot, np_, nnp_, pct, delta, examples[m]["plan"], examples[m]["nonplan"]))
            rows.sort(key=lambda r: -r[1])
            for r in rows:
                m, tot, np_, nnp_, pct, delta, exp, exn = r
                m_str = "-".join(str(x) for x in m)
                f.write(f"{m_str}\t{tot}\t{np_}\t{nnp_}\t{pct:.2f}\t{delta:+.2f}\t"
                        f"{','.join(str(x) for x in exp)}\t{','.join(str(x) for x in exn)}\n")
        print(f"  ecrit {out}")

    conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("Usage: extract_boundary_motifs.py <h>  (ex: 7 ou 9 ou 'all')")
        sys.exit(1)
    arg = sys.argv[1]
    if arg == "all":
        for h in [7, 8, 9]:
            run_for_h(h)
    else:
        run_for_h(int(arg))
