"""
Phase C : Assemblage du MolecularGraph et export XYZ.

Prend la topologie (sommets, liaisons, cycles) et les coordonnees
pour construire un MolecularGraph complet, resoudre les valences
(doubles liaisons + hydrogenes), et exporter en format XYZ.
"""

from reconstruction.topology import CycleTopology
from reconstruction.placement import CyclePlacer

from csp_solver.primitives.topology import MolecularGraph, Cycle
from csp_solver.primitives.valence import ValenceSolver


def build_molecular_graph(topo: CycleTopology, placer: CyclePlacer) -> MolecularGraph:
    """Construit le MolecularGraph a partir de la topologie et des coordonnees.

    1. Cree les atomes de carbone avec leurs coordonnees 2D (z=0)
    2. Ajoute toutes les liaisons C-C (ordre 1)
    3. Enregistre les cycles (necessaires pour ValenceSolver)
    4. Appelle ValenceSolver pour les doubles liaisons et les hydrogenes

    Args:
        topo: CycleTopology apres build() — fournit vertex_set, bond_set, cycle_vertices
        placer: CyclePlacer apres build() — fournit coords

    Returns:
        MolecularGraph complet avec C, H, liaisons simples et doubles
    """
    mol = MolecularGraph()

    # Mapping label -> vertex id dans le MolecularGraph
    label_to_id: dict[str, int] = {}

    # Ajouter tous les carbones dans un ordre CANONIQUE (sorted) pour garantir
    # que la geometrie 3D produite ne depend que de (graph, solution) et pas
    # de l'ordre d'iteration sur le set. Sans tri, Python randomise le hash
    # des strings entre processus (PYTHONHASHSEED), donc 2 lancements
    # successifs de main.py donnent des ordres d'atomes differents -> meme
    # geometrie modulo permutation, mais xTB MD est sensible a l'ordre des
    # atomes (vitesses initiales + accumulation des forces) et converge vers
    # des minima differents. Bug observe sur h6 avec ecart d'angle > 11 deg
    # entre runs cense identiques.
    for label in sorted(topo.vertex_set):
        x, y = placer.coords[label]
        vid = mol.add_vertex("C", x, y, 0.0)
        label_to_id[label] = vid

    # Ajouter toutes les liaisons C-C dans un ordre canonique aussi (les bonds
    # sont des frozenset donc indeterministes a l'iteration ; on les serialise
    # comme tuples tries pour avoir un ordre stable).
    for bond in sorted(topo.bond_set, key=lambda b: tuple(sorted(b))):
        labels = sorted(bond)
        a, b = labels[0], labels[1]
        if a in label_to_id and b in label_to_id:
            mol.add_bond(label_to_id[a], label_to_id[b], order=1)

    # Enregistrer les cycles (necessaires pour le placement des doubles liaisons)
    for v_idx in sorted(topo.cycle_vertices.keys()):
        verts = topo.cycle_vertices[v_idx]
        ids = [label_to_id[label] for label in verts]
        mol.cycles.append(Cycle(vertices=ids, size=len(ids)))

    # Resoudre les valences : doubles liaisons + hydrogenes
    solver = ValenceSolver(mol)
    solver.solve()

    return mol


def export_xyz(mol: MolecularGraph, filepath: str, comment: str = ""):
    """Exporte le MolecularGraph au format XYZ.

    Args:
        mol: MolecularGraph complet (C + H)
        filepath: chemin du fichier de sortie
        comment: ligne de commentaire dans le fichier XYZ
    """
    atoms = sorted(mol.vertices.values(), key=lambda v: v.id)
    with open(filepath, "w") as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"{comment}\n")
        for a in atoms:
            f.write(f"{a.element:<2s}  {a.x:14.5f}  {a.y:14.5f}  {a.z:14.5f}\n")
