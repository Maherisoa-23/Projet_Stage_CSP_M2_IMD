"""Compare les classements de motifs entre h7, h8, h9.

Produit :
  1. Un tableau cote-a-cote des top 10 fav / def w4 pour chaque h.
  2. Pour chaque motif, son rang dans chaque h (table de coherence).
  3. Coefficient de Spearman entre les classements (mesure d'accord global).
  4. Liste des motifs "universels" (top 10 dans h7 ET h8 ET h9).
  5. Liste des motifs "h-specifiques".

Sortie : tmp/motifs_universal_comparison.txt
"""

import csv
import math
import sys
from pathlib import Path


BASELINE = {7: 67.79, 8: 60.08, 9: 40.71}


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        r["n_total"] = int(r["n_total"])
        r["pct_plan"] = float(r["pct_plan"])
        r["delta_pp"] = float(r["delta_pp"])
        r["score"] = abs(r["delta_pp"]) * math.sqrt(r["n_total"])
    return rows


def top_n(rows, n=10, sense=+1, min_total=200):
    filt = [r for r in rows if r["n_total"] >= min_total and (sense * r["delta_pp"]) > 0]
    filt.sort(key=lambda r: -r["score"])
    return filt[:n]


def spearman(ranks_a, ranks_b):
    """Coefficient de Spearman entre deux dicts {motif: rank}."""
    common = set(ranks_a) & set(ranks_b)
    if len(common) < 2:
        return 0.0
    n = len(common)
    d2 = sum((ranks_a[m] - ranks_b[m]) ** 2 for m in common)
    return 1 - 6 * d2 / (n * (n*n - 1))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = []

    def p(s=""): out.append(s); print(s)

    rows = {h: {w: load(f"tmp/motifs_h{h}_w{w}.csv") for w in (4, 5)} for h in (7, 8, 9)}

    # -- Top 10 fav et def pour chaque h, w=4
    for w in (4, 5):
        p(f"\n{'#'*70}")
        p(f"# COMPARATIF TOP 10 - w={w}")
        p(f"# (Baseline h7={BASELINE[7]}%, h8={BASELINE[8]}%, h9={BASELINE[9]}%)")
        p(f"{'#'*70}\n")

        for label, sense in [("FAVORISANT", +1), ("DEFAVORISANT", -1)]:
            p(f"--- TOP 10 motifs {label} la planarite (w={w}) ---\n")
            tops = {h: top_n(rows[h][w], n=10, sense=sense) for h in (7, 8, 9)}
            p(f"  {'rank':<5} {'h7':<28} {'h8':<28} {'h9':<28}")
            p(f"  {'':5} {'motif    pct  delta':<28} {'motif    pct  delta':<28} {'motif    pct  delta':<28}")
            for i in range(10):
                line = f"  {i+1:<5} "
                for h in (7, 8, 9):
                    if i < len(tops[h]):
                        r = tops[h][i]
                        line += f"{r['motif']:<10} {r['pct_plan']:>5.1f}% {r['delta_pp']:>+6.1f}   "
                    else:
                        line += " " * 28
                p(line)
            p("")

    # -- Spearman global entre les classements (par delta_pp)
    p(f"\n{'#'*70}")
    p(f"# ACCORD ENTRE CLASSEMENTS (Spearman, sur tous motifs n>=200)")
    p(f"{'#'*70}\n")

    for w in (4, 5):
        # Rang : 1 = plus FAVorisant, ... 45 = plus DEFavorisant. Trie par delta_pp desc.
        ranks = {}
        for h in (7, 8, 9):
            sorted_rows = sorted(
                (r for r in rows[h][w] if r["n_total"] >= 200),
                key=lambda r: -r["delta_pp"],
            )
            ranks[h] = {r["motif"]: i+1 for i, r in enumerate(sorted_rows)}
        s78 = spearman(ranks[7], ranks[8])
        s89 = spearman(ranks[8], ranks[9])
        s79 = spearman(ranks[7], ranks[9])
        p(f"w={w} : Spearman h7-h8 = {s78:.3f}, h8-h9 = {s89:.3f}, h7-h9 = {s79:.3f}")

    # -- Motifs universels : top 10 (favorisant OU defavorisant) dans 7 ET 8 ET 9
    p(f"\n{'#'*70}")
    p(f"# MOTIFS UNIVERSELS (top 10 |delta| dans h7 ET h8 ET h9)")
    p(f"{'#'*70}\n")

    def top_signed_set(h, w, n=10):
        # On combine fav + def : top 10 par |delta| * sqrt(N)
        rs = [r for r in rows[h][w] if r["n_total"] >= 200]
        rs.sort(key=lambda r: -r["score"])
        return {r["motif"] for r in rs[:n]}

    for w in (4, 5):
        s7 = top_signed_set(7, w, 10)
        s8 = top_signed_set(8, w, 10)
        s9 = top_signed_set(9, w, 10)
        univ = s7 & s8 & s9
        p(f"\nw={w} : {len(univ)} motifs presents dans le top 10 des 3 tailles")
        for m in sorted(univ):
            # Donne le delta dans chaque h
            deltas = []
            for h in (7, 8, 9):
                for r in rows[h][w]:
                    if r["motif"] == m:
                        deltas.append(f"h{h}:{r['delta_pp']:+.1f}")
                        break
            p(f"  {m:<12} {'  '.join(deltas)}")

        # Motifs h-specifiques (dans 1 seul top)
        only7 = s7 - s8 - s9
        only8 = s8 - s7 - s9
        only9 = s9 - s7 - s8
        p(f"\n  Specifiques :")
        p(f"    h7 only : {sorted(only7)}")
        p(f"    h8 only : {sorted(only8)}")
        p(f"    h9 only : {sorted(only9)}")

    # -- Comparaison directe : pour 5 motifs phares, leur evolution
    p(f"\n{'#'*70}")
    p(f"# EVOLUTION DES MOTIFS PHARES (h7 -> h8 -> h9)")
    p(f"{'#'*70}\n")

    phares_w4 = ["7-7-7-7", "5-5-5-5", "5-7-7-7", "5-5-7-7", "6-6-6-6",
                 "6-6-6-7", "5-6-6-6", "5-7-6-6"]
    phares_w5 = ["7-7-7-7-7", "5-5-5-5-5", "6-6-6-6-7", "5-6-6-6-6",
                 "5-7-7-7-7", "5-7-7-7-5"]

    for w, phares in [(4, phares_w4), (5, phares_w5)]:
        p(f"\n--- Motifs w={w} ---")
        p(f"  {'motif':<12} {'h7 pct/delta/N':<22} {'h8 pct/delta/N':<22} {'h9 pct/delta/N':<22}")
        for m in phares:
            line = f"  {m:<12} "
            for h in (7, 8, 9):
                found = next((r for r in rows[h][w] if r["motif"] == m), None)
                if found:
                    line += f"{found['pct_plan']:>5.1f}/{found['delta_pp']:>+5.1f}/{found['n_total']:>6d}    "
                else:
                    line += " "*22
            p(line)

    # Ecrire fichier
    Path("tmp/motifs_universal_comparison.txt").write_text("\n".join(out), encoding="utf-8")
    p(f"\n=> Ecrit tmp/motifs_universal_comparison.txt")


if __name__ == "__main__":
    main()
