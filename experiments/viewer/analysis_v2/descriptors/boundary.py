"""
Famille B : descripteurs de bordure.

Calcule a partir d'un MolGraph :
  - n_boundary_atoms, n_interior_atoms : separation interne / externe
    Un atome interieur d'un PAH est lie a 3 autres carbones (les hydrogenes
    sont absents de notre representation). Un atome de bordure est lie a
    2 carbones (et implicitement 1 hydrogene).
  - boundary_length : nb d'aretes entre atomes de bordure
  - Groupes Varet (def 2.2.4) : sequences consecutives d'atomes de bordure
    appartenant a un meme cycle. Compte par taille :
      n_solo (1), n_duo (2), n_trio (3), n_quatuor (4), n_groups_5plus (>=5)
  - irregularity_param (Bouwman et al., def 2.2.5) :
        B = (N3 + N4) / (N1 + N2 + N3 + N4)
    avec Ni = nb de carbones appartenant a un groupe de taille i.
  - n_<size>_at_boundary : combien de cycles de chaque taille touchent la bordure
  - <size>_boundary_ratio : fraction des cycles de cette taille qui touchent
    la bordure (NULL si denominateur 0).

Toutes les fonctions sont PURES.

Note : pour les molecules avec 5/7, la definition Varet des groupes
(carbones consecutifs deg=2 d'un meme hexagone) s'etend naturellement aux
pent/hept. On parcourt la bordure et on compte les sequences maximales
de carbones de bordure consecutifs partageant un meme cycle.
"""

from typing import Dict, List, Set, Tuple

from ...molviz.bonds import MolGraph


def compute_boundary_descriptors(mol: MolGraph) -> Dict[str, float]:
    """Calcule les descripteurs de la famille B."""
    if not mol.atoms or not mol.bonds:
        return _empty()

    # Degre de chaque atome dans le squelette carbone
    deg: Dict[int, int] = {i: 0 for i in range(len(mol.atoms))}
    for u, v in mol.bonds:
        deg[u] += 1
        deg[v] += 1

    boundary_atoms: Set[int] = {i for i, d in deg.items() if d == 2}
    interior_atoms: Set[int] = {i for i, d in deg.items() if d >= 3}

    n_boundary = len(boundary_atoms)
    n_interior = len(interior_atoms)

    # Aretes de bordure : (u, v) avec u et v tous deux dans boundary_atoms
    boundary_length = sum(
        1 for u, v in mol.bonds
        if u in boundary_atoms and v in boundary_atoms
    )

    # Groupes Varet : pour chaque cycle, sequences consecutives d'atomes
    # de bordure. Un atome peut appartenir a plusieurs cycles ; on compte
    # les groupes par cycle (consistant avec Varet def 2.2.4).
    group_sizes: List[int] = []  # tailles de tous les groupes (multi-cycles)
    for c in mol.cycles:
        n = len(c.atoms)
        if n == 0:
            continue
        # Marqueur : atome de bordure ou non, dans l'ordre cyclique
        in_boundary = [a in boundary_atoms for a in c.atoms]
        if not any(in_boundary):
            continue
        # Trouver un point de demarrage hors-bordure (si possible) pour
        # eviter de couper un groupe au milieu. Si tous en bordure
        # (cycle isole = mol = 1 seul cycle), on demarre a 0.
        start = 0
        for k in range(n):
            if not in_boundary[k]:
                start = (k + 1) % n
                break
        # Parcours dans l'ordre cyclique a partir de `start`
        current_size = 0
        for offset in range(n):
            k = (start + offset) % n
            if in_boundary[k]:
                current_size += 1
            else:
                if current_size > 0:
                    group_sizes.append(current_size)
                    current_size = 0
        # Fermeture (cycle isole : on n'a pas trouve de hors-bordure)
        if current_size > 0:
            group_sizes.append(current_size)

    # Comptage par taille
    n_solo = sum(1 for s in group_sizes if s == 1)
    n_duo = sum(1 for s in group_sizes if s == 2)
    n_trio = sum(1 for s in group_sizes if s == 3)
    n_quatuor = sum(1 for s in group_sizes if s == 4)
    n_groups_5plus = sum(1 for s in group_sizes if s >= 5)

    # Parametre d'irregularite : Ni = nb d'ATOMES (pas de groupes) dans
    # un groupe de taille i. N_i = i * (nb de groupes de taille i).
    n_atoms_g1 = 1 * n_solo
    n_atoms_g2 = 2 * n_duo
    n_atoms_g3 = 3 * n_trio
    n_atoms_g4 = 4 * n_quatuor
    denom = n_atoms_g1 + n_atoms_g2 + n_atoms_g3 + n_atoms_g4
    irregularity = (n_atoms_g3 + n_atoms_g4) / denom if denom > 0 else None

    # Cycles touchant la bordure (= ont au moins un atome de bordure)
    n_pent_at_b = n_hex_at_b = n_hept_at_b = 0
    n_pent_total = n_hex_total = n_hept_total = 0
    for c in mol.cycles:
        touches = any(a in boundary_atoms for a in c.atoms)
        if c.size == 5:
            n_pent_total += 1
            if touches: n_pent_at_b += 1
        elif c.size == 6:
            n_hex_total += 1
            if touches: n_hex_at_b += 1
        elif c.size == 7:
            n_hept_total += 1
            if touches: n_hept_at_b += 1

    pent_b_ratio = (n_pent_at_b / n_pent_total) if n_pent_total > 0 else None
    hept_b_ratio = (n_hept_at_b / n_hept_total) if n_hept_total > 0 else None

    return {
        "n_boundary_atoms": int(n_boundary),
        "n_interior_atoms": int(n_interior),
        "boundary_length": int(boundary_length),
        "n_solo": int(n_solo),
        "n_duo": int(n_duo),
        "n_trio": int(n_trio),
        "n_quatuor": int(n_quatuor),
        "n_groups_5plus": int(n_groups_5plus),
        "irregularity_param": irregularity,
        "n_pent_at_boundary": int(n_pent_at_b),
        "n_hept_at_boundary": int(n_hept_at_b),
        "n_hex_at_boundary": int(n_hex_at_b),
        "pent_boundary_ratio": pent_b_ratio,
        "hept_boundary_ratio": hept_b_ratio,
    }


def _empty() -> Dict[str, float]:
    return {
        "n_boundary_atoms": 0, "n_interior_atoms": 0, "boundary_length": 0,
        "n_solo": 0, "n_duo": 0, "n_trio": 0, "n_quatuor": 0, "n_groups_5plus": 0,
        "irregularity_param": None,
        "n_pent_at_boundary": 0, "n_hept_at_boundary": 0, "n_hex_at_boundary": 0,
        "pent_boundary_ratio": None, "hept_boundary_ratio": None,
    }
