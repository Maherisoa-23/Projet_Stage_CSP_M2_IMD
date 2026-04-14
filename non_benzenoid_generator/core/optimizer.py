"""Optimisation geometrique MMFF94 via Open Babel (subprocess)

Strategie : convertir le CML en MOL V2000 temporaire (format qui inclut
les liaisons explicitement, donc obabel n'a pas besoin de les deviner),
optimiser, puis relire les coordonnees depuis le XYZ de sortie.
"""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, List


def _cml_to_mol(cml_path: str, mol_path: str) -> int:
    """
    Convertit un fichier CML en MOL V2000 en lisant directement le XML.
    Le MOL inclut les atomes ET les liaisons (avec leurs ordres).
    Retourne le nombre d'atomes ecrits.
    """
    tree = ET.parse(cml_path)
    root = tree.getroot()

    # Lire les atomes
    atoms = []  # (element, x, y, z)
    atom_id_to_idx = {}  # "a1" -> 1
    idx = 1
    for atom in root.iter('atom'):
        aid = atom.get('id', '')
        elem = atom.get('elementType', 'C')
        x = float(atom.get('x3', 0))
        y = float(atom.get('y3', 0))
        z = float(atom.get('z3', 0))
        atoms.append((elem, x, y, z))
        atom_id_to_idx[aid] = idx
        idx += 1

    # Lire les liaisons
    bonds = []  # (idx1, idx2, order)
    for bond in root.iter('bond'):
        refs = bond.get('atomRefs2', '').split()
        order = int(bond.get('order', '1'))
        if len(refs) == 2 and refs[0] in atom_id_to_idx and refs[1] in atom_id_to_idx:
            bonds.append((atom_id_to_idx[refs[0]], atom_id_to_idx[refs[1]], order))

    # Ecrire le MOL V2000
    n_atoms = len(atoms)
    n_bonds = len(bonds)

    lines = []
    lines.append(Path(cml_path).stem)
    lines.append("  NonBenzGen  3D")
    lines.append("")
    lines.append(f"{n_atoms:3d}{n_bonds:3d}  0  0  0  0  0  0  0  0999 V2000")

    for elem, x, y, z in atoms:
        lines.append(
            f"{x:10.4f}{y:10.4f}{z:10.4f} {elem:<3s} 0  0  0  0  0  0  0  0  0  0  0  0"
        )

    for a1, a2, order in bonds:
        lines.append(f"{a1:3d}{a2:3d}{order:3d}  0  0  0  0")

    lines.append("M  END")

    with open(mol_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    return n_atoms


def optimize_cml(input_cml: str, output_cml: str,
                 forcefield: str = "mmff94",
                 steps: int = 500) -> Tuple[bool, str]:
    """
    Optimise une structure CML avec Open Babel et MMFF94.

    1. CML -> MOL temporaire (avec liaisons explicites)
    2. obabel --minimize sur le MOL -> XYZ de sortie
    3. Les coordonnees optimisees sont dans le XYZ

    Retourne (succes: bool, message: str).
    """
    input_path = Path(input_cml)
    tmp_mol = input_path.with_suffix('.mol')
    out_xyz = Path(output_cml).with_suffix('.xyz')

    # 1. CML -> MOL (avec liaisons explicites)
    try:
        n_atoms = _cml_to_mol(input_cml, str(tmp_mol))
    except Exception as e:
        return False, f"Erreur lecture CML : {e}"

    if n_atoms == 0:
        return False, "CML vide (0 atomes)"

    # 2. Optimisation MOL -> XYZ
    cmd = [
        "obabel",
        str(tmp_mol),
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
        _cleanup(tmp_mol)
        return False, "Timeout apres 120s"

    # Nettoyer le MOL temporaire
    _cleanup(tmp_mol)

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
    """
    xyz_path = Path(cml_path).with_suffix('.xyz')
    if not xyz_path.exists():
        return []
    return _read_coords_from_xyz(str(xyz_path))


def _read_coords_from_xyz(xyz_path: str) -> List[List[float]]:
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
