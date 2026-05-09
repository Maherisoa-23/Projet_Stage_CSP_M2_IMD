"""
Assignation Kekule via matching maximum + identification des radicaux.

Principe :
  - Le squelette carbone est un graphe simple (pas de multigraphe a ce stade).
  - Un Kekule valide = perfect matching sur ce graphe : chaque arete couplee
    est une double liaison, chaque atome est dans exactement une double
    liaison, donc valence sp2 (3 liaisons sigma + 1 pi via la double).
  - Si le graphe n'admet pas de perfect matching (e.g. nb impair de
    sommets, ou structure topologique qui force un atome non couvert),
    on prend un MAXIMUM matching et les sommets non couverts sont les
    radicaux : ils ont un electron pi non apparie.

Algorithme : networkx.max_weight_matching (Edmonds blossom).
  - Pour avoir un comportement reproductible, on assigne des poids
    uniformes (1.0). Edmonds renvoie un matching maximum cardinality.
  - On peut biaiser avec `weights="distance"` pour favoriser les paires
    courtes (== plus proches d'une vraie double bond) ; pas implemente
    ici, a faire si besoin futur.

Sortie : pour chaque liaison, son ordre (1 ou 2). Pour chaque atome, son
flag radical.
"""

from dataclasses import dataclass, field
from typing import List, Set, Tuple

from .bonds import MolGraph


@dataclass
class KekuleAssignment:
    """Resultat d'une assignation Kekule.

    bond_orders : liste de longueur len(mol.bonds), valeurs 1 (single) ou 2 (double).
    radicals    : set des indices d'atomes non couverts par le matching.
    n_doubles   : nombre de doubles bonds.
    is_perfect  : True si tous les atomes sont couverts (pas de radicaux).
    """
    bond_orders: List[int] = field(default_factory=list)
    radicals: Set[int] = field(default_factory=set)
    n_doubles: int = 0
    is_perfect: bool = True


def assign_kekule(mol: MolGraph) -> KekuleAssignment:
    """Calcule un Kekule par matching maximum sur le squelette carbone.

    Returns KekuleAssignment avec bond_orders[i] = 1 ou 2 pour chaque
    bond i de mol.bonds, et radicals = indices d'atomes non couverts.
    """
    import networkx as nx

    if not mol.atoms or not mol.bonds:
        return KekuleAssignment(bond_orders=[], radicals=set())

    g = nx.Graph()
    g.add_nodes_from(range(len(mol.atoms)))
    g.add_edges_from(mol.bonds)

    # max_weight_matching avec maxcardinality=True garantit un matching
    # de cardinalite max (= ce qu'on veut). Les poids uniformes assurent
    # que c'est purement topologique.
    matching = nx.max_weight_matching(g, maxcardinality=True, weight=None)
    matching_set = set()
    for u, v in matching:
        matching_set.add(tuple(sorted((u, v))))

    bond_orders = []
    for u, v in mol.bonds:
        key = tuple(sorted((u, v)))
        bond_orders.append(2 if key in matching_set else 1)

    covered = set()
    for u, v in matching:
        covered.add(u)
        covered.add(v)
    radicals = set(range(len(mol.atoms))) - covered

    return KekuleAssignment(
        bond_orders=bond_orders,
        radicals=radicals,
        n_doubles=len(matching_set),
        is_perfect=(len(radicals) == 0),
    )
