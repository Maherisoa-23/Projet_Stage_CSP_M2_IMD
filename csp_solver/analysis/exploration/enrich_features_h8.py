"""Enrichit tmp/h8_c1_features.csv avec features manquantes :
  - n_kekule          : nb de structures Kekule (plafonne a 1000)
  - is_biradical      : 1 si pas de matching parfait du squelette pi
  - dual_diameter     : diametre du graphe dual (BFS)
  - max_dual_deg      : degre max dans le dual
  - n_triple_junction : nb d'atomes partages par >=3 cycles
  - adj_entropy       : entropie Shannon normalisee sur (adj_55, adj_57, adj_77)

Multiprocessing local. Lit la DB pour le XYZ optimise.
"""

import csv
import gzip
import math
import multiprocessing
import sqlite3
import sys
import time
from collections import deque, Counter
from pathlib import Path


def _init_worker():
    global _build_mol_graph_from_text, _enumerate_kekule
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "viewer"))
    from molviz.bonds import build_mol_graph_from_text
    from molviz.kekule import enumerate_kekule
    _build_mol_graph_from_text = build_mol_graph_from_text
    _enumerate_kekule = enumerate_kekule


def _compute_features(args):
    sol_id, xyz_gz, adj_55, adj_57, adj_77 = args
    try:
        xyz = gzip.decompress(xyz_gz).decode("utf-8")
        mol = _build_mol_graph_from_text(xyz)
        n_atoms = len(mol.atoms)
        n_cycles = len(mol.cycles)
        if n_atoms == 0 or n_cycles == 0:
            return (sol_id, None, None, None, None, None, None, "empty_mol")

        # Kekule
        kekule_list, _is_exact = _enumerate_kekule(mol, max_count=1000)
        if not kekule_list:
            n_kekule = 0
            is_biradical = 1
        elif not kekule_list[0].is_perfect:
            n_kekule = len(kekule_list)
            is_biradical = 1
        else:
            n_kekule = len(kekule_list)
            is_biradical = 0

        # Dual graph : sommets = cycles, aretes = paires partageant >=2 atomes
        cycle_atoms = [set(c.atoms) for c in mol.cycles]
        dual_neighbors = {i: [] for i in range(n_cycles)}
        for i in range(n_cycles):
            for j in range(i + 1, n_cycles):
                if len(cycle_atoms[i] & cycle_atoms[j]) >= 2:
                    dual_neighbors[i].append(j)
                    dual_neighbors[j].append(i)
        max_dual_deg = max((len(nbrs) for nbrs in dual_neighbors.values()), default=0)

        # Diameter via BFS pour chaque sommet
        diameter = 0
        for start in range(n_cycles):
            dist = [-1] * n_cycles
            dist[start] = 0
            q = deque([start])
            while q:
                v = q.popleft()
                for u in dual_neighbors[v]:
                    if dist[u] == -1:
                        dist[u] = dist[v] + 1
                        q.append(u)
            local_max = max(d for d in dist if d >= 0)
            if local_max > diameter:
                diameter = local_max

        # n_triple_junction : atomes appartenant a >=3 cycles
        atom_in_cycles = Counter()
        for cycle in mol.cycles:
            for a in cycle.atoms:
                atom_in_cycles[a] += 1
        n_triple_junction = sum(1 for cnt in atom_in_cycles.values() if cnt >= 3)

        # Entropie d'adjacence
        total_adj = adj_55 + adj_57 + adj_77
        if total_adj == 0:
            adj_entropy = 0.0
        else:
            H = 0.0
            for c in (adj_55, adj_57, adj_77):
                if c > 0:
                    p = c / total_adj
                    H -= p * math.log2(p)
            adj_entropy = H / math.log2(3)  # normalize to [0, 1]

        return (sol_id, n_kekule, is_biradical, diameter, max_dual_deg,
                n_triple_junction, adj_entropy, None)
    except Exception as e:
        return (sol_id, None, None, None, None, None, None,
                f"{type(e).__name__}: {str(e)[:120]}")


def main():
    csv_in = "tmp/h8_c1_features.csv"
    csv_out = "tmp/h8_c1_features_enriched.csv"
    db_path = "experiments/final/final_h3_h9.db"

    # Charger le CSV existant
    with open(csv_in) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"Loaded {len(rows)} rows from {csv_in}")

    # Recuperer xyz_optimized_gz depuis la DB par sol_id
    print("Chargement xyz_optimized_gz depuis DB...")
    sol_ids = [int(r['sol_id']) for r in rows]
    conn = sqlite3.connect(db_path)
    # Iterer par batch pour eviter d'allouer 100k blobs d'un coup
    xyz_map = {}
    BATCH = 5000
    t0 = time.perf_counter()
    for i in range(0, len(sol_ids), BATCH):
        batch_ids = sol_ids[i:i + BATCH]
        placeholders = ",".join("?" * len(batch_ids))
        cur = conn.execute(
            f"SELECT sol_id, xyz_optimized_gz FROM final_solutions WHERE sol_id IN ({placeholders})",
            batch_ids,
        )
        for sid, xyz_gz in cur:
            xyz_map[sid] = xyz_gz
    conn.close()
    print(f"  -> {len(xyz_map)} xyz charges en {time.perf_counter()-t0:.1f}s")

    # Préparer args
    tasks = []
    for r in rows:
        sid = int(r['sol_id'])
        xyz_gz = xyz_map.get(sid)
        if xyz_gz is None:
            continue
        adj_55 = int(r['adj_55'])
        adj_57 = int(r['adj_57'])
        adj_77 = int(r['adj_77'])
        tasks.append((sid, xyz_gz, adj_55, adj_57, adj_77))
    print(f"Tasks : {len(tasks)}")

    # Multiprocessing
    print("Multiprocessing 10 workers...")
    results = {}
    pool = multiprocessing.Pool(processes=10, initializer=_init_worker)
    t0 = time.perf_counter()
    n_done = 0
    n_err = 0
    for r in pool.imap_unordered(_compute_features, tasks, chunksize=50):
        sol_id, nk, ib, diam, maxd, ntj, ent, err = r
        if err:
            n_err += 1
        results[sol_id] = (nk, ib, diam, maxd, ntj, ent)
        n_done += 1
        if n_done % 10000 == 0:
            dt = time.perf_counter() - t0
            print(f"  {n_done}/{len(tasks)} en {dt:.1f}s ({n_done/dt:.0f}/s, err={n_err})")
    pool.close()
    pool.join()
    dt = time.perf_counter() - t0
    print(f"Termine : {n_done} en {dt:.1f}s (err={n_err})")

    # Ecrire CSV enrichi
    extra_cols = ['n_kekule', 'is_biradical', 'dual_diameter',
                  'max_dual_deg', 'n_triple_junction', 'adj_entropy']
    with open(csv_out, 'w', newline='', encoding='utf-8') as f:
        fieldnames = list(rows[0].keys()) + extra_cols
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            sid = int(r['sol_id'])
            res = results.get(sid)
            if res:
                nk, ib, diam, maxd, ntj, ent = res
                r['n_kekule'] = nk if nk is not None else ''
                r['is_biradical'] = ib if ib is not None else ''
                r['dual_diameter'] = diam if diam is not None else ''
                r['max_dual_deg'] = maxd if maxd is not None else ''
                r['n_triple_junction'] = ntj if ntj is not None else ''
                r['adj_entropy'] = f"{ent:.4f}" if ent is not None else ''
            else:
                for c in extra_cols:
                    r[c] = ''
            writer.writerow(r)
    print(f"CSV ecrit : {csv_out}")


if __name__ == "__main__":
    main()
