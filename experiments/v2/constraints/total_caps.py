"""
C-TOT : limite le total de cycles non-hex.

  nb(v : x[v] != 6) <= K_tot

Justification : a composition equilibree, %plan decroit avec
n_pent + n_hept (43% pour 1+1, 30% pour 2+2, 25% pour 3+3, 25.5% pour 4+4).
Forcer un cap modere permet de reduire la complexite.

Defaut : pas de cap (None). A activer explicitement pour les benchmarks.
"""

from pycsp3 import Sum, satisfy


def apply(x, graph, K_tot=None) -> None:
    if K_tot is None:
        return
    h = graph.h
    satisfy(Sum(x[v] != 6 for v in range(h)) <= K_tot)
