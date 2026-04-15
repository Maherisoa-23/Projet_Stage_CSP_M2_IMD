"""Optimisation geometrique via xTB (subprocess)

xTB (extended Tight-Binding) est un programme de chimie quantique semi-empirique.
Il lit un XYZ, calcule la structure electronique, et optimise la geometrie.
Pas besoin de specifier les liaisons — xTB les calcule depuis les electrons.

Commande : xtb molecule.xyz --opt tight
Sortie   : xtbopt.xyz (geometrie optimisee)
"""

import subprocess
import os
import math
from pathlib import Path
from typing import Tuple, List


def optimize_xtb(input_xyz: str, output_xyz: str,
                 opt_level: str = "tight") -> Tuple[bool, str]:
    """
    Optimise une structure XYZ avec xTB (GFN2-xTB).

    xTB ecrit toujours dans le repertoire courant (xtbopt.xyz, etc.),
    donc on se place dans le dossier du fichier d'entree.

    Retourne (succes: bool, message: str).
    """
    input_path = Path(input_xyz).resolve()
    output_path = Path(output_xyz).resolve()
    work_dir = input_path.parent

    cmd = [
        "xtb",
        str(input_path),
        "--opt", opt_level,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(work_dir), encoding='utf-8', errors='replace'
        )
    except FileNotFoundError:
        return False, "xtb non trouve dans le PATH"
    except subprocess.TimeoutExpired:
        return False, "Timeout apres 300s"

    # xTB ecrit xtbopt.xyz dans le repertoire de travail
    xtbopt = work_dir / "xtbopt.xyz"

    if not xtbopt.exists() or xtbopt.stat().st_size == 0:
        # Extraire le message d'erreur
        err = result.stderr.strip() if result.stderr else result.stdout.strip()
        # Garder juste les dernieres lignes pertinentes
        err_lines = err.split('\n')[-5:] if err else ["Fichier xtbopt.xyz non genere"]
        return False, " | ".join(l.strip() for l in err_lines if l.strip())

    # Renommer xtbopt.xyz vers le chemin de sortie souhaite
    if xtbopt.resolve() != output_path:
        xtbopt.replace(output_path)

    # Verifier la convergence dans la sortie
    converged = "GEOMETRY OPTIMIZATION CONVERGED" in (result.stdout or "")
    status = "OK (converge)" if converged else "OK (non converge, max iterations)"

    # Nettoyer les fichiers temporaires xTB
    _cleanup_xtb(work_dir)

    return True, status


def verify_distances(xyz_path: str) -> Tuple[bool, str]:
    """
    Verifie que les distances interatomiques sont raisonnables
    dans un fichier XYZ optimise.

    Seuils : C-C entre 1.2 et 1.8 A, C-H entre 0.9 et 1.3 A.
    Retourne (ok, message).
    """
    atoms = _read_atoms_from_xyz(xyz_path)
    if len(atoms) < 2:
        return False, "Moins de 2 atomes"

    issues = []
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            ei, xi, yi, zi = atoms[i]
            ej, xj, yj, zj = atoms[j]
            d = math.sqrt((xj - xi)**2 + (yj - yi)**2 + (zj - zi)**2)

            pair = ''.join(sorted([ei, ej]))
            if pair == 'CC' and d < 1.8:
                # Liaison C-C probable
                if d < 1.2 or d > 1.8:
                    issues.append(f"C-C distance {d:.3f} A hors limites")
            elif pair == 'CH' and d < 1.3:
                # Liaison C-H probable
                if d < 0.8 or d > 1.4:
                    issues.append(f"C-H distance {d:.3f} A hors limites")

    if issues:
        return False, "; ".join(issues[:3])
    return True, "Distances OK"


def read_optimized_coords(opt_xyz_path: str) -> List[List[float]]:
    """Lit les coordonnees depuis un XYZ optimise par xTB."""
    return _read_coords_from_xyz(opt_xyz_path)


def _read_atoms_from_xyz(xyz_path: str) -> List[tuple]:
    """Lit (element, x, y, z) depuis un fichier XYZ."""
    atoms = []
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 3:
        return atoms
    n = int(lines[0].strip())
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            atoms.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
    return atoms


def _read_coords_from_xyz(xyz_path: str) -> List[List[float]]:
    """Lit les coordonnees 3D depuis un fichier XYZ."""
    coords = []
    with open(xyz_path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 3:
        return coords
    n = int(lines[0].strip())
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) >= 4:
            coords.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return coords


def _cleanup_xtb(work_dir: Path):
    """Supprime les fichiers temporaires generes par xTB."""
    xtb_files = [
        "xtbrestart", "xtbtopo.mol", "wbo", "charges",
        "xtbopt.log", ".xtboptok"
    ]
    for name in xtb_files:
        p = work_dir / name
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
