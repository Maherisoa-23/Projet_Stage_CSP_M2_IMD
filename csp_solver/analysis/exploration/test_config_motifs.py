"""Teste plusieurs configurations virtuelles 'C-motifs' :

  - C-motif-strict : aucun motif blacklist STRICT (universels top 10 def w4+w5)
  - C-motif-loose  : aucun motif blacklist ELARGI (universels + h8-top)
  - C-motif-fav    : sols ayant AU MOINS UN motif favorisant universel
  - combinaisons C-motif x Pb1, x C2

Mesure sur h7, h8, h9.

Output : tableau comparatif vs C1/C2/C3 reels.
"""

import gzip
import json
import multiprocessing
import sqlite3
import sys
import time
from collections import defaultdict


# ---- Blacklists ----

BLACKLIST_W4_STRICT = {
    (7, 7, 7, 7), (5, 7, 7, 7), (5, 5, 5, 7), (5, 5, 7, 7), (7, 5, 7, 7),
}
BLACKLIST_W5_STRICT = {
    (5, 7, 7, 7, 7), (7, 5, 7, 7, 7), (7, 7, 5, 7, 7),
    (5, 5, 5, 7, 7), (5, 5, 7, 7, 7),
}

# Loose : ajoute les motifs h-specifiques mais clairement deletes
BLACKLIST_W4_LOOSE = BLACKLIST_W4_STRICT | {
    (5, 5, 5, 5), (5, 7, 7, 5), (6, 7, 7, 7), (6, 5, 7, 7),
}
BLACKLIST_W5_LOOSE = BLACKLIST_W5_STRICT | {
    (7, 7, 7, 7, 7), (5, 5, 5, 5, 5), (5, 7, 7, 7, 5), (5, 7, 7, 5, 7),
    (7, 5, 5, 5, 7), (5, 6, 7, 7, 7), (6, 7, 7, 7, 7),
}

# Motifs favorisants universels
FAVORS_W4 = {(6, 6, 6, 7), (6, 6, 6, 6), (5, 6, 6, 6), (5, 7, 6, 6), (6, 5, 6, 6)}
FAVORS_W5 = {(6, 6, 6, 6, 7), (5, 6, 6, 6, 6), (6, 6, 6, 6, 6), (6, 5, 6, 6, 6),
             (6, 6, 6, 7, 6), (5, 6, 6, 6, 7), (6, 6, 7, 6, 6)}


def _canonical(w):
    return min(w, tuple(reversed(w)))


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


def _dedup(seq):
    if not seq:
        return seq
    out = [seq[0]]
    for x in seq[1:]:
        if x != out[-1]:
            out.append(x)
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def _compute_motif_features(args):
    """Pour un sol : retourne (sol_id, has_bl_strict_w4, has_bl_strict_w5,
                                has_bl_loose_w4, has_bl_loose_w5,
                                has_fav_w4, has_fav_w5)."""
    sol_id, graph_gz, csp_json = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        hexs = _parse_hexs(graph)
        sizes = [int(sol.get(str(i), 6)) for i in range(len(hexs))]
        seq = _boundary_cycle_seq(hexs)
        if seq is None:
            return (sol_id, 0, 0, 0, 0, 0, 0)
        ddup = _dedup(seq)
        if len(ddup) < 4:
            return (sol_id, 0, 0, 0, 0, 0, 0)
        size_seq = [sizes[c] for c in ddup]
        L = len(size_seq)
        bl_strict_w4 = bl_loose_w4 = fav_w4 = False
        bl_strict_w5 = bl_loose_w5 = fav_w5 = False
        for i in range(L):
            w4 = _canonical(tuple(size_seq[(i + k) % L] for k in range(4)))
            if w4 in BLACKLIST_W4_STRICT: bl_strict_w4 = True
            if w4 in BLACKLIST_W4_LOOSE: bl_loose_w4 = True
            if w4 in FAVORS_W4: fav_w4 = True
            if L >= 5:
                w5 = _canonical(tuple(size_seq[(i + k) % L] for k in range(5)))
                if w5 in BLACKLIST_W5_STRICT: bl_strict_w5 = True
                if w5 in BLACKLIST_W5_LOOSE: bl_loose_w5 = True
                if w5 in FAVORS_W5: fav_w5 = True
        return (sol_id,
                int(bl_strict_w4), int(bl_strict_w5),
                int(bl_loose_w4), int(bl_loose_w5),
                int(fav_w4), int(fav_w5))
    except Exception:
        return (sol_id, 0, 0, 0, 0, 0, 0)


def compute_features_for_h(h_int, conn):
    print(f"\n=== Compute motif features pour h{h_int} ===")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sol_motif_features (
            sol_id INTEGER PRIMARY KEY,
            has_bl_strict_w4 INTEGER,
            has_bl_strict_w5 INTEGER,
            has_bl_loose_w4 INTEGER,
            has_bl_loose_w5 INTEGER,
            has_fav_w4 INTEGER,
            has_fav_w5 INTEGER
        )
    """)
    conn.commit()
    cur = conn.execute(
        "SELECT sol_id, graph_content_gz, csp_solution_json "
        "FROM final_solutions WHERE size_h=? AND config='C1' AND status='done' "
        "AND verdict IN ('PLAN','NON_PLAN')",
        (h_int,),
    )
    tasks = [(r[0], r[1], r[2]) for r in cur]
    print(f"  sols a calculer : {len(tasks)}")
    if not tasks:
        return
    t0 = time.perf_counter()
    pool = multiprocessing.Pool(processes=10)
    pending = []
    BATCH = 5000
    n_done = 0
    try:
        for r in pool.imap_unordered(_compute_motif_features, tasks, chunksize=200):
            pending.append(r)
            n_done += 1
            if len(pending) >= BATCH:
                conn.executemany(
                    "INSERT OR REPLACE INTO sol_motif_features VALUES (?,?,?,?,?,?,?)",
                    pending,
                )
                conn.commit()
                pending = []
            if n_done % 50000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s ({n_done/dt:.0f}/s)")
        if pending:
            conn.executemany(
                "INSERT OR REPLACE INTO sol_motif_features VALUES (?,?,?,?,?,?,?)",
                pending,
            )
            conn.commit()
    finally:
        pool.close()
        pool.join()
    print(f"  done en {time.perf_counter()-t0:.1f}s")


def test_configs(conn):
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n" + "="*80)
    print("COMPARATIF CONFIGURATIONS VIRTUELLES (motifs) vs REELLES C1/C2/C3")
    print("="*80)

    # Variantes : (nom, predicat SQL sur sol_motif_features smf + sol_features sf + sol_features_c9 sfc)
    # Predicats relatifs a la table solutions s, joints sur s.id = smf.sol_id
    VARIANTS = [
        ("C1 baseline",          "1=1"),
        ("C-mot w4 strict",       "smf.has_bl_strict_w4 = 0"),
        ("C-mot w5 strict",       "smf.has_bl_strict_w5 = 0"),
        ("C-mot w4 OR w5 strict", "smf.has_bl_strict_w4 = 0 AND smf.has_bl_strict_w5 = 0"),
        ("C-mot w4 loose",        "smf.has_bl_loose_w4 = 0"),
        ("C-mot w5 loose",        "smf.has_bl_loose_w5 = 0"),
        ("C-mot loose w4+w5",     "smf.has_bl_loose_w4 = 0 AND smf.has_bl_loose_w5 = 0"),
        ("C-mot + fav w5",        "smf.has_bl_strict_w4 = 0 AND smf.has_bl_strict_w5 = 0 AND smf.has_fav_w5 = 1"),
        ("Pb1",                   "sfc.n_pent <= 1"),
        ("Pb1 + C-mot strict",    "sfc.n_pent <= 1 AND smf.has_bl_strict_w4 = 0 AND smf.has_bl_strict_w5 = 0"),
        ("Pb1 + C-mot loose",     "sfc.n_pent <= 1 AND smf.has_bl_loose_w4 = 0 AND smf.has_bl_loose_w5 = 0"),
    ]

    # Reference C2/C3 reels
    print(f"\n--- Reference : C2/C3 reelles ---")
    print(f"  {'h':<4} {'cfg':<6} {'N':>8} {'%PLAN':>7} {'median':>8} {'max':>7}")
    for h in ['h7','h8','h9']:
        for cfg in ['C1','C2','C3']:
            r = conn.execute(
                "SELECT COUNT(*), SUM(verdict='plan') FROM solutions "
                "WHERE h=? AND config=? AND angle_deg IS NOT NULL",
                (h, cfg)).fetchone()
            n, np = r
            if not n: continue
            med = conn.execute(
                "SELECT angle_deg FROM solutions WHERE h=? AND config=? AND angle_deg IS NOT NULL "
                "ORDER BY angle_deg LIMIT 1 OFFSET ?", (h, cfg, n//2)).fetchone()[0]
            mx = conn.execute(
                "SELECT MAX(angle_deg) FROM solutions WHERE h=? AND config=? AND angle_deg IS NOT NULL",
                (h, cfg)).fetchone()[0]
            print(f"  {h:<4} {cfg:<6} {n:>8} {100*np/n:>6.1f}% {med:>7.2f}° {mx:>6.2f}°")

    # Variantes virtuelles
    for h in ['h7', 'h8', 'h9']:
        print(f"\n--- {h} : variantes virtuelles (filtre sols C1) ---")
        print(f"  {'variante':<26} {'N':>8} {'%PLAN':>7} {'median':>8} {'max':>7}")
        for name, pred in VARIANTS:
            q = f"""
                SELECT angle_deg FROM solutions s
                JOIN sol_motif_features smf ON smf.sol_id = s.id
                JOIN sol_features sf  ON sf.sol_id  = s.id
                JOIN sol_features_c9 sfc ON sfc.sol_id = s.id
                WHERE s.h=? AND s.config='C1' AND s.angle_deg IS NOT NULL AND ({pred})
                ORDER BY s.angle_deg
            """
            vals = [r[0] for r in conn.execute(q, (h,)).fetchall()]
            n = len(vals)
            if n == 0:
                print(f"  {name:<26} {'-':>8}"); continue
            n_plan = sum(1 for v in vals if v <= 10.0)
            med = vals[n//2]
            mx = vals[-1]
            print(f"  {name:<26} {n:>8} {100*n_plan/n:>6.1f}% {med:>7.2f}° {mx:>6.2f}°")


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    sys.stdout.reconfigure(encoding="utf-8")

    # Compute features pour h7, h8, h9 (skip si deja en base)
    n_existing = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sol_motif_features'").fetchone()[0]
    if n_existing:
        cnt = conn.execute("SELECT COUNT(*) FROM sol_motif_features").fetchone()[0]
        print(f"sol_motif_features existe deja avec {cnt} entrees")
    else:
        cnt = 0

    if cnt < 700000:  # h7+h8+h9 ~ 730k
        for h in [7, 8, 9]:
            compute_features_for_h(h, conn)
    else:
        print("Features deja calculees, skip.")

    test_configs(conn)
    conn.close()


if __name__ == "__main__":
    main()
