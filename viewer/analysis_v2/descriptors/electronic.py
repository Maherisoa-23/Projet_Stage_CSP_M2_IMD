"""
Famille D : descripteurs electroniques.

Wrapper sur les calculs existants de molviz/{kekule,rbo,clar} + nouveaux :
  - n_kekule, is_exact, n_radicals               (matching max + enumeration)
  - clar_number, n_clar_covers                   (couvertures de Clar)
  - cbo_available, cbo_mean/max par taille de cycle  (RBO)
  - radical_on_pent/hex/hept_freq                (NOUVEAU : localisation des radicaux)
  - radical_at_boundary_freq                     (NOUVEAU)
  - n_aromatic_islands, largest_aromatic_island  (NOUVEAU : composantes hex >2.5)

Note sur la localisation des radicaux :
  Pour les molecules radicalaires (n_radicals > 0), on agrege sur toutes
  les configurations de matching max enumerees. Pour chaque atome A,
  on calcule la frequence d'apparition de A comme radical sur les
  configurations. Puis on regroupe par type de cycle hote.
"""

from typing import Dict, Optional, Set

from ...molviz.bonds import MolGraph
from ...molviz.kekule import enumerate_kekule, assign_kekule
from ...molviz.rbo import compute_rbo
from ...molviz.clar import enumerate_clar_covers


# Plafonds (alignes sur analysis/compute.py)
DEFAULT_MAX_KEKULE = 10000
DEFAULT_MAX_CLAR = 200

# Seuil au-dessus duquel un hex est considere "aromatique" pour aromatic islands
AROMATIC_HEX_THRESHOLD = 2.5


def compute_electronic_descriptors(mol: MolGraph,
                                    max_kekule: int = DEFAULT_MAX_KEKULE,
                                    max_clar: int = DEFAULT_MAX_CLAR) -> Dict:
    """Calcule tous les descripteurs electroniques d'une molecule."""
    if not mol.bonds:
        return _empty()

    # 1. Matching max + enumeration Kekule
    matching = assign_kekule(mol)
    kekule_list, is_exact = enumerate_kekule(mol, max_count=max_kekule)
    n_kekule = len(kekule_list)
    n_radicals = len(matching.radicals)

    # 2. Couvertures de Clar
    clar_covers, _ = enumerate_clar_covers(mol, max_count=max_clar)
    clar_number = clar_covers[0].n_sextets if clar_covers else 0
    n_clar_covers = len(clar_covers)

    # 3. RBO agrege
    rbo = compute_rbo(mol, max_count=max_kekule)
    cbo_available = 1 if rbo.available else 0

    # Aggregation CBO par taille de cycle
    cbo_by_size = {5: [], 6: [], 7: []}
    if rbo.available:
        for cyc, val in zip(mol.cycles, rbo.cbo):
            if cyc.size in cbo_by_size:
                cbo_by_size[cyc.size].append(val)

    def _stats(lst):
        if not lst:
            return None, None
        return sum(lst) / len(lst), max(lst)

    mean_hex, max_hex = _stats(cbo_by_size[6])
    mean_pent, max_pent = _stats(cbo_by_size[5])
    mean_hept, max_hept = _stats(cbo_by_size[7])

    # 4. Localisation des radicaux
    rad_on_pent = rad_on_hex = rad_on_hept = None
    rad_at_boundary = None
    if n_radicals > 0 and kekule_list:
        rad_locations = _radical_locations(mol, kekule_list)
        rad_on_pent = rad_locations["pent_freq"]
        rad_on_hex = rad_locations["hex_freq"]
        rad_on_hept = rad_locations["hept_freq"]
        rad_at_boundary = rad_locations["boundary_freq"]

    # 5. Aromatic islands (hex avec cbo > seuil, connexes dans le dual)
    n_islands, largest = 0, 0
    if rbo.available and any(c.size == 6 for c in mol.cycles):
        n_islands, largest = _aromatic_islands(mol, rbo.cbo,
                                                AROMATIC_HEX_THRESHOLD)

    return {
        "n_kekule": int(n_kekule),
        "is_exact": int(bool(is_exact)),
        "n_radicals": int(n_radicals),
        "clar_number": int(clar_number),
        "n_clar_covers": int(n_clar_covers),
        "cbo_available": int(cbo_available),
        "cbo_mean_hex": mean_hex, "cbo_max_hex": max_hex,
        "cbo_mean_pent": mean_pent, "cbo_max_pent": max_pent,
        "cbo_mean_hept": mean_hept, "cbo_max_hept": max_hept,
        "radical_on_pent_freq": rad_on_pent,
        "radical_on_hex_freq": rad_on_hex,
        "radical_on_hept_freq": rad_on_hept,
        "radical_at_boundary_freq": rad_at_boundary,
        "n_aromatic_islands": int(n_islands),
        "largest_aromatic_island": int(largest),
    }


def _radical_locations(mol: MolGraph, kekule_list) -> Dict[str, float]:
    """Pour chaque atome, frequence d'etre radical dans les configurations
    enumerees. Puis aggrege par type de cycle hote et bordure.

    Returns: dict avec pent_freq, hex_freq, hept_freq (somme des freq des
    atomes appartenant a au moins un cycle de cette taille / nb_total_radicals
    sur l'echantillon) ET boundary_freq.

    Plus precisement :
      Pour chaque atome A :
        rad_count[A] = nb de configurations ou A est radical
      Total possibles = N * n_radicals (N = nb config, chacune a n_radicals radicaux)
      pent_freq = somme(rad_count[A] pour A dans un pent) / total
    """
    n_atoms = len(mol.atoms)
    rad_count = [0] * n_atoms
    for k in kekule_list:
        for a in k.radicals:
            rad_count[a] += 1
    total = sum(rad_count)
    if total == 0:
        return {"pent_freq": 0.0, "hex_freq": 0.0,
                "hept_freq": 0.0, "boundary_freq": 0.0}

    # Atomes par type de cycle (un atome peut etre dans plusieurs cycles
    # de tailles differentes ; on additionne sans normaliser : un atome
    # dans (1 pent + 1 hex) compte pour les deux).
    in_pent = set()
    in_hex = set()
    in_hept = set()
    for c in mol.cycles:
        target = (in_pent if c.size == 5 else
                  in_hex if c.size == 6 else
                  in_hept if c.size == 7 else None)
        if target is not None:
            target.update(c.atoms)

    pent_freq = sum(rad_count[a] for a in in_pent) / total
    hex_freq = sum(rad_count[a] for a in in_hex) / total
    hept_freq = sum(rad_count[a] for a in in_hept) / total

    # Bordure : atomes de degre 2
    deg = [0] * n_atoms
    for u, v in mol.bonds:
        deg[u] += 1
        deg[v] += 1
    boundary = {i for i, d in enumerate(deg) if d == 2}
    boundary_freq = sum(rad_count[a] for a in boundary) / total

    return {
        "pent_freq": float(pent_freq),
        "hex_freq": float(hex_freq),
        "hept_freq": float(hept_freq),
        "boundary_freq": float(boundary_freq),
    }


def _aromatic_islands(mol: MolGraph, cbo_per_cycle, threshold: float):
    """Composantes connexes dans le dual des HEX avec CBO > threshold.

    Returns (n_islands, largest_size).
    """
    # Indices des hex aromatiques
    aromatic_hex_indices = [
        i for i, (c, val) in enumerate(zip(mol.cycles, cbo_per_cycle))
        if c.size == 6 and val is not None and val > threshold
    ]
    if not aromatic_hex_indices:
        return 0, 0
    # Sous-graphe induit sur ces hex (arete = partage atome)
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(aromatic_hex_indices)
    for i in range(len(aromatic_hex_indices)):
        for j in range(i + 1, len(aromatic_hex_indices)):
            ia, ib = aromatic_hex_indices[i], aromatic_hex_indices[j]
            if set(mol.cycles[ia].atoms) & set(mol.cycles[ib].atoms):
                g.add_edge(ia, ib)
    comps = list(nx.connected_components(g))
    return len(comps), max((len(c) for c in comps), default=0)


def _empty() -> Dict:
    return {
        "n_kekule": 0, "is_exact": 1, "n_radicals": 0,
        "clar_number": 0, "n_clar_covers": 0,
        "cbo_available": 0,
        "cbo_mean_hex": None, "cbo_max_hex": None,
        "cbo_mean_pent": None, "cbo_max_pent": None,
        "cbo_mean_hept": None, "cbo_max_hept": None,
        "radical_on_pent_freq": None, "radical_on_hex_freq": None,
        "radical_on_hept_freq": None, "radical_at_boundary_freq": None,
        "n_aromatic_islands": 0, "largest_aromatic_island": 0,
    }
