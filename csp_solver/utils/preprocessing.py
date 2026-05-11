"""
Pre-traitement : hexagones geles, filtrage des tables, automorphismes.

Ce module exploite le graphe dual G_D (connu avant resolution) pour
reduire l'espace de recherche du solveur CSP.
"""

import networkx as nx
from itertools import permutations
from utils.parser import BenzenoidGraph, count_zero_blocks
from utils.table import load_table


def has_interior_free_vertex(pattern: tuple) -> bool:
    """Vrai ssi le pattern contient au moins 2 zeros consecutifs (cyclique).

    C'est la condition exacte pour pouvoir transformer l'hexagone en
    pentagone : on a besoin d'un sommet interieur libre (= un sommet
    dont les deux cotes adjacents sont libres) a contracter.
    Cf. reconstruction/topology.py::_get_interior_free_vertices, qui
    utilise exactement cette condition.

    Sans 2 zeros adjacents, chaque sommet de l'hexagone est partage avec
    au moins un voisin -> aucune contraction n'est possible sans casser
    la topologie d'un voisin -> pentagone topologiquement infaisable.
    """
    n = len(pattern)
    return any(pattern[(i - 1) % n] == 0 and pattern[i] == 0 for i in range(n))


def has_free_side(pattern: tuple) -> bool:
    """Vrai ssi le pattern contient au moins un zero (cote libre).

    Condition pour pouvoir transformer l'hexagone en heptagone : on insere
    un sommet sur un cote libre. Avec 0 cote libre (pattern (1,1,1,1,1,1),
    deg=6 fully surrounded), c'est impossible -- mais ce cas est de toute
    facon deja gele par is_fully_surrounded.
    """
    return any(p == 0 for p in pattern)


def compute_domains(graph: BenzenoidGraph, freeze_b2: bool = True) -> dict:
    """Calcule le domaine de chaque variable x_v.

    On filtre 5 et 7 selon la faisabilite topologique de la reconstruction
    (cf. has_interior_free_vertex + has_free_side). Sans ce filtrage, le
    solveur produirait des solutions CSP-valides mais geometriquement
    inaccessibles (ex. pattern (1,1,1,1,1,0) qui demanderait un pentagone :
    main.py les rejetait deja en levant ValueError dans la reconstruction,
    laissant des sol_dirs vides sur disque ; ici on les exclut a la source).

    Args:
        graph: le graphe dual
        freeze_b2: si True, les hexagones avec b(v)>=2 sont geles a {6}.
                   Si False, seuls les hexagones avec deg=6 sont geles
                   (et le filtrage par faisabilite s'applique).

    Returns:
        dict {v: set} -- domaine de x_v (sous-ensemble de {5,6,7})
    """
    domains = {}
    for v in range(graph.h):
        pattern = graph.patterns[v]
        if graph.is_fully_surrounded(v):
            # deg=6 : toujours gele (pattern (1,1,1,1,1,1))
            domains[v] = {6}
        elif freeze_b2 and graph.has_separated_free_edges(v):
            # b(v)>=2 avec freeze actif : gele
            domains[v] = {6}
        else:
            # Hexagone non gele : on filtre 5 et 7 selon ce que la
            # reconstruction sait realiser sans casser la topologie
            # des voisins.
            d = {6}
            if has_interior_free_vertex(pattern):
                d.add(5)
            if has_free_side(pattern):
                d.add(7)
            domains[v] = d
    return domains


def filter_table_for_vertex(graph: BenzenoidGraph, v: int,
                            full_table: dict) -> list:
    """Filtre la table T(n) pour un sommet v non gele.

    Pour un sommet non gele (b(v)=1), les aretes partagees forment un
    bloc consecutif dans le pattern. On ne garde que les lignes de T(n)
    dont la structure correspond.

    Args:
        graph: le graphe dual
        v: indice du sommet
        full_table: table complete {5: [...], 6: [...], 7: [...]}

    Returns:
        Liste de tuples (x_v, x_u1, x_u2, ...) pour la contrainte
        extensionnelle. Chaque tuple contient la taille du cycle central
        suivie des tailles des voisins dans l'ordre du dual.
    """
    pattern = graph.patterns[v]
    deg = graph.degree(v)
    neighbors = graph.neighbors(v)

    # Positions des aretes partagees dans l'hexagone d'origine
    shared_positions = [i for i, p in enumerate(pattern) if p == 1]

    # L'index de debut du bloc de 1 dans le pattern
    if not shared_positions:
        # Pas de voisin (ne devrait pas arriver si deg >= 1)
        return []

    compatible_tuples = []

    for n in (5, 6, 7):
        for seq in full_table.get(n, []):
            # seq est un tuple de longueur n : (s_0, s_1, ..., s_{n-1})
            # Positions non nulles dans la sequence
            seq_shared = [i for i, s in enumerate(seq) if s != 0]

            # Le nombre de voisins doit correspondre
            if len(seq_shared) != deg:
                continue

            # Verifier que les positions non-nulles forment un bloc
            # consecutif (comme dans le pattern d'origine, puisque b(v)=1)
            if not _is_consecutive_block(seq_shared, n):
                continue

            # Verifier la compatibilite structurelle :
            # Les aretes partagees dans le pattern (taille 6) sont remappees
            # dans le cycle de taille n. Puisque b(v)=1, le bloc consecutif
            # de shared_positions dans l'hexagone correspond a un bloc
            # consecutif dans le nouveau cycle.

            # Construire le tuple pour la contrainte extensionnelle :
            # (x_v, x_u1, x_u2, ...) ou les u_i sont les voisins
            # dans l'ordre du graphe dual.
            # Les voisins dans seq sont dans l'ordre des positions.
            neighbor_sizes = [seq[i] for i in seq_shared]

            # L'ordre des voisins dans seq_shared correspond a l'ordre
            # cyclique dans le nouveau cycle. On doit le mapper a l'ordre
            # des voisins dans le graphe dual.
            # Pour b(v)=1, les voisins sont dans le meme ordre cyclique.
            entry = (n,) + tuple(neighbor_sizes)
            compatible_tuples.append(entry)

    return compatible_tuples


def _is_consecutive_block(positions: list, n: int) -> bool:
    """Verifie que les positions forment un bloc consecutif (cyclique)."""
    if not positions:
        return True
    if len(positions) == 1:
        return True

    # Trier et verifier la consecutivite cyclique
    positions = sorted(positions)
    for i in range(len(positions) - 1):
        if positions[i + 1] - positions[i] != 1:
            # Verifier le wrap-around : le dernier et le premier
            if i == len(positions) - 2:
                if positions[0] == 0 and positions[-1] == n - 1:
                    continue
            return False
    return True


def compute_automorphisms(graph: BenzenoidGraph) -> list:
    """Calcule les generateurs du groupe d'automorphismes de G_D.

    Utilise NetworkX pour trouver les automorphismes du graphe dual.

    Returns:
        Liste de permutations (chaque permutation est un dict {v: pi(v)}).
    """
    G = graph.dual
    matcher = nx.algorithms.isomorphism.GraphMatcher(G, G)

    # Collecter tous les automorphismes
    all_auts = []
    for iso in matcher.isomorphisms_iter():
        # iso est un dict {v: pi(v)}
        # Exclure l'identite
        if any(iso[v] != v for v in iso):
            all_auts.append(iso)

    if not all_auts:
        return []

    # Extraire un ensemble de generateurs
    # Pour les petits groupes, on peut utiliser une approche simple :
    # on garde les automorphismes qui ne sont pas produits par les
    # precedents. Pour les grands groupes, il faudrait un algorithme
    # plus sophistique (Schreier-Sims).
    generators = _extract_generators(all_auts, list(G.nodes()))
    return generators


def _extract_generators(automorphisms: list, nodes: list) -> list:
    """Extrait un ensemble minimal de generateurs.

    Approche simple : ajouter des automorphismes tant qu'ils generent
    de nouvelles permutations.
    """
    if not automorphisms:
        return []

    generators = []
    generated = {_perm_to_tuple(nodes, {v: v for v in nodes})}  # identite

    for aut in automorphisms:
        aut_tuple = _perm_to_tuple(nodes, aut)
        if aut_tuple not in generated:
            generators.append(aut)
            # Generer le sous-groupe avec ce nouveau generateur
            generated = _generate_group(generators, nodes)

            # Si on a genere tout le groupe, on s'arrete
            if len(generated) == len(automorphisms) + 1:  # +1 pour identite
                break

    return generators


def _perm_to_tuple(nodes: list, perm: dict) -> tuple:
    """Convertit une permutation dict en tuple pour le hachage."""
    return tuple(perm.get(v, v) for v in sorted(nodes))


def _generate_group(generators: list, nodes: list) -> set:
    """Genere le groupe a partir des generateurs (fermeture)."""
    identity = {v: v for v in nodes}
    elements = {_perm_to_tuple(nodes, identity)}

    queue = [identity] + generators[:]
    for gen in generators:
        elements.add(_perm_to_tuple(nodes, gen))

    changed = True
    while changed:
        changed = False
        new_elements = set()
        for elem_tuple in elements:
            elem = dict(zip(sorted(nodes), elem_tuple))
            for gen in generators:
                # Composer elem o gen
                composed = {v: elem[gen[v]] for v in nodes}
                ct = _perm_to_tuple(nodes, composed)
                if ct not in elements and ct not in new_elements:
                    new_elements.add(ct)
                    changed = True
        elements |= new_elements

    return elements


def preprocess(graph: BenzenoidGraph, freeze_b2: bool = True) -> dict:
    """Execute tout le pre-traitement.

    Args:
        graph: le graphe dual
        freeze_b2: si True, geler les hexagones avec b(v)>=2.
                   Si False, ne geler que ceux avec deg=6 (completement entoures).

    Returns:
        dict avec :
        - 'domains': {v: set} domaines des variables
        - 'tables': {v: list} tables filtrees pour chaque sommet non gele
        - 'generators': list de permutations (generateurs de Aut(G_D))
        - 'frozen': list des sommets geles
        - 'free': list des sommets libres
    """
    full_table = load_table()

    # Domaines
    domains = compute_domains(graph, freeze_b2=freeze_b2)

    # Hexagones geles / libres
    frozen = [v for v in range(graph.h) if graph.is_frozen(v, freeze_b2=freeze_b2)]
    free = [v for v in range(graph.h) if not graph.is_frozen(v, freeze_b2=freeze_b2)]

    # Tables filtrees pour les sommets libres avec deg >= 2
    # Les sommets de deg=1 n'ont pas besoin de contrainte de table :
    # un cycle avec un seul voisin est toujours geometriquement admissible.
    tables = {}
    for v in free:
        if graph.degree(v) >= 2:
            tables[v] = filter_table_for_vertex(graph, v, full_table)
        # else: pas de contrainte de table pour deg=1

    # Automorphismes
    generators = compute_automorphisms(graph)

    return {
        'domains': domains,
        'tables': tables,
        'generators': generators,
        'frozen': frozen,
        'free': free,
    }


# --- Test ---
if __name__ == "__main__":
    import sys
    from pathlib import Path
    from parser import parse

    if len(sys.argv) < 2:
        filepath = str(Path(__file__).parent / "data" / "example_3hex.ben")
    else:
        filepath = sys.argv[1]

    graph = parse(filepath)
    print(graph.summary())
    print()

    result = preprocess(graph)
    print(f"Geles: {result['frozen']}")
    print(f"Libres: {result['free']}")
    print(f"Generateurs Aut(G_D): {len(result['generators'])}")

    for gen in result['generators']:
        print(f"  pi: {gen}")

    for v in result['free']:
        if v in result['tables']:
            t = result['tables'][v]
            print(f"Table filtree v{v}: {len(t)} entrees")
            if len(t) <= 10:
                for entry in t:
                    print(f"    {entry}")
        else:
            print(f"v{v}: deg={graph.degree(v)}, pas de contrainte de table")
