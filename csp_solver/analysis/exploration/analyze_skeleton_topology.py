"""Test : classer les squelettes (forme avant assignment 5/6/7) et regarder
si certaines familles sont intrinsequement plus planes.

Pour chaque squelette unique (mol_name) :
  - n_atoms      : nombre de carbones
  - n_peri_atoms : atomes appartenant a >=3 cycles
  - dual_diameter : BFS sur le dual
  - max_dual_deg : degre max dans le dual
  - n_branch_nodes : nb hex avec degre dual >= 3
  - shape : 'linear' / 'branched' / 'peri'

Puis on aggrege par (shape, h) : %PLAN moyen, N_sols, etc.

Output : tmp/skeleton_topology_h{H}.csv + analyse globale
"""

import gzip
import sqlite3
import sys
from collections import Counter, defaultdict, deque


def parse_hexs(graph_content):
    hexs = []
    for line in graph_content.strip().split("\n"):
        line = line.strip()
        if line.startswith("h "):
            hexs.append(line.split()[1:])
    return hexs


def skeleton_features(hexs):
    """Retourne dict de features pour un squelette."""
    sets = [set(h) for h in hexs]
    n_hex = len(hexs)
    # Adjacence du dual
    adj = [[] for _ in range(n_hex)]
    for i in range(n_hex):
        for j in range(i+1, n_hex):
            if len(sets[i] & sets[j]) >= 2:
                adj[i].append(j); adj[j].append(i)
    degs = [len(a) for a in adj]
    max_deg = max(degs) if degs else 0
    n_branch = sum(1 for d in degs if d >= 3)
    # Diametre BFS
    diameter = 0
    for start in range(n_hex):
        dist = [-1] * n_hex
        dist[start] = 0
        q = deque([start])
        while q:
            v = q.popleft()
            for u in adj[v]:
                if dist[u] == -1:
                    dist[u] = dist[v] + 1
                    q.append(u)
        local_max = max((d for d in dist if d >= 0), default=0)
        if local_max > diameter: diameter = local_max
    # Peri atoms
    cnt = Counter()
    for h in hexs:
        for a in h: cnt[a] += 1
    n_peri = sum(1 for v in cnt.values() if v >= 3)
    n_atoms = len(cnt)
    # Shape categorie
    if n_peri >= 1:
        shape = "peri"
    elif max_deg >= 3:
        shape = "branched"
    else:
        shape = "linear"
    return {
        "n_atoms": n_atoms,
        "n_hex": n_hex,
        "n_peri_atoms": n_peri,
        "dual_diameter": diameter,
        "max_dual_deg": max_deg,
        "n_branch_nodes": n_branch,
        "shape": shape,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db)

    for H in [7, 8, 9]:
        print(f"\n=== h{H} ===")
        # Squelettes uniques
        rows = conn.execute(
            "SELECT DISTINCT graph_name, graph_content_gz FROM final_solutions "
            "WHERE size_h=? AND config='C1' AND status='done'",
            (H,)
        ).fetchall()
        print(f"  {len(rows)} squelettes uniques")

        # Compute features
        skel_features = {}
        for graph_name, gz in rows:
            g = gzip.decompress(gz).decode()
            hexs = parse_hexs(g)
            skel_features[graph_name] = skeleton_features(hexs)

        # Aggreger : %PLAN par shape
        # Pour chaque squelette : compter ses sols C1 done plan/nonplan
        sol_stats = conn.execute(
            "SELECT graph_name, "
            "       SUM(verdict='PLAN') AS n_plan, "
            "       SUM(verdict='NON_PLAN') AS n_nonplan "
            "FROM final_solutions "
            "WHERE size_h=? AND config='C1' AND status='done' "
            "  AND verdict IN ('PLAN','NON_PLAN') "
            "GROUP BY graph_name",
            (H,)
        ).fetchall()

        agg_by_shape = defaultdict(lambda: {"n_mol": 0, "n_plan": 0, "n_nonplan": 0})
        for graph_name, n_plan, n_nonplan in sol_stats:
            feats = skel_features.get(graph_name)
            if not feats: continue
            shape = feats["shape"]
            agg_by_shape[shape]["n_mol"] += 1
            agg_by_shape[shape]["n_plan"] += n_plan
            agg_by_shape[shape]["n_nonplan"] += n_nonplan

        print(f"  {'shape':<12} {'N_mol':>7} {'N_sols':>10} {'N_plan':>10} {'%PLAN':>7}")
        for shape, stats in sorted(agg_by_shape.items()):
            n_sols = stats["n_plan"] + stats["n_nonplan"]
            pct = 100 * stats["n_plan"] / n_sols if n_sols else 0
            print(f"  {shape:<12} {stats['n_mol']:>7d} {n_sols:>10d} {stats['n_plan']:>10d} {pct:>6.1f}%")

        # Plus fin : par n_peri_atoms
        print()
        agg_peri = defaultdict(lambda: {"n_mol": 0, "n_plan": 0, "n_nonplan": 0})
        for graph_name, n_plan, n_nonplan in sol_stats:
            feats = skel_features.get(graph_name)
            if not feats: continue
            np_atoms = feats["n_peri_atoms"]
            agg_peri[np_atoms]["n_mol"] += 1
            agg_peri[np_atoms]["n_plan"] += n_plan
            agg_peri[np_atoms]["n_nonplan"] += n_nonplan
        print(f"  Par n_peri_atoms :")
        print(f"  {'n_peri':>6} {'N_mol':>7} {'N_sols':>10} {'N_plan':>10} {'%PLAN':>7}")
        for np_atoms in sorted(agg_peri.keys()):
            stats = agg_peri[np_atoms]
            n_sols = stats["n_plan"] + stats["n_nonplan"]
            pct = 100 * stats["n_plan"] / n_sols if n_sols else 0
            print(f"  {np_atoms:>6d} {stats['n_mol']:>7d} {n_sols:>10d} {stats['n_plan']:>10d} {pct:>6.1f}%")

        # Et par max_dual_deg
        print()
        agg_dd = defaultdict(lambda: {"n_mol": 0, "n_plan": 0, "n_nonplan": 0})
        for graph_name, n_plan, n_nonplan in sol_stats:
            feats = skel_features.get(graph_name)
            if not feats: continue
            mdd = feats["max_dual_deg"]
            agg_dd[mdd]["n_mol"] += 1
            agg_dd[mdd]["n_plan"] += n_plan
            agg_dd[mdd]["n_nonplan"] += n_nonplan
        print(f"  Par max_dual_deg :")
        print(f"  {'max_dd':>6} {'N_mol':>7} {'N_sols':>10} {'N_plan':>10} {'%PLAN':>7}")
        for mdd in sorted(agg_dd.keys()):
            stats = agg_dd[mdd]
            n_sols = stats["n_plan"] + stats["n_nonplan"]
            pct = 100 * stats["n_plan"] / n_sols if n_sols else 0
            print(f"  {mdd:>6d} {stats['n_mol']:>7d} {n_sols:>10d} {stats['n_plan']:>10d} {pct:>6.1f}%")

    conn.close()


if __name__ == "__main__":
    main()
