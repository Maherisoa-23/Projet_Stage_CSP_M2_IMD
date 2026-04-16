"""
Generation de graphiques pour les resultats d'experimentation.

Graphiques produits (matplotlib, export PDF) :
  1. h vs nb_solutions — par categorie
  2. h vs taux_planarite
  3. Heatmap categorie x taille
  4. Distribution des angles max
  5. frozen_ratio vs taux_planarite
  6. Diagramme nb_pentagones vs nb_heptagones

Usage :
    python plots.py [--output-dir DIR]
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import STRUCTURAL_CSV, CSP_RESULTS_CSV, VALIDATION_CSV, DOCS_DIR

try:
    import matplotlib
    matplotlib.use('Agg')  # backend non-interactif
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("ATTENTION: matplotlib non installe, pas de graphiques")


def load_csv(filepath):
    """Charge un CSV en liste de dicts."""
    filepath = Path(filepath)
    if not filepath.exists():
        return []
    with open(filepath, 'r') as f:
        return list(csv.DictReader(f))


def plot_solutions_vs_h(output_dir):
    """Plot 1 : nombre de solutions en fonction de h, colore par categorie."""
    if not HAS_MPL:
        return

    rows = load_csv(CSP_RESULTS_CSV)
    if not rows:
        print("  Pas de donnees CSP pour le plot solutions vs h")
        return

    by_cat = defaultdict(lambda: ([], []))
    for r in rows:
        cat = Path(r["file"]).parent.name
        by_cat[cat][0].append(int(r["h"]))
        by_cat[cat][1].append(int(r["n_solutions"]))

    fig, ax = plt.subplots(figsize=(10, 6))
    for cat, (hs, sols) in sorted(by_cat.items()):
        ax.scatter(hs, sols, label=cat, alpha=0.7)

    ax.set_xlabel("Nombre d'hexagones (h)")
    ax.set_ylabel("Nombre de solutions CSP")
    ax.set_title("Solutions CSP en fonction de la taille")
    ax.legend()
    ax.set_yscale('log')

    out = Path(output_dir) / "solutions_vs_h.pdf"
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print(f"  → {out}")


def plot_planarity_vs_h(output_dir):
    """Plot 2 : taux de planarite en fonction de h."""
    if not HAS_MPL:
        return

    rows = load_csv(VALIDATION_CSV)
    if not rows:
        print("  Pas de donnees validation pour le plot planarite vs h")
        return

    # Grouper par fichier, calculer taux
    by_file = defaultdict(lambda: {"total": 0, "planar": 0})
    for r in rows:
        by_file[r["file"]]["total"] += 1
        if r.get("is_planar") == "True":
            by_file[r["file"]]["planar"] += 1

    # Recuperer h depuis structural
    struct_rows = load_csv(STRUCTURAL_CSV)
    file_to_h = {r["file"]: int(r["h"]) for r in struct_rows}

    hs, rates = [], []
    for f, stats in by_file.items():
        if f in file_to_h and stats["total"] > 0:
            hs.append(file_to_h[f])
            rates.append(100 * stats["planar"] / stats["total"])

    if not hs:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(hs, rates, alpha=0.7)
    ax.set_xlabel("Nombre d'hexagones (h)")
    ax.set_ylabel("Taux de planarite (%)")
    ax.set_title("Planarite des solutions CSP en fonction de la taille")
    ax.set_ylim(-5, 105)

    out = Path(output_dir) / "planarity_vs_h.pdf"
    fig.savefig(out, bbox_inches='tight')
    plt.close(fig)
    print(f"  → {out}")


if __name__ == "__main__":
    output_dir = DOCS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== Generation des graphiques ===")
    plot_solutions_vs_h(output_dir)
    plot_planarity_vs_h(output_dir)
    print("Termine.")
