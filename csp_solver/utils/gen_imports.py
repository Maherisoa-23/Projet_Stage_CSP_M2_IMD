"""Wrapper de retro-compatibilite (mai 2026, refactor Option C).

Ce module servait a charger les modules de l'ex-`non_benzenoid_generator/`
(planarity, optimizer, primitives, valence) via importlib pour eviter une
collision avec `csp_solver/utils/`. Depuis l'absorption de ces modules
dans csp_solver/ (planarity/, xtb/, primitives/), cette gymnastique est
inutile : on importe directement depuis les modules canoniques.

Conserve ici pour ne pas casser un import historique
`from utils.gen_imports import compute_planarity`.
"""

from csp_solver.planarity.pca import compute_planarity, is_planar
from csp_solver.xtb.optimizer import (
    optimize_xtb,
    read_optimized_coords,
    verify_distances,
)
from csp_solver.primitives.topology import MolecularGraph, Cycle, Vertex
from csp_solver.primitives.valence import ValenceSolver


__all__ = [
    "compute_planarity",
    "is_planar",
    "optimize_xtb",
    "read_optimized_coords",
    "verify_distances",
    "MolecularGraph",
    "Cycle",
    "Vertex",
    "ValenceSolver",
]
