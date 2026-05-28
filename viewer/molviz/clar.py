"""
Enumeration des couvertures de Clar (sextets aromatiques).

Definition (Clar 1972 ; these Varet section 2.4.5) :
  Une couverture de Clar est un choix de :
    1. Un sous-ensemble S d'hexagones de la molecule, DEUX-A-DEUX VERTEX-DISJOINTS.
       Chaque hexagone de S porte un "rond de Clar" = sextet aromatique de 6
       electrons pi delocalises dans l'hexagone.
    2. Un matching parfait du sous-graphe forme par les atomes NON consommes
       par S (= "residu"). Pour les molecules radicalaires, on tolere que ce
       matching laisse autant de radicaux que le matching max global.
  Le score de Clar d'une couverture = |S|.
  Le nombre de Clar de la molecule = max |S| sur toutes les couvertures valides.

Remarques :
  - Seuls les HEXAGONES (cycles de taille 6) peuvent porter un sextet (regle
    de Huckel 4n+2 avec n=1 : il faut exactement 6 electrons pi). Pentagones
    et heptagones sont structurellement exclus.
  - "Vertex-disjoints" : aucun atome n'est partage entre deux hex de S. Cette
    contrainte est forte pour les PAH condenses (hex souvent fusionnes par
    arete = 2 atomes partages). C'est la definition stricte de Clar, confirmee
    avec les chimistes (Hagebaum-Reignier / Carissan) : un rond de Clar
    represente un sextet aromatique AUTONOME, ses 6 electrons pi circulent dans
    l'hexagone seul, donc deux ronds ne peuvent pas se partager d'atome.
  - Une molecule peut admettre plusieurs couvertures de Clar maximales (= avec
    le meme nombre de sextets, choisis differemment). On les enumere toutes.

Algorithme (enumeration exhaustive) :
  Pour mol avec n_hex hexagones :
    Pour chaque sous-ensemble S des hex (2^n_hex iterations) :
      - Verifier que S est vertex-disjoint.
      - Calculer max matching du residu G \\ V(S).
      - Si le nb total de radicaux <= min global, c'est une couverture valide.
      - On garde celles avec |S| max.
  Pour h3-h9 : n_hex <= 9 donc 2^9 = 512 sous-ensembles, trivial.

Sortie : pour chaque couverture, ses sextets + bond_orders (canonique sur les
sextets + matching du residu) + radicaux.
"""

from dataclasses import dataclass, field
from typing import List, Set, Tuple

from .bonds import MolGraph, bond_index_map, build_nx_graph, cycle_edge_indices


@dataclass
class ClarCover:
    """Une couverture de Clar.

    sextets       : indices des cycles porteurs d'un rond de Clar (sextets).
                    Tous sont des hexagones.
    bond_orders   : longueur len(mol.bonds), valeurs 1 ou 2.
                    Sur les aretes d'un sextet : alternance canonique
                    (double sur les positions paires du cycle).
                    Sur les aretes du residu : matching max du residu.
                    Sur les aretes connectant sextet et residu : 1 (single).
    radicals      : indices d'atomes non couverts par le matching du residu.
                    Typiquement vide pour molecule non-radicalaire.
    n_sextets     : len(sextets) = score Clar de cette couverture.
    """
    sextets: List[int] = field(default_factory=list)
    bond_orders: List[int] = field(default_factory=list)
    radicals: Set[int] = field(default_factory=set)
    n_sextets: int = 0


def enumerate_clar_covers(mol: MolGraph,
                          max_count: int = 200) -> Tuple[List[ClarCover], bool]:
    """Enumere les couvertures de Clar de score MAXIMUM.

    Args:
        mol       : MolGraph (squelette carbone)
        max_count : nombre maximum de couvertures a retourner. Au-dela on
                    s'arrete et on signale is_exact=False.

    Returns:
        (covers, is_exact)
          - covers   : List[ClarCover], len <= max_count. Toutes ont le meme
                       n_sextets (= nombre de Clar de la molecule).
          - is_exact : True si on a tout enumere, False si plafonne.

    Note : retourne toujours au moins la couverture vide (S = {}) si la
    molecule admet un matching max (ce qui est trivialement vrai). Cette
    couverture vide a n_sextets = 0 et son matching = matching max global.
    """
    import networkx as nx

    n = len(mol.atoms)
    n_bonds = len(mol.bonds)

    if n == 0 or not mol.bonds:
        return [], True

    # Hexagones uniquement (les pent/hept ne peuvent pas porter un sextet)
    hex_indices = [i for i, c in enumerate(mol.cycles) if len(c.atoms) == 6]
    n_hex = len(hex_indices)

    # Graphe complet pour le matching global
    g_full = build_nx_graph(mol)
    full_match = nx.max_weight_matching(g_full, maxcardinality=True, weight=None)
    # Nb de radicaux du matching max global (= min realisable)
    n_radicals_total = n - 2 * len(full_match)

    # Index des aretes pour conversion (u,v) -> indice dans mol.bonds
    bond_idx = bond_index_map(mol)

    # Pre-calcul : atomes et aretes de chaque cycle, puis on ne garde que les hex.
    # cycle_edge_indices retourne UNE liste par cycle (dans l'ordre mol.cycles),
    # on indexe sur hex_indices pour ne garder que les hex.
    all_cycle_edges = cycle_edge_indices(mol, bond_idx)
    hex_atoms_set = {hi: set(mol.cycles[hi].atoms) for hi in hex_indices}
    hex_bond_indices = {hi: all_cycle_edges[hi] for hi in hex_indices}

    best_score = 0     # au moins la couverture vide est toujours valide
    capped = False
    covers: List[ClarCover] = []

    # Enumeration canonique : par bitmask croissant.
    for mask in range(1 << n_hex):
        # S = liste d'indices d'hex porteurs de sextets pour ce mask
        S = [hex_indices[k] for k in range(n_hex) if mask & (1 << k)]

        # Verification vertex-disjoint
        consumed = set()
        disjoint = True
        for hi in S:
            for a in hex_atoms_set[hi]:
                if a in consumed:
                    disjoint = False
                    break
                consumed.add(a)
            if not disjoint:
                break
        if not disjoint:
            continue

        score = len(S)
        # Optimisation : si on a deja un best_score > score, inutile de continuer.
        # On garde uniquement les couvertures avec le meilleur score.
        if score < best_score:
            continue

        # Residu = atomes non consommes par les sextets
        remaining = [v for v in range(n) if v not in consumed]
        if remaining:
            g_sub = g_full.subgraph(remaining)
            sub_match = nx.max_weight_matching(g_sub, maxcardinality=True, weight=None)
            sub_matched = set()
            for u, v in sub_match:
                sub_matched.add(u)
                sub_matched.add(v)
            sub_radicals = set(remaining) - sub_matched
        else:
            # Tous les atomes sont consommes par des sextets, pas de residu
            sub_match = set()
            sub_radicals = set()

        # Validite : le nb total de radicaux ne doit pas exceder le min global.
        # Pour une molecule non-radicalaire (n_radicals_total = 0), il faut
        # sub_radicals = vide (= matching parfait du residu).
        if len(sub_radicals) > n_radicals_total:
            continue

        # Cette couverture est valide. On construit ses bond_orders.
        bond_orders = [1] * n_bonds
        # Sextets : alternance canonique (double aux positions paires dans
        # l'ordre des bonds_of_hex). 3 doubles, 3 singles dans chaque sextet.
        for hi in S:
            for j, bi in enumerate(hex_bond_indices[hi]):
                bond_orders[bi] = 2 if j % 2 == 0 else 1
        # Residu : matching
        for u, v in sub_match:
            key = (min(u, v), max(u, v))
            if key in bond_idx:
                bond_orders[bond_idx[key]] = 2

        cover = ClarCover(
            sextets=list(S),
            bond_orders=bond_orders,
            radicals=set(sub_radicals),
            n_sextets=score,
        )

        if score > best_score:
            # Nouveau record : on jette les anciennes couvertures
            best_score = score
            covers = [cover]
        else:
            # score == best_score : on ajoute
            covers.append(cover)

        if len(covers) >= max_count:
            capped = True
            break

    return covers, not capped
