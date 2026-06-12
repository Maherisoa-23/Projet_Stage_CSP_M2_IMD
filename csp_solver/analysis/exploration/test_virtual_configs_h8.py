"""Teste des configurations CSP virtuelles sur h8 C1 (sans relancer xTB).

Pour chaque config virtuelle (= predicat sur features) :
  - filtre les sols qui le satisfont
  - calcule %PLAN dans le subset
  - compare avec C1 (57.4%), C2 (82.0%), C3 (97.3%) reels

Output : tableau + ranking + frontiere Pareto purity/quantity.
"""

import csv
import math
from collections import defaultdict


def load_features(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    int_cols = ['n_pent','n_hept','n_hex','n_diff','n_sum','adj_55','adj_57','adj_77',
                'adj_56','adj_67','adj_66','pent_on_boundary','hept_on_boundary',
                'n_kekule','is_biradical','dual_diameter','max_dual_deg','n_triple_junction']
    float_cols = ['energy_eh','homo_lumo_ev','angle_deg','adj_entropy']
    for r in rows:
        for k in int_cols:
            if r.get(k) and r[k] != '':
                r[k] = int(r[k])
            else:
                r[k] = None
        for k in float_cols:
            if r.get(k) and r[k] != '':
                try: r[k] = float(r[k])
                except: r[k] = None
            else:
                r[k] = None
    return rows


def evaluate_config(rows, predicate, name):
    matched = [r for r in rows if predicate(r)]
    if not matched:
        return None
    n_total = len(matched)
    n_plan = sum(1 for r in matched if r['verdict'] == 'PLAN')
    pct = 100 * n_plan / n_total
    return {
        'name': name,
        'N': n_total,
        'N_plan': n_plan,
        '%PLAN': pct,
        'selectivity': n_total / len(rows),
        'gain_pts': pct - 57.4,
    }


def main():
    rows = load_features("tmp/h8_c1_features_enriched.csv")
    # Filtre : ne garder que ceux avec features completes
    rows = [r for r in rows if r.get('n_kekule') is not None]
    print(f"Sols completes (avec features enrichies) : {len(rows)}")

    n_plan_baseline = sum(1 for r in rows if r['verdict'] == 'PLAN')
    baseline_pct = 100 * n_plan_baseline / len(rows)
    print(f"Baseline (C1 actuel) : {n_plan_baseline}/{len(rows)} = {baseline_pct:.2f}% PLAN")
    print()

    # Configs virtuelles a tester
    configs = [
        # Singles
        ("C4: adj_77 == 0",                    lambda r: r['adj_77'] == 0),
        ("C5: adj_55 + adj_77 == 0",            lambda r: r['adj_55'] + r['adj_77'] == 0),
        ("C6: adj_55 + adj_77 <= 1",            lambda r: r['adj_55'] + r['adj_77'] <= 1),
        ("C7: adj_57 >= 1",                     lambda r: r['adj_57'] >= 1),
        ("C8: n_sum <= 4",                      lambda r: r['n_sum'] <= 4),
        ("C9: n_kekule >= 3",                   lambda r: r['n_kekule'] >= 3),
        ("C9b: n_kekule >= 5",                  lambda r: r['n_kekule'] >= 5),
        ("C9c: n_kekule >= 9",                  lambda r: r['n_kekule'] >= 9),
        ("C10: dual_diameter >= 4",             lambda r: r['dual_diameter'] >= 4),
        ("C10b: dual_diameter >= 5",            lambda r: r['dual_diameter'] >= 5),
        ("C11: not biradical",                  lambda r: r['is_biradical'] == 0),
        ("C12: adj_entropy >= 0.8",             lambda r: r['adj_entropy'] >= 0.8),
        ("C13: n_triple_junction <= 1",         lambda r: r['n_triple_junction'] <= 1),
        ("C14: max_dual_deg <= 3",              lambda r: r['max_dual_deg'] <= 3),
        # Combinaisons promising
        ("C5+C7: same==0 ET adj_57>=1",         lambda r: r['adj_55']+r['adj_77']==0 and r['adj_57']>=1),
        ("C5+C9: same==0 ET n_kekule>=3",       lambda r: r['adj_55']+r['adj_77']==0 and r['n_kekule']>=3),
        ("C5+C11: same==0 ET not biradical",    lambda r: r['adj_55']+r['adj_77']==0 and r['is_biradical']==0),
        ("C4+C8: adj_77==0 ET n_sum<=4",        lambda r: r['adj_77']==0 and r['n_sum']<=4),
        ("C4+C9+C11: adj_77==0 ET Kekule>=3 ET not bir", lambda r: r['adj_77']==0 and r['n_kekule']>=3 and r['is_biradical']==0),
        # Hypotheses originales testees ensemble
        ("C9+C10+C11: Kekule>=3 ET diam>=4 ET not bir", lambda r: r['n_kekule']>=3 and r['dual_diameter']>=4 and r['is_biradical']==0),
        # Approximations C2/C3 reels
        ("Approx C2: adj_57>=1 ET pent_boundary>=1",    lambda r: r['adj_57']>=1 and r['pent_on_boundary']>=1),
        ("Approx C3: adj_77==0 ET pent_boundary>=1 ET adj_57>=1", lambda r: r['adj_77']==0 and r['pent_on_boundary']>=1 and r['adj_57']>=1),
    ]

    results = []
    for name, pred in configs:
        res = evaluate_config(rows, pred, name)
        if res:
            results.append(res)

    # Sort by %PLAN descending
    results.sort(key=lambda r: -r['%PLAN'])

    print("=== Configs virtuelles classees par %PLAN (top) ===")
    print(f"  {'Config':<55} {'N':>10} {'N_plan':>10} {'%PLAN':>8} {'sel%':>7} {'gain_pts':>10}")
    for r in results:
        print(f"  {r['name']:<55} {r['N']:>10} {r['N_plan']:>10} {r['%PLAN']:>7.2f}% {100*r['selectivity']:>6.1f}% {r['gain_pts']:>+9.2f}")

    # Pareto frontier purity vs quantity
    print()
    print("=== Frontière de Pareto (purity vs N_filtered) ===")
    print("Configs DOMINANTES (aucune autre n'a >=pureté ET >=quantité) :")
    sorted_by_N = sorted(results, key=lambda r: -r['N'])
    pareto = []
    best_pct_so_far = 0
    for r in sorted_by_N:  # parcours par N decroissant
        if r['%PLAN'] > best_pct_so_far:
            pareto.append(r)
            best_pct_so_far = r['%PLAN']
    print(f"  {'Config':<55} {'N':>10} {'%PLAN':>8}")
    for r in pareto:
        print(f"  {r['name']:<55} {r['N']:>10} {r['%PLAN']:>7.2f}%")

    print()
    print("=== Référence : configs C2/C3 reelles (h8) ===")
    print("  C1 reel: 64746/112800 = 57.40% PLAN sur 112800 sols")
    print("  C2 reel:  2701/3292  = 82.05% PLAN sur 3292 sols")
    print("  C3 reel:   498/512   = 97.27% PLAN sur 512 sols")

    print()
    print("=== Score combine (purity x log(N)) ===")
    print("Maximise %PLAN x log10(N) pour balancer pureté/quantité :")
    for r in results:
        r['score'] = r['%PLAN'] * math.log10(max(r['N'], 1))
    results.sort(key=lambda r: -r['score'])
    print(f"  {'Config':<55} {'N':>10} {'%PLAN':>8} {'score':>8}")
    for r in results[:10]:
        print(f"  {r['name']:<55} {r['N']:>10} {r['%PLAN']:>7.2f}% {r['score']:>7.2f}")


if __name__ == "__main__":
    main()
