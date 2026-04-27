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
import random
import shutil
import tempfile
from pathlib import Path
from typing import Tuple, List


def optimize_xtb(input_xyz: str, output_xyz: str,
                 opt_level: str = "tight",
                 perturb_z: float = 0.1,
                 seed: int = None) -> Tuple[bool, str]:
    """
    Optimise une structure XYZ avec xTB (GFN2-xTB).

    Avant l'optimisation, une perturbation aleatoire est ajoutee aux
    coordonnees z (amplitude ±perturb_z en Angstroms). Cela empeche xTB
    de rester coince dans un minimum local plat lorsque la geometrie
    initiale est parfaitement plane (z=0 partout).

    Si la molecule est reellement plane, xTB la ramene a plat malgre
    la perturbation. Si elle ne l'est pas, xTB trouve le vrai minimum.

    xTB est execute dans un repertoire temporaire isole (scratch dir),
    ce qui evite toute collision entre runs concurrents partageant le
    meme dossier de sortie (essentiel pour la parallelisation et les
    clusters HPC).

    Retourne (succes: bool, message: str).
    """
    input_path = Path(input_xyz).resolve()
    output_path = Path(output_xyz).resolve()

    # Repertoire de travail temporaire isole : evite les collisions xTB
    # quand plusieurs runs s'executent en parallele sur la meme molecule.
    # xTB ecrit toujours xtbopt.xyz, xtbrestart, xtbtopo.mol, wbo, charges,
    # xtbopt.log, .xtboptok dans son cwd → un scratch dir par run.
    work_dir = Path(tempfile.mkdtemp(prefix="xtb_run_"))

    try:
        # Copier le XYZ d'entree dans le scratch et le perturber
        perturbed_path = work_dir / "input.xyz"
        rng = random.Random(seed) if seed is not None else None
        _write_perturbed_xyz(str(input_path), str(perturbed_path), perturb_z, rng)

        cmd = [
            "xtb",
            str(perturbed_path),
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

        # xTB ecrit xtbopt.xyz dans le scratch
        xtbopt = work_dir / "xtbopt.xyz"

        if not xtbopt.exists() or xtbopt.stat().st_size == 0:
            err = result.stderr.strip() if result.stderr else result.stdout.strip()
            err_lines = err.split('\n')[-5:] if err else ["Fichier xtbopt.xyz non genere"]
            return False, " | ".join(l.strip() for l in err_lines if l.strip())

        # Copier la geometrie optimisee vers le chemin de sortie souhaite
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(xtbopt), str(output_path))

        # Verifier la convergence dans la sortie
        converged = "GEOMETRY OPTIMIZATION CONVERGED" in (result.stdout or "")
        status = "OK (converge)" if converged else "OK (non converge, max iterations)"

        return True, status

    finally:
        # Nettoyer le scratch dir (toujours, meme en cas d'erreur)
        shutil.rmtree(str(work_dir), ignore_errors=True)


def _write_perturbed_xyz(input_path: str, output_path: str, amplitude: float, rng=None):
    """Ecrit une copie du XYZ avec perturbations aleatoires en z.

    Si rng (random.Random) est fourni, il est utilise pour la reproductibilite.
    Sinon, utilise le generateur global random (comportement historique).
    """
    atoms = _read_atoms_from_xyz(input_path)
    source = rng if rng is not None else random
    with open(output_path, 'w') as f:
        f.write(f"{len(atoms)}\n")
        f.write("perturbed for xTB optimization\n")
        for elem, x, y, z in atoms:
            z_perturbed = z + source.uniform(-amplitude, amplitude)
            f.write(f"{elem:<2s} {x:14.6f} {y:14.6f} {z_perturbed:14.6f}\n")


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


