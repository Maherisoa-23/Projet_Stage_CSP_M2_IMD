"""
Detection des liaisons C-C par distance + extraction des cycles.

Le fichier XYZ d'une solution contient typiquement carbones (C) + hydrogenes
(H). Pour la visualisation, on ignore les H : on garde le squelette carbone,
et on identifie ses liaisons par seuil de distance.

Distances de reference (Angstroms) :
  C-C simple    : ~1.46-1.54  (chaine, polyene)
  C-C aromatique: ~1.40
  C-C double    : ~1.34
  C-C triple    : ~1.20

Seuil utilise : C-C present si d in [BOND_MIN, BOND_MAX].
On ne classe PAS les liaisons en simple/double a ce stade ; ca se fait
dans kekule.py par matching topologique.

Cycles : on extrait le cycle_basis de networkx (cycles fondamentaux du
graphe). Pour un benzenoide / non-benzenoide planaire, ce sont les
"faces" 5/6/7. Suffisant pour la visualisation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np


# Seuils en Angstroms (calibres pour structures optimisees xTB)
BOND_MIN = 1.20    # < : on est sur d'une triple ou d'une erreur
BOND_MAX = 1.65    # > : pas de liaison


@dataclass
class Atom:
    element: str
    x: float
    y: float
    z: float

    def to_dict(self):
        return {"element": self.element, "x": self.x, "y": self.y, "z": self.z}


@dataclass
class MolGraph:
    """Squelette carbone d'une molecule.
    - atoms : liste des atomes C uniquement (les H sont droppes).
    - bonds : liste de tuples (i, j) avec i<j, indices dans `atoms`.
    - cycles : liste de listes d'indices, dans l'ordre cyclique.
    """
    atoms: List[Atom] = field(default_factory=list)
    bonds: List[Tuple[int, int]] = field(default_factory=list)
    cycles: List[List[int]] = field(default_factory=list)


def read_xyz(path) -> List[Atom]:
    """Lit un fichier XYZ standard. Retourne tous les atomes (C, H, ...)."""
    with open(path) as f:
        lines = f.readlines()
    if len(lines) < 3:
        return []
    try:
        n = int(lines[0].strip())
    except ValueError:
        return []
    atoms = []
    for line in lines[2:2 + n]:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            atoms.append(Atom(
                element=parts[0],
                x=float(parts[1]),
                y=float(parts[2]),
                z=float(parts[3]),
            ))
        except ValueError:
            continue
    return atoms


def detect_bonds(atoms: List[Atom],
                 bond_min: float = BOND_MIN,
                 bond_max: float = BOND_MAX,
                 only_cc: bool = True) -> List[Tuple[int, int]]:
    """Detecte les liaisons par distance.
    Si only_cc=True, ne considere que les paires C-C.

    Retourne liste de tuples (i, j) avec i<j.
    """
    n = len(atoms)
    if n < 2:
        return []

    coords = np.array([[a.x, a.y, a.z] for a in atoms])
    elements = [a.element for a in atoms]

    bonds = []
    for i in range(n):
        if only_cc and elements[i] != "C":
            continue
        for j in range(i + 1, n):
            if only_cc and elements[j] != "C":
                continue
            d = np.linalg.norm(coords[i] - coords[j])
            if bond_min <= d <= bond_max:
                bonds.append((i, j))
    return bonds


def filter_carbons(atoms: List[Atom]) -> Tuple[List[Atom], List[int]]:
    """Retourne (carbones_seulement, mapping_old_idx_to_new).
    Les indices de bonds doivent ensuite etre re-mappes via ce mapping.
    """
    carbons = []
    old_to_new = [-1] * len(atoms)
    for i, a in enumerate(atoms):
        if a.element == "C":
            old_to_new[i] = len(carbons)
            carbons.append(a)
    return carbons, old_to_new


def extract_cycles(n_atoms: int,
                   bonds: List[Tuple[int, int]]) -> List[List[int]]:
    """Extrait les cycles fondamentaux (cycle_basis de networkx).
    Pour un benzenoide / non-benzenoide planaire propre, ils correspondent
    aux faces 5/6/7. Si le graphe a des bonds parasites (cf. note dans
    build_mol_graph), cycle_basis peut retourner des 3- ou 4-cycles.
    """
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(n_atoms))
    g.add_edges_from(bonds)
    try:
        basis = nx.cycle_basis(g)
    except nx.NetworkXNoCycle:
        return []
    return [list(c) for c in basis]


def enumerate_small_cycles(n_atoms: int,
                           bonds: List[Tuple[int, int]],
                           max_len: int = 7) -> List[List[int]]:
    """Enumere TOUS les cycles simples de longueur in [3, max_len].
    Plus exhaustif que cycle_basis : utile quand on veut filtrer par taille
    avant de decider quels bonds sont legitimes.

    Complexite : exponentielle dans le pire cas, mais nos graphes sont petits
    (~50 atomes max) et les benzenoides / non-benzenoides ont peu de cycles
    par atome -> en pratique <100 ms.
    """
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(n_atoms))
    g.add_edges_from(bonds)

    # nx.simple_cycles accepte un graphe non-oriente depuis networkx 3.x,
    # mais peut sortir chaque cycle plusieurs fois (orientation, point de
    # depart). On dedupe via frozenset des sommets.
    seen = set()
    cycles = []
    try:
        for c in nx.simple_cycles(g, length_bound=max_len):
            if len(c) < 3:
                continue
            key = frozenset(c)
            if key in seen or len(key) != len(c):
                continue
            seen.add(key)
            cycles.append(list(c))
    except (nx.NetworkXNoCycle, AttributeError):
        # Fallback : si simple_cycles ne supporte pas length_bound (vieux
        # networkx) ou ne marche pas sur graphe non-oriente, on retombe sur
        # cycle_basis (moins exhaustif mais OK la plupart du temps).
        return extract_cycles(n_atoms, bonds)
    return cycles


VALID_CYCLE_SIZES = (5, 6, 7)


def build_mol_graph(xyz_path) -> MolGraph:
    """Charge un XYZ, garde uniquement les C, construit liaisons + cycles.

    Workflow :
      1. Detection des bonds C-C par seuil de distance (1.20-1.65 A).
      2. Enumeration de tous les cycles simples de taille <= 7.
      3. Filtrage : on ne garde que les cycles de taille 5/6/7 (les seules
         valides par construction de notre projet).
      4. Filtrage des bonds : on supprime ceux qui n'appartiennent a aucun
         cycle retenu. Cible les "chord bonds" parasites qui apparaissent
         dans les structures fortement tendues (ex. 4 pentagones + 4
         heptagones, ou des heptagones tres courbes ou deux atomes
         non-adjacents s'approchent < 1.65 A).
      5. Re-extraction des cycles fondamentaux sur le graphe nettoye
         (cycle_basis renvoie maintenant directement les faces 5/6/7).
    """
    raw_atoms = read_xyz(Path(xyz_path))
    if not raw_atoms:
        return MolGraph()

    carbons, _old_to_new = filter_carbons(raw_atoms)
    bonds = detect_bonds(carbons, only_cc=True)
    if not bonds:
        return MolGraph(atoms=carbons, bonds=[], cycles=[])

    # Etape 2-3 : enumeration + filtrage par taille
    all_cycles = enumerate_small_cycles(len(carbons), bonds, max_len=max(VALID_CYCLE_SIZES))
    valid_cycles = [c for c in all_cycles if len(c) in VALID_CYCLE_SIZES]

    # Etape 4 : ne garder que les bonds dans au moins un cycle retenu
    valid_edges = set()
    for c in valid_cycles:
        for k in range(len(c)):
            a, b = c[k], c[(k + 1) % len(c)]
            valid_edges.add(tuple(sorted((a, b))))

    cleaned_bonds = [
        (u, v) for (u, v) in bonds
        if tuple(sorted((u, v))) in valid_edges
    ]

    # Etape 5 : on utilise directement les cycles enumerated filtres comme
    # cycles finaux. C'est plus complet que cycle_basis (qui ne retourne
    # qu'une BASE de cycles dependante du spanning tree, donc peut
    # masquer certaines faces).
    # Dans nos non-benzenoides, simple_cycles avec length_bound=7 retourne
    # exactement les faces 5/6/7 (les "compound cycles" naturels font >= 8
    # sommets puisque 2 polycycles fusionnes partagent au moins une arete).

    return MolGraph(atoms=carbons, bonds=cleaned_bonds, cycles=valid_cycles)
