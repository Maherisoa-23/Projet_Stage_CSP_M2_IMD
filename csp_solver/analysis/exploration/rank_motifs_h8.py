"""Classe les motifs de bord par discriminance plan/non-plan sur h8 C1.

Lit tmp/motifs_h8_{w4,w5}.csv et calcule :
  - %PLAN par motif (P(plan | motif present dans la sol))
  - delta_pp = %PLAN_motif - baseline (60.08% sur h8 C1)
  - chi2 (significativite vs distribution de reference)
  - score = |delta_pp| * sqrt(n_total) (favorise effets forts ET frequents)

Sort 2 tableaux pour w4 et w5 :
  - Top 15 motifs FAVORISANT la planarite (delta > 0)
  - Top 15 motifs DEFAVORISANT (delta < 0)

Filtre les motifs trop rares (n_total < 1000) pour eviter les outliers.
"""

import csv
import math
import sys


BASELINE = 60.08  # %PLAN h8 C1 done


def chi2(n_plan, n_nonplan, baseline_pct):
    """Test khi-deux a 1ddl : observe (n_plan, n_nonplan) vs attendu si
    baseline. Retourne chi2 (plus c'est grand, plus c'est significatif).
    """
    n = n_plan + n_nonplan
    if n == 0:
        return 0.0
    p = baseline_pct / 100
    exp_plan = n * p
    exp_nonplan = n * (1 - p)
    if exp_plan == 0 or exp_nonplan == 0:
        return 0.0
    return ((n_plan - exp_plan) ** 2 / exp_plan +
            (n_nonplan - exp_nonplan) ** 2 / exp_nonplan)


def load_motifs(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            r["n_total"] = int(r["n_total"])
            r["n_plan"] = int(r["n_plan"])
            r["n_nonplan"] = int(r["n_nonplan"])
            r["pct_plan"] = float(r["pct_plan"])
            r["delta_pp"] = float(r["delta_pp"])
            r["chi2"] = chi2(r["n_plan"], r["n_nonplan"], BASELINE)
            r["score"] = abs(r["delta_pp"]) * math.sqrt(r["n_total"])
            rows.append(r)
    return rows


def show_top(rows, title, sense, n=15, min_n=1000):
    """sense = +1 (favoritise plan) ou -1 (defavorise)."""
    filtered = [r for r in rows if r["n_total"] >= min_n]
    filtered = [r for r in filtered if (sense * r["delta_pp"]) > 0]
    filtered.sort(key=lambda r: -r["score"])
    print(f"\n=== {title} ===")
    print(f"  (filtre n_total >= {min_n}, classe par |delta| * sqrt(N))")
    print(f"  {'motif':<22} {'N':>8} {'%PLAN':>7} {'delta_pp':>10} {'chi2':>10} {'score':>8}")
    for r in filtered[:n]:
        print(f"  {r['motif']:<22} {r['n_total']:>8} {r['pct_plan']:>6.2f}% {r['delta_pp']:>+9.2f} {r['chi2']:>10.1f} {r['score']:>8.1f}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Baseline h8 C1 done : {BASELINE:.2f}% PLAN")

    for w, path in [(4, "tmp/motifs_h8_w4.csv"), (5, "tmp/motifs_h8_w5.csv")]:
        rows = load_motifs(path)
        print(f"\n\n{'#'*60}")
        print(f"# MOTIFS DE BORD - FENETRE LARGEUR {w}")
        print(f"# Total motifs distincts : {len(rows)}")
        print('#'*60)

        show_top(rows, f"TOP 15 motifs FAVORISANT la planarite (w={w})", +1)
        show_top(rows, f"TOP 15 motifs DEFAVORISANT la planarite (w={w})", -1)


if __name__ == "__main__":
    main()
