"""
Chargement et gestion de la table de voisinage T(n).

La table T(n) contient les configurations locales admissibles (planes)
pour un cycle central de taille n ∈ {5, 6, 7}. Chaque entrée est un
tuple de longueur n, où chaque position vaut 0 (arête libre) ou 5/6/7
(taille du cycle voisin).

Source : rapport_planarite.txt (section STRUCTURES PLANES).
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
TABLE_PATH = DATA_DIR / "table_voisinage.json"


def extract_from_rapport(rapport_path: str) -> dict:
    """Parse le rapport de planarité et extrait les séquences planes.

    Returns:
        dict avec clés "5", "6", "7", chacune contenant une liste de tuples.
    """
    table = {"5": [], "6": [], "7": []}
    in_planes = False

    with open(rapport_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()

            # Début de la section planes
            if "STRUCTURES PLANES" in stripped:
                in_planes = True
                continue

            # Fin de la section planes
            if "STRUCTURES NON PLANES" in stripped:
                break

            if not in_planes:
                continue

            # Ignorer les lignes de séparation et d'en-tête
            if stripped.startswith("-") or stripped.startswith("Sequence") or not stripped:
                continue

            # Parser une ligne de données :
            # 7_6_5_0_0                          5   17      0.00 ...
            parts = stripped.split()
            if len(parts) < 2:
                continue

            sequence_str = parts[0]
            cycle_str = parts[1]

            # Vérifier que c'est bien une ligne de données
            if cycle_str not in ("5", "6", "7"):
                continue

            # Convertir la séquence
            sequence = tuple(int(x) for x in sequence_str.split("_"))

            # Vérifier la cohérence : la longueur de la séquence doit
            # correspondre à la taille du cycle central
            if len(sequence) != int(cycle_str):
                continue

            table[cycle_str].append(list(sequence))

    return table


def build_table(rapport_path: str) -> None:
    """Extrait T(n) du rapport et sauvegarde en JSON."""
    table = extract_from_rapport(rapport_path)

    print(f"Table extraite :")
    for n in ("5", "6", "7"):
        print(f"  T({n}) : {len(table[n])} entrées")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TABLE_PATH, "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)

    print(f"Sauvegardé dans {TABLE_PATH}")


def load_table() -> dict:
    """Charge la table T(n) depuis le fichier JSON.

    Returns:
        dict {5: [list of tuples], 6: [...], 7: [...]}
    """
    with open(TABLE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return {
        int(k): [tuple(seq) for seq in v]
        for k, v in raw.items()
    }


# --- Point d'entrée pour l'extraction one-shot ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python table.py <chemin_rapport_planarite.txt>")
        sys.exit(1)
    rapport = sys.argv[1]

    build_table(rapport)
