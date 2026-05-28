"""Import unifie des modules du generateur non_benzenoid_generator.

Le generateur etant dans un dossier parallele (non un package installe),
il faut charger ses modules via importlib pour eviter les conflits avec
le dossier `utils/` local. Ce module centralise cette logique.

Utilisation :
    from utils.gen_imports import (
        compute_planarity, is_planar,
        optimize_xtb, read_optimized_coords, verify_distances,
        MolecularGraph, Cycle, ValenceSolver,
    )
"""

import sys
import importlib.util
from pathlib import Path

from config import CONFIG


_GEN_ROOT = CONFIG.paths.generator_root


def _add_gen_to_syspath():
    """Ajoute le dossier du generateur au sys.path (pour les imports internes)."""
    gen_str = str(_GEN_ROOT)
    if gen_str not in sys.path:
        sys.path.insert(0, gen_str)


def _load_module_from_path(module_name: str, file_path: Path):
    """Charge un module Python depuis un chemin de fichier."""
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de charger {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------
# Charger le generateur (une seule fois)
# ----------------------------------------------------------------------

_add_gen_to_syspath()

# Modules importes par leur chemin direct (evite les conflits avec utils/)
_planarity = _load_module_from_path("gen_planarity", _GEN_ROOT / "utils" / "planarity.py")

# Ceux-ci utilisent les imports internes du generateur (core, config, etc.)
# donc il faut que sys.path soit deja configure.
from csp_solver.xtb.optimizer import (
    optimize_xtb,
    read_optimized_coords,
    verify_distances,
)
from csp_solver.primitives.topology import (
    MolecularGraph,
    Cycle,
    Vertex,
)
from csp_solver.primitives.valence import ValenceSolver


# ----------------------------------------------------------------------
# API publique
# ----------------------------------------------------------------------

compute_planarity = _planarity.compute_planarity
is_planar = _planarity.is_planar


__all__ = [
    # Planarite
    "compute_planarity",
    "is_planar",
    # Optimisation xTB
    "optimize_xtb",
    "read_optimized_coords",
    "verify_distances",
    # Graphe moleculaire
    "MolecularGraph",
    "Cycle",
    "Vertex",
    "ValenceSolver",
]
