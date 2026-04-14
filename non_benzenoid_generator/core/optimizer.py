"""Optimisation geometrique MMFF94 via Open Babel (subprocess)

Prend un fichier CML en entree, lance `obabel --minimize --ff MMFF94`,
et produit un fichier CML optimise. MMFF94 uniquement — pas de fallback UFF.
"""

import subprocess
from pathlib import Path
from typing import Tuple, List


def optimize_cml(input_cml: str, output_cml: str,
                 forcefield: str = "mmff94",
                 steps: int = 500) -> Tuple[bool, str]:
    """
    Optimise une structure CML avec Open Babel et MMFF94.

    Retourne (succes: bool, message: str).
    Erreur fatale si obabel n'est pas installe (verifier avant d'appeler).
    """
    cmd = [
        "obabel",
        str(input_cml),
        "-O", str(output_cml),
        "--minimize",
        "--steps", str(steps),
        "--ff", forcefield,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return False, f"Timeout apres 120s pour {input_cml}"

    out_path = Path(output_cml)
    if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
        return True, f"OK ({forcefield}, {steps} steps)"

    return False, result.stderr.strip() if result.stderr else "Fichier de sortie vide"


def read_coords_from_cml(cml_path: str) -> List[List[float]]:
    """
    Lit les coordonnees 3D de tous les atomes depuis un fichier CML.
    Retourne une liste de [x, y, z].
    """
    import xml.etree.ElementTree as ET

    tree = ET.parse(cml_path)
    root = tree.getroot()

    coords = []
    # Gerer le namespace CML si present
    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    for atom in root.iter(f'{ns}atom'):
        x = float(atom.get('x3', 0))
        y = float(atom.get('y3', 0))
        z = float(atom.get('z3', 0))
        coords.append([x, y, z])

    return coords
