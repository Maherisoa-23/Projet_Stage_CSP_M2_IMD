"""
Analyse des resultats d'experimentation.

Lit les CSV de resultats et produit :
  - Resume par categorie (moyennes, medianes, min/max)
  - Correlations entre proprietes et planarite
  - Comparaisons inter-categories
  - Export LaTeX (tableaux formattes)

Usage :
    python analyze.py [--structural] [--csp] [--validation] [--latex]
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import STRUCTURAL_CSV, CSP_RESULTS_CSV, VALIDATION_CSV


def load_csv(filepath):
    """Charge un CSV en liste de dicts."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  Fichier introuvable: {filepath}")
        return []
    with open(filepath, 'r') as f:
        return list(csv.DictReader(f))


def summarize_structural():
    """Resume des proprietes structurelles par categorie."""
    rows = load_csv(STRUCTURAL_CSV)
    if not rows:
        return

    by_category = defaultdict(list)
    for r in rows:
        by_category[r.get("category", "unknown")].append(r)

    print("\n=== Resume structurel par categorie ===")
    print(f"{'Categorie':<20} {'Nb':>5} {'h min':>6} {'h max':>6} "
          f"{'% geles':>8} {'% internes':>10}")
    print("-" * 60)

    for cat, items in sorted(by_category.items()):
        hs = [int(r["h"]) for r in items]
        frozen_ratios = [float(r.get("frozen_ratio", 0)) for r in items]
        internals = [int(r.get("n_internal", 0)) for r in items]
        h_vals = [int(r["h"]) for r in items]
        pct_internal = [100 * i / h if h > 0 else 0
                        for i, h in zip(internals, h_vals)]

        print(f"{cat:<20} {len(items):>5} {min(hs):>6} {max(hs):>6} "
              f"{100*sum(frozen_ratios)/len(frozen_ratios):>7.1f}% "
              f"{sum(pct_internal)/len(pct_internal):>9.1f}%")


def summarize_csp():
    """Resume des resultats CSP par fichier."""
    rows = load_csv(CSP_RESULTS_CSV)
    if not rows:
        return

    print("\n=== Resume CSP ===")
    print(f"{'Fichier':<40} {'h':>3} {'Mode':>10} {'Sol':>5} {'Temps':>7} "
          f"{'%5':>5} {'%6':>5} {'%7':>5}")
    print("-" * 85)

    for r in rows:
        fname = Path(r["file"]).name
        print(f"{fname:<40} {r['h']:>3} {r.get('freeze_mode',''):>10} "
              f"{r['n_solutions']:>5} {r['solve_time']:>7} "
              f"{r.get('pct_5',''):>5} {r.get('pct_6',''):>5} "
              f"{r.get('pct_7',''):>5}")


def summarize_validation():
    """Resume de la validation xTB."""
    rows = load_csv(VALIDATION_CSV)
    if not rows:
        return

    by_file = defaultdict(list)
    for r in rows:
        by_file[r["file"]].append(r)

    print("\n=== Resume validation ===")
    print(f"{'Fichier':<40} {'Total':>6} {'Planes':>7} {'Taux':>7}")
    print("-" * 65)

    for f, items in sorted(by_file.items()):
        fname = Path(f).name
        total = len(items)
        planar = sum(1 for r in items if r.get("is_planar") == "True")
        pct = 100 * planar / total if total > 0 else 0
        print(f"{fname:<40} {total:>6} {planar:>7} {pct:>6.1f}%")


if __name__ == "__main__":
    print("=== Analyse des resultats ===")
    summarize_structural()
    summarize_csp()
    summarize_validation()
