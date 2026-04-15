"""
Reconstruction de la molecule complete a partir du benzenoide + solution CSP.

Pipeline :
1. Partir du graphe de carbone du benzenoide (coordonnees hexagonales)
2. Convertir en coordonnees cartesiennes 2D (z=0)
3. Appliquer les substitutions (retirer/ajouter un carbone par cycle modifie)
4. Placer les hydrogenes
5. Exporter en XYZ
6. Valider avec xTB + planarite
"""

import sys
import math
import shutil
import importlib.util
from pathlib import Path

from utils.parser import BenzenoidGraph, count_zero_blocks
from utils.validate import validate_xyz

# Import du generateur via chemin absolu (evite conflit avec le package utils/ local)
_gen_root = Path(__file__).parent.parent.parent / "non_benzenoid_generator"


# Ajouter le generateur au path pour que ses imports internes (from core.X) marchent
_gen_str = str(_gen_root)
if _gen_str not in sys.path:
    sys.path.insert(0, _gen_str)

from core.topology import MolecularGraph
from core.valence_solver import ValenceSolver


# ===================================================================
# Coordonnees hexagonales → cartesiennes
# ===================================================================

# Dans le reseau hexagonal, les sommets sont identifies par x_y.
# Le systeme de coordonnees hexagonales utilise deux axes :
#   axe 1 (horizontal) : direction (1, 0)
#   axe 2 (diagonal)   : direction (cos(60°), sin(60°)) = (0.5, sqrt(3)/2)
# Distance C-C = 1.42 A

BOND_CC = 1.42


def hex_to_cartesian(label: str) -> tuple:
    """Convertit un identifiant hexagonal 'x_y' en coordonnees (X, Y, 0)."""
    parts = label.split("_")
    hx = int(parts[0])
    hy = int(parts[1])
    # Vecteurs de base du reseau hexagonal
    x = BOND_CC * (hx + hy * 0.5)
    y = BOND_CC * (hy * math.sqrt(3) / 2)
    return (x, y, 0.0)


# ===================================================================
# Reconstruction de la molecule
# ===================================================================

def reconstruct_molecule(graph: BenzenoidGraph, solution: dict) -> MolecularGraph:
    """Reconstruit la molecule complete a partir du benzenoide et de la solution CSP.

    Args:
        graph: BenzenoidGraph depuis parser.py
        solution: dict {v: taille} depuis le solveur CSP

    Returns:
        MolecularGraph avec tous les atomes et liaisons
    """
    mol = MolecularGraph()

    # --- Etape 1 : Placer tous les carbones du benzenoide original ---
    # Mapping : label hexagonal -> vertex id dans le MolecularGraph
    label_to_id = {}

    # Collecter tous les sommets uniques depuis les hexagones
    all_labels = set()
    for hex_verts in graph.hexagons:
        for label in hex_verts:
            all_labels.add(label)

    for label in all_labels:
        x, y, z = hex_to_cartesian(label)
        vid = mol.add_vertex("C", x, y, z)
        label_to_id[label] = vid

    # --- Etape 2 : Ajouter les liaisons C-C du benzenoide ---
    for s1, s2 in graph.edges:
        if s1 in label_to_id and s2 in label_to_id:
            mol.add_bond(label_to_id[s1], label_to_id[s2], order=1)

    # --- Etape 3 : Appliquer les substitutions ---
    for v_idx in range(graph.h):
        target_size = solution[v_idx]
        hex_verts = graph.hexagons[v_idx]
        current_size = len(hex_verts)

        if target_size == current_size:
            continue  # Pas de changement

        pattern = graph.patterns[v_idx]

        if target_size == current_size - 1:
            # Pentagone : retirer un carbone du bloc d'aretes libres
            _remove_carbon(mol, hex_verts, pattern, label_to_id)
        elif target_size == current_size + 1:
            # Heptagone : ajouter un carbone dans le bloc d'aretes libres
            _add_carbon(mol, hex_verts, pattern, label_to_id)

    # --- Etape 4 : Placer les hydrogenes ---
    solver = ValenceSolver(mol)
    solver.solve()

    return mol


def _get_free_block(hex_verts: list, pattern: tuple) -> list:
    """Retourne les indices du bloc d'aretes libres (b=1, bloc consecutif).

    Les aretes libres sont les cotes i ou pattern[i]=0.
    Le cote i est l'arete entre hex_verts[i] et hex_verts[(i+1) % n].
    """
    n = len(hex_verts)
    free_edges = [i for i in range(n) if pattern[i] == 0]
    return free_edges


def _remove_carbon(mol: MolecularGraph, hex_verts: list, pattern: tuple,
                   label_to_id: dict):
    """Retire un carbone au milieu du bloc d'aretes libres (hexagone → pentagone).

    On choisit le sommet qui est au milieu du bloc de cotes libres.
    Ce sommet n'est partage avec aucun voisin (il est sur le bord libre).
    """
    free_edges = _get_free_block(hex_verts, pattern)
    if not free_edges:
        return

    n = len(hex_verts)

    # Les sommets du bloc libre : pour chaque arete libre i, les sommets
    # sont hex_verts[i] et hex_verts[(i+1)%n]. On cherche les sommets
    # qui ne sont PAS partages avec d'autres cycles (= pas sur une arete partagee).
    # Le sommet au milieu du bloc libre est le meilleur candidat.
    mid_edge_idx = free_edges[len(free_edges) // 2]
    # Le sommet a retirer est celui entre deux aretes libres consecutives
    # C'est hex_verts[(mid_edge_idx + 1) % n] si cette arete et la precedente sont libres
    vertex_to_remove_label = hex_verts[(mid_edge_idx + 1) % n]

    vid = label_to_id.get(vertex_to_remove_label)
    if vid is None:
        return

    # Trouver les voisins de ce sommet dans le cycle
    prev_label = hex_verts[mid_edge_idx]
    next_label = hex_verts[(mid_edge_idx + 2) % n]

    prev_id = label_to_id.get(prev_label)
    next_id = label_to_id.get(next_label)

    if prev_id is None or next_id is None:
        return

    # Retirer le sommet et ses liaisons
    mol.remove_vertex(vid)
    del label_to_id[vertex_to_remove_label]

    # Reconnecter les voisins
    mol.add_bond(prev_id, next_id, order=1)


def _add_carbon(mol: MolecularGraph, hex_verts: list, pattern: tuple,
                label_to_id: dict):
    """Ajoute un carbone au milieu du bloc d'aretes libres (hexagone → heptagone).

    On coupe l'arete libre du milieu en inserant un nouveau sommet.
    """
    free_edges = _get_free_block(hex_verts, pattern)
    if not free_edges:
        return

    n = len(hex_verts)

    # Arete libre a couper : celle du milieu du bloc
    mid_edge_idx = free_edges[len(free_edges) // 2]
    v1_label = hex_verts[mid_edge_idx]
    v2_label = hex_verts[(mid_edge_idx + 1) % n]

    v1_id = label_to_id.get(v1_label)
    v2_id = label_to_id.get(v2_label)

    if v1_id is None or v2_id is None:
        return

    # Coordonnees du nouveau sommet : milieu de l'arete, decale vers l'exterieur
    v1 = mol.vertices[v1_id]
    v2 = mol.vertices[v2_id]
    mx = (v1.x + v2.x) / 2
    my = (v1.y + v2.y) / 2

    # Decaler vers l'exterieur du cycle (perpendiculaire a l'arete)
    dx = v2.x - v1.x
    dy = v2.y - v1.y
    length = math.sqrt(dx*dx + dy*dy)
    if length > 0:
        # Normale vers l'exterieur
        nx_dir = -dy / length
        ny_dir = dx / length
        # Decalage d'environ la moitie de la longueur de liaison
        mx += nx_dir * BOND_CC * 0.5
        my += ny_dir * BOND_CC * 0.5

    # Creer le nouveau sommet
    new_id = mol.add_vertex("C", mx, my, 0.0)

    # Retirer l'ancienne liaison v1-v2
    mol.remove_bond(v1_id, v2_id)

    # Ajouter les deux nouvelles liaisons
    mol.add_bond(v1_id, new_id, order=1)
    mol.add_bond(new_id, v2_id, order=1)


# ===================================================================
# Export XYZ
# ===================================================================

def export_xyz(mol: MolecularGraph, filepath: str, comment: str = ""):
    """Exporte le MolecularGraph au format XYZ."""
    atoms = sorted(mol.vertices.values(), key=lambda v: v.id)
    with open(filepath, 'w') as f:
        f.write(f"{len(atoms)}\n")
        f.write(f"{comment}\n")
        for a in atoms:
            f.write(f"{a.element:<2s}  {a.x:14.5f}  {a.y:14.5f}  {a.z:14.5f}\n")


# ===================================================================
# Pipeline complet : reconstruction + validation
# ===================================================================

def reconstruct_and_validate(graph: BenzenoidGraph, solutions: list,
                             threshold=10.0, opt_level="tight"):
    """Pour chaque solution CSP, reconstruit la molecule et la valide.

    Args:
        graph: BenzenoidGraph
        solutions: liste de dicts {v: taille}
        threshold: seuil de planarite en degres
        opt_level: niveau de convergence xTB
    """
    output_dir = Path(__file__).parent.parent / "output" / "molecules"

    # Nettoyer
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Verifier xtb
    if not shutil.which("xtb"):
        print("ERREUR : xtb non trouve dans le PATH.")
        return

    results = []

    for i, sol in enumerate(solutions, 1):
        sol_str = " ".join(f"v{v}={sol[v]}" for v in sorted(sol.keys()))
        substituted = [v for v in sorted(sol.keys()) if sol[v] != 6]

        print(f"\n--- Solution {i}/{len(solutions)} : {sol_str} ---")

        if not substituted:
            print("  Tous hexagones, pas de reconstruction necessaire.")
            results.append({'index': i, 'planar': True, 'message': 'Tout hexagonal'})
            continue

        # Reconstruction
        try:
            mol = reconstruct_molecule(graph, sol)
        except Exception as e:
            print(f"  ERREUR reconstruction : {e}")
            results.append({'index': i, 'planar': False, 'message': f'Erreur: {e}'})
            continue

        # Export XYZ
        sizes_str = "_".join(str(sol[v]) for v in sorted(sol.keys()))
        xyz_path = output_dir / f"sol_{i}_{sizes_str}.xyz"
        export_xyz(mol, str(xyz_path), comment=f"Solution {i}: {sol_str}")
        print(f"  XYZ genere : {xyz_path.name}")

        # Validation xTB + planarite
        result = validate_xyz(str(xyz_path), threshold=threshold,
                              opt_level=opt_level)
        print(f"  Resultat : {result['message']}")
        if result.get('angle_deg', 0) > 0:
            print(f"  Angle max : {result['angle_deg']:.2f} deg")

        result['index'] = i
        result['solution'] = sol
        results.append(result)

    # Resume
    n_valid = sum(1 for r in results if r.get('planar', False))
    n_invalid = sum(1 for r in results if not r.get('planar', False))
    print(f"\n=== Resume validation globale ===")
    print(f"Solutions testees : {len(results)}")
    print(f"Planes (valides)  : {n_valid}")
    print(f"Non planes        : {n_invalid}")

    return results
