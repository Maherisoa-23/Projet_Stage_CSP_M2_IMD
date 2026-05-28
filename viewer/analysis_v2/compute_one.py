"""
Orchestrateur : calcule TOUS les descripteurs d'une seule solution.

Appelle dans l'ordre :
  1. descriptors/cycles.py      (famille A)
  2. descriptors/boundary.py    (famille B)
  3. descriptors/geometry.py    (famille C)
  4. descriptors/electronic.py  (famille D)
  5. cross-features             (famille E, calcule ici car combinaison)

Retourne un dict avec ~50 cles, alignees sur le schema de la table
solution_descriptors.

Cette fonction est PURE : pas d'I/O. Elle est appelee par :
  - le worker cluster (cluster/worker.py)
  - le test local
  - eventuellement un endpoint API plus tard
"""

from typing import Dict

from ..molviz.bonds import MolGraph
from .descriptors.cycles import compute_cycle_descriptors
from .descriptors.boundary import compute_boundary_descriptors
from .descriptors.geometry import compute_geometry_descriptors
from .descriptors.electronic import (
    compute_electronic_descriptors,
    DEFAULT_MAX_KEKULE,
    DEFAULT_MAX_CLAR,
)


def compute_all_descriptors(mol: MolGraph,
                            max_kekule: int = DEFAULT_MAX_KEKULE,
                            max_clar: int = DEFAULT_MAX_CLAR) -> Dict:
    """Calcule tous les descripteurs d'une molecule.

    Returns un dict prepret a inserer dans solution_descriptors. Les
    cles h, config, mol, sol_idx, computed_at, compute_version sont a
    ajouter par l'appelant.
    """
    out: Dict = {}

    # Familles A, B, C, D
    out.update(compute_cycle_descriptors(mol))
    out.update(compute_boundary_descriptors(mol))
    out.update(compute_geometry_descriptors(mol))
    out.update(compute_electronic_descriptors(mol,
                                                max_kekule=max_kekule,
                                                max_clar=max_clar))

    # Famille E : croisements (sur les valeurs deja calculees)
    out.update(_cross_features(out))

    return out


def _cross_features(d: Dict) -> Dict:
    """Calcule les croisements aromatique x planeite et radicaux x planeite."""
    n_hex = d.get("n_hex") or 0
    clar = d.get("clar_number") or 0
    n_rad = d.get("n_radicals") or 0
    max_angle = d.get("max_angle_deg") or 0.0

    # Score d'aromaticite-planeite : a quel point la molecule est
    # plane ET aromatique. Score in [0, 1].
    # On normalise l'angle par 30 deg (au-dela, on considere "compl. tordu").
    planeity_factor = max(0.0, 1.0 - max_angle / 30.0)

    aromatic_planarity = None
    if n_hex > 0:
        aromatic_planarity = (clar / n_hex) * planeity_factor

    radical_planarity = n_rad * planeity_factor

    return {
        "aromatic_planarity_score": aromatic_planarity,
        "radical_planarity_score": float(radical_planarity),
    }
