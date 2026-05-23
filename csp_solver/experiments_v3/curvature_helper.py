"""Gauss-Bonnet discret local : courbure d'une mol = somme de (6 - taille) sur
les hexagones d'un voisinage.

Theorie
-------
Sur une surface polyedrique, chaque face k-gonale porte un defaut angulaire
   K(face) = (6 - k) * pi/3
   -> pentagone (k=5) : +pi/3   (courbure positive, type sphere)
   -> hexagone  (k=6) :  0      (plat)
   -> heptagone (k=7) : -pi/3   (courbure negative, type selle)

Theoreme (Gauss-Bonnet discret pour surface sans bord) :
   sum_faces K(face) = 2*pi * chi   (chi = caracteristique d'Euler)

Pour notre cas (pavage planaire de polygones), la condition necessaire pour
qu'il existe un plongement plat est que la courbure se REPARTISSE de maniere
equilibree localement. Concentration de courbure (positive ou negative) dans
un patch -> buckling de cette zone.

Notre score : on definit pour chaque hexagone h et chaque rayon r :
   curv_r(h) = sum_{v in N_r(h)} (6 - label(v))
ou N_r(h) = hexagones a distance graphique <= r dans le dual.

L'invariant de selectivite est :
   max_local_curvature(graph, labeling, r) = max_h |curv_r(h)|

Si on impose max_local_curvature <= tau, on rejette les molecules ou la
courbure se concentre dans un patch — donc theoriquement les mol qui
buckleraient apres optim.
"""

from __future__ import annotations

import networkx as nx
from typing import Iterable


# ---------------- Curvature primitive ----------------

def vertex_curvature(label: int) -> int:
    """Defaut angulaire entier d'une face (en unites pi/3).

    Args:
        label: taille du polygone (5, 6 ou 7)

    Returns:
        +1 pour 5, 0 pour 6, -1 pour 7
    """
    return 6 - label


# ---------------- Voisinages ----------------

def k_neighborhood(graph, v: int, radius: int) -> set[int]:
    """Ensemble des sommets a distance <= radius de v dans le graphe dual.

    Inclut v lui-meme (distance 0).
    """
    if radius < 0:
        return set()
    if radius == 0:
        return {v}
    # BFS limite a la profondeur radius
    return set(nx.single_source_shortest_path_length(graph.dual, v, cutoff=radius).keys())


def all_k_neighborhoods(graph, radius: int) -> dict[int, set[int]]:
    """Pre-calcule N_r(v) pour chaque v. Pratique pour replay rapide."""
    return {v: k_neighborhood(graph, v, radius) for v in range(graph.h)}


# ---------------- Courbure locale ----------------

def local_curvature_at(labeling: dict[int, int], neighborhood: Iterable[int]) -> int:
    """Somme des defauts angulaires sur un voisinage.

    Args:
        labeling     : dict {v: 5|6|7}
        neighborhood : iterable d'indices d'hex

    Returns:
        int (en unites pi/3). Signe : >0 = courbure positive (bol),
        <0 = courbure negative (selle), 0 = plat.
    """
    return sum(vertex_curvature(labeling[v]) for v in neighborhood)


def max_local_curvature(graph, labeling: dict[int, int],
                          radius: int = 2) -> tuple[int, int]:
    """Retourne (max_abs, vertex_argmax) sur tous les voisinages de rayon r.

    Args:
        graph    : BenzenoidGraph
        labeling : dict {v: taille en {5,6,7}}
        radius   : rayon des voisinages

    Returns:
        (max |curv_r(v)|, v) sur tous v
    """
    if graph.h == 0:
        return 0, -1
    nbrs = all_k_neighborhoods(graph, radius)
    best_v = 0
    best_abs = 0
    for v in range(graph.h):
        c = abs(local_curvature_at(labeling, nbrs[v]))
        if c > best_abs:
            best_abs = c
            best_v = v
    return best_abs, best_v


def curvature_summary(graph, labeling: dict[int, int],
                       radii: tuple[int, ...] = (1, 2, 3)) -> dict:
    """Resume multi-rayon de la courbure locale + global.

    Returns:
        dict {
          'n_pent': int, 'n_hept': int,
          'total_curv': int,           # = n_pent - n_hept
          'max_local_r1', 'max_local_r2', 'max_local_r3': int (en pi/3),
        }
    """
    n_pent = sum(1 for v in range(graph.h) if labeling[v] == 5)
    n_hept = sum(1 for v in range(graph.h) if labeling[v] == 7)
    out = {
        "n_pent": n_pent,
        "n_hept": n_hept,
        "total_curv": n_pent - n_hept,
    }
    for r in radii:
        m, _ = max_local_curvature(graph, labeling, radius=r)
        out[f"max_local_r{r}"] = m
    return out
