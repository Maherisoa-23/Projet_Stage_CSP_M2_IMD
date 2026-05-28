"""Primitives chimiques 3D : topologie moleculaire, geometrie, valences.

Modules absorbes depuis non_benzenoid_generator/core/ (mai 2026, refactoring
option C). Utilises par csp_solver.reconstruction.
"""
from .topology import MolecularGraph, Cycle  # noqa: F401
from .geometry import GeometryEngine  # noqa: F401
from .valence import ValenceSolver  # noqa: F401
