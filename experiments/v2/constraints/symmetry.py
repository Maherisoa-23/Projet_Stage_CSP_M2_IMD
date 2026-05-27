"""
C-SYM : contrainte de symetrie 5/7.

  |nb(v : x[v]=5) - nb(v : x[v]=7)| <= K_sym

Justification (analysis_v2 sur 890k solutions) :
  |n_pent - n_hept| <= 1  ->  %plan = 25-43%
  |n_pent - n_hept| >= 2  ->  %plan =  0-7%

Defaut K_sym = 1 (compromis : assure la symetrie mais autorise un ecart
unique pour ne pas trop reduire la diversite combinatoire).

Pour les benzenoides ou peu d'hex sont mobilisables (beaucoup de geles
deg=6), la contrainte peut etre quasi-vide -- c'est normal.
"""

from pycsp3 import Sum, satisfy


def apply(x, graph, K_sym: int = 1) -> None:
    """Ajoute la contrainte |n_pent - n_hept| <= K_sym au modele.

    Args:
        x : VarArray des x[v] (taille h)
        graph : BenzenoidGraph (pour h)
        K_sym : ecart maximum autorise (>=0)
    """
    if K_sym < 0:
        return
    h = graph.h
    # Comptes via expressions Sum
    n_pent = Sum(x[v] == 5 for v in range(h))
    n_hept = Sum(x[v] == 7 for v in range(h))
    # |n_pent - n_hept| <= K  <=>  -K <= n_pent - n_hept <= K
    satisfy(n_pent - n_hept <= K_sym)
    satisfy(n_hept - n_pent <= K_sym)
