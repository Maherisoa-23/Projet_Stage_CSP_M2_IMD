"""Analyse data mining h8 C1 : qu'est-ce qui sépare PLAN de NON_PLAN ?

Approche :
1. Extraction features par sol (depuis final_solutions + parsing graph)
2. Stats descriptives par verdict
3. Tests d'hypothèses (corrélations univariées + multivariées)
4. Règles simples (decision rules manuelles)

Features extraites par sol :
  - n_pent, n_hept, n_hex : nombre de cycles 5/7/6 dans la sol
  - n_diff : |n_pent - n_hept|
  - adj_55, adj_57, adj_77 : nb d'adjacences entre cycles de ces tailles
  - adj_56, adj_67 : adjacences avec hexagones
  - pent_on_boundary : pent sur le bord (degree dual < 6)
  - hept_on_boundary : hept sur le bord
  - energy_eh, homo_lumo_ev : metriques xTB
  - angle_deg, verdict
"""

import json
import gzip
import sqlite3
import time
from collections import Counter, defaultdict


def parse_graph_to_adjacency(graph_content):
    """Parse le format DIMACS et retourne dict {vertex: [neighbors]}.

    Format ligne 'h v1 v2 ... v6' (hexagones avec leurs sommets atomes).
    Ici on veut l'adjacence entre HEXAGONES (cycles) du benzenoide,
    pas entre atomes. Deux hex sont adjacents s'ils partagent une arete = 2 atomes.
    """
    lines = graph_content.strip().split('\n')
    hexagons = []  # list of frozensets of atom-vertices
    for line in lines:
        line = line.strip()
        if not line.startswith('h '):
            continue
        atoms = line.split()[1:]
        hexagons.append(frozenset(atoms))
    # Adjacence: deux hexagones adjacents s'ils partagent >= 2 atomes (arete)
    n_hex = len(hexagons)
    adj = {i: [] for i in range(n_hex)}
    for i in range(n_hex):
        for j in range(i+1, n_hex):
            shared = hexagons[i] & hexagons[j]
            if len(shared) >= 2:
                adj[i].append(j)
                adj[j].append(i)
    return adj, n_hex


def compute_features(sol_dict, graph_content, energy, homo_lumo, angle):
    """Calcule les features pour une sol."""
    n_pent = sum(1 for v in sol_dict.values() if v == 5)
    n_hept = sum(1 for v in sol_dict.values() if v == 7)
    n_hex = sum(1 for v in sol_dict.values() if v == 6)

    adj, n_total = parse_graph_to_adjacency(graph_content)

    # Compteurs d'adjacences
    adj_55 = adj_57 = adj_77 = adj_56 = adj_67 = adj_66 = 0
    for v, neighbors in adj.items():
        v_size = sol_dict.get(str(v), 6)
        for u in neighbors:
            if u > v:  # éviter double comptage
                u_size = sol_dict.get(str(u), 6)
                pair = tuple(sorted([v_size, u_size]))
                if pair == (5, 5): adj_55 += 1
                elif pair == (5, 7): adj_57 += 1
                elif pair == (7, 7): adj_77 += 1
                elif pair == (5, 6): adj_56 += 1
                elif pair == (6, 7): adj_67 += 1
                elif pair == (6, 6): adj_66 += 1

    # Bord = sommets de degré dual < 6 (graphe dual des hexagones)
    pent_on_boundary = 0
    hept_on_boundary = 0
    for v in range(n_total):
        v_size = sol_dict.get(str(v), 6)
        if len(adj[v]) < 6:  # sommet de bord (moins de 6 voisins)
            if v_size == 5:
                pent_on_boundary += 1
            elif v_size == 7:
                hept_on_boundary += 1

    return {
        'n_pent': n_pent,
        'n_hept': n_hept,
        'n_hex': n_hex,
        'n_diff': abs(n_pent - n_hept),
        'n_sum': n_pent + n_hept,
        'adj_55': adj_55,
        'adj_57': adj_57,
        'adj_77': adj_77,
        'adj_56': adj_56,
        'adj_67': adj_67,
        'adj_66': adj_66,
        'pent_on_boundary': pent_on_boundary,
        'hept_on_boundary': hept_on_boundary,
        'energy_eh': energy,
        'homo_lumo_ev': homo_lumo,
        'angle_deg': angle,
    }


def main():
    db = "experiments/final/final_h3_h9.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    print("=== Extraction features h8 C1 ===")
    t0 = time.perf_counter()
    cur = conn.execute("""
        SELECT sol_id, graph_name, sol_index, csp_solution_json, graph_content_gz,
               verdict, angle_deg, energy_eh, homo_lumo_ev
        FROM final_solutions
        WHERE size_h=8 AND config='C1' AND status='done'
    """)

    features_list = []
    n = 0
    for row in cur:
        sol = json.loads(row['csp_solution_json'])
        graph = gzip.decompress(row['graph_content_gz']).decode()
        feats = compute_features(sol, graph, row['energy_eh'], row['homo_lumo_ev'], row['angle_deg'])
        feats['verdict'] = row['verdict']
        feats['sol_id'] = row['sol_id']
        feats['graph_name'] = row['graph_name']
        features_list.append(feats)
        n += 1
        if n % 5000 == 0:
            print(f"  ... {n} sols extraites en {time.perf_counter()-t0:.1f}s")
    print(f"  Total: {n} sols en {time.perf_counter()-t0:.1f}s")
    conn.close()

    # === STATS DESCRIPTIVES ===
    print("\n=== Stats descriptives par verdict ===")
    plans = [f for f in features_list if f['verdict'] == 'PLAN']
    non_plans = [f for f in features_list if f['verdict'] in ('NON_PLAN', 'LIMITE')]
    print(f"PLAN: {len(plans)}  NON_PLAN+LIMITE: {len(non_plans)}")

    def stats(lst, key):
        vals = [f[key] for f in lst if f[key] is not None]
        if not vals:
            return (0, 0, 0, 0)
        vals = sorted(vals)
        n = len(vals)
        return (vals[0], vals[n//2], vals[-1], sum(vals)/n)

    print(f"\n{'Feature':<20} {'PLAN min/med/max/avg':<35} {'NONPLAN min/med/max/avg':<35}")
    for key in ['n_pent','n_hept','n_hex','n_diff','n_sum',
                'adj_55','adj_57','adj_77','adj_56','adj_67','adj_66',
                'pent_on_boundary','hept_on_boundary',
                'energy_eh','homo_lumo_ev','angle_deg']:
        sp = stats(plans, key)
        sn = stats(non_plans, key)
        print(f"{key:<20} P:{sp[0]:>7.2f}/{sp[1]:>7.2f}/{sp[2]:>7.2f}/{sp[3]:>7.2f}   N:{sn[0]:>7.2f}/{sn[1]:>7.2f}/{sn[2]:>7.2f}/{sn[3]:>7.2f}")

    # === Distribution par (n_pent, n_hept) ===
    print("\n=== Distribution PLAN/NONPLAN par (n_pent, n_hept) ===")
    dist = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in features_list:
        k = (f['n_pent'], f['n_hept'])
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        dist[k][v] += 1
    print(f"  {'(n_pent,n_hept)':<15} {'PLAN':>8} {'NONPLAN':>8} {'%PLAN':>8}")
    for k in sorted(dist.keys()):
        d = dist[k]
        tot = d['plan'] + d['non_plan']
        pct = 100*d['plan']/tot if tot > 0 else 0
        print(f"  ({k[0]},{k[1]}):       {d['plan']:>8} {d['non_plan']:>8} {pct:>7.1f}%")

    # === Effet adj_77 ===
    print("\n=== Effet adjacences 7-7 (forte courbure attendue) ===")
    by_adj77 = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in features_list:
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        by_adj77[f['adj_77']][v] += 1
    print(f"  {'adj_77':<8} {'PLAN':>8} {'NONPLAN':>8} {'%PLAN':>8}")
    for k in sorted(by_adj77.keys()):
        d = by_adj77[k]
        tot = d['plan'] + d['non_plan']
        pct = 100*d['plan']/tot if tot > 0 else 0
        print(f"  {k:<8} {d['plan']:>8} {d['non_plan']:>8} {pct:>7.1f}%")

    # === Effet adj_55 ===
    print("\n=== Effet adjacences 5-5 ===")
    by_adj55 = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in features_list:
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        by_adj55[f['adj_55']][v] += 1
    print(f"  {'adj_55':<8} {'PLAN':>8} {'NONPLAN':>8} {'%PLAN':>8}")
    for k in sorted(by_adj55.keys()):
        d = by_adj55[k]
        tot = d['plan'] + d['non_plan']
        pct = 100*d['plan']/tot if tot > 0 else 0
        print(f"  {k:<8} {d['plan']:>8} {d['non_plan']:>8} {pct:>7.1f}%")

    # === Effet symétrie locale (adj_57 vs total def) ===
    print("\n=== Effet 'symétrie défauts' (adj_57 / max possible) ===")
    by_adj57 = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in features_list:
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        by_adj57[f['adj_57']][v] += 1
    print(f"  {'adj_57':<8} {'PLAN':>8} {'NONPLAN':>8} {'%PLAN':>8}")
    for k in sorted(by_adj57.keys()):
        d = by_adj57[k]
        tot = d['plan'] + d['non_plan']
        pct = 100*d['plan']/tot if tot > 0 else 0
        print(f"  {k:<8} {d['plan']:>8} {d['non_plan']:>8} {pct:>7.1f}%")

    # === Effet boundary 5/7 ===
    print("\n=== Effet 5/7 sur le bord ===")
    by_bound = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in features_list:
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        k = (f['pent_on_boundary'], f['hept_on_boundary'])
        by_bound[k][v] += 1
    print(f"  {'(pent_b,hept_b)':<15} {'PLAN':>8} {'NONPLAN':>8} {'%PLAN':>8}")
    for k in sorted(by_bound.keys()):
        d = by_bound[k]
        tot = d['plan'] + d['non_plan']
        pct = 100*d['plan']/tot if tot > 0 else 0
        print(f"  ({k[0]},{k[1]}):       {d['plan']:>8} {d['non_plan']:>8} {pct:>7.1f}%")

    # === Règles simples (decision rules) ===
    print("\n=== Test de règles de séparation ===")
    rules = [
        ("adj_77 == 0", lambda f: f['adj_77'] == 0),
        ("adj_77 <= 1", lambda f: f['adj_77'] <= 1),
        ("adj_55 == 0", lambda f: f['adj_55'] == 0),
        ("adj_55 == 0 AND adj_77 == 0", lambda f: f['adj_55'] == 0 and f['adj_77'] == 0),
        ("n_diff <= 1", lambda f: f['n_diff'] <= 1),
        ("n_diff <= 2", lambda f: f['n_diff'] <= 2),
        ("pent_on_boundary <= 1", lambda f: f['pent_on_boundary'] <= 1),
        ("pent_on_boundary == 0 AND hept_on_boundary == 0", lambda f: f['pent_on_boundary'] == 0 and f['hept_on_boundary'] == 0),
        ("adj_57 >= n_pent + n_hept - 2", lambda f: f['adj_57'] >= f['n_pent'] + f['n_hept'] - 2),
        ("homo_lumo_ev > 1.0", lambda f: f['homo_lumo_ev'] is not None and f['homo_lumo_ev'] > 1.0),
        ("homo_lumo_ev > 0.5", lambda f: f['homo_lumo_ev'] is not None and f['homo_lumo_ev'] > 0.5),
    ]
    print(f"  {'Rule':<55} {'N matched':>10} {'%PLAN if match':>16}  {'%PLAN if not':>14}")
    for name, fn in rules:
        match = [f for f in features_list if fn(f)]
        nomatch = [f for f in features_list if not fn(f)]
        if match:
            p_match = 100*sum(1 for f in match if f['verdict']=='PLAN')/len(match)
        else:
            p_match = -1
        if nomatch:
            p_nomatch = 100*sum(1 for f in nomatch if f['verdict']=='PLAN')/len(nomatch)
        else:
            p_nomatch = -1
        print(f"  {name:<55} {len(match):>10} {p_match:>15.1f}%  {p_nomatch:>13.1f}%")

    # Sauve les features pour analyse ultérieure
    import csv
    out_path = "tmp/h8_c1_features.csv"
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        if features_list:
            writer = csv.DictWriter(f, fieldnames=features_list[0].keys())
            writer.writeheader()
            writer.writerows(features_list)
    print(f"\nFeatures sauvegardes : {out_path}")


if __name__ == "__main__":
    main()
