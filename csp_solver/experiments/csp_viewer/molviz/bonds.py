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
    Pour un benzenoide / non-benzenoide planaire, ils correspondent aux
    faces 5/6/7. Les cycles sont retournes dans l'ordre cyclique des
    sommets (utile pour le rendu : permet de tracer le polygone).
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


def build_mol_graph(xyz_path) -> MolGraph:
    """Charge un XYZ, garde uniquement les C, construit liaisons + cycles.

    Retourne un MolGraph pret pour le rendu et le matching Kekule.
    """
    raw_atoms = read_xyz(Path(xyz_path))
    if not raw_atoms:
        return MolGraph()

    carbons, _old_to_new = filter_carbons(raw_atoms)
    bonds = detect_bonds(carbons, only_cc=True)
    cycles = extract_cycles(len(carbons), bonds)

    return MolGraph(atoms=carbons, bonds=bonds, cycles=cycles)
