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


def _ring_of_vertex(graph: BenzenoidGraph, v: int) -> list:
    """Construit le 'ring' du sommet v : une liste de longueur 6 (= nb de
    cotes de l'hexagone) ou ring[p] vaut l'index du voisin partageant le
    cote p, ou None si le cote p est libre.

    L'ordre des positions est celui de graph.patterns[v] (et de
    graph.edge_positions, qui donne pour chaque arete duale (v,u) la
    position du cote dans v)."""
    n_sides = len(graph.patterns[v])
    ring = [None] * n_sides
    for u in graph.neighbors(v):
        pos = graph.edge_positions[(v, u)][0]
        ring[pos] = u
    return ring


def _realize_ring(ring: list, target_n: int) -> list:
    """Genere les realisations topologiques du ring en taille target_n.

    Seuls les COTES LIBRES (None) bougent ; les voisins gardent leur
    disposition relative (c'est exactement ce que fait la reconstruction
    geometrique en contractant/expansant) :

      - target_n == len(ring)      : ring inchange (hexagone reste hexagone).
      - target_n == len(ring) - 1  : contraction (-> pentagone). On fusionne
        deux cotes libres ADJACENTS (cycliques) en un seul = suppression d'un
        sommet interieur libre. Plusieurs realisations si plusieurs paires.
      - target_n == len(ring) + 1  : expansion (-> heptagone). On dedouble un
        cote libre = insertion d'un sommet. Plusieurs realisations si
        plusieurs cotes libres.

    Retourne une liste de rings (longueur target_n), dedupliquee. Vide si la
    transformation est topologiquement impossible (coherent avec
    has_interior_free_vertex / has_free_side de compute_domains)."""
    cur = len(ring)
    out = []
    if target_n == cur:
        out.append(list(ring))
    elif target_n == cur - 1:
        for i in range(cur):
            j = (i + 1) % cur
            if ring[i] is None and ring[j] is None:
                out.append([ring[k] for k in range(cur) if k != j])
    elif target_n == cur + 1:
        for i in range(cur):
            if ring[i] is None:
                out.append(ring[:i + 1] + [None] + ring[i + 1:])
    # dedupe (deux fusions/dedoublements peuvent donner le meme ring)
    uniq, seen = [], set()
    for r in out:
        key = tuple(-1 if x is None else x for x in r)
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _seq_variants(seq) -> set:
    """Toutes les rotations + reflexions cycliques d'une sequence."""
    n = len(seq)
    s = list(seq)
    variants = set()
    for base in (s, s[::-1]):
        for k in range(n):
            variants.add(tuple(base[k:] + base[:k]))
    return variants


def filter_table_for_vertex(graph: BenzenoidGraph, v: int,
                            full_table: dict) -> list:
    """Genere les tuples extensionnels (x_v, x_u1, x_u2, ...) admissibles
    pour le sommet v, ou (u1, u2, ...) = graph.neighbors(v) -- exactement
    l'ordre utilise par model.py (contrainte C3 : scope in tables[v]).

    Pour chaque taille candidate n in {5,6,7} :
      1. On 'realise' le ring de v en taille n via _realize_ring
         (contraction/expansion des cotes LIBRES uniquement ; les voisins
         conservent leur disposition relative).
      2. Pour chaque entree seq de T(n) ayant le bon nombre de voisins, on
         cherche une rotation/reflexion de seq qui aligne les positions des
         voisins de la realisation avec les positions non-nulles de seq.
      3. Si l'alignement existe, on lit la taille de chaque voisin et on
         construit le tuple dans l'ordre neighbors(v).

    IMPORTANT (correction mai 2026) : cette version verifie la DISPOSITION
    complete des voisins, pas seulement leurs tailles. L'ancienne version
    ne gardait que les entrees a bloc consecutif (_is_consecutive_block) et
    ne comparait que les tailles -- correcte uniquement pour b(v)=1. Avec
    --no-freeze, les sommets b(v)>=2 deviennent libres et recevaient une
    contrainte mal posee : elle acceptait a tort des voisinages comme
    [7,0,7,0,0,0] (deux heptagones SEPARES, absent de la table) en les
    confondant avec [7,7,0,0,0,0] (deux heptagones ADJACENTS, present).
    Le matching par disposition elimine ces faux positifs.
    """
    neighbors = graph.neighbors(v)
    if not neighbors:
        return []
    ring = _ring_of_vertex(graph, v)
    deg = len(neighbors)

    compatible = set()
    for n in (5, 6, 7):
        seqs = full_table.get(n, [])
        if not seqs:
            continue
        realizations = _realize_ring(ring, n)
        if not realizations:
            continue
        # Positions des voisins pour chaque realisation (constantes par n).
        realized_occ = [
            (realized, [i for i in range(len(realized))
                        if realized[i] is not None])
            for realized in realizations
        ]
        for seq in seqs:
            if sum(1 for s in seq if s != 0) != deg:
                continue
            for var in _seq_variants(seq):
                var_occ = [i for i in range(len(var)) if var[i] != 0]
                for realized, ring_occ in realized_occ:
                    if var_occ != ring_occ:
                        continue
                    sizes_by_nbr = {realized[i]: var[i] for i in ring_occ}
                    entry = (n,) + tuple(sizes_by_nbr[u] for u in neighbors)
                    compatible.add(entry)
    return sorted(compatible)


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


def preprocess(graph: BenzenoidGraph, freeze_b2: bool = True,
               table_path=None) -> dict:
    """Execute tout le pre-traitement.

    Args:
        graph: le graphe dual
        freeze_b2: si True, geler les hexagones avec b(v)>=2.
                   Si False, ne geler que ceux avec deg=6 (completement entoures).
        table_path: chemin d'une table de voisinage alternative (cf.
                    utils/table.py::load_table). None = table par defaut.

    Returns:
        dict avec :
        - 'domains': {v: set} domaines des variables
        - 'tables': {v: list} tables filtrees pour chaque sommet non gele
        - 'generators': list de permutations (generateurs de Aut(G_D))
        - 'frozen': list des sommets geles
        - 'free': list des sommets libres
    """
    full_table = load_table(table_path)

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
