"""Optimisation geometrique MMFF94 via Open Babel (subprocess)

Strategie : convertir le CML en XYZ temporaire (format que obabel lit
sans probleme), optimiser le XYZ, puis relire les coordonnees optimisees.
Les fichiers CML restent intacts pour le solveur CSP.
"""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, List


def _cml_to_xyz(cml_path: str, xyz_path: str) -> int:
    """
    Convertit un fichier CML en XYZ en lisant directement le XML.
    Retourne le nombre d'atomes ecrits.
    """
    tree = ET.parse(cml_path)
    root = tree.getroot()

    atoms = []
    for atom in root.iter('atom'):
        elem = atom.get('elementType', 'C')
        x = float(atom.get('x3', 0))
        y = float(atom.get('y3', 0))
        z = float(atom.get('z3', 0))
        atoms.append((elem, x, y, z))

    with open(xyz_path, 'w') as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"Converted from {Path(cml_path).name}\n")
        for elem, x, y, z in atoms:
            f.write(f"{elem:2s} {x:12.6f} {y:12.6f} {z:12.6f}\n")

    return len(atoms)


def optimize_cml(input_cml: str, output_cml: str,
                 forcefield: str = "mmff94",
                 steps: int = 500) -> Tuple[bool, str]:
    """
    Optimise une structure CML avec Open Babel et MMFF94.

    1. CML -> XYZ temporaire (lecture directe, sans obabel)
    2. obabel --minimize sur le XYZ
    3. Resultat dans output_xyz (on garde le XYZ optimise)

    Retourne (succes: bool, message: str).
    """
    input_path = Path(input_cml)
    # Fichiers temporaires a cote du CML d'entree
    tmp_xyz = input_path.with_suffix('.xyz')
    out_xyz = Path(output_cml).with_suffix('.xyz')

    # 1. CML -> XYZ
    try:
        n_atoms = _cml_to_xyz(input_cml, str(tmp_xyz))
    except Exception as e:
        return False, f"Erreur lecture CML : {e}"

    if n_atoms == 0:
        return False, "CML vide (0 atomes)"

    # 2. Optimisation XYZ -> XYZ
    cmd = [
        "obabel",
        str(tmp_xyz),
        "-O", str(out_xyz),
        "--minimize",
        "--steps", str(steps),
        "--ff", forcefield,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        _cleanup(tmp_xyz)
        return False, f"Timeout apres 120s"

    # Nettoyer le XYZ temporaire d'entree
    _cleanup(tmp_xyz)

    # Verifier le resultat
    if result.returncode == 0 and out_xyz.exists() and out_xyz.stat().st_size > 0:
        return True, f"OK ({forcefield}, {steps} steps)"

    # Message d'erreur detaille
    err_parts = []
    if result.stderr:
        err_parts.append(result.stderr.strip())
    if result.stdout:
        err_parts.append(result.stdout.strip())
    err_msg = " | ".join(err_parts) if err_parts else "Fichier de sortie vide"
    return False, err_msg


def read_optimized_coords(cml_path: str) -> List[List[float]]:
    """
    Lit les coordonnees optimisees depuis le fichier XYZ produit par optimize_cml.
    Le XYZ optimise porte le meme nom que le CML de sortie mais avec .xyz.
    """
    xyz_path = Path(cml_path).with_suffix('.xyz')
    if not xyz_path.exists():
        return []
    return read_coords_from_xyz(str(xyz_path))


def read_coords_from_xyz(xyz_path: str) -> List[List[float]]:
    """Lit les coordonnees 3D depuis un fichier XYZ."""
    coords = []
    with open(xyz_path, 'r') as f:
        lines = f.readlines()

    if len(lines) < 3:
        return coords

    n_atoms = int(lines[0].strip())
    for line in lines[2:2 + n_atoms]:
        parts = line.split()
        if len(parts) >= 4:
            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])

    return coords


def read_coords_from_cml(cml_path: str) -> List[List[float]]:
    """Lit les coordonnees 3D depuis un fichier CML."""
    tree = ET.parse(cml_path)
    root = tree.getroot()

    coords = []
    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    for atom in root.iter(f'{ns}atom'):
        x = float(atom.get('x3', 0))
        y = float(atom.get('y3', 0))
        z = float(atom.get('z3', 0))
        coords.append([x, y, z])

    return coords


def _cleanup(path: Path):
    """Supprime un fichier temporaire sans erreur si absent."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
