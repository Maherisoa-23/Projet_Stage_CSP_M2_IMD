"""Analyse v2 h8 C1 : tableaux croisés + decision rules composites."""

import csv
from collections import defaultdict


def main():
    with open('tmp/h8_c1_features.csv') as f:
        reader = csv.DictReader(f)
        feats = list(reader)
    print(f"Loaded {len(feats)} features")

    # Convert numerics
    for f in feats:
        for k in ('n_pent','n_hept','n_hex','n_diff','n_sum',
                  'adj_55','adj_57','adj_77','adj_56','adj_67','adj_66',
                  'pent_on_boundary','hept_on_boundary'):
            f[k] = int(f[k])
        for k in ('energy_eh','homo_lumo_ev','angle_deg'):
            try: f[k] = float(f[k]) if f[k] != '' else None
            except: f[k] = None

    plan = [f for f in feats if f['verdict'] == 'PLAN']
    non_plan = [f for f in feats if f['verdict'] != 'PLAN']
    total = len(feats)
    print(f"PLAN: {len(plan)} ({100*len(plan)/total:.1f}%)  NON_PLAN: {len(non_plan)} ({100*len(non_plan)/total:.1f}%)")

    # === Tableau croisé n_sum x adj_77 ===
    print("\n=== Tableau croisé : %PLAN par (n_sum, adj_77) ===")
    cross = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in feats:
        k = (f['n_sum'], f['adj_77'])
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        cross[k][v] += 1

    n_sums = sorted(set(k[0] for k in cross.keys()))
    adj_77s = sorted(set(k[1] for k in cross.keys()))
    print(f"  {'n_sum\\adj_77':<14}", end='')
    for a in adj_77s:
        print(f"  adj77={a:<4}", end='')
    print()
    for ns in n_sums:
        print(f"  n_sum={ns:<8}", end='')
        for a in adj_77s:
            d = cross[(ns, a)]
            tot = d['plan'] + d['non_plan']
            if tot == 0:
                print(f"      -    ", end='')
            else:
                pct = 100*d['plan']/tot
                print(f"  {pct:>4.0f}%/{tot:<4d}", end='')
        print()

    # === Tableau croisé n_sum x (adj_55 + adj_77) ===
    print("\n=== Tableau croisé : %PLAN par (n_sum, adj_55 + adj_77) ===")
    cross = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in feats:
        k = (f['n_sum'], f['adj_55'] + f['adj_77'])
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        cross[k][v] += 1
    n_sums = sorted(set(k[0] for k in cross.keys()))
    adj_sames = sorted(set(k[1] for k in cross.keys()))
    print(f"  {'n_sum\\same':<14}", end='')
    for a in adj_sames:
        print(f"  same={a:<5}", end='')
    print()
    for ns in n_sums:
        print(f"  n_sum={ns:<8}", end='')
        for a in adj_sames:
            d = cross[(ns, a)]
            tot = d['plan'] + d['non_plan']
            if tot == 0:
                print(f"      -    ", end='')
            else:
                pct = 100*d['plan']/tot
                print(f"  {pct:>4.0f}%/{tot:<4d}", end='')
        print()

    # === Decision tree manuel (composite rules) ===
    print("\n=== Decision rules composites ===")

    def evaluate(name, predict_fn):
        """predict_fn(f) -> 'PLAN' ou 'NON_PLAN'. Calcule accuracy."""
        tp = fp = tn = fn = 0
        for f in feats:
            pred = predict_fn(f)
            actual = 'PLAN' if f['verdict'] == 'PLAN' else 'NON_PLAN'
            if pred == 'PLAN' and actual == 'PLAN': tp += 1
            elif pred == 'PLAN' and actual == 'NON_PLAN': fp += 1
            elif pred == 'NON_PLAN' and actual == 'PLAN': fn += 1
            else: tn += 1
        acc = (tp + tn) / (tp + fp + tn + fn)
        prec_plan = tp / (tp + fp) if tp+fp > 0 else 0
        rec_plan = tp / (tp + fn) if tp+fn > 0 else 0
        prec_np = tn / (tn + fn) if tn+fn > 0 else 0
        rec_np = tn / (tn + fp) if tn+fp > 0 else 0
        f1 = 2*prec_plan*rec_plan/(prec_plan+rec_plan) if prec_plan+rec_plan > 0 else 0
        print(f"  {name:<60} acc={acc:.3f}  F1_plan={f1:.3f}  P/R_plan={prec_plan:.3f}/{rec_plan:.3f}  P/R_nonp={prec_np:.3f}/{rec_np:.3f}")

    # baseline
    evaluate("BASELINE: always PLAN", lambda f: 'PLAN')

    # Single features
    evaluate("adj_77 == 0", lambda f: 'PLAN' if f['adj_77'] == 0 else 'NON_PLAN')
    evaluate("adj_77 + adj_55 == 0", lambda f: 'PLAN' if f['adj_77'] + f['adj_55'] == 0 else 'NON_PLAN')
    evaluate("n_sum <= 4", lambda f: 'PLAN' if f['n_sum'] <= 4 else 'NON_PLAN')

    # Combined
    evaluate("adj_77 == 0 AND adj_55 == 0", lambda f: 'PLAN' if f['adj_77'] == 0 and f['adj_55'] == 0 else 'NON_PLAN')
    evaluate("adj_77 == 0 AND n_sum <= 4", lambda f: 'PLAN' if f['adj_77'] == 0 and f['n_sum'] <= 4 else 'NON_PLAN')

    # Decision tree manual (3 levels)
    def tree1(f):
        if f['adj_77'] >= 3: return 'NON_PLAN'
        if f['adj_77'] + f['adj_55'] == 0:
            if f['n_sum'] <= 4: return 'PLAN'
            else: return 'PLAN' if f['n_sum'] <= 6 else 'NON_PLAN'
        if f['n_sum'] >= 8: return 'NON_PLAN'
        return 'PLAN'
    evaluate("TREE-1 (composite)", tree1)

    # Score continu (combinaison linéaire)
    def score_rule(f, threshold):
        # Score positif = défauts isolés = plus plan
        # Score négatif = défauts agglomérés = moins plan
        score = -2 * f['adj_77'] - f['adj_55'] - 0.5 * f['n_sum'] + 0.3 * f['adj_57']
        return 'PLAN' if score >= threshold else 'NON_PLAN'
    for th in [-4, -3, -2, -1, 0]:
        evaluate(f"SCORE: -2*adj77 -adj55 -0.5*n_sum +0.3*adj57 >= {th}",
                 lambda f, t=th: score_rule(f, t))

    # ===== Effet "défauts isolés" =====
    # adj_57 / (adj_55 + adj_77 + adj_57) = ratio "défauts bien alternés" / total adj entre défauts
    print("\n=== Ratio adjacences alternées vs même-type ===")
    by_ratio = defaultdict(lambda: {'plan': 0, 'non_plan': 0})
    for f in feats:
        tot_adj_def = f['adj_55'] + f['adj_77'] + f['adj_57']
        if tot_adj_def == 0:
            bucket = 'no_adj'
        else:
            r = f['adj_57'] / tot_adj_def
            if r >= 0.9: bucket = '>=0.9'
            elif r >= 0.7: bucket = '0.7-0.9'
            elif r >= 0.5: bucket = '0.5-0.7'
            elif r >= 0.3: bucket = '0.3-0.5'
            else: bucket = '<0.3'
        v = 'plan' if f['verdict'] == 'PLAN' else 'non_plan'
        by_ratio[bucket][v] += 1
    print(f"  {'bucket':<12} {'PLAN':>8} {'NONPLAN':>8} {'%PLAN':>8} {'N':>8}")
    for k in ['no_adj', '<0.3', '0.3-0.5', '0.5-0.7', '0.7-0.9', '>=0.9']:
        d = by_ratio.get(k, {'plan':0,'non_plan':0})
        tot = d['plan'] + d['non_plan']
        pct = 100*d['plan']/tot if tot > 0 else 0
        print(f"  {k:<12} {d['plan']:>8} {d['non_plan']:>8} {pct:>7.1f}% {tot:>8}")


if __name__ == "__main__":
    main()
