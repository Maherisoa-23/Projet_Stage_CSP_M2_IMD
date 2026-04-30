"""
Point d'entree du solveur CSP pour les non-benzenoides.

Usage:
    python main.py <fichier.graph> [--all] [--count] [--validate]

Options:
    --all      : enumerer toutes les solutions (defaut)
    --count    : afficher seulement le nombre de solutions
    --validate : valider les solutions avec xTB + test planarite
"""

import sys
import os
from pathlib import Path

# Sauvegarder nos arguments AVANT d'importer pycsp3,
# car pycsp3 intercepte sys.argv a l'import.
_own_argv = sys.argv[:]
filepath = _own_argv[1] if len(_own_argv) >= 2 else None
count_only = "--count" in _own_argv
do_validate = "--validate" in _own_argv
no_freeze = "--no-freeze" in _own_argv
adj_57 = "--adj-57" in _own_argv
no_table = "--no-table" in _own_argv
enumerate_all = "--all" in _own_argv or not count_only
output_dir = None
if "--output-dir" in _own_argv:
    idx = _own_argv.index("--output-dir")
    if idx + 1 < len(_own_argv):
        output_dir = _own_argv[idx + 1]
n_runs = 1
if "--n-runs" in _own_argv:
    idx = _own_argv.index("--n-runs")
    if idx + 1 < len(_own_argv):
        try:
            n_runs = max(1, int(_own_argv[idx + 1]))
        except ValueError:
            n_runs = 1
# Strategy de validation. Defaut "multi-runs" = comportement historique.
# Voir utils.validation.list_strategies() pour les valeurs acceptees.
method = "multi-runs"
if "--method" in _own_argv:
    idx = _own_argv.index("--method")
    if idx + 1 < len(_own_argv):
        method = _own_argv[idx + 1]

# Nettoyer sys.argv pour que pycsp3 ne les intercepte pas
sys.argv = [_own_argv[0]]

# Ajouter le dossier csp_solver/ au path pour les imports
sys.path.insert(0, str(Path(__file__).parent))

from utils.parser import parse
from utils.preprocessing import preprocess
from utils.model import build_and_solve, format_solution


def main():
    if filepath is None:
        print("Usage: python main.py <fichier.graph> [options]")
        print("  --all         : enumerer toutes les solutions (defaut)")
        print("  --count       : afficher seulement le nombre de solutions")
        print("  --validate    : valider les solutions avec xTB + test planarite")
        print("  --no-freeze   : desactiver la contrainte des hexagones geles (b(v)>=2)")
        print("  --no-table    : desactiver la contrainte de table de voisinage (C3)")
        print("  --adj-57      : activer la contrainte d'adjacence 5-7 (C5)")
        print("  --n-runs N    : nombre d'optimisations xTB par solution (defaut 1)")
        print("  --method M    : strategy de validation (defaut 'multi-runs')")
        print("                  voir utils/validation/ pour les strategies disponibles")
        print("Exemple: python main.py data/first.graph --validate --n-runs 10")
        sys.exit(1)

    # --- Etape 1 : Lecture du fichier Benzai ---
    print(f"=== Lecture de {filepath} ===")
    graph = parse(filepath)
    print(graph.summary())
    print()

    # --- Etape 2 : Pre-traitement ---
    print("=== Pre-traitement ===")
    preprocessed = preprocess(graph, freeze_b2=not no_freeze)
    if no_freeze:
        print("  (contrainte b(v)>=2 DESACTIVEE, seuls les deg=6 sont geles)")

    frozen = preprocessed['frozen']
    free = preprocessed['free']
    generators = preprocessed['generators']

    print(f"Hexagones geles: {len(frozen)} {frozen}")
    print(f"Hexagones libres: {len(free)} {free}")
    print(f"Generateurs Aut(G_D): {len(generators)}")
    for i, gen in enumerate(generators):
        mapping = ", ".join(f"v{k}->v{v}" for k, v in sorted(gen.items()) if k != v)
        print(f"  pi_{i+1}: {mapping}")

    tables_info = preprocessed['tables']
    for v, t in tables_info.items():
        print(f"  Table v{v}: {len(t)} entrees admissibles")
    print()

    # --- Etape 3 : Resolution ---
    print("=== Resolution CSP ===")
    if adj_57:
        print("  Contrainte C5 (adjacence 5-7) : ACTIVEE")
    if no_table:
        print("  Contrainte C3 (table voisinage) : DESACTIVEE")
    solutions = build_and_solve(graph, preprocessed, enumerate_all=enumerate_all,
                                adj_57=adj_57, no_table=no_table)

    if not solutions:
        print("Aucune solution trouvee.")
        return

    print(f"Nombre de solutions: {len(solutions)}")
    print()

    if not count_only:
        # --- Etape 4 : Affichage ---
        print("=== Solutions ===")
        for i, sol in enumerate(solutions, 1):
            print(format_solution(sol, i))

        # Resume
        print()
        print("=== Resume ===")
        print(f"Source: {filepath} (h={graph.h}, |E_D|={graph.dual.number_of_edges()})")
        print(f"Solutions distinctes (apres rupture de symetrie): {len(solutions)}")

        # Statistiques sur les solutions
        counts = {5: 0, 6: 0, 7: 0}
        for sol in solutions:
            for v, size in sol.items():
                counts[size] += 1
        total = len(solutions) * graph.h
        print(f"Repartition des tailles sur toutes les solutions:")
        for size in (5, 6, 7):
            pct = 100 * counts[size] / total if total > 0 else 0
            print(f"  Taille {size}: {counts[size]} ({pct:.1f}%)")

    # --- Etape 5 (optionnelle) : Validation xTB ---
    if do_validate and solutions:
        print()
        print("=== Validation xTB + planarite ===")
        from reconstruction import reconstruct_and_validate
        reconstruct_and_validate(graph, solutions, output_dir=output_dir,
                                 n_runs=n_runs, method=method)


if __name__ == "__main__":
    main()
