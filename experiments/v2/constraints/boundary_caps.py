"""
C-PB : limite le nombre de pentagones en bord
C-HB : limite le nombre d'heptagones en bord

  C-PB : nb(v in boundary : x[v]=5) <= K_pb
  C-HB : nb(v in boundary : x[v]=7) <= K_hb

Justification (analysis_v2) :

  C-PB (pentagones en bord) -- effet quasi-lineaire :
    0 pent en bord = 59% plan
    1 pent en bord = 41% plan
    2 pent en bord = 27% plan
    3 pent en bord = 19% plan
    4 pent en bord = 15% plan
    5 pent en bord =  2% plan
    -> defaut K_pb = 2 (compromis efficacite/diversite)

  C-HB (heptagones en bord) -- effet plus doux :
    1 hept en bord = 43% plan
    4 hept en bord = 24% plan
    -> defaut K_hb = 3
"""

from pycsp3 import Sum, satisfy
from ..boundary_helper import boundary_hexes


def apply_pb(x, graph, K_pb: int = 2) -> None:
    """nb_pent_at_boundary <= K_pb."""
    if K_pb is None:
        return
    bds = boundary_hexes(graph)
    if not bds:
        return
    satisfy(Sum(x[v] == 5 for v in sorted(bds)) <= K_pb)


def apply_hb(x, graph, K_hb: int = 3) -> None:
    """nb_hept_at_boundary <= K_hb."""
    if K_hb is None:
        return
    bds = boundary_hexes(graph)
    if not bds:
        return
    satisfy(Sum(x[v] == 7 for v in sorted(bds)) <= K_hb)
