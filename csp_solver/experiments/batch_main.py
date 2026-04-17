"""
Lance main.py sur tous les .graph d'un dossier.

Usage:
    python batch_main.py <dossier> [options main.py...]

Exemple:
    python batch_main.py plane/benzdb/h4
    python batch_main.py plane/benzdb/h4 --no-freeze
    python batch_main.py plane/benzdb/h4 --validate
    python batch_main.py plane/benzdb/h4 --count
"""

import sys
import subprocess
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python batch_main.py <dossier> [options main.py...]")
        sys.exit(1)

    dossier = Path(sys.argv[1])
    extra_args = sys.argv[2:]
    main_py = Path(__file__).parent.parent / "main.py"

    if not dossier.is_dir():
        print(f"ERREUR : {dossier} n'est pas un dossier.")
        sys.exit(1)

    graphs = sorted(dossier.glob("*.graph"))
    if not graphs:
        print(f"Aucun fichier .graph dans {dossier}")
        sys.exit(1)

    print(f"=== Batch main.py sur {dossier} ({len(graphs)} fichiers) ===")
    print(f"Options: {extra_args if extra_args else '(aucune)'}")
    print()

    for i, graph_file in enumerate(graphs, 1):
        print(f"--- [{i}/{len(graphs)}] {graph_file.name} ---")
        cmd = [sys.executable, str(main_py), str(graph_file)] + extra_args
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  ECHEC (code {result.returncode})")
        print()

    print(f"=== Termine : {len(graphs)} fichiers traites ===")


if __name__ == "__main__":
    main()
