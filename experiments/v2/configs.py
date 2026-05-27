"""
5 configurations pre-definies pour la phase experimentale.

Chaque config = un nom + un dict de parametres a passer a build_and_solve_v2.
Les configs sont combinables avec les flags existants (adj_57, no_table,
no_freeze) au niveau du main / batch.

NOMS et CHOIX :
  baseline_v2  : aucun nouveau cap (= reference pour comparaison cross-DB)
  sym1         : C-SYM=1 seul -- teste l'effet de la symetrie 5/7
  pb2          : C-PB=2 seul -- teste l'effet du cap pent-en-bord
  sym1_pb2     : combinaison principale (notre meilleur pari empirique)
  all_strict   : C-SYM=0 (egalite stricte), C-PB=2, C-HB=3
  pb1          : C-PB=1 -- cap pent-en-bord plus strict que pb2
  pb0          : C-PB=0 -- aucun pentagone en bord du tout
"""

CONFIGS = {
    "baseline_v2": {
        "K_sym": None,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
    },
    "sym1": {
        "K_sym": 1,
        "K_pb": None,
        "K_hb": None,
        "K_tot": None,
    },
    "pb2": {
        "K_sym": None,
        "K_pb": 2,
        "K_hb": None,
        "K_tot": None,
    },
    "sym1_pb2": {
        "K_sym": 1,
        "K_pb": 2,
        "K_hb": None,
        "K_tot": None,
    },
    "all_strict": {
        "K_sym": 0,
        "K_pb": 2,
        "K_hb": 3,
        "K_tot": None,
    },
    "pb1": {
        "K_sym": None,
        "K_pb": 1,
        "K_hb": None,
        "K_tot": None,
    },
    "pb0": {
        "K_sym": None,
        "K_pb": 0,
        "K_hb": None,
        "K_tot": None,
    },
    "pb1_adj57": {
        # Meme K_pb=1 que pb1 ; le drapeau adj-57 est passe via --extra-flag
        # (le label different sert juste a separer ces resultats dans la DB).
        "K_sym": None,
        "K_pb": 1,
        "K_hb": None,
        "K_tot": None,
    },
}


def get(config_name: str) -> dict:
    """Retourne les kwargs pour une config nommee. KeyError sinon."""
    return CONFIGS[config_name]


def all_names() -> list:
    return list(CONFIGS.keys())
