"""Test de planarite par ACP (Analyse en Composantes Principales)

Adapte de planarite.py — version integree au pipeline, fonctionne
directement sur des listes de coordonnees (pas de lecture de fichier).
Pur Python, aucune dependance externe.
"""

import math
from typing import List, Tuple, Dict


def _compute_mean(coords: List[List[float]]) -> List[float]:
    n = len(coords)
    return [sum(c[i] for c in coords) / n for i in range(3)]


def _dot(v1: List[float], v2: List[float]) -> float:
    return sum(v1[i] * v2[i] for i in range(3))


def _subtract(v1: List[float], v2: List[float]) -> List[float]:
    return [v1[i] - v2[i] for i in range(3)]


def _covariance_matrix(coords: List[List[float]], mean: List[float]) -> List[List[float]]:
    n = len(coords)
    centered = [_subtract(c, mean) for c in coords]
    cov = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            cov[i][j] = sum(centered[k][i] * centered[k][j] for k in range(n)) / n
    return cov


def _jacobi(A: List[List[float]], max_iter: int = 100,
            tol: float = 1e-10) -> Tuple[List[float], List[List[float]]]:
    """Valeurs et vecteurs propres par methode de Jacobi (matrice 3x3)."""
    n = len(A)
    M = [[A[i][j] for j in range(n)] for i in range(n)]
    V = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    for _ in range(max_iter):
        max_val, p, q = 0.0, 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                if abs(M[i][j]) > abs(max_val):
                    max_val, p, q = M[i][j], i, j
        if abs(max_val) < tol:
            break

        if M[p][p] == M[q][q]:
            theta = math.pi / 4
        else:
            theta = 0.5 * math.atan2(2 * M[p][q], M[q][q] - M[p][p])

        c, s = math.cos(theta), math.sin(theta)
        Mpp, Mqq = M[p][p], M[q][q]
        M[p][p] = c * c * Mpp - 2 * s * c * M[p][q] + s * s * Mqq
        M[q][q] = s * s * Mpp + 2 * s * c * M[p][q] + c * c * Mqq
        M[p][q] = M[q][p] = 0.0

        for i in range(n):
            if i != p and i != q:
                Mip, Miq = M[i][p], M[i][q]
                M[i][p] = M[p][i] = c * Mip - s * Miq
                M[i][q] = M[q][i] = s * Mip + c * Miq

        for i in range(n):
            Vip, Viq = V[i][p], V[i][q]
            V[i][p] = c * Vip - s * Viq
            V[i][q] = s * Vip + c * Viq

    return [M[i][i] for i in range(n)], V


def compute_planarity(coords: List[List[float]]) -> Dict[str, float]:
    """
    Calcule les metriques de planarite pour une liste de coordonnees 3D.

    Parametres
    ----------
    coords : liste de [x, y, z] pour chaque atome

    Retourne
    --------
    dict avec les cles :
      - height        : epaisseur totale selon l'axe le plus fin (A)
      - rmsd_plane    : RMSD des distances au plan moyen (A)
      - max_deviation : deviation maximale au plan moyen (A)
      - thickness_ratio : height / max(length, width)
    """
    if len(coords) < 3:
        return {'height': 0.0, 'rmsd_plane': 0.0, 'max_deviation': 0.0,
                'thickness_ratio': 0.0}

    centroid = _compute_mean(coords)
    centered = [_subtract(c, centroid) for c in coords]

    cov = _covariance_matrix(coords, centroid)
    eigenvalues, eigenvectors = _jacobi(cov)

    # Trier par valeur propre decroissante
    indexed = sorted(enumerate(eigenvalues), key=lambda x: -x[1])
    sorted_ev = [[eigenvectors[j][i] for j in range(3)] for i, _ in indexed]

    # Projections sur chaque axe principal
    projections = [[_dot(c, sorted_ev[ax]) for ax in range(3)] for c in centered]

    length = max(p[0] for p in projections) - min(p[0] for p in projections)
    width = max(p[1] for p in projections) - min(p[1] for p in projections)
    height = max(p[2] for p in projections) - min(p[2] for p in projections)

    # Distances au plan moyen (perpendiculaire au 3e axe)
    normal = sorted_ev[2]
    dists = [abs(_dot(c, normal)) for c in centered]
    rmsd = math.sqrt(sum(d * d for d in dists) / len(dists))
    max_dev = max(dists)

    max_dim = max(length, width) if max(length, width) > 0 else 1.0

    return {
        'height': height,
        'rmsd_plane': rmsd,
        'max_deviation': max_dev,
        'thickness_ratio': height / max_dim,
    }


def is_planar(metrics: Dict[str, float], threshold: float = 0.5) -> bool:
    """Retourne True si la molecule est consideree plane (max_deviation <= seuil)."""
    return metrics['max_deviation'] <= threshold
