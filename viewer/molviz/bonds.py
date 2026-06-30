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


# Seuils en Angstroms.
# BOND_MAX a 2.10 pour tolerer les reconstructions non-relaxees du designer
# en mode skip xTB : a l'interface 5-6-7, le placement BFS rigide a 1.42 A
# fait sortir certaines aretes jusqu'a ~2.01 A (mesure empirique). Sous un
# seuil plus bas, ces aretes etaient ratees -> carbones sous-coordonnes ->
# Kekule les marquait radicaux -> rendu en spheres violettes "flottantes"
# au-dessus du squelette.
#
# 2.10 laisse passer quelques DIAGONALES accidentelles (2nd voisins a ~2.0-2.1
# dans les cycles tres deformes), mais celles-ci sont eliminees ensuite par :
#   1. mutual_knn_filter  : borne chaque atome a ses 3 plus proches voisins
#      mutuels -> supprime la sur-coordination (deg > 3).
#   2. prune_small_cycle_diagonals : retire l'arete la plus longue de tout
#      3- ou 4-cycle (= diagonale parasite), sans jamais sous-coordonner.
# Cette combinaison (mesuree sur 170 sols designer) reduit a la fois les
# carbones sous-coordonnes (13 -> 10, le reste etant de VRAIS degre-1) et les
# cycles anormaux (12 -> 10) par rapport a l'ancien filtre "cycle <= 8".
# Pas d'effet de bord sur les structures optimisees xTB (aromatique 1.39-1.42 A,
# single 1.54 A, tres en dessous de 2.10 A).
BOND_MIN = 1.20    # < : on est sur d'une triple ou d'une erreur
BOND_MAX = 2.10    # > : pas de liaison
KNN_MAX_NEIGHBORS = 3  # un carbone sp2 a au plus 3 voisins C


@dataclass
class Atom:
    element: str
    x: float
    y: float
    z: float

    def to_dict(self):
        return {"element": self.element, "x": self.x, "y": self.y, "z": self.z}


@dataclass
class Cycle:
    """Un cycle (face planaire) du squelette carbone.
    - atoms  : liste ordonnee des indices d'atomes (sequence cyclique).
    - anomaly: True si la taille n'est pas dans {5,6,7} (signal d'un bond
               parasite ou d'une geometrie cassee).
    """
    atoms: List[int]
    anomaly: bool = False

    @property
    def size(self) -> int:
        return len(self.atoms)


@dataclass
class MolGraph:
    """Squelette carbone d'une molecule.
    - atoms : liste des atomes C uniquement (les H sont droppes).
    - bonds : liste de tuples (i, j) avec i<j, indices dans `atoms`.
    - cycles : liste de Cycle, idealement les faces 5/6/7 du plongement planaire.
    """
    atoms: List[Atom] = field(default_factory=list)
    bonds: List[Tuple[int, int]] = field(default_factory=list)
    cycles: List["Cycle"] = field(default_factory=list)


# ===== Helpers reutilises par kekule.py / clar.py / rbo.py =====

def build_nx_graph(mol: MolGraph):
    """Construit un networkx.Graph du squelette carbone.

    Sommets = indices d'atomes (0..n-1). Aretes = mol.bonds.
    Import local de networkx pour ne pas penaliser les imports module
    quand on n'utilise pas cette fonction.
    """
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(len(mol.atoms)))
    g.add_edges_from(mol.bonds)
    return g


def bond_index_map(mol: MolGraph) -> dict:
    """Retourne {tuple(sorted((u,v))): i} pour mol.bonds.

    Utilise pour convertir une arete (u,v) en son index dans mol.bonds,
    pour pouvoir indexer bond_orders[i].
    """
    return {tuple(sorted(p)): i for i, p in enumerate(mol.bonds)}


def cycle_edge_indices(mol: MolGraph, bond_idx: dict = None):
    """Pour chaque cycle de mol.cycles, retourne la liste des indices
    d'aretes (dans mol.bonds) qui le composent.

    Une arete d'un cycle qui n'apparait PAS dans mol.bonds est ignoree
    silencieusement (cas pathologique : bonds.py a rate une liaison).

    Args:
        mol      : MolGraph
        bond_idx : dict precalcule {tuple(sorted): i}. Si None, recalcule.

    Returns:
        List[List[int]] : un sous-tableau d'indices par cycle.
    """
    if bond_idx is None:
        bond_idx = bond_index_map(mol)
    out = []
    for c in mol.cycles:
        atoms = c.atoms
        edges = []
        for k in range(len(atoms)):
            u, v = atoms[k], atoms[(k + 1) % len(atoms)]
            key = (min(u, v), max(u, v))
            if key in bond_idx:
                edges.append(bond_idx[key])
        out.append(edges)
    return out


def read_xyz_text(text: str) -> List[Atom]:
    """Parse un XYZ standard depuis une string. Retourne tous les atomes."""
    lines = text.splitlines()
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


def read_xyz(path) -> List[Atom]:
    """Lit un fichier XYZ standard. Retourne tous les atomes (C, H, ...)."""
    with open(path) as f:
        return read_xyz_text(f.read())


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


def mutual_knn_filter(atoms: List[Atom],
                      bonds: List[Tuple[int, int]],
                      k: int = KNN_MAX_NEIGHBORS) -> List[Tuple[int, int]]:
    """Garde une arete (i,j) seulement si j est parmi les k plus proches
    voisins de i ET i parmi les k plus proches de j (k-NN mutuel).

    Borne la coordination de chaque atome a k. Pour un PAH (carbones sp2,
    au plus 3 voisins C), k=3 elimine les diagonales accidentelles captees
    par le seuil de distance sans jamais retirer une vraie liaison du
    squelette : une vraie liaison est toujours parmi les 3 plus proches des
    deux cotes, alors qu'une diagonale (2nd voisin) ne l'est generalement
    pas d'au moins un cote.
    """
    n = len(atoms)
    if n < 2 or not bonds:
        return list(bonds)
    coords = np.array([[a.x, a.y, a.z] for a in atoms])

    # Distances uniquement entre atomes deja relies (suffit pour le tri kNN
    # restreint au voisinage candidat).
    from collections import defaultdict
    nbr_dist = defaultdict(list)
    for (u, v) in bonds:
        d = float(np.linalg.norm(coords[u] - coords[v]))
        nbr_dist[u].append((d, v))
        nbr_dist[v].append((d, u))

    # k plus proches voisins de chaque atome parmi les candidats
    knn = {}
    for v, lst in nbr_dist.items():
        lst.sort()
        knn[v] = {w for _, w in lst[:k]}

    kept = []
    for (u, v) in bonds:
        if v in knn.get(u, ()) and u in knn.get(v, ()):
            kept.append((u, v))
    return kept


def prune_small_cycle_diagonals(atoms: List[Atom],
                                bonds: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Retire l'arete la plus longue de chaque 3- ou 4-cycle (= diagonale
    parasite issue d'une geometrie deformee), MAIS uniquement si ses deux
    extremites conservent un degre >= 2 apres retrait.

    Une vraie face d'un PAH a au moins 5 cotes ; un 3- ou 4-cycle est donc
    toujours un artefact (une corde a travers un cycle reel). On retire la
    corde et pas un cote du vrai cycle en ciblant l'arete la plus LONGUE du
    petit cycle (la corde traverse, donc plus longue que les cotes). La
    garde "degre >= 2" empeche de creer un atome sous-coordonne.

    Iteratif : retirer une corde peut en reveler une autre (cycles imbriques).
    """
    import networkx as nx

    coords = np.array([[a.x, a.y, a.z] for a in atoms])
    dist = lambda e: float(np.linalg.norm(coords[e[0]] - coords[e[1]]))
    cur = set(tuple(sorted(e)) for e in bonds)

    while True:
        g = nx.Graph()
        g.add_edges_from(cur)
        deg = dict(g.degree())
        removed = False
        for cyc in nx.cycle_basis(g):
            if len(cyc) not in (3, 4):
                continue
            edges = [tuple(sorted((cyc[i], cyc[(i + 1) % len(cyc)])))
                     for i in range(len(cyc))]
            edges = [e for e in edges if e in cur]
            if not edges:
                continue
            # Arete la plus longue dont le retrait ne sous-coordonne pas
            for e in sorted(edges, key=dist, reverse=True):
                if deg.get(e[0], 0) > 2 and deg.get(e[1], 0) > 2:
                    cur.discard(e)
                    removed = True
                    break
            if removed:
                break
        if not removed:
            break
    return list(cur)


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


def _order_cycle_vertices(node_set, graph) -> List[int]:
    """Reconstruit l'ordre cyclique des sommets d'un cycle simple.

    `minimum_cycle_basis` retourne juste l'ensemble des sommets ; pour dessiner
    le polygone il faut la sequence le long du cycle. On part d'un sommet
    quelconque et on suit l'arete qui reste dans node_set jusqu'a revenir au
    point de depart.
    """
    nodes = set(node_set)
    if not nodes:
        return []
    start = next(iter(nodes))
    ordered = [start]
    prev = None
    current = start
    while True:
        # Trouve le voisin de `current` qui est dans le cycle et pas le precedent
        nxt = None
        for v in graph.neighbors(current):
            if v in nodes and v != prev:
                nxt = v
                break
        if nxt is None or nxt == start:
            break
        ordered.append(nxt)
        prev = current
        current = nxt
        if len(ordered) > len(nodes):  # garde-fou
            break
    return ordered


def _compute_cycles_sssr(n_atoms: int,
                         bonds: List[Tuple[int, int]]) -> List["Cycle"]:
    """Calcule le SSSR via nx.minimum_cycle_basis et reconstruit l'ordre
    cyclique des sommets. Marque comme `anomaly` toute taille hors {5,6,7}.

    Pour un graphe planaire 2-connecte (cas standard des non-benzenoides),
    c'est mathematiquement equivalent aux faces internes du plongement.
    """
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(range(n_atoms))
    g.add_edges_from(bonds)
    try:
        basis = nx.minimum_cycle_basis(g)
    except (nx.NetworkXNoCycle, nx.NetworkXError):
        return []

    cycles: List[Cycle] = []
    for node_list in basis:
        ordered = _order_cycle_vertices(node_list, g)
        if len(ordered) < 3:
            continue
        cycles.append(Cycle(
            atoms=ordered,
            anomaly=(len(ordered) not in VALID_CYCLE_SIZES),
        ))
    return cycles


def _build_mol_graph_from_atoms(raw_atoms: List[Atom]) -> MolGraph:
    """Logique commune : a partir d'une liste d'atomes brute (C + H + ...),
    construit le squelette carbone + bonds + cycles. Partagee entre
    build_mol_graph(path) et build_mol_graph_from_text(text).
    """
    if not raw_atoms:
        return MolGraph()

    carbons, _old_to_new = filter_carbons(raw_atoms)

    # Etape 1 : detection brute par seuil de distance (genereux, 2.10 A).
    bonds = detect_bonds(carbons, only_cc=True)
    if not bonds:
        return MolGraph(atoms=carbons, bonds=[], cycles=[])

    # Etape 2 : k-NN mutuel -> borne chaque atome a 3 voisins, supprime les
    # diagonales captees par le seuil large (elimine la sur-coordination).
    bonds = mutual_knn_filter(carbons, bonds)

    # Etape 3 : retrait des cordes des 3/4-cycles parasites, sans jamais
    # sous-coordonner un atome. Cible la geometrie deformee a l'interface 5/7.
    cleaned_bonds = prune_small_cycle_diagonals(carbons, bonds)
    if not cleaned_bonds:
        # Garde-fou : ne jamais retourner un squelette vide si on avait des bonds.
        cleaned_bonds = bonds

    # Etape 4 : SSSR final sur le graphe nettoye. Tout cycle hors {5,6,7}
    # est conserve mais flagge anomaly=True (signal visuel cote viewer).
    cycles_final = _compute_cycles_sssr(len(carbons), cleaned_bonds)

    return MolGraph(atoms=carbons, bonds=cleaned_bonds, cycles=cycles_final)


def build_mol_graph(xyz_path) -> MolGraph:
    """Charge un XYZ depuis un fichier, garde uniquement les C, construit
    liaisons + cycles.

    Workflow :
      1. Detection des bonds C-C par seuil de distance (1.20-2.10 A).
      2. k-NN mutuel (k=3) : borne chaque carbone a ses 3 plus proches
         voisins mutuels -> elimine les diagonales captees par le seuil
         large (supprime la sur-coordination), sans retirer de vraie liaison.
      3. prune_small_cycle_diagonals : retire la corde (arete la plus longue)
         de tout 3/4-cycle parasite, sans jamais sous-coordonner un atome.
      4. SSSR final via nx.minimum_cycle_basis -> faces 5/6/7. Tout cycle
         hors {5,6,7} est conserve mais flagge `anomaly=True`.
    """
    return _build_mol_graph_from_atoms(read_xyz(Path(xyz_path)))


def build_mol_graph_from_text(xyz_text: str) -> MolGraph:
    """Idem build_mol_graph mais depuis une string xyz (ex. contenu lu depuis
    la DB plutot que depuis le filesystem). Utile pour le mode "DB-backed"
    du viewer ou les xyz sont stockes embarques dans la table xyz_files.
    """
    return _build_mol_graph_from_atoms(read_xyz_text(xyz_text))
