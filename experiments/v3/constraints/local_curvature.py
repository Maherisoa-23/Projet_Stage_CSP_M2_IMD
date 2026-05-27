"""C-LC : contrainte de courbure de Gauss-Bonnet LOCALE.

Pour chaque hexagone h, dans son voisinage de rayon r dans le graphe dual :
   | (#pent dans N_r(h)) - (#hept dans N_r(h)) |  <=  tau

Justification : la courbure totale d'un patch ne doit pas etre concentree,
sinon le patch ne peut plus etre plat (Gauss-Bonnet discret). Cette
contrainte est STRICTEMENT plus forte que la symetrie globale n_pent-n_hept
de experiments_v2 et capture aussi des configurations spatialement nuisibles
(2 pent adjacents, cluster de hept, etc).

Defauts recommandes :
   radius = 2 (premier et second voisins)
   tau    = 1 (la courbure n'excede pas +/-pi/3 dans aucun voisinage)
   pent   = pent inclut le centre ou non ? -> oui, on integre le centre

Avec radius=2 sur graphe dual hexagonal, |N_2| <= 19 hex (centre + 6 + 12).
"""

from pycsp3 import Sum, satisfy
from ..curvature_helper import k_neighborhood


def apply(x, graph, tau: int = 1, radius: int = 2) -> None:
    """Pour chaque h, |Sum(x[v]==5) - Sum(x[v]==7)| <= tau sur N_r(h).

    Args:
        x      : VarArray PyCSP3 de longueur graph.h
        graph  : BenzenoidGraph
        tau    : seuil de courbure locale (en unites pi/3). None -> no-op.
        radius : rayon du voisinage (BFS dans le dual)
    """
    if tau is None or tau < 0:
        return
    for h in range(graph.h):
        nbrs = sorted(k_neighborhood(graph, h, radius))
        if not nbrs:
            continue
        pents = Sum(x[v] == 5 for v in nbrs)
        hepts = Sum(x[v] == 7 for v in nbrs)
        # | pents - hepts | <= tau
        satisfy(pents - hepts <= tau)
        satisfy(hepts - pents <= tau)
