"""Teste les configurations combinees rayon-2 + topologie squelette.

Variantes :
  - C-r2 strict   : aucun motif rayon-2 de la blacklist universelle
  - C-r2 loose    : aucun motif rayon-2 de la blacklist elargie
  - C-skel good   : squelette dans {linear, peri-haut-deg}
  - C-skel bad-x  : exclure les squelettes 'branched'
  - C-r2 + C-skel : combinaison
  - + Pb1, + favs : variantes encore plus precises

Sortie : tableau avec N total, N plan, %PLAN pour h7/h8/h9.
"""

import gzip
import json
import multiprocessing
import sqlite3
import sys
import time
from collections import Counter, defaultdict, deque


# ---- BLACKLISTS RAYON-2 (universelles) ----
# Top motifs def communs h7+h8+h9 (Δ < -20 partout)
BL_R2_STRICT = {
    (7, (5, 7, 7)),
    (7, (7, 7)),
    (7, (6, 7, 7)),
    (7, (5, 6, 7, 7)),
    (5, (5,)),
    (7, (7,)),  # un hept au bord avec un seul voisin hept
}
# Loose : ajoute les variantes assez fortes
BL_R2_LOOSE = BL_R2_STRICT | {
    (7, (5, 5, 7, 7)),
    (5, (5, 5)),
    (7, (6, 6, 7, 7)),  # h9 : 0.13% PLAN
    (6, (6, 7, 7)),     # h9 : 1.89% PLAN
}
# Favorisants forts
FAV_R2 = {
    (6, (6, 6, 6, 7)),    # 87% PLAN h8
    (5, (6, 6, 6, 7)),    # 85% PLAN h8
    (6, (5, 6, 6, 7)),    # 83% PLAN h8
    (6, (6, 6, 6)),       # 84% PLAN h8
    (6, (5, 6, 6, 6)),
    (6, (6, 6, 7)),
}


def parse_hexs(g):
    return [line.split()[1:] for line in g.strip().split("\n") if line.strip().startswith("h ")]


def adj_dual(hexs):
    sets = [set(h) for h in hexs]
    n = len(hexs)
    a = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i+1, n):
            if len(sets[i] & sets[j]) >= 2:
                a[i].append(j); a[j].append(i)
    return a


def skeleton_shape(hexs):
    a = adj_dual(hexs)
    degs = [len(x) for x in a]
    max_deg = max(degs)
    cnt = Counter()
    for h in hexs:
        for atom in h: cnt[atom] += 1
    n_peri = sum(1 for v in cnt.values() if v >= 3)
    if n_peri >= 1: shape = "peri"
    elif max_deg >= 3: shape = "branched"
    else: shape = "linear"
    return shape, max_deg, n_peri


def _compute(args):
    sol_id, graph_gz, csp_json = args
    try:
        graph = gzip.decompress(graph_gz).decode()
        sol = json.loads(csp_json)
        hexs = parse_hexs(graph)
        sizes = [int(sol.get(str(i), 6)) for i in range(len(hexs))]
        a = adj_dual(hexs)

        # rayon-2 motifs presents
        has_bl_strict = 0
        has_bl_loose = 0
        has_fav = 0
        for ci in range(len(hexs)):
            nbrs = tuple(sorted(sizes[u] for u in a[ci]))
            motif = (sizes[ci], nbrs)
            if motif in BL_R2_STRICT: has_bl_strict = 1
            if motif in BL_R2_LOOSE: has_bl_loose = 1
            if motif in FAV_R2: has_fav = 1

        # shape (du squelette, independant de l'assignment)
        shape, max_deg, n_peri = skeleton_shape(hexs)

        return (sol_id, has_bl_strict, has_bl_loose, has_fav, shape, max_deg, n_peri)
    except Exception:
        return (sol_id, 0, 0, 0, "unknown", 0, 0)


def compute_features_for_h(h_int, conn):
    print(f"\n=== Compute combined features pour h{h_int} ===")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sol_combined_features (
            sol_id INTEGER PRIMARY KEY,
            has_bl_r2_strict INTEGER,
            has_bl_r2_loose INTEGER,
            has_fav_r2 INTEGER,
            skel_shape TEXT,
            skel_max_deg INTEGER,
            skel_n_peri INTEGER
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
        for r in pool.imap_unordered(_compute, tasks, chunksize=200):
            pending.append(r)
            n_done += 1
            if len(pending) >= BATCH:
                conn.executemany(
                    "INSERT OR REPLACE INTO sol_combined_features VALUES (?,?,?,?,?,?,?)",
                    pending,
                )
                conn.commit()
                pending = []
            if n_done % 100000 == 0:
                dt = time.perf_counter() - t0
                print(f"  {n_done}/{len(tasks)} en {dt:.1f}s")
        if pending:
            conn.executemany(
                "INSERT OR REPLACE INTO sol_combined_features VALUES (?,?,?,?,?,?,?)",
                pending,
            )
            conn.commit()
    finally:
        pool.close()
        pool.join()
    print(f"  done en {time.perf_counter()-t0:.1f}s")


def test_variants(conn):
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n" + "="*100)
    print("COMPARATIF CONFIGS COMBINEES (rayon-2 + topologie squelette)")
    print("="*100)

    VARIANTS = [
        ("C1 baseline",                  "1=1"),
        ("C-r2 strict",                  "scf.has_bl_r2_strict = 0"),
        ("C-r2 loose",                   "scf.has_bl_r2_loose = 0"),
        ("C-skel (no branched)",         "scf.skel_shape != 'branched'"),
        ("C-skel (peri-haut)",           "scf.skel_max_deg >= 4"),
        ("C-skel (n_peri >= 3)",         "scf.skel_n_peri >= 3"),
        ("C-r2 + no branched",           "scf.has_bl_r2_strict = 0 AND scf.skel_shape != 'branched'"),
        ("C-r2 loose + no branched",     "scf.has_bl_r2_loose = 0 AND scf.skel_shape != 'branched'"),
        ("C-r2 + n_peri >= 3",           "scf.has_bl_r2_strict = 0 AND scf.skel_n_peri >= 3"),
        ("C-r2 loose + n_peri >= 4",     "scf.has_bl_r2_loose = 0 AND scf.skel_n_peri >= 4"),
        ("C-r2 + fav + n_peri >= 3",     "scf.has_bl_r2_strict = 0 AND scf.has_fav_r2 = 1 AND scf.skel_n_peri >= 3"),
        ("Pb1",                          "sfc.n_pent <= 1"),
        ("Pb1 + C-r2 strict",            "sfc.n_pent <= 1 AND scf.has_bl_r2_strict = 0"),
        ("Pb1 + C-r2 + no branched",     "sfc.n_pent <= 1 AND scf.has_bl_r2_strict = 0 AND scf.skel_shape != 'branched'"),
        ("Pb1 + C-r2 loose + n_peri>=3", "sfc.n_pent <= 1 AND scf.has_bl_r2_loose = 0 AND scf.skel_n_peri >= 3"),
    ]

    # Reference C1/C2/C3 reels
    print(f"\n--- Reference C1/C2/C3 reels ---")
    print(f"  {'h':<4} {'cfg':<6} {'N_total':>10} {'N_plan':>10} {'%PLAN':>7}")
    for h in ['h7','h8','h9']:
        for cfg in ['C1','C2','C3']:
            r = conn.execute(
                "SELECT COUNT(*), SUM(verdict='plan') FROM solutions "
                "WHERE h=? AND config=? AND angle_deg IS NOT NULL",
                (h, cfg)).fetchone()
            n, np_ = r
            if not n: continue
            print(f"  {h:<4} {cfg:<6} {n:>10d} {np_:>10d} {100*np_/n:>6.1f}%")

    for h in ['h7', 'h8', 'h9']:
        print(f"\n--- {h} : variantes ---")
        print(f"  {'variante':<35} {'N_total':>10} {'N_plan':>10} {'%PLAN':>7} {'median':>8}")
        for name, pred in VARIANTS:
            q = f"""
                SELECT angle_deg FROM solutions s
                JOIN sol_combined_features scf ON scf.sol_id = s.id
                JOIN sol_features_c9 sfc ON sfc.sol_id = s.id
                WHERE s.h=? AND s.config='C1' AND s.angle_deg IS NOT NULL AND ({pred})
                ORDER BY s.angle_deg
            """
            vals = [r[0] for r in conn.execute(q, (h,)).fetchall()]
            n = len(vals)
            if n == 0:
                print(f"  {name:<35} {'-':>10}"); continue
            n_plan = sum(1 for v in vals if v <= 10.0)
            med = vals[n//2]
            print(f"  {name:<35} {n:>10d} {n_plan:>10d} {100*n_plan/n:>6.1f}% {med:>7.2f}°")


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db, timeout=120.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    sys.stdout.reconfigure(encoding="utf-8")

    # Compute features pour h7, h8, h9 si pas deja fait
    n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sol_combined_features'").fetchone()[0]
    cnt = conn.execute("SELECT COUNT(*) FROM sol_combined_features").fetchone()[0] if n else 0
    if cnt < 720000:
        for h in [7, 8, 9]:
            compute_features_for_h(h, conn)
    else:
        print(f"Features deja en base ({cnt} entrees)")

    test_variants(conn)
    conn.close()


if __name__ == "__main__":
    main()
