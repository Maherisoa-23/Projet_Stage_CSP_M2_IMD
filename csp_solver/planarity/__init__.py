"""Test de planarite par analyse en composantes principales.

Module absorbe depuis non_benzenoid_generator/utils/planarity.py.
Renomme pca.py car l'ancien nom 'planarity' entrait en collision avec
les autres modules du projet.
"""
from .pca import compute_planarity, is_planar  # noqa: F401
