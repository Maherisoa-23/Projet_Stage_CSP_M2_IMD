"""
Determine quels hexagones d'un BenzenoidGraph sont en BORD.

Definition retenue :
  Un hexagone v du benzenoide d'entree est dit en BORD si son degre dans
  le graphe dual est < 6 (= pas totalement entoure par d'autres hex).

Cela correspond exactement a notre observation analysis_v2 :
  les pent/hept "en bord" = ceux dont l'hexagone d'origine n'est pas
  entoure de 6 voisins.

Note : un hex frozen-fully (deg=6) peut neanmoins porter un x[v]=5/7
dans certaines configs (no-freeze etc), donc le concept de bord est
purement topologique sur le DUAL D'ENTREE, pas conditionnel a la
solution CSP.
"""

from typing import Set


def boundary_hexes(graph) -> Set[int]:
    """Indices des hexagones en bord du benzenoide d'entree.

    Args:
        graph: BenzenoidGraph (utils.parser)

    Returns:
        Set[int] : indices v tels que graph.degree(v) < 6.
    """
    return {v for v in range(graph.h) if graph.degree(v) < 6}


def interior_hexes(graph) -> Set[int]:
    """Inverse : indices des hex INTERIEURS (deg=6)."""
    return {v for v in range(graph.h) if graph.degree(v) == 6}
