"""
Lance batch_main.py --validate pour toutes les combinaisons de contraintes.

Usage (depuis csp_solver/experiments/) :
    python batch_all.py <dossier>

Exemple:
    python batch_all.py plane/benzdb/h3
    python batch_all.py plane/benzdb/h4
"""

import sys
import subprocess
from itertools import combinations
from pathlib import Path

CSP_FLAGS = ["--no-freeze", "--no-table", "--adj-57"]


def all_combinations():
    """Genere toutes les combinaisons possibles (2^3 = 8)."""
    combos = [()]  # default (aucun flag)
    for r in range(1, len(CSP_FLAGS) + 1):
        combos.extend(combinations(CSP_FLAGS, r))
    return combos


def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_all.py <dossier>")
        print("Exemple: python batch_all.py plane/benzdb/h3")
        sys.exit(1)

    dossier = sys.argv[1]
    batch_main = Path(__file__).parent / "batch_main.py"
    combos = all_combinations()

    print(f"=== Batch ALL : {len(combos)} configurations sur {dossier} ===\n")

    for i, flags in enumerate(combos, 1):
        name = " ".join(flags) if flags else "(default)"
        print(f"===== [{i}/{len(combos)}] {name} =====\n")
        cmd = [sys.executable, str(batch_main), dossier, "--validate"] + list(flags)
        subprocess.run(cmd)
        print()

    print(f"=== Termine : {len(combos)} configurations traitees ===")


if __name__ == "__main__":
    main()
