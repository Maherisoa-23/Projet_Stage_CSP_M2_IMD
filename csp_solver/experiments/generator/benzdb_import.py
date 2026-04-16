"""
Import de benzenoides depuis la base de donnees BenzDB.

BenzDB (these Varet 2022, sec. 6.2) contient tous les benzenoides h<=9.
API REST : https://benzenoids.lis-lab.fr/

Requetes :
  - GET  /find_all_benzenoids  → tous les benzenoides
  - POST /find_benzenoids/     → filtre JSON

Chaque benzenoide retourne contient :
  - graphFile : contenu au format .graph
  - label     : identifiant interne BenzAI (ex: "0-1-6-7-12")
  - nbHexagons, nbCarbons, nbHydrogens, irregularity, inchi
"""

import json
import time
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

BENZDB_BASE_URL = "https://benzenoids.lis-lab.fr"


def fetch_benzenoids(nb_hexagons=None, nb_carbons=None, nb_hydrogens=None,
                     irregularity=None, timeout=120):
    """
    Interroge BenzDB et retourne la liste des benzenoides correspondants.

    Args:
        nb_hexagons: str filtre, ex "= 5", "<= 7"
        nb_carbons: str filtre, ex "<= 20"
        nb_hydrogens: str filtre, ex "<> 12"
        irregularity: str filtre, ex ">= 0.5"
        timeout: timeout HTTP en secondes

    Returns:
        liste de dicts avec les champs BenzDB
    """
    if not HAS_REQUESTS:
        raise ImportError(
            "Le module 'requests' est necessaire. "
            "Installer avec : pip install requests"
        )

    payload = {
        "idBenzenoid": "",
        "label": "",
        "inchi": "",
        "nbHexagons": nb_hexagons or "",
        "nbCarbons": nb_carbons or "",
        "nbHydrogens": nb_hydrogens or "",
        "irregularity": irregularity or "",
    }

    url = f"{BENZDB_BASE_URL}/find_benzenoids/"
    print(f"  Requete POST → {url}")
    print(f"  Filtres : {json.dumps(payload, indent=2)}")

    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()

    data = resp.json()
    print(f"  → {len(data)} benzenoide(s) recu(s)")
    return data


def save_benzdb_to_graph_files(benzenoids, output_dir):
    """
    Sauvegarde les benzenoides BenzDB en fichiers .graph locaux.

    Args:
        benzenoids: liste de dicts retournes par fetch_benzenoids
        output_dir: dossier de sortie

    Returns:
        nombre de fichiers ecrits
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for benz in benzenoids:
        graph_content = benz.get("graphFile", "")
        label = benz.get("label", f"id_{benz.get('idBenzenoid', count)}")

        if not graph_content:
            print(f"  SKIP {label} : pas de graphFile")
            continue

        # Nom de fichier : label avec / remplace par _
        safe_label = label.replace("/", "_").replace("\\", "_")
        filepath = output_dir / f"{safe_label}.graph"

        with open(filepath, 'w') as f:
            f.write(graph_content)

        count += 1

    return count


def import_benzdb_by_hexagons(h_min=1, h_max=9, base_dir="benzenoids/benzdb"):
    """
    Importe tous les benzenoides de BenzDB organises par nombre d'hexagones.

    Args:
        h_min, h_max: bornes du nombre d'hexagones
        base_dir: dossier racine de sortie

    Returns:
        dict {h: nb_fichiers}
    """
    results = {}

    for h in range(h_min, h_max + 1):
        print(f"\n=== Import h={h} ===")
        output_dir = Path(base_dir) / f"h{h}"

        try:
            data = fetch_benzenoids(nb_hexagons=f"= {h}")
            n = save_benzdb_to_graph_files(data, output_dir)
            results[h] = n
            print(f"  → {n} fichiers .graph ecrits dans {output_dir}")
        except Exception as e:
            print(f"  ERREUR: {e}")
            results[h] = -1

        # Pause entre requetes pour ne pas surcharger le serveur
        if h < h_max:
            time.sleep(1)

    return results


if __name__ == "__main__":
    import sys

    if not HAS_REQUESTS:
        print("ERREUR: pip install requests")
        sys.exit(1)

    # Par defaut : importer h=3..5 (petit ensemble pour tester)
    h_max = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    base = Path(__file__).parent.parent / "benzenoids" / "benzdb"

    print(f"Import BenzDB h=1..{h_max} → {base}")
    results = import_benzdb_by_hexagons(1, h_max, str(base))

    print("\n=== Resume ===")
    total = 0
    for h, n in sorted(results.items()):
        status = f"{n} fichiers" if n >= 0 else "ERREUR"
        print(f"  h={h}: {status}")
        if n > 0:
            total += n
    print(f"  Total: {total} fichiers")
