"""Calcule adj_55, adj_57, adj_77, n_sum pour TOUTES les sols C1 done (h3-h9).

Sauvegarde dans nouvelle table sol_features (sol_id PK, adj_55, adj_57, adj_77,
n_sum). Multiprocessing local 10 workers.

Utilise par materialize_virtual_configs.py pour creer les configs virtuelles.
"""

import gzip
import json
import multiprocessing
import sqlite3
import sys
import time
from pathlib import Path


def _parse_graph_to_adjacency(graph_content):
    lines = graph_content.strip().split('\n')
    hexagons = []
    for line in lines:
        line = line.strip()
        if not line.startswith('h '):
            continue
        atoms = line.split()[1:]
        hexagons.append(frozenset(atoms))
    n_hex = len(hexagons)
    adj = [[] for _ in range(n_hex)]
    for i in range(n_hex):
        for j in range(i+1, n_hex):
            if len(hexagons[i] & hexagons[j]) >= 2:
                adj[i].append(j)
                adj[j].append(i)
    return adj


def _compute(args):
    sol_id, graph_gz, csp_json = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        adj = _parse_graph_to_adjacency(graph)
        n_pent = sum(1 for v in sol.values() if v == 5)
        n_hept = sum(1 for v in sol.values() if v == 7)
        adj_55 = adj_57 = adj_77 = 0
        for v in range(len(adj)):
            v_size = sol.get(str(v), 6)
            for u in adj[v]:
                if u > v:
                    u_size = sol.get(str(u), 6)
                    pair = tuple(sorted([v_size, u_size]))
                    if pair == (5, 5): adj_55 += 1
                    elif pair == (5, 7): adj_57 += 1
                    elif pair == (7, 7): adj_77 += 1
        return (sol_id, adj_55, adj_57, adj_77, n_pent + n_hept)
    except Exception:
        return (sol_id, None, None, None, None)


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    print("=== compute_adjacencies_all START ===")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sol_features (
            sol_id INTEGER PRIMARY KEY,
            adj_55 INTEGER,
            adj_57 INTEGER,
            adj_77 INTEGER,
            n_sum  INTEGER
        )
    """)
    conn.commit()

    # Sols C1 done deja calculees
    done_existing = {r[0] for r in conn.execute("SELECT sol_id FROM sol_features").fetchall()}
    print(f"  Deja en base : {len(done_existing)}")

    # Sols a calculer : C1 done h3-h9 non encore dans sol_features
    cur = conn.execute("""
        SELECT sol_id, graph_content_gz, csp_solution_json
        FROM final_solutions
        WHERE config='C1' AND status='done'
        ORDER BY sol_id
    """)
    tasks = []
    for sol_id, graph_gz, csp_json in cur:
        if sol_id in done_existing:
            continue
        tasks.append((sol_id, graph_gz, csp_json))
    print(f"  Sols a calculer : {len(tasks)}")

    if not tasks:
        print("  Rien a faire.")
        conn.close()
        return

    t0 = time.perf_counter()
    pool = multiprocessing.Pool(processes=10)
    BATCH = 5000
    n_done = 0
    n_err = 0
    pending_insert = []
    try:
        for r in pool.imap_unordered(_compute, tasks, chunksize=200):
            sol_id, a55, a57, a77, ns = r
            if a55 is None:
                n_err += 1
            else:
                pending_insert.append((sol_id, a55, a57, a77, ns))
            n_done += 1
            if len(pending_insert) >= BATCH:
                conn.executemany("INSERT OR REPLACE INTO sol_features VALUES (?,?,?,?,?)", pending_insert)
                conn.commit()
                pending_insert = []
            if n_done % 10000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s ({n_done/dt:.0f}/s)")
        if pending_insert:
            conn.executemany("INSERT OR REPLACE INTO sol_features VALUES (?,?,?,?,?)", pending_insert)
            conn.commit()
    finally:
        pool.close()
        pool.join()
    print(f"=== DONE : {n_done} sols en {time.perf_counter()-t0:.1f}s (err={n_err}) ===")
    # Index pour les queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sol_features_adj ON sol_features(adj_55, adj_57, adj_77, n_sum)")
    conn.commit()
    print(f"Total sol_features: {conn.execute('SELECT COUNT(*) FROM sol_features').fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main()
