"""
Lance test.py sur tous les .graph d'un dossier.

Usage:
    python batch_test.py <dossier>

Exemple:
    python batch_test.py plane/benzdb/h4
"""

import sys
import subprocess
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_test.py <dossier>")
        sys.exit(1)

    dossier = Path(sys.argv[1])
    test_py = Path(__file__).parent.parent / "test.py"

    if not dossier.is_dir():
        print(f"ERREUR : {dossier} n'est pas un dossier.")
        sys.exit(1)

    graphs = sorted(dossier.glob("*.graph"))
    if not graphs:
        print(f"Aucun fichier .graph dans {dossier}")
        sys.exit(1)

    print(f"=== Batch test.py sur {dossier} ({len(graphs)} fichiers) ===")
    print()

    for i, graph_file in enumerate(graphs, 1):
        print(f"--- [{i}/{len(graphs)}] {graph_file.name} ---")
        cmd = [sys.executable, str(test_py), str(graph_file)]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  ECHEC (code {result.returncode})")
        print()

    print(f"=== Termine : {len(graphs)} fichiers traites ===")


if __name__ == "__main__":
    main()
