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
    output_base = Path(__file__).parent / "output"

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
        # output/h4/0-5-6-11/solutions/
        out_dir = output_base / dossier.name / graph_file.stem / "solutions"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(main_py), str(graph_file),
               "--output-dir", str(out_dir)] + extra_args
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"  ECHEC (code {result.returncode})")
        print()

    print(f"=== Termine : {len(graphs)} fichiers traites ===")

    # Generer le rapport si --validate
    if "--validate" in extra_args:
        h_dir = output_base / dossier.name
        view_py = Path(__file__).parent / "view.py"
        print(f"\n=== Generation du rapport ===")
        subprocess.run([sys.executable, str(view_py), str(h_dir)])


if __name__ == "__main__":
    main()
