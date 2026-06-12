"""
Famille A : descripteurs de cycles et de leurs relations.

Calcule a partir d'un MolGraph :
  - comptes par taille (n_pent, n_hex, n_hept)
  - paires fusionnees par type (n_55, n_57, n_56, n_66, n_67, n_77)
  - n_azulene_units (paires 5+7 partageant une arete = 2 atomes adjacents)
  - n_stone_wales (cluster 5-7-7-5 mutuellement fusionnes)
  - n_3_fused_atoms (atomes partages par >=3 cycles = sites de stress)
  - statistiques du graphe d'hexagones etendu :
      dual_diameter, dual_radius, dual_max_degree, dual_n_components

Toutes les fonctions sont PURES (pas d'effet de bord, pas d'I/O).
Reutilisables independamment.
"""

from typing import Dict, List, Set

from ...molviz.bonds import MolGraph


def _shared_atoms(cycle_a, cycle_b) -> int:
    """Nombre d'atomes communs entre deux cycles."""
    return len(set(cycle_a.atoms) & set(cycle_b.atoms))


def _share_edge(mol: MolGraph, cycle_a, cycle_b) -> bool:
    """True ssi cycles partagent au moins une ARETE (= 2 atomes consecutifs
    dans l'un et l'autre). Plus fort que partage de sommet."""
    common = set(cycle_a.atoms) & set(cycle_b.atoms)
    if len(common) < 2:
        return False
    bonds_set = {tuple(sorted(b)) for b in mol.bonds}
    # Cherche une arete (u,v) avec u,v dans common ET (u,v) dans bonds
    common_list = list(common)
    for i in range(len(common_list)):
        for j in range(i + 1, len(common_list)):
            key = tuple(sorted((common_list[i], common_list[j])))
            if key in bonds_set:
                return True
    return False


def compute_cycle_descriptors(mol: MolGraph) -> Dict[str, int]:
    """Calcule les descripteurs de la famille A."""
    if not mol.cycles:
        return _empty_descriptors()

    cycles = mol.cycles
    n_cycles = len(cycles)

    # Comptes par taille
    n_pent = sum(1 for c in cycles if c.size == 5)
    n_hex = sum(1 for c in cycles if c.size == 6)
    n_hept = sum(1 for c in cycles if c.size == 7)

    # Paires fusionnees (au moins 1 atome commun)
    n_55 = n_57 = n_56 = n_66 = n_67 = n_77 = 0
    n_azulene = 0
    fused_edges_dual = []  # liste de (i, j) pour construire le graphe dual

    for i in range(n_cycles):
        for j in range(i + 1, n_cycles):
            ca, cb = cycles[i], cycles[j]
            common = _shared_atoms(ca, cb)
            if common == 0:
                continue
            # Comptage par type de paire
            sa, sb = sorted([ca.size, cb.size])
            key = (sa, sb)
            if key == (5, 5):    n_55 += 1
            elif key == (5, 6):  n_56 += 1
            elif key == (5, 7):
                n_57 += 1
                if _share_edge(mol, ca, cb):
                    n_azulene += 1
            elif key == (6, 6):  n_66 += 1
            elif key == (6, 7):  n_67 += 1
            elif key == (7, 7):  n_77 += 1
            # Graphe dual : arete entre cycles partageant au moins 1 atome
            fused_edges_dual.append((i, j))

    # Atomes partages par >=3 cycles (sites de stress topologique)
    atom_cycle_count: Dict[int, int] = {}
    for c in cycles:
        for a in c.atoms:
            atom_cycle_count[a] = atom_cycle_count.get(a, 0) + 1
    n_3_fused_atoms = sum(1 for v in atom_cycle_count.values() if v >= 3)

    # Stone-Wales pattern : cluster 5-7-7-5 mutuellement fusionnes.
    # On compte les sous-graphes induits du dual avec exactement
    # 2 pent + 2 hept tous mutuellement adjacents (= clique K_4 dans le dual).
    n_stone_wales = _count_stone_wales(cycles, fused_edges_dual)

    # Graphe dual : statistiques globales
    dual_stats = _dual_graph_stats(n_cycles, fused_edges_dual)

    return {
        "n_pent": n_pent,
        "n_hex": n_hex,
        "n_hept": n_hept,
        "n_cycles_total": n_cycles,
        "n_55": n_55, "n_57": n_57, "n_56": n_56,
        "n_66": n_66, "n_67": n_67, "n_77": n_77,
        "n_azulene_units": n_azulene,
        "n_stone_wales": n_stone_wales,
        "n_3_fused_atoms": n_3_fused_atoms,
        "dual_diameter": dual_stats["diameter"],
        "dual_radius": dual_stats["radius"],
        "dual_max_degree": dual_stats["max_degree"],
        "dual_n_components": dual_stats["n_components"],
    }


def _empty_descriptors() -> Dict[str, int]:
    """Valeurs par defaut pour molecule sans cycles (ne devrait pas arriver
    pour nos h3-h9 mais robustesse)."""
    return {
        "n_pent": 0, "n_hex": 0, "n_hept": 0, "n_cycles_total": 0,
        "n_55": 0, "n_57": 0, "n_56": 0, "n_66": 0, "n_67": 0, "n_77": 0,
        "n_azulene_units": 0,
        "n_stone_wales": 0,
        "n_3_fused_atoms": 0,
        "dual_diameter": 0, "dual_radius": 0,
        "dual_max_degree": 0, "dual_n_components": 0,
    }


def _count_stone_wales(cycles, fused_edges_dual) -> int:
    """Compte les motifs Stone-Wales : clusters de 4 cycles (2 pent + 2 hept)
    tous mutuellement fusionnes (clique K_4 dans le dual).

    Note : c'est une approximation du motif chimique reel. Un vrai
    Stone-Wales en graphene est un defaut precis ou 2 hex ont permute
    en 2 pent + 2 hept ; topologiquement, ca donne 4 cycles disposes
    en "papillon". On cherche les 4-cliques avec composition 2pent+2hept.
    """
    if len(cycles) < 4:
        return 0
    # Map index -> set des voisins dans le dual
    adj: Dict[int, Set[int]] = {i: set() for i in range(len(cycles))}
    for u, v in fused_edges_dual:
        adj[u].add(v)
        adj[v].add(u)

    sw_count = 0
    pent_idx = [i for i, c in enumerate(cycles) if c.size == 5]
    hept_idx = [i for i, c in enumerate(cycles) if c.size == 7]
    if len(pent_idx) < 2 or len(hept_idx) < 2:
        return 0

    # On itere sur toutes les paires (pent_a, pent_b) puis on cherche
    # 2 hept communs adjacents aux deux et a eux-memes
    for i in range(len(pent_idx)):
        pa = pent_idx[i]
        for j in range(i + 1, len(pent_idx)):
            pb = pent_idx[j]
            # Les 2 pent doivent etre adjacents
            if pb not in adj[pa]:
                continue
            # Hept commun voisins des 2 pent
            common_hept = (adj[pa] & adj[pb]) & set(hept_idx)
            if len(common_hept) < 2:
                continue
            common_hept_list = sorted(common_hept)
            for k in range(len(common_hept_list)):
                ha = common_hept_list[k]
                for l in range(k + 1, len(common_hept_list)):
                    hb = common_hept_list[l]
                    # Les 2 hept doivent etre adjacents
                    if hb in adj[ha]:
                        sw_count += 1
    return sw_count


def _dual_graph_stats(n_nodes: int, edges) -> Dict[str, int]:
    """Calcule diametre, rayon, degre max, nb composantes du graphe dual."""
    if n_nodes == 0:
        return {"diameter": 0, "radius": 0, "max_degree": 0, "n_components": 0}

    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(n_nodes))
    g.add_edges_from(edges)

    n_components = nx.number_connected_components(g)
    max_degree = max((d for _, d in g.degree()), default=0)

    # Diametre / rayon : seulement si connexe
    if n_components == 1 and n_nodes > 1:
        try:
            diameter = nx.diameter(g)
            radius = nx.radius(g)
        except nx.NetworkXError:
            diameter = radius = 0
    elif n_nodes == 1:
        diameter = radius = 0
    else:
        # Graphe non connexe : on prend le max sur les composantes
        diameter = 0
        radius = 0
        for comp in nx.connected_components(g):
            sub = g.subgraph(comp)
            if len(comp) > 1:
                try:
                    diameter = max(diameter, nx.diameter(sub))
                    radius = max(radius, nx.radius(sub))
                except nx.NetworkXError:
                    pass

    return {
        "diameter": int(diameter),
        "radius": int(radius),
        "max_degree": int(max_degree),
        "n_components": int(n_components),
    }
