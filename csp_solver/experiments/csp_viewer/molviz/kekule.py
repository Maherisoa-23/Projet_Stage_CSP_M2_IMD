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

Deux modes :
  - assign_kekule(mol)               -> UNE Kekule arbitraire (matching max
                                        via Edmonds blossom). Rapide, utilise
                                        pour la vue par defaut du viewer.
  - enumerate_kekule(mol, max_count) -> liste de TOUTES les Kekule (matchings
                                        max), plafonnee. Pour le mode
                                        navigation Kekule du viewer.

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


def enumerate_kekule(mol: MolGraph,
                     max_count: int = 200) -> Tuple[List[KekuleAssignment], bool]:
    """Enumere toutes les structures de Kekule du squelette carbone,
    plafonne a max_count.

    Une structure de Kekule = un matching de cardinalite MAXIMUM du graphe.
    Pour un benzenoide a nombre pair de carbones admettant un perfect
    matching, c'est equivalent a enumerer les perfect matchings. Pour une
    structure 5/7 avec nombre impair de carbones (ou topologie qui force
    des radicaux), les matchings max laissent des sommets non couverts =
    sites radicalaires. Chaque Kekule de la liste retournee peut avoir
    une distribution differente des radicaux mais TOUS ont la meme
    cardinalite.

    L'enumeration est CANONIQUE (deterministe, reproductible) :
      - On traite les sommets dans l'ordre d'index croissant.
      - A chaque etape, on prend le plus petit index non encore decide,
        et on branche soit sur "matche avec un voisin", soit sur "laisse
        radical" (uniquement si le budget de radicaux le permet).
      - Le budget de radicaux est exactement n - 2*M ou M est la
        cardinalite max, donc tout matching de taille M en utilise pile
        n - 2*M.

    Pas de deduplication : l'ordre canonique garantit que chaque Kekule
    est genere une et une seule fois.

    Args:
        mol       : MolGraph (squelette carbone)
        max_count : nombre maximum de Kekule a retourner. Au-dela on
                    s'arrete et on signale is_exact=False.

    Returns:
        (kekule_list, is_exact)
          - kekule_list : List[KekuleAssignment], len <= max_count
          - is_exact    : True si on a enumere TOUT, False si on a
                          atteint max_count avant epuisement
    """
    import networkx as nx

    n = len(mol.atoms)
    if n == 0 or not mol.bonds:
        return [], True

    g = nx.Graph()
    g.add_nodes_from(range(n))
    g.add_edges_from(mol.bonds)

    # Cardinalite max d'un matching (Edmonds blossom)
    max_match = nx.max_weight_matching(g, maxcardinality=True, weight=None)
    M = len(max_match)
    radical_budget = n - 2 * M  # nombre exact de radicaux dans tout matching max

    # Voisinage trie par index (pour enumeration canonique)
    neighbors_sorted = {v: sorted(g.neighbors(v)) for v in g.nodes}

    # Index de chaque arete (pour construire bond_orders en sortie)
    bond_idx = {tuple(sorted(p)): i for i, p in enumerate(mol.bonds)}

    results: List[KekuleAssignment] = []
    capped = [False]  # flag mutable dans la closure

    def _to_assignment(matching, radicals):
        bond_orders = [1] * len(mol.bonds)
        for u, v in matching:
            key = (min(u, v), max(u, v))
            bond_orders[bond_idx[key]] = 2
        return KekuleAssignment(
            bond_orders=bond_orders,
            radicals=set(radicals),
            n_doubles=len(matching),
            is_perfect=(len(radicals) == 0),
        )

    def _backtrack(matching, decided_radicals, used):
        # `used` = matched_set | decided_radicals, materialise pour eviter
        # de le recalculer a chaque appel.
        if capped[0]:
            return
        if len(results) >= max_count:
            capped[0] = True
            return

        # Plus petit index non decide
        candidate = None
        for v in range(n):
            if v not in used:
                candidate = v
                break

        if candidate is None:
            # Tous les sommets decides. Verifier la cardinalite max
            # (devrait toujours etre satisfait grace au radical_budget,
            # mais on garde la verif par robustesse).
            if len(matching) == M:
                results.append(_to_assignment(matching, decided_radicals))
            return

        # Branche 1 : matcher candidate avec chaque voisin non decide.
        # On itere dans l'ordre canonique (index croissant).
        for u in neighbors_sorted[candidate]:
            if u in used or u == candidate:
                continue
            new_match = matching | {(candidate, u)}
            new_used = used | {candidate, u}
            _backtrack(new_match, decided_radicals, new_used)
            if capped[0]:
                return

        # Branche 2 : laisser candidate radical (si budget non epuise).
        # Cette branche permet d'enumerer les configurations ou le radical
        # tombe a differentes positions dans le graphe.
        if len(decided_radicals) < radical_budget:
            new_radicals = decided_radicals | {candidate}
            new_used = used | {candidate}
            _backtrack(matching, new_radicals, new_used)

    _backtrack(set(), set(), set())

    return results, not capped[0]
