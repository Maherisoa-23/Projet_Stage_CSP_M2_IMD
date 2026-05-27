"""
Famille C : descripteurs geometriques 3D.

Calcule a partir d'un MolGraph (coordonnees apres optimisation xTB) :
  - max_angle_deg          : max angle entre normale d'un cycle et plan moyen
                             (redondant avec solutions.angle_deg, mais
                              auto-contenu pour eviter dep)
  - buckling_height        : deviation max au plan moyen, en A
  - radius_of_gyration     : compacite (A)
  - aspect_ratio           : longueur/largeur dans plan ACP (max axis / min axis)
  - convex_hull_area       : etendue 2D apres projection plan moyen (A^2)
  - curvature_discrete_*   : approximation discrete de courbure :
        pour chaque paire de cycles voisins, angle entre leurs normales.
        Moyenne et max sur toutes les paires.
  - n_atoms_above/below_plane : asymetrie
  - plane_asymmetry        : |n_above - n_below| / n_total

Methode : on calcule UN plan moyen via ACP sur les positions des
carbones, puis on raisonne par rapport a ce plan (normale = vecteur
propre associe a la plus petite valeur propre).

Aucune dependance externe lourde : utilise numpy.
"""

from typing import Dict, List, Optional

import numpy as np

from ...molviz.bonds import MolGraph


def compute_geometry_descriptors(mol: MolGraph) -> Dict[str, float]:
    """Calcule les descripteurs de la famille C."""
    if not mol.atoms or len(mol.atoms) < 3:
        return _empty()

    coords = np.array([[a.x, a.y, a.z] for a in mol.atoms])
    n = len(coords)

    # ACP : trouver le plan moyen et sa normale.
    centroid = coords.mean(axis=0)
    centered = coords - centroid
    # SVD plus stable que cov().eig sur petites molecules
    _, sv, vh = np.linalg.svd(centered, full_matrices=False)
    # vh[2] = direction de plus faible variance = normale au plan moyen
    plane_normal = vh[2]
    # vh[0] et vh[1] = directions principales dans le plan

    # Buckling : distance max au plan moyen
    distances_to_plane = np.abs(centered @ plane_normal)
    buckling = float(distances_to_plane.max())

    # Asymetrie : combien d'atomes au-dessus/dessous du plan
    signed = centered @ plane_normal
    n_above = int((signed > 1e-6).sum())
    n_below = int((signed < -1e-6).sum())
    plane_asym = abs(n_above - n_below) / n if n > 0 else 0.0

    # Radius of gyration (compacite)
    rog = float(np.sqrt(np.mean(np.sum(centered ** 2, axis=1))))

    # Aspect ratio dans le plan ACP : ratio sv[0] / sv[1]
    # sv[0] >= sv[1] >= sv[2] >= 0. Tres allonge = ratio grand.
    aspect_ratio = float(sv[0] / sv[1]) if sv[1] > 1e-9 else float("inf")
    if not np.isfinite(aspect_ratio):
        aspect_ratio = None

    # Convex hull area dans le plan (apres projection sur axes 1 et 2)
    convex_hull_area = _convex_hull_area_2d(centered @ vh[:2].T)

    # Angle de planeite : pour chaque cycle, angle entre normale du cycle
    # et normale au plan moyen. Max sur les cycles.
    cycle_normals: List[np.ndarray] = []
    angles_to_plane: List[float] = []
    for c in mol.cycles:
        if len(c.atoms) < 3:
            continue
        n_normal = _cycle_normal(coords[c.atoms])
        if n_normal is None:
            continue
        cycle_normals.append(n_normal)
        # Angle entre normale du cycle et normale au plan moyen (en deg)
        cos_a = float(np.clip(abs(np.dot(n_normal, plane_normal)), -1, 1))
        angle = float(np.degrees(np.arccos(cos_a)))
        angles_to_plane.append(angle)
    max_angle = float(max(angles_to_plane)) if angles_to_plane else 0.0

    # Courbure discrete : pour chaque paire de cycles partageant >= 2 atomes
    # (= fusionnes par arete), angle entre leurs normales.
    curvature_angles: List[float] = []
    for i in range(len(mol.cycles)):
        for j in range(i + 1, len(mol.cycles)):
            ca, cb = mol.cycles[i], mol.cycles[j]
            if len(set(ca.atoms) & set(cb.atoms)) < 2:
                continue
            if i >= len(cycle_normals) or j >= len(cycle_normals):
                continue
            na, nb = cycle_normals[i], cycle_normals[j]
            # On prend l'angle non-oriente entre les normales (0 = coplan,
            # 180 = oppose). On normalise dans [0, 90] en prenant le min
            # avec son complementaire.
            cos_a = float(np.clip(abs(np.dot(na, nb)), -1, 1))
            angle = float(np.degrees(np.arccos(cos_a)))
            curvature_angles.append(angle)

    if curvature_angles:
        curv_mean = float(np.mean(curvature_angles))
        curv_max = float(np.max(curvature_angles))
    else:
        curv_mean = 0.0
        curv_max = 0.0

    return {
        "max_angle_deg": max_angle,
        "buckling_height": buckling,
        "radius_of_gyration": rog,
        "aspect_ratio": aspect_ratio,
        "convex_hull_area": convex_hull_area,
        "curvature_discrete_mean": curv_mean,
        "curvature_discrete_max": curv_max,
        "n_atoms_above_plane": n_above,
        "n_atoms_below_plane": n_below,
        "plane_asymmetry": plane_asym,
    }


def _cycle_normal(points: np.ndarray) -> Optional[np.ndarray]:
    """Normale d'un cycle via ACP (3e composante de SVD)."""
    if len(points) < 3:
        return None
    centered = points - points.mean(axis=0)
    try:
        _, _, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    if vh.shape[0] < 3:
        return None
    return vh[2]


def _convex_hull_area_2d(points_2d: np.ndarray) -> float:
    """Aire de l'enveloppe convexe d'un nuage 2D.
    Implementation simple (Graham scan / shoelace), pas de dep scipy."""
    n = len(points_2d)
    if n < 3:
        return 0.0
    hull = _convex_hull(points_2d)
    if len(hull) < 3:
        return 0.0
    # Formule du lacet
    area = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]
        x2, y2 = hull[(i + 1) % len(hull)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _convex_hull(points_2d: np.ndarray) -> List[tuple]:
    """Andrew's monotone chain : enveloppe convexe en O(n log n)."""
    pts = sorted([tuple(p) for p in points_2d.tolist()])
    if len(pts) <= 1:
        return pts
    # lower hull
    lower = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    # upper hull
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _empty() -> Dict[str, float]:
    return {
        "max_angle_deg": 0.0,
        "buckling_height": 0.0,
        "radius_of_gyration": 0.0,
        "aspect_ratio": None,
        "convex_hull_area": 0.0,
        "curvature_discrete_mean": 0.0,
        "curvature_discrete_max": 0.0,
        "n_atoms_above_plane": 0,
        "n_atoms_below_plane": 0,
        "plane_asymmetry": 0.0,
    }
