"""Calcule deux features manquantes pour tester la config virtuelle C9 :

  - n_pent  : nombre de pentagones (pour la contrainte Pb1 = n_pent <= 1)
  - triple_jct_defect : nombre d'atomes appartenant a >= 3 cycles et dont
    AU MOINS UN cycle adjacent est un pent ou un hept. Cible la "Famille B"
    identifiee sur le top-10 h9 (defaut sur point peri-condense).

Ces features sont sauvegardees dans une table dediee `sol_features_c9` pour
ne pas casser le schema existant (sol_features = adj_55/57/77/n_sum).

Multiprocessing 10 workers.
"""

import gzip
import json
import multiprocessing
import sqlite3
import time
from collections import Counter


def _parse_hexs(graph_content):
    hexs = []
    for line in graph_content.strip().split("\n"):
        line = line.strip()
        if line.startswith("h "):
            hexs.append(line.split()[1:])
    return hexs


def _compute(args):
    sol_id, graph_gz, csp_json = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        hexs = _parse_hexs(graph)
        n_hex = len(hexs)

        sizes = [int(sol.get(str(i), 6)) for i in range(n_hex)]
        n_pent = sizes.count(5)
        n_hept = sizes.count(7)

        # Comptage des atomes : un atome partage par >=3 cycles est peri-condense
        atom_cycles = {}  # atom -> liste d'indices de cycles
        for ci, atoms in enumerate(hexs):
            for a in atoms:
                atom_cycles.setdefault(a, []).append(ci)

        # triple_jct_defect = atomes peri (>=3 cycles) dont au moins UN
        # cycle attache est pent ou hept
        triple_jct_defect = 0
        for a, cyc_list in atom_cycles.items():
            if len(cyc_list) < 3:
                continue
            if any(sizes[ci] != 6 for ci in cyc_list):
                triple_jct_defect += 1

        return (sol_id, n_pent, n_hept, triple_jct_defect)
    except Exception:
        return (sol_id, None, None, None)


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sol_features_c9 (
            sol_id INTEGER PRIMARY KEY,
            n_pent INTEGER,
            n_hept INTEGER,
            triple_jct_defect INTEGER
        )
    """)
    conn.commit()

    done_existing = {r[0] for r in conn.execute(
        "SELECT sol_id FROM sol_features_c9").fetchall()}
    print(f"=== compute_c9_features START ===")
    print(f"  deja en base : {len(done_existing)}")

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
    print(f"  a calculer : {len(tasks)}")

    if not tasks:
        print("  rien a faire.")
        conn.close()
        return

    t0 = time.perf_counter()
    pool = multiprocessing.Pool(processes=10)
    pending = []
    n_done = 0
    n_err = 0
    BATCH = 5000
    try:
        for r in pool.imap_unordered(_compute, tasks, chunksize=200):
            sol_id, n_pent, n_hept, tjd = r
            if n_pent is None:
                n_err += 1
            else:
                pending.append((sol_id, n_pent, n_hept, tjd))
            n_done += 1
            if len(pending) >= BATCH:
                conn.executemany(
                    "INSERT OR REPLACE INTO sol_features_c9 VALUES (?,?,?,?)",
                    pending,
                )
                conn.commit()
                pending = []
            if n_done % 10000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s ({n_done/dt:.0f}/s)")
        if pending:
            conn.executemany(
                "INSERT OR REPLACE INTO sol_features_c9 VALUES (?,?,?,?)",
                pending,
            )
            conn.commit()
    finally:
        pool.close()
        pool.join()
    print(f"=== DONE : {n_done} en {time.perf_counter()-t0:.1f}s (err={n_err}) ===")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sfc9 ON sol_features_c9(n_pent, triple_jct_defect)")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM sol_features_c9").fetchone()[0]
    print(f"Total sol_features_c9: {total}")
    conn.close()


if __name__ == "__main__":
    main()
